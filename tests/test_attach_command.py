"""`swarmbox-attach`: the session of each terminal tab, the idle window and the
`swarmbox <command>` mechanism: detached window, wait-for channel, status file, exit codes, no-terminal path.

Three layers, all against container/scripts/swarmbox-attach.sh:
  1. A FAKE tmux (python, recording) first on PATH: argument construction, quoting, exit-code mapping, fallback poll,
     not-ready exit 6, no-terminal path. Nothing real runs.
  2. REAL tmux, ISOLATED: every call goes through IsoTmux, which forces `-L swarmbox-test-<random> -f /dev/null`, a private
     TMUX_TMPDIR and no TMUX variable, and refuses a call without -L (tested). The server is killed only by that exact -L name.
     The live server (`tmux ls` shows main and main-1) is never addressed.
  3. The entrypoint's `attach` subcommand forwards to swarmbox-attach.

A terminal is a pty made by the test (the grouped tmux client needs one). HOME, the run folder and the shell fragment are
mktemp directories. Test-only variables: SWARMBOX_TEST_LIB, SWARMBOX_TEST_RUN_DIR,
SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60), SWARMBOX_TEST_POLL_INTERVAL (seconds, default 1), SWARMBOX_TEST_FRAGMENT.

Run with: python3 tests/test_attach_command.py   (needs bash and, for layer 2, tmux)
"""
import fcntl
import json
import os
import pty
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_NAME  # noqa: E402

