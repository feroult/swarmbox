"""The resident subscriber of the sysop and the CLI around it: goals from the bus, the queue and its limit, the states, the stop, a brain that
crashes, a bus that restarts, a service that is killed and started again, the private folders, swarmbox-sysop goal | status | stop.
A fake bus and the fake claude (tests/support/fixtures/sysop); no model, no multiplexer.
Run with: python3 -W error tests/fast/test_sysop_service.py
"""
import contextlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
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
    fast_loop = False          # True: the waits of the main loop are cut (ss.fast_cond), for a test of a loop that fails turn after turn
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

    def gate(self):
        """(a script step, open): the brain waits at the step until open() is called. A goal that stays running without a sleep"""
        path = os.path.join(self.e.dir, "gate-%d" % len(os.listdir(self.e.dir)))
        return {"waitfile": path}, lambda: open(path, "w").close()

    def start(self, **over):
        replace = {k: over.pop(k) for k in ("max_seconds", "approval_timeout") if isinstance(over.get(k), float) and over[k] < 5}   # below what a setting may be
        kw = dict(dict(self.cfg_over, countdown=0), **over)
        self.svc = service.Service(self.e.cfg(**kw)._replace(**replace), self.e.paths, backoff=(0.05, 0.3), log=lambda m: None)
        if self.fast_loop:
            ss.fast_cond(self.svc)
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
        service at all (seen once in the end-to-end test of version 1). The start tries again for a moment; a live service still refuses a second one."""
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
        """Found by the end-to-end test of version 1: the reader thread writes status.json when a goal arrives, the main thread when it starts the goal. The state was read
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
    def test_the_next_goal_starts_with_the_conversation_so_far_and_the_first_one_has_none(self):
        """a brain has no memory of its own: the goals before it (the words of the user and what the sysop said) go in front of the goal on its stdin"""
        self.start()
        first = self.goal("list the tabs", "voice")
        self.assertEqual(self.wait_state(first)["state"], "done")
        with open(self.logf) as f:
            self.assertEqual(json.load(f)["stdin"], "list the tabs\n", "nothing before the first goal")
        second = self.goal("and the other one?", "panel")
        self.assertEqual(self.wait_state(second)["state"], "done")
        with open(self.logf) as f:
            got = json.load(f)["stdin"]
        self.assertTrue(got.startswith("[conversation so far"), got)
        for must in ('The user said: "list the tabs"', "you said: finished it", "[end of the conversation so far]", "The goal now (panel):\nand the other one?"):
            self.assertIn(must, got)
        self.assertEqual(self.wait_state(second)["text"], "and the other one?", "the goal itself is kept as the user said it")

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
        # the state file and the audit file are written one after the other: wait for the last line of the audit
        self.assertTrue(ss.wait_for(lambda: any(e.get("state") == "done" for e in self.events("state", gid)), 10))
        ev = self.events(goal=gid)             # the audit file has the goal, its states and the end
        self.assertTrue(all(e["source"] == "voice" for e in ev))
        kinds = [(e["event"], e.get("state")) for e in ev if e["event"] in ("goal", "state", "brain")]
        self.assertEqual(kinds, [("goal", None), ("state", "queued"), ("state", "running"), ("brain", None), ("state", "done")])
        self.assertEqual([e["text"] for e in ev if e["event"] == "goal"], ["list the tabs"])
        self.assertEqual([e["tool"] for e in ev if e["event"] == "call"], ["say", "done"])
        self.assertEqual([e["event"] for e in ev if e["event"] in ("say",)], ["say"])

    def test_status_json(self):
        self.start()
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "connected", 5))
        st = self.status()
        self.assertEqual(st["pid"], os.getpid())
        self.assertEqual((st["bus"], st["current"], st["queue"]), ("connected", None, []))
        self.assertEqual(st["settings"]["autonomy"], "full-auto")
        self.assertEqual(st["settings"]["max_goals"], 5)
        self.assertEqual(st["version"], "1.0.0")

    def test_goals_run_one_at_a_time_in_order_and_the_status_shows_the_queue(self):
        hold, release = self.gate()
        self.script([hold] + DONE)
        self.start()
        a, b, c = self.goal("first"), self.goal("second"), self.goal("third")
        self.assertTrue(ss.wait_for(lambda: (self.status() or {}).get("current") == a and [q["id"] for q in self.status()["queue"]] == [b, c], 10), self.status())
        self.assertEqual((self.state(a)["state"], self.state(b)["state"]), ("running", "queued"))
        self.assertEqual(self.status()["queue"][0]["text"], "second")
        release()
        sts = [self.wait_state(i) for i in (a, b, c)]
        self.assertEqual([s["state"] for s in sts], ["done"] * 3)
        self.assertEqual([s["started"] for s in sts], sorted(s["started"] for s in sts), "in order")
        for i in range(2):
            self.assertLessEqual(sts[i]["ended"], sts[i + 1]["started"] + 0.001, "one at a time")
        self.assertTrue(ss.wait_for(lambda: self.status()["current"] is None and not self.status()["queue"], 5))

    def test_the_state_waiting_approval_with_the_pending_action(self):
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "rm -rf build"}}, {"tool": "say", "args": {"text": "not allowed"}},
                     {"tool": "done", "args": {"summary": "refused"}}])
        self.start(approval_timeout=0.5, autonomy="auto")
        gid = self.goal("clean the build folder")
        st = self.wait_state(gid, ("waiting_approval",))
        self.assertEqual((st["pending"]["risk"], st["pending"]["mode"], st["pending"]["text"], st["pending"]["tab"]), ("high", "approve", "rm -rf build", "@1"))
        end = self.wait_state(gid)
        self.assertEqual(end["state"], "done")
        self.assertIsNone(end["pending"])
        self.assertEqual(self.tabs.sent, [], "never approved, never typed")
        self.assertEqual([c["is_error"] for c in end["calls"]], [True, False, False])

    def test_by_default_a_high_risk_action_is_sent_without_asking(self):
        """full-auto, the default: what the user asks, the sysop does; the risk is still in the call log"""
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "rm -rf build"}}, {"tool": "done", "args": {"summary": "removed"}}])
        self.start(approval_timeout=20)
        gid = self.goal("clean")
        end = self.wait_state(gid)
        self.assertEqual(end["state"], "done")
        self.assertIsNone(end["pending"])
        self.assertEqual(end["calls"][0]["verdict"]["level"], "high")
        self.assertFalse(end["calls"][0]["is_error"])
        self.assertTrue(self.tabs.sent, "typed without an approval")
        with open(os.path.join(self.e.paths.goals, gid, "system-prompt.txt"), encoding="utf-8") as f:
            self.assertIn("autonomy full-auto", f.read())

    def test_a_high_risk_goal_with_a_panel_that_approves(self):
        self.script([{"tool": "run", "args": {"tab": "@1", "command": "rm -rf build"}}, {"tool": "done", "args": {"summary": "removed"}}])
        self.start(approval_timeout=20, autonomy="auto")
        gid = self.goal("clean")
        st = self.wait_state(gid, ("waiting_approval",))
        gdir = os.path.join(self.e.paths.goals, gid)
        ipc.write_json(os.path.join(gdir, "decision.json"), {"id": st["pending"]["id"], "decision": "approve", "by": "panel", "word": "run"})
        self.assertEqual(self.wait_state(gid)["state"], "done")
        self.assertEqual(self.tabs.sent, [("@1", {"run": "rm -rf build"})])


