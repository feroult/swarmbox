"""The panel of the sysop in the mode `always` (setting sysop.panel, the default): up in every window from the start of the box, idle when there
is no goal (container/addons/sysop/lib/swarmbox_sysop/dock.py, panel.py).

  * (the setting and its checks, the Follower for each mode with a fake dock and the tmux file need no tmux: tests/fast/test_sysop_dock_logic.py)
  * the real thing against a REAL tmux on a private socket with real clients on a pty, with the REAL panel program in the panes: the panel exists
    in every window and never takes the focus, a new window gets one (the hook), a window that holds only the panel is closed, a resize flips the
    layout of each window, the toggle hides and shows all windows and is remembered, `q` of the panel hides all of them, a killed panel comes
    back, the modes auto and off, the idle screen at several widths, no focus stolen while typing, and the CPU of an idle box.
Run the tmux part in Podman only (see tests/slow/test_sysop_dock.py): it skips unless tmux is installed AND SWARMBOX_TEST_REAL_TMUX=1 is set.
"""
import fcntl
import os
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import test_sysop_dock as td  # noqa: E402

from swarmbox_sysop import dock, ipc, paths  # noqa: E402
from swarmbox_sysop.dock import DockError, Follower  # noqa: E402

SETTINGS = {"topic": "goal", "autonomy": "confirm-risky", "brain": "claude", "model": "haiku", "panel": "always"}










LAUNCHER = td.LAUNCHER


@unittest.skipUnless(td.HAVE, "needs tmux and a container (run it in Podman, see tests/slow/test_sysop_dock.py)")


