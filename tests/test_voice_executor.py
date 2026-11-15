"""Voice tool, core: the executor and the tmux snapshot, against a REAL tmux on a private socket (skipped when tmux is
missing) and against a spy that records the tmux calls (always runs).

The tmux server is `tmux -L swarmbox-test-<random>` with TMUX_TMPDIR in a temp folder; it is killed in cleanup and the live
box (or any default server) is never touched. Run with: python3 -W error tests/test_voice_executor.py
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402,F401

from swarmbox_voice import context, executor  # noqa: E402
from swarmbox_voice.tmuxrun import Result, Tmux  # noqa: E402


class Spy:
    """A Tmux stand-in: answers list-panes with the given ids and records every other call."""

    def __init__(self, panes=("%1", "%2"), rc=0):
        self.panes, self.calls, self.rc = panes, [], rc

    def run(self, *args):
        self.calls.append(list(args))
        if args[0] == "list-panes":
            return Result(self.rc, "\n".join(self.panes) + "\n", "" if self.rc == 0 else "no session")
        return Result(0, "%9\n" if args[0] == "new-window" else "", "")

    def sent(self):
        return [c for c in self.calls if c[0] != "list-panes"]


def send(text, pane="%1", enter=False):
    return {"type": "send_text", "pane": pane, "text": text, "enter": enter}


class SpyTests(unittest.TestCase):
    def test_not_confirmed_sends_nothing(self):
        for flag in (False, None, 1, "yes", "true"):
            spy = Spy()
            with self.assertRaises(executor.ExecutorError):
                executor.execute([send("ls")], flag, tmux=spy)
            self.assertEqual(spy.calls, [], "not even a tmux call without a confirmation")

    def test_send_text_is_literal_and_has_no_enter(self):
        spy = Spy()
        res = executor.execute([send("echo $HOME; Enter C-c -x")], True, tmux=spy)
        self.assertEqual(spy.sent(), [["send-keys", "-t", "%1", "-l", "--", "echo $HOME; Enter C-c -x"]])
        self.assertTrue(res[0]["ok"])

    def test_enter_only_when_the_action_says_so(self):
        spy = Spy()
        executor.execute([send("ls", enter=True)], True, tmux=spy)
        self.assertEqual(spy.sent(), [["send-keys", "-t", "%1", "-l", "--", "ls"], ["send-keys", "-t", "%1", "Enter"]])

    def test_unknown_pane_and_bad_actions_are_rejected_before_anything_is_sent(self):
        for actions in ([send("ls", pane="%7")], [send("ls"), send("x", pane="%7")], [{"type": "run_shell"}], [send("a\nb")],
                        [{"type": "send_text", "pane": "%1", "text": "x", "extra": 1}], ["x"]):
            spy = Spy()
            with self.subTest(actions=str(actions)[:50]):
                with self.assertRaises(executor.ExecutorError):
                    executor.execute(actions, True, tmux=spy)
                self.assertEqual(spy.sent(), [])

    def test_missing_session(self):
        with self.assertRaises(executor.ExecutorError):
            executor.execute([send("ls")], True, tmux=Spy(rc=1))

    def test_session_is_matched_exactly(self):
        spy = Spy()
        executor.execute([send("ls")], True, tmux=spy, session="work")
        self.assertEqual(spy.calls[0][:4], ["list-panes", "-s", "-t", "=work"])

    def test_new_window_and_select_pane(self):
        spy = Spy()
        res = executor.execute([{"type": "new_window", "name": "w", "cwd": tempfile.gettempdir()},
                                {"type": "select_pane", "pane": "%2"}], True, tmux=spy)
        self.assertEqual(spy.sent()[0][:2], ["new-window", "-t"])
        self.assertIn("-n", spy.sent()[0])
        self.assertEqual(res[0]["pane"], "%9")
        self.assertEqual([c[0] for c in spy.sent()[1:]], ["select-window", "select-pane"])

    def test_new_window_with_a_bad_cwd_fails_without_calling_tmux(self):
        spy = Spy()
        res = executor.execute([{"type": "new_window", "cwd": "/nonexistent/dir"}], True, tmux=spy)
        self.assertFalse(res[0]["ok"])
        self.assertEqual(spy.sent(), [])

    def test_stops_at_the_first_failure(self):
        class Failing(Spy):
            def run(self, *args):
                if args[0] == "send-keys":
                    self.calls.append(list(args))
                    return Result(1, "", "can't find pane")
                return Spy.run(self, *args)
        spy = Failing()
        res = executor.execute([send("a"), send("b")], True, tmux=spy)
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0]["ok"])
        self.assertIn("can't find pane", res[0]["error"])

    def test_tmux_hook_and_environment(self):
        os.environ["SWARMBOX_TEST_TMUX"] = "tmux -L swarmbox-test-hook"
        self.addCleanup(os.environ.pop, "SWARMBOX_TEST_TMUX", None)
        self.assertEqual(Tmux().argv, ["tmux", "-L", "swarmbox-test-hook"])
        self.assertNotIn("TMUX", Tmux(env={"TMUX": "x", "A": "b"}).env)
        self.assertEqual(Tmux(argv=["/nonexistent/tmux"]).run("ls").rc, 127)


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class RealTmuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        sock = "swarmbox-test-%d" % (os.getpid() % 100000)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp, "TMUX_TMPDIR": self.tmp, "TERM": "xterm"}
        self.tmux = Tmux(argv=["tmux", "-L", sock, "-f", "/dev/null"], env=env)
        self.addCleanup(self.tmux.run, "kill-server")
        r = self.tmux.run("new-session", "-d", "-s", "main", "-x", "100", "-y", "30", "-c", self.tmp, "exec cat -v")
        self.assertEqual(r.rc, 0, r.err)
        self.tmux.run("new-window", "-t", "=main:", "-n", "second", "-c", self.tmp, "exec cat -v")
        self.tmux.run("new-session", "-d", "-s", "other", "-x", "100", "-y", "30", "exec cat -v")
        self.panes = context.snapshot(self.tmux, "main")

    def wait_for(self, pane, needle, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            out = self.tmux.run("capture-pane", "-p", "-J", "-t", pane).out
            if needle in out:
                return out
            time.sleep(0.05)
        self.fail("%r never appeared in %s: %r" % (needle, pane, out))

    def test_snapshot_lists_only_the_session_panes(self):
        self.assertEqual(len(self.panes), 2)
        self.assertIn("second", [p["window"] for p in self.panes])
        other = self.tmux.run("list-panes", "-t", "=other", "-F", "#{pane_id}").out.split()
        self.assertFalse(set(other) & {p["id"] for p in self.panes})
        self.assertEqual(context.snapshot(self.tmux, "nosuch"), [])

    def test_send_text_lands_literally_without_enter(self):
        pane = self.panes[0]["id"]
        executor.execute([send("hello; $HOME C-c Enter 'x'", pane=pane)], True, tmux=self.tmux)
        out = self.wait_for(pane, "hello; $HOME C-c Enter 'x'")
        # `cat -v` echoes only after Enter: without it the text sits in the terminal line buffer, and appears once
        # (typed echo), not twice (typed + cat output)
        self.assertEqual(out.count("hello; $HOME C-c Enter 'x'"), 1)

    def test_enter_sends_the_line(self):
        pane = self.panes[0]["id"]
        executor.execute([send("line-one", pane=pane, enter=True)], True, tmux=self.tmux)
        end = time.time() + 5
        while time.time() < end and self.tmux.run("capture-pane", "-p", "-J", "-t", pane).out.count("line-one") < 2:
            time.sleep(0.05)
        self.assertEqual(self.tmux.run("capture-pane", "-p", "-J", "-t", pane).out.count("line-one"), 2)

    def test_pane_of_another_session_is_refused(self):
        other = self.tmux.run("list-panes", "-t", "=other", "-F", "#{pane_id}").out.split()[0]
        with self.assertRaises(executor.ExecutorError):
            executor.execute([send("nope", pane=other)], True, tmux=self.tmux)
        time.sleep(0.2)
        self.assertNotIn("nope", self.tmux.run("capture-pane", "-p", "-t", other).out)

    def test_select_pane_and_new_window(self):
        first = self.panes[0]["id"]
        self.tmux.run("select-window", "-t", first)
        second = [p["id"] for p in self.panes if p["id"] != first][0]
        res = executor.execute([{"type": "select_pane", "pane": second}], True, tmux=self.tmux)
        self.assertTrue(res[0]["ok"], res)
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", "=main:", "#{pane_id}").out.strip(), second)
        res = executor.execute([{"type": "new_window", "name": "third", "cwd": self.tmp}], True, tmux=self.tmux)
        self.assertTrue(res[0]["ok"], res)
        names = [p["window"] for p in context.snapshot(self.tmux, "main")]
        self.assertIn("third", names)

    def test_snapshot_tail_cwd_and_redaction(self):
        pane = self.panes[0]["id"]
        self.tmux.run("send-keys", "-t", pane, "-l", "--", "token sk-" + "a" * 30)
        self.tmux.run("send-keys", "-t", pane, "Enter")
        self.wait_for(pane, "token sk-")
        raw = [p for p in context.snapshot(self.tmux, "main") if p["id"] == pane][0]
        self.assertIn("sk-" + "a" * 30, raw["tail"])
        limited = context.limit_context([raw], pane)[0]
        self.assertNotIn("a" * 30, limited["tail"])
        self.assertEqual(raw["command"], "cat")


if __name__ == "__main__":
    unittest.main()
