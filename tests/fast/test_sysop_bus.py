"""The bus client of the sysop against the REAL broker (swarmbox-bus.py, in a thread): the protocol is repeated in busclient.py, so a change of the
broker breaks a test here. Then the whole path goal -> service -> fake claude -> MCP server -> swarmbox-tabs (a stub, tests/support/sysop_support.py FakeTabs),
with the topic and the group taken from the settings. No multiplexer, no model.
Run with: python3 -W error tests/fast/test_sysop_bus.py
"""
import json
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
from bus_support import Harness  # noqa: E402

from swarmbox_sysop import busclient, ipc, service  # noqa: E402


class Client(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.close)
        self.bus = busclient.Bus(self.h.path)

    def stream(self, topic, group=None):
        sub = self.bus.subscribe(topic, group)
        got = []
        t = threading.Thread(target=lambda: got.extend(sub), daemon=True)
        t.start()
        self.addCleanup(lambda: (sub.close(), t.join(5)))
        return got

    def test_ping(self):
        self.assertEqual(self.bus.ping()["v"], 1)

    def test_errors_keep_their_code(self):
        for fn, code in ((lambda: self.bus.pub("goal", {"text": "x"}), "no_subscriber"), (lambda: self.bus.request({"op": "nonsense"}), "bad_request"),
                         (lambda: self.bus.pub("a/b", {"text": "x"}), "bad_topic"), (lambda: self.bus.subscribe("tab/main/in"), "bad_topic"),
                         (lambda: self.bus.subscribe("goal", "bad group"), "bad_group")):
            with self.assertRaises(busclient.BusError) as cm:
                fn()
            self.assertEqual(cm.exception.code, code)
    def test_pub_counts_the_receivers(self):
        a, b = self.stream("goal"), self.stream("goal")
        c = self.stream("other")
        self.assertTrue(ss.wait_for(lambda: len(self.h.broker.subs.get("goal", [])) == 2, 5))
        rep = self.bus.pub("goal", {"text": "hello"}, "voice")
        self.assertEqual(rep["delivered"], 2)
        self.assertTrue(ss.wait_for(lambda: a and b, 5))
        self.assertEqual(c, [])
        self.assertEqual((a[0]["topic"], a[0]["source"], a[0]["body"]), ("goal", "voice", {"text": "hello"}))
        self.assertEqual(a[0]["peer"]["uid"], os.getuid())
        self.assertEqual(a[0]["id"], rep["id"])

    def test_the_topic_is_a_free_name(self):
        got = self.stream("ops.night-1")
        self.assertTrue(ss.wait_for(lambda: self.h.broker.subs.get("ops.night-1"), 5))
        self.assertEqual(self.bus.pub("ops.night-1", {"text": "x"})["delivered"], 1)
        self.assertTrue(ss.wait_for(lambda: got, 5))
        with self.assertRaises(busclient.BusError) as cm:
            self.bus.pub("goal", {"text": "x"})
        self.assertEqual(cm.exception.code, "no_subscriber", "a message goes only to the topic it names")

    def test_members_of_a_group_share_the_messages_one_each(self):
        a, b = self.stream("goal", "sysop"), self.stream("goal", "sysop")
        solo = self.stream("goal")
        self.assertTrue(ss.wait_for(lambda: len(self.h.broker.subs.get("goal", [])) == 3, 5))
        for i in range(4):
            rep = self.bus.pub("goal", {"text": str(i)})
            self.assertEqual(rep["delivered"], 2, "one for the group, one for the member without a group")
            # the broker does not pick a member that has not read the last message: wait for the reads, or a loaded machine skews the rotation
            self.assertTrue(ss.wait_for(lambda: len(a) + len(b) == i + 1 and len(solo) == i + 1, 5), (a, b, solo))
        self.assertTrue(ss.wait_for(lambda: len(a) + len(b) == 4 and len(solo) == 4, 5), (a, b, solo))
        self.assertEqual((len(a), len(b)), (2, 2), "round robin")
        self.assertEqual(sorted(e["body"]["text"] for e in a + b), ["0", "1", "2", "3"])

    def test_too_large_is_refused_before_it_is_sent(self):
        with self.assertRaises(busclient.BusError) as cm:
            self.bus.pub("goal", {"text": "x" * (1 << 20)})
        self.assertEqual(cm.exception.code, "too_large")

    def test_the_bus_is_down(self):
        with self.assertRaises(busclient.BusError) as cm:
            busclient.Bus(os.path.join(self.h.dir, "nothing.sock")).ping()
        self.assertEqual(cm.exception.code, "bus_down")
        with self.assertRaises(busclient.BusError) as cm:
            busclient.Bus(os.path.join(self.h.dir, "nothing.sock")).subscribe("goal")
        self.assertEqual(cm.exception.code, "bus_down")

    def test_the_stream_ends_at_close_and_at_broker_stop(self):
        sub = self.bus.subscribe("goal", "sysop")
        t = threading.Thread(target=lambda: list(sub), daemon=True)
        t.start()
        sub.close()
        t.join(5)
        self.assertFalse(t.is_alive())
        sub2 = self.bus.subscribe("goal", "sysop")
        self.h.close()
        self.assertEqual(list(sub2), [], "the broker went away: the stream ends")
        sub2.close()