ATTACH = os.path.join(ROOT, "container", "scripts", "swarmbox-attach.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
REAL_TMUX = shutil.which("tmux")

FAKE_TMUX = r'''#!/usr/bin/env python3
import json, os, sys, time
d = os.environ["FAKE_DIR"]
argv = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(argv) + "\n")
def mode(name, default=""):
    p = os.path.join(d, name)
    return open(p).read().strip() if os.path.exists(p) else default
def windows():
    p = os.path.join(d, "windows.txt")
    return [l for l in open(p).read().splitlines() if l] if os.path.exists(p) else []
def save(rows):
    open(os.path.join(d, "windows.txt"), "w").write("".join(r + "\n" for r in rows))
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None
sub = argv[0] if argv else ""
if sub == "has-session":
    sys.exit(1 if mode("no-session") else 0)
if sub == "show-options":
    p = os.path.join(d, "show-options.txt")
    if "@sb_order" in argv and os.path.exists(p):
        print(open(p).read().strip())
    sys.exit(0)
if sub == "list-windows" and "@sb_tab" in (opt("-F") or ""):
    p = os.path.join(d, "owners.txt")
    if os.path.exists(p):
        print(open(p).read().strip())
    sys.exit(0)
if sub == "list-windows":
    fmt = opt("-F") or ""
    for row in windows():
        print(row if "window_name" in fmt else row.split("|")[0])
    sys.exit(0)
if sub == "new-window":
    wid = mode("next-id", "@7")
    st = mode("status", "")
    if "wrapper" in argv:
        i = argv.index("wrapper")
        q, status, chan = argv[i + 1], argv[i + 2], argv[i + 3]
        if st != "":
            open(status, "w").write(st + "\n")
    if mode("window") != "vanishes":
        save(windows() + [wid + "|bash|bash|1"])
    if "-P" in argv:
        print(wid)
    sys.exit(int(mode("new-window-exit", "0")))
if sub == "wait-for":
    if "-S" in argv:
        sys.exit(0)
    if mode("waitfor") == "block":
        time.sleep(60)
    sys.exit(0)
if sub == "kill-window":
    t = opt("-t")
    save([r for r in windows() if r.split("|")[0] != t])
    sys.exit(0)
if sub == "display-message":
    print(mode("next-id", "@7"))
    sys.exit(0)
if sub == "link-window":
    if "-b" in argv and os.path.exists(os.path.join(d, "link-before-fails")):
        sys.exit(1)
    save(windows() + [opt("-s") + "|bash|bash|1"])
    sys.exit(0)
if sub == "attach-session":
    sys.exit(0)
if sub == "new-session":
    if "-t" in argv and mode("client") == "block":
        end = time.time() + 30
        while time.time() < end and not os.path.exists(os.path.join(d, "kill-session-called")):
            time.sleep(0.05)
    sys.exit(0)
if sub == "kill-session":
    open(os.path.join(d, "kill-session-called"), "w").write("x")
    sys.exit(0)
sys.exit(0)
'''

FRAGMENT = r'''case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return;; esac
alias greet='sh -c '"'"'echo "$@" > "$OUT_DIR/alias_out"'"'"' x --auto-approve'
export PATH="$HOME/bin:$PATH"
'''


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


# ----------------------------------------------------------------------------------------------------------------------
# The isolated real tmux. Every call to a real tmux in this file goes through checked_tmux_argv.
# ----------------------------------------------------------------------------------------------------------------------
def checked_tmux_argv(argv):
    """Refuse a real-tmux call that is not isolated: it must start with -L swarmbox-test-<name> (and -f /dev/null)."""
    argv = list(argv)
    if len(argv) < 5 or argv[1] != "-L" or not argv[2].startswith("swarmbox-test-") or argv[3:5] != ["-f", "/dev/null"]:
        raise ValueError("refusing a tmux call without -L swarmbox-test-<name> -f /dev/null: %r" % (argv,))
    if "-S" in argv or any(a in ("kill-server",) for a in argv[5:]) and argv[2] == "main":
        raise ValueError("refusing: %r" % (argv,))
    return argv


class IsoTmux:
    def __init__(self):
        self.name = "swarmbox-test-" + secrets.token_hex(4)
        self.tmpdir = tempfile.mkdtemp(prefix="sbt-tmux-")
        self.shim_dir = tempfile.mkdtemp(prefix="sbt-shim-")
        # the shim is what swarmbox-attach (and the windows it creates) find as `tmux`
        write_exec(os.path.join(self.shim_dir, "tmux"),
                   '#!/bin/sh\nunset TMUX\nTMUX_TMPDIR=%s\nexport TMUX_TMPDIR\nexec %s -L %s -f /dev/null "$@"\n'
                   % (self.tmpdir, REAL_TMUX, self.name))

    def env(self):
        e = {k: v for k, v in os.environ.items() if k != "TMUX"}
        e["TMUX_TMPDIR"] = self.tmpdir
        return e

    def run(self, *args, check=False):
        argv = checked_tmux_argv([REAL_TMUX, "-L", self.name, "-f", "/dev/null"] + list(args))
        r = subprocess.run(argv, env=self.env(), capture_output=True, text=True, timeout=30)
        if check and r.returncode != 0:
            raise AssertionError("tmux %r failed: %s" % (args, r.stderr))
        return r

    def close(self):
        try:
            self.run("kill-server")  # only this -L name
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            shutil.rmtree(self.shim_dir, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------------------------
# A pty as the terminal
# ----------------------------------------------------------------------------------------------------------------------
class PtyProc:
    def __init__(self, argv, env, cwd=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))

        def pre():
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        self.p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
                                  start_new_session=True, preexec_fn=pre, close_fds=True)
        os.close(slave)
        os.set_blocking(self.master, False)
        self.out = b""

    def pump(self):
        try:
            while True:
                b = os.read(self.master, 65536)
                if not b:
                    break
                self.out += b
        except (BlockingIOError, OSError):
            pass

    def write(self, data):
        os.write(self.master, data)

    def wait(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            self.pump()
            rc = self.p.poll()
            if rc is not None:
                self.pump()
                return rc
            time.sleep(0.05)
        raise AssertionError("timeout waiting for %r; output so far: %r" % (self.p.args, self.out[-500:]))

    def alive(self):
        return self.p.poll() is None

    def close(self):
        if self.p.poll() is None:  # only the PID this test started
            try:
                self.p.send_signal(signal.SIGHUP)
                self.p.wait(timeout=5)
            except Exception:
                self.p.kill()
                self.p.wait()
        try:
            os.close(self.master)
        except OSError:
            pass


def wait_until(fn, seconds=15, step=0.1):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def bash_words(q):
    """What bash makes of the quoted string `q`: the argument list, NUL separated."""
    r = subprocess.run(["bash", "-c", 'eval "set -- $1"; printf "%s\\0" "$@"', "bash", q], capture_output=True)
    out = r.stdout.decode("utf-8", "surrogateescape")
    return out.split("\0")[:-1] if out else []


AWKWARD = ["a b", "it's", "$HOME", '"dq"', "a\\b", "*", "line1\nline2", "", "-n", "~", "`id`", ";touch /tmp/pwned", "&", "!x",
           "é", "tab\there", "  lead and trail  "]


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="attach-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.fake = os.path.join(self.base, "fake")
        self.lib = os.path.join(self.base, "lib")
        self.home = os.path.join(self.base, "home")
        self.run_dir = os.path.join(self.base, "run")
        self.out_dir = os.path.join(self.base, "out")
        for d in (self.fake, self.lib, self.home, self.run_dir, self.out_dir, os.path.join(self.home, "bin")):
            os.makedirs(d, exist_ok=True)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        self.fragment = os.path.join(self.base, "bashrc.sh")
        with open(self.fragment, "w") as f:
            f.write(FRAGMENT)
        self.ptys = []
        self.addCleanup(self._close_ptys)
        self.mark_ready()

    def _close_ptys(self):
        for p in self.ptys:
            p.close()

    def mark_ready(self, text="ok"):
        with open(os.path.join(self.run_dir, "ready"), "w") as f:
            f.write(text + "\n")

    def not_ready(self):
        os.unlink(os.path.join(self.run_dir, "ready"))

    def env(self, path_dir, **extra):
        env = {"PATH": path_dir + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "HOME": self.home, "FAKE_DIR": self.fake,
               "SWARMBOX_TEST_LIB": self.lib, "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_FRAGMENT": self.fragment,
               "SWARMBOX_TEST_READY_TIMEOUT": "2", "SWARMBOX_TEST_POLL_INTERVAL": "0.2", "OUT_DIR": self.out_dir,
               "LANG": "C.UTF-8", "TERM": "xterm-256color", "SHELL": "/bin/bash"}
        env.update({k: v for k, v in extra.items() if v is not None})
        return env

    def run_noterm(self, path_dir, args, timeout=30, **extra):
        return subprocess.run(["bash", ATTACH] + list(args), env=self.env(path_dir, **extra), stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout, cwd=self.base)

    def run_term(self, path_dir, args, **extra):
        p = PtyProc(["bash", ATTACH] + list(args), self.env(path_dir, **extra), cwd=self.base)
        self.ptys.append(p)
        return p

    def out(self, name):
        p = os.path.join(self.out_dir, name)
        return open(p).read() if os.path.exists(p) else None


# ----------------------------------------------------------------------------------------------------------------------
# Layer 0: the guard of the isolated helper
# ----------------------------------------------------------------------------------------------------------------------
class IsolationHelper(unittest.TestCase):
    def test_the_helper_refuses_calls_without_l(self):
        for bad in (["tmux", "ls"], ["tmux", "-S", "/tmp/x", "ls"], ["tmux", "-L", "main", "-f", "/dev/null", "ls"],
                    ["tmux", "-L", "swarmbox-test-x", "ls"], ["tmux", "-L", "swarmbox-test-x", "-f", "/etc/tmux.conf", "ls"],
                    ["tmux"], []):
            with self.assertRaises(ValueError, msg=bad):
                checked_tmux_argv(bad)
        checked_tmux_argv(["tmux", "-L", "swarmbox-test-ab12", "-f", "/dev/null", "ls"])

    @unittest.skipUnless(REAL_TMUX, "needs tmux")
    def test_iso_run_uses_a_private_socket_and_never_the_live_one(self):
        iso = IsoTmux()
        self.addCleanup(iso.close)
        iso.run("new-session", "-d", "-s", "probe", check=True)
        self.assertIn("probe", iso.run("ls").stdout)
        self.assertNotIn("TMUX", iso.env())
        self.assertTrue(os.path.exists(os.path.join(iso.tmpdir, "tmux-%d" % os.getuid(), iso.name)))


# ----------------------------------------------------------------------------------------------------------------------
# Layer 1: fake tmux
# ----------------------------------------------------------------------------------------------------------------------
class FakeTmuxCase(Base):
    def setUp(self):
        super().setUp()
        write_exec(os.path.join(self.fake, "tmux"), FAKE_TMUX)
        self.assertEqual(shutil.which("tmux", path=self.fake + os.pathsep + "/usr/bin"), os.path.join(self.fake, "tmux"))

    def calls(self):
        p = os.path.join(self.fake, "calls.jsonl")
        return [json.loads(l) for l in open(p).read().splitlines()] if os.path.exists(p) else []

    def put(self, name, text):
        with open(os.path.join(self.fake, name), "w") as f:
            f.write(text)

    def subs(self, name):
        return [c for c in self.calls() if c and c[0] == name]


class ReadinessTests(FakeTmuxCase):
    def test_not_ready_exits_6_after_the_timeout_and_never_calls_tmux(self):
        self.not_ready()
        t0 = time.time()
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="1")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertGreaterEqual(time.time() - t0, 0.9)
        self.assertLess(time.time() - t0, 10)
        self.assertIn(b"not ready", r.stderr)
        self.assertIn(b"podman logs", r.stderr)
        self.assertEqual(self.calls(), [])

