"""`swarmbox-entrypoint serve`: the ordered steps, failures, readiness marker, health file, PID 1 signals and the two supervisors (the web
server, the bus broker), all against the fake environment of tests/support/serve_support.py.

A start of `serve` costs a fraction of a second, so the checks of one ordinary start share it (DefaultRun) and the other classes start
it again only with the one thing that is different.

Run with: python3 tests/fast/test_serve_steps.py   (needs bash; python3 is the fake podman)
"""
import concurrent.futures
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
        wait_for(lambda: read(os.path.join(cls.c.fake, "web.pid")).strip())
        cls.bus_pid = int(wait_for(lambda: read(os.path.join(cls.c.fake, "bus.pid")).strip()))
        cls.bus_sup = int(read(os.path.join(cls.c.run_dir, "bus-supervisor.pid")).strip())
        cls.marker = cls.c.marker()
        cls.health = cls.c.health_lines()
        cls.live_pids = [int(read(os.path.join(cls.c.fake, n)).strip()) for n in ("web.pid", "service.pid")]
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

    def test_the_steps_run_in_order_and_the_broker_does_not_wait_for_the_multiplexer(self):
        order = [self.first("swarmbox-pubkey --ensure"), self.first("swarmbox-addon link --user"), self.first("swarmbox-bus serve"),
                 self.first("swarmbox-addon prepare"), self.first("podman system service"), self.first("hc server start"),
                 self.first("swarmbox-web run")]
        self.assertEqual(order, sorted(order), self.calls)
        # with no terminal yet, step 9 opens the first one (a login shell)
        self.assertIn("/bin/bash -l", self.calls[self.first("hc run")])

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

    @classmethod
    def _run_scenario(cls, fn):
        c = ServeCase()
        c.setUp()
        try:
            res = fn(c)
        finally:
            c.doCleanups()
        return res

    @classmethod
    def setUpClass(cls):
        def s_stale_rr(c):
            rr = os.path.join(c.base, "storage-run")
            os.makedirs(os.path.join(rr, "libpod", "tmp"))
            put(os.path.join(rr, "libpod", "tmp", "alive"), "old boot id")
            p = c.run_ready(SWARMBOX_TEST_PODMAN_RUNROOT=rr)
            res = (os.path.exists(rr), c.serve_log(), c.calls())
            c.stop(p)
            return res

        def s_marker(c, fuse_spec, content="true"):
            if fuse_spec == "dir-not-device":
                fuse = os.path.join(c.base, "dir-not-device")
                os.mkdir(fuse)
            elif fuse_spec == "no-such-fuse":
                fuse = os.path.join(c.base, "no-such-fuse")
            else:
                fuse = fuse_spec
            graph = os.path.join(c.base, "graphroot")
            marker = os.path.join(graph, "overlay", ".has-mount-program")
            os.makedirs(os.path.dirname(marker))
            put(marker, content)
            p = c.run_ready(SWARMBOX_TEST_PODMAN_GRAPHROOT=graph, SWARMBOX_TEST_FUSE=fuse, FAKE_MARKER=marker,
                            SWARMBOX_TEST_PODMAN_RUNROOT=os.path.join(c.base, "never-there"))
            c.stop(p)
            return (os.path.exists(marker), read(marker), read(os.path.join(c.fake, "marker.seen")), c.serve_log())

        tasks = {
            "stale_rr": s_stale_rr,
            "no_such_fuse": lambda c: s_marker(c, "no-such-fuse"),
            "dir_not_dev": lambda c: s_marker(c, "dir-not-device"),
            "usable_fuse": lambda c: s_marker(c, "/dev/null", "true"),
            "marker_false": lambda c: s_marker(c, "/nonexistent-fuse", "false"),
        }
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            cls._res = {k: cls._run_scenario(fn) for k, fn in tasks.items()}
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                futs = {k: ex.submit(cls._run_scenario, fn) for k, fn in tasks.items()}
                cls._res = {k: f.result() for k, f in futs.items()}

    def setUp(self):
        pass

    def test_a_stale_runtime_folder_of_nested_podman_is_removed_before_the_service_starts(self):
        # after a host reboot nested Podman refused to start: its runtime folder held the old boot ID
        exists, log, calls = self._res["stale_rr"]
        self.assertFalse(exists, "the stale folder must be gone")
        self.assertIn("removed the runtime state of the previous run", log)
        self.assertTrue([c for c in calls if c.startswith("podman system service")])

    def test_a_serve_test_never_points_step_8_at_the_real_runtime_folder_of_podman(self):
        # step 8 removes this folder: by default the real /tmp/storage-run-<uid> of whatever box runs the tests (the gate once wiped a live box's)
        c = ServeCase()
        c.setUp()
        self.addCleanup(c.doCleanups)
        env = c.env()
        self.assertEqual(os.path.dirname(env["SWARMBOX_TEST_PODMAN_RUNROOT"]), c.base)
        self.assertEqual(os.path.dirname(env["SWARMBOX_TEST_PODMAN_LIBPOD_RUN"]), c.base)
        self.assertEqual(env["HOME"], c.home)
        self.assertTrue(c.home.startswith(c.base))

    def test_without_a_usable_fuse_the_stale_marker_is_removed_before_the_service_starts(self):
        # one probe of native overlay that fails on another graph root (the cache is shared by all of them) makes Podman fall back to
        # fuse-overlayfs and leave .has-mount-program = true for good: every later run died with "fuse: device not found" (a real box)
        for label, key in (("no such path", "no_such_fuse"), ("not a character device", "dir_not_dev")):
            with self.subTest(label):
                exists, _, seen, log = self._res[key]
                self.assertFalse(exists)
                self.assertEqual(seen, "no", "the marker must be gone when the service starts")
                self.assertIn("removed the stale marker", log)

    def test_a_usable_fuse_device_or_a_marker_that_says_false_leaves_the_marker_alone(self):
        for label, key, content in (("usable fuse", "usable_fuse", "true"), ("marker false", "marker_false", "false")):
            with self.subTest(label):   # /dev/null is a character device the agent can open: it stands for /dev/fuse
                _, text, _, log = self._res[key]
                self.assertEqual(text, content)
                self.assertNotIn("stale marker", log)


