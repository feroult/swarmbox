"""Slice 2.2: `swarmbox-entrypoint serve` (design 4.1 and 4.2, 5.1): the ordered steps, failures, readiness marker, health file,
PID 1 signals and the ttyd supervisor, all against a fake environment.

Nothing here touches the live box: tmux, ttyd, podman, swarmbox-pubkey and swarmbox-tool are fakes in a
scratch folder that comes first on PATH (the test refuses to run when tmux or podman would resolve elsewhere); HOME, the run
folder and every XDG folder are mktemp directories; `serve` is started by the test and only that PID is ever signalled.
The test-only variables SWARMBOX_TEST_* are the ones decided in docs/history/decision-log.md ([2.2] test-only switches).

Run with: python3 tests/test_serve_steps.py   (needs bash; python3 is the fake podman)
"""
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
DESIGN = os.path.join(ROOT, "docs", "design.md")

FAKE_TMUX = """#!/bin/bash
echo "tmux $*" >> "$FAKE_DIR/calls.log"
[ -f "$FAKE_DIR/tmux.exit" ] && exit "$(cat "$FAKE_DIR/tmux.exit")"
exit 0
"""

FAKE_TTYD = """#!/bin/bash
echo "ttyd $*" >> "$FAKE_DIR/calls.log"
echo start >> "$FAKE_DIR/ttyd.starts"
echo $$ > "$FAKE_DIR/ttyd.pid"
mode=run
[ -f "$FAKE_DIR/ttyd.mode" ] && mode=$(cat "$FAKE_DIR/ttyd.mode")
[ "$mode" = crash ] && exit 1
exec sleep 1000
"""

FAKE_PODMAN = """#!/usr/bin/env python3
import os, socket, sys, time
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write("podman " + " ".join(args) + "\\n")
if "system" in args and "service" in args:
    if os.path.exists(os.path.join(d, "service.mode")) and open(os.path.join(d, "service.mode")).read().strip() == "fail":
        sys.exit(1)
    path = [a for a in args if a.startswith("unix://")][0][len("unix://"):]
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.listen(1)
    open(os.path.join(d, "service.pid"), "w").write(str(os.getpid()))
    time.sleep(1000)
    sys.exit(0)
if "--url" in args:
    sys.exit(1 if os.path.exists(os.path.join(d, "service.noanswer")) else 0)
sys.exit(0)
"""

FAKE_PROG = """#!/bin/bash
# generic fake: records the call, exit code from <name>.exit
n=$(basename "$0")
echo "$n $*" >> "$FAKE_DIR/calls.log"
if [ "$n" = swarmbox-tool ] && [ "$1" = install ]; then
    if [ -f "$SWARMBOX_TEST_RUN_DIR/ready" ]; then echo "install $2 saw-ready" >> "$FAKE_DIR/calls.log"; else echo "install $2 no-ready" >> "$FAKE_DIR/calls.log"; fi
fi
if [ -f "$FAKE_DIR/$n.$1.out" ]; then cat "$FAKE_DIR/$n.$1.out"; fi
[ -f "$FAKE_DIR/$n.exit" ] && exit "$(cat "$FAKE_DIR/$n.exit")"
exit 0
"""


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie counts as gone
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def wait_for(fn, seconds=10.0, step=0.02):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


