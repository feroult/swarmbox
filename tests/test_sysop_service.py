"""The resident subscriber of the sysop and the CLI around it: goals from the bus, the queue and its limit, the states, the stop, a brain that
crashes, a bus that restarts, a service that is killed and started again, the private folders, swarmbox-sysop goal | status | stop.
A fake bus and the fake claude (tests/fixtures/sysop); no model, no tmux.
Run with: python3 -W error tests/test_sysop_service.py
"""
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import audit, cli, ipc, paths, service  # noqa: E402

DONE = [{"tool": "say", "args": {"text": "working"}}, {"tool": "done", "args": {"summary": "finished it"}}]
TERMINAL = ("done", "stopped", "failed")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


class Base(unittest.TestCase):
    cfg_over = {}
    read = staticmethod(read)

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.saved = dict(os.environ)
        self.addCleanup(self.restore_env)
        self.bus = ss.FakeBus(self.e.env["SB_BUS_SOCKET"])
        self.addCleanup(self.bus.stop)
        self.tabs = ss.FakeTabs(os.path.join(self.e.dir, "tabs.sock"))
        self.addCleanup(self.tabs.stop)
        self.out = os.path.join(self.e.dir, "out.jsonl")
        self.logf = os.path.join(self.e.dir, "claude.log")
        os.environ.update(self.e.env)
        os.environ.update(self.tabs.cmd_env)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_OUT"] = self.out
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_LOG"] = self.logf
        os.environ.pop("SWARMBOX_TEST_FAKE_CLAUDE_MODE", None)
        self.script(DONE)
        self.svc = None
        self.thread = None

    def restore_env(self):
        os.environ.clear()
        os.environ.update(self.saved)

    def script(self, steps):
        p = os.path.join(self.e.dir, "script.json")
        with open(p, "w") as f:
            json.dump(steps, f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = p

    def start(self, **over):
        kw = dict(dict(self.cfg_over, countdown=0), **over)
        self.svc = service.Service(self.e.cfg(**kw), self.e.paths, backoff=(0.05, 0.3), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.assertTrue(self.svc.wait_ready(10))
        self.assertTrue(self.bus.wait_subscriber(1, 10), "the service did not subscribe")
        self.addCleanup(self.end)
        return self.svc

    def end(self):
        if self.svc:
            self.svc.shutdown()
        if self.thread:
            self.thread.join(15)

    def goal(self, text="do it", source="cli", **kw):
        r = self.bus.publish_goal(text, source, **kw)
        self.assertTrue(r.get("ok"), r)
        return r["id"]

    def state(self, gid):
        return ipc.read_json(os.path.join(self.e.paths.goals, gid, "state.json"))

    def wait_state(self, gid, states=TERMINAL, seconds=30):
        got = ss.wait_for(lambda: (self.state(gid) or {}).get("state") in states, seconds)
        self.assertTrue(got, "goal %s: %s" % (gid, self.state(gid)))
        return self.state(gid)

    def status(self):
        return ipc.read_json(self.e.paths.status)

    def events(self, kind=None, goal=None):
        return [x for x in audit.read(self.e.paths.audit) if (kind is None or x["event"] == kind) and (goal is None or x["goal"] == goal)]


class SingleInstance(Base):
    def test_a_probe_of_the_lock_at_the_moment_of_the_start_does_not_cost_the_service(self):
        """`running()` (the panel, status, prepare.sh) takes the lock for an instant when it is free. A start that met it said "already running" and left no
        service at all (seen once in tests/e2e_sysop.py). The start tries again for a moment; a live service still refuses a second one."""
        svc = service.Service(self.e.cfg(countdown=0), self.e.paths, log=lambda m: None)
        svc.paths.make()
        probe = os.open(svc.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
        import fcntl
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        threading.Timer(0.3, lambda: os.close(probe)).start()
        t = time.time()
        self.assertTrue(svc.acquire(), "a lock held for 0.3 s by a probe is not a running service")
        self.assertGreaterEqual(time.time() - t, 0.25)
        os.close(svc.lock_fd)

    def test_a_live_service_still_refuses_a_second_one_after_the_wait(self):
        first = service.Service(self.e.cfg(countdown=0), self.e.paths, log=lambda m: None)
        self.assertTrue(first.acquire())
        self.addCleanup(os.close, first.lock_fd)
        second = service.Service(self.e.cfg(countdown=0), self.e.paths, log=lambda m: None)
        t = time.time()
        self.assertFalse(second.acquire(wait=0.3))
        self.assertGreaterEqual(time.time() - t, 0.28)
        self.assertTrue(service.running(self.e.paths))


class StatusFile(Base):
    def test_two_threads_writing_status_json_leave_the_newest_state(self):
        """Found by tests/e2e_sysop.py: the reader thread writes status.json when a goal arrives, the main thread when it starts the goal. The state was read
        before the lock-less write, so a slow writer could land LAST with the OLD state (queue 1, no current goal) and the panel showed `1 queued, idle`
        for the whole goal: no countdown, no approval prompt, nothing for the veto key to act on."""
        svc = service.Service(self.e.cfg(countdown=0), self.e.paths, log=lambda m: None)
        svc.paths.make()
        g = service.Goal("g1", "cli", "do it")
        svc.queue.append(g)
        real, slow_first, entered = ipc.write_json, [True], threading.Event()

        def slow_write(path, obj):
            if path == svc.paths.status and slow_first[0]:
                slow_first[0] = False
                entered.set()
                time.sleep(0.4)          # the reader is still writing when the main thread has taken the goal
            real(path, obj)
        ipc.write_json = slow_write
        self.addCleanup(setattr, ipc, "write_json", real)
        reader = threading.Thread(target=svc.status)
        reader.start()
        self.assertTrue(entered.wait(5))
        svc.queue.clear()                # the main thread takes the goal ...
        svc.current = g
        svc.status()                     # ... and writes the new state
        reader.join(5)
        st = self.status()
        self.assertEqual(st["current"], "g1", "the file shows the goal that runs, not the queue of a moment ago: %s" % st)
        self.assertEqual(st["queue"], [])


class Flow(Base):
    def test_a_goal_runs_to_the_end(self):
        self.start()
        gid = self.goal("list the tabs", "voice")
        st = self.wait_state(gid)
        self.assertEqual(st["state"], "done", st)
        self.assertEqual((st["source"], st["text"], st["summary"], st["error"]), ("voice", "list the tabs", "finished it", ""))
        self.assertEqual([s["text"] for s in st["say"]], ["working"])
        self.assertEqual([c["tool"] for c in st["calls"]], ["say", "done"])
        self.assertEqual(st["steps"], 0)
        self.assertEqual((st["brain"]["exit"], st["brain"]["turns"]), (0, 3))
        self.assertTrue(st["created"] <= st["started"] <= st["ended"])
        with open(self.logf) as f:
            self.assertEqual(json.load(f)["stdin"], "list the tabs\n")

    def test_the_audit_file_has_the_goal_its_states_and_the_end(self):
        self.start()
        gid = self.goal("hello world", "panel")
        self.wait_state(gid)
        ev = self.events(goal=gid)
        self.assertTrue(all(e["source"] == "panel" for e in ev))
        kinds = [(e["event"], e.get("state")) for e in ev if e["event"] in ("goal", "state", "brain")]
        self.assertEqual(kinds, [("goal", None), ("state", "queued"), ("state", "running"), ("brain", None), ("state", "done")])
        self.assertEqual([e["text"] for e in ev if e["event"] == "goal"], ["hello world"])
        self.assertEqual([e["tool"] for e in ev if e["event"] == "call"], ["say", "done"])
        self.assertEqual([e["event"] for e in ev if e["event"] in ("say",)], ["say"])

    def test_status_json(self):
        self.start()
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "connected", 5))
        st = self.status()
        self.assertEqual(st["pid"], os.getpid())
        self.assertEqual((st["bus"], st["current"], st["queue"]), ("connected", None, []))
        self.assertEqual(st["settings"]["autonomy"], "confirm-risky")
        self.assertEqual(st["settings"]["max_goals"], 5)
        self.assertEqual(st["version"], "1.0.0")

    def test_a_plain_text_body_is_a_goal(self):
        self.start()
        gid = self.goal(body="run the tests")
        self.assertEqual(self.wait_state(gid)["text"], "run the tests")

    def test_the_source_is_a_clean_label(self):
        self.start()
        for src, want in (("VOICE", "voice"), ("evil\nsource", "evil_source"), ("", "unknown"), ("x" * 100, "x" * 32)):
            gid = self.goal("x", src)
            self.assertEqual(self.wait_state(gid)["source"], want)

    def test_goals_run_one_at_a_time_in_order(self):
        self.script([{"sleep": 0.4}] + DONE)
        self.start()
        ids = [self.goal("g%d" % i) for i in range(3)]
        sts = [self.wait_state(i) for i in ids]
        starts = [s["started"] for s in sts]
        ends = [s["ended"] for s in sts]
        self.assertEqual(starts, sorted(starts))
        for i in range(2):
            self.assertLessEqual(ends[i], starts[i + 1] + 0.001, "one at a time")
        self.assertEqual([s["state"] for s in sts], ["done"] * 3)

    def test_the_state_while_it_runs_shows_the_queue_and_the_current_goal(self):
        self.script([{"sleep": 1.0}] + DONE)
        self.start()
        a, b = self.goal("first"), self.goal("second")
        self.assertTrue(ss.wait_for(lambda: (self.status() or {}).get("current") == a and [q["id"] for q in self.status()["queue"]] == [b], 10), self.status())
        self.assertEqual(self.state(a)["state"], "running")
        self.assertEqual(self.state(b)["state"], "queued")
        self.assertEqual(self.status()["queue"][0]["text"], "second")
        self.wait_state(b)
        self.assertTrue(ss.wait_for(lambda: self.status()["current"] is None and not self.status()["queue"], 5))

    def test_the_state_waiting_approval_with_the_pending_action(self):
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "rm -rf build"}}, {"tool": "say", "args": {"text": "not allowed"}},
                     {"tool": "done", "args": {"summary": "refused"}}])
        self.start(approval_timeout=2)
        gid = self.goal("clean the build folder")
        st = self.wait_state(gid, ("waiting_approval",))
        self.assertEqual((st["pending"]["risk"], st["pending"]["mode"], st["pending"]["text"], st["pending"]["tab"]), ("high", "approve", "rm -rf build", "@1"))
        end = self.wait_state(gid)
        self.assertEqual(end["state"], "done")
        self.assertIsNone(end["pending"])
        self.assertEqual(self.tabs.sent, [], "never approved, never typed")
        self.assertEqual([c["is_error"] for c in end["calls"]], [True, False, False])

    def test_a_high_risk_goal_with_a_panel_that_approves(self):
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "rm -rf build"}}, {"tool": "done", "args": {"summary": "removed"}}])
        self.start(approval_timeout=20)
        gid = self.goal("clean")
        st = self.wait_state(gid, ("waiting_approval",))
        gdir = os.path.join(self.e.paths.goals, gid)
        ipc.write_json(os.path.join(gdir, "decision.json"), {"id": st["pending"]["id"], "decision": "approve", "by": "panel", "word": "run"})
        self.assertEqual(self.wait_state(gid)["state"], "done")
        self.assertEqual(self.tabs.sent, [("@1", {"run": "rm -rf build"})])