class Accept(Base):
    """What the reader does with an envelope (Service.accept): the label of the source, the goals that are refused, the queue limit. No brain runs."""

    def setUp(self):
        super().setUp()
        self.svc = service.Service(self.e.cfg(max_goals=2), self.e.paths, log=lambda m: None)
        self.e.paths.make()
        self.n = 0

    def accept(self, body="x", source="cli", **env):
        self.n += 1
        self.svc.accept(dict({"v": 1, "id": "e%d" % self.n, "topic": "goal", "source": source, "body": body}, **env))
        return self.state("e%d" % self.n)

    def test_the_source_is_a_clean_label(self):
        for src, want in (("VOICE", "voice"), ("evil\nsource", "evil_source"), ("", "unknown"), ("x" * 100, "x" * 32)):
            self.assertEqual(self.accept(source=src)["source"], want)

    def test_a_plain_text_body_is_a_goal_and_the_text_is_stripped(self):
        self.assertEqual(self.accept("  run the tests ")["text"], "run the tests")
        self.assertEqual(self.accept({"text": "from a map"})["text"], "from a map")

    def test_bad_goals_fail_with_their_reason_and_keep_no_big_text(self):
        cases = [({"text": ""}, "no text"), ({"text": "   "}, "no text"), ({"nope": 1}, "no text"), (5, "no text"), (None, "no text"), (["a"], "no text"),
                 ({"text": 5}, "no text"), ({"text": "x" * 5000}, "5000 characters")]
        for body, why in cases:
            st = self.accept(body)
            self.assertEqual(st["state"], "failed", body)
            self.assertIn(why, st["error"])
            self.assertLessEqual(len(st["text"]), 200)
        self.assertEqual(len(self.svc.queue), 0)

    def test_the_queue_limit_drops_the_goals_over_it_and_counts_them(self):
        got = [self.accept("g%d" % i)["state"] for i in range(5)]
        self.assertEqual(got, ["queued", "queued", "failed", "failed", "failed"])
        self.assertIn("queue is full", self.state("e3")["error"])
        self.assertEqual(self.svc.rejected, 3)
        self.assertEqual(len(self.events("rejected")), 3)

    def test_a_newer_envelope_version_and_garbage_are_ignored(self):
        for env in ({"v": 2, "id": "x", "topic": "goal", "body": {"text": "hi"}}, {"_bad": True}, [1, 2], "text", {"v": "1", "body": "x"}):
            self.svc.accept(env)
        self.assertEqual(len(self.events("rejected")), 5)
        self.assertEqual(len(self.svc.queue), 0)


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
        self.assertEqual(self.status()["bus"], "down")
        self.bus.start()
        self.assertTrue(self.bus.wait_subscriber(1, 10))
        self.assertEqual(self.wait_state(self.goal("late"))["state"], "done")

    def test_the_bus_dies_in_the_middle_of_a_goal(self):
        hold, release = self.gate()
        self.script([hold, {"tool": "list_tabs"}, {"tool": "say", "args": {"text": "x"}}] + DONE)
        self.start()
        gid = self.goal("long")
        self.wait_state(gid, ("running",))
        self.bus.stop()
        self.assertTrue(ss.wait_for(lambda: self.status()["bus"] == "down", 10))
        self.bus.start()
        release()
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
        hold, release = self.gate()
        self.script([hold] + DONE)
        self.start()
        a, b, c = self.goal("a"), self.goal("b"), self.goal("c")
        self.wait_state(a, ("running",))
        ss.wait_for(lambda: len(self.status()["queue"]) == 2, 5)
        ipc.request_stop(self.e.paths, b)
        self.assertEqual(self.wait_state(b)["state"], "stopped")
        release()
        self.assertEqual(self.wait_state(a)["state"], "done")
        self.assertEqual(self.wait_state(c)["state"], "done")

    def test_stop_of_a_goal_that_is_not_running_does_not_hurt_the_current_one(self):
        hold, release = self.gate()
        self.script([hold] + DONE)
        self.start()
        a = self.goal("a")
        self.wait_state(a, ("running",))
        ipc.request_stop(self.e.paths, "no-such-goal")
        self.assertTrue(ss.wait_for(lambda: not os.path.exists(self.e.paths.stop_request), 5), "the request was taken")
        release()
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
        self.start(countdown=30, autonomy="confirm-risky")
        a = self.goal("a")
        self.wait_state(a, ("waiting_approval",))
        ipc.request_stop(self.e.paths)
        self.assertEqual(self.wait_state(a)["state"], "stopped")
        self.assertEqual(self.tabs.sent, [])

    def test_the_deadline_ends_a_goal(self):
        self.script([{"sleep": 60}])
        self.start(max_seconds=1.0)         # below what the setting allows (5): the budget is the same code
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

    def test_a_line_break_or_a_nul_in_any_setting_is_refused_by_name(self):
        from swarmbox_sysop import config
        for key, bad in (("model", "haiku\nx"), ("model", "haiku\rx"), ("model", "a\0b"), ("autonomy", "auto\n"), ("brain", "a\0b {mcp_config}")):
            with self.subTest(key=key, bad=bad), self.assertRaises(config.ConfigError) as cm:
                config.load({config.ENV[key]: bad})
            self.assertIn("%s: no line breaks" % config.ENV[key], str(cm.exception))