class Always(td.RealTmux):
    MODE = "always"

    def conf(self):
        return td.TMUX_CONF if getattr(self, "USE_BOX_CONF", False) else super().conf()

    def setUp(self):
        super().setUp()
        exe = os.path.join(self.bin, "swarmbox-sysop")
        with open(exe, "w") as f:
            f.write(LAUNCHER)
        os.chmod(exe, 0o755)
        self.d = dock.default_dock(self.tmux)         # the real panel program in every pane
        self.assertEqual(self.d.mode, "always")
        self.pth = paths.Paths(self.env)

    # helpers
    def hidden(self):
        return self.tmux.run("show-options", "-gqv", "@swarmbox_sysop_hidden").out.strip() == "1"

    def open_compact(self):
        """a window of 80 columns or fewer has no panel until it is opened (see the class Compact): the tests of the geometry of the panel in a narrow window open it first"""
        self.assertEqual(self.tmux.run("set-option", "-g", "@swarmbox_sysop_open", "1").rc, 0)

    def windows(self):
        return self.tmux.run("list-windows", "-t", "=main", "-F", "#{window_id}").out.split()

    def screen(self, pane):
        return self.tmux.run("capture-pane", "-p", "-t", pane).out

    def one_panel_in_each_window(self):
        wins = self.windows()
        ps = self.panels()
        return len(ps) == len(wins) and sorted(p["win"] for p in ps) == sorted(wins)

    def cli(self, *args):
        sock = self.tmux.run("display-message", "-p", "#{socket_path}").out.strip()
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "dock", *args, "--socket", sock], env=self.env, capture_output=True, text=True, timeout=30)

    def serve_files(self, **status):
        """the files of a running service (the lock and status.json), so the panels show the idle screen and not the "not running" text"""
        self.pth.make()
        fd = os.open(self.pth.lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        st = {"pid": os.getpid(), "bus": "connected", "current": None, "queue": [], "settings": dict(SETTINGS)}
        st.update(status)
        ipc.write_json(self.pth.status, st)


class AtStart(Always):
    def test_every_window_gets_a_panel_that_does_not_take_the_focus(self):
        self.attach(50, 200)
        w2, u2 = self.new_window()
        w3, u3 = self.new_window()
        self.assertEqual(self.d.sync(), "created 3")
        self.assertTrue(self.one_panel_in_each_window(), self.panes())
        for win, user in ((self.win1, self.user), (w2, u2), (w3, u3)):
            self.assertEqual(self.active_pane(win), [user], "the pane of the user keeps the focus in " + win)
            self.assertEqual(len(self.panels_of(win)), 1)
        self.assertEqual(sorted(p["id"] for p in self.panes() if not p["panel"]), sorted([self.user, u2, u3]), "the panes of the user are untouched")
        self.assertEqual(self.d.sync(), "unchanged", "again: nothing")
        self.assertEqual(len(self.panels()), 3)

    def test_the_panel_is_idle_and_says_so(self):
        self.serve_files()
        self.attach(50, 200)
        self.d.sync()
        panel, = self.panels()
        self.wait(lambda: "Say a goal, or type it below." in self.screen(panel["id"]), "the idle text")
        text = self.screen(panel["id"])
        for needle in ("SYSOP  idle", "Say a goal, or type it below.", "Type a goal"):
            self.assertIn(needle, text)
        for gone in ("autonomy:", "brain:", "topic:", "[q] Hide", "no goal. Type"):
            self.assertNotIn(gone, text, "the idle panel is short: the state, one sentence and a button")

    def test_the_hooks_are_set_by_the_first_sync_and_stay(self):
        self.attach(50, 200)
        self.d.sync()
        for h in ("after-new-window", "pane-exited", "after-kill-pane", "window-resized"):
            self.assertIn("[418]", self.tmux.run("show-hooks", "-g", h).out, h)
        self.d.hide()
        self.assertIn("[418]", self.tmux.run("show-hooks", "-g", "after-new-window").out, "hiding does not remove them: showing again needs them")
        self.assertIn("[418]", self.tmux.run("show-hooks", "-g", "window-resized").out)

    def test_the_names_of_the_tabs_are_not_frozen(self):
        self.attach(50, 200)
        self.d.sync()
        self.assertEqual(self.tmux.run("show-options", "-wqv", "-t", self.win1, "@swarmbox_sysop_ar").out.strip(), "")
        self.assertEqual(self.tmux.run("show-options", "-w", "-t", self.win1, "automatic-rename").out.strip(), "", "not set on the window: it follows the program of the user")

    def test_sync_in_a_session_that_is_not_there_is_a_dock_error(self):
        d = dock.default_dock(td.Tmux(argv=["tmux", "-L", "never-%d" % os.getpid()]))
        with self.assertRaises(DockError):
            d.sync()

    def test_the_follower_in_always_mode_brings_the_panels_by_itself_and_costs_no_cpu(self):
        self.attach(50, 200)
        w2, _ = self.new_window()
        f = Follower(self.pth, dock=self.d, mode="always", tick=1.0, log=print).start()
        self.addCleanup(f.shutdown)
        self.wait(self.one_panel_in_each_window, "the Follower to put a panel in each window")
        # CPU of the Follower (this process' threads) and of the tmux commands it runs, over 10 s of a box that does nothing
        self.serve_files()
        f.shutdown()
        f.thread.join(3)
        g = Follower(self.pth, dock=self.d, mode="always", log=print).start()      # the real tick
        self.addCleanup(g.shutdown)
        time.sleep(1.0)
        t0, w0 = os.times(), time.time()
        time.sleep(10)
        t1, w1 = os.times(), time.time()
        used = (t1.user - t0.user) + (t1.system - t0.system) + (t1.children_user - t0.children_user) + (t1.children_system - t0.children_system)
        self.assertLess(used / (w1 - w0), 0.02, "the Follower and its tmux commands used %.3f s in %.1f s" % (used, w1 - w0))
        self.assertEqual(len(self.panels()), 2)


class Following(Always):
    def test_a_new_window_gets_a_panel_by_the_hook(self):
        self.attach(50, 200)
        self.d.sync()
        win, user = self.new_window()
        self.wait(lambda: len(self.panels_of(win)) == 1, "the panel of the new window")
        self.assertEqual(self.active_pane(win), [user], "the new window keeps its own pane in front")
        self.assertIn("swarmbox_sysop", self.tmux.run("display-message", "-p", "-t", self.panels_of(win)[0]["id"], "#{pane_start_command}").out, "the real panel program")
        win3, _ = self.new_window(detached=False)
        self.wait(lambda: len(self.panels_of(win3)) == 1, "the panel of a window that is also selected")
        self.assertEqual(len(self.active_pane(win3)), 1)
        self.assertFalse(self.panels_of(win3)[0]["active"], "even in the window you are looking at it is not the active pane")
        self.assertEqual(len(self.panels()), 3)

    def test_a_panel_that_was_killed_comes_back(self):
        self.attach(50, 200)
        self.d.sync()
        time.sleep(dock.REMAKE_AFTER + 0.3)
        panel, = self.panels()
        self.tmux.run("kill-pane", "-t", panel["id"])
        self.wait(lambda: len(self.panels()) == 1 and self.panels()[0]["id"] != panel["id"], "a new panel")

    def test_a_panel_that_crashed_comes_back_at_the_next_sync(self):
        self.attach(50, 200)
        self.d.panel_argv = ["env", "SWARMBOX_SYSOP_PANEL=1", "sh", "-c", "sleep 0.3"]
        self.d.sync()
        self.wait(lambda: not self.panels(), "the stand-in to end")
        self.d.panel_argv = list(td.STAND_IN)
        self.assertEqual(self.d.sync(), "unchanged", "made a moment ago: not again at once (a panel that crashes at its start must not be made in a loop)")
        self.assertEqual(self.panels(), [])
        time.sleep(dock.REMAKE_AFTER + 0.2)
        self.assertEqual(self.d.sync(), "created 1")

    def test_a_panel_that_crashes_at_its_start_is_not_made_in_a_loop(self):
        self.attach(50, 200)
        self.d.panel_argv = ["env", "SWARMBOX_SYSOP_PANEL=1", "sh", "-c", "exit 1"]
        made = []
        real = self.d._create

        def counting(*a, **k):
            made.append(time.time())
            return real(*a, **k)
        self.d._create = counting
        self.d.sync()
        end = time.time() + 5.0
        while time.time() < end:                       # what the hook of the pane's exit does, as fast as it can
            self.d.sync()
            time.sleep(0.05)
        self.assertLessEqual(len(made), 3, "a panel made %d times in 5 s" % len(made))
        self.assertGreaterEqual(len(made), 2, "but it is tried again")

    def test_closing_the_user_pane_closes_a_window_that_holds_only_the_panel(self):
        self.attach(50, 200)
        w2, u2 = self.new_window()
        w3, u3 = self.new_window()
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "panels")
        self.tmux.run("kill-pane", "-t", u2)                         # tmux kill-pane of the pane of the user
        self.wait(lambda: w2 not in self.windows(), "the window of only a panel to close")
        self.assertEqual(sorted(self.windows()), sorted([self.win1, w3]))
        self.assertTrue(self.one_panel_in_each_window(), "the other windows keep theirs")
        self.tmux.run("send-keys", "-t", u3, "C-d")                  # the shell of the user ends: the program exits
        self.wait(lambda: w3 not in self.windows(), "the window whose program exited")
        self.assertEqual(self.windows(), [self.win1])
        self.assertEqual(len(self.panels()), 1)

    def test_the_last_window_closing_ends_the_session_as_it_would_without_a_panel(self):
        self.attach(50, 200)
        self.d.sync()
        self.wait(lambda: len(self.panels()) == 1, "panel")
        self.tmux.run("kill-pane", "-t", self.user)
        self.wait(lambda: self.tmux.run("has-session", "-t", "=main").rc != 0, "the session to end")

    def test_a_window_with_a_split_of_the_user_is_not_closed(self):
        self.attach(50, 200)
        self.d.sync()
        self.tmux.run("split-window", "-d", "-t", self.win1, "cat -v")
        time.sleep(1.0)
        self.assertEqual(self.windows(), [self.win1])
        self.assertEqual(len(self.panels()), 1)
        self.assertEqual(len([p for p in self.panes() if not p["panel"]]), 2)

    def test_sync_with_a_window_makes_only_that_panel(self):
        self.attach(50, 200)
        w2, _ = self.new_window()
        self.assertEqual(self.d.sync(window=w2), "created 1")
        self.assertEqual([p["win"] for p in self.panels()], [w2])