class Rejections(Base):
    def test_the_queue_limit(self):
        self.script([{"sleep": 1.5}] + DONE)
        self.start(max_goals=2)
        ids = [self.goal("g%d" % i) for i in range(5)]
        self.assertTrue(ss.wait_for(lambda: self.state(ids[4]) is not None, 5))
        self.assertTrue(ss.wait_for(lambda: self.state(ids[3]) is not None, 5))
        for i in (3, 4):
            st = self.state(ids[i])
            self.assertEqual(st["state"], "failed", st)
            self.assertIn("queue is full", st["error"])
        self.assertEqual(self.status()["rejected"], 2)
        self.assertEqual(len([e for e in self.events("rejected")]), 2)
        for i in (0, 1, 2):
            self.assertEqual(self.wait_state(ids[i])["state"], "done")
        self.assertEqual(self.tabs.sent, [])

    def test_the_default_limit_is_five(self):
        self.script([{"sleep": 2}] + DONE)
        self.start()
        ids = [self.goal("g%d" % i) for i in range(8)]       # 1 running + 5 waiting + 2 dropped
        self.assertTrue(ss.wait_for(lambda: self.state(ids[7]) is not None, 8))
        dropped = [i for i in ids if (self.state(i) or {}).get("state") == "failed"]
        self.assertEqual(len(dropped), 2, [(i, (self.state(i) or {}).get("state")) for i in ids])

    def test_bad_goals(self):
        self.start()
        cases = [({"text": ""}, "no text"), ({"text": "   "}, "no text"), ({"nope": 1}, "no text"), (5, "no text"), (None, "no text"), (["a"], "no text"),
                 ({"text": 5}, "no text"), ({"text": "x" * 5000}, "5000 characters")]
        for body, why in cases:
            r = self.bus.publish_goal("", body=body)
            self.assertTrue(r["ok"])
            gid = r["id"]
            self.assertTrue(ss.wait_for(lambda: self.state(gid), 5))
            st = self.state(gid)
            self.assertEqual(st["state"], "failed", body)
            self.assertIn(why, st["error"])
        self.assertEqual(self.tabs.sent, [])
        self.assertEqual(self.status()["queue"], [])

    def test_a_newer_envelope_version_and_garbage_are_ignored(self):
        self.start()
        with self.bus.lock:
            sub = self.bus.subs[0]
        sub.sendall(b'{"v":2,"id":"x","topic":"goal","body":{"text":"hi"}}\n')
        sub.sendall(b"this is not json\n")
        sub.sendall(b'[1,2]\n')
        gid = self.goal("after the garbage")
        self.assertEqual(self.wait_state(gid)["state"], "done")
        self.assertEqual(len(self.events("rejected")), 3)