class PodmanServiceFolders(ServeCase):
    """Step 8 on a Mac: the second runtime folder Podman names in its boot ID error, and a state folder that cannot hold the service's
    socket (its own class, so that the runner runs these starts beside those of NestedPodmanState)."""

    @classmethod
    def _run_scenario(cls, fn):
        c = ServeCase()
        c.setUp()
        try:
            res = fn(c)
        finally:
            c.doCleanups()
        return res

    @classmethod
    def setUpClass(cls):
        def s_second_rr(c):
            lr = os.path.join(c.base, "podman-run")
            os.makedirs(os.path.join(lr, "libpod", "tmp"))
            os.makedirs(os.path.join(lr, "containers"))
            p = c.run_ready()
            res = (lr, os.path.exists(lr), c.serve_log())
            c.stop(p)
            return res

        def s_no_sock(c):
            p = c.run_ready(SWARMBOX_TEST_NO_STATE_SOCKET="1")
            res = (os.path.join(c.base, "fallback.sock"), c.serve_log(), c.calls())
            c.stop(p)
            return res

        def s_shared_fs(c):
            with open(os.path.join(c.fake, "stat"), "w") as f:
                f.write('#!/bin/sh\ncase "$*" in "-f -c %T "*) echo fuse ;; *) exec /usr/bin/stat "$@" ;; esac\n')
            os.chmod(os.path.join(c.fake, "stat"), 0o755)
            p = c.run_ready()
            res = c.serve_log()
            c.stop(p)
            return res

        def s_holds_sock(c):
            p = c.run_ready()
            res = (c.serve_log(), c.calls())
            c.stop(p)
            return res

        tasks = {"second_rr": s_second_rr, "no_sock": s_no_sock, "shared_fs": s_shared_fs, "holds_sock": s_holds_sock}
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            cls._res = {k: cls._run_scenario(fn) for k, fn in tasks.items()}
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                futs = {k: ex.submit(cls._run_scenario, fn) for k, fn in tasks.items()}
                cls._res = {k: f.result() for k, f in futs.items()}

    def setUp(self):
        pass

    def test_the_second_runtime_folder_podman_names_in_its_boot_id_error_is_removed_too(self):
        # seen on a Mac after local-up: "current system boot ID differs from cached boot ID ... delete /tmp/podman-run-1000/containers and
        # /tmp/podman-run-1000/libpod/tmp": step 8 only cleared /tmp/storage-run-<uid>, so the service never started
        lr, exists, log = self._res["second_rr"]
        self.assertFalse(exists, "the stale folder must be gone")
        self.assertIn(lr, log)

    def test_a_state_folder_that_cannot_hold_a_socket_gets_the_service_on_the_box_disk(self):
        # a Mac: the workspace is a virtiofs share, a stale podman.sock in it cannot be seen or removed and Podman cannot bind there ("operation not supported")
        fb, log, calls = self._res["no_sock"]
        self.assertIn("cannot hold a unix socket", log)
        self.assertTrue([c for c in calls if c.startswith("podman system service") and fb in c], calls)

    def test_a_state_folder_on_a_shared_file_system_gets_the_service_on_the_box_disk(self):
        # the bind probe passes on virtiofs; what fails is a stale socket from an earlier run. The file system type decides, whatever the probe says.
        self.assertIn("cannot hold a unix socket", self._res["shared_fs"])

    def test_a_state_folder_that_holds_sockets_keeps_the_service_where_it_was(self):
        log, calls = self._res["holds_sock"]
        self.assertNotIn("cannot hold a unix socket", log)
        self.assertTrue([c for c in calls if c.startswith("podman system service") and "podman.sock" in c], calls)


