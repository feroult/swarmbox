#!/usr/bin/env python3
"""Tests for what start.sh opens inside the container: a window of the tmux session "main" (the one the web
terminal shows), through a grouped session; SWARMBOX_ATTACH=shell keeps the plain bash.

Run:  python3 tests/test_start_attach.py

The tmux part runs the real script start.sh sends to the container, on a private tmux socket and a pty.
"""
import fcntl
import os
import pty
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import termios
import time
import unittest

from helpers import ROOT

START = os.path.join(ROOT, "start.sh")
STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$1" in
  images) echo img1 ;;
  ps) echo cid1 ;;
esac
exit 0
"""


def attach_script():
    with open(os.path.join(ROOT, "lib", "attach-session.sh")) as f:
        return f.read()


class Calls(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.bin, ignore_errors=True)
        self.log = os.path.join(self.work, "calls.log")
        stub = os.path.join(self.bin, "podman")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        os.makedirs(os.path.join(self.work, ".work", ".swarmbox"))
        open(os.path.join(self.work, ".work", ".swarmbox", "podman.sock"), "w").close()

    def enter(self, attach=None):
        env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.work, "STUB_LOG": self.log}
        if attach:
            env["SWARMBOX_ATTACH"] = attach
        r = subprocess.run(["bash", START], cwd=self.work, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            # one call per "exec -it": the script argument spans several lines
            return ["exec -it" + c for c in f.read().split("exec -it")[1:]]

    def test_by_default_it_attaches_to_the_main_tmux_session(self):
        (call,) = self.enter()
        self.assertIn("swarmbox bash -c", call)
        self.assertIn("tmux new-session -t main", call)

    def test_attach_shell_keeps_the_plain_bash(self):
        (call,) = self.enter("shell")
        self.assertTrue(call.strip().endswith("swarmbox bash"), call)


@unittest.skipUnless(shutil.which("tmux"), "needs tmux")
class RealTmux(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sba")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {"PATH": os.environ["PATH"], "HOME": self.tmp, "TMUX_TMPDIR": self.tmp, "TERM": "xterm-256color",
                    "SHELL": "/bin/sh", "LANG": "C.UTF-8"}
        self.addCleanup(lambda: subprocess.run(["tmux", "kill-server"], env=self.env, capture_output=True))
        self.pids = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass

    def tmux(self, *a):
        r = subprocess.run(["tmux"] + list(a), env=self.env, capture_output=True, text=True)
        return r.stdout.strip().splitlines()

    def attach(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe("bash", ["bash", "-c", attach_script()], self.env)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
        self.pids.append(pid)
        self.addCleanup(os.close, fd)
        return pid, fd

    def wait(self, cond, what):
        for _ in range(100):
            if cond():
                return
            time.sleep(0.1)
        self.fail("timed out: " + what)

    def test_with_the_web_session_running_it_adds_a_window_in_a_grouped_session(self):
        self.tmux("new-session", "-d", "-s", "main")           # what the web terminal runs
        self.assertEqual(len(self.tmux("list-windows", "-t", "main")), 1)
        pid, _ = self.attach()
        self.wait(lambda: len(self.tmux("list-sessions")) == 2, "grouped session")
        self.assertEqual(len(self.tmux("list-windows", "-t", "main")), 2, "the web session sees the new window")
        # the web side keeps its own current window
        self.assertEqual(self.tmux("display-message", "-p", "-t", "main", "#I"), ["1"])

    def test_the_grouped_session_goes_away_when_the_host_tab_closes_but_the_window_stays(self):
        self.tmux("new-session", "-d", "-s", "main")
        pid, fd = self.attach()
        self.wait(lambda: len(self.tmux("list-sessions")) == 2, "grouped session")
        os.kill(pid, signal.SIGHUP)
        os.waitpid(pid, 0)
        self.pids.remove(pid)
        self.wait(lambda: self.tmux("list-sessions") == [s for s in self.tmux("list-sessions") if s.startswith("main:")]
                  and len(self.tmux("list-sessions")) == 1, "grouped session cleanup")
        self.assertEqual(len(self.tmux("list-windows", "-t", "main")), 2)

    def test_without_a_session_it_creates_main_with_a_single_window(self):
        self.attach()
        self.wait(lambda: self.tmux("list-sessions"), "session")
        self.wait(lambda: len(self.tmux("list-sessions")) == 2, "grouped session")
        self.assertEqual(len(self.tmux("list-windows", "-t", "main")), 1)

    def test_the_host_tab_has_no_status_bar_but_the_web_session_keeps_it(self):
        self.tmux("new-session", "-d", "-s", "main")
        self.attach()
        self.wait(lambda: len(self.tmux("list-sessions")) == 2, "grouped session")
        grouped = [s.split(":")[0] for s in self.tmux("list-sessions") if not s.startswith("main:")][0]
        self.assertEqual(self.tmux("show-options", "-v", "-t", grouped, "status"), ["off"])
        self.assertNotEqual(self.tmux("show-options", "-v", "-t", "main", "status"), ["off"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
