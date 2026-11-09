"""Slice 2.3: `swarmbox-attach` (design 3.3, 3.4, 4.2): the grouped session, the idle window (B36) and the
`swarmbox <command>` mechanism (B13): detached window, wait-for channel, status file, exit codes, no-terminal path.

Three layers, all against container/scripts/swarmbox-attach.sh:
  1. A FAKE tmux (python, recording) first on PATH: argument construction, quoting, exit-code mapping, fallback poll,
     not-ready exit 6, no-terminal path. Nothing real runs.
  2. REAL tmux, ISOLATED: every call goes through IsoTmux, which forces `-L swarmbox-test-<random> -f /dev/null`, a private
     TMUX_TMPDIR and no TMUX variable, and refuses a call without -L (tested). The server is killed only by that exact -L name.
     The live server (`tmux ls` shows main and main-1) is never addressed.
  3. The entrypoint's `attach` subcommand forwards to swarmbox-attach.

A terminal is a pty made by the test (the grouped tmux client needs one). HOME, the run folder and the shell fragment are
mktemp directories. Test-only variables (decision log [2.3]): SWARMBOX_TEST_LIB, SWARMBOX_TEST_RUN_DIR,
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

    def test_the_box_name_in_the_message_is_swarmbox_name_else_the_defaults_file(self):
        """D40: no literal name in the script: the helper's SWARMBOX_NAME, else the DEFAULTS file next to the helper copy."""
        self.not_ready()
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="1", SWARMBOX_NAME="other-box")
        self.assertIn(b"podman logs other-box` on the host", r.stderr)
        hd = os.path.join(self.base, "hostdir")
        os.makedirs(hd)
        for text, want in (("SWARMBOX_DEFAULT_NAME=flipped\n", b"podman logs flipped` on"),
                           ("SWARMBOX_DEFAULT_NAME='quoted'\n", b"podman logs quoted` on")):
            with open(os.path.join(hd, "DEFAULTS"), "w") as f:
                f.write(text)
            r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="1", SWARMBOX_TEST_HOST_DIR=hd)
            self.assertIn(want, r.stderr)
        shutil_rm = os.path.join(hd, "DEFAULTS")
        os.unlink(shutil_rm)
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="1", SWARMBOX_TEST_HOST_DIR=hd)
        self.assertIn(b"podman logs <box>` on", r.stderr)
        self.assertNotIn(b"No such file", r.stderr)
        with open(os.path.join(ROOT, "container", "host", "DEFAULTS")) as f:
            self.assertIn("SWARMBOX_DEFAULT_NAME=" + DEFAULT_NAME, f.read())

    def test_not_ready_with_a_terminal_also_exits_6(self):
        self.not_ready()
        p = self.run_term(self.fake, [], SWARMBOX_TEST_READY_TIMEOUT="1")
        self.assertEqual(p.wait(), 6)
        self.assertEqual(self.calls(), [])

    def test_a_marker_that_appears_while_waiting_is_accepted(self):
        self.not_ready()
        import threading
        threading.Timer(0.6, self.mark_ready).start()
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="5")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_warnings_marker_counts_as_ready(self):
        self.mark_ready("warnings=2")
        self.assertEqual(self.run_noterm(self.fake, ["true"]).returncode, 0)