class WarnSteps(ServeCase):
    """Steps 4 to 10: failure writes a health line and continues (W); the marker carries the count."""

    @classmethod
    def _run_warn(cls, setup):
        c = ServeCase()
        c.setUp()
        try:
            setup(c)
            p = c.run_ready(SWARMBOX_TEST_HC_WAIT_SLEEP="0.01")
            web_ok = wait_for(lambda: any(x.startswith("swarmbox-web ") for x in c.calls()), 10, 0.01)
            res = (c.marker(), c.health_lines(), web_ok)
            c.stop(p)
            return res
        finally:
            c.doCleanups()

    @classmethod
    def _run_with(cls):
        c = ServeCase()
        c.setUp()
        try:
            p = c.run_ready(SWARMBOX_WITH="claude, opencode")
            saw = wait_for(lambda: "install opencode saw-ready" in c.calls(), 10, 0.01)
            calls = c.calls()
            c.stop(p)
            return saw, calls
        finally:
            c.doCleanups()

    @classmethod
    def setUpClass(cls):
        cases = [
            ("step 5 ssh key", lambda c: put(os.path.join(c.fake, "swarmbox-pubkey.exit"), "1"), "ssh"),
            ("step 8 service", lambda c: put(os.path.join(c.fake, "service.mode"), "fail"), "podman"),
            ("step 9 herdr-core", lambda c: put(os.path.join(c.fake, "hc.exit"), "1"), "herdr"),
        ]
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            cls._warn_res = [(label, word, cls._run_warn(setup)) for label, setup, word in cases]
            cls._with_res = cls._run_with()
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futs = [(label, word, ex.submit(cls._run_warn, setup)) for label, setup, word in cases]
                f_with = ex.submit(cls._run_with)
                cls._warn_res = [(label, word, f.result()) for label, word, f in futs]
                cls._with_res = f_with.result()

    def setUp(self):
        pass

    def test_each_w_step_failure_is_one_health_line_and_serve_continues(self):
        for label, word, (marker, lines, web_ok) in self._warn_res:
            with self.subTest(label):
                self.assertEqual(marker, "warnings=1", label)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(word, lines[0].lower())
                # the web server is started by its supervisor in the background, about when the marker appears: wait for the call
                self.assertTrue(web_ok, "the web server must still start: %s" % label)

    def test_with_installs_run_after_the_marker_in_order(self):
        saw, calls = self._with_res
        self.assertTrue(saw, calls)
        installs = [c for c in calls if c.startswith("swarmbox-addon install ")]
        self.assertEqual(installs, ["swarmbox-addon install claude", "swarmbox-addon install opencode"])
        self.assertIn("install claude saw-ready", calls)


class SupervisorCase(ServeCase):
    """The policy both supervisors share (supervise_one): five exits within a minute and it gives up, idle, until USR1 restarts it by hand."""
    NAME = ""      # the fake's file prefix: web or bus

    def starts(self):
        return len(read(os.path.join(self.fake, self.NAME + ".starts")).split())

    def sup_pid(self):
        s = read(os.path.join(self.run_dir, self.SUP_PID)).strip()
        return int(s) if s.isdigit() else None


