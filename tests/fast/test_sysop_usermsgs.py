"""Fast tests for the Sysop auto-namer's per-agent readers of the user's last requests (`usermsgs`).

The fixtures copy the shapes measured on the box (Claude Code 2.1 history.jsonl, Antigravity CLI history.jsonl, OpenCode 2.3 SQLite).
Run: python3 tests/fast/test_sysop_usermsgs.py
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SYSOP_LIB = os.path.join(ROOT, "container", "addons", "sysop", "lib")
if SYSOP_LIB not in sys.path:
    sys.path.insert(0, SYSOP_LIB)

from swarmbox_sysop import usermsgs  # noqa: E402

NOW = 2_000_000_000.0
CWD = "/home/agent/.local/share/swarmbox/worktrees/shop/sb-wt-1a2b"


class UserMsgsTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="swarmbox-test-usermsgs.")
        self.addCleanup(shutil.rmtree, self.home, True)
        for k in ("CLAUDE_CONFIG_DIR", "XDG_DATA_HOME"):
            old = os.environ.pop(k, None)
            if old is not None:
                self.addCleanup(os.environ.__setitem__, k, old)

    # -- claude
    def _claude(self, recs):
        d = os.path.join(self.home, ".claude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "history.jsonl"), "w") as f:
            f.write("not json\n")
            for r in recs:
                f.write(json.dumps(r) + "\n")

    def test_claude_typed_requests_of_the_latest_session_in_this_folder(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        h = lambda text, sid, t, project=CWD: {"display": text, "pastedContents": {}, "timestamp": ms(t),  # noqa: E731
                                               "project": project, "sessionId": sid}
        self._claude([
            h("an older session goal here", "old", 9000),
            h("other folder request text", "x", 10, project="/home/agent/x"),
            h("entenda o repo agora", "s", 50),
            h("/clear", "s", 45),
            h("! git status", "s", 44),
            h("pode sim", "s", 40),
            h("entenda o repo agora", "s", 35),
            h("entenda o repo agora", "s", 34),
            h("fix the login\nredirect please", "s", 30),
            h("z " * 600, "s", 20),
        ])
        got = usermsgs.recent("claude", CWD + "/", home=self.home, now=NOW)
        self.assertEqual(got[:2], ["entenda o repo agora", "fix the login redirect please"])
        self.assertEqual(len(got[2]), usermsgs.MAX_MESSAGE_CHARS)
        self.assertTrue(got[2].endswith("…"))

    def test_claude_keeps_the_last_requests_and_short_ones_only_alone(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        self._claude([{"display": "request number %d" % i, "project": CWD, "sessionId": "s", "timestamp": ms(100 - i)}
                      for i in range(9)])
        self.assertEqual(usermsgs.recent("claude", CWD, home=self.home, now=NOW),
                         ["request number 5", "request number 6", "request number 7", "request number 8"])
        self._claude([{"display": "ok", "project": CWD, "sessionId": "s", "timestamp": ms(5)}])
        self.assertEqual(usermsgs.recent("claude", CWD, home=self.home, now=NOW), ["ok"])

    def test_claude_two_live_sessions_in_one_folder_are_ambiguous(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        self._claude([
            {"display": "the first tab goal", "project": CWD, "sessionId": "a", "timestamp": ms(60)},
            {"display": "the second tab goal", "project": CWD, "sessionId": "b", "timestamp": ms(5)},
        ])
        self.assertEqual(usermsgs.recent("claude", CWD, home=self.home, now=NOW), [])

    # -- agy
    def _agy(self, recs):
        d = os.path.join(self.home, ".gemini", "antigravity-cli")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "history.jsonl"), "w") as f:
            f.write("not json\n")
            for r in recs:
                f.write(json.dumps(r) + "\n")

    def test_agy_requests_of_the_latest_conversation_in_this_folder(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        self._agy([
            {"display": "older conv", "workspace": CWD, "conversationId": "a", "timestamp": ms(9000)},
            {"display": "other folder", "workspace": "/home/agent/x", "conversationId": "b", "timestamp": ms(10)},
            {"display": "/model", "workspace": CWD, "conversationId": "c", "timestamp": ms(30), "type": "slash_command"},
            {"display": "entenda o repo", "workspace": CWD, "conversationId": "c", "timestamp": ms(20)},
            {"display": "pode sim", "workspace": CWD, "conversationId": "c", "timestamp": ms(15)},
            {"display": "add the merge button", "workspace": CWD, "conversationId": "c", "timestamp": ms(10)},
        ])
        self.assertEqual(usermsgs.recent("agy", CWD, home=self.home, now=NOW), ["entenda o repo", "add the merge button"])
        self._agy([
            {"display": "one", "workspace": CWD, "conversationId": "a", "timestamp": ms(100)},
            {"display": "two", "workspace": CWD, "conversationId": "b", "timestamp": ms(10)},
        ])
        self.assertEqual(usermsgs.recent("agy", CWD, home=self.home, now=NOW), [])

    # -- opencode
    def _opencode(self, sessions, messages):
        d = os.path.join(self.home, "data", "opencode")
        os.makedirs(d)
        os.environ["XDG_DATA_HOME"] = os.path.join(self.home, "data")
        self.addCleanup(os.environ.pop, "XDG_DATA_HOME", None)
        con = sqlite3.connect(os.path.join(d, "opencode.db"))
        con.execute("CREATE TABLE session_v2 (id text, directory text, parent_id text, time_archived integer, time_updated integer)")
        con.execute("CREATE TABLE session_message (id text, session_id text, type text, seq integer, data text)")
        con.executemany("INSERT INTO session_v2 VALUES (?,?,?,?,?)", sessions)
        con.executemany("INSERT INTO session_message VALUES (?,?,?,?,?)", messages)
        con.commit()
        con.close()

    def test_opencode_user_rows_of_the_latest_session(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        self._opencode(
            [("s1", CWD, None, None, ms(5)), ("s0", CWD, None, None, ms(9000)), ("child", CWD, "s1", None, ms(1))],
            [
                ("m1", "s1", "user", 1, json.dumps({"text": "fix checkout cache", "files": []})),
                ("m2", "s1", "assistant", 2, json.dumps({"content": [{"type": "text", "text": "ok"}]})),
                ("m3", "s1", "user", 3, json.dumps({"text": "now the tests"})),
                ("m4", "s0", "user", 1, json.dumps({"text": "old"})),
            ],
        )
        self.assertEqual(usermsgs.recent("opencode", CWD, home=self.home, now=NOW), ["fix checkout cache", "now the tests"])

    def test_opencode_two_live_sessions_are_ambiguous(self):
        ms = lambda t: int((NOW - t) * 1000)  # noqa: E731
        self._opencode([("s1", CWD, None, None, ms(5)), ("s2", CWD, None, None, ms(60))],
                       [("m1", "s1", "user", 1, json.dumps({"text": "a"}))])
        self.assertEqual(usermsgs.recent("opencode", CWD, home=self.home, now=NOW), [])

    # -- best effort
    def test_unknown_agent_missing_or_broken_stores_give_nothing(self):
        self.assertEqual(usermsgs.recent("shell", CWD, home=self.home, now=NOW), [])
        self.assertEqual(usermsgs.recent("claude", "", home=self.home, now=NOW), [])
        for agent in ("claude", "agy", "opencode"):
            self.assertEqual(usermsgs.recent(agent, CWD, home=self.home, now=NOW), [])
        d = os.path.join(self.home, ".local", "share", "opencode")
        os.makedirs(d)
        with open(os.path.join(d, "opencode.db"), "w") as f:
            f.write("not a database")
        self.assertEqual(usermsgs.recent("opencode", CWD, home=self.home, now=NOW), [])


if __name__ == "__main__":
    unittest.main()