class Cli(Base):
    def run_cli(self, *args, env=None, stdin=None):
        e = dict(os.environ, PYTHONPATH=ss.LIB, **(env or {}))
        # no input means no terminal either: `goal` with no text asks isatty(0), and on a developer's terminal it would wait for a line
        feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop"] + list(args), env=e, capture_output=True, text=True, timeout=60, **feed)

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
        self.assertIn("autonomy full-auto", s.stdout)
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

    def test_the_tmux_panel_and_dock_are_gone(self):
        """herdr is the only multiplexer: the panel is the web studio's and the cockpit's, and the key commands take no tmux socket, window or client"""
        for argv in (("panel",), ("dock", "open"), ("approve", "--window", "@3"), ("veto", "--socket", "/x"), ("stop", "--client", "c")):
            p = self.run_cli(*argv)
            self.assertEqual(p.returncode, 2, argv)
            self.assertIn("usage:", p.stderr)

    def test_the_command_shape_and_self_test(self):
        h = self.run_cli("--help")
        for word in ("serve", "goal", "status", "stop", "mcp", "agent", "veto", "approve"):
            self.assertIn(word, h.stdout)
        commands = re.search(r"\{([a-z,]+)\}", h.stdout).group(1).split(",")
        self.assertNotIn("panel", commands)
        self.assertNotIn("dock", commands)
        p = self.run_cli("--self-test")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("self-test ok", p.stderr)
        self.assertEqual(self.run_cli().returncode, 2)


