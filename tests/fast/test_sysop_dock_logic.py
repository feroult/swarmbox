"""The panel of the sysop that needs no tmux: the layout rule (ONE pure function of the size of the window), the marks and hooks the dock sets and
swarmbox-tabs hides, the key of tmux.conf, the setting sysop.panel and its three modes (config.py), and the Follower for each mode with a fake dock
(always syncs, off does nothing, auto follows the goals, a trouble is said once). The panel in real panes, windows and clients is
tests/slow/test_sysop_dock.py and test_sysop_always.py (real tmux, in Podman).
Run with: python3 -W error tests/fast/test_sysop_dock_logic.py
"""
import importlib.util
import os
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
from helpers import ROOT  # noqa: E402
from waiting import wait_until  # noqa: E402

from swarmbox_sysop import config, dock, ipc  # noqa: E402
from swarmbox_sysop.dock import DockError, Follower, Layout, Tmux, layout, split_args  # noqa: E402

TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
BOTTOM = Layout("bottom", "30%")
SETTINGS = {"topic": "goal", "autonomy": "confirm-risky", "brain": "claude", "model": "haiku", "panel": "always"}


def slurp(path):
    with open(path) as f:
        return f.read()


class LayoutRule(unittest.TestCase):
    def test_the_constants_are_the_ones_of_the_design(self):
        self.assertEqual((dock.CELL_FACTOR, dock.BOTTOM_PERCENT, dock.RIGHT_PERCENT, dock.MIN_PANEL_COLS, dock.MIN_TERMINAL_COLS, dock.MIN_BOTTOM_ROWS), (2, 30, 20, 40, 60, 8))

    def test_portrait_windows_get_a_full_width_pane_at_the_bottom(self):
        for cols, rows in ((50, 70), (40, 80), (30, 40), (80, 41), (60, 31), (100, 51), (200, 101), (1, 1000)):
            self.assertEqual(layout(cols, rows), BOTTOM, (cols, rows))

    def test_landscape_windows_get_20_percent_at_the_right_edge(self):
        self.assertEqual(layout(200, 50), Layout("right", "20%"))
        self.assertEqual(layout(300, 50), Layout("right", "20%"))
        self.assertEqual(layout(400, 100), Layout("right", "20%"))

    def test_the_right_pane_is_never_narrower_than_40_columns(self):
        self.assertEqual(layout(150, 50), Layout("right", "40"))      # 20 % of 150 is 30: the minimum applies, in columns
        self.assertEqual(layout(120, 40), Layout("right", "40"))
        self.assertEqual(layout(200, 50), Layout("right", "20%"))     # 20 % of 200 is exactly 40, of 199 is 39
        self.assertEqual(layout(199, 50), Layout("right", "40"))

    def test_a_narrow_landscape_window_falls_back_to_the_bottom(self):
        self.assertEqual(layout(90, 30), BOTTOM)
        self.assertEqual(layout(100, 30), BOTTOM, "100 columns: 40 + the border leave 59")
        self.assertEqual(layout(101, 30), Layout("right", "40"), "101 columns: 40 + the border leave 60, enough")
        self.assertEqual(layout(60, 20), Layout("bottom", "8"), "a short window: 30 % would be 6 lines, 8 is the least that is useful")
        self.assertEqual(layout(80, 24), Layout("bottom", "8"))

    def test_the_portrait_boundary_is_cols_below_twice_the_rows(self):
        self.assertEqual(layout(119, 60), BOTTOM)
        self.assertEqual(layout(120, 60), Layout("right", "40"), "exactly twice as many columns as rows is landscape")
        self.assertEqual(layout(121, 60), Layout("right", "40"))
        self.assertEqual(layout(239, 120), BOTTOM)

    def test_nonsense_sizes_give_the_bottom_layout(self):
        for cols, rows in ((0, 0), (-5, 10), (10, 0), (None, None), ("x", 5), (0, 30)):
            self.assertEqual(layout(cols, rows), BOTTOM, (cols, rows))

    def test_the_rule_is_a_function_of_the_size_alone(self):
        for cols in range(1, 260, 7):
            for rows in range(1, 120, 5):
                lay = layout(cols, rows)
                self.assertIn(lay.kind, ("bottom", "right"))
                if lay.kind == "right":
                    width = cols * 20 // 100 if lay.size == "20%" else int(lay.size)
                    self.assertGreaterEqual(width, 40)
                    self.assertGreaterEqual(cols - width - 1, 60)
                    self.assertGreaterEqual(cols, 2 * rows)
                elif rows * 30 // 100 >= 8:
                    self.assertEqual(lay.size, "30%")
                else:
                    self.assertEqual(lay.size, str(max(1, min(8, rows // 2))), (cols, rows))

    def test_the_tmux_flags(self):
        self.assertEqual(split_args(BOTTOM), ["-f", "-v", "-l", "30%"])
        self.assertEqual(split_args(Layout("right", "20%")), ["-f", "-h", "-l", "20%"])
        self.assertEqual(split_args(Layout("right", "40")), ["-f", "-h", "-l", "40"])


class DockWiring(unittest.TestCase):
    """What needs no tmux: the marks, the hook, the key in the file."""

    def test_the_marks_are_the_ones_swarmbox_tabs_hides(self):
        spec = importlib.util.spec_from_file_location("swarmbox_tabs", os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIn(dock.PANEL_OPTION, mod.HIDDEN_OPTIONS)
        self.assertEqual(dock.PANEL_OPTION, "@swarmbox_sysop_panel")
        self.assertEqual(dock.PANEL_COMMAND, "SWARMBOX_SYSOP_PANEL=1")

    def test_the_hook_has_its_own_slot(self):
        self.assertEqual(dock.HOOK, "window-resized[418]")      # [417] was the voice panel's, removed: nobody else's slot is touched

    def test_the_hooks_keep_the_session_and_the_tabs_socket_of_the_service(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update({"SB_TABS_SESSION": "work", "SB_TABS_SOCKET": "sock-x", "SB_TABS_BIN": "/opt/tabs"})
        d = dock.default_dock(Tmux(argv=["tmux", "-L", "never-started-%d" % os.getpid()]))
        for argv in (d.redock_argv, d.sync_argv):
            for want in ("SB_TABS_SESSION=work", "SB_TABS_SOCKET=sock-x", "SB_TABS_BIN=/opt/tabs"):
                self.assertIn(want, argv)
        self.assertEqual(d.session, "work")

    def test_the_default_dock_runs_this_library_and_hands_the_folders_on(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(SB_RUN_DIR="/tmp/run-x", SB_STATE_DIR="/tmp/state-x", SB_BUS_SOCKET="/tmp/bus-x.sock")
        d = dock.default_dock(Tmux(argv=["tmux", "-L", "never-started-%d" % os.getpid()]))
        self.assertEqual(d.panel_argv[:2], ["env", "SWARMBOX_SYSOP_PANEL=1"])
        self.assertEqual(d.panel_argv[-3:], ["-m", "swarmbox_sysop", "panel"])
        for words in (d.panel_argv, d.redock_argv):
            for want in ("SB_RUN_DIR=/tmp/run-x", "SB_STATE_DIR=/tmp/state-x", "SB_BUS_SOCKET=/tmp/bus-x.sock", sys.executable):
                self.assertIn(want, words)
            self.assertTrue(any(w.startswith("PYTHONPATH=") and ss.LIB in w for w in words))
        self.assertEqual(d.redock_argv[-3:], ["swarmbox_sysop", "dock", "redock"])

    def test_the_tmux_file_binds_a_free_key_for_the_sysop_and_none_for_voice(self):
        conf = slurp(TMUX_CONF)
        binds = [ln for ln in conf.splitlines() if re.match(r"\s*bind\s+S\s", ln)]
        self.assertEqual(len(binds), 1, binds)
        self.assertIn("swarmbox-sysop dock toggle --socket '#{socket_path}' --window '#{window_id}'", binds[0])
        self.assertEqual([ln for ln in conf.splitlines() if re.match(r"\s*bind\s+v\s", ln)], [], "voice has no panel and no key")
        self.assertNotIn("swarmbox-voice", conf)

    def test_the_cli_refuses_a_bad_window_and_a_bad_action(self):
        for bad in ("1", "%1", "@x", "-t", "@1;kill-server", ""):
            r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "dock", "toggle", "--window", bad], env=dict(os.environ, PYTHONPATH=ss.LIB, SB_TABS_SOCKET="never-%d" % os.getpid()),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2, bad)
        r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "dock", "nonsense"], env=dict(os.environ, PYTHONPATH=ss.LIB), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)


class Setting(unittest.TestCase):
    def test_the_default_is_always_and_the_three_values_are_accepted(self):
        self.assertEqual(config.panel_mode({}), "always")
        self.assertEqual(config.panel_mode({"SWARMBOX_SYSOP_PANEL_MODE": ""}), "always")
        for v in ("always", "auto", "off"):
            self.assertEqual(config.panel_mode({"SWARMBOX_SYSOP_PANEL_MODE": v}), v)
            self.assertEqual(config.load({"SWARMBOX_SYSOP_PANEL_MODE": v}).panel_mode, v)

    def test_a_wrong_value_names_the_variable(self):
        for bad in ("Always", "on", "never", "1", "auto ", "always\n"):
            with self.assertRaises(config.ConfigError, msg=repr(bad)) as cm:
                config.load({"SWARMBOX_SYSOP_PANEL_MODE": bad})
            self.assertIn("SWARMBOX_SYSOP_PANEL_MODE", str(cm.exception))

    def test_the_name_does_not_collide_with_the_marker_of_a_panel_pane(self):
        self.assertEqual(config.ENV["panel_mode"], "SWARMBOX_SYSOP_PANEL_MODE")
        self.assertNotEqual(config.ENV["panel_mode"], "SWARMBOX_SYSOP_PANEL")
        self.assertEqual(dock.PANEL_COMMAND, "SWARMBOX_SYSOP_PANEL=1")
        self.assertNotIn(dock.PANEL_COMMAND, "SWARMBOX_SYSOP_PANEL_MODE=1")

    def test_the_dock_gets_the_mode_from_the_environment_and_hands_it_on(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop("SWARMBOX_SYSOP_PANEL_MODE", None)
        self.assertEqual(dock.default_dock(Tmux(argv=["tmux", "-L", "never-%d" % os.getpid()])).mode, "always")
        os.environ["SWARMBOX_SYSOP_PANEL_MODE"] = "off"
        d = dock.default_dock(Tmux(argv=["tmux", "-L", "never-%d" % os.getpid()]))
        self.assertEqual(d.mode, "off")
        for argv in (d.panel_argv, d.redock_argv, d.sync_argv):
            self.assertIn("SWARMBOX_SYSOP_PANEL_MODE=off", argv)
        self.assertEqual(d.sync_argv[-3:], ["swarmbox_sysop", "dock", "sync"])
        os.environ["SWARMBOX_SYSOP_PANEL_MODE"] = "bogus"
        self.assertEqual(dock.default_dock(Tmux(argv=["tmux", "-L", "never-%d" % os.getpid()])).mode, "always", "the service refuses a bad value at its start")

    def test_the_status_of_the_service_carries_the_mode(self):
        from swarmbox_sysop import service
        with open(service.__file__) as f:
            self.assertIn('"panel": self.cfg.panel_mode', f.read())

    def test_the_cli_knows_the_sync_action(self):
        self.assertIn("sync", dock.ACTIONS)


class OptionTmux:
    """A tmux that knows only the window options the dock freezes the tab name with: `automatic-rename` (absent = inherited from the session) and the
    dock's own remembering option."""
    def __init__(self, opts=None):
        self.opts = dict(opts or {})

    def run(self, *args):
        a = list(args)
        if a[0] == "show-options":
            name = a[-1]
            v = self.opts.get(name)
            if "-wqv" in a:
                return dock.Result(0, (v or "") + "\n", "")
            return dock.Result(0, "%s %s\n" % (name, v) if v else "", "")
        if a[0] == "set-option":
            if a[1] == "-wu":
                self.opts.pop(a[-1], None)
            else:
                self.opts[a[-2]] = a[-1]
            return dock.Result(0, "", "")
        raise AssertionError("unexpected tmux call %r" % (a,))


class TabName(unittest.TestCase):
    """Found by the e2e run: tmux names a window after the command of its ACTIVE pane and the panel takes the focus, so the Claude Code tab was called
    "python3" while the panel was open. The dock freezes automatic-rename while a panel is there and gives back exactly what the window had (the real
    tmux version of this is tests/slow/test_sysop_dock.py::TabName)."""

    def cycle(self, before):
        tm = OptionTmux(before)
        d = dock.Dock(tm)
        d._freeze_name("@1")
        frozen = tm.opts.get("automatic-rename")
        d._freeze_name("@1")   # idempotent: the second call must not remember "off" as the user's value
        d._thaw_name("@1")
        return frozen, tm.opts

    def test_the_name_is_frozen_while_the_panel_is_there_and_given_back_as_it_was(self):
        for before, after in (({}, {}), ({"automatic-rename": "on"}, {"automatic-rename": "on"}), ({"automatic-rename": "off"}, {"automatic-rename": "off"})):
            with self.subTest(before=before):
                frozen, opts = self.cycle(before)
                self.assertEqual(frozen, "off")
                self.assertEqual(opts, after, "a tab the user renamed (automatic-rename off) stays renamed; an inherited setting is inherited again")

    def test_a_window_that_was_never_frozen_is_left_alone_by_the_thaw(self):
        tm = OptionTmux({"automatic-rename": "off"})
        dock.Dock(tm)._thaw_name("@1")
        self.assertEqual(tm.opts, {"automatic-rename": "off"})


class FakeDock:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def sync(self):
        self.calls.append("sync")
        if self.fail:
            raise self.fail

    def forget_sync(self):
        self.calls.append("forget_sync")

    def open(self, **kw):
        self.calls.append(("open", kw))

    def close(self, **kw):
        self.calls.append(("close", kw))


class FollowerModes(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()
        self.now, self.log = 0.0, []

    def follower(self, mode, dk, **kw):
        return Follower(self.pth, dock=dk, mode=mode, clock=lambda: self.now, log=self.log.append, **kw)

    def test_always_syncs_at_every_step_and_never_looks_at_goals(self):
        dk = FakeDock()
        f = self.follower("always", dk)
        ipc.write_json(self.pth.status, {"pid": 1, "current": "g1", "queue": []})
        f.step()
        f.step()
        self.assertEqual(dk.calls, ["sync", "sync"])

    def test_off_does_nothing(self):
        dk = FakeDock()
        f = self.follower("off", dk)
        ipc.write_json(self.pth.status, {"pid": 1, "current": "g1", "queue": []})
        f.step()
        self.assertEqual(dk.calls, [])

    def test_auto_opens_for_a_goal_without_focus_and_closes_after_the_grace(self):
        dk = FakeDock()
        f = self.follower("auto", dk)
        f.step()
        self.assertEqual(dk.calls, [])
        ipc.write_json(self.pth.status, {"pid": 1, "current": "g1", "queue": []})
        f.step()
        self.assertEqual(dk.calls, [("open", {"auto": True, "focus": False})])
        ipc.write_json(self.pth.status, {"pid": 1, "current": None, "queue": []})
        self.now = 1
        f.step()
        self.now = 5
        f.step()
        self.assertEqual(dk.calls[-1], ("close", {"only_auto": True}))

    def test_status_json_is_read_again_only_when_it_changed(self):
        f = self.follower("auto", FakeDock())
        ipc.write_json(self.pth.status, {"pid": 1, "current": None, "queue": []})
        f.step()
        first = f._status
        f.step()
        self.assertIs(f._status, first, "same file: the parsed content is kept, nothing is read")
        ipc.write_json(self.pth.status, {"pid": 1, "current": "g1", "queue": []})
        f.step()
        self.assertIsNot(f._status, first)

    def test_the_same_trouble_is_said_once(self):
        dk = FakeDock(fail=DockError("the tmux session 'main' is not available"))
        f = self.follower("always", dk)
        for _ in range(5):
            f.step()
        self.assertEqual(len(self.log), 1, self.log)
        dk.fail = DockError("another trouble")
        f.step()
        self.assertEqual(len(self.log), 2)
        dk.fail = None
        f.step()
        dk.fail = DockError("another trouble")
        f.step()
        self.assertEqual(len(self.log), 3, "said again after a good look")

    def test_an_unexpected_error_does_not_take_the_service_down(self):
        f = self.follower("always", FakeDock(fail=ValueError("boom")))
        f.step()
        self.assertIn("boom", self.log[0])

    def test_the_thread_in_the_mode_always_syncs_at_once_and_then_at_the_tick(self):
        dk = FakeDock()
        f = self.follower("always", dk, tick=0.05).start()
        self.addCleanup(f.shutdown)
        self.assertTrue(wait_until(lambda: len(dk.calls) >= 3, 5), dk.calls)
        time.sleep(0.3)
        self.assertLessEqual(len(dk.calls), 20, "a tick, not a busy loop")

    def test_the_thread_in_auto_or_off_takes_away_the_hooks_of_an_earlier_always_once_and_the_mode_always_never_does(self):
        for mode in ("auto", "off", "always"):
            dk = FakeDock()
            f = self.follower(mode, dk, tick=0.05).start()
            wait_until(lambda: dk.calls, 5)
            time.sleep(0.15)
            f.shutdown()
            f.thread.join(2)
            self.assertEqual(dk.calls.count("forget_sync"), 0 if mode == "always" else 1, (mode, dk.calls))


class AlwaysWiring(unittest.TestCase):
    def test_serve_starts_the_follower_in_every_mode_so_that_off_also_drops_the_old_hooks(self):
        """found by the e2e (sysop.panel=off after an always in the same box still made panels in new windows): serve skipped the Follower in off, so nothing took
        the hooks of the earlier always away"""
        cli = slurp(os.path.join(os.path.dirname(dock.__file__), "cli.py"))
        line = next(x for x in cli.splitlines() if "dock.Follower(" in x)
        self.assertNotIn('"off"', line.split("#")[0])
        self.assertIn("args.dock", line)

    def test_the_tmux_file_says_what_the_key_does_in_each_mode(self):
        conf = slurp(TMUX_CONF)
        self.assertIn("`always`", conf)
        self.assertIn("`auto`", conf)
        self.assertIn("`off`", conf)

    def test_the_hooks_have_the_slot_of_the_sysop(self):
        for h in dock.SYNC_HOOKS + (dock.HOOK,):
            self.assertTrue(h.endswith("[418]"), h)
        self.assertEqual(set(h.split("[")[0] for h in dock.SYNC_HOOKS), {"after-new-window", "pane-exited", "after-kill-pane"})


if __name__ == "__main__":
    unittest.main()
