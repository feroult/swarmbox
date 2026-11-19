"""Shared by the tests of `swarmbox-attach` (tests/fast/test_attach_command.py with a fake tmux, tests/slow/test_attach_real.py with a
real one, tests/slow/test_bashrc_container.py): a fake tmux that records, the isolated real tmux, a pty as the terminal.

The real tmux is ALWAYS isolated: every call goes through IsoTmux, which forces `-L swarmbox-test-<random> -f /dev/null`, a private
TMUX_TMPDIR and no TMUX variable, and refuses a call without -L (tested). The server is killed only by that exact -L name; the server of
the machine (`tmux ls` shows main and main-1) is never addressed. Test-only variables of the script: SWARMBOX_TEST_LIB,
SWARMBOX_TEST_RUN_DIR, SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60), SWARMBOX_TEST_POLL_INTERVAL (seconds, default 1),
SWARMBOX_TEST_FRAGMENT.
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
from helpers import ROOT  # noqa: E402

ATTACH = os.path.join(ROOT, "container", "scripts", "swarmbox-attach.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
REAL_TMUX = shutil.which("tmux")
# a real tmux (even a private one) only where the gate says a container runs the tests: dev/test-slow.sh and the browser job of CI set it
HAVE_REAL_TMUX = bool(REAL_TMUX) and os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"
NEEDS_TMUX = "needs tmux and a container (SWARMBOX_TEST_REAL_TMUX=1, which only dev/test-slow.sh and CI set)"

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
if sub == "attach-session":
    open(os.path.join(d, "attach-env.txt"), "a").write("web=%s\n" % os.environ.get("SWARMBOX_WEB_CLIENT", ""))
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
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read()



class FakeTmuxCase(Base):
    def setUp(self):
        super().setUp()
        write_exec(os.path.join(self.fake, "tmux"), FAKE_TMUX)
        self.assertEqual(shutil.which("tmux", path=self.fake + os.pathsep + "/usr/bin"), os.path.join(self.fake, "tmux"))

    def calls(self):
        p = os.path.join(self.fake, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f.read().splitlines()]

    def put(self, name, text):
        with open(os.path.join(self.fake, name), "w") as f:
            f.write(text)

    def subs(self, name):
        return [c for c in self.calls() if c and c[0] == name]