class Supervisor(SupervisorCase):
    """The web supervisor."""
    NAME = "web"
    SUP_PID = "web-supervisor.pid"

    def test_crash_loop_gives_up_after_five_exits_stays_alive_and_a_restart_by_hand_starts_it_again(self):
        put(os.path.join(self.fake, "web.mode"), "crash")
        p = self.run_ready()
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10, 0.01), self.health_lines())
        time.sleep(0.08)
        self.assertEqual(self.starts(), 5)
        self.assertIn("web terminal keeps crashing; see web-terminal.log", self.health_lines())
        self.assertIsNone(p.poll(), "the box must stay up")
        self.assertTrue(alive(self.sup_pid()), "the supervisor must stay alive, idle")
        self.assertEqual(self.starts(), 5, "no restart while idle")
        # fix the cause, then `swarmbox-web restart` (which sends USR1 to the supervisor)
        put(os.path.join(self.fake, "web.mode"), "run")
        os.kill(self.sup_pid(), signal.SIGUSR1)
        self.assertTrue(wait_for(lambda: self.starts() == 6, 5, 0.01), "the web server was not restarted")
        self.assertTrue(wait_for(lambda: not any("keeps crashing" in l for l in self.health_lines()), 3, 0.01), self.health_lines())
        self.assertTrue(wait_for(lambda: read(os.path.join(self.fake, "web.pid")).strip().isdigit(), 3, 0.01), "web.pid was not written")
        self.assertTrue(alive(int(read(os.path.join(self.fake, "web.pid")).strip())))
        # the count was reset: five more quick exits are needed before it gives up again
        put(os.path.join(self.fake, "web.mode"), "crash")
        os.kill(self.sup_pid(), signal.SIGUSR1)
        self.assertTrue(wait_for(lambda: any("keeps crashing" in l for l in self.health_lines()), 10, 0.01))
        time.sleep(0.08)
        self.assertEqual(self.starts(), 6 + 5)
        self.stop(p)