class WholePath(unittest.TestCase):
    """goal on the real bus -> the service -> the fake claude -> the MCP server -> swarmbox-tabs (a stub), on a topic and in a group of the settings"""
    topic = "ops.goals"

    def setUp(self):
        self.e = ss.Env(SWARMBOX_SYSOP_TOPIC=self.topic, SWARMBOX_SYSOP_GROUP="night")
        self.addCleanup(self.e.cleanup)
        self.saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.saved)))
        self.h = Harness()
        self.addCleanup(self.h.close)
        self.tabs = ss.FakeTabs(os.path.join(self.e.dir, "tabs.sock"))
        self.addCleanup(self.tabs.stop)
        self.e.env["SB_BUS_SOCKET"] = self.h.path
        os.environ.update(self.e.env)
        os.environ.update(self.tabs.cmd_env)
        script = os.path.join(self.e.dir, "script.json")
        with open(script, "w") as f:
            json.dump([{"tool": "box_state"}, {"tool": "read_tab", "args": {}}, {"tool": "run", "args": {"command": "make test"}},
                       {"tool": "done", "args": {"summary": "ran make test"}}], f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = script
        self.svc = service.Service(self.e.cfg(countdown=0), self.e.paths, backoff=(0.05, 0.3), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.addCleanup(lambda: (self.svc.shutdown(), self.thread.join(15)))
        self.assertTrue(self.svc.wait_ready(10))
        self.assertTrue(ss.wait_for(lambda: self.h.broker.subs.get(self.topic), 10))

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", *args], env=dict(os.environ, PYTHONPATH=ss.LIB, **env), capture_output=True,
                              text=True, timeout=60)

    def test_a_goal_on_the_topic_of_the_setting_types_in_the_tab_through_swarmbox_tabs(self):
        p = self.cli("goal", "--source", "voice", "--wait", "run the tests")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("done: ran make test", p.stdout)
        self.assertEqual(self.tabs.sent, [("@1", {"run": "make test"})])
        self.assertEqual({a[0] for a, _ in self.tabs.calls}, {"list", "screen", "send"})
        gid = p.stdout.splitlines()[0]
        st = ipc.read_json(os.path.join(self.e.paths.goals, gid, "state.json"))
        self.assertEqual((st["source"], st["state"], st["steps"]), ("voice", "done", 3))
        self.assertEqual(list(self.h.broker.subs), [self.topic], "the bus saw one topic, the one of the settings, and no tab traffic")

    def test_a_goal_on_another_topic_is_nobody_s(self):
        p = self.cli("goal", "x", SWARMBOX_SYSOP_TOPIC="elsewhere")
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertEqual(self.tabs.sent, [])

    def test_a_bad_topic_setting_is_said_by_the_goal_command(self):
        p = self.cli("goal", "x", SWARMBOX_SYSOP_TOPIC="Bad Topic")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("SWARMBOX_SYSOP_TOPIC", p.stderr)

    def test_the_cli_exit_codes_against_the_real_broker(self):
        self.svc.shutdown()
        self.thread.join(15)
        p = self.cli("goal", "x")
        self.assertEqual(p.returncode, 3, p.stderr)
        self.h.close()
        p = self.cli("goal", "x")
        self.assertEqual(p.returncode, 4, p.stderr)


if __name__ == "__main__":
    unittest.main()