class TwoScreens(Always):
    """The computer and a phone on the same session: the window follows the client that last had focus, so it goes back and forth between 193 and 123 columns"""
    USE_BOX_CONF = True

    def test_the_panel_survives_two_screens_taking_the_window_by_turns(self):
        computer = self.attach(99, 193)
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "the panel")
        phone = self.attach(99, 123)
        for _ in range(8):
            computer.send(b"\x1b[I")
            time.sleep(0.4)
            phone.send(b"\x1b[I")
            time.sleep(0.4)
        time.sleep(2.5)
        self.d.sync()
        panels = self.panels()
        self.assertEqual(len(panels), 1, "one panel, not none and not two: %s" % self.panes())
        self.assertEqual(self.hidden(), False, "the panels were not hidden")
        self.assertTrue(self.tmux.run("list-panes", "-t", panels[0]["id"], "-F", "x").rc == 0)
        self.assertEqual(self.active_pane(self.win1), [self.user])


class Compact(Always):
    """A window of 80 columns or fewer (a phone) has no panel until it is opened: the key (or the Panel button, or a tap on the line of the page) opens it, the
    close control or q closes it, an approval makes a small second pane (the approval pane, not the panel) that goes after the answer, and a computer that takes
    the window back wide gets its panel back."""

    def flag(self):
        return self.tmux.run("show-options", "-gqv", "@swarmbox_sysop_open").out.strip()

    def test_a_narrow_window_has_no_panel_and_the_key_opens_and_closes_it(self):
        self.serve_files()
        self.attach(60, 50)
        self.d.sync()
        time.sleep(0.5)
        self.assertEqual(self.panels(), [], "no panel in a window of 50 columns")
        r = self.cli("toggle")
        self.assertEqual(r.returncode, 0, r.stderr)
        panel, = self.wait(self.panels, "the panel after the key")
        self.assertEqual(self.flag(), "1")
        self.wait(lambda: "✕ close" in self.screen(panel["id"]), "the close control on its head line: %r" % self.screen(panel["id"]))
        self.assertEqual(self.active_pane(self.win1), [self.user], "the panel did not take the focus")
        self.assertEqual(self.cli("toggle").returncode, 0)
        self.wait(lambda: not self.panels(), "the second key closes it")
        self.assertEqual(self.flag(), "")
        self.assertFalse(self.hidden(), "nothing was hidden for the other screens")

    def test_the_close_control_closes_the_panel_and_hides_nothing(self):
        self.serve_files()
        c = self.attach(60, 50)
        self.tmux.run("set-option", "-g", "mouse", "on")
        self.assertEqual(self.cli("toggle").returncode, 0)
        panel, = self.wait(self.panels, "the panel")
        self.wait(lambda: "✕ close" in self.screen(panel["id"]), "the panel ready")
        col, row = panel["left"] + panel["w"] - 3, panel["top"] + 1

        def click():
            c.send("\x1b[<0;%d;%dM\x1b[<0;%d;%dM" % (col, row, col, row))
        click()                                      # the first click gives the panel the focus
        self.wait(lambda: self.panels() and self.panels()[0]["active"], "the click to focus the panel")
        time.sleep(0.8)
        click()
        self.wait(lambda: not self.panels(), "the close control closes the panel")
        self.assertEqual(self.flag(), "")
        self.assertFalse(self.hidden())

    def test_q_in_a_narrow_panel_closes_it_and_hides_nothing(self):
        self.serve_files()
        c = self.attach(60, 50)
        self.tmux.run("set-option", "-g", "mouse", "on")
        self.assertEqual(self.cli("toggle").returncode, 0)
        panel, = self.wait(self.panels, "the panel")
        self.wait(lambda: "✕ close" in self.screen(panel["id"]), "the panel ready")
        c.send("\x1b[<0;%d;%dM\x1b[<0;%d;%dM" % (panel["left"] + 5, panel["top"] + 3, panel["left"] + 5, panel["top"] + 3))
        self.wait(lambda: self.panels() and self.panels()[0]["active"], "the click to focus the panel")
        time.sleep(0.8)
        self.tmux.run("send-keys", "-t", panel["id"], "q")
        self.wait(lambda: not self.panels(), "q closes it")
        self.assertEqual(self.flag(), "")
        self.assertFalse(self.hidden())

    def approvals(self):
        return [p for p in self.panes() if p["approval"]]

    def start_goal(self):
        self.serve_files(current="g1")
        gdir = self.pth.goal_dir("g1")
        os.makedirs(gdir, mode=0o700, exist_ok=True)
        ipc.write_json(os.path.join(gdir, "state.json"), {"id": "g1", "source": "voice", "text": "deploy", "state": "running", "created": time.time(), "started": time.time(),
                                                          "ended": None, "say": [], "calls": [], "pending": None, "summary": "", "error": "", "note": "", "steps": 0, "brain": {}})
        return gdir, os.path.join(gdir, "pending_action.json")

    def pend(self, path, mode="approve", text="git push --force", pid="p1"):
        now = time.time()
        ipc.write_json(path, {"id": pid, "goal": "g1", "tab": "@1", "label": "1:shell", "kind": "run", "text": text, "risk": "high", "reasons": ["a test"],
                              "mode": mode, "created": now, "deadline": now + 120})

    def test_an_approval_makes_a_small_pane_that_is_not_the_panel_and_it_goes_after_the_answer(self):
        gdir, pend = self.start_goal()
        self.attach(60, 50)
        f = dock.Follower(self.pth, dock=self.d, mode="always", interval=0.1, tick=0.5, grace=1.0, approval_grace=0.5).start()
        self.addCleanup(f.shutdown)
        time.sleep(1.0)
        self.assertEqual((self.panels(), self.approvals()), ([], []), "a goal that runs opens nothing")
        self.pend(pend)
        appr, = self.wait(self.approvals, "the approval pane", timeout=8)
        self.assertEqual(self.panels(), [], "the sysop panel is not opened for an approval")
        self.assertEqual(self.flag(), "")
        self.assertEqual((appr["w"], appr["h"]), (50, dock.Dock.approval_height(60)), "full width at the bottom, about ten rows")
        self.assertEqual(appr["top"] + appr["h"], 60, "below everything")
        self.assertEqual(self.active_pane(self.win1), [self.user], "and it does not take the focus")
        self.wait(lambda: "ALLOW?" in self.screen(appr["id"]), "the action on its screen: %r" % self.screen(appr["id"]))
        text = self.screen(appr["id"])
        for needle in ("high risk", "git push --force", "Allow", "Cancel"):
            self.assertIn(needle, text)
        self.assertNotIn("SYSOP", text, "the page reads that word to know the panel is up")
        self.assertNotIn("deploy", text, "the goal stays out")
        time.sleep(1.5)
        self.assertTrue(self.approvals(), "it stays while the action waits")
        os.unlink(pend)
        self.wait(lambda: not self.approvals(), "it goes by itself after the answer", timeout=10)

    def test_a_tap_on_allow_answers_in_one_tap_and_a_countdown_never_makes_the_pane(self):
        gdir, pend = self.start_goal()
        c = self.attach(60, 50)
        self.tmux.run("set-option", "-g", "mouse", "on")
        f = dock.Follower(self.pth, dock=self.d, mode="always", interval=0.1, tick=0.5, grace=1.0, approval_grace=0.5).start()
        self.addCleanup(f.shutdown)
        self.pend(pend, mode="veto", text="ls")
        time.sleep(1.5)
        self.assertEqual(self.approvals(), [], "a veto countdown is not for the approval pane")
        self.pend(pend, text="git push --force", pid="p2")
        appr, = self.wait(self.approvals, "the approval pane", timeout=8)
        self.wait(lambda: "Allow" in self.screen(appr["id"]), "the buttons")
        time.sleep(0.8)                                   # past the guard of half a second
        col, row = appr["left"] + 8, appr["top"] + appr["h"] - 2          # the middle of the left button (Allow)
        c.send("\x1b[<0;%d;%dM\x1b[<0;%d;%dM" % (col, row, col, row))
        dec = os.path.join(gdir, "decision.json")
        self.wait(lambda: os.path.exists(dec), "the decision written by one tap")
        self.assertEqual(ipc.read_json(dec), {"id": "p2", "decision": "approve", "by": "panel", "word": "run"})

    def test_the_panel_opened_by_hand_and_the_approval_pane_are_together_and_the_panel_stays_after(self):
        gdir, pend = self.start_goal()
        self.attach(60, 50)
        self.assertEqual(self.cli("toggle").returncode, 0)
        panel, = self.wait(self.panels, "the panel opened by hand")
        f = dock.Follower(self.pth, dock=self.d, mode="always", interval=0.1, tick=0.5, grace=1.0, approval_grace=0.5).start()
        self.addCleanup(f.shutdown)
        self.pend(pend)
        appr, = self.wait(self.approvals, "the approval pane", timeout=8)
        self.assertEqual([p["id"] for p in self.panels()], [panel["id"]], "the panel was not touched")
        time.sleep(1.5)
        self.assertEqual(len(self.approvals()), 1)
        self.assertEqual([p["id"] for p in self.panels()], [panel["id"]])
        os.unlink(pend)
        self.wait(lambda: not self.approvals(), "the approval pane goes", timeout=10)
        self.assertEqual([p["id"] for p in self.panels()], [panel["id"]], "the panel opened by hand stays")
        self.assertEqual(self.flag(), "1")

    def test_a_wide_window_gets_no_approval_pane_and_its_panel_answers(self):
        gdir, pend = self.start_goal()
        self.attach(50, 200)
        self.d.sync()
        panel, = self.wait(self.panels, "the panel of the wide window")
        f = dock.Follower(self.pth, dock=self.d, mode="always", interval=0.1, tick=0.5, grace=1.0, approval_grace=0.5).start()
        self.addCleanup(f.shutdown)
        self.pend(pend)
        self.wait(lambda: "allow? high risk" in self.screen(panel["id"]), "the approval in the panel")
        time.sleep(1.0)
        self.assertEqual(self.approvals(), [], "nothing new in a wide window")

    def test_a_phone_takes_the_panel_away_and_the_computer_brings_it_back(self):
        computer = self.attach(50, 200)
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "the panel")
        phone = self.attach(60, 50)
        phone.send(b"\x1b[I")
        width = lambda: self.tmux.run("display-message", "-p", "-t", self.win1, "#{window_width}").out.strip()
        self.wait(lambda: width() == "50", "the window to be the phone's")
        self.d.sync()
        self.wait(lambda: not self.panels(), "no panel in the phone's window: %s" % self.panes())
        computer.send(b"\x1b[I")
        self.wait(lambda: width() == "200", "the window to be the computer's")
        self.d.sync(force=True)
        self.wait(self.one_panel_in_each_window, "the panel is back for the computer")
        self.assertFalse(self.hidden())


