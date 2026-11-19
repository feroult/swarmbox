"""`swarmbox-attach` against a FAKE tmux (python, recording) first on PATH: the session of each terminal tab, the idle window and the
`swarmbox <command>` mechanism: argument construction, quoting, exit-code mapping, where a returning tab goes in main, not-ready exit 6,
no-terminal path. Nothing real runs; the same script against a real, isolated tmux is tests/slow/test_attach_real.py. The entrypoint's
`attach` forwarding is in test_entrypoint.py.

A terminal is a pty made by the test. The fake tmux, the pty and the base class are in tests/support/attach_support.py.
Run with: python3 tests/fast/test_attach_command.py   (needs bash)
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from attach_support import AWKWARD, FakeTmuxCase, bash_words  # noqa: E402


class ReadinessTests(FakeTmuxCase):
    def test_not_ready_exits_6_and_never_calls_tmux(self):
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


class InteractiveAttachFakeTests(FakeTmuxCase):
    def test_a_terminal_tab_gets_a_session_of_its_own_with_its_window_linked_into_main(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, [])
        self.assertEqual(p.wait(), 0)
        calls = self.calls()
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds[0], "has-session")
        self.assertIn("=main", calls[0])
        self.assertEqual(self.subs("new-window"), [], "the window is made by new-session, in the session of the tab")
        ns = self.subs("new-session")[0]
        self.assertIn("-d", ns)
        name = ns[ns.index("-s") + 1]
        self.assertTrue(name.startswith("swarmbox-tab-"), name)
        self.assertIn(self.base, ns)  # -c <cwd of the caller>
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-s") + 1], "@7", "the window id read back from the tab's session")
        self.assertEqual(link[link.index("-t") + 1], "=main:{end}")
        self.assertIn("-a", link)
        self.assertIn("-d", link)
        self.assertEqual(self.subs("kill-window")[0][-1], "@0", "the idle window of serve is closed")
        att = self.subs("attach-session")[0]
        flat = " ".join(att)
        self.assertIn("-t =" + name, flat)
        self.assertIn("set-option destroy-unattached on", flat)
        self.assertIn("set-option status off", flat)
        self.assertEqual(att.count(";"), 2)  # two chained commands
        # the order matters: the window is linked into main before the idle one goes, so main never ends up with no window
        self.assertLess(kinds.index("link-window"), kinds.index("kill-window"))
        self.assertLess(kinds.index("kill-window"), kinds.index("attach-session"))
        self.assertFalse(any("@sb_tab" in " ".join(c) or "@sb_order" in " ".join(c) for c in calls), "no key given: nothing is recorded")

    def test_a_key_is_recorded_on_the_window_and_in_the_order_and_a_new_tab_goes_to_the_end(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        calls = self.calls()
        owner = [c for c in calls if c[:1] == ["set-option"] and "@sb_tab" in c][0]
        self.assertEqual(owner, ["set-option", "-w", "-t", "@7", "@sb_tab", "/dev/pts/9"])
        order = [c for c in calls if c[:1] == ["set-option"] and "@sb_order" in c][0]
        self.assertEqual(order, ["set-option", "-g", "@sb_order", "/dev/pts/9"])
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-t") + 1], "=main:{end}", "a tab the box has not seen goes to the end")
        self.assertIn("-a", link)

    def test_a_known_key_goes_before_the_first_window_of_a_later_tab_and_the_target_names_the_session(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.put("show-options.txt", "/dev/pts/9 /dev/pts/10\n")
        self.put("owners.txt", "@3|/dev/pts/10\n")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        link = self.subs("link-window")[0]
        self.assertEqual(link[link.index("-t") + 1], "=main:@3", "before the window of the later tab, named with the session")
        self.assertIn("-b", link)
        self.assertNotIn("-a", link)
        self.assertEqual([c for c in self.calls() if c[:1] == ["set-option"] and "@sb_order" in c], [], "the key was already in the order")

    def test_if_the_anchor_window_cannot_be_used_the_window_goes_to_the_end(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.put("show-options.txt", "/dev/pts/9 /dev/pts/10\n")
        self.put("owners.txt", "@3|/dev/pts/10\n")
        self.put("link-before-fails", "x")
        p = self.run_term(self.fake, [], SWARMBOX_TAB="/dev/pts/9")
        self.assertEqual(p.wait(), 0)
        links = self.subs("link-window")
        self.assertEqual(len(links), 2)
        self.assertIn("-b", links[0])
        self.assertEqual(links[1][links[1].index("-t") + 1], "=main:{end}")

    def test_web_attaches_to_the_session_itself_so_the_status_bar_stays(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        p = self.run_term(self.fake, ["--web"])
        self.assertEqual(p.wait(), 0)
        self.assertEqual(self.subs("new-window"), [])
        att = self.subs("attach-session")[0]
        self.assertIn("=main", att)
        flat = " ".join(" ".join(c) for c in self.calls())
        self.assertNotIn("status off", flat)
        self.assertNotIn("destroy-unattached", flat)

    def test_the_browser_client_says_so_in_its_environment_and_a_terminal_does_not(self):
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.assertEqual(self.run_term(self.fake, ["--web"]).wait(), 0)
        self.assertEqual(open(os.path.join(self.fake, "attach-env.txt")).read().split(), ["web=1"], "the sysop panel finds the browser by this")
        os.remove(os.path.join(self.fake, "attach-env.txt"))
        self.put("windows.txt", "@0|idle|bash|1\n")
        self.assertEqual(self.run_term(self.fake, []).wait(), 0)
        self.assertEqual(open(os.path.join(self.fake, "attach-env.txt")).read().split(), ["web="], "a terminal does not")


class CommandFakeTests(FakeTmuxCase):
    def setUp(self):
        super().setUp()
        self.put("client", "block")

    def attach(self, args, status="0", **extra):
        if status is not None:
            self.put("status", str(status))
        p = self.run_term(self.fake, args, **extra)
        return p, p.wait()

    def test_window_arguments_and_the_quoted_command_string(self):
        args = ["printf", "%s\n"] + AWKWARD
        p, rc = self.attach(args)
        self.assertEqual(rc, 0, p.out)
        (nw,) = self.subs("new-window")
        i = nw.index("bash")
        self.assertEqual(nw[i:i + 2][0], "bash")
        self.assertEqual(nw[i + 1], "-c")
        self.assertEqual(nw[i + 3], "wrapper")  # the wrapper takes the next three as separate arguments, no extra quoting layer
        q, status, chan = nw[i + 4:i + 7]
        self.assertEqual(bash_words(q), args)  # byte for byte after one level of shell parsing
        self.assertTrue(status.startswith(self.run_dir + "/exit."))
        self.assertTrue(chan.startswith("swarmbox-"))
        self.assertIn(chan[len("swarmbox-"):], status)
        self.assertIn("-d", nw)
        self.assertIn("-P", nw)
        self.assertIn("=main:", nw)
        wrapper = nw[i + 2]
        self.assertIn("bash -ic", wrapper)  # interactive shell: aliases and PATH apply
        for needle in ("trap", "HUP", "TERM", "129", "wait-for -S", "mv "):
            self.assertIn(needle, wrapper)
        self.assertFalse(os.path.exists("/tmp/pwned"))

    def test_no_terminal_runs_the_command_directly_without_tmux(self):
        r = self.run_noterm(self.fake, ["sh", "-c", "exit 9"])
        self.assertEqual(r.returncode, 9)
        self.assertEqual(self.calls(), [])
        r = self.run_noterm(self.fake, ["sh", "-c", "kill -TERM $$"])
        self.assertEqual(r.returncode, 143)


if __name__ == "__main__":
    unittest.main()
