"""`swarmbox-entrypoint serve`: the ordered steps, failures, readiness marker, health file, PID 1 signals and the two supervisors (ttyd, the
bus broker), all against the fake environment of tests/support/serve_support.py.

A start of `serve` costs a fraction of a second, so the checks of one ordinary start share it (DefaultRun) and the other classes start
it again only with the one thing that is different.

Run with: python3 tests/fast/test_serve_steps.py   (needs bash; python3 is the fake podman)
"""
import os
import shutil
import signal
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from serve_support import ENTRYPOINT, ServeCase, alive, put, read, wait_for, write_exec  # noqa: E402,F401  (bus_serve imports these from here)


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


class DefaultRun(unittest.TestCase):
    """One ordinary start, stopped with SIGTERM; the tests read what it left."""

    @classmethod
    def setUpClass(cls):
        cls.c = ServeCase()
        cls.c.setUp()
        cls.addClassCleanup(cls.c.doCleanups)
        # a sudo that would be recorded (and fail): a run folder the agent can write must never call it
        write_exec(os.path.join(cls.c.fake, "sudo"), '#!/bin/bash\necho "sudo $*" >> "$FAKE_DIR/calls.log"\nexit 1\n')
        p = cls.c.run_ready()
        wait_for(lambda: read(os.path.join(cls.c.fake, "ttyd.pid")).strip())
        cls.bus_pid = int(wait_for(lambda: read(os.path.join(cls.c.fake, "bus.pid")).strip()))
        cls.bus_sup = int(read(os.path.join(cls.c.run_dir, "bus-supervisor.pid")).strip())
        cls.marker = cls.c.marker()
        cls.health = cls.c.health_lines()
        cls.live_pids = [int(read(os.path.join(cls.c.fake, n)).strip()) for n in ("ttyd.pid", "service.pid")]
        cls.t0 = time.time()
        cls.rc = cls.c.stop(p, signal.SIGTERM)
        cls.stop_seconds = time.time() - cls.t0
        cls.calls = cls.c.calls()
        cls.log = cls.c.serve_log()

    def first(self, prefix):
        for i, c in enumerate(self.calls):
            if c.startswith(prefix):
                return i
        self.fail("no call starting with %r in %r" % (prefix, self.calls))

    def test_the_marker_is_ok_with_no_health_line_and_the_broker_gets_the_socket_of_the_run_folder(self):
        self.assertEqual(self.marker, "ok")
        self.assertEqual(self.health, [])
        self.assertIn("swarmbox-bus serve [%s]" % os.path.join(self.c.run_dir, "bus.sock"), self.calls)

    def test_the_steps_run_in_order_and_the_broker_does_not_wait_for_tmux(self):
        order = [self.first("swarmbox-pubkey --ensure"), self.first("swarmbox-addon link --user"), self.first("swarmbox-bus serve"),
                 self.first("swarmbox-addon prepare"), self.first("podman system service"), self.first("tmux new-session"), self.first("ttyd ")]
        self.assertEqual(order, sorted(order), self.calls)
        new = self.calls[self.first("tmux new-session")].split()
        self.assertIn("-d", new)
        self.assertIn("main", new)

    def test_the_serve_log_records_the_steps(self):
        for n in (1, 2, 3, 5, 6, "6b", 7, 8, 9, 10, 11):
            self.assertIn("step %s" % n, self.log)

    def test_nothing_is_said_or_done_when_there_is_nothing_to_fix(self):
        self.assertFalse([c for c in self.calls if c.startswith("sudo")], "a writable run folder never calls sudo")
        self.assertNotIn("removed the runtime state", self.log, "no stale runtime folder of nested Podman")
        self.assertNotIn("stale marker", self.log, "no graph root yet")

    def test_sigterm_gives_143_promptly_and_stops_the_children_and_the_supervisors(self):
        self.assertEqual(self.rc, 143)
        self.assertLess(self.stop_seconds, 8.0, "a stop that waits for a child takes the 10 s of the container's grace; a second on a quiet machine")
        self.assertEqual([p for p in self.live_pids + [self.bus_pid, self.bus_sup] if alive(p)], [])
        self.assertFalse(os.path.exists(os.path.join(self.c.run_dir, "bus-supervisor.pid")))


class Signals(ServeCase):
    def test_sigint_gives_130_within_a_second(self):
        p = self.run_ready()
        t0 = time.time()
        self.assertEqual(self.stop(p, signal.SIGINT), 130)
        self.assertLess(time.time() - t0, 1.0)


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


