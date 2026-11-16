"""`swarmbox-entrypoint serve`: the ordered steps, failures, readiness marker, health file,
PID 1 signals and the ttyd supervisor, all against a fake environment.

Nothing here touches the live box: tmux, ttyd, podman, swarmbox-pubkey and swarmbox-addon are fakes in a
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
from helpers import ROOT, restore_signals  # noqa: E402

restore_signals()

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

# the fake bus broker: `serve` records itself and runs (or exits with the status in bus.exit when bus.mode is crash); `ping` is
# answered unless bus.noping exists. SB_BUS_SOCKET is recorded, to see what the entrypoint passes.
FAKE_BUS = """#!/bin/bash
if [ "$1" = ping ]; then [ -f "$FAKE_DIR/bus.noping" ] && exit 4; exit 0; fi
echo "swarmbox-bus $* [$SB_BUS_SOCKET]" >> "$FAKE_DIR/calls.log"
echo start >> "$FAKE_DIR/bus.starts"
echo $$ > "$FAKE_DIR/bus.pid"
mode=run
[ -f "$FAKE_DIR/bus.mode" ] && mode=$(cat "$FAKE_DIR/bus.mode")
[ "$mode" = crash ] && exit "$(cat "$FAKE_DIR/bus.exit" 2>/dev/null || echo 1)"
exec sleep 1000
"""

FAKE_PODMAN = """#!/usr/bin/env python3
import os, socket, sys, time
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write("podman " + " ".join(args) + "\\n")
if "system" in args and "service" in args:
    if os.environ.get("FAKE_MARKER"):   # the stale-marker tests: was the fuse-overlayfs marker still there when the service started?
        open(os.path.join(d, "marker.seen"), "w").write("yes" if os.path.exists(os.environ["FAKE_MARKER"]) else "no")
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
if [ "$n" = swarmbox-addon ] && [ "$1" = install ]; then
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
    PROGRAMS = ("swarmbox-pubkey", "swarmbox-addon", "swarmbox-mcp")

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
        write_exec(os.path.join(self.fake, "swarmbox-bus"), FAKE_BUS)
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
               # step 8 removes this folder: by default it is the real /tmp/storage-run-<uid>, i.e. the runtime state of the nested Podman of whatever
               # box runs these tests (found when the gate wiped it in a running box); every test gets its own
               "SWARMBOX_TEST_PODMAN_RUNROOT": os.path.join(self.base, "storage-run"),
               "SWARMBOX_TEST_BACKOFF_SCALE": "0", "SWARMBOX_TEST_SERVICE_WAIT": "2", "SWARMBOX_TEST_BUS_WAIT": "1", "LANG": "C.UTF-8"}
        env.update({k: v for k, v in extra.items() if v is not None})
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        for prog in ("tmux", "podman"):  # a real tmux or podman must never run from these tests
            self.assertEqual(shutil.which(prog, path=env["PATH"]), os.path.join(self.fake, prog))
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
        for name in ("ttyd.pid", "service.pid", "bus.pid", "web-supervisor.pid", "bus-supervisor.pid"):
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