class TopicAndGroup(Base):
    def test_the_defaults_are_the_topic_goal_and_the_group_sysop(self):
        self.start()
        self.assertEqual(self.bus.sub_reqs, [("goal", "sysop")])
        self.assertEqual(self.status()["settings"]["topic"], "goal")
        self.assertEqual(self.status()["settings"]["group"], "sysop")

    def test_the_service_listens_where_its_settings_say(self):
        self.start(topic="ops.goals", group="night")
        self.assertEqual(self.bus.sub_reqs, [("ops.goals", "night")])
        r = self.bus.publish_goal("on the default topic", topic="goal")
        self.assertEqual(r.get("err"), "no_subscriber", "nobody listens on `goal` now")
        gid = self.goal("on the topic of the setting", topic="ops.goals")
        self.assertEqual(self.wait_state(gid)["state"], "done")

    def test_a_reconnect_asks_for_the_same_topic_and_group(self):
        self.start(topic="ops", group="g")
        self.bus.stop()
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "down", 10))
        self.bus.start()
        self.assertTrue(self.bus.wait_subscriber(1, 10))
        self.assertEqual(set(self.bus.sub_reqs), {("ops", "g")})
        self.assertEqual(self.wait_state(self.goal("again", topic="ops"))["state"], "done")

    def test_two_sysops_of_a_group_share_the_goals_one_each(self):
        self.start()
        e2 = ss.Env()
        self.addCleanup(e2.cleanup)
        e2.env["SB_BUS_SOCKET"] = self.e.env["SB_BUS_SOCKET"]
        svc2 = service.Service(e2.cfg(countdown=0), e2.paths, backoff=(0.05, 0.3), log=lambda m: None)
        t2 = threading.Thread(target=svc2.run, daemon=True)
        t2.start()
        self.addCleanup(lambda: (svc2.shutdown(), t2.join(15)))
        self.assertTrue(svc2.wait_ready(10))
        self.assertTrue(self.bus.wait_subscriber(2, 10))
        ids = [self.goal("goal %d" % i) for i in range(4)]
        self.assertTrue(ss.wait_for(lambda: all((self.state(i) or {}).get("state") in TERMINAL for i in ids) or
                                    len([1 for x in audit.read(self.e.paths.audit) if x["event"] == "goal"]) +
                                    len([1 for x in audit.read(e2.paths.audit) if x["event"] == "goal"]) == 4, 20))
        mine = len([1 for x in audit.read(self.e.paths.audit) if x["event"] == "goal"])
        theirs = len([1 for x in audit.read(e2.paths.audit) if x["event"] == "goal"])
        self.assertEqual((mine, theirs), (2, 2), "round robin inside the group: each goal went to ONE sysop")