class ServeCase(unittest.TestCase):
    PROGRAMS = ("swarmbox-pubkey", "swarmbox-tool", "swarmbox-mcp")

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="serve-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.fake = os.path.join(self.base, "fake")
        self.lib = os.path.join(self.base, "lib")
        self.home = os.path.join(self.base, "home")
        self.run_dir = os.path.join(self.base, "run")
        self.tun = os.path.join(self.base, "tun")
        for d in (self.fake, self.lib, self.home):
            os.mkdir(d)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        open(self.tun, "w").close()
        write_exec(os.path.join(self.fake, "tmux"), FAKE_TMUX)
        write_exec(os.path.join(self.fake, "swarmbox-web"), FAKE_TTYD)
        write_exec(os.path.join(self.fake, "podman"), FAKE_PODMAN)
        for p in self.PROGRAMS:
            write_exec(os.path.join(self.fake, p), FAKE_PROG)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.health = os.path.join(self.state, "health")
        self.procs = []
        self.addCleanup(self._reap)

    # -- environment -------------------------------------------------------------------------------------------------
    def env(self, **extra):
        path = self.fake + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
        env = {"PATH": path, "HOME": self.home, "FAKE_DIR": self.fake, "SWARMBOX_TEST_LIB": self.lib,
               "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_TUN": self.tun,
               "SWARMBOX_TEST_BACKOFF_SCALE": "0", "SWARMBOX_TEST_SERVICE_WAIT": "2", "LANG": "C.UTF-8"}
        env.update({k: v for k, v in extra.items() if v is not None})
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        for tool in ("tmux", "podman"):  # a real tmux or podman must never run from these tests
            self.assertEqual(shutil.which(tool, path=env["PATH"]), os.path.join(self.fake, tool))
        return env

    def start(self, **extra):
        p = subprocess.Popen(["bash", ENTRYPOINT, "serve"], env=self.env(**extra), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.procs.append(p)
        return p

    def _reap(self):
        for p in self.procs:
            if p.poll() is None:  # only the PID this test started
                try:
                    os.kill(p.pid, signal.SIGTERM)
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
                    p.wait()
            try:  # serve is the leader of its own session: end what it left behind (its `sleep infinity`, fake ttyd)
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()
        for name in ("ttyd.pid", "service.pid", "web-supervisor.pid"):
            for base in (self.fake, self.run_dir):
                s = read(os.path.join(base, name)).strip()
                if s.isdigit() and alive(int(s)):
                    os.kill(int(s), signal.SIGKILL)

    def run_to_exit(self, **extra):
        p = self.start(**extra)
        out, err = p.communicate(timeout=20)
        return p.returncode, out, err

    def run_ready(self, **extra):
        """Start serve, wait for the readiness marker, return the process."""
        p = self.start(**extra)
        ok = wait_for(lambda: os.path.exists(os.path.join(self.run_dir, "ready")) or p.poll() is not None, 15)
        self.assertTrue(ok and p.poll() is None, "serve did not become ready: rc=%s %s" % (p.poll(), p.stderr.read() if p.poll() is not None else ""))
        return p

    def marker(self):
        return read(os.path.join(self.run_dir, "ready")).strip()

    def calls(self):
        return read(os.path.join(self.fake, "calls.log")).splitlines()

    def health_lines(self):
        return [l for l in read(self.health).splitlines() if l.strip()]

    def serve_log(self):
        return read(os.path.join(self.state, "serve.log"))

    def stop(self, p, sig=signal.SIGTERM):
        os.kill(p.pid, sig)
        p.wait(timeout=10)
        return p.returncode


class FatalSteps(ServeCase):
    """Steps 0 to 3: failure exits 1 with a reason (F)."""

    def test_step1_workspace_missing(self):
        rc, out, err = self.run_to_exit(HOME=os.path.join(self.base, "nope"))
        self.assertEqual(rc, 1)
        self.assertIn("workspace", err.lower())
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "ready")))
        self.assertEqual(self.calls(), [])

    def test_step2_tun_missing(self):
        rc, out, err = self.run_to_exit(SWARMBOX_TEST_TUN=os.path.join(self.base, "no-tun"))
        self.assertEqual(rc, 1)
        self.assertIn("/dev/net/tun", err)
        self.assertIn("nested Podman needs /dev/net/tun", err)
        self.assertEqual(self.calls(), [], "nothing after step 2 may run")

class WarnSteps(ServeCase):
    """Steps 4 to 10: failure writes a health line and continues (W); the marker carries the count."""

    def test_each_w_step_failure_is_one_health_line_and_serve_continues(self):
        # (label, setup, expected word in the health line)
        cases = [
            ("step 5 ssh key", lambda: put(os.path.join(self.fake, "swarmbox-pubkey.exit"), "1"), "ssh"),
            ("step 8 service", lambda: put(os.path.join(self.fake, "service.mode"), "fail"), "podman"),
            ("step 9 tmux", lambda: put(os.path.join(self.fake, "tmux.exit"), "1"), "tmux"),
        ]
        for label, setup, word in cases:
            with self.subTest(label):
                self.tearDown_state()
                setup()
                p = self.run_ready()
                self.assertEqual(self.marker(), "warnings=1", label)
                lines = self.health_lines()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(word, lines[0].lower())
                # later steps still ran
                self.assertTrue(any(c.startswith("tmux new-session") for c in self.calls()) or label == "step 9 tmux")
                self.assertTrue(any(c.startswith("ttyd ") for c in self.calls()), "ttyd must still start: %s" % label)
                self.stop(p)

    def test_step_order_of_calls(self):
        p = self.run_ready()
        self.stop(p)
        calls = self.calls()

        def first(prefix):
            for i, c in enumerate(calls):
                if c.startswith(prefix):
                    return i
            self.fail("no call starting with %r in %r" % (prefix, calls))
        order = [first("swarmbox-pubkey --ensure"), first("swarmbox-tool link --user"),
                 first("swarmbox-tool prepare"), first("podman system service"), first("tmux new-session"), first("ttyd ")]
        self.assertEqual(order, sorted(order), calls)
        new = [c for c in calls if c.startswith("tmux new-session")][0]
        self.assertIn("-d", new.split())
        self.assertIn("main", new.split())

    def test_with_installs_run_after_the_marker_in_order(self):
        p = self.run_ready(SWARMBOX_WITH="claude, opencode")
        self.assertTrue(wait_for(lambda: "install opencode saw-ready" in self.calls()), self.calls())
        installs = [c for c in self.calls() if c.startswith("swarmbox-tool install ")]
        self.assertEqual(installs, ["swarmbox-tool install claude", "swarmbox-tool install opencode"])
        self.assertIn("install claude saw-ready", self.calls())
        self.stop(p)

    def test_serve_log_records_the_steps(self):
        p = self.run_ready()
        self.stop(p)
        log = self.serve_log()
        for n in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11):
            self.assertIn("step %d" % n, log)

    def tearDown_state(self):
        """Reset between sub-tests that start serve more than once."""
        for name in os.listdir(self.fake):
            if name.endswith((".exit", ".mode", ".noanswer", ".starts", ".pid", ".log")):
                os.unlink(os.path.join(self.fake, name))
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(os.path.join(self.home, ".local"), ignore_errors=True)


