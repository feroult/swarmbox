"""Regression tests for what the soak and fault test of version 1 (tests/e2e/soak_v1.py, removed with tmux) found in the sysop: the audit file's limit and its rotation with several writers, an audit
line that cannot be written, a service that must not die on a full disk, the reconnect delay, the words of a brain that was killed.
No model, no multiplexer. Run with: python3 -W error tests/fast/test_sysop_soak.py
"""
import errno
import gc
import io
import os
import subprocess
import sys
import threading
import time
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
import test_sysop_mcp as tm  # noqa: E402
import test_sysop_service as tss  # noqa: E402

from swarmbox_sysop import audit, brain, busclient, cli, ipc, mcpserver, service, watch  # noqa: E402

WRITER = r"""
import sys
sys.path.insert(0, %(lib)r)
from swarmbox_sysop import audit
audit.MAX_FILE, audit.KEEP = %(max)d, %(keep)d
a = audit.Audit(%(path)r, "g", "cli")
for i in range(%(n)d):
    a.append("pad", i=i, text="x" * 80)
"""


class AuditLimit(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.path = os.path.join(self.e.dir, "events.jsonl")
        for name in ("MAX_FILE", "KEEP"):
            self.addCleanup(setattr, audit, name, getattr(audit, name))

    def files(self):
        return sorted(f for f in os.listdir(self.e.dir) if f.startswith("events.jsonl") and not f.endswith(".lock"))

    def test_the_limit_is_documented_and_bounds_the_total(self):
        self.assertEqual(audit.MAX_FILE, 8 << 20)
        self.assertEqual(audit.KEEP, 3)
        self.assertIn("(KEEP + 1) * MAX_FILE = 32 MiB", audit.__doc__)
        self.assertIn("8 MiB", audit.__doc__)

    def test_old_files_move_up_and_the_oldest_is_deleted(self):
        audit.MAX_FILE, audit.KEEP = 1500, 3
        a = audit.Audit(self.path, "g", "cli")
        for i in range(120):
            a.append("pad", i=i, text="x" * 60)
        self.assertEqual(self.files(), ["events.jsonl", "events.jsonl.1", "events.jsonl.2", "events.jsonl.3"], "never more than KEEP old files")
        last = [e["i"] for e in audit.read(self.path)]
        newer = [e["i"] for e in audit.read(self.path + ".1")]
        older = [e["i"] for e in audit.read(self.path + ".3")]
        self.assertEqual(last[-1], 119)
        self.assertGreater(min(last), max(newer), ".1 holds what came just before the current file")
        self.assertGreater(min(newer), max(older), "and .3 the oldest of the kept ones")
        self.assertTrue(all(os.path.getsize(os.path.join(self.e.dir, f)) < 1500 + 400 for f in self.files()), "no file is much over the limit")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.path + ".2").st_mode & 0o777, 0o600)

    def test_a_smaller_keep_prunes_the_files_that_are_left_over(self):
        audit.MAX_FILE, audit.KEEP = 1000, 5
        a = audit.Audit(self.path, "g", "cli")
        for i in range(120):
            a.append("pad", i=i, text="x" * 60)
        self.assertEqual(len(self.files()), 6)
        audit.KEEP = 2
        for i in range(30):
            a.append("pad", i=i, text="x" * 60)
        self.assertLessEqual(len(self.files()), 3, self.files())

    def test_two_writers_do_not_throw_a_generation_away(self):
        """the old rotation (stat, then rename) let two processes that saw the file too big both rename it: the second one replaced the .1 that
        held the first one's whole file. With a lock and a second look, KEEP big enough keeps every line."""
        procs = [subprocess.Popen([sys.executable, "-c", WRITER % {"lib": ss.LIB, "max": 6000, "keep": 500, "path": self.path, "n": 400}],
                                  stdin=subprocess.DEVNULL) for _ in range(5)]
        for p in procs:
            self.assertEqual(p.wait(60), 0)
        total = sum(len(audit.read(os.path.join(self.e.dir, f))) for f in self.files())
        self.assertEqual(total, 5 * 400, "every line is in some file (%s)" % self.files())
        self.assertGreater(len(self.files()), 10, "the test did rotate")

    def test_append_never_raises_and_says_false(self):
        a = audit.Audit(os.path.join(self.e.dir, "no", "such", "events.jsonl"))
        self.assertFalse(a.append("pad"))
        with mock.patch.object(audit.os, "write", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            self.assertFalse(audit.Audit(self.path).append("pad"))

    def test_a_line_that_cannot_be_written_is_said_once_a_minute(self):
        err = io.StringIO()
        audit._last_warning[0] = 0.0
        with mock.patch.object(audit.os, "write", side_effect=OSError(errno.ENOSPC, "No space left on device")), mock.patch.object(sys, "stderr", err):
            a = audit.Audit(self.path)
            for _ in range(5):
                a.append("pad")
        self.assertEqual(err.getvalue().count("cannot write"), 1)
        self.assertIn("No space left on device", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_require_raises_audit_error_that_says_what_to_do(self):
        with mock.patch.object(audit.os, "write", side_effect=OSError(errno.ENOSPC, "No space left on device")), mock.patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(audit.AuditError) as cm:
                audit.Audit(self.path).require("pad")
        self.assertIn("cannot be written", str(cm.exception))
        self.assertTrue(audit.Audit(self.path).append("pad"), "and it works again when the disk has room")


class McpWithoutAudit(tm.Rig):
    """a tool that types is not run when its record cannot be written; the tools that only read go on"""

    def failing(self):
        return mock.patch.object(audit.Audit, "_write", side_effect=OSError(errno.ENOSPC, "No space left on device"))

    def test_run_and_input_type_nothing_when_the_audit_line_cannot_be_written(self):
        with self.failing(), mock.patch.object(sys, "stderr", io.StringIO()):
            t1 = self.fail("run", tab="@1", command="echo hi")
            t2 = self.fail("input", tab="@1", text="{Esc}")
        self.assertEqual(self.tabs.sent, [], "nothing was typed")
        for t in (t1, t2):
            self.assertIn("nothing was typed", t)
            self.assertIn("audit file cannot be written", t)
            self.assertIn("disk", t)
            self.assertNotIn("Traceback", t)
        self.ok("run", tab="@1", command="echo hi")             # and it works again once there is room
        self.assertEqual(len(self.tabs.sent), 1)

    def test_reading_and_saying_go_on_without_the_audit(self):
        with self.failing(), mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertIn("repos", self.ok("box_state"))
            self.ok("read_tab", tab="@1")
            self.ok("say", text="the disk is full")
            self.ok("done", summary="stopped")


class ServiceOnAFullDisk(tss.Base):
    def test_a_disk_that_refuses_writes_does_not_end_the_service(self):
        svc = self.start()
        real = ipc.write_json
        broken = threading.Event()

        def write_json(path, obj):
            if broken.is_set() and "/goals/" in path:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(path, obj)
        with mock.patch.object(ipc, "write_json", write_json), mock.patch.object(audit.os, "write", side_effect=OSError(errno.ENOSPC, "No space left on device")), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            broken.set()
            ids = [self.goal("goal %d" % i) for i in range(3)]
            ss.wait_for(lambda: not svc.queue and svc.current is None, 20)
            self.assertTrue(self.thread.is_alive(), "the service is still running")
            broken.clear()
        gid = self.goal("after the disk had room")
        st = self.wait_state(gid)
        self.assertEqual(st["state"], "done", st)
        self.assertTrue(self.thread.is_alive())


class ServiceMainLoop(tss.Base):
    fast_loop = True

    def test_an_error_in_one_turn_of_the_main_loop_is_logged_and_the_loop_goes_on(self):
        svc = self.start()
        logs = []
        svc.log = logs.append
        real = svc.poll_stop
        calls = [0]

        def poll_stop():
            calls[0] += 1
            if calls[0] == 3:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real()
        svc.poll_stop = poll_stop
        self.assertTrue(ss.wait_for(lambda: calls[0] > 8, 15), "the loop kept turning")
        self.assertTrue(self.thread.is_alive())
        self.assertTrue(any("internal error in the main loop" in m and "No space left" in m for m in logs), logs)
        gid = self.goal("still works")
        self.assertEqual(self.wait_state(gid)["state"], "done")


ROTATE = r"""
import os, sys
sys.path.insert(0, %(lib)r)
from swarmbox_sysop import cli, paths
pth = paths.Paths().make()
fd = cli._open_log(pth)
os.dup2(fd, 1)
os.dup2(fd, 2)
os.close(fd)
print("before the rotation", flush=True)
print("rotated:", cli.rotate_log(pth), flush=True)
print("after the rotation", flush=True)
print("again:", cli.rotate_log(pth), flush=True)
"""


class LogRotation(unittest.TestCase):
    def test_the_log_of_the_daemon_is_rotated_while_it_runs_and_output_follows_the_new_file(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        pth = e.paths.make()
        with open(pth.log, "w") as f:
            f.write("x" * ((1 << 20) + 10) + "\n")
        env = dict(os.environ, **e.env)
        r = subprocess.run([sys.executable, "-c", ROTATE % {"lib": ss.LIB}], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(pth.log) as f:
            new = f.read()
        with open(pth.log + ".1") as f:
            old = f.read()
        self.assertEqual(new, "rotated: True\nafter the rotation\nagain: False\n", "what is printed after the rotation goes to the new file")
        self.assertTrue(old.startswith("x" * 100) and old.endswith("before the rotation\n"), "the old one holds what came before")
        self.assertEqual(os.stat(pth.log).st_mode & 0o777, 0o600)



class Housekeeping(tss.Base):
    fast_loop = True

    def test_the_service_runs_the_housekeeping_of_its_main_loop(self):
        old = service.HOUSEKEEPING
        service.HOUSEKEEPING = 0.05
        self.addCleanup(setattr, service, "HOUSEKEEPING", old)
        calls = []
        svc = self.start()
        svc.housekeeping = lambda: calls.append(1)
        self.assertTrue(ss.wait_for(lambda: len(calls) >= 3, 10), calls)
        logs = []
        svc.log = logs.append
        svc.housekeeping = lambda: 1 / 0               # a housekeeping that fails is one failed turn, not the end: the loop turns again
        self.assertTrue(ss.wait_for(lambda: len([m for m in logs if "ZeroDivisionError" in m]) >= 2, 10), logs)
        self.assertTrue(self.thread.is_alive())


class ClockJumps(unittest.TestCase):
    """a wall clock that jumps back (NTP, a laptop that wakes up) must not stretch a countdown or the time budget of a goal: the server of a goal runs on
    the steady clock (the countdown and the budget of the Server follow the clock it is given: tests/fast/test_sysop_mcp.py)"""

    def test_the_steady_clock_follows_the_monotonic_clock_not_the_wall_clock(self):
        real = time.time
        clock = mcpserver.steady_clock()
        t0 = clock()
        with mock.patch.object(time, "time", lambda: real() - 3600):
            t1 = clock()
        self.assertAlmostEqual(t1, t0, delta=1.0, msg="a jump of the wall clock is not seen")
        self.assertGreaterEqual(clock(), t1)

    def test_the_mcp_process_gives_the_server_the_steady_clock(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        seen = {}

        class Server:
            def __init__(self, ctx, **kw):
                seen.update(kw)

            def serve(self, fin, fout):
                pass
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)           # main() leaves its mcp.log open: the process ends right after
            with mock.patch.object(mcpserver, "Server", Server):
                self.assertEqual(mcpserver.main(dict(e.env)), 0)
            clock = seen.pop("clock")
            seen.clear()
            gc.collect()
        real = time.time
        t0 = clock()
        with mock.patch.object(time, "time", lambda: real() - 3600):
            self.assertAlmostEqual(clock(), t0, delta=1.0)


class BrainClock(unittest.TestCase):
    def test_the_time_budget_of_a_goal_is_not_stretched_by_a_wall_clock_that_jumps_back(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        gdir = e.paths.make().goal_dir("g1")
        os.makedirs(gdir)
        real, offset = time.time, [0.0]
        clock = lambda: real() + offset[0]
        threading.Timer(0.15, lambda: offset.__setitem__(0, -3600.0)).start()
        which = brain.shutil.which
        with mock.patch.object(brain.shutil, "which", lambda n, path=None: None if n == "timeout" else which(n, path=path)):        # without the `timeout` wrapper, which counts by itself
            t0 = time.monotonic()
            res = brain.run(e.cfg(max_seconds=5), "goal", "cli", gdir, ["sleep", "30"], {}, lambda: False, lambda: None, clock() + 0.6, clock=clock)
        self.assertLess(time.monotonic() - t0, 8, "the brain ran on after its budget because the clock went back")
        self.assertEqual(res.outcome, "failed")
        self.assertIn("time budget", res.error)


class Words(unittest.TestCase):
    def test_a_goal_that_was_not_sent_is_said_in_words_not_codes_or_paths(self):
        for code, text in (("no_subscriber", "sysop is not running"), ("bus_down", "starts it again within seconds"), ("bus_closed", "starts it again within seconds"),
                           ("busy", "busy with another goal"), ("timeout", "did not answer in time")):
            w = busclient.words(busclient.BusError(code, "the bus is not running (/tmp/swarmbox/bus.sock)"))
            self.assertIn(text, w)
            if "_" in code:
                self.assertNotIn(code, w)
            self.assertNotIn("/tmp", w)
        self.assertEqual(busclient.words(busclient.BusError("too_large", "the request is longer than the bus accepts")), "too_large: the request is longer than the bus accepts")

    def test_the_key_g_says_it(self):
        class Down:
            def pub(self, *a, **k):
                raise busclient.BusError("bus_down", "the bus is not running (/tmp/swarmbox/bus.sock)")
        out = io.StringIO()
        rc = cli.prompt_goal(Down(), "panel", inp=io.StringIO("list the tabs\n\n"), out=out, topic="goal")
        self.assertEqual(rc, 3)
        self.assertIn("the goal was not sent: the bus is not answering (the box starts it again within seconds). Press Enter.", out.getvalue())

    def test_goal_on_the_command_line_names_what_to_do(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        env = dict(os.environ, **e.env)
        env["PYTHONPATH"] = ss.LIB
        r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "goal", "list the tabs"], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 4)
        self.assertIn("the bus is not running", r.stderr)
        self.assertIn("swarmbox-bus restart", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class StatusWords(unittest.TestCase):
    def status(self, e):
        env = dict(os.environ, **e.env)
        env["PYTHONPATH"] = ss.LIB
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "status"], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)

    def test_status_says_what_to_do_when_the_service_is_down_and_when_the_watcher_gave_up(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        pth = e.paths.make()
        r = self.status(e)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not running", r.stdout)
        self.assertIn("again after a crash", r.stdout)
        self.assertIn("swarmbox-addon prepare", r.stdout)
        with open(pth.crashloop, "w") as f:
            f.write("the sysop service keeps crashing (killed by signal 9); see serve.log\n")
        r = self.status(e)
        self.assertEqual(r.returncode, 1)
        self.assertIn("keeps crashing (killed by signal 9); see serve.log. Start it again: swarmbox-addon prepare", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)


class FullStream:
    """standard error when serve.log is on a full disk: every write fails"""

    def write(self, s):
        raise OSError(errno.ENOSPC, "No space left on device")

    def flush(self):
        raise OSError(errno.ENOSPC, "No space left on device")


class LogOnAFullDisk(tss.Base):
    """found by the soak test: on a full disk the service died of its own log line (print to a stderr that cannot be written, inside the handler of an
    earlier failure)"""

    def test_a_log_that_cannot_be_written_does_not_end_the_service(self):
        svc = ss.fast_cond(service.Service(self.e.cfg(countdown=0), self.e.paths, backoff=(0.05, 0.3)))     # the default log: standard error
        self.svc = svc
        real = svc.poll_stop
        calls = [0]

        def poll_stop():
            calls[0] += 1
            if calls[0] in (3, 4, 5):
                raise OSError(errno.ENOSPC, "No space left on device")
            return real()
        svc.poll_stop = poll_stop
        with mock.patch.object(sys, "stderr", FullStream()):
            self.thread = threading.Thread(target=svc.run, daemon=True)
            self.thread.start()
            self.addCleanup(self.end)
            self.assertTrue(svc.wait_ready(10))
            self.assertTrue(ss.wait_for(lambda: calls[0] > 12, 20), "the main loop kept turning")
            self.assertTrue(self.thread.is_alive(), "the service is alive although nothing could be logged")
        buf = io.StringIO()
        with mock.patch.object(sys, "stderr", buf):
            svc.log("a line again")           # with a standard error that works it logs
        self.assertIn("a line again", buf.getvalue())

    def test_the_watcher_logs_the_same_way(self):
        with mock.patch.object(sys, "stderr", FullStream()):
            watch.Watcher.stderr_log("a line that cannot be written")


class FullDiskEnds(tss.Base):
    def test_the_end_of_a_goal_that_the_disk_refused_is_written_when_there_is_room_again(self):
        """found by the soak test: a goal whose end could not be written stayed `running` in its state.json for ever (the panel showed a goal that was long over)"""
        old = service.RETRY_WRITES
        service.RETRY_WRITES = 0.05
        self.addCleanup(setattr, service, "RETRY_WRITES", old)
        hold, release = self.gate()
        self.script([{"tool": "box_state"}, hold, {"tool": "done", "args": {"summary": "finished"}}])
        svc = self.start()
        real = svc.write_goal
        full = threading.Event()
        refused = []

        def write_goal(goal):
            if full.is_set():
                refused.append(1)
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(goal)
        svc.write_goal = write_goal
        gid = self.goal("a goal that ends on a full disk")
        self.assertTrue(ss.wait_for(lambda: (self.state(gid) or {}).get("state") == "running", 20))
        full.set()                                   # the disk fills while the goal works
        release()
        self.assertTrue(ss.wait_for(lambda: gid in svc.unwritten, 20), "the service remembers the end it could not write")
        self.assertEqual(self.state(gid)["state"], "running", "this is what the panel would show")
        n = len(refused)
        self.assertTrue(ss.wait_for(lambda: len(refused) >= n + 2, 10), "it keeps trying while the disk is full")
        self.assertIn(gid, svc.unwritten)
        full.clear()
        got = ss.wait_for(lambda: (self.state(gid) or {}).get("state") == "failed", 10)
        self.assertTrue(got, self.state(gid))
        self.assertIn("the disk of the box is full", self.state(gid)["error"], "a goal whose state cannot be kept is ended, and says why once it can")
        self.assertEqual(svc.unwritten, {})
        self.assertTrue(self.thread.is_alive())


class DiskWords(unittest.TestCase):
    def test_a_full_disk_is_said_as_one(self):
        w = service.explain(OSError(errno.ENOSPC, "No space left on device"))
        self.assertIn("the disk of the box is full", w)
        self.assertIn("free some space and send the goal again", w)
        self.assertNotIn("Errno", w)
        self.assertEqual(service.explain(ValueError("boom")), "internal error: ValueError: boom")
        self.assertIn("full", service.explain(OSError(errno.EDQUOT, "Disk quota exceeded")))

    def test_a_failed_goal_on_an_almost_full_disk_says_so(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        with mock.patch.object(service.shutil, "disk_usage", lambda p: type("U", (), {"free": 100 << 10})()):
            self.assertTrue(service.disk_low(e.dir))
        with mock.patch.object(service.shutil, "disk_usage", lambda p: type("U", (), {"free": 500 << 20})()):
            self.assertFalse(service.disk_low(e.dir))
        with mock.patch.object(service.shutil, "disk_usage", side_effect=OSError("gone")):
            self.assertFalse(service.disk_low(e.dir))


class FailedGoalOnAFullDisk(tss.Base):
    def test_the_reason_of_a_failed_goal_names_the_disk_when_it_is_almost_full(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "crash"
        self.start()
        with mock.patch.object(service.shutil, "disk_usage", lambda p: type("U", (), {"free": 100 << 10})()):
            gid = self.goal("this brain crashes")
            st = self.wait_state(gid)
        self.assertEqual(st["state"], "failed")
        self.assertIn("the disk of the box is almost full: free some space", st["error"])
        self.assertIn("exited with status 3", st["error"])

    def test_a_failure_on_a_roomy_disk_and_a_success_on_a_full_one_do_not_name_the_disk(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "crash"
        self.start()
        gid = self.goal("this brain crashes on a roomy disk")
        st = self.wait_state(gid)
        self.assertEqual(st["state"], "failed")
        self.assertNotIn("almost full", st["error"])
        del os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"]
        with mock.patch.object(service.shutil, "disk_usage", lambda p: type("U", (), {"free": 100 << 10})()):
            st = self.wait_state(self.goal("this one works on a full disk"))
        self.assertEqual(st["state"], "done")
        self.assertNotIn("almost full", st["error"])


class Backoff(unittest.TestCase):
    def test_the_reconnect_delay_is_short_at_most_five_seconds(self):
        self.assertEqual(service.BACKOFF[0], 1.0)
        self.assertLessEqual(service.BACKOFF[1], 5.0, "the bus is on a unix socket of the same box, and a supervisor that gave up is restarted by hand")


class Limits(unittest.TestCase):
    def test_what_a_brain_may_write_is_bounded_by_the_folders_kept(self):
        self.assertLessEqual(brain.MAX_OUTPUT * 2 * service.KEEP_GOALS, 4 << 30, "50 folders of goals, two files each: a few GB at the very worst")


class BrainWords(unittest.TestCase):
    def test_a_killed_brain_is_said_as_killed_not_as_status_minus_nine(self):
        for code in (-9, 137):
            w = brain.exit_words(code)
            self.assertIn("killed (signal 9, KILL", w)
            self.assertNotIn("-9", w)
        self.assertEqual(brain.exit_words(-15), "was killed (signal 15, TERM)")
        self.assertIn("may be out of memory", brain.exit_words(-9))
        self.assertEqual(brain.exit_words(1), "exited with status 1")
        self.assertEqual(brain.exit_words(3), "exited with status 3")
        self.assertEqual(brain.exit_words(255), "exited with status 255")


class KilledBrainGoal(tss.Base):
    def test_the_goal_of_a_killed_brain_fails_with_a_message_a_person_can_read(self):
        self.script([{"tool": "box_state"}, {"sleep": 30}, {"tool": "done", "args": {"summary": "x"}}])
        self.start()
        gid = self.goal("long")
        pid = ss.wait_for(lambda: (self.state(gid) or {}).get("brain", {}).get("pid"), 15)
        self.assertTrue(pid)
        ss.wait_for(lambda: os.path.exists(os.path.join(self.e.paths.goals, gid, "calls.jsonl")), 15)
        os.kill(pid, 9)
        st = self.wait_state(gid, seconds=30)
        self.assertEqual(st["state"], "failed")
        self.assertIn("killed (signal 9, KILL", st["error"], st["error"])
        self.assertIn("it left no message", st["error"])
        self.assertNotIn("status -9", st["error"])


if __name__ == "__main__":
    unittest.main()