class CliText(unittest.TestCase):
    def test_status_prints_no_escape_sequence_from_a_goal_text(self):
        e = ss.Env()
        self.addCleanup(e.cleanup)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(e.env)
        pth = e.paths.make()
        gdir = paths.private_dir(pth.goal_dir("g1"))
        ipc.write_json(os.path.join(gdir, "state.json"), {"id": "g1", "state": "queued", "source": "cli", "text": "hello \x1b]0;PWNED-TITLE\x07 \x1b[2J\x1b[31m red"})
        out = io.StringIO()
        ns = type("A", (), {"json": False, "quiet": False})()
        with contextlib.redirect_stdout(out):
            cli.cmd_status(ns)
        self.assertIn("hello", out.getvalue())
        self.assertNotIn("\x1b", out.getvalue())
        self.assertNotIn("\x07", out.getvalue())


class Flood(Base):
    def accept(self, svc, i, text):
        svc.accept({"v": 1, "id": "f%d" % i, "topic": "goal", "source": "cli", "peer": {}, "body": {"text": text}})

    def test_rejected_goals_keep_little_and_the_folders_are_pruned_while_it_runs(self):
        svc = service.Service(self.e.cfg(), self.e.paths, log=lambda m: None)
        self.e.paths.make()
        self.accept(svc, 0, "keep me")                 # queued: its folder must survive the pruning
        for i in range(1, 80):
            self.accept(svc, i, "x" * (service.MAX_GOAL_TEXT + 5000))
        names = os.listdir(self.e.paths.goals)
        self.assertLessEqual(len(names), service.KEEP_GOALS + 1)
        self.assertIn("f0", names, "a queued goal is never pruned")
        sizes = [os.path.getsize(os.path.join(self.e.paths.goals, n, "state.json")) for n in names]
        self.assertLess(max(sizes), 2000, "a rejected goal does not keep its text")
        self.assertLess(os.path.getsize(self.e.paths.audit), 80 * 3000)
        self.assertEqual(len(svc.queue), 1)

    def test_the_audit_file_rotates_instead_of_growing_without_bound(self):
        old = audit.MAX_FILE
        audit.MAX_FILE = 2000
        self.addCleanup(setattr, audit, "MAX_FILE", old)
        a = audit.Audit(os.path.join(self.e.dir, "events.jsonl"))
        for i in range(100):
            a.append("say", text="x" * 100)
        self.assertTrue(os.path.exists(a.path + ".1"))
        self.assertLess(os.path.getsize(a.path), 2000 + 400)


