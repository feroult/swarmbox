"""`swarmbox-attach` against a REAL tmux, ISOLATED (IsoTmux of tests/support/attach_support.py: `-L swarmbox-test-<random>`, a private
TMUX_TMPDIR; the server of the machine is never addressed): the session of each tab, the windows of main, the place of a returning host tab,
the exit codes of a command through a real window. The argument construction and the fake-tmux cases are tests/fast/test_attach_command.py.

A terminal is a pty made by the test (the tmux client needs one). Needs tmux and the gate SWARMBOX_TEST_REAL_TMUX=1 (set by
dev/test-slow.sh and the browser job of CI, never on a machine whose tmux you use); it skips without them.
Run with: python3 tests/slow/test_attach_real.py
"""
import os
import signal
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from attach_support import Base, FRAGMENT, HAVE_REAL_TMUX, NEEDS_TMUX, IsoTmux, checked_tmux_argv, write_exec  # noqa: E402
from waiting import wait_until  # noqa: E402


class IsolationHelper(unittest.TestCase):
    def test_the_helper_refuses_calls_without_l(self):
        for bad in (["tmux", "ls"], ["tmux", "-S", "/tmp/x", "ls"], ["tmux", "-L", "main", "-f", "/dev/null", "ls"],
                    ["tmux", "-L", "swarmbox-test-x", "ls"], ["tmux", "-L", "swarmbox-test-x", "-f", "/etc/tmux.conf", "ls"],
                    ["tmux"], []):
            with self.assertRaises(ValueError, msg=bad):
                checked_tmux_argv(bad)
        checked_tmux_argv(["tmux", "-L", "swarmbox-test-ab12", "-f", "/dev/null", "ls"])

    @unittest.skipUnless(HAVE_REAL_TMUX, NEEDS_TMUX)
    def test_iso_run_uses_a_private_socket_and_never_the_live_one(self):
        iso = IsoTmux()
        self.addCleanup(iso.close)
        iso.run("new-session", "-d", "-s", "probe", check=True)
        self.assertIn("probe", iso.run("ls").stdout)
        self.assertNotIn("TMUX", iso.env())
        self.assertTrue(os.path.exists(os.path.join(iso.tmpdir, "tmux-%d" % os.getuid(), iso.name)))