class RunFolderNotWritable(ServeCase):
    """After a host reboot the tmpfs of the box came back unwritable for the agent: serve made no marker and the host timed out."""

    def test_a_run_folder_the_agent_cannot_write_is_made_writable_with_sudo(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        os.mkdir(self.run_dir, 0o555)
        write_exec(os.path.join(self.fake, "sudo"),
                   '#!/bin/bash\necho "sudo $*" >> "$FAKE_DIR/calls.log"\n[ "$1" = -n ] && shift\nexec "$@"\n')
        p = self.run_ready()
        self.assertEqual(self.marker(), "ok")
        self.assertIn("sudo -n chmod 1777 %s" % self.run_dir, self.calls())
        self.assertIn("was not writable", self.serve_log())
        self.stop(p)

    def test_a_writable_run_folder_never_calls_sudo(self):
        write_exec(os.path.join(self.fake, "sudo"), '#!/bin/bash\necho "sudo $*" >> "$FAKE_DIR/calls.log"\nexit 1\n')
        p = self.run_ready()
        self.assertFalse([c for c in self.calls() if c.startswith("sudo")])
        self.stop(p)


class NestedRunroot(ServeCase):
    """After a host reboot the nested Podman refused to start: its runtime folder, in the box's own filesystem, held the old boot ID."""

    def test_a_stale_runtime_folder_of_nested_podman_is_removed_before_the_service_starts(self):
        rr = os.path.join(self.base, "storage-run")
        os.makedirs(os.path.join(rr, "libpod", "tmp"))
        put(os.path.join(rr, "libpod", "tmp", "alive"), "old boot id")
        p = self.run_ready(SWARMBOX_TEST_PODMAN_RUNROOT=rr)
        self.assertFalse(os.path.exists(rr), "the stale folder must be gone")
        self.assertIn("removed the runtime state of the previous run", self.serve_log())
        self.assertTrue([c for c in self.calls() if c.startswith("podman system service")])
        self.stop(p)

    def test_no_folder_to_remove_says_nothing(self):
        p = self.run_ready(SWARMBOX_TEST_PODMAN_RUNROOT=os.path.join(self.base, "never-there"))
        self.assertNotIn("removed the runtime state", self.serve_log())
        self.stop(p)


class NestedFuseMarker(ServeCase):
    """The box has no /dev/fuse. One probe of native overlay that fails on another graph root (the cache is shared by all of them) makes Podman fall back to
    fuse-overlayfs and leave .has-mount-program = true, for good: every later run died with "fuse: device not found" (found in a real box). serve step 8 removes
    that marker when there is no usable /dev/fuse, before the service starts, and touches nothing when there is one."""

    def setUp(self):
        super().setUp()
        self.graph = os.path.join(self.base, "graphroot")
        self.marker_path = os.path.join(self.graph, "overlay", ".has-mount-program")
        os.makedirs(os.path.dirname(self.marker_path))
        self.no_fuse = os.path.join(self.base, "no-such-fuse")

    def serve(self, fuse, content="true"):
        put(self.marker_path, content)
        p = self.run_ready(SWARMBOX_TEST_PODMAN_GRAPHROOT=self.graph, SWARMBOX_TEST_FUSE=fuse, FAKE_MARKER=self.marker_path,
                           SWARMBOX_TEST_PODMAN_RUNROOT=os.path.join(self.base, "never-there"))
        self.addCleanup(self.stop, p)
        return p

    def test_without_fuse_the_stale_marker_is_removed_before_the_service_starts(self):
        self.serve(self.no_fuse)
        self.assertFalse(os.path.exists(self.marker_path))
        self.assertEqual(read(os.path.join(self.fake, "marker.seen")), "no", "the marker must be gone when the service starts")
        self.assertIn("removed the stale marker", self.serve_log())
        self.assertEqual(self.marker(), "ok")

    def test_a_marker_that_says_false_is_left_alone(self):
        self.serve(self.no_fuse, content="false")
        self.assertEqual(read(self.marker_path), "false")
        self.assertNotIn("stale marker", self.serve_log())

    def test_a_path_that_is_not_a_character_device_counts_as_no_fuse(self):
        self.serve(os.path.join(self.base, "dir-not-device"), content="true")   # a path that is not a character device
        self.assertFalse(os.path.exists(self.marker_path))

    def test_with_a_usable_fuse_device_nothing_is_touched(self):
        self.serve("/dev/null")   # a character device the agent can open: stands for /dev/fuse
        self.assertEqual(read(self.marker_path), "true")
        self.assertEqual(read(os.path.join(self.fake, "marker.seen")), "yes")
        self.assertNotIn("stale marker", self.serve_log())

    def test_no_graph_root_yet_says_nothing(self):
        shutil.rmtree(self.graph)
        p = self.run_ready(SWARMBOX_TEST_PODMAN_GRAPHROOT=self.graph, SWARMBOX_TEST_FUSE=self.no_fuse)
        self.addCleanup(self.stop, p)
        self.assertNotIn("stale marker", self.serve_log())
        self.assertEqual(self.marker(), "ok")


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
        order = [first("swarmbox-pubkey --ensure"), first("swarmbox-addon link --user"), first("swarmbox-bus serve"),
                 first("swarmbox-addon prepare"), first("podman system service"), first("tmux new-session"), first("ttyd ")]
        self.assertEqual(order, sorted(order), calls)
        new = [c for c in calls if c.startswith("tmux new-session")][0]
        self.assertIn("-d", new.split())
        self.assertIn("main", new.split())

    def test_with_installs_run_after_the_marker_in_order(self):
        p = self.run_ready(SWARMBOX_WITH="claude, opencode")
        self.assertTrue(wait_for(lambda: "install opencode saw-ready" in self.calls()), self.calls())
        installs = [c for c in self.calls() if c.startswith("swarmbox-addon install ")]
        self.assertEqual(installs, ["swarmbox-addon install claude", "swarmbox-addon install opencode"])
        self.assertIn("install claude saw-ready", self.calls())
        self.stop(p)

    def test_serve_log_records_the_steps(self):
        p = self.run_ready()
        self.stop(p)
        log = self.serve_log()
        for n in (1, 2, 3, 5, 6, "6b", 7, 8, 9, 10, 11):
            self.assertIn("step %s" % n, log)

    def tearDown_state(self):
        """Reset between sub-tests that start serve more than once."""
        for name in os.listdir(self.fake):
            if name.endswith((".exit", ".mode", ".noanswer", ".starts", ".pid", ".log")):
                os.unlink(os.path.join(self.fake, name))
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(os.path.join(self.home, ".local"), ignore_errors=True)


class Signals(ServeCase):
    """PID 1 behavior: handlers, exit codes, children stopped."""

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
    """The ttyd supervisor: backoff, giving up, idle, restart by hand."""

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

class BusStep(ServeCase):
    """Step 6b: the bus broker under supervise_one (the same policy as ttyd's), a W step."""

    def starts(self):
        return len(read(os.path.join(self.fake, "bus.starts")).split())

    def sup_pid(self):
        s = read(os.path.join(self.run_dir, "bus-supervisor.pid")).strip()
        return int(s) if s.isdigit() else None

    def test_the_broker_runs_with_the_socket_in_the_run_folder_and_the_marker_is_ok(self):
        p = self.run_ready()
        self.assertEqual(self.marker(), "ok")
        self.assertEqual(self.health_lines(), [])
        self.assertIn("swarmbox-bus serve [%s]" % os.path.join(self.run_dir, "bus.sock"), self.calls())
        self.assertTrue(alive(self.sup_pid()))
        self.stop(p)

    def test_it_is_started_before_prepare_and_without_waiting_for_tmux(self):
        p = self.run_ready()
        calls = self.calls()
        idx = lambda pre: [i for i, c in enumerate(calls) if c.startswith(pre)][0]  # noqa: E731
        self.assertLess(idx("swarmbox-bus serve"), idx("swarmbox-addon prepare"))
        self.assertLess(idx("swarmbox-bus serve"), idx("tmux new-session"))
        self.stop(p)

    def test_a_broker_that_does_not_answer_is_one_warning_and_serve_goes_on(self):
        put(os.path.join(self.fake, "bus.noping"), "")
        p = self.run_ready()
        self.assertEqual(self.marker(), "warnings=1")
        self.assertEqual(len(self.health_lines()), 1, self.health_lines())
        self.assertIn("the bus did not answer", self.health_lines()[0])
        self.assertTrue(any(c.startswith("ttyd ") for c in self.calls()), "ttyd must still start")
        self.stop(p)

    def test_a_missing_program_is_one_warning(self):
        os.unlink(os.path.join(self.fake, "swarmbox-bus"))
        p = self.run_ready()
        self.assertEqual(self.marker(), "warnings=1")
        self.assertIn("swarmbox-bus not found", self.health_lines()[0])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "bus-supervisor.pid")))
        self.stop(p)

    def test_a_killed_broker_is_started_again_with_the_backoff(self):
        p = self.run_ready(SWARMBOX_TEST_BACKOFF_SCALE="1")
        pid = int(wait_for(lambda: read(os.path.join(self.fake, "bus.pid")).strip()))
        t0 = time.time()
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(wait_for(lambda: self.starts() == 2, 5), "the broker was not restarted")
        self.assertGreaterEqual(time.time() - t0, 0.9, "the first retry is after 1 s")
        self.assertIn("bus exited; restarting in 1 s", self.serve_log())
        self.stop(p)

    def test_crash_loop_gives_up_with_a_health_line_and_restart_by_signal_starts_again(self):
        put(os.path.join(self.fake, "bus.mode"), "crash")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: "the bus keeps crashing; see bus.log" in self.health_lines(), 10), self.health_lines())
        time.sleep(0.3)
        self.assertEqual(self.starts(), 5)
        self.assertIn("waiting for 'swarmbox-bus restart'", self.serve_log())
        self.assertIsNone(p.poll(), "the box stays up")
        put(os.path.join(self.fake, "bus.mode"), "run")
        os.kill(self.sup_pid(), signal.SIGUSR1)
        self.assertTrue(wait_for(lambda: self.starts() == 6))
        self.assertTrue(wait_for(lambda: not self.health_lines(), 3), self.health_lines())
        self.stop(p)

    def test_exit_8_means_another_broker_runs_and_is_not_restarted(self):
        put(os.path.join(self.fake, "bus.mode"), "crash")
        put(os.path.join(self.fake, "bus.exit"), "8")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: "another one is running" in self.serve_log(), 5))
        time.sleep(0.3)
        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.health_lines(), [])
        self.stop(p)

    def test_the_pid_file_does_not_outlive_a_supervisor_that_ended_by_itself(self):
        # `swarmbox-bus restart` sends USR1 to the pid in that file, and USR1 kills a process that does not handle it
        put(os.path.join(self.fake, "bus.mode"), "crash")
        put(os.path.join(self.fake, "bus.exit"), "8")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: "another one is running" in self.serve_log(), 5))
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.run_dir, "bus-supervisor.pid")), 3),
                        "bus-supervisor.pid is still there: %r" % read(os.path.join(self.run_dir, "bus-supervisor.pid")))
        self.stop(p)

    def test_sigterm_stops_the_supervisor_and_the_broker_and_removes_the_pid_file(self):
        p = self.run_ready()
        pid = int(wait_for(lambda: read(os.path.join(self.fake, "bus.pid")).strip()))
        sup = self.sup_pid()
        self.assertEqual(self.stop(p), 143)
        self.assertFalse(alive(pid))
        self.assertFalse(alive(sup))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "bus-supervisor.pid")))


class StaticOrder(unittest.TestCase):
    """The step markers of the script are in order."""

    def test_step_markers_are_in_the_serve_function_in_order(self):
        text = read(ENTRYPOINT)
        pos = [text.index("# step %s [" % n) for n in ("0", "1", "2", "3", "5", "6", "6b", "7", "8", "9", "10", "11", "12")]   # step 4 (migration) was removed
        self.assertEqual(pos, sorted(pos))
        self.assertLess(text.index("trap "), pos[0], "the handlers are installed before the first step")

    def test_script_is_bash_and_parses(self):
        first = read(ENTRYPOINT).splitlines()[0]
        self.assertEqual(first, "#!/bin/bash")
        r = subprocess.run(["bash", "-n", ENTRYPOINT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
