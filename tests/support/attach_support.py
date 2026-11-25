"""Shared by the tests of `swarmbox-attach` (tests/fast/test_attach_command.py, tests/fast/test_mux_isolation.py, tests/slow/smoke_image.py):
a fake multiplexer backend that records, a pty as the terminal. The herdr backend itself is tests/fast/test_herdr_backend.py.
Test-only variables of the script: SWARMBOX_TEST_LIB, SWARMBOX_TEST_MUX_DIR,
SWARMBOX_TEST_RUN_DIR, SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60), SWARMBOX_TEST_POLL_INTERVAL (seconds, default 1),
SWARMBOX_TEST_FRAGMENT.
"""
import fcntl
import os
import pty
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
MUX_SH = os.path.join(ROOT, "container", "scripts", "mux", "mux.sh")

# A fake multiplexer backend (the contract of container/scripts/mux/mux.sh), loaded with SWARMBOX_TEST_MUX_DIR + SWARMBOX_MUX=fake: each
# function records its call (calls.txt in FAKE_DIR, "name args...") and exits FAKE_RC (0 by default); FAKE_UNAVAILABLE=1 makes it absent.
FAKE_BACKEND = r'''mux_available() { [ "${FAKE_UNAVAILABLE:-0}" != 1 ]; }
_fake_rec() { printf '%s\n' "$*" >> "$FAKE_DIR/calls.txt"; }
mux_serve_init() { _fake_rec serve_init; }
mux_serve_shutdown_note() { _fake_rec shutdown_note; }
mux_attach_interactive() { _fake_rec attach_interactive; exit "${FAKE_RC:-0}"; }
mux_attach_command() { _fake_rec attach_command; printf '%s' "$1" > "$FAKE_DIR/command.q"; exit "${FAKE_RC:-0}"; }
mux_web_run() { _fake_rec web_run "$@"; exit "${FAKE_RC:-0}"; }
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



class FakeMuxCase(Base):
    """swarmbox-attach over the fake backend: the real mux.sh loads fake.sh from a folder of the test."""

    def setUp(self):
        super().setUp()
        self.mux_dir = os.path.join(self.base, "mux")
        os.makedirs(self.mux_dir)
        os.symlink(MUX_SH, os.path.join(self.mux_dir, "mux.sh"))
        with open(os.path.join(self.mux_dir, "fake.sh"), "w") as f:
            f.write(FAKE_BACKEND)

    def env(self, path_dir, **extra):
        e = {"SWARMBOX_TEST_MUX_DIR": self.mux_dir, "SWARMBOX_MUX": "fake"}
        e.update(extra)
        return super().env(path_dir, **e)

    def calls(self):
        p = os.path.join(self.fake, "calls.txt")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return f.read().splitlines()

    def command_q(self):
        with open(os.path.join(self.fake, "command.q")) as f:
            return f.read()
