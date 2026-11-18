"""Compact windows of the panel of the sysop (the mode always): a window of 80 columns or fewer (a phone) has no panel until it is opened, an approval
opens it and it closes by itself after, the key and the close control close it, and a wide window is not touched. A fake tmux that keeps panes, windows and
options (no real tmux: the real one is tests/slow/test_sysop_always.py). Run with: python3 -W error tests/fast/test_sysop_compact.py
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import dock, ipc  # noqa: E402
from swarmbox_sysop.dock import Dock, Follower, layout  # noqa: E402


class FakeTmux:
    """Windows with panes of the user and panels, global options, and just the tmux commands the dock uses."""

    def __init__(self):
        self.windows = {}          # id -> [width, height]
        self.panes = {}            # id -> dict(window, panel, w, h, argv)
        self.opts = {}
        self.calls = []
        self.n = 0

    def window(self, wid, cols, rows, panel=True, user=1):
        self.windows[wid] = [cols, rows]
        for _ in range(user):
            self._add(wid, False, cols, rows, [])
        if panel:
            self._panel(wid)
        return wid

    def _add(self, wid, panel, w, h, argv):
        self.n += 1
        pid = "%%%d" % self.n
        self.panes[pid] = {"window": wid, "panel": panel, "w": w, "h": h, "argv": argv}
        return pid

    def _panel(self, wid, argv=None):
        cols, rows = self.windows[wid]
        lay = layout(cols, rows)
        whole = rows if lay.kind == "bottom" else cols
        cells = whole * int(lay.size[:-1]) // 100 if lay.size.endswith("%") else int(lay.size)
        return self._add(wid, True, cols if lay.kind == "bottom" else cells, cells if lay.kind == "bottom" else rows, argv or ["panel"])

    def panels(self, wid=None):
        return [p for p, v in self.panes.items() if v["panel"] and (wid is None or v["window"] == wid)]

    def resize(self, wid, cols, rows):
        self.windows[wid] = [cols, rows]

    def run(self, *a):
        self.calls.append(a)
        cmd = a[0]
        if cmd == "list-panes":
            out = []
            for pid, v in self.panes.items():
                cols, rows = self.windows[v["window"]]
                bottom = v["w"] >= cols
                out.append(dock.SEP.join([pid, v["window"], "1", "1" if not v["panel"] else "0", "0", "0" if not v["panel"] else str(rows - v["h"] if bottom else 0),
                                          str(v["w"]), str(v["h"]), str(cols), str(rows), "1" if v["panel"] else "", "x", ""]))
            return dock.Result(0, "\n".join(out) + "\n", "")
        if cmd == "show-options":
            return dock.Result(0, self.opts.get(a[-1], "") + "\n", "")
        if cmd == "set-option":
            if "-gu" in a:
                self.opts.pop(a[-1], None)
            elif "-g" in a:
                self.opts[a[-2]] = a[-1]
            return dock.Result(0, "", "")
        if cmd == "kill-pane":
            self.panes.pop(a[-1], None)
            return dock.Result(0, "", "")
        if cmd == "kill-window":
            for pid in [p for p, v in self.panes.items() if v["window"] == a[-1]]:
                del self.panes[pid]
            self.windows.pop(a[-1], None)
            return dock.Result(0, "", "")
        if cmd == "split-window":
            wid = a[a.index("-t") + 1]
            argv = list(a[a.index("--") + 1:])
            return dock.Result(0, self._panel(wid, argv) + "\n", "")
        if cmd == "display-message":
            pane = a[a.index("-t") + 1] if "-t" in a else None
            if pane in self.panes and a[-1] == "#{window_width}":
                return dock.Result(0, "%d\n" % self.windows[self.panes[pane]["window"]][0], "")
            return dock.Result(0, "\n", "")
        if cmd in ("set-hook", "select-pane", "resize-pane", "join-pane", "list-windows"):
            return dock.Result(0, "", "")
        raise AssertionError("unexpected tmux call %r" % (a,))


def make_dock(tm, mode="always"):
    tmp = tempfile.mkdtemp(prefix="sbcmp-")
    return Dock(tm, panel_argv=["env", dock.PANEL_COMMAND, "python3", "panel"], mode=mode, lock_path=os.path.join(tmp, "dock.lock"))


PHONE, DESKTOP = (64, 100), (200, 50)


class CompactSync(unittest.TestCase):
    def setUp(self):
        self.tm = FakeTmux()
        self.d = make_dock(self.tm)

    def test_a_narrow_window_has_no_panel_and_a_wide_one_keeps_its_own(self):
        self.tm.window("@1", *PHONE)
        self.tm.window("@2", *DESKTOP)
        self.assertEqual(len(self.tm.panels("@1")), 1)
        self.assertIn("closed 1 compact", self.d.sync())
        self.assertEqual(self.tm.panels("@1"), [], "the phone's window loses its panel")
        self.assertEqual(len(self.tm.panels("@2")), 1, "the desktop's window keeps its panel, and it is the same pane")
        pane = self.tm.panels("@2")[0]
        self.d.sync()
        self.assertEqual(self.tm.panels("@2"), [pane])
        self.assertEqual(self.tm.panels("@1"), [], "and it stays without one at the next look")

    def test_a_narrow_window_is_80_columns_or_fewer(self):
        for cols, compact in ((30, True), (64, True), (80, True), (81, False), (120, False), (0, False)):
            self.assertEqual(Dock.is_compact(cols), compact, cols)
        self.assertEqual(dock.COMPACT_COLS, 80)
        for tm_cols in (80, 81):
            tm = FakeTmux()
            tm.window("@1", tm_cols, 120, panel=False)
            make_dock(tm).sync(force=True)
            self.assertEqual(len(tm.panels("@1")), 0 if tm_cols == 80 else 1, tm_cols)

    def test_a_new_narrow_window_does_not_get_one_and_a_new_wide_window_does(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.tm.window("@2", *DESKTOP, panel=False)
        self.d.sync(force=True)
        self.assertEqual((len(self.tm.panels("@1")), len(self.tm.panels("@2"))), (0, 1))

    def test_opened_by_hand_or_for_an_approval_the_narrow_window_has_one_with_the_close_control(self):
        for flag in ("1", "auto"):
            tm = FakeTmux()
            tm.window("@1", *PHONE, panel=False)
            d = make_dock(tm)
            tm.opts[dock.OPEN_OPTION] = flag
            d.sync(force=True)
            panels = tm.panels("@1")
            self.assertEqual(len(panels), 1, flag)
            self.assertIn(dock.COMPACT_ENV + "=1", tm.panes[panels[0]]["argv"], "the panel is told it is in a narrow window")
            d.sync(force=True)
            self.assertEqual(tm.panels("@1"), panels, "and keeps it")

    def test_a_wide_panel_is_not_told_it_is_narrow(self):
        self.tm.window("@1", *DESKTOP, panel=False)
        self.d.sync(force=True)
        self.assertNotIn(dock.COMPACT_ENV + "=1", self.tm.panes[self.tm.panels("@1")[0]]["argv"])

    def test_the_hidden_flag_still_governs_wide_windows_and_not_a_narrow_window_that_was_opened(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.tm.window("@2", *DESKTOP, panel=False)
        self.tm.opts[dock.HIDDEN_OPTION] = "1"
        self.tm.opts[dock.OPEN_OPTION] = "1"
        out = self.d.sync(force=True)
        self.assertEqual((len(self.tm.panels("@1")), len(self.tm.panels("@2"))), (1, 0))
        self.assertIn("hidden", out)

    def test_without_a_narrow_window_the_sync_is_what_it_always_was(self):
        self.tm.window("@1", *DESKTOP, panel=False)
        self.assertEqual(self.d.sync(force=True), "created 1")
        self.assertEqual(self.d.sync(), "unchanged")
        self.tm.opts[dock.HIDDEN_OPTION] = "1"
        self.assertEqual(self.d.sync(), "hidden")

    def test_a_desktop_that_takes_the_window_back_brings_the_panel_back_and_a_phone_takes_it_away(self):
        self.tm.window("@1", *DESKTOP)
        self.tm.resize("@1", *PHONE)
        self.d.sync()
        self.assertEqual(self.tm.panels("@1"), [], "the phone is the latest client: no panel")
        self.tm.resize("@1", *DESKTOP)
        self.d.sync(force=True)
        self.assertEqual(len(self.tm.panels("@1")), 1, "the desktop is: the panel is back")
        self.tm.resize("@1", *PHONE)
        self.d.sync()
        self.assertEqual(self.tm.panels("@1"), [])

    def test_the_resize_hook_takes_the_panel_away_at_once_in_a_narrow_window_only(self):
        self.tm.window("@1", *PHONE)
        self.tm.window("@2", *DESKTOP)
        self.d._redock_now("@2")
        self.assertEqual((len(self.tm.panels("@1")), len(self.tm.panels("@2"))), (1, 1), "the hook of another window does not touch it")
        self.d._redock_now("@1")
        self.assertEqual((len(self.tm.panels("@1")), len(self.tm.panels("@2"))), (0, 1))

    def test_the_other_modes_do_not_know_compact_windows(self):
        for mode in ("auto", "off"):
            tm = FakeTmux()
            tm.window("@1", *PHONE)
            d = make_dock(tm, mode)
            d.sync()
            self.assertEqual(len(tm.panels("@1")), 1, mode)
            self.assertEqual(d.approval(True), "unchanged")


class Toggle(unittest.TestCase):
    def setUp(self):
        self.tm = FakeTmux()
        self.d = make_dock(self.tm)

    def test_in_a_narrow_window_the_key_opens_and_closes_the_panel_and_nothing_is_hidden(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.assertEqual(self.d.toggle(window="@1"), "shown")
        self.assertEqual(self.tm.opts[dock.OPEN_OPTION], "1")
        self.assertEqual(len(self.tm.panels("@1")), 1)
        self.assertEqual(self.d.toggle(window="@1"), "closed")
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)
        self.assertEqual(self.tm.panels("@1"), [])
        self.assertNotIn(dock.HIDDEN_OPTION, self.tm.opts, "the choice of a phone does not hide the panels of a desktop")

    def test_the_shown_window_decides_when_no_window_is_given(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.assertEqual(self.d.toggle(), "shown")

    def test_a_toggle_while_the_panel_is_open_for_an_approval_closes_it(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.tm.opts[dock.OPEN_OPTION] = "auto"
        self.d.sync(force=True)
        self.assertEqual(self.d.toggle(window="@1"), "closed")
        self.assertEqual(self.tm.panels("@1"), [])

    def test_in_a_wide_window_the_key_hides_and_shows_every_panel_as_before(self):
        self.tm.window("@1", *DESKTOP)
        self.assertEqual(self.d.toggle(window="@1"), "closed")
        self.assertEqual(self.tm.opts[dock.HIDDEN_OPTION], "1")
        self.assertEqual(self.tm.panels("@1"), [])
        self.assertEqual(self.d.toggle(window="@1"), "shown")
        self.assertNotIn(dock.HIDDEN_OPTION, self.tm.opts)
        self.assertEqual(len(self.tm.panels("@1")), 1)
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)


class Approval(unittest.TestCase):
    def setUp(self):
        self.tm = FakeTmux()
        self.d = make_dock(self.tm)

    def test_an_action_that_waits_opens_the_panel_of_a_narrow_window_as_auto_and_the_answer_closes_it(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.assertEqual(self.d.approval(True), "opened")
        self.assertEqual(self.tm.opts[dock.OPEN_OPTION], "auto")
        self.assertEqual(len(self.tm.panels("@1")), 1)
        self.assertEqual(self.d.approval(True), "unchanged", "once")
        self.assertEqual(self.d.approval(False), "closed")
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)
        self.assertEqual(self.tm.panels("@1"), [])

    def test_a_panel_opened_by_hand_stays_after_the_answer(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.d.toggle(window="@1")
        self.assertEqual(self.d.approval(True), "unchanged")
        self.assertEqual(self.d.approval(False), "unchanged")
        self.assertEqual(self.tm.opts[dock.OPEN_OPTION], "1")
        self.assertEqual(len(self.tm.panels("@1")), 1)

    def test_with_no_narrow_window_there_is_nothing_to_open(self):
        self.tm.window("@1", *DESKTOP)
        self.assertEqual(self.d.approval(True), "unchanged")
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)


class Closing(unittest.TestCase):
    def setUp(self):
        self.tm = FakeTmux()
        self.d = make_dock(self.tm)

    def test_the_close_of_a_narrow_panel_closes_the_narrow_panels_only(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.tm.window("@2", *DESKTOP)
        self.tm.opts[dock.OPEN_OPTION] = "1"
        self.d.sync(force=True)
        own = self.tm.panels("@1")[0]
        self.d.close_compact(own_pane=own)
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)
        self.assertEqual(self.tm.panels("@1"), [])
        self.assertEqual(len(self.tm.panels("@2")), 1)
        self.assertNotIn(dock.HIDDEN_OPTION, self.tm.opts)

    def _quit(self, window):
        pane = self.tm.panels(window)[0]
        env = {"TMUX": "/tmp/x.sock,1,0", "TMUX_PANE": pane, "SWARMBOX_SYSOP_PANEL_MODE": "always"}
        with mock.patch.dict(os.environ, env), mock.patch.object(dock, "Tmux", lambda argv=None: self.tm):
            dock.panel_quit()

    def test_q_in_a_narrow_panel_closes_it_and_q_in_a_wide_one_hides_every_panel(self):
        self.tm.window("@1", *PHONE, panel=False)
        self.tm.window("@2", *DESKTOP)
        self.tm.opts[dock.OPEN_OPTION] = "1"
        self.d.sync(force=True)
        self._quit("@1")
        self.assertEqual(self.tm.panels("@1"), [])
        self.assertNotIn(dock.OPEN_OPTION, self.tm.opts)
        self.assertEqual(len(self.tm.panels("@2")), 1)
        self.assertNotIn(dock.HIDDEN_OPTION, self.tm.opts, "the phone's q did not hide the desktop's panel")
        self._quit("@2")
        self.assertEqual(self.tm.opts.get(dock.HIDDEN_OPTION), "1", "q in a wide window hides them all, as before")


class FollowerApproval(unittest.TestCase):
    """The Follower in the mode always: an action that waits opens the panel (once for each action) and it closes `grace` seconds after the answer."""

    class Dk:
        def __init__(self):
            self.calls = []

        def sync(self):
            self.calls.append("sync")

        def approval(self, on):
            self.calls.append(("approval", on))

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)
        self.now, self.dk = [0.0], self.Dk()
        self.f = Follower(self.pth, dock=self.dk, mode="always", clock=lambda: self.now[0], log=lambda m: None, grace=3.0)

    def approvals(self):
        return [c for c in self.dk.calls if isinstance(c, tuple)]

    def test_it_opens_once_for_each_action_and_closes_after_the_grace(self):
        self.svc.goal("deploy")
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [], "a goal that runs is not an approval")
        self.svc.pending("approve", "high")
        self.f.watch_approval()
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [("approval", True)], "opened once")
        os.unlink(os.path.join(self.pth.goal_dir("g1"), "pending_action.json"))
        self.f.watch_approval()
        self.now[0] += 2.9
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [("approval", True)], "not before the grace")
        self.now[0] += 0.2
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [("approval", True), ("approval", False)])
        self.f.watch_approval()
        self.assertEqual(len(self.approvals()), 2)

    def test_a_second_action_before_the_grace_keeps_the_panel_and_a_countdown_never_opens_it(self):
        self.svc.goal("deploy")
        self.svc.pending("veto", "low")
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [], "a countdown (veto) is not an approval")
        self.svc.pending("approve", "high")
        self.f.watch_approval()
        os.unlink(os.path.join(self.pth.goal_dir("g1"), "pending_action.json"))
        self.f.watch_approval()
        self.now[0] += 2
        ipc.write_json(os.path.join(self.pth.goal_dir("g1"), "pending_action.json"),
                       {"id": "p2", "goal": "g1", "tab": "@1", "label": "x", "kind": "run", "text": "y", "risk": "high", "reasons": [], "mode": "approve",
                        "created": time.time(), "deadline": time.time() + 60})
        self.f.watch_approval()
        self.now[0] += 10
        self.f.watch_approval()
        self.assertEqual(self.approvals(), [("approval", True), ("approval", True)], "the second action opens it again, and nothing closed it in between")

    def test_an_expired_action_is_not_waiting_and_step_does_both_things(self):
        self.svc.goal("x")
        self.svc.pending("approve", "high", seconds=-5)
        self.f.step()
        self.assertEqual(self.dk.calls, ["sync"])
        self.svc.pending("approve", "high")
        self.f.step()
        self.assertEqual(self.dk.calls, ["sync", "sync", ("approval", True)])

    def test_the_thread_watches_between_the_syncs(self):
        f = Follower(self.pth, dock=self.dk, mode="always", log=lambda m: None, interval=0.02, tick=0.2)
        self.svc.goal("x")
        f.start()
        self.addCleanup(f.shutdown)
        ss.wait_for(lambda: self.dk.calls, 5)
        self.svc.pending("approve", "high")
        ss.wait_for(lambda: ("approval", True) in self.dk.calls, 2)
        self.assertIn(("approval", True), self.dk.calls, "seen at a look of the thread, not only at a sync")
        self.assertLess(self.dk.calls.count("sync"), 20)


if __name__ == "__main__":
    unittest.main()
