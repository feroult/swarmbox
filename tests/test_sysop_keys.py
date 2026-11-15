"""The keys of the sysop that work from any tab (container/tools/sysop/lib/swarmbox_sysop/keys.py): veto, approve, the goal prompt, the stop key's
messages and the bindings in container/config/tmux.conf. No tmux here: the dock is a fake that records what was asked. The same commands against a
real tmux, the real panel and a real client typing are in test_sysop_dock.py (class NoFocus, Podman only)."""
import io
import os
import re
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_sysop import busclient, dock, ipc, keys, paths  # noqa: E402

with open(os.path.join(ROOT, "container", "config", "tmux.conf")) as _f:
    CONF = _f.read()


class FakeDock:
    def __init__(self, fail_open=False, fail_focus=False):
        self.calls, self.fail_open, self.fail_focus = [], fail_open, fail_focus

    def open(self, window=None, focus=True, auto=False):
        self.calls.append(("open", window, focus, auto))
        if self.fail_open:
            raise dock.DockError("no session")

    def focus(self, window=None):
        self.calls.append(("focus", window))
        if self.fail_focus:
            raise dock.DockError("no panel")


class FakeTmux:
    def __init__(self):
        self.ran = []

    def run(self, *a):
        self.ran.append(a)


class Base(unittest.TestCase):
    def setUp(self):
        self.env = ss.Env()
        self.addCleanup(self.env.cleanup)
        self.pth = self.env.paths
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)
        self.tm = FakeTmux()


class Veto(Base):
    def test_a_countdown_is_vetoed_and_an_approval_is_refused(self):
        self.svc.goal()
        self.svc.pending("veto")
        self.assertEqual(keys.veto(self.pth, self.tm, "client-1"), 0)
        self.assertEqual(self.svc.decision(), {"id": "p1", "decision": "veto", "by": "key"})
        self.svc.pending("approve", "high")
        self.assertEqual(keys.veto(self.pth), 0)
        self.assertEqual(self.svc.decision()["decision"], "deny")
        self.assertTrue(any(a[:3] == ("display-message", "-c", "client-1") for a in self.tm.ran), "the client is told")

    def test_nothing_waiting_or_an_expired_action_writes_nothing(self):
        self.assertEqual(keys.veto(self.pth), 1)            # no goal
        self.svc.goal()
        self.assertEqual(keys.veto(self.pth), 1)            # a goal, no action
        self.svc.pending("veto", seconds=-1)
        self.assertEqual(keys.veto(self.pth), 1)            # expired
        self.assertIsNone(self.svc.decision())

    def test_the_service_down_writes_nothing(self):
        self.svc.goal()
        self.svc.pending("veto")
        self.svc.close()
        self.svc.fd = os.open(os.devnull, os.O_RDONLY)      # so the cleanup can close something
        self.assertEqual(keys.veto(self.pth), 1)
        self.assertIsNone(self.svc.decision())


class Approve(Base):
    def run_approve(self, ack=True, dk=None, wait=2.0):
        dk = dk or FakeDock()
        if ack:
            def panel():          # what the panel does: take the request (delete it)
                end = time.time() + 5
                while time.time() < end:
                    if os.path.exists(self.pth.panel_request):
                        self.seen = ipc.read_json(self.pth.panel_request)
                        os.unlink(self.pth.panel_request)
                        return
                    time.sleep(0.01)
            threading.Thread(target=panel, daemon=True).start()
        rc = keys.approve(self.pth, dk, "@3", self.tm, "c1", wait=wait)
        return rc, dk

    def test_it_opens_without_focus_asks_the_panel_and_focuses_only_after_the_panel_took_the_request(self):
        self.svc.goal()
        self.svc.pending("approve", "high")
        rc, dk = self.run_approve()
        self.assertEqual(rc, 0)
        self.assertEqual(dk.calls, [("open", "@3", False, True), ("focus", "@3")], "open without focus, focus last")
        self.assertEqual((self.seen["action"], self.seen["id"]), ("approve", "p1"))
        self.assertIsNone(self.svc.decision(), "the gesture decides nothing")

    def test_a_panel_that_does_not_answer_is_not_focused(self):
        self.svc.goal()
        self.svc.pending("approve", "high")
        rc, dk = self.run_approve(ack=False, wait=0.3)
        self.assertEqual(rc, 1)
        self.assertNotIn(("focus", "@3"), dk.calls)
        self.assertFalse(os.path.exists(self.pth.panel_request), "the stale request is removed")

    def test_no_approval_waiting_does_nothing_at_all(self):
        self.svc.goal()
        for setup in (lambda: None, lambda: self.svc.pending("veto"), lambda: self.svc.pending("approve", "high", seconds=-1)):
            setup()
            rc, dk = self.run_approve(ack=False, wait=0.1)
            self.assertEqual((rc, dk.calls), (1, []))
        self.assertFalse(os.path.exists(self.pth.panel_request))

    def test_a_dock_that_fails_is_said_and_nothing_is_focused(self):
        self.svc.goal()
        self.svc.pending("approve", "high")
        rc, dk = self.run_approve(ack=False, dk=FakeDock(fail_open=True))
        self.assertEqual((rc, dk.calls), (1, [("open", "@3", False, True)]))
        rc, dk = self.run_approve(dk=FakeDock(fail_focus=True))
        self.assertEqual(rc, 1)