class BusStep(SupervisorCase):
    """Step 6b: the bus broker under supervise_one (the same policy as the web server's), a W step."""
    NAME = "bus"
    SUP_PID = "bus-supervisor.pid"

    @classmethod
    def _run_case(cls, fn):
        c = ServeCase()
        c.setUp()
        try:
            return fn(c)
        finally:
            c.doCleanups()

    @classmethod
    def _starts(cls, c):
        return len(read(os.path.join(c.fake, "bus.starts")).split())

    @classmethod
    def _sup_pid(cls, c):
        s = read(os.path.join(c.run_dir, "bus-supervisor.pid")).strip()
        return int(s) if s.isdigit() else None

    @classmethod
    def setUpClass(cls):
        def s_noping(c):
            put(os.path.join(c.fake, "bus.noping"), "")
            p = c.run_ready(SWARMBOX_TEST_BUS_WAIT="0")
            web_ok = wait_for(lambda: any(x.startswith("swarmbox-web ") for x in c.calls()), 10, 0.01)
            res = (c.marker(), c.health_lines(), web_ok)
            c.stop(p)
            return res

        def s_missing(c):
            os.unlink(os.path.join(c.fake, "swarmbox-bus"))
            p = c.run_ready()
            res = (c.marker(), c.health_lines(), os.path.exists(os.path.join(c.run_dir, "bus-supervisor.pid")))
            c.stop(p)
            return res

        def s_crash_loop(c):
            put(os.path.join(c.fake, "bus.mode"), "crash")
            p = c.run_ready()
            gave_up = wait_for(lambda: "the bus keeps crashing; see bus.log" in c.health_lines(), 10, 0.01)
            h_before = c.health_lines()
            time.sleep(0.08)
            starts_5 = cls._starts(c)
            log = c.serve_log()
            poll_up = p.poll()
            put(os.path.join(c.fake, "bus.mode"), "run")
            os.kill(cls._sup_pid(c), signal.SIGUSR1)
            restarted = wait_for(lambda: cls._starts(c) == 6, 5, 0.01)
            cleared = wait_for(lambda: not c.health_lines(), 3, 0.01)
            h_after = c.health_lines()
            c.stop(p)
            return (gave_up, h_before, starts_5, log, poll_up, restarted, cleared, h_after)

        def s_exit_8(c):
            put(os.path.join(c.fake, "bus.mode"), "crash")
            put(os.path.join(c.fake, "bus.exit"), "8")
            p = c.run_ready()
            saw_msg = wait_for(lambda: "another one is running" in c.serve_log(), 5, 0.01)
            pid_gone = wait_for(lambda: not os.path.exists(os.path.join(c.run_dir, "bus-supervisor.pid")), 3, 0.01)
            pid_content = read(os.path.join(c.run_dir, "bus-supervisor.pid"))
            res = (saw_msg, pid_gone, pid_content, cls._starts(c), c.health_lines())
            c.stop(p)
            return res

        tasks = {"noping": s_noping, "missing": s_missing, "crash_loop": s_crash_loop, "exit_8": s_exit_8}
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            cls._res = {k: cls._run_case(fn) for k, fn in tasks.items()}
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as ex:
                futs = {k: ex.submit(cls._run_case, fn) for k, fn in tasks.items()}
                cls._res = {k: f.result() for k, f in futs.items()}

    def setUp(self):
        pass

    def test_a_broker_that_does_not_answer_is_one_warning_and_serve_goes_on(self):
        marker, health, web_ok = self._res["noping"]
        self.assertEqual(marker, "warnings=1")
        self.assertEqual(len(health), 1, health)
        self.assertIn("the bus did not answer", health[0])
        self.assertTrue(web_ok, "the web server must still start")

    def test_a_missing_program_is_one_warning(self):
        marker, health, pid_exists = self._res["missing"]
        self.assertEqual(marker, "warnings=1")
        self.assertIn("swarmbox-bus not found", health[0])
        self.assertFalse(pid_exists)

    def test_crash_loop_gives_up_with_a_health_line_and_restart_by_signal_starts_again(self):
        gave_up, h_before, starts_5, log, poll_up, restarted, cleared, h_after = self._res["crash_loop"]
        self.assertTrue(gave_up, h_before)
        self.assertEqual(starts_5, 5)
        self.assertIn("waiting for 'swarmbox-bus restart'", log)
        self.assertIsNone(poll_up, "the box stays up")
        self.assertTrue(restarted)
        self.assertTrue(cleared, h_after)

    def test_exit_8_means_another_broker_runs_and_is_not_restarted_and_the_pid_file_goes(self):
        # `swarmbox-bus restart` sends USR1 to the pid in that file, and USR1 kills a process that does not handle it
        saw_msg, pid_gone, pid_content, starts, health = self._res["exit_8"]
        self.assertTrue(saw_msg)
        self.assertTrue(pid_gone, "bus-supervisor.pid is still there: %r" % pid_content)
        self.assertEqual(starts, 1)
        self.assertEqual(health, [])


class BusBackoff(ServeCase):
    """Step 6b: a killed broker is restarted after the real first backoff of one second (its own class: the second is spent beside BusStep)."""

    def test_a_killed_broker_is_started_again_with_the_backoff(self):
        p = self.run_ready(SWARMBOX_TEST_BACKOFF_SCALE="1")
        pid = int(wait_for(lambda: read(os.path.join(self.fake, "bus.pid")).strip(), 10, 0.01))
        t0 = time.time()
        os.kill(pid, signal.SIGKILL)
        restarted = wait_for(lambda: len(read(os.path.join(self.fake, "bus.starts")).split()) == 2, 5, 0.01)
        dt = time.time() - t0
        log = self.serve_log()
        self.stop(p)
        self.assertTrue(restarted, "the broker was not restarted")
        self.assertGreaterEqual(dt, 0.9, "the first retry is after 1 s")
        self.assertIn("bus exited; restarting in 1 s", log)


class StaticOrder(unittest.TestCase):
    """The step markers of the script are in order."""

    def test_step_markers_are_in_the_serve_function_in_order(self):
        text = read(ENTRYPOINT)
        pos = [text.index("# step %s [" % n) for n in ("0", "1", "2", "3", "5", "6", "6b", "7", "8", "9", "10", "11", "12")]   # step 4 (migration) was removed
        self.assertEqual(pos, sorted(pos))
        self.assertLess(text.index("trap "), pos[0], "the handlers are installed before the first step")


if __name__ == "__main__":
    unittest.main()