class NestedPodmanState(ServeCase):
    """The box has no /dev/fuse and its filesystem outlives a host reboot: step 8 clears what the old boot left, before the service starts."""

    def test_a_stale_runtime_folder_of_nested_podman_is_removed_before_the_service_starts(self):
        # after a host reboot nested Podman refused to start: its runtime folder held the old boot ID
        rr = os.path.join(self.base, "storage-run")
        os.makedirs(os.path.join(rr, "libpod", "tmp"))
        put(os.path.join(rr, "libpod", "tmp", "alive"), "old boot id")
        p = self.run_ready(SWARMBOX_TEST_PODMAN_RUNROOT=rr)
        self.assertFalse(os.path.exists(rr), "the stale folder must be gone")
        self.assertIn("removed the runtime state of the previous run", self.serve_log())
        self.assertTrue([c for c in self.calls() if c.startswith("podman system service")])
        self.stop(p)

    def test_the_second_runtime_folder_podman_names_in_its_boot_id_error_is_removed_too(self):
        # seen on a Mac after local-up: "current system boot ID differs from cached boot ID ... delete /tmp/podman-run-1000/containers and
        # /tmp/podman-run-1000/libpod/tmp": step 8 only cleared /tmp/storage-run-<uid>, so the service never started
        lr = os.path.join(self.base, "podman-run")
        os.makedirs(os.path.join(lr, "libpod", "tmp"))
        os.makedirs(os.path.join(lr, "containers"))
        p = self.run_ready()
        self.assertFalse(os.path.exists(lr), "the stale folder must be gone")
        self.assertIn(lr, self.serve_log())
        self.stop(p)

    def test_a_state_folder_that_cannot_hold_a_socket_gets_the_service_on_the_box_disk(self):
        # a Mac: the workspace is a virtiofs share, a stale podman.sock in it cannot be seen or removed and Podman cannot bind there ("operation not supported")
        p = self.run_ready(SWARMBOX_TEST_NO_STATE_SOCKET="1")
        fb = os.path.join(self.base, "fallback.sock")
        self.assertIn("cannot hold a unix socket", self.serve_log())
        self.assertTrue([c for c in self.calls() if c.startswith("podman system service") and fb in c], self.calls())
        self.stop(p)

    def test_a_state_folder_that_holds_sockets_keeps_the_service_where_it_was(self):
        p = self.run_ready()
        self.assertNotIn("cannot hold a unix socket", self.serve_log())
        self.assertTrue([c for c in self.calls() if c.startswith("podman system service") and "podman.sock" in c], self.calls())
        self.stop(p)

    def test_a_serve_test_never_points_step_8_at_the_real_runtime_folder_of_podman(self):
        # step 8 removes this folder: by default the real /tmp/storage-run-<uid> of whatever box runs the tests (the gate once wiped a live box's)
        env = self.env()
        self.assertEqual(os.path.dirname(env["SWARMBOX_TEST_PODMAN_RUNROOT"]), self.base)
        self.assertEqual(os.path.dirname(env["SWARMBOX_TEST_PODMAN_LIBPOD_RUN"]), self.base)
        self.assertEqual(env["HOME"], self.home)
        self.assertTrue(self.home.startswith(self.base))

    def serve_with_marker(self, fuse, content="true"):
        """A serve (the one before it is over) whose graph root has the fuse-overlayfs marker `content`; `fuse` is the path that
        stands for /dev/fuse. Returns the path of the marker; the serve ends in the cleanup of the test."""
        self.fresh()
        graph = os.path.join(self.base, "graphroot")
        shutil.rmtree(graph, True)
        marker = os.path.join(graph, "overlay", ".has-mount-program")
        os.makedirs(os.path.dirname(marker))
        put(marker, content)
        p = self.run_ready(SWARMBOX_TEST_PODMAN_GRAPHROOT=graph, SWARMBOX_TEST_FUSE=fuse, FAKE_MARKER=marker,
                           SWARMBOX_TEST_PODMAN_RUNROOT=os.path.join(self.base, "never-there"))
        self.stop(p)
        return marker

    def test_without_a_usable_fuse_the_stale_marker_is_removed_before_the_service_starts(self):
        # one probe of native overlay that fails on another graph root (the cache is shared by all of them) makes Podman fall back to
        # fuse-overlayfs and leave .has-mount-program = true for good: every later run died with "fuse: device not found" (a real box)
        os.mkdir(os.path.join(self.base, "dir-not-device"))
        for label, fuse in (("no such path", "no-such-fuse"), ("not a character device", "dir-not-device")):
            with self.subTest(label):
                marker = self.serve_with_marker(os.path.join(self.base, fuse))
                self.assertFalse(os.path.exists(marker))
                self.assertEqual(read(os.path.join(self.fake, "marker.seen")), "no", "the marker must be gone when the service starts")
                self.assertIn("removed the stale marker", self.serve_log())

    def test_a_usable_fuse_device_or_a_marker_that_says_false_leaves_the_marker_alone(self):
        for label, fuse, content in (("usable fuse", "/dev/null", "true"), ("marker false", "/nonexistent-fuse", "false")):
            with self.subTest(label):   # /dev/null is a character device the agent can open: it stands for /dev/fuse
                marker = self.serve_with_marker(fuse, content)
                self.assertEqual(read(marker), content)
                self.assertNotIn("stale marker", self.serve_log())


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
                self.fresh()
                setup()
                p = self.run_ready()
                self.assertEqual(self.marker(), "warnings=1", label)
                lines = self.health_lines()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(word, lines[0].lower())
                # ttyd is started by its supervisor in the background, about when the marker appears: wait for the call
                self.assertTrue(wait_for(lambda: any(c.startswith("ttyd ") for c in self.calls())), "ttyd must still start: %s" % label)
                self.stop(p)

    def test_with_installs_run_after_the_marker_in_order(self):
        p = self.run_ready(SWARMBOX_WITH="claude, opencode")
        self.assertTrue(wait_for(lambda: "install opencode saw-ready" in self.calls()), self.calls())
        installs = [c for c in self.calls() if c.startswith("swarmbox-addon install ")]
        self.assertEqual(installs, ["swarmbox-addon install claude", "swarmbox-addon install opencode"])
        self.assertIn("install claude saw-ready", self.calls())
        self.stop(p)


