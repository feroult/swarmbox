"""Docking of the voice panel (container/tools/voice/lib/swarmbox_voice/dock.py).

  * layout(cols, rows) is ONE pure function: portrait -> a full-width pane at the bottom, 40 % of the height; otherwise a pane at the right
    edge, 20 % of the width, at least 40 columns; if that leaves the terminal fewer than 60 columns, the bottom layout. Boundaries are tested.
  * the real thing against a REAL tmux on a private socket with real clients attached through a pty (skipped when tmux is missing):
    where the pane goes for a portrait, a landscape and a narrow landscape window, never two panels, the user's panes untouched, the panel
    is a marked pane that the context and the executor leave out, several windows, the toggle, the key binding of container/config/tmux.conf,
    and the hook: resizing the window moves the SAME pane (its program keeps running), and the hook removes itself when no panel is left.

Run with: python3 -W error tests/test_voice_dock.py
"""
import fcntl
import os
import pty
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_voice import context, dock, executor  # noqa: E402
from swarmbox_voice.dock import Layout, layout, split_args  # noqa: E402
from swarmbox_voice.tmuxrun import Tmux  # noqa: E402

LIB = os.path.join(voice_support.VOICE, "lib")
TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
BOTTOM = Layout("bottom", "40%")


def slurp(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


class LayoutRule(unittest.TestCase):
    def test_the_constants_are_the_ones_of_the_design(self):
        self.assertEqual((dock.CELL_FACTOR, dock.BOTTOM_PERCENT, dock.RIGHT_PERCENT, dock.MIN_PANEL_COLS, dock.MIN_TERMINAL_COLS),
                         (2, 40, 20, 40, 60))

    def test_portrait_windows_get_a_full_width_pane_at_the_bottom(self):
        for cols, rows in ((50, 70), (40, 80), (30, 40), (80, 41), (60, 31), (100, 51), (200, 101), (1, 1000)):
            self.assertEqual(layout(cols, rows), BOTTOM, (cols, rows))

    def test_landscape_windows_get_20_percent_at_the_right_edge(self):
        self.assertEqual(layout(200, 50), Layout("right", "20%"))
        self.assertEqual(layout(300, 50), Layout("right", "20%"))
        self.assertEqual(layout(400, 100), Layout("right", "20%"))

    def test_the_right_pane_is_never_narrower_than_40_columns(self):
        # 20 % of 150 is 30: the minimum applies and the size is given in columns
        self.assertEqual(layout(150, 50), Layout("right", "40"))
        self.assertEqual(layout(120, 40), Layout("right", "40"))
        # the boundary of the minimum: 20 % of 200 is exactly 40, of 199 is 39
        self.assertEqual(layout(200, 50), Layout("right", "20%"))
        self.assertEqual(layout(199, 50), Layout("right", "40"))

    def test_a_narrow_landscape_window_falls_back_to_the_bottom(self):
        self.assertEqual(layout(90, 30), BOTTOM)
        self.assertEqual(layout(100, 30), BOTTOM, "100 columns: 40 + the border leave 59")
        self.assertEqual(layout(101, 30), Layout("right", "40"), "101 columns: 40 + the border leave 60, enough")
        self.assertEqual(layout(60, 20), BOTTOM)
        self.assertEqual(layout(80, 24), BOTTOM)

    def test_the_portrait_boundary_is_cols_below_twice_the_rows(self):
        self.assertEqual(layout(119, 60), BOTTOM)
        self.assertEqual(layout(120, 60), Layout("right", "40"), "exactly twice as many columns as rows is landscape")
        self.assertEqual(layout(121, 60), Layout("right", "40"))
        self.assertEqual(layout(239, 120), BOTTOM)
        self.assertEqual(layout(240, 120), Layout("right", "20%") if 240 * 20 // 100 >= 40 else Layout("right", "40"))

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
                else:
                    self.assertEqual(lay.size, "40%")

    def test_the_tmux_flags(self):
        self.assertEqual(split_args(BOTTOM), ["-f", "-v", "-l", "40%"])
        self.assertEqual(split_args(Layout("right", "20%")), ["-f", "-h", "-l", "20%"])
        self.assertEqual(split_args(Layout("right", "40")), ["-f", "-h", "-l", "40"])


class FakeClient:
    """A tmux client on a pty with a window size: what a browser tab or a phone is to the shared session."""

    def __init__(self, sock, env, target, rows, cols):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("tmux", ["tmux", "-L", sock, "attach", "-t", target], dict(env, TERM="xterm-256color"))
        self.resize(rows, cols, False)
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            try:
                if not os.read(self.fd, 65536):
                    return
            except OSError:
                return

    def resize(self, rows, cols, signal_it=True):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        if signal_it:
            os.kill(self.pid, signal.SIGWINCH)

    def send(self, data):
        os.write(self.fd, data if isinstance(data, bytes) else data.encode())

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (OSError, ChildProcessError):
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


@unittest.skipUnless(shutil.which("tmux"), "tmux not installed")
class RealTmux(unittest.TestCase):
    counter = 0

    def setUp(self):
        RealTmux.counter += 1
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-dock.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock = "swarmbox-dock-%d-%d" % (os.getpid() % 100000, RealTmux.counter)
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.env = {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp, "TMUX_TMPDIR": self.tmp,
                    "TERM": "xterm", "PYTHONPATH": LIB, "TMPDIR": self.tmp}
        self.tmux = Tmux(argv=["tmux", "-L", self.sock, "-f", self.conf()], env=self.env)
        self.addCleanup(self.tmux.run, "kill-server")
        self.clients = []
        self.addCleanup(lambda: [c.close() for c in self.clients])
        r = self.tmux.run("new-session", "-d", "-s", "main", "-x", "100", "-y", "40", "-c", self.tmp, "cat -v")
        self.assertEqual(r.rc, 0, r.err)
        self.user = self.tmux.run("list-panes", "-t", "=main", "-F", "#{pane_id}").out.split()[0]
        self.d = dock.default_dock(self.tmux, "127.0.0.1:1")
        self.d.panel_argv = ["env", "SWARMBOX_VOICE_PANEL=1", "sleep", "600"]      # a stand-in: only the pane matters here

    def conf(self):
        path = os.path.join(self.tmp, "tmux.conf")
        with open(path, "w") as f:
            f.write("set -g status off\n")      # the window is then exactly the size of the client
        return path

    def attach(self, rows, cols):
        c = FakeClient(self.sock, self.env, "=main", rows, cols)
        self.clients.append(c)
        time.sleep(0.6)
        return c

    def panes(self):
        fmt = "#{pane_id} #{window_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} #{window_width} #{window_height} #{pane_active} #{@swarmbox_voice_panel}"
        out = []
        for line in self.tmux.run("list-panes", "-s", "-t", "=main", "-F", fmt).out.splitlines():
            p = line.split(" ")
            out.append({"id": p[0], "win": p[1], "left": int(p[2]), "top": int(p[3]), "w": int(p[4]), "h": int(p[5]), "ww": int(p[6]), "wh": int(p[7]),
                        "active": p[8] == "1", "panel": p[9] == "1"})
        return out

    def panels(self):
        return [p for p in self.panes() if p["panel"]]

    def wait(self, fn, what, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.05)
        self.fail("timed out waiting for " + what)

    def pid_of(self, pane):
        return self.tmux.run("display-message", "-p", "-t", pane, "#{pane_pid}").out.strip()

    def hooks(self):
        return self.tmux.run("show-hooks", "-g", "window-resized").out


class Placement(RealTmux):
    def test_a_portrait_window_gets_a_full_width_pane_of_40_percent_at_the_bottom(self):
        self.attach(70, 50)
        self.assertEqual(self.d.open(), "created")
        panel, = self.panels()
        self.assertEqual((panel["ww"], panel["wh"]), (50, 70))
        self.assertEqual((panel["left"], panel["w"]), (0, 50), "full width")
        self.assertEqual(panel["top"] + panel["h"], 70, "at the bottom edge")
        self.assertTrue(26 <= panel["h"] <= 29, "about 40 %% of the height: %d" % panel["h"])
        self.assertTrue(panel["active"], "the panel has the focus: the keys are for it")
        user = [p for p in self.panes() if not p["panel"]]
        self.assertEqual([p["id"] for p in user], [self.user], "the user's pane is the only other one")

    def test_a_landscape_window_gets_20_percent_at_the_right_edge(self):
        self.attach(50, 200)
        self.assertEqual(self.d.open(), "created")
        panel, = self.panels()
        self.assertEqual((panel["ww"], panel["wh"]), (200, 50))
        self.assertEqual(panel["h"], 50, "full height")
        self.assertEqual(panel["left"] + panel["w"], 200, "at the right edge")
        self.assertEqual(panel["w"], 40, "20 %% of 200")
        user, = [p for p in self.panes() if not p["panel"]]
        self.assertGreaterEqual(user["w"], 60)

    def test_a_narrow_landscape_window_falls_back_to_the_bottom(self):
        self.attach(30, 90)
        self.d.open()
        panel, = self.panels()
        self.assertEqual((panel["ww"], panel["wh"]), (90, 30))
        self.assertEqual((panel["left"], panel["w"]), (0, 90), "full width, at the bottom")
        self.assertEqual(panel["top"] + panel["h"], 30)

    def test_a_wide_but_short_of_the_minimum_window_uses_40_columns(self):
        self.attach(40, 150)
        self.d.open()
        panel, = self.panels()
        self.assertEqual(panel["w"], 40, "20 %% of 150 is 30: the 40-column minimum")
        self.assertEqual(panel["left"] + panel["w"], 150)

    def test_the_tmux_calls_are_the_split_the_design_names(self):
        calls = []
        real = self.tmux.run
        self.d.tmux = type("Spy", (), {"argv": self.tmux.argv, "run": lambda s, *a: (calls.append(list(a)), real(*a))[1]})()
        self.attach(70, 50)
        self.d.open()
        split = [c for c in calls if c[0] == "split-window"][0]
        self.assertEqual(split[split.index("-f"):split.index("-f") + 4], ["-f", "-v", "-l", "40%"])
        self.d.close()
        calls.clear()
        self.clients[0].resize(50, 200)
        time.sleep(0.8)
        self.d.open()
        split = [c for c in calls if c[0] == "split-window"][0]
        self.assertEqual(split[split.index("-f"):split.index("-f") + 4], ["-f", "-h", "-l", "20%"])

    def test_the_users_panes_are_untouched(self):
        self.attach(50, 200)
        self.tmux.run("send-keys", "-t", self.user, "-l", "typed by the user")
        time.sleep(0.2)
        before = self.tmux.run("capture-pane", "-p", "-t", self.user).out.strip()
        pid = self.pid_of(self.user)
        self.d.open()
        self.d.close()
        self.d.open()
        self.assertEqual(self.pid_of(self.user), pid)
        self.assertEqual(self.tmux.run("capture-pane", "-p", "-t", self.user).out.strip(), before)
        self.assertEqual(self.tmux.run("list-panes", "-t", "=main", "-F", "#{pane_id}").out.split().count(self.user), 1)

    def test_opening_again_never_makes_a_second_panel(self):
        self.attach(50, 200)
        self.assertEqual(self.d.open(), "created")
        self.assertEqual(self.d.open(), "shown")
        self.assertEqual(self.d.open(), "shown")
        self.assertEqual(len(self.panels()), 1)

    def test_parallel_opens_make_one_panel(self):
        self.attach(50, 200)
        threads = [threading.Thread(target=self.d.open) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(len(self.panels()), 1)

    def test_a_stray_second_panel_is_removed(self):
        self.attach(50, 200)
        self.d.open()
        extra = self.tmux.run("split-window", "-d", "-t", self.user, "-P", "-F", "#{pane_id}", "sleep 600").out.strip()
        self.tmux.run("set-option", "-p", "-t", extra, "@swarmbox_voice_panel", "1")
        self.assertEqual(len(self.panels()), 2)
        self.d.open()
        self.assertEqual(len(self.panels()), 1)

    def test_close_removes_the_panel_and_the_hook(self):
        self.attach(50, 200)
        self.d.open()
        self.assertIn("window-resized[417]", self.hooks())
        self.assertEqual(self.d.close(), 1)
        self.assertEqual(self.panels(), [])
        self.assertNotIn("window-resized[417]", self.hooks())
        self.assertEqual(self.d.close(), 0)

    def test_a_window_with_no_room_is_an_error_not_a_crash(self):
        self.tmux.run("new-session", "-d", "-s", "tiny", "-x", "10", "-y", "2", "cat")
        d = dock.default_dock(self.tmux, "127.0.0.1:1", session="tiny")
        d.panel_argv = ["env", "SWARMBOX_VOICE_PANEL=1", "sleep", "600"]
        with self.assertRaises(dock.DockError):
            d.open()

    def test_no_tmux_session_is_a_dock_error(self):
        d = dock.default_dock(self.tmux, "127.0.0.1:1", session="nosuch")
        with self.assertRaises(dock.DockError):
            d.open()


class PanelIsNotAUserPane(RealTmux):
    def test_context_and_executor_leave_the_panel_out_whichever_way_it_is_marked(self):
        self.attach(50, 200)
        self.d.open()
        panel, = self.panels()
        self.tmux.run("send-keys", "-t", panel["id"], "-l", "TEXT-IN-THE-PANEL")
        raw = context.snapshot(self.tmux, "main")
        self.assertEqual([p["id"] for p in raw], [self.user])
        self.assertNotIn(panel["id"], executor.session_panes(self.tmux, "main"))
        # only the option removed: the marker argument of the start command still identifies it
        self.tmux.run("set-option", "-p", "-t", panel["id"], "-u", "@swarmbox_voice_panel")
        self.assertEqual([p["id"] for p in context.snapshot(self.tmux, "main")], [self.user])
        self.assertNotIn(panel["id"], executor.session_panes(self.tmux, "main"))
        # and the other way: a pane that only has the option
        plain = self.tmux.run("split-window", "-d", "-t", self.user, "-P", "-F", "#{pane_id}", "cat").out.strip()
        self.assertIn(plain, executor.session_panes(self.tmux, "main"))
        self.tmux.run("set-option", "-p", "-t", plain, "@swarmbox_voice_panel", "1")
        self.assertNotIn(plain, executor.session_panes(self.tmux, "main"))
        data = context.build_input("hi", self.user, context.snapshot(self.tmux, "main"))
        self.assertNotIn("TEXT-IN-THE-PANEL", repr(data))

    def test_a_plan_never_goes_to_the_panel_even_when_it_has_the_focus(self):
        self.attach(50, 200)
        self.d.open()
        panel, = self.panels()
        self.assertTrue(panel["active"])
        raw = context.snapshot(self.tmux, "main")
        self.assertEqual([p["id"] for p in raw if p["active"]], [self.user])
        with self.assertRaises(executor.ExecutorError):
            executor.execute([{"type": "send_text", "pane": panel["id"], "text": "x", "enter": False}], True, tmux=self.tmux)


class SeveralWindows(RealTmux):
    def test_it_opens_in_the_window_the_session_shows_and_moves_when_that_changes(self):
        self.attach(70, 50)
        first = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.d.open()
        self.assertEqual(self.panels()[0]["win"], first)
        self.tmux.run("new-window", "-t", "=main:", "cat")
        second = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.assertNotEqual(first, second)
        pid = self.pid_of(self.panels()[0]["id"])
        self.assertEqual(self.d.open(), "moved", "opening again brings the panel to the window you look at")
        panel, = self.panels()
        self.assertEqual(panel["win"], second)
        self.assertEqual(self.pid_of(panel["id"]), pid, "the same program: it was moved, not restarted")
        self.assertEqual(len([p for p in self.panes() if p["win"] == first]), 1, "the first window is as it was")

    def test_toggle_opens_closes_and_brings_the_panel_to_this_window(self):
        self.attach(70, 50)
        first = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.assertEqual(self.d.toggle(first), "created")
        self.assertEqual(self.d.toggle(first), "closed")
        self.assertEqual(self.panels(), [])
        self.d.toggle(first)
        self.tmux.run("new-window", "-t", "=main:", "cat")
        second = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.assertEqual(self.d.toggle(second), "moved", "it was in another window: toggling shows it here, it does not close it")
        self.assertEqual(self.panels()[0]["win"], second)
        self.assertEqual(self.d.toggle(second), "closed")
        self.assertEqual(self.panels(), [])

    def test_the_window_can_be_named_explicitly(self):
        self.attach(70, 50)
        first = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.tmux.run("new-window", "-d", "-t", "=main:", "cat")
        others = [w for w in self.tmux.run("list-windows", "-t", "=main", "-F", "#{window_id}").out.split() if w != first]
        self.d.open(window=others[0])
        self.assertEqual(self.panels()[0]["win"], others[0])


class HookRedock(RealTmux):
    def test_resizing_the_window_moves_the_same_pane_to_the_other_layout(self):
        c = self.attach(70, 50)
        self.d.open()
        panel, = self.panels()
        pid = self.pid_of(panel["id"])
        self.assertEqual((panel["left"], panel["w"]), (0, 50), "portrait: at the bottom")
        c.resize(50, 200)       # the phone is rotated, the browser is made wide
        moved = self.wait(lambda: [p for p in self.panels() if p["ww"] == 200 and p["h"] == p["wh"]], "the panel to move to the right edge")
        self.assertEqual(moved[0]["id"], panel["id"], "the same pane")
        self.assertEqual(self.pid_of(moved[0]["id"]), pid, "the program in it was not restarted")
        self.assertEqual(moved[0]["left"] + moved[0]["w"], 200)
        self.assertEqual(moved[0]["w"], 40)
        c.resize(70, 50)
        back = self.wait(lambda: [p for p in self.panels() if p["ww"] == 50 and p["w"] == 50], "the panel to come back to the bottom")
        self.assertEqual(back[0]["id"], panel["id"])
        self.assertEqual(self.pid_of(back[0]["id"]), pid)
        self.assertEqual(len(self.panels()), 1)

    def test_a_resize_that_keeps_the_layout_changes_nothing(self):
        c = self.attach(70, 50)
        self.d.open()
        panel, = self.panels()
        c.resize(80, 60)
        time.sleep(1.0)
        now, = self.panels()
        self.assertEqual(now["id"], panel["id"])
        self.assertEqual(now["w"], 60, "still full width at the bottom")

    def test_the_hook_does_not_take_the_focus_from_the_pane_the_user_is_in(self):
        c = self.attach(70, 50)
        self.d.open()
        self.tmux.run("select-pane", "-t", self.user)
        c.resize(50, 200)
        self.wait(lambda: [p for p in self.panels() if p["ww"] == 200 and p["h"] == p["wh"]], "the move")
        time.sleep(0.5)
        active = [p["id"] for p in self.panes() if p["active"]]
        self.assertEqual(active, [self.user], "the user keeps the focus through a redock")

    def test_the_hook_removes_itself_when_the_panel_is_gone(self):
        c = self.attach(70, 50)
        self.d.open()
        self.assertIn("window-resized[417]", self.hooks())
        self.tmux.run("kill-pane", "-t", self.panels()[0]["id"])      # the panel exited by itself, as it does when the plan ends
        c.resize(50, 200)
        self.wait(lambda: "window-resized[417]" not in self.hooks(), "the hook to remove itself")

    def test_only_one_panel_survives_a_redock_race(self):
        c = self.attach(70, 50)
        self.d.open()
        for rows, cols in ((50, 200), (70, 50), (50, 200), (70, 50)):
            c.resize(rows, cols)
            time.sleep(0.4)
        time.sleep(1.0)
        self.assertEqual(len(self.panels()), 1)
        self.assertEqual(len([p for p in self.panes() if not p["panel"]]), 1)

    def test_the_hook_fires_on_the_real_tmux_resize_events(self):
        """Which hook: window-resized fires when a client changes the size of the window (checked here with this tmux)."""
        c = self.attach(40, 100)
        log = os.path.join(self.tmp, "hook.log")
        self.tmux.run("set-hook", "-g", "window-resized[5]", 'run-shell "echo resized #{window_width}x#{window_height} >> %s"' % log)
        c.resize(50, 120)
        self.wait(lambda: "resized 120x50" in slurp(log), "window-resized")


class Cli(RealTmux):
    """`swarmbox-voice dock ...` as the key and the hook run it, with the real panel program in the pane."""

    def cli(self, *args):
        sock = self.tmux.run("display-message", "-p", "#{socket_path}").out.strip()
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "dock", *args, "--socket", sock, "--service", "127.0.0.1:1"],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def test_toggle_creates_the_real_panel_and_toggles_it_closed(self):
        self.attach(70, 50)
        window = self.tmux.run("display-message", "-p", "#{window_id}").out.strip()
        r = self.cli("toggle", "--window", window)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("panel created", r.stderr)
        panel, = self.wait(self.panels, "the panel")
        # the real program is in the pane and says the service is down (port 1)
        self.wait(lambda: "not answering" in self.tmux.run("capture-pane", "-p", "-t", panel["id"]).out, "the panel's message")
        self.assertIn("swarmbox_voice", self.tmux.run("display-message", "-p", "-t", panel["id"], "#{pane_start_command}").out)
        r = self.cli("toggle", "--window", window)
        self.assertIn("panel closed", r.stderr)
        self.wait(lambda: not self.panels(), "the panel to go")

    def test_a_panel_that_exits_by_itself_closes_its_pane(self):
        self.attach(70, 50)
        self.d.panel_argv = ["env", "SWARMBOX_VOICE_PANEL=1", "sh", "-c", "sleep 0.5"]
        self.d.open()
        self.assertEqual(len(self.panels()), 1)
        self.wait(lambda: not self.panels(), "the pane to close when the program ends")
        self.assertEqual(len(self.panes()), 1)

    def test_even_with_remain_on_exit_the_panel_pane_goes(self):
        self.tmux.run("set-option", "-g", "remain-on-exit", "on")
        self.attach(70, 50)
        self.d.panel_argv = ["env", "SWARMBOX_VOICE_PANEL=1", "sh", "-c", "sleep 0.5"]
        self.d.open()
        self.wait(lambda: not self.panels(), "the pane to close although remain-on-exit is on")

    def test_the_window_must_be_a_window_id(self):
        for bad in ("1", "%1", "@x", "-t", "@1;kill-server", ""):
            r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "dock", "toggle", "--window", bad], env=self.env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2, bad)

    def test_plan_with_the_service_down_says_so(self):
        r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "plan", "--service", "127.0.0.1:1", "hello"], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not answering", r.stderr)


