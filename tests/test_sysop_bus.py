"""The bus client of the sysop against the REAL broker (swarmbox-bus.py, in a thread, with its in-memory stub driver): the protocol is repeated
in busclient.py, so a change of the broker breaks a test here. Then the whole path goal -> service -> fake claude -> MCP server -> bus.
No tmux, no model. Run with: python3 -W error tests/test_sysop_bus.py
"""
import json
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402
from bus_support import Harness, bus as busmod  # noqa: E402

from swarmbox_sysop import busclient, ipc, service  # noqa: E402


class Client(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.close)
        self.bus = busclient.Bus(self.h.path)

    def test_ping_tabs_screen(self):
        self.assertEqual(self.bus.ping()["v"], 1)
        tabs = self.bus.tabs()
        self.assertEqual([t["tab"] for t in tabs], ["main"])
        self.assertTrue(tabs[0]["active"])
        scr = self.bus.screen("main")
        self.assertIn("screen of main line 1", scr["text"])
        self.assertEqual(len(self.bus.screen("main", 5)["text"].splitlines()), 5)

    def test_errors_keep_their_code_and_message(self):
        for fn, code in ((lambda: self.bus.screen("nope"), "no_such_tab"), (lambda: self.bus.send("nope", {"run": "ls"}), "no_such_tab"),
                         (lambda: self.bus.send("main", {"nonsense": 1}), "bad_body"), (lambda: self.bus.pub("goal", {"text": "x"}), "no_subscriber"),
                         (lambda: self.bus.request({"op": "nonsense"}), "bad_request"), (lambda: self.bus.screen("a/b"), "bad_topic")):
            with self.assertRaises(busclient.BusError) as cm:
                fn()
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(busclient.BusError) as cm:
            self.bus.send("main", {"nonsense": 1})
        self.assertIn("run", cm.exception.msg)

    def test_send_reaches_the_driver(self):
        rep = self.bus.send("main", {"run": "ls"})
        self.assertTrue(rep["ok"])
        self.assertEqual(self.h.driver.sent, [("main", {"run": "ls"})])

    def test_too_large_is_refused_before_it_is_sent(self):
        with self.assertRaises(busclient.BusError) as cm:
            self.bus.pub("goal", {"text": "x" * (1 << 20)})
        self.assertEqual(cm.exception.code, "too_large")

    def test_the_bus_is_down(self):
        with self.assertRaises(busclient.BusError) as cm:
            busclient.Bus(os.path.join(self.h.dir, "nothing.sock")).ping()
        self.assertEqual(cm.exception.code, "bus_down")
        with self.assertRaises(busclient.BusError) as cm:
            busclient.Bus(os.path.join(self.h.dir, "nothing.sock")).subscribe()
        self.assertEqual(cm.exception.code, "bus_down")

    def test_subscribe_gets_goals_and_ends_at_close_and_at_broker_stop(self):
        sub = self.bus.subscribe("goal")
        got = []
        t = threading.Thread(target=lambda: got.extend(sub), daemon=True)
        t.start()
        rep = busclient.Bus(self.h.path).pub("goal", {"text": "hello"}, "voice")
        self.assertTrue(rep["ok"])
        self.assertTrue(ss.wait_for(lambda: got, 5))
        env = got[0]
        self.assertEqual((env["v"], env["topic"], env["source"], env["body"]), (1, "goal", "voice", {"text": "hello"}))
        self.assertEqual(env["peer"]["uid"], os.getuid())
        self.assertEqual(env["id"], rep["id"])
        sub.close()
        t.join(5)
        self.assertFalse(t.is_alive())
        sub2 = self.bus.subscribe("goal")
        self.h.close()
        self.assertEqual(list(sub2), [], "the broker went away: the stream ends")
        sub2.close()

    def test_only_goal_can_be_subscribed(self):
        with self.assertRaises(busclient.BusError) as cm:
            self.bus.subscribe("tab/main/in")
        self.assertEqual(cm.exception.code, "bad_topic")


class WholePath(unittest.TestCase):
    """goal on the real bus -> the service -> the fake claude -> the MCP server -> tab/<tab>/in on the real bus"""

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.saved)))
        self.h = Harness()
        self.addCleanup(self.h.close)
        self.e.env["SB_BUS_SOCKET"] = self.h.path
        os.environ.update(self.e.env)
        script = os.path.join(self.e.dir, "script.json")
        with open(script, "w") as f:
            json.dump([{"tool": "list_tabs"}, {"tool": "read_tab", "args": {}}, {"tool": "run", "args": {"command": "make test"}},
                       {"tool": "done", "args": {"summary": "ran make test"}}], f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = script
        self.svc = service.Service(self.e.cfg(countdown=0), self.e.paths, backoff=(0.05, 0.3), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.addCleanup(lambda: (self.svc.shutdown(), self.thread.join(15)))
        self.assertTrue(self.svc.wait_ready(10))
        self.assertTrue(ss.wait_for(lambda: self.h.broker.subs["goal"], 10))

    def test_a_goal_on_the_bus_types_in_the_tab_through_the_bus(self):
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "goal", "--source", "voice", "--wait", "run the tests"],
                           env=dict(os.environ, PYTHONPATH=ss.LIB), capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("done: ran make test", p.stdout)
        self.assertEqual(self.h.driver.sent, [("main", {"run": "make test"})])
        gid = p.stdout.splitlines()[0]
        st = ipc.read_json(os.path.join(self.e.paths.goals, gid, "state.json"))
        self.assertEqual((st["source"], st["state"], st["steps"]), ("voice", "done", 3))

    def test_the_cli_exit_codes_against_the_real_broker(self):
        env = dict(os.environ, PYTHONPATH=ss.LIB)
        self.svc.shutdown()
        self.thread.join(15)
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "goal", "x"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.h.close()
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "goal", "x"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 4, p.stderr)


if __name__ == "__main__":
    unittest.main()