@unittest.skipUnless(HAVE_REAL_TMUX, NEEDS_TMUX)
class RealTmuxCase(Base):
    def setUp(self):
        super().setUp()
        self.iso = IsoTmux()
        self.addCleanup(self.iso.close)
        with open(os.path.join(self.home, ".bashrc"), "w") as f:
            f.write(FRAGMENT)
        write_exec(os.path.join(self.home, "bin", "myprog"), '#!/bin/sh\necho "myprog:$*" > "$OUT_DIR/path_out"\n')
        self.start_server()

    def start_server(self):
        # what serve step 9 does: env -u TMUX tmux new-session -d -s main -n idle  (through the shim: -L is forced)
        env = self.env(self.iso.shim_dir)
        env.pop("TMUX", None)
        r = subprocess.run(["tmux", "new-session", "-d", "-s", "main", "-n", "idle", "-x", "100", "-y", "30"], env=env,
                           capture_output=True, text=True, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def prompt(self, tab):
        """Wait until the shell of the tab has drawn its prompt on the terminal of the test."""
        def drawn():
            tab.pump()
            return b"$" in tab.out or b"#" in tab.out
        self.assertTrue(wait_until(drawn, 10), "no prompt: %r" % tab.out[-300:])

    def term(self, args, **extra):
        return self.run_term(self.iso.shim_dir, args, **extra)

    def windows(self, session="main"):
        r = self.iso.run("list-windows", "-t", "=" + session, "-F", "#{window_id}|#{window_name}|#{pane_current_command}")
        return [l.split("|") for l in r.stdout.splitlines() if l]

    def sessions(self):
        return self.iso.run("list-sessions", "-F", "#{session_name}").stdout.split()

    def tabs(self):
        return [x for x in self.sessions() if x.startswith("swarmbox-tab-")]

    def test_two_attach_calls_are_two_windows_of_main_each_in_a_session_of_its_own_and_the_idle_one_is_gone(self):
        self.assertEqual([w[1] for w in self.windows()], ["idle"])
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2), a.out)
        # the session of a call exists before the call has made its window and dropped the idle one: wait for the windows (a loaded machine shows the gap)
        self.assertTrue(wait_until(lambda: len(self.windows()) == 1 and self.windows()[0][1] != "idle"), self.windows())  # the idle window is gone
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 3), b.out)
        self.assertTrue(wait_until(lambda: len(self.windows()) == 2), "main shows both tabs (the browser sees them as tabs): %s" % self.windows())
        self.assertNotIn("idle", [x[1] for x in self.windows()])
        # a session per tab: no status bar, one window each (not a group sharing every window), destroyed when the client goes
        for s in self.tabs():
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "status").stdout.strip(), "off")
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "destroy-unattached").stdout.strip(), "on")
            self.assertEqual(len(self.windows(s)), 1)
        self.assertNotEqual(self.iso.run("show-options", "-t", "=main", "-v", "status").stdout.strip(), "off")
        # closing a tab of the host terminal only detaches: its session goes, its window keeps running in main
        a.p.send_signal(signal.SIGHUP)
        a.close()
        self.assertTrue(wait_until(lambda: len(self.sessions()) == 2))
        self.assertEqual(len(self.windows()), 2)

    def test_exit_in_a_tab_leaves_the_box_and_does_not_jump_to_the_window_of_another_tab(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 2), b.out)
        self.assertTrue(wait_until(lambda: len(self.windows()) == 2), self.windows())
        self.prompt(a)   # the shell of tab A has drawn its prompt
        a.write(b"exit\r")
        self.assertEqual(a.wait(), 0, a.out)   # the client of A is gone: the user is back at the host shell
        self.assertTrue(b.alive(), "the other tab is untouched")
        self.assertTrue(wait_until(lambda: len(self.windows()) == 1), "the window of A is gone from main")
        self.assertEqual(len(self.tabs()), 1, "the session of A ended with its window")
        self.assertEqual(len(self.windows(self.tabs()[0])), 1)

    def test_exit_in_the_only_tab_ends_that_client_too(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        self.prompt(a)
        a.write(b"exit\r")
        self.assertEqual(a.wait(), 0, a.out)
        self.assertTrue(wait_until(lambda: self.tabs() == []), "no session of a finished tab is left")
        # main had no other window, so tmux ends it as it always did when the last window of a session goes; the next call makes it again
        # (the test below)

    # -- the place of a tab in main: the same host tab comes back to the same slot ------------------------------------------------------
    def owners(self):
        """The key of the host tab that owns each window of main, in the order the browser shows them ('' for a window nobody owns)."""
        return self.iso.run("list-windows", "-t", "=main", "-F", "#{@sb_tab}").stdout.split("\n")[:-1]

    def enter(self, key, expect):
        t = self.term([], **({"SWARMBOX_TAB": key} if key is not None else {}))
        self.assertTrue(wait_until(lambda: len(self.windows()) == expect), t.out)
        self.prompt(t)
        return t

    def leave(self, tab, expect):
        tab.write(b"exit\r")
        self.assertEqual(tab.wait(), 0, tab.out)
        self.assertTrue(wait_until(lambda: len(self.windows()) == expect))

    def test_a_tab_that_leaves_and_comes_back_returns_to_its_place_in_the_browser(self):
        k = ["/dev/pts/101", "/dev/pts/102", "/dev/pts/103"]
        t1 = self.enter(k[0], 1)
        t2 = self.enter(k[1], 2)
        t3 = self.enter(k[2], 3)
        self.assertEqual(self.owners(), k, "the order in which the tabs were opened")
        self.leave(t1, 2)                                    # exit in the tab on the LEFT
        self.assertEqual(self.owners(), k[1:])
        t1 = self.enter(k[0], 3)                             # and the same host tab comes back
        self.assertEqual(self.owners(), k, "back on the left, not at the end")
        self.leave(t2, 2)                                    # the one in the MIDDLE
        self.assertEqual(self.owners(), [k[0], k[2]])
        t2 = self.enter(k[1], 3)
        self.assertEqual(self.owners(), k, "back in the middle")
        self.leave(t3, 2)                                    # the last one: it goes to the end again
        t3 = self.enter(k[2], 3)
        self.assertEqual(self.owners(), k)

    def test_a_tab_without_a_key_goes_to_the_end_and_does_not_disturb_the_others(self):
        a = self.enter("/dev/pts/201", 1)
        self.enter(None, 2)                                  # an old host script, or a client that gave no key
        c = self.enter("/dev/pts/202", 3)
        self.assertEqual(self.owners(), ["/dev/pts/201", "", "/dev/pts/202"])
        self.leave(a, 2)
        self.enter("/dev/pts/201", 3)
        # What is kept is the order of the host tabs among themselves. Nothing records on which side of a returning tab a window with no owner
        # was, so it can end up on either side; the returning tab goes right before the next tab that has an owner.
        self.assertEqual([k for k in self.owners() if k], ["/dev/pts/201", "/dev/pts/202"])
        self.assertEqual(self.owners().count(""), 1, "the keyless window is still there")
        self.assertEqual(self.owners()[-2:], ["/dev/pts/201", "/dev/pts/202"])
        self.assertTrue(c.alive())

    def test_a_window_opened_from_the_browser_stays_and_the_host_tabs_keep_their_order(self):
        a = self.enter("/dev/pts/301", 1)
        self.iso.run("new-window", "-d", "-a", "-t", "=main:{end}", "sleep 600", check=True)   # Alt+N in the browser: no owner
        self.assertTrue(wait_until(lambda: len(self.windows()) == 2))
        self.enter("/dev/pts/302", 3)
        self.assertEqual(self.owners(), ["/dev/pts/301", "", "/dev/pts/302"])
        self.leave(a, 2)
        self.enter("/dev/pts/301", 3)
        self.assertEqual([k for k in self.owners() if k], ["/dev/pts/301", "/dev/pts/302"], "the host tabs keep their order")
        self.assertEqual(self.owners().count(""), 1, "the window from the browser is still there")

    def test_the_key_is_cleaned_before_it_is_kept(self):
        self.enter("a b;c$(id)", 1)
        self.assertEqual(self.owners(), ["a_b_c__id_"])
        self.assertEqual(self.iso.run("show-options", "-gqv", "@sb_order").stdout.strip(), "a_b_c__id_", "one word, so the list stays a list")

    def test_the_order_remembers_at_most_64_tabs_the_newest_ones(self):
        self.iso.run("set-option", "-g", "@sb_order", " ".join("old%d" % i for i in range(100)), check=True)
        self.enter("/dev/pts/401", 1)
        keys = self.iso.run("show-options", "-gqv", "@sb_order").stdout.split()
        self.assertEqual(len(keys), 64)
        self.assertEqual(keys[-1], "/dev/pts/401")
        self.assertEqual(keys[0], "old37")

    def test_a_tab_opened_after_another_one_ended_still_works(self):
        a = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), a.out)
        self.prompt(a)
        a.write(b"exit\r")
        a.wait()
        self.assertTrue(wait_until(lambda: self.tabs() == []))
        b = self.term([])
        self.assertTrue(wait_until(lambda: len(self.tabs()) == 1), b.out)
        # the session of the tab exists before the call has made its window and dropped the idle one: wait for that, a loaded machine shows the gap
        self.assertTrue(wait_until(lambda: len(self.windows()) == 1), self.windows())

    def test_the_last_screen_of_a_command_is_printed_after_its_window_closes(self):
        p = self.term(["echo", "output-of-the-command"])
        self.assertEqual(p.wait(), 0, p.out)
        self.assertIn(b"output-of-the-command", p.out.split(b"[exited]")[-1], p.out)

    def test_command_exit_codes_through_a_real_window(self):
        for args, want in ((["true"], 0), (["false"], 1), (["sh", "-c", "exit 130"], 130), (["sh", "-c", "exit 7"], 7),
                           (["sh", "-c", "kill -9 $$"], 137), (["sh", "-c", "kill -15 $$"], 143),
                           (["no-such-command-xyz"], 127)):
            with self.subTest(args=args):
                p = self.term(args)
                self.assertEqual(p.wait(), want, p.out)
        self.assertEqual([f for f in os.listdir(self.run_dir) if f.startswith("exit.")], [])
        self.assertEqual(self.sessions(), ["main"], "the sessions of finished calls must be gone")


if __name__ == "__main__":
    unittest.main()