class ShutdownRace(Base):
    def test_a_shutdown_between_the_ack_and_the_assignment_does_not_leave_the_stream_open(self):
        svc = service.Service(self.e.cfg(), self.e.paths, backoff=(0.05, 0.3), log=lambda m: None)
        real = svc.bus.subscribe
        subs = []

        def subscribe(topic, group=None):
            sub = real(topic, group)
            subs.append(sub)
            svc.shutdown()                  # the stop arrives when the broker has acknowledged and svc.sub is not set yet,
            t.join(10)                      # and the service has ended its main loop (its own shutdown found no stream to close)
            return sub
        svc.bus.subscribe = subscribe
        t = threading.Thread(target=svc.run, daemon=True)
        t.start()
        t.join(15)
        self.assertFalse(t.is_alive())
        self.assertTrue(subs)
        self.assertTrue(ss.wait_for(lambda: subs[0].sock.fileno() == -1, 5), "the goal stream was left open")


class Surrogates(Base):
    def test_a_goal_with_a_byte_that_is_not_utf8_does_not_kill_the_service(self):
        self.start()
        first = self.goal("caf\udce9 list tabs")
        st = self.wait_state(first)
        self.assertIn(st["state"], ("done", "failed"))
        self.assertTrue(self.thread.is_alive(), "the service is still running")
        self.assertTrue(self.svc.reader.is_alive(), "and still reads goals")
        self.assertEqual(self.wait_state(self.goal("second goal"))["state"], "done")

    def test_whatever_accept_or_the_end_of_a_goal_raises_the_service_goes_on(self):
        self.start()
        real_accept, real_final = self.svc.accept, self.svc.refresh_final
        calls = []

        def accept(env):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("bug in accept")
            return real_accept(env)

        def final(goal):
            if len(calls) == 2:
                raise RuntimeError("bug at the end")
            return real_final(goal)
        self.svc.accept, self.svc.refresh_final = accept, final
        self.goal("lost goal")                                # accept raises: the reader must live on
        self.assertTrue(ss.wait_for(lambda: len(calls) >= 1, 5))
        self.assertTrue(self.svc.reader.is_alive())
        second = self.goal("second")                          # the end of this goal raises: the loop must live on
        self.assertTrue(ss.wait_for(lambda: self.events("brain", second), 30))
        third = self.goal("third")
        self.assertEqual(self.wait_state(third)["state"], "done")
        self.assertTrue(self.thread.is_alive())

    def test_json_files_and_the_audit_take_a_lone_surrogate(self):
        p = os.path.join(self.e.dir, "x.json")
        ipc.write_json(p, {"t": "a\udce9b"})
        self.assertEqual(ipc.read_json(p), {"t": "a\udce9b"})
        audit.Audit(os.path.join(self.e.dir, "ev.jsonl")).append("goal", text="a\udce9b")
        self.assertEqual(audit.read(os.path.join(self.e.dir, "ev.jsonl"))[0]["text"], "a\udce9b")
        ipc.append_jsonl(os.path.join(self.e.dir, "c.jsonl"), {"t": "a\udce9b"})
        self.assertEqual(len(ipc.read_jsonl(os.path.join(self.e.dir, "c.jsonl"))), 1)


if __name__ == "__main__":
    unittest.main()