class Resizing(Always):
    def test_a_resize_flips_the_layout_of_each_window(self):
        self.open_compact()
        c = self.attach(50, 200)               # landscape: right
        w2, _ = self.new_window()
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "panels")

        def shapes():
            out = {}
            for p in self.panels():
                out[p["win"]] = "right" if p["h"] == p["wh"] and p["w"] < p["ww"] else "bottom" if p["w"] == p["ww"] and p["h"] < p["wh"] else "?"
            return out
        self.assertEqual(shapes(), {self.win1: "right", w2: "right"})
        c.resize(70, 50)                       # a phone, upright: the window you look at flips at once, the other one when it is shown (tmux resizes it then)
        self.wait(lambda: shapes()[self.win1] == "bottom", "the window in view to flip to the bottom")
        self.tmux.run("select-window", "-t", w2)
        self.wait(lambda: shapes() == {self.win1: "bottom", w2: "bottom"}, "the other window to flip when shown")
        for p in self.panels():
            self.assertTrue(20 <= p["h"] <= 22, "30 %% of 70 lines: %d" % p["h"])
        self.assertEqual(self.active_pane(self.win1), [self.user])
        c.resize(50, 200)
        self.wait(lambda: shapes()[w2] == "right", "the window in view to flip back")
        self.tmux.run("select-window", "-t", self.win1)
        self.wait(lambda: shapes() == {self.win1: "right", w2: "right"}, "both windows flipped back")
        for p in self.panels():
            self.assertEqual(p["w"], 40, "20 %% of 200")

    def test_a_phone_that_changes_its_letters_keeps_one_panel_of_30_percent(self):
        """the letters of a phone shrink after the page opens and the window goes from 50 x 33 cells to 130 x 100 in a few steps (each refit): seen with two panels
        in the window, 70 % of its height between them, one showing Stop and the other Goal"""
        self.open_compact()
        c = self.attach(50, 33)
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "the panel")
        for rows, cols in ((50, 33), (90, 60), (130, 100), (130, 100), (118, 92), (130, 100), (60, 40), (130, 100)):
            c.resize(rows, cols)
            time.sleep(0.05)
        self.wait(lambda: self.panels() and self.panels()[0]["wh"] == 130, "the window to be 130 lines: %s" % self.panes())
        time.sleep(1.5)
        self.d.sync()
        panels = self.panels()
        self.assertEqual(len(panels), 1, "one panel in the window: %s" % self.panes())
        self.wait(lambda: abs(self.panels()[0]["h"] - 39) <= 2, "30 %% of 130 lines (now %s)" % self.panes())
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_a_short_portrait_window_gets_the_minimum_height(self):
        self.open_compact()
        self.attach(24, 60)
        self.d.sync()
        panel, = self.panels()
        self.assertEqual(panel["h"], 8)
        self.assertEqual(panel["w"], 60)

    def test_a_window_that_gets_shorter_keeps_a_useful_panel(self):
        """tmux shrinks panes in proportion and can leave a panel one line high: the hook puts the size back"""
        self.open_compact()
        c = self.attach(70, 50)
        self.d.sync()
        self.wait(lambda: self.panels() and self.panels()[0]["h"] == 21, "30 % of 70")
        for rows, want in ((24, 8), (40, 12), (100, 30), (30, 9)):
            c.resize(rows, 50)
            self.wait(lambda: self.panels() and self.panels()[0]["wh"] == rows and abs(self.panels()[0]["h"] - want) <= 1,
                      "the panel of %d lines in a window of %d (now %s)" % (want, rows, self.panes()))
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_the_idle_screen_at_several_widths(self):
        self.open_compact()
        self.serve_files()
        c = self.attach(50, 200)
        self.d.sync()
        panel, = self.wait(self.panels, "panel")
        for rows, cols, width in ((50, 200, 40), (70, 50, 50), (24, 60, 60), (30, 90, 90)):
            c.resize(rows, cols)
            self.wait(lambda: (self.panels() or [{}])[0].get("w") == width, "panel width %d at %dx%d" % (width, cols, rows))
            self.wait(lambda: "SYSOP" in (self.screen(panel["id"]).splitlines() or [""])[0], "the panel to redraw at %dx%d: %s" % (cols, rows, self.panes()))
            text = self.screen(panel["id"])
            self.assertIn("SYSOP", text.splitlines()[0])
            self.assertIn("Say a goal, or type it below.", text, (rows, cols))
            self.assertIn("Type a goal", text.splitlines()[-1] if text.splitlines()[-1].strip() else [x for x in text.splitlines() if x.strip()][-1], (rows, cols))
            for line in text.splitlines():
                self.assertLessEqual(len(line), width)