class InteractiveAttachFakeTests(FakeTmuxCase):
    def test_the_grouped_session_without_status_bar_and_a_new_window(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, [])
        self.assertEqual(p.wait(), 0)
        kinds = [c[0] for c in self.calls()]
        self.assertEqual(kinds[0], "has-session")
        self.assertIn("=main", self.calls()[0])
        nw = self.subs("new-window")[0]
        self.assertIn("-d", nw)
        self.assertIn("=main:", nw)
        self.assertIn(self.base, nw)  # -c <cwd of the caller>
        ns = [c for c in self.subs("new-session") if "-t" in c][0]
        flat = " ".join(ns)
        self.assertIn("-t =main", flat)
        self.assertIn("set-option destroy-unattached on", flat)
        self.assertIn("set-option status off", flat)
        self.assertIn("select-window -t @7", flat)
        self.assertEqual(ns.count(";"), 3)  # three chained commands

    def test_the_idle_window_alone_is_closed_after_the_new_one_exists(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.run_term(self.fake, []).wait()
        order = [c[0] for c in self.calls()]
        self.assertEqual([c for c in self.subs("kill-window")][0][-2:], ["-t", "@0"])
        self.assertLess(order.index("new-window"), order.index("kill-window"))

    def test_the_idle_window_is_kept_when_it_is_not_alone_or_not_idle(self):
        for rows in ("@0|idle|bash|1\n@1|bash|bash|1\n",   # another window exists
                     "@0|idle|vim|1\n",                    # something runs in it (the user typed)
                     "@0|idle|bash|2\n",                   # the user split it
                     "@0|work|bash|1\n",                   # renamed, or a window the user made
                     "@0|bash|bash|1\n"):
            with self.subTest(rows=rows):
                os.unlink(os.path.join(self.fake, "calls.jsonl")) if os.path.exists(os.path.join(self.fake, "calls.jsonl")) else None
                self.put("windows.txt", rows)
                self.run_term(self.fake, []).wait()
                self.assertEqual(self.subs("kill-window"), [])
                self.assertEqual(len(self.subs("new-window")), 1)

    def test_a_missing_session_is_created_with_the_idle_window_first(self):
        self.put("no-session", "1")
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.run_term(self.fake, []).wait()
        creates = [c for c in self.subs("new-session") if "-d" in c]
        self.assertEqual(len(creates), 1)
        self.assertIn("-n", creates[0])
        self.assertEqual(creates[0][creates[0].index("-n") + 1], "idle")
        self.assertIn("main", creates[0])

    def test_no_command_and_no_terminal_gives_a_plain_shell_not_tmux(self):
        r = subprocess.run(["bash", ATTACH], env=self.env(self.fake), stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])


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

    def test_the_grouped_client_is_selected_on_the_command_window_and_ended_by_name(self):
        self.attach(["true"])
        ns = [c for c in self.subs("new-session") if "-t" in c][0]
        flat = " ".join(ns)
        self.assertIn("select-window -t @7", flat)
        self.assertIn("set-option status off", flat)
        self.assertIn("-s swarmbox-cmd-", flat)
        name = ns[ns.index("-s") + 1]
        (ks,) = self.subs("kill-session")
        self.assertEqual(ks[-1], "=" + name)
        # the waiter blocks on the channel of the window
        nw = self.subs("new-window")[0]
        chan = nw[nw.index("wrapper") + 3]
        self.assertIn(["wait-for", chan], self.calls())

    def test_the_idle_window_is_left_alone_for_a_command(self):
        # decision [2.3]: closing it could leave `main` without a window when the command ends (the session would vanish)
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.attach(["true"])
        self.assertEqual(self.subs("kill-window"), [])

    def test_exit_code_mapping(self):
        for status, want in (("0", 0), ("1", 1), ("130", 130), ("137", 137), ("143", 143), ("129", 129), ("7", 7)):
            with self.subTest(status=status):
                p, rc = self.attach(["cmd"], status=status)
                self.assertEqual(rc, want, p.out)
                self.assertEqual([f for f in os.listdir(self.run_dir) if f.startswith("exit.")], [], "status file not removed")

    def test_missing_status_file_gives_1_and_a_message(self):
        os.unlink(os.path.join(self.fake, "status")) if os.path.exists(os.path.join(self.fake, "status")) else None
        self.put("windows.txt", "")  # the window is gone and nothing was written
        self.put("window", "vanishes")
        p, rc = self.attach(["cmd"], status=None)
        self.assertEqual(rc, 1, p.out)
        self.assertIn(b"status", p.out)

    def test_garbage_in_the_status_file_gives_1(self):
        p, rc = self.attach(["cmd"], status="not a number")
        self.assertEqual(rc, 1, p.out)

    def test_sigkilled_wrapper_is_noticed_by_polling_the_window_id(self):
        # wait-for never fires; the window is not listed; no status file: exit 1 within a few poll intervals
        self.put("waitfor", "block")
        self.put("window", "vanishes")
        t0 = time.time()
        p, rc = self.attach(["sleep", "60"], status=None)
        self.assertEqual(rc, 1, p.out)
        self.assertLess(time.time() - t0, 10)
        self.assertGreaterEqual(len([c for c in self.subs("list-windows")]), 1)

    def test_a_listed_window_keeps_the_waiter_blocked_until_wait_for_returns(self):
        self.put("waitfor", "block")  # window stays listed: the poll must NOT end the wait
        self.put("status", "")
        p = self.run_term(self.fake, ["sleep", "60"])
        time.sleep(1.5)
        self.assertTrue(p.alive())
        self.put("windows.txt", "")  # now the window disappears with a status file: that ends it
        nw = self.subs("new-window")[0]
        status = nw[nw.index("wrapper") + 2]
        with open(status, "w") as f:
            f.write("4\n")
        self.assertEqual(p.wait(), 4)

    def test_hup_to_the_caller_ends_the_client_and_leaves_the_window(self):
        self.put("waitfor", "block")
        self.put("status", "")
        p = self.run_term(self.fake, ["sleep", "60"])
        wait_until(lambda: self.subs("wait-for"))
        p.p.send_signal(signal.SIGHUP)
        self.assertEqual(p.wait(), 129)
        self.assertEqual(self.subs("kill-window"), [])
        self.assertTrue(self.subs("kill-session"))

    def test_no_terminal_runs_the_command_directly_without_tmux(self):
        r = self.run_noterm(self.fake, ["sh", "-c", "exit 9"])
        self.assertEqual(r.returncode, 9)
        self.assertEqual(self.calls(), [])
        r = self.run_noterm(self.fake, ["sh", "-c", "kill -TERM $$"])
        self.assertEqual(r.returncode, 143)

    def test_no_terminal_output_has_no_cr_and_no_job_control_noise(self):
        r = self.run_noterm(self.fake, ["printf", "a\nb\n"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"a\nb\n")
        self.assertNotIn(b"\r", r.stdout)
        self.assertEqual(r.stderr, b"")  # bash -ic would print "cannot set terminal process group"

    def test_no_terminal_applies_alias_and_path_from_the_fragment_and_hides_the_switch(self):
        write_exec(os.path.join(self.home, "bin", "mytool"), '#!/bin/sh\necho "mytool:$*" > "$OUT_DIR/path_out"\n')
        r = self.run_noterm(self.fake, ["greet", "world"])
        self.assertEqual((r.returncode, r.stderr), (0, b""))
        self.assertEqual(self.out("alias_out"), "--auto-approve world\n")
        r = self.run_noterm(self.fake, ["mytool", "one", "two"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.out("path_out"), "mytool:one two\n")
        r = self.run_noterm(self.fake, ["sh", "-c", 'echo "cmd=${SWARMBOX_CMD:-unset}"'])
        self.assertEqual(r.stdout, b"cmd=unset\n")

    def test_no_terminal_quoting_arrives_byte_for_byte(self):
        outfile = os.path.join(self.out_dir, "q.out")
        r = self.run_noterm(self.fake, ["sh", "-c", 'f=$1; shift; printf "%s\\0" "$@" > "$f"', "sh", outfile] + AWKWARD)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = open(outfile, "rb").read().decode("utf-8", "surrogateescape").split("\0")[:-1]
        self.assertEqual(got, AWKWARD)

    def test_a_missing_fragment_is_not_an_error(self):
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_FRAGMENT=os.path.join(self.base, "nope.sh"))
        self.assertEqual((r.returncode, r.stderr), (0, b""))

    def test_plain_with_a_terminal_runs_through_bash_ic_without_tmux(self):
        with open(os.path.join(self.home, ".bashrc"), "w") as f:
            f.write(FRAGMENT)
        p = self.run_term(self.fake, ["--plain", "sh", "-c", "exit 5"])
        self.assertEqual(p.wait(), 5, p.out)
        self.assertEqual(self.calls(), [])
        p = self.run_term(self.fake, ["--plain", "greet", "hi"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual(self.out("alias_out"), "--auto-approve hi\n")

    def test_plain_without_terminal_is_the_no_terminal_form(self):
        r = self.run_noterm(self.fake, ["--plain", "greet", "x"])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.out("alias_out"), "--auto-approve x\n")

    def test_double_dash_ends_the_options(self):
        r = self.run_noterm(self.fake, ["--", "--plain-looking"], )
        self.assertEqual(r.returncode, 127)  # run as a command (not found), not parsed as an option


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

    def test_two_attach_calls_share_one_session_as_two_windows_and_the_idle_one_is_gone(self):
        self.assertEqual([w[1] for w in self.windows()], ["idle"])
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        w = self.windows()
        self.assertEqual(len(w), 1)
        self.assertNotEqual(w[0][1], "idle")  # B36: the idle window is gone
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 3), b.out)
        self.assertEqual(len(self.windows()), 2)
        self.assertNotIn("idle", [x[1] for x in self.windows()])
        # the grouped sessions: no status bar; each keeps its own current window; the group shares the windows
        for s in (s for s in self.sessions() if s != "main"):
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "status").stdout.strip(), "off")
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "destroy-unattached").stdout.strip(), "on")
            self.assertEqual(len(self.windows(s)), 2)
        self.assertNotEqual(self.iso.run("show-options", "-t", "=main", "-v", "status").stdout.strip(), "off")
        # closing a tab removes its grouped session and nothing else: both windows stay
        a.p.send_signal(signal.SIGHUP)
        a.close()
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2))
        self.assertEqual(len(self.windows()), 2)

    def test_b36_a_window_the_user_typed_in_is_not_closed_as_idle(self):
        self.iso.run("send-keys", "-t", "=main:idle", "sleep 300", "Enter", check=True)
        self.assertTrue(wait_until(lambda: [w for w in self.windows() if w[2] == "sleep"]))
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        names = [w[1] for w in self.windows()]
        self.assertEqual(len(names), 2)
        self.assertIn("idle", names)

    def test_b36_a_renamed_idle_window_is_not_closed(self):
        self.iso.run("rename-window", "-t", "=main:idle", "mine", check=True)
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        self.assertEqual(len(self.windows()), 2)

    def test_attach_creates_main_when_the_server_has_no_session(self):
        self.iso.run("kill-server")
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        self.assertEqual(len(self.windows()), 1)

    def test_command_exit_codes_through_a_real_window(self):
        for args, want in ((["true"], 0), (["false"], 1), (["sh", "-c", "exit 130"], 130), (["sh", "-c", "exit 7"], 7),
                           (["sh", "-c", "kill -9 $$"], 137), (["sh", "-c", "kill -15 $$"], 143),
                           (["no-such-command-xyz"], 127)):
            with self.subTest(args=args):
                p = self.term(args)
                self.assertEqual(p.wait(), want, p.out)
        self.assertEqual([f for f in os.listdir(self.run_dir) if f.startswith("exit.")], [])
        self.assertEqual(self.sessions(), ["main"], "grouped sessions of finished calls must be gone")

    def test_instant_commands_do_not_lose_the_wakeup(self):
        for i in range(8):
            p = self.term(["true"])
            self.assertEqual(p.wait(), 0, (i, p.out))

    def test_alias_and_path_apply_in_the_command_window(self):
        p = self.term(["greet", "world"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual(self.out("alias_out"), "--auto-approve world\n")
        p = self.term(["mytool", "a", "b"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual(self.out("path_out"), "mytool:a b\n")

    def test_quoting_through_a_real_window(self):
        outfile = os.path.join(self.out_dir, "q.out")
        p = self.term(["sh", "-c", 'f=$1; shift; printf "%s\\0" "$@" > "$f"', "sh", outfile] + AWKWARD)
        self.assertEqual(p.wait(), 0, p.out)
        got = open(outfile, "rb").read().decode("utf-8", "surrogateescape").split("\0")[:-1]
        self.assertEqual(got, AWKWARD)
        self.assertFalse(os.path.exists("/tmp/pwned"))

    def test_the_command_reads_the_terminal(self):
        outfile = os.path.join(self.out_dir, "read.out")
        p = self.term(["sh", "-c", 'echo ready > "$1".started; read x; echo "got:$x" > "$1"', "sh", outfile])
        self.assertTrue(wait_until(lambda: os.path.exists(outfile + ".started")), p.out)
        time.sleep(0.3)
        p.write(b"hello\n")
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual(open(outfile).read(), "got:hello\n")

    def test_the_command_starts_in_the_callers_directory(self):
        outfile = os.path.join(self.out_dir, "cwd.out")
        p = self.term(["sh", "-c", 'pwd > "$1"', "sh", outfile])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual(open(outfile).read().strip(), os.path.realpath(self.base))

    def test_a_window_killed_from_elsewhere_gives_129(self):
        before = {w[0] for w in self.windows()}
        p = self.term(["sleep", "300"])
        new = wait_until(lambda: [w for w in self.windows() if w[0] not in before])
        self.assertTrue(new, p.out)
        time.sleep(0.5)
        self.iso.run("kill-window", "-t", new[0][0], check=True)
        self.assertEqual(p.wait(), 129, p.out)
        self.assertEqual([f for f in os.listdir(self.run_dir) if f.startswith("exit.")], [])

    def test_a_sigkilled_wrapper_is_noticed_by_the_poll_and_gives_1(self):
        before = {w[0] for w in self.windows()}
        p = self.term(["sleep", "300"])
        new = wait_until(lambda: [w for w in self.windows() if w[0] not in before])
        self.assertTrue(new, p.out)
        time.sleep(0.5)
        pane_pid = self.iso.run("list-panes", "-t", new[0][0], "-F", "#{pane_pid}", check=True).stdout.split()[0]
        os.kill(int(pane_pid), signal.SIGKILL)  # the wrapper of a window of the isolated server this test made
        self.assertEqual(p.wait(timeout=20), 1, p.out)
        self.assertIn(b"status", p.out)

    def test_command_without_a_terminal_leaves_tmux_alone_and_has_no_cr(self):
        windows_before = self.windows()
        r = self.run_noterm(self.iso.shim_dir, ["printf", "a\nb\n"])
        self.assertEqual(r.returncode, 0, r.stderr)
        od = subprocess.run(["od", "-c"], input=r.stdout, capture_output=True).stdout.decode()
        self.assertNotIn("\\r", od)
        self.assertEqual(r.stdout, b"a\nb\n")
        self.assertEqual(self.windows(), windows_before)
        r = self.run_noterm(self.iso.shim_dir, ["greet", "nt"])
        self.assertEqual((r.returncode, r.stderr), (0, b""))
        self.assertEqual(self.out("alias_out"), "--auto-approve nt\n")

    def test_the_command_window_stays_out_of_the_idle_logic_and_idle_survives(self):
        p = self.term(["true"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertEqual([w[1] for w in self.windows()], ["idle"])


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

    def test_attach_without_the_program_fails_loudly(self):
        empty = os.path.join(self.base, "empty")
        os.mkdir(empty)
        r = subprocess.run(["bash", ENTRYPOINT, "attach", "true"], env=dict(self.env(empty), PATH=empty + ":/usr/bin:/bin"),
                           capture_output=True)
        self.assertEqual(r.returncode, 127)
        self.assertIn(b"swarmbox-attach", r.stderr)

    def test_attach_true_and_false_end_to_end_without_a_terminal(self):
        # the real script (installed under its image name) behind the real entrypoint: the exit criterion of 2.3 in miniature
        bindir = os.path.join(self.base, "bin")
        os.mkdir(bindir)
        os.symlink(ATTACH, os.path.join(bindir, "swarmbox-attach"))
        for cmd, want in (("true", 0), ("false", 1)):
            r = subprocess.run(["bash", ENTRYPOINT, "attach", cmd], env=self.env(bindir), stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=30)
            self.assertEqual(r.returncode, want, r.stderr)


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

    def test_bash_syntax(self):
        r = subprocess.run(["bash", "-n", ATTACH], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
