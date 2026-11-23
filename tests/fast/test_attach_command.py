"""`swarmbox-attach` over a FAKE multiplexer backend (tests/support/attach_support.py: the real mux.sh loads a recording fake.sh): the
readiness wait (exit 6), which backend function each entry calls (--web, an interactive terminal, a command), the quoted command string,
and the paths that bypass the multiplexer (no terminal, --plain, a backend that is not installed). The herdr functions themselves are
tests/fast/test_herdr_backend.py; the entrypoint's `attach` forwarding is in test_entrypoint.py.

A terminal is a pty made by the test. Run with: python3 tests/fast/test_attach_command.py   (needs bash)
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from attach_support import AWKWARD, FakeMuxCase, bash_words  # noqa: E402


class ReadinessTests(FakeMuxCase):
    def test_not_ready_exits_6_and_never_calls_the_multiplexer(self):
        self.not_ready()
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="0")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertIn(b"not ready", r.stderr)
        self.assertIn(b"podman logs", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_box_that_becomes_ready_during_the_wait_is_attached_to(self):
        self.not_ready()
        timer = threading.Timer(0.4, self.mark_ready)
        timer.start()
        self.addCleanup(timer.cancel)
        t0 = time.time()
        r = self.run_noterm(self.fake, ["true"], SWARMBOX_TEST_READY_TIMEOUT="10")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - t0, 5, "the wait ends when the marker appears, not at the timeout")


class DispatchTests(FakeMuxCase):
    def test_a_terminal_without_a_command_is_an_interactive_tab(self):
        self.assertEqual(self.run_term(self.fake, []).wait(), 0)
        self.assertEqual(self.calls(), ["attach_interactive"])

    def test_web_is_the_browser_client(self):
        self.assertEqual(self.run_term(self.fake, ["--web"]).wait(), 0)
        self.assertEqual(self.calls(), ["attach_web web="])

    def test_a_command_reaches_the_backend_as_one_quoted_string_and_its_status_comes_back(self):
        args = ["printf", "%s\n"] + AWKWARD
        p = self.run_term(self.fake, args, FAKE_RC="5")
        self.assertEqual(p.wait(), 5, p.out)
        self.assertEqual(self.calls(), ["attach_command"])
        self.assertEqual(bash_words(self.command_q()), args)   # byte for byte after one level of shell parsing
        self.assertFalse(os.path.exists("/tmp/pwned"))

    def test_plain_bypasses_the_multiplexer(self):
        p = self.run_term(self.fake, ["--plain", "sh", "-c", "exit 4"])
        self.assertEqual(p.wait(), 4)
        self.assertEqual(self.calls(), [])

    def test_a_backend_that_is_not_installed_runs_the_command_directly(self):
        p = self.run_term(self.fake, ["sh", "-c", "exit 3"], FAKE_UNAVAILABLE="1")
        self.assertEqual(p.wait(), 3)
        self.assertEqual(self.calls(), [])

    def test_no_terminal_runs_the_command_directly_without_the_multiplexer(self):
        r = self.run_noterm(self.fake, ["sh", "-c", "exit 9"])
        self.assertEqual(r.returncode, 9)
        self.assertEqual(self.calls(), [])
        r = self.run_noterm(self.fake, ["sh", "-c", "kill -TERM $$"])
        self.assertEqual(r.returncode, 143)

    def test_no_terminal_keeps_the_aliases_of_the_shell_fragment(self):
        r = self.run_noterm(self.fake, ["greet", "hi"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.out("alias_out"), "--auto-approve hi\n")


if __name__ == "__main__":
    unittest.main()