class Toggle(Always):
    def test_the_toggle_hides_all_windows_and_is_remembered_until_shown_again(self):
        self.attach(50, 200)
        w2, _ = self.new_window()
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "panels")
        r = self.cli("toggle", "--window", self.win1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("panel closed", r.stderr)
        self.wait(lambda: not self.panels(), "all panels to go")
        self.assertTrue(self.hidden())
        w3, _ = self.new_window()
        time.sleep(1.5)
        self.assertEqual(self.panels(), [], "a new window does not bring the panels back while they are hidden")
        self.assertEqual(self.cli("sync").returncode, 0)
        self.assertEqual(self.panels(), [], "nor does a sync")
        self.assertEqual(self.d.sync(), "hidden")
        r = self.cli("toggle", "--window", w3)
        self.assertIn("panel shown", r.stderr)
        self.wait(self.one_panel_in_each_window, "the panels in all three windows")
        self.assertFalse(self.hidden())
        w4, _ = self.new_window()
        self.wait(lambda: len(self.panels_of(w4)) == 1, "a new window follows again")

    def test_the_tmux_key_toggles(self):
        self.USE_BOX_CONF = True
        # a new server with the box's tmux.conf: the key is bound there
        self.tmux.run("kill-server")
        time.sleep(0.3)
        self.tmux = td.Tmux(argv=["tmux", "-L", self.sock, "-f", td.TMUX_CONF], env=self.env)
        self.assertEqual(self.tmux.run("new-session", "-d", "-s", "main", "-x", "100", "-y", "40", "-c", self.tmp, "cat -v").rc, 0)
        self.d = dock.default_dock(self.tmux)
        c = self.attach(40, 160)
        self.d.sync()
        self.wait(lambda: len(self.panels()) == 1, "panel")
        c.send("\x01S")
        self.wait(lambda: not self.panels() and self.hidden(), "the key to hide the panel")
        c.send("\x01S")
        self.wait(lambda: len(self.panels()) == 1 and not self.hidden(), "the key to show it again")

    def test_q_in_a_panel_hides_the_panels_of_all_windows(self):
        self.serve_files()
        self.attach(50, 200)
        w2, _ = self.new_window()
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "panels")
        panel = self.panels_of(self.win1)[0]
        self.wait(lambda: "Say a goal, or type it below." in self.screen(panel["id"]), "the panel to be ready")
        self.tmux.run("send-keys", "-t", panel["id"], "q")
        self.wait(lambda: not self.panels(), "q to hide the panels of every window")
        self.assertTrue(self.hidden())
        self.assertEqual(len(self.windows()), 2, "the windows stay")
        self.assertEqual(self.d.sync(), "hidden")

    def test_a_panel_killed_by_the_tmux_server_signal_is_not_a_hide(self):
        """the pane is killed (SIGHUP), not quit with q: it is not a choice of the user, so the panel comes back and nothing is hidden"""
        self.attach(50, 200)
        self.d.sync()
        time.sleep(dock.REMAKE_AFTER + 0.3)
        panel, = self.panels()
        self.tmux.run("kill-pane", "-t", panel["id"])
        self.wait(lambda: len(self.panels()) == 1, "it to come back")
        self.assertFalse(self.hidden())