class Survival(Base):
    def test_a_crashing_brain_fails_its_goal_and_the_next_one_runs(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "crash"
        self.start()
        a = self.goal("first")
        st = self.wait_state(a)
        self.assertEqual(st["state"], "failed")
        self.assertIn("boom", st["error"])
        os.environ.pop("SWARMBOX_TEST_FAKE_CLAUDE_MODE")
        b = self.goal("second")
        self.assertEqual(self.wait_state(b)["state"], "done")
        self.assertTrue(self.thread.is_alive())

    def test_not_logged_in(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "notloggedin"
        self.start()
        st = self.wait_state(self.goal("x"))
        self.assertEqual(st["state"], "failed")
        self.assertIn("not logged in", st["error"])
        self.assertIn("/login", st["error"])

    def test_a_missing_brain(self):
        self.start(brain="no-such-brain-q --c {mcp_config}")
        st = self.wait_state(self.goal("x"))
        self.assertEqual(st["state"], "failed")
        self.assertIn("'no-such-brain-q' was not found", st["error"])

    def test_a_bug_inside_a_goal_fails_that_goal_only(self):
        self.start()
        orig = service.brain.build

        def boom(*a, **k):
            service.brain.build = orig
            raise RuntimeError("bug")
        service.brain.build = boom
        self.addCleanup(setattr, service.brain, "build", orig)
        a = self.goal("a")
        st = self.wait_state(a)
        self.assertEqual(st["state"], "failed")
        self.assertIn("internal error", st["error"])
        self.assertEqual(self.wait_state(self.goal("b"))["state"], "done")

    def test_the_bus_goes_away_and_comes_back(self):
        self.start()
        self.bus.stop()
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "down", 10), self.status())
        self.bus.start()
        self.assertTrue(self.bus.wait_subscriber(1, 10), "the service must reconnect by itself")
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "connected", 5))
        self.assertEqual(self.wait_state(self.goal("after the restart"))["state"], "done")

    def test_the_bus_is_not_there_at_the_start(self):
        self.bus.stop()
        self.svc = service.Service(self.e.cfg(countdown=0), self.e.paths, backoff=(0.05, 0.2), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.addCleanup(self.end)
        self.assertTrue(self.svc.wait_ready(10))
        time.sleep(0.4)
        self.assertEqual(self.status()["bus"], "down")
        self.bus.start()
        self.assertTrue(self.bus.wait_subscriber(1, 10))
        self.assertEqual(self.wait_state(self.goal("late"))["state"], "done")

    def test_the_bus_dies_in_the_middle_of_a_goal(self):
        self.script([{"sleep": 0.5}, {"tool": "list_tabs"}, {"tool": "say", "args": {"text": "x"}}] + DONE)
        self.start()
        gid = self.goal("long")
        self.wait_state(gid, ("running",))
        self.bus.stop()
        time.sleep(0.2)
        self.bus.start()
        st = self.wait_state(gid)
        self.assertEqual(st["state"], "done", st)
        self.assertTrue(ss.wait_for(lambda: self.bus.wait_subscriber(1, 1), 10))

    def test_the_audit_survives_the_service_and_is_appended_to(self):
        self.start()
        self.wait_state(self.goal("one"))
        n = len(self.events())
        self.end()
        self.start()
        self.wait_state(self.goal("two"))
        self.assertGreater(len(self.events()), n)
        self.assertEqual([e["text"] for e in self.events("goal")], ["one", "two"])

    def test_old_goal_folders_are_pruned(self):
        pth = self.e.paths.make()
        for i in range(60):
            d = os.path.join(pth.goals, "old%02d" % i)
            os.mkdir(d, 0o700)
            os.utime(d, (1000 + i, 1000 + i))
        self.start()
        names = os.listdir(pth.goals)
        self.assertEqual(len(names), service.KEEP_GOALS)
        self.assertIn("old59", names)
        self.assertNotIn("old00", names)


class Stopping(Base):
    def test_stop_ends_the_running_goal_kills_the_brain_and_drops_the_queue(self):
        self.script([{"tool": "list_tabs"}, {"sleep": 60}])
        self.start()
        a, b, c = self.goal("a"), self.goal("b"), self.goal("c")
        self.wait_state(a, ("running",))
        ss.wait_for(lambda: os.path.exists(self.logf), 10)
        with open(self.logf) as f:
            brain_pid = json.load(f)["pid"]
        t0 = time.time()
        ipc.request_stop(self.e.paths)
        self.assertEqual(self.wait_state(a)["state"], "stopped")
        self.assertLess(time.time() - t0, 8)
        for g in (b, c):
            st = self.state(g)
            self.assertEqual(st["state"], "stopped")
            self.assertIn("before it started", st["error"])
        self.assertTrue(ss.wait_for(lambda: not alive(brain_pid), 5), "the brain is gone")
        self.assertFalse(os.path.exists(self.e.paths.stop_request), "the request was taken")
        self.assertTrue(os.path.exists(os.path.join(self.e.paths.goals, a, "stopped")))
        self.assertTrue(ss.wait_for(lambda: self.status()["current"] is None, 5))
        self.assertEqual(self.status()["queue"], [])
        self.script(DONE)
        self.assertEqual(self.wait_state(self.goal("after"))["state"], "done", "the service goes on")
        self.assertIn("stop", [e.get("decision") for e in self.events("decision", a)])

    def test_stop_of_one_queued_goal_leaves_the_rest(self):
        self.script([{"sleep": 1.0}] + DONE)
        self.start()
        a, b, c = self.goal("a"), self.goal("b"), self.goal("c")
        self.wait_state(a, ("running",))
        ss.wait_for(lambda: len(self.status()["queue"]) == 2, 5)
        ipc.request_stop(self.e.paths, b)
        self.assertEqual(self.wait_state(b)["state"], "stopped")
        self.assertEqual(self.wait_state(a)["state"], "done")
        self.assertEqual(self.wait_state(c)["state"], "done")

    def test_stop_of_a_goal_that_is_not_running_does_not_hurt_the_current_one(self):
        self.script([{"sleep": 1.0}] + DONE)
        self.start()
        a = self.goal("a")
        self.wait_state(a, ("running",))
        ipc.request_stop(self.e.paths, "no-such-goal")
        self.assertEqual(self.wait_state(a)["state"], "done")

    def test_stop_while_idle_is_taken_and_harmless(self):
        self.start()
        ipc.request_stop(self.e.paths)
        self.assertTrue(ss.wait_for(lambda: not os.path.exists(self.e.paths.stop_request), 5))
        self.assertEqual(self.wait_state(self.goal("x"))["state"], "done")

    def test_a_damaged_stop_request_still_stops(self):
        self.script([{"sleep": 60}])
        self.start()
        a = self.goal("a")
        self.wait_state(a, ("running",))
        with open(self.e.paths.stop_request, "w") as f:
            f.write("{garbage")
        self.assertEqual(self.wait_state(a)["state"], "stopped")

    def test_stop_while_a_countdown_is_running(self):
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "ls"}}] + DONE)
        self.start(countdown=30)
        a = self.goal("a")
        self.wait_state(a, ("waiting_approval",))
        ipc.request_stop(self.e.paths)
        self.assertEqual(self.wait_state(a)["state"], "stopped")
        self.assertEqual(self.tabs.sent, [])

    def test_the_deadline_ends_a_goal(self):
        self.script([{"sleep": 60}])
        self.start(max_seconds=5)
        a = self.goal("a")
        st = self.wait_state(a, seconds=30)
        self.assertEqual(st["state"], "failed")
        self.assertIn("time budget", st["error"])