class Prompt(Base):
    def setUp(self):
        super().setUp()
        self.bus = ss.FakeBus(self.env.env["SB_BUS_SOCKET"])
        self.addCleanup(self.bus.stop)

    def ask(self, text):
        out = io.StringIO()
        rc = keys.prompt(busclient.Bus(self.env.env["SB_BUS_SOCKET"]), "panel", io.StringIO(text), out)
        return rc, out.getvalue()

    def test_a_line_is_published_as_a_goal_with_the_source_panel(self):
        import json
        import socket
        sub = socket.socket(socket.AF_UNIX)
        sub.connect(self.bus.path)
        sub.sendall(b'{"op":"sub","topic":"goal"}\n')
        f = sub.makefile("rb")
        self.addCleanup(sub.close)
        f.readline()
        self.assertEqual(self.ask("  run the tests \n")[0], 0)
        env = json.loads(f.readline())
        self.assertEqual((env["body"], env["source"]), ({"text": "run the tests"}, "panel"))

    def test_the_topic_is_the_one_of_the_setting_and_a_bad_setting_is_said(self):
        import json
        import socket
        sub = socket.socket(socket.AF_UNIX)
        sub.connect(self.bus.path)
        sub.sendall(b'{"op":"sub","topic":"ops"}\n')
        f = sub.makefile("rb")
        self.addCleanup(sub.close)
        f.readline()
        saved = os.environ.get("SWARMBOX_SYSOP_TOPIC")
        self.addCleanup(lambda: os.environ.pop("SWARMBOX_SYSOP_TOPIC", None) if saved is None else os.environ.update(SWARMBOX_SYSOP_TOPIC=saved))
        os.environ["SWARMBOX_SYSOP_TOPIC"] = "ops"
        self.assertEqual(self.ask("run the tests\n")[0], 0)
        self.assertEqual(json.loads(f.readline())["topic"], "ops")
        self.assertEqual([p[0] for p in self.bus.pubs], ["ops"])
        os.environ["SWARMBOX_SYSOP_TOPIC"] = "Bad Topic"
        rc, out = self.ask("run the tests\n\n")
        self.assertEqual(rc, 3)
        self.assertIn("SWARMBOX_SYSOP_TOPIC", out)

    def test_empty_is_a_cancel_and_no_service_is_said(self):
        self.assertEqual(self.ask("\n")[0], 1)
        rc, out = self.ask("a goal\n\n")
        self.assertEqual(rc, 3)
        self.assertIn("not running", out)
        self.assertEqual(self.ask("x" * 5000 + "\n\n")[0], 2)


class Bindings(unittest.TestCase):
    def binds(self):
        return {ln.split()[1]: ln for ln in CONF.splitlines() if re.match(r"\s*bind\s+[^-\s]", ln)}

    def test_the_four_keys_are_plain_prefix_keys_with_the_right_commands(self):
        b = self.binds()
        for k, cmd in (("V", "swarmbox-sysop veto"), ("X", "swarmbox-sysop stop"), ("a", "swarmbox-sysop approve")):
            self.assertIn(cmd, b[k])
            self.assertIn("--socket '#{socket_path}'", b[k])
            self.assertIn("--client '#{client_name}'", b[k])
        self.assertIn("--window '#{window_id}'", b["a"])
        self.assertIn("display-popup -E", b["g"])
        self.assertIn("swarmbox-sysop goal", b["g"])
        self.assertNotIn("switch-client", CONF, "no key table: a queued table switch loses the next key typed fast")

    def test_no_other_binding_uses_these_keys(self):
        for k in "VXag":
            self.assertEqual(len([ln for ln in CONF.splitlines() if re.match(r"\s*bind\s+%s\s" % k, ln)]), 1, k)


if __name__ == "__main__":
    unittest.main()