class OtherModes(Always):
    def test_auto_and_off_never_make_panels_by_themselves(self):
        self.attach(50, 200)
        for mode in ("auto", "off"):
            d = dock.default_dock(self.tmux, mode=mode)
            self.assertEqual(d.sync(), "unchanged")
            self.assertEqual(self.panels(), [], mode)
            f = Follower(self.pth, dock=d, mode=mode)
            f.step()
            self.assertEqual(self.panels(), [], mode)
        self.assertNotIn("[418]", self.tmux.run("show-hooks", "-g", "after-new-window").out, "no hook of the sysop when it is not always")

    def test_a_service_that_starts_in_auto_or_off_after_an_always_leaves_no_hook_that_makes_panels(self):
        """the service restarted with another mode while the tmux server stayed up: the sync hooks of the earlier always carry mode=always, so
        every new window would still get a panel (found by the e2e: sysop.panel=auto came up with panels in every window)"""
        self.attach(50, 200)
        for mode in ("auto", "off"):
            dock.default_dock(self.tmux, mode="always").sync()
            self.assertIn("[418]", self.tmux.run("show-hooks", "-g", "after-new-window").out)
            self.assertNotEqual(self.tmux.run("show-options", "-gqv", "@swarmbox_sysop_sync").out.strip(), "")
            d = dock.default_dock(self.tmux, mode=mode)
            f = Follower(self.pth, dock=d, mode=mode).start()
            self.addCleanup(f.shutdown)
            deadline = time.time() + 5
            while time.time() < deadline and "[418]" in self.tmux.run("show-hooks", "-g", "after-new-window").out:
                time.sleep(0.1)
            f.shutdown()
            for h in dock.SYNC_HOOKS:
                self.assertNotIn("[418]", self.tmux.run("show-hooks", "-g", h.split("[")[0]).out, (mode, h))
            self.assertEqual(self.tmux.run("show-options", "-gqv", "@swarmbox_sysop_sync").out.strip(), "", mode)
            for p in self.panels():
                self.tmux.run("kill-pane", "-t", p["id"])
            w2, u2 = self.new_window()
            time.sleep(1.5)
            self.assertEqual([p for p in self.panels() if p["win"] == w2], [], "a new window gets no panel in %s" % mode)
            self.tmux.run("kill-window", "-t", w2)

    def test_by_hand_a_panel_opens_in_the_window_in_auto_and_off(self):
        self.attach(50, 200)
        for mode in ("auto", "off"):
            d = dock.default_dock(self.tmux, mode=mode)
            d.panel_argv = list(td.STAND_IN)
            self.assertEqual(d.toggle(window=self.win1), "created", mode)
            self.assertEqual(len(self.panels()), 1)
            self.assertEqual(d.toggle(window=self.win1), "closed", mode)
            self.assertEqual(self.panels(), [])
            self.assertFalse(self.hidden(), "the hidden choice is the mode always's")

    def test_sync_in_auto_still_closes_a_window_of_only_a_panel(self):
        self.attach(50, 200)
        w2, u2 = self.new_window()
        d = dock.default_dock(self.tmux, mode="auto")
        d.panel_argv = list(td.STAND_IN)
        d.open(window=w2, focus=False)
        self.tmux.run("kill-pane", "-t", u2)
        self.assertEqual(d.sync(), "closed 1 windows")
        self.assertEqual(self.windows(), [self.win1])

    def test_the_old_behaviour_of_auto_freezes_the_name_of_a_window_with_a_panel(self):
        self.attach(50, 200)
        d = dock.default_dock(self.tmux, mode="auto")
        d.panel_argv = list(td.STAND_IN)
        d.open(window=self.win1, focus=False)
        self.assertNotEqual(self.tmux.run("show-options", "-wqv", "-t", self.win1, "@swarmbox_sysop_ar").out.strip(), "")