class KeyBinding(RealTmux):
    def conf(self):
        return TMUX_CONF

    def test_the_default_config_binds_prefix_v_to_the_toggle_with_the_socket_and_the_window(self):
        out = "\n".join(l for l in self.tmux.run("list-keys", "-T", "prefix").out.splitlines() if l.split()[3:4] == ["v"])
        self.assertIn("run-shell", out)
        self.assertIn("swarmbox-voice dock toggle", out)
        self.assertIn("--socket", out)
        self.assertIn("socket_path", out)
        self.assertIn("window_id", out)

    def test_pressing_the_key_calls_the_toggle_for_this_window_on_this_server(self):
        log = os.path.join(self.tmp, "args.log")
        exe = os.path.join(self.bin, "swarmbox-voice")
        with open(exe, "w") as f:
            f.write('#!/bin/sh\nprintf "%%s\\n" "$*" >> %s\n' % log)
        os.chmod(exe, 0o755)
        c = self.attach(40, 100)
        window = self.tmux.run("display-message", "-p", "#{window_id}").out.strip()
        c.send("\x01v")           # the prefix of the box is Ctrl+A
        self.wait(lambda: slurp(log).strip(), "the command to run")
        line = slurp(log).strip()
        self.assertTrue(line.startswith("dock toggle --socket "), line)
        self.assertTrue(line.endswith("--window " + window), line)
        sock = line.split("--socket ")[1].split(" ")[0]
        self.assertTrue(sock.endswith(self.sock), "the socket of THIS server: " + sock)

    def test_the_key_does_not_collide_with_any_other_binding(self):
        keys = self.tmux.run("list-keys", "-T", "prefix").out
        self.assertEqual(len([l for l in keys.splitlines() if l.split()[3:4] == ["v"]]), 1)
        browser = self.tmux.run("list-keys", "-T", "root").out
        self.assertNotIn(" M-v ", browser, "no Alt+V either: the shell keeps it")


if __name__ == "__main__":
    unittest.main()