class Folders(Base):
    def test_folders_and_files_are_private(self):
        self.start()
        gid = self.goal("x")
        self.wait_state(gid)
        pth = self.e.paths
        for d in (pth.run, pth.state, pth.goals, os.path.join(pth.goals, gid)):
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700, d)
        for f in (pth.audit, pth.status, pth.pidfile, pth.lock, os.path.join(pth.goals, gid, "state.json"), os.path.join(pth.goals, gid, "context.json"),
                  os.path.join(pth.goals, gid, "mcp.json"), os.path.join(pth.goals, gid, "stream.jsonl"), os.path.join(pth.goals, gid, "calls.jsonl"),
                  os.path.join(pth.goals, gid, "say.jsonl"), os.path.join(pth.goals, gid, "done.json")):
            self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600, f)

    def test_a_loose_folder_is_tightened(self):
        pth = self.e.paths
        os.makedirs(pth.state, mode=0o755)
        os.chmod(pth.state, 0o755)
        pth.make()
        self.assertEqual(stat.S_IMODE(os.stat(pth.state).st_mode), 0o700)

    def test_a_link_in_the_way_is_refused(self):
        pth = self.e.paths
        os.makedirs(os.path.dirname(pth.state))
        os.symlink("/tmp", pth.state)
        with self.assertRaises(paths.SysopPathError):
            pth.make()

    def test_a_file_in_the_way_is_refused(self):
        pth = self.e.paths
        os.makedirs(os.path.dirname(pth.run))
        with open(pth.run, "w") as f:
            f.write("x")
        with self.assertRaises(paths.SysopPathError):
            pth.make()

    def test_the_folders_follow_the_rules_of_dirs_sh(self):
        self.assertEqual(paths.state_root({"HOME": "/h"}), "/h/.local/state/swarmbox")
        self.assertEqual(paths.state_root({"HOME": "/h", "XDG_STATE_HOME": "/x"}), "/x/swarmbox")
        self.assertEqual(paths.state_root({"HOME": "/h", "XDG_STATE_HOME": "rel"}), "/h/.local/state/swarmbox")
        self.assertEqual(paths.state_root({"HOME": "/h", "XDG_STATE_HOME": "/x/"}), "/x/swarmbox")
        self.assertEqual(paths.state_root({"SB_STATE_DIR": "/s"}), "/s")
        self.assertEqual(paths.run_root({}), "/tmp/swarmbox")
        self.assertEqual(paths.bus_socket({}), "/tmp/swarmbox/bus.sock")
        self.assertEqual(paths.bus_socket({"SB_RUN_DIR": "/r"}), "/r/bus.sock")
        self.assertEqual(paths.bus_socket({"SB_BUS_SOCKET": "/z.sock", "SB_RUN_DIR": "/r"}), "/z.sock")

    def test_a_goal_id_cannot_leave_the_folder(self):
        for bad, ok in (("../../etc", "etc"), ("a/b", "a_b"), ("..", "g"), ("", "g"), ("a b\n", "a_b_")):
            got = service.sanitize(bad, "g")
            self.assertNotIn("/", got)
            self.assertFalse(got.startswith("."))
            self.assertTrue(got)