class NoFocusSteal(Always):
    def test_typing_in_the_tab_while_windows_and_panels_come_and_go_reaches_only_the_tab(self):
        self.serve_files()
        c = self.attach(40, 160)
        self.d.sync()
        self.wait(lambda: len(self.panels()) == 1, "panel")
        state = {"n": 0, "run": True}

        def go():
            while state["run"]:
                c.send("xcgxqrXGayn")
                state["n"] += 1
                time.sleep(0.03)
        th = threading.Thread(target=go, daemon=True)
        th.start()
        time.sleep(0.5)
        for _ in range(3):                                         # windows come (the hook makes a panel) and go (a panel-only window closes)
            w, u = self.new_window()
            self.wait(lambda: len(self.panels_of(w)) == 1, "panel of the new window")
            self.tmux.run("kill-pane", "-t", u)
            self.wait(lambda: w not in self.windows(), "the window to close")
        time.sleep(1.0)
        state["run"] = False
        th.join()
        time.sleep(0.5)
        panel, = self.panels()
        self.assertFalse(panel["active"], "the panel never took the focus")
        self.assertEqual(self.active_pane(self.win1), [self.user])
        text = self.tmux.run("capture-pane", "-p", "-J", "-S", "-", "-t", self.user).out
        self.assertEqual(text.count("x"), 2 * state["n"], "every key typed reached the tab (x twice per send)")
        self.assertFalse(os.path.exists(self.pth.stop_request), "no x reached the panel")
        self.assertFalse(self.hidden(), "no q reached the panel")

    def test_a_click_on_the_panel_focuses_it_and_then_q_hides(self):
        self.serve_files()
        c = self.attach(40, 160)
        self.d.sync()
        panel, = self.wait(self.panels, "panel")
        self.wait(lambda: "Say a goal, or type it below." in self.screen(panel["id"]), "panel ready")
        self.tmux.run("set-option", "-g", "mouse", "on")
        c.send("\x1b[<0;%d;%dM\x1b[<0;%d;%dM" % (panel["left"] + 5, panel["top"] + 3, panel["left"] + 5, panel["top"] + 3))   # SGR: press, release
        self.wait(lambda: self.panels()[0]["active"], "the click to focus the panel")
        time.sleep(0.8)
        self.tmux.run("send-keys", "-t", panel["id"], "q")
        self.wait(lambda: not self.panels() and self.hidden(), "q of the focused panel hides")


