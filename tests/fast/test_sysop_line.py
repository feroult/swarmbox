"""The one line of the sysop (container/addons/sysop/lib/swarmbox_sysop/line.py): what line_of says for each state of the files, and the Toaster that sets
and unsets the tmux option @sysop_line (a fake tmux, a fake clock, the files of a service written by hand). No real tmux, no network, no model.
Run with: python3 -W error tests/fast/test_sysop_line.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
from test_sysop_panel import call, make_goal, make_pending, snap  # noqa: E402

from swarmbox_sysop import dock, ipc, line  # noqa: E402


class LineOf(unittest.TestCase):
    def test_nothing_to_say_is_none(self):
        self.assertIsNone(line.line_of(snap()))
        self.assertIsNone(line.line_of(snap(up=False)))
        self.assertIsNone(line.line_of(snap(make_goal("running"), up=False)))

    def test_a_running_goal_is_working_with_the_last_thing_it_said_or_did(self):
        g = make_goal("running", text="run the tests", calls=[call("read_tab", {"tab": "1"}, t=10.0)], say=[{"t": 5.0, "text": "I will look first"}])
        self.assertEqual(line.line_of(snap(g)), ("working", "read tab 1"), "the step is newer than the sentence")
        g = make_goal("running", text="run the tests", calls=[call("read_tab", {"tab": "1"}, t=10.0)], say=[{"t": 12.0, "text": "The tests pass in the second tab"}])
        self.assertEqual(line.line_of(snap(g)), ("working", "The tests pass in the second tab"))
        g = make_goal("running", text="run the tests", calls=[call("run", {"tab": "1", "command": "pytest -q"}, t=10.0), call("done", {"summary": "x"}, t=11.0)])
        self.assertEqual(line.line_of(snap(g)), ("working", "run: pytest -q"), "done is not a step")
        self.assertEqual(line.line_of(snap(make_goal("running", text="run the tests"))), ("working", "run the tests"), "before the first step: the goal")

    def test_a_goal_that_waits_in_the_queue_and_the_queue_alone(self):
        self.assertEqual(line.line_of(snap(make_goal("queued", text="later"))), ("queued", "later"))
        self.assertEqual(line.line_of(snap(queue=[{"id": "a"}, {"id": "b"}])), ("queued", "2 queued"))
        self.assertEqual(line.line_of(snap(make_goal("waiting_approval", text="deploy"))), ("allow?", "deploy"))

    def test_an_action_that_waits_is_allow_and_a_countdown_is_sending(self):
        now = time.time()
        g = make_goal("running")
        self.assertEqual(line.line_of(snap(g, make_pending("approve", "high", deadline=now + 30, text="rm -rf build"))), ("allow?", "rm -rf build"))
        self.assertEqual(line.line_of(snap(g, make_pending("veto", deadline=now + 30, text="ls -la"))), ("sending", "ls -la"))

    def test_the_end_of_a_goal_is_its_summary_or_error_cut_short_and_it_goes_after_a_while(self):
        now = time.time()
        for state, kw, want in (("done", {"summary": "All 12 tests pass."}, "All 12 tests pass."), ("failed", {"error": "the tab went away"}, "the tab went away"),
                                ("stopped", {}, "stopped")):
            g = make_goal(state, ended=now - 1, **kw)
            self.assertEqual(line.line_of(snap(g), now), (state, want))
        old = make_goal("done", ended=now - 60, summary="long gone")
        self.assertIsNone(line.line_of(snap(old), now), "a goal that ended a minute ago says nothing")
        long = make_goal("done", ended=now, summary="word " * 200)
        text = line.line_of(snap(long), now)[1]
        self.assertLessEqual(len(text), line.MAX_TEXT)
        self.assertTrue(text.endswith("…"))

    def test_the_sentence_is_one_clean_line(self):
        g = make_goal("done", ended=time.time(), summary="two\nlines\x1b[31m and ‮ bidi \x07 bell")
        state, text = line.line_of(snap(g), time.time())
        self.assertNotRegex(text, r"[\x00-\x1f\x7f‮]")
        self.assertNotIn("\n", text)
        self.assertEqual(line.value_of((state, text)).split(":", 2)[:2], ["sysop", "done"])
        self.assertIsNone(line.value_of(None))

    def test_the_value_is_sysop_state_sentence_and_a_sentence_may_hold_colons(self):
        self.assertEqual(line.value_of(("working", "run: pytest -q")), "sysop:working:run: pytest -q")
        self.assertEqual(line.value_of(("allow?", "x")).split(":", 2), ["sysop", "allow?", "x"])


class FakeTmux:
    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def run(self, *a):
        self.calls.append(a)
        return dock.Result(self.rc, "", "no server running" if self.rc else "")


class ToasterCase(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)
        self.tm, self.log, self.now = FakeTmux(), [], [1000.0]
        self.t = line.Toaster(self.pth, tmux=self.tm, log=self.log.append, clock=lambda: self.now[0])

    def last(self):
        return self.tm.calls[-1] if self.tm.calls else None

    def test_it_sets_the_option_when_the_line_changes_and_unsets_it_when_there_is_none(self):
        self.t.look()
        self.assertEqual(self.tm.calls, [("set-option", "-gu", "@sysop_line")], "the first look clears what an earlier service left")
        self.t.look()
        self.assertEqual(len(self.tm.calls), 1, "the same line is not sent twice")
        self.svc.goal("run the tests")
        self.t.look()
        self.assertEqual(self.last(), ("set-option", "-g", "@sysop_line", "sysop:working:run the tests"))
        ipc.append_jsonl(os.path.join(self.pth.goal_dir("g1"), "say.jsonl"), {"t": 99, "text": "looking at the tabs"})
        self.t.look()
        self.assertEqual(self.last(), ("set-option", "-g", "@sysop_line", "sysop:working:looking at the tabs"))
        n = len(self.tm.calls)
        self.t.look()
        self.assertEqual(len(self.tm.calls), n)

    def test_an_approval_is_allow_and_the_end_stays_ten_seconds(self):
        self.svc.goal("deploy")
        self.svc.pending("approve", "high", text="git push --force")
        self.t.look()
        self.assertEqual(self.last()[-1], "sysop:allow?:git push --force")
        os.unlink(os.path.join(self.pth.goal_dir("g1"), "pending_action.json"))
        d = self.pth.goal_dir("g1")
        g = ipc.read_json(os.path.join(d, "state.json"))
        g.update(state="done", summary="Pushed the branch.", ended=time.time())
        ipc.write_json(os.path.join(d, "state.json"), g)
        self.svc.write_status(None)
        self.t.look()
        self.assertEqual(self.last()[-1], "sysop:done:Pushed the branch.")
        self.now[0] += line.SHOW_END - 1
        self.t.look()
        self.assertEqual(self.last()[-1], "sysop:done:Pushed the branch.", "still there before the ten seconds")
        self.now[0] += 2
        self.t.look()
        self.assertEqual(self.last(), ("set-option", "-gu", "@sysop_line"), "and gone after")
        n = len(self.tm.calls)
        self.t.look()
        self.assertEqual(len(self.tm.calls), n, "it does not come back")

    def test_a_service_that_is_down_unsets_the_line(self):
        self.svc.goal("x")
        self.t.look()
        self.assertTrue(self.last()[-1].startswith("sysop:working"))
        os.close(self.svc.fd)                                   # the lock goes: service.running() is false
        self.svc.fd = os.open(os.devnull, os.O_RDONLY)
        self.t.look()
        self.assertEqual(self.last(), ("set-option", "-gu", "@sysop_line"))

    def test_a_tmux_that_is_not_there_is_said_once_and_tried_again(self):
        self.tm.rc = 1
        self.svc.goal("x")
        for _ in range(3):
            self.t.look()
        self.assertEqual(len(self.log), 1, self.log)
        self.assertEqual(len(self.tm.calls), 3, "tried at every look")
        self.tm.rc = 0
        self.t.look()
        self.assertEqual(self.last()[-1], "sysop:working:x", "and set when tmux is there")
        self.assertEqual(self.t.sent, "sysop:working:x")

    def test_nothing_in_a_look_can_raise(self):
        def boom():
            raise ValueError("boom")
        self.t.current = boom
        self.t.look()
        self.t.look()
        self.assertEqual(len(self.log), 1)
        self.assertIn("boom", self.log[0])

    def test_the_thread_starts_and_stops(self):
        t = line.Toaster(self.pth, tmux=self.tm, log=self.log.append).start()
        ss.wait_for(lambda: self.tm.calls, 5)
        t.shutdown()
        t.thread.join(3)
        self.assertFalse(t.thread.is_alive())
        self.assertEqual(self.tm.calls[0], ("set-option", "-gu", "@sysop_line"))

    def test_shutdown_unsets_a_line_it_set_except_when_told_another_service_runs(self):
        self.svc.goal("x")
        self.t.look()
        self.t.shutdown(unset=False)
        self.assertTrue(self.last()[-1].startswith("sysop:working"))
        self.t.shutdown()
        self.assertEqual(self.last(), ("set-option", "-gu", "@sysop_line"))


if __name__ == "__main__":
    unittest.main()