class OwnProcess(Base):
    """the service as a real process: kill it, start it again, two at once, SIGTERM"""

    def spawn(self, extra_env=None, log=True):
        env = dict(dict(os.environ, PYTHONPATH=ss.LIB, SWARMBOX_SYSOP_COUNTDOWN="0"), **(extra_env or {}))
        args = [sys.executable, "-B", "-m", "swarmbox_sysop", "serve"] + (["--log"] if log else [])
        p = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if not log else subprocess.DEVNULL,
                             stderr=subprocess.PIPE if not log else subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.reap, p)
        return p

    @staticmethod
    def reap(p):
        if p.poll() is None:
            p.kill()
        p.wait()
        for s in (p.stdout, p.stderr):
            if s:
                s.close()

    def up(self, p):
        self.assertTrue(ss.wait_for(lambda: service.running(self.e.paths) and self.bus.subs, 15), "the service did not start")

    def test_kill_and_restart_loses_the_goal_in_flight_and_says_so(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "hang"
        p = self.spawn()
        self.up(p)
        gid = self.goal("this one will be lost", "voice")
        self.wait_state(gid, ("running",))
        ss.wait_for(lambda: os.path.exists(self.logf), 10)
        with open(self.logf) as f:
            brain_pid = json.load(f)["pid"]
        queued = self.goal("this one waits")
        ss.wait_for(lambda: self.state(queued), 5)
        os.kill(p.pid, signal.SIGKILL)
        p.wait()
        self.assertTrue(ss.wait_for(lambda: not alive(brain_pid), 10), "the brain of a dead service gets a signal from the kernel and goes")
        self.assertEqual(self.state(gid)["state"], "running", "nobody ended it yet")
        self.assertFalse(service.running(self.e.paths), "the lock of a dead service is gone")
        os.environ.pop("SWARMBOX_TEST_FAKE_CLAUDE_MODE")
        self.bus.stop()
        self.bus.start()
        p2 = self.spawn()
        self.up(p2)
        for g in (gid, queued):
            st = self.state(g)
            self.assertEqual(st["state"], "failed", st)
            self.assertIn("lost", st["error"])
            self.assertIn("not kept", st["error"])
        self.assertEqual(len(self.events("lost")), 2)
        self.assertEqual(self.wait_state(self.goal("and now a new one"))["state"], "done")

    def test_a_second_service_does_not_start_and_does_not_disturb_the_first(self):
        p = self.spawn()
        self.up(p)
        self.assertTrue(ss.wait_for(lambda: self.status(), 10))
        pid = ipc.read_json(self.e.paths.status)["pid"]
        p2 = self.spawn(log=False)
        out, err = p2.communicate(timeout=20)
        self.assertEqual(p2.returncode, 0)
        self.assertIn(b"already running", err)
        self.assertEqual(ipc.read_json(self.e.paths.status)["pid"], pid)
        self.assertIsNone(p.poll())
        with open(self.e.paths.pidfile) as f:
            self.assertEqual(int(f.read()), pid)
        self.assertEqual(self.wait_state(self.goal("still serving"))["state"], "done")

    def test_sigterm_ends_the_goal_in_flight_and_the_service_cleanly(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "hang"
        p = self.spawn()
        self.up(p)
        gid = self.goal("x")
        self.wait_state(gid, ("running",))
        ss.wait_for(lambda: os.path.exists(self.logf), 10)
        with open(self.logf) as f:
            brain_pid = json.load(f)["pid"]
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(20), 0)
        st = self.state(gid)
        self.assertEqual(st["state"], "stopped")
        self.assertIn("service was stopped", st["error"])
        self.assertFalse(alive(brain_pid))
        self.assertFalse(os.path.exists(self.e.paths.pidfile))
        self.assertFalse(service.running(self.e.paths))
        self.assertEqual(ipc.read_json(self.e.paths.status)["bus"], "stopped")

    def test_detached_mode_writes_its_log_and_holds_no_inherited_descriptor(self):
        r, w = os.pipe()
        env = dict(os.environ, PYTHONPATH=ss.LIB)
        p = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_sysop", "serve", "--log"], env=env, stdin=subprocess.DEVNULL, stdout=w, stderr=w,
                             pass_fds=(w,), start_new_session=True)
        os.close(w)
        self.addCleanup(self.reap, p)
        self.up(p)
        self.assertTrue(ss.wait_for(lambda: "serving" in self.read(self.e.paths.log), 10))
        self.assertEqual(stat.S_IMODE(os.stat(self.e.paths.log).st_mode), 0o600)
        os.set_blocking(r, False)
        got = None
        end = time.time() + 5
        while time.time() < end:
            try:
                got = os.read(r, 100)
                break
            except BlockingIOError:
                time.sleep(0.05)
        self.assertEqual(got, b"", "the pipe must be at EOF: the service must not hold it (a caller that waits for EOF would hang)")
        os.close(r)

    def test_bad_settings_stop_it_with_a_clear_line(self):
        for var, val in (("SWARMBOX_SYSOP_AUTONOMY", "yolo"), ("SWARMBOX_SYSOP_COUNTDOWN", "x"), ("SWARMBOX_SYSOP_MAX_STEPS", "0"),
                         ("SWARMBOX_SYSOP_BRAIN", "b {nope}"), ("SWARMBOX_SYSOP_MODEL", "a b"),
                         ("SWARMBOX_SYSOP_TOPIC", "Goal"), ("SWARMBOX_SYSOP_TOPIC", "a/b"), ("SWARMBOX_SYSOP_GROUP", "x" * 64), ("SWARMBOX_SYSOP_GROUP", "-g")):
            with self.subTest(var=var):
                p = self.spawn({var: val}, log=False)
                out, err = p.communicate(timeout=20)
                self.assertEqual(p.returncode, 2)
                self.assertIn(var.encode(), err)
                self.assertFalse(service.running(self.e.paths))