class Signals(ServeCase):
    """PID 1 behavior: handlers, exit codes, children stopped (design 4.1, B3)."""

    def children_gone(self):
        pids = []
        for base, name in ((self.fake, "ttyd.pid"), (self.fake, "service.pid")):
            s = read(os.path.join(base, name)).strip()
            if s.isdigit():
                pids.append(int(s))
        self.assertTrue(pids, "no child pid was recorded")
        return [p for p in pids if alive(p)]

    def test_sigterm_gives_143_within_a_second_and_stops_children(self):
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: read(os.path.join(self.fake, "ttyd.pid")).strip()))
        t0 = time.time()
        rc = self.stop(p, signal.SIGTERM)
        self.assertEqual(rc, 143)
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(self.children_gone(), [])

    def test_sigint_gives_130_within_a_second_and_stops_children(self):
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: read(os.path.join(self.fake, "ttyd.pid")).strip()))
        t0 = time.time()
        rc = self.stop(p, signal.SIGINT)
        self.assertEqual(rc, 130)
        self.assertLess(time.time() - t0, 1.0)
        self.assertEqual(self.children_gone(), [])

class Supervisor(ServeCase):
    """The ttyd supervisor: backoff, giving up, idle, restart by hand (design 4.2)."""

    def starts(self):
        return len(read(os.path.join(self.fake, "ttyd.starts")).split())

    def sup_pid(self):
        s = read(os.path.join(self.run_dir, "web-supervisor.pid")).strip()
        return int(s) if s.isdigit() else None

    def test_crash_loop_gives_up_after_five_exits_and_stays_alive(self):
        put(os.path.join(self.fake, "ttyd.mode"), "crash")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10), self.health_lines())
        time.sleep(0.4)
        self.assertEqual(self.starts(), 5)
        self.assertIn("web terminal keeps crashing; see web-terminal.log", self.health_lines())
        self.assertIsNone(p.poll(), "the box must stay up")
        self.assertTrue(alive(self.sup_pid()), "the supervisor must stay alive, idle")
        self.assertEqual(self.starts(), 5, "no restart while idle")
        self.stop(p)

    def test_restart_signal_restarts_ttyd_resets_count_and_clears_the_line(self):
        put(os.path.join(self.fake, "ttyd.mode"), "crash")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10))
        time.sleep(0.2)
        self.assertEqual(self.starts(), 5)
        # fix the cause, then `swarmbox-web restart` (which sends USR1 to the supervisor)
        put(os.path.join(self.fake, "ttyd.mode"), "run")
        os.kill(self.sup_pid(), signal.SIGUSR1)
        self.assertTrue(wait_for(lambda: self.starts() == 6), "ttyd was not restarted")
        self.assertTrue(wait_for(lambda: not any("keeps crashing" in l for l in self.health_lines()), 3), self.health_lines())
        self.assertTrue(alive(int(read(os.path.join(self.fake, "ttyd.pid")).strip())))
        # the count was reset: five more quick exits are needed before it gives up again
        put(os.path.join(self.fake, "ttyd.mode"), "crash")
        os.kill(self.sup_pid(), signal.SIGUSR1)
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10))
        time.sleep(0.3)
        self.assertEqual(self.starts(), 6 + 5)
        self.stop(p)

class StaticOrder(unittest.TestCase):
    """The step markers of the script are in order."""

    def test_step_markers_are_in_the_serve_function_in_order(self):
        text = read(ENTRYPOINT)
        pos = [text.index("# step %d [" % n) for n in range(13) if n != 4]   # step 4 (migration) was removed
        self.assertEqual(pos, sorted(pos))
        self.assertLess(text.index("trap "), pos[0], "the handlers are installed before the first step")

    def test_script_is_bash_and_parses(self):
        first = read(ENTRYPOINT).splitlines()[0]
        self.assertEqual(first, "#!/bin/bash")
        r = subprocess.run(["bash", "-n", ENTRYPOINT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