class SupervisorCase(ServeCase):
    """The policy both supervisors share (supervise_one): five exits within a minute and it gives up, idle, until USR1 restarts it by hand."""
    NAME = ""      # the fake's file prefix: ttyd or bus

    def starts(self):
        return len(read(os.path.join(self.fake, self.NAME + ".starts")).split())

    def sup_pid(self):
        s = read(os.path.join(self.run_dir, self.SUP_PID)).strip()
        return int(s) if s.isdigit() else None


class Supervisor(SupervisorCase):
    """The ttyd supervisor."""
    NAME = "ttyd"
    SUP_PID = "web-supervisor.pid"

    def test_crash_loop_gives_up_after_five_exits_stays_alive_and_a_restart_by_hand_starts_it_again(self):
        put(os.path.join(self.fake, "ttyd.mode"), "crash")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10), self.health_lines())
        time.sleep(0.3)
        self.assertEqual(self.starts(), 5)
        self.assertIn("web terminal keeps crashing; see web-terminal.log", self.health_lines())
        self.assertIsNone(p.poll(), "the box must stay up")
        self.assertTrue(alive(self.sup_pid()), "the supervisor must stay alive, idle")
        self.assertEqual(self.starts(), 5, "no restart while idle")
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


class BusStep(SupervisorCase):
    """Step 6b: the bus broker under supervise_one (the same policy as ttyd's), a W step."""
    NAME = "bus"
    SUP_PID = "bus-supervisor.pid"

    def test_a_broker_that_does_not_answer_is_one_warning_and_serve_goes_on(self):
        put(os.path.join(self.fake, "bus.noping"), "")
        p = self.run_ready(SWARMBOX_TEST_BUS_WAIT="0")
        self.assertEqual(self.marker(), "warnings=1")
        self.assertEqual(len(self.health_lines()), 1, self.health_lines())
        self.assertIn("the bus did not answer", self.health_lines()[0])
        self.assertTrue(wait_for(lambda: any(c.startswith("ttyd ") for c in self.calls())), "ttyd must still start")
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

    def test_exit_8_means_another_broker_runs_and_is_not_restarted_and_the_pid_file_goes(self):
        # `swarmbox-bus restart` sends USR1 to the pid in that file, and USR1 kills a process that does not handle it
        put(os.path.join(self.fake, "bus.mode"), "crash")
        put(os.path.join(self.fake, "bus.exit"), "8")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: "another one is running" in self.serve_log(), 5))
        self.assertTrue(wait_for(lambda: not os.path.exists(os.path.join(self.run_dir, "bus-supervisor.pid")), 3),
                        "bus-supervisor.pid is still there: %r" % read(os.path.join(self.run_dir, "bus-supervisor.pid")))
        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.health_lines(), [])
        self.stop(p)


class StaticOrder(unittest.TestCase):
    """The step markers of the script are in order."""

    def test_step_markers_are_in_the_serve_function_in_order(self):
        text = read(ENTRYPOINT)
        pos = [text.index("# step %s [" % n) for n in ("0", "1", "2", "3", "5", "6", "6b", "7", "8", "9", "10", "11", "12")]   # step 4 (migration) was removed
        self.assertEqual(pos, sorted(pos))
        self.assertLess(text.index("trap "), pos[0], "the handlers are installed before the first step")


if __name__ == "__main__":
    unittest.main()