class IdleCpu(Always):
    def test_idle_panels_use_almost_no_cpu(self):
        self.serve_files()
        self.attach(50, 200)
        self.new_window()
        self.new_window()
        self.d.sync()
        self.wait(self.one_panel_in_each_window, "panels")
        for p in self.panels():
            self.wait(lambda: "Say a goal, or type it below." in self.screen(p["id"]), "idle")
        pids = [self.pid_of(p["id"]) for p in self.panels()]

        def ticks():
            total = 0.0
            for pid in pids:
                with open("/proc/%s/stat" % pid) as f:
                    x = f.read().rsplit(")", 1)[1].split()
                total += (int(x[11]) + int(x[12])) / os.sysconf("SC_CLK_TCK")
            return total
        time.sleep(1.5)
        a, t0 = ticks(), time.time()
        time.sleep(10)
        used, wall = ticks() - a, time.time() - t0
        self.assertLess(used / wall, 0.02, "three idle panels used %.3f s of CPU in %.1f s" % (used, wall))


@unittest.skipUnless(td.HAVE, "needs tmux and a container (run it in Podman, see tests/slow/test_sysop_dock.py)")
class NoFocusAlways(td.NoFocus):
    """Every test of the keys that work from any tab (tests/slow/test_sysop_dock.py, NoFocus), again with the panel already up when the goal arrives: the
    panel of the mode always is the same program in the same pane, and typing, the veto, the approval gesture, the click and the goal key behave the same."""
    MODE = "always"

    def setUp(self):
        super().setUp()
        self.assertEqual(self.d.mode, "always")
        self.d.sync()
        self.wait(lambda: len(self.panels()) == 1, "the panel that is up before any goal")
        self.wait(lambda: any(w in self.tmux.run("capture-pane", "-p", "-t", self.panels()[0]["id"]).out for w in ("Say a goal, or type it below.", "The sysop is not running")), "the panel to draw")
        time.sleep(0.6)

    test_the_approval_gesture_opens_the_panel_when_it_is_not_there_and_does_not_focus_without_an_approval = None    # the panel is always there: the test below

    test_the_approval_gesture_does_nothing_without_an_approval_and_opens_no_panel = None    # the panel is always there: the test below

    def test_the_approval_gesture_does_nothing_without_an_approval_and_allows_with_one(self):
        self.svc.goal()
        self.client.send("\x01a")                          # no pending action
        time.sleep(1.0)
        panel, = self.panels()
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.assertIsNone(self.svc.decision())
        self.svc.pending(mode="approve", risk="high")
        self.client.send("\x01a")                          # a pending approval: allowed in one step, the panel that is up keeps its place and nobody gets the focus
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["decision"], d["by"], d["word"]), ("approve", "key", "run"))
        time.sleep(0.5)
        self.assertEqual(self.active_pane(self.win1), [self.user], "the gesture never takes the focus")
        self.assertEqual([p["id"] for p in self.panels()], [panel["id"]], "the same panel, no second one")

    def test_with_a_panel_in_every_window_the_gesture_allows_once_and_moves_no_focus(self):
        """found by tests/e2e/e2e_sysop.py (s4c) when the gesture went through a request file that every panel read: the wrong panel took it. The gesture now
        writes the decision itself, so the claim is: with a panel in each window it allows exactly the action that waits, and no pane gets the focus"""
        w2, u2 = self.new_window(detached=False)                    # the client now shows the second window
        self.d.sync()
        self.wait(lambda: len(self.panels()) == 2, "a panel in each window")
        self.wait(lambda: all(any(w in self.screen(p["id"]) for w in ("Say a goal, or type it below.", "The sysop is not running")) for p in self.panels()), "both to draw")
        time.sleep(0.6)
        self.svc.goal()
        self.svc.pending(mode="approve", risk="high", text="rm -r build")
        mine, other = self.panels_of(w2)[0], self.panels_of(self.win1)[0]
        self.wait(lambda: "allow? high risk" in self.screen(mine["id"]) and "allow? high risk" in self.screen(other["id"]), "the approval in the panel of each window")
        time.sleep(0.8)
        self.client.send("\x01a")
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["id"], d["decision"], d["by"], d["word"]), ("p1", "approve", "key", "run"))
        time.sleep(0.5)
        self.assertEqual(self.active_pane(w2), [u2], "the pane of the user of THIS window keeps the focus")
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.assertEqual(len(self.panels()), 2)

    def test_the_idle_screen_gives_way_to_the_goal_and_its_end_stays(self):
        panel = self.panels()[0]
        self.assertTrue(self.wait(lambda: "Say a goal, or type it below." in self.screen(panel["id"]), "idle"))
        self.svc.goal()                                   # a goal runs (status.json names it)
        self.wait(lambda: "run the tests" in self.screen(panel["id"]) and "Say a goal, or type it below." not in self.screen(panel["id"]), "the goal to replace the idle text")
        self.assertIn("working", self.screen(panel["id"]).splitlines()[0])
        self.svc.goal(state="done")
        self.svc.write_status(None)
        self.wait(lambda: "done" in self.screen(panel["id"]).splitlines()[0], "the end of the goal")
        text = self.screen(panel["id"])
        self.assertIn("run the tests", text, "the goal and its end stay on screen")
        self.assertNotIn("Say a goal, or type it below.", text, "that sentence is only for a panel that has seen no goal")

if __name__ == "__main__":
    unittest.main()