class Settings(unittest.TestCase):
    def test_topic_and_group_defaults_and_values(self):
        from swarmbox_sysop import config
        c = config.load({})
        self.assertEqual((c.topic, c.group), ("goal", "sysop"))
        c = config.load({"SWARMBOX_SYSOP_TOPIC": "ops.night-1", "SWARMBOX_SYSOP_GROUP": "g_2"})
        self.assertEqual((c.topic, c.group), ("ops.night-1", "g_2"))
        self.assertEqual(config.load({"SWARMBOX_SYSOP_TOPIC": "  "}).topic, "goal", "empty means the default")
        self.assertEqual(config.goal_topic({}), "goal")
        self.assertEqual(config.goal_topic({"SWARMBOX_SYSOP_TOPIC": "ops"}), "ops")
        for bad in ("Goal", "a b", "a/b", ".x", "-x", "x" * 64, "a\nb"):
            for fn in (lambda: config.load({"SWARMBOX_SYSOP_TOPIC": bad}), lambda: config.load({"SWARMBOX_SYSOP_GROUP": bad}),
                       lambda: config.goal_topic({"SWARMBOX_SYSOP_TOPIC": bad})):
                with self.assertRaises(config.ConfigError, msg=bad):
                    fn()


class Cli(Base):
    def run_cli(self, *args, env=None, stdin=None):
        e = dict(os.environ, PYTHONPATH=ss.LIB, **(env or {}))
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop"] + list(args), env=e, capture_output=True, text=True, timeout=60, input=stdin)

    def test_status_when_not_running(self):
        p = self.run_cli("status")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not running", p.stdout)
        self.assertEqual(self.run_cli("status", "-q").stdout, "")
        j = json.loads(self.run_cli("status", "--json").stdout)
        self.assertEqual((j["running"], j["status"]), (False, None))

    def test_goal_without_a_service_exits_3_and_without_a_bus_4(self):
        p = self.run_cli("goal", "hello")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("service running", p.stderr)
        self.bus.stop()
        p = self.run_cli("goal", "hello")
        self.assertEqual(p.returncode, 4)
        self.assertIn("not running", p.stderr)

    def test_goal_status_stop(self):
        self.script([{"sleep": 30}])
        self.start()
        p = self.run_cli("goal", "do", "something", "hard")
        self.assertEqual(p.returncode, 0, p.stderr)
        gid = p.stdout.strip()
        self.assertEqual(self.wait_state(gid, ("running",))["text"], "do something hard")
        self.assertEqual(self.state(gid)["source"], "cli")
        s = self.run_cli("status")
        self.assertEqual(s.returncode, 0)
        self.assertIn("running (pid %d)" % os.getpid(), s.stdout)
        self.assertIn("current: %s" % gid, s.stdout)
        self.assertIn("autonomy confirm-risky", s.stdout)
        j = json.loads(self.run_cli("status", "--json").stdout)
        self.assertTrue(j["running"])
        self.assertEqual(j["recent"][0]["id"], gid)
        st = self.run_cli("stop")
        self.assertEqual(st.returncode, 0, st.stderr)
        self.assertIn("stop taken", st.stdout)
        self.assertEqual(self.wait_state(gid)["state"], "stopped")

    def test_goal_source_and_stdin(self):
        self.start()
        p = self.run_cli("goal", "--source", "panel", "-", stdin="text from stdin\nline 2\n")
        gid = p.stdout.strip()
        st = self.wait_state(gid)
        self.assertEqual((st["source"], st["text"]), ("panel", "text from stdin\nline 2"))
        for bad in ("Evil", "a b", "x" * 40, "1x"):
            self.assertEqual(self.run_cli("goal", "--source", bad, "x").returncode, 2)
        self.assertEqual(self.run_cli("goal", "-", stdin="  \n").returncode, 2)
        p = self.run_cli("goal", "-", stdin="x" * 4001)
        self.assertEqual(p.returncode, 2)
        self.assertIn("at most 4000", p.stderr)

    def test_goal_wait_follows_it_to_the_end(self):
        self.start()
        p = self.run_cli("goal", "--wait", "go")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertEqual(lines[1:], ["say: working", "done: finished it"])
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "crash"
        p = self.run_cli("goal", "--wait", "go", env={"SWARMBOX_TEST_FAKE_CLAUDE_MODE": "crash"})
        self.assertEqual(p.returncode, 1)
        self.assertIn("failed", p.stdout)

    def test_stop_without_a_service(self):
        p = self.run_cli("stop")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not running", p.stderr)

    def test_panel_and_dock_entry_points_keep_their_shape(self):
        p = self.run_cli("panel")
        self.assertEqual(p.returncode, 2)
        self.assertIn("needs a terminal", p.stderr)
        for action in ("open", "close", "toggle", "redock"):        # a socket that does not exist: no tmux server is ever touched here
            p = self.run_cli("dock", action, "--window", "@3", "--socket", "/nonexistent/sbsysop.sock")
            self.assertEqual(p.returncode, 1, action)
            self.assertIn("swarmbox-sysop: dock:", p.stderr)
        self.assertEqual(self.run_cli("dock", "nonsense").returncode, 2)
        self.assertEqual(self.run_cli("dock", "open", "--window", "x").returncode, 2)

    def test_the_command_shape_and_self_test(self):
        h = self.run_cli("--help")
        for word in ("serve", "goal", "status", "stop", "mcp", "panel", "dock"):
            self.assertIn(word, h.stdout)
        p = self.run_cli("--self-test")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("self-test ok", p.stderr)
        self.assertEqual(self.run_cli().returncode, 2)


if __name__ == "__main__":
    unittest.main()
