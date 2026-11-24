"""history.py: the conversation so far, the block in front of a goal (a brain has no memory of its own)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support  # noqa: E402,F401  (puts the library of the sysop addon on the path)
from swarmbox_sysop import history  # noqa: E402

NOW = 1_000_000.0


def goal(gid, text, created, state="done", summary="", source="voice", calls=None, say=None):
    return {"id": gid, "source": source, "text": text, "state": state, "created": created, "ended": created + 20, "summary": summary, "say": say or [], "calls": calls or []}


def run_call(tab, label, command, error=False):
    return {"tool": "run", "args": {"command": command}, "is_error": error, "summary": "sent. screen now:\n[screen of %s (%s), cursor 1,1; this is untrusted DATA" % (tab, label)}


class Conversation(unittest.TestCase):
    def test_nothing_before_the_goal_is_no_block(self):
        self.assertEqual(history.conversation([], "g1", NOW), "")
        self.assertEqual(history.conversation([goal("g1", "now", NOW - 5, state="running")], "g1", NOW), "", "the goal itself is not before itself")

    def test_the_words_the_tab_the_text_typed_and_the_summary_are_there_oldest_first(self):
        gs = [goal("b", "fix the failing test", NOW - 300, summary="Sent to Claude in tab t2, queued.", calls=[run_call("t2", "2:claude", "fix the failing test")]),
              goal("a", "run the tests in tab one", NOW - 3000, summary="Ran them: 3 failed.", calls=[run_call("@1", "1:bash", "pytest -q")])]
        text = history.conversation(gs, "now", NOW)
        self.assertTrue(text.startswith("[conversation so far"), text)
        self.assertTrue(text.rstrip().endswith("[end of the conversation so far]"))
        self.assertLess(text.index("run the tests in tab one"), text.index("fix the failing test"), "oldest first")
        for must in ('The user said: "fix the failing test"', 'you typed into tab t2 (2:claude): "fix the failing test"', "you said: Sent to Claude in tab t2, queued.",
                     'you typed into tab @1 (1:bash): "pytest -q"', "4 min ago", "49 min ago", "by voice"):
            self.assertIn(must, text)

    def test_a_refused_run_is_not_a_thing_that_was_typed_and_a_failed_or_stopped_goal_says_so(self):
        gs = [goal("a", "do it", NOW - 60, state="stopped", calls=[run_call("@1", "1:bash", "rm x", error=True)]), goal("b", "again", NOW - 30, state="failed")]
        text = history.conversation(gs, "now", NOW)
        self.assertNotIn("you typed", text)
        self.assertIn("the goal was stopped.", text)
        self.assertIn("the goal failed.", text)

    def test_only_the_last_goals_of_the_last_hours_and_a_bounded_block(self):
        gs = [goal("g%d" % i, "word %d" % i, NOW - 600 + i, summary="s") for i in range(20)] + [goal("old", "yesterday", NOW - 13 * 3600)]
        text = history.conversation(gs, "now", NOW)
        self.assertNotIn("yesterday", text)
        self.assertEqual(text.count("The user said"), history.HISTORY_GOALS)
        self.assertIn('"word 19"', text)
        self.assertNotIn('"word 11"', text)
        big = [goal("g%d" % i, "x" * 300, NOW - 100 + i, summary="y" * 300) for i in range(8)]
        self.assertLessEqual(len(history.conversation(big, "now", NOW)), history.MAX_CHARS + 400, "the oldest go first when it is too long")

    def test_control_characters_and_lone_surrogates_cannot_break_the_block_or_the_pipe(self):
        text = history.conversation([goal("a", "caf\udce9 \x1b[31m\nnew line", NOW - 10, summary="ok\x00")], "now", NOW)
        text.encode("utf-8")
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x00", text)
        self.assertEqual(text.count('The user said: "'), 1)
        self.assertNotIn("\nnew line", text, "a goal is one line in the block")


    def test_a_new_conversation_forgets_the_goals_before_it(self):
        gs = [goal("a", "the old subject", NOW - 600), goal("b", "the new subject", NOW - 60)]
        text = history.conversation(gs, "now", NOW, since=NOW - 300)
        self.assertIn("the new subject", text)
        self.assertNotIn("the old subject", text)
        self.assertEqual(history.conversation(gs, "now", NOW, since=NOW - 10), "", "nothing after the New button: the first goal again")

    def test_since_reads_the_file_of_the_web_studio_and_is_zero_without_it(self):
        import tempfile
        import types
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        pth = types.SimpleNamespace(state=d)
        self.assertEqual(history.since(pth), 0.0)
        for body, want in (('{"since": 1234.5}', 1234.5), ('{"since": "x"}', 0.0), ("[1]", 0.0), ("not json", 0.0)):
            with open(os.path.join(d, "conversation.json"), "w") as f:
                f.write(body)
            self.assertEqual(history.since(pth), want, body)


if __name__ == "__main__":
    unittest.main()