class InteractiveAttachFakeTests(FakeTmuxCase):
    def test_a_terminal_tab_gets_a_session_of_its_own_with_its_window_linked_into_main(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, [])
        self.assertEqual(p.wait(), 0)
        calls = self.calls()
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds[0], "has-session")
        self.assertIn("=main", calls[0])
        self.assertEqual(self.subs("new-window"), [], "the window is made by new-session, in the session of the tab")
        ns = self.subs("new-session")[0]
        self.assertIn("-d", ns)
        name = ns[ns.index("-s") + 1]
        self.assertTrue(name.startswith("swarmbox-tab-"), name)
        self.assertIn(self.base, ns)  # -c <cwd of the caller>
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-s") + 1], "@7", "the window id read back from the tab's session")
        self.assertEqual(link[link.index("-t") + 1], "=main:{end}")
        self.assertIn("-a", link)
        self.assertIn("-d", link)
        self.assertEqual(self.subs("kill-window")[0][-1], "@0", "the idle window of serve is closed")
        att = self.subs("attach-session")[0]
        flat = " ".join(att)
        self.assertIn("-t =" + name, flat)
        self.assertIn("set-option destroy-unattached on", flat)
        self.assertIn("set-option status off", flat)
        self.assertEqual(att.count(";"), 2)  # two chained commands
        # the order matters: the window is linked into main before the idle one goes, so main never ends up with no window
        self.assertLess(kinds.index("link-window"), kinds.index("kill-window"))
        self.assertLess(kinds.index("kill-window"), kinds.index("attach-session"))
        self.assertFalse(any("@sb_tab" in " ".join(c) or "@sb_order" in " ".join(c) for c in calls), "no key given: nothing is recorded")

    def test_a_key_is_recorded_on_the_window_and_in_the_order_and_a_new_tab_goes_to_the_end(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        calls = self.calls()
        owner = [c for c in calls if c[:1] == ["set-option"] and "@sb_tab" in c][0]
        self.assertEqual(owner, ["set-option", "-w", "-t", "@7", "@sb_tab", "/dev/pts/9"])
        order = [c for c in calls if c[:1] == ["set-option"] and "@sb_order" in c][0]
        self.assertEqual(order, ["set-option", "-g", "@sb_order", "/dev/pts/9"])
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-t") + 1], "=main:{end}", "a tab the box has not seen goes to the end")
        self.assertIn("-a", link)

    def test_a_known_key_goes_before_the_first_window_of_a_later_tab_and_the_target_names_the_session(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.put("show-options.txt", "/dev/pts/9 /dev/pts/10\n")
        self.put("owners.txt", "@3|/dev/pts/10\n")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-t") + 1], "=main:@3", "before the window of the later tab, named with the session")
        self.assertIn("-b", link)
        self.assertNotIn("-a", link)
        self.assertEqual([c for c in self.calls() if c[:1] == ["set-option"] and "@sb_order" in c], [], "the key was already in the order")

    def test_if_the_anchor_window_cannot_be_used_the_window_goes_to_the_end(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.put("show-options.txt", "/dev/pts/9 /dev/pts/10\n")
        self.put("owners.txt", "@3|/dev/pts/10\n")
        self.put("link-before-fails", "x")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        links = self.subs("link-window")
        self.assertEqual(len(links), 2)
        self.assertIn("-b", links[0])
        self.assertEqual(links[1][links[1].index("-t") + 1], "=main:{end}")

    def test_web_attaches_to_the_session_itself_so_the_status_bar_stays(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, ["--web"])
        self.assertEqual(p.wait(), 0)
        self.assertEqual(self.subs("new-window"), [])
        att = self.subs("attach-session")[0]
        self.assertIn("=main", att)
        flat = " ".join(" ".join(c) for c in self.calls())
        self.assertNotIn("status off", flat)
        self.assertNotIn("destroy-unattached", flat)


class CommandFakeTests(FakeTmuxCase):
    def setUp(self):
        super().setUp()
        self.put("client", "block")

    def attach(self, args, status="0", **extra):
        if status is not None:
            self.put("status", str(status))
        p = self.run_term(self.fake, args, **extra)
        return p, p.wait()

    def test_window_arguments_and_the_quoted_command_string(self):
        args = ["printf", "%s\n"] + AWKWARD
        p, rc = self.attach(args)
        self.assertEqual(rc, 0, p.out)
        (nw,) = self.subs("new-window")
        i = nw.index("bash")
        self.assertEqual(nw[i:i + 2][0], "bash")
        self.assertEqual(nw[i + 1], "-c")
        self.assertEqual(nw[i + 3], "wrapper")  # the wrapper takes the next three as separate arguments, no extra quoting layer
        q, status, chan = nw[i + 4:i + 7]
        self.assertEqual(bash_words(q), args)  # byte for byte after one level of shell parsing
        self.assertTrue(status.startswith(self.run_dir + "/exit."))
        self.assertTrue(chan.startswith("swarmbox-"))
        self.assertIn(chan[len("swarmbox-"):], status)
        self.assertIn("-d", nw)
        self.assertIn("-P", nw)
        self.assertIn("=main:", nw)
        wrapper = nw[i + 2]
        self.assertIn("bash -ic", wrapper)  # interactive shell: aliases and PATH apply
        for needle in ("trap", "HUP", "TERM", "129", "wait-for -S", "mv "):
            self.assertIn(needle, wrapper)
        self.assertFalse(os.path.exists("/tmp/pwned"))

    def test_no_terminal_runs_the_command_directly_without_tmux(self):
        r = self.run_noterm(self.fake, ["sh", "-c", "exit 9"])
        self.assertEqual(r.returncode, 9)
        self.assertEqual(self.calls(), [])
        r = self.run_noterm(self.fake, ["sh", "-c", "kill -TERM $$"])
        self.assertEqual(r.returncode, 143)

# ----------------------------------------------------------------------------------------------------------------------
# Layer 2: real tmux, isolated
# ----------------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(REAL_TMUX, "needs tmux")
class RealTmuxCase(Base):
    def setUp(self):
        super().setUp()
        self.iso = IsoTmux()
        self.addCleanup(self.iso.close)
        with open(os.path.join(self.home, ".bashrc"), "w") as f:
            f.write(FRAGMENT)
        write_exec(os.path.join(self.home, "bin", "mytool"), '#!/bin/sh\necho "mytool:$*" > "$OUT_DIR/path_out"\n')
        self.start_server()

    def start_server(self):
        # what serve step 9 does: env -u TMUX tmux new-session -d -s main -n idle  (through the shim: -L is forced)
        env = self.env(self.iso.shim_dir)
        env.pop("TMUX", None)
        r = subprocess.run(["tmux", "new-session", "-d", "-s", "main", "-n", "idle", "-x", "100", "-y", "30"], env=env,
                           capture_output=True, text=True, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def term(self, args, **extra):
        return self.run_term(self.iso.shim_dir, args, **extra)

    def windows(self, session="main"):
        r = self.iso.run("list-windows", "-t", "=" + session, "-F", "#{window_id}|#{window_name}|#{pane_current_command}")
        return [l.split("|") for l in r.stdout.splitlines() if l]

    def sessions(self):
        return self.iso.run("list-sessions", "-F", "#{session_name}").stdout.split()

    def tabs(self):
        return [x for x in self.sessions() if x.startswith("swarmbox-tab-")]

    def test_two_attach_calls_are_two_windows_of_main_each_in_a_session_of_its_own_and_the_idle_one_is_gone(self):
        self.assertEqual([w[1] for w in self.windows()], ["idle"])
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        w = self.windows()
        self.assertEqual(len(w), 1)
        self.assertNotEqual(w[0][1], "idle")  # the idle window is gone
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 3), b.out)
        self.assertEqual(len(self.windows()), 2, "main shows both tabs (the browser sees them as tabs)")
        self.assertNotIn("idle", [x[1] for x in self.windows()])
        # a session per tab: no status bar, one window each (not a group sharing every window), destroyed when the client goes
        for s in self.tabs():
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "status").stdout.strip(), "off")
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "destroy-unattached").stdout.strip(), "on")
            self.assertEqual(len(self.windows(s)), 1)
        self.assertNotEqual(self.iso.run("show-options", "-t", "=main", "-v", "status").stdout.strip(), "off")
        # closing a tab of the host terminal only detaches: its session goes, its window keeps running in main
        a.p.send_signal(signal.SIGHUP)
        a.close()
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2))
        self.assertEqual(len(self.windows()), 2)

    def test_exit_in_a_tab_leaves_the_box_and_does_not_jump_to_the_window_of_another_tab(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 2), b.out)
        self.assertEqual(len(self.windows()), 2)
        time.sleep(0.8)  # let the shell of tab A draw its prompt
        a.write(b"exit\r")
        self.assertEqual(a.wait(), 0, a.out)   # the client of A is gone: the user is back at the host shell
        self.assertTrue(b.alive(), "the other tab is untouched")
        self.assertTrue(wait_until(lambda: len(self.windows()) == 1), "the window of A is gone from main")
        self.assertEqual(len(self.tabs()), 1, "the session of A ended with its window")
        self.assertEqual(len(self.windows(self.tabs()[0])), 1)

    def test_exit_in_the_only_tab_ends_that_client_too(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        time.sleep(0.8)
        a.write(b"exit\r")
        self.assertEqual(a.wait(), 0, a.out)
        self.assertTrue(wait_until(lambda: self.tabs() == []), "no session of a finished tab is left")
        # main had no other window, so tmux ends it as it always did when the last window of a session goes; the next call makes it again
        # (the test below)

    # -- the place of a tab in main: the same host tab comes back to the same slot ------------------------------------------------------
    def owners(self):
        """The key of the host tab that owns each window of main, in the order the browser shows them ('' for a window nobody owns)."""
        return self.iso.run("list-windows", "-t", "=main", "-F", "#{@sb_tab}").stdout.split("\n")[:-1]

    def enter(self, key, expect):
        t = self.term([], **({"SWARMBOX_TAB": key} if key is not None else {}))
        self.assertTrue(wait_until(lambda: len(self.windows()) == expect), t.out)
        time.sleep(0.4)
        return t

    def leave(self, tab, expect):
        time.sleep(0.6)
        tab.write(b"exit\r")
        self.assertEqual(tab.wait(), 0, tab.out)
        self.assertTrue(wait_until(lambda: len(self.windows()) == expect))

    def test_a_tab_that_leaves_and_comes_back_returns_to_its_place_in_the_browser(self):
        k = ["/dev/pts/101", "/dev/pts/102", "/dev/pts/103"]
        t1 = self.enter(k[0], 1)
        t2 = self.enter(k[1], 2)
        t3 = self.enter(k[2], 3)
        self.assertEqual(self.owners(), k, "the order in which the tabs were opened")
        self.leave(t1, 2)                                    # exit in the tab on the LEFT
        self.assertEqual(self.owners(), k[1:])
        t1 = self.enter(k[0], 3)                             # and the same host tab comes back
        self.assertEqual(self.owners(), k, "back on the left, not at the end")
        self.leave(t2, 2)                                    # the one in the MIDDLE
        self.assertEqual(self.owners(), [k[0], k[2]])
        t2 = self.enter(k[1], 3)
        self.assertEqual(self.owners(), k, "back in the middle")
        self.leave(t3, 2)                                    # the last one: it goes to the end again
        t3 = self.enter(k[2], 3)
        self.assertEqual(self.owners(), k)

    def test_a_tab_without_a_key_goes_to_the_end_and_does_not_disturb_the_others(self):
        a = self.enter("/dev/pts/201", 1)
        self.enter(None, 2)                                  # an old host script, or a client that gave no key
        c = self.enter("/dev/pts/202", 3)
        self.assertEqual(self.owners(), ["/dev/pts/201", "", "/dev/pts/202"])
        self.leave(a, 2)
        self.enter("/dev/pts/201", 3)
        # What is kept is the order of the host tabs among themselves. Nothing records on which side of a returning tab a window with no owner
        # was, so it can end up on either side; the returning tab goes right before the next tab that has an owner.
        self.assertEqual([k for k in self.owners() if k], ["/dev/pts/201", "/dev/pts/202"])
        self.assertEqual(self.owners().count(""), 1, "the keyless window is still there")
        self.assertEqual(self.owners()[-2:], ["/dev/pts/201", "/dev/pts/202"])
        self.assertTrue(c.alive())

    def test_a_window_opened_from_the_browser_stays_and_the_host_tabs_keep_their_order(self):
        a = self.enter("/dev/pts/301", 1)
        self.iso.run("new-window", "-d", "-a", "-t", "=main:{end}", "sleep 600", check=True)   # Alt+N in the browser: no owner
        self.assertTrue(wait_until(lambda: len(self.windows()) == 2))
        self.enter("/dev/pts/302", 3)
        self.assertEqual(self.owners(), ["/dev/pts/301", "", "/dev/pts/302"])
        self.leave(a, 2)
        self.enter("/dev/pts/301", 3)
        self.assertEqual([k for k in self.owners() if k], ["/dev/pts/301", "/dev/pts/302"], "the host tabs keep their order")
        self.assertEqual(self.owners().count(""), 1, "the window from the browser is still there")

    def test_the_key_is_cleaned_before_it_is_kept(self):
        self.enter("a b;c$(id)", 1)
        self.assertEqual(self.owners(), ["a_b_c__id_"])
        self.assertEqual(self.iso.run("show-options", "-gqv", "@sb_order").stdout.strip(), "a_b_c__id_", "one word, so the list stays a list")

    def test_the_order_remembers_at_most_64_tabs_the_newest_ones(self):
        self.iso.run("set-option", "-g", "@sb_order", " ".join("old%d" % i for i in range(100)), check=True)
        self.enter("/dev/pts/401", 1)
        keys = self.iso.run("show-options", "-gqv", "@sb_order").stdout.split()
        self.assertEqual(len(keys), 64)
        self.assertEqual(keys[-1], "/dev/pts/401")
        self.assertEqual(keys[0], "old37")

    def test_a_tab_opened_after_another_one_ended_still_works(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        time.sleep(0.8)
        a.write(b"exit\r")
        a.wait()
        self.assertTrue(wait_until(lambda: self.tabs() == []))
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), b.out)
        self.assertEqual(len(self.windows()), 1)

    def test_the_last_screen_of_a_command_is_printed_after_its_window_closes(self):
        p = self.term(["echo", "output-of-the-command"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertIn(b"output-of-the-command", p.out.split(b"[exited]")[-1], p.out)

    def test_command_exit_codes_through_a_real_window(self):
        for args, want in ((["true"], 0), (["false"], 1), (["sh", "-c", "exit 130"], 130), (["sh", "-c", "exit 7"], 7),
                           (["sh", "-c", "kill -9 $$"], 137), (["sh", "-c", "kill -15 $$"], 143),
                           (["no-such-command-xyz"], 127)):
            with self.subTest(args=args):
                p = self.term(args)
                self.assertEqual(p.wait(), want, p.out)
        self.assertEqual([f for f in os.listdir(self.run_dir) if f.startswith("exit.")], [])
        self.assertEqual(self.sessions(), ["main"], "the sessions of finished calls must be gone")

# ----------------------------------------------------------------------------------------------------------------------
# Layer 3: the entrypoint's attach subcommand
# ----------------------------------------------------------------------------------------------------------------------
class EntrypointAttach(Base):
    def test_attach_forwards_every_argument_to_swarmbox_attach(self):
        write_exec(os.path.join(self.fake, "swarmbox-attach"),
                   '#!/usr/bin/env python3\nimport json, os, sys\nopen(os.environ["FAKE_DIR"] + "/args.json", "w").write(json.dumps(sys.argv[1:]))\nsys.exit(int(os.environ.get("FAKE_RC", "0")))\n')
        args = ["--plain"] + AWKWARD[:8]
        r = subprocess.run(["bash", ENTRYPOINT, "attach"] + args, env=self.env(self.fake, FAKE_RC="3"), capture_output=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(json.load(open(os.path.join(self.fake, "args.json"))), args)

class ServeCreatesTheIdleWindow(unittest.TestCase):
    def test_serve_step_9_names_the_idle_window(self):
        with open(ENTRYPOINT) as f:
            text = f.read()
        self.assertIn("new-session -d -s main -n idle", text)
        with open(ATTACH) as f:
            attach = f.read()
        self.assertIn("IDLE_NAME=idle", attach)


class Static(unittest.TestCase):
    def test_script_is_executable_bash_and_installed_by_the_dockerfile(self):
        self.assertTrue(os.path.isfile(ATTACH))
        with open(ATTACH) as f:
            self.assertTrue(f.readline().startswith("#!/bin/bash"))
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("COPY container/scripts/swarmbox-attach.sh /usr/local/bin/swarmbox-attach", d)
        self.assertIn("/usr/local/bin/swarmbox-attach", d.split("COPY container/entrypoint.sh")[1])  # chmod 755

if __name__ == "__main__":
    unittest.main()
