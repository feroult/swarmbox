"""Docking of the panel of the sysop (container/addons/sysop/lib/swarmbox_sysop/dock.py).

  * (the layout rule, the marks, the hook slot and the key of tmux.conf need no tmux: tests/fast/test_sysop_dock_logic.py)
  * the real thing against a REAL tmux on a private socket with real clients attached through a pty: where the pane goes for a portrait, a landscape
    and a narrow landscape window, ONE PANEL PER WINDOW (never two in one window, the other windows never touched), the user's panes untouched, the
    panel is a marked pane that swarmbox-tabs hides, the key binding of container/config/tmux.conf, the hook that fits only
    the window that was resized and never takes the focus, and its removal when no panel is left in any window, the Follower (opens for a goal,
    closes the panel it opened when the goal ends) and `swarmbox-sysop dock ...` as the key and the hook run it, with the real panel in the pane.

Run the tmux part in Podman only (a developer's machine may have a tmux of its own that these tests must never touch): they skip unless tmux is
installed AND SWARMBOX_TEST_REAL_TMUX=1 is set, which only this command does:

  podman run --rm -e SWARMBOX_TEST_REAL_TMUX=1 --userns=keep-id:uid=1000,gid=1000 -v $PWD:/src:ro --tmpfs /work:rw,exec,mode=1777,size=1g IMAGE \\
      bash -c 'cp -r /src /work/repo && cd /work/repo && HOME=/work/home python3 -W error tests/slow/test_sysop_dock.py'
"""
import fcntl
import importlib.util
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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_sysop import dock, ipc, paths  # noqa: E402
from swarmbox_sysop.dock import Follower, Layout, Tmux  # noqa: E402

TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
BOTTOM = Layout("bottom", "30%")
HAVE = bool(shutil.which("tmux")) and os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"


def slurp(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""






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


STAND_IN = ["env", "SWARMBOX_SYSOP_PANEL=1", "sleep", "600"]      # a stand-in for the panel program: only the pane matters in most tests


@unittest.skipUnless(HAVE, "needs tmux and a container (run it in Podman, see the docstring)")
class RealTmux(unittest.TestCase):
    counter = 0
    MODE = "auto"       # SWARMBOX_SYSOP_PANEL_MODE of these tests: the transient panel (the default of the box is always: tests/slow/test_sysop_always.py)
    OWN_PATH = False    # True: the PATH is the test's bin and the system's, so a program that is installed on this machine is not found

    def setUp(self):
        RealTmux.counter += 1
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-sysop-dock.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sock = "sbsysopdock-%d-%d" % (os.getpid() % 100000, RealTmux.counter)
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.run_dir, self.state_dir = os.path.join(self.tmp, "run"), os.path.join(self.tmp, "state")
        self.env = {"PATH": self.bin + os.pathsep + ("/usr/bin:/bin" if self.OWN_PATH else os.environ.get("PATH", "/usr/bin:/bin")), "HOME": self.tmp, "TMUX_TMPDIR": self.tmp, "TERM": "xterm",
                    "PYTHONPATH": ss.LIB, "TMPDIR": self.tmp, "SB_RUN_DIR": self.run_dir, "SB_STATE_DIR": self.state_dir, "LANG": "C.UTF-8",
                    "SWARMBOX_SYSOP_PANEL_MODE": self.MODE}
        self.saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.saved)))
        os.environ.update(self.env)
        os.environ.pop("TMUX", None)
        os.environ.pop("SB_TABS_SOCKET", None)
        self.tmux = Tmux(argv=["tmux", "-L", self.sock, "-f", self.conf()], env=self.env)
        self.addCleanup(self.tmux.run, "kill-server")
        self.clients = []
        self.addCleanup(lambda: [c.close() for c in self.clients])
        r = self.tmux.run("new-session", "-d", "-s", "main", "-x", "100", "-y", "40", "-c", self.tmp, "cat -v")
        self.assertEqual(r.rc, 0, r.err)
        self.user = self.tmux.run("list-panes", "-t", "=main", "-F", "#{pane_id}").out.split()[0]
        self.win1 = self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip()
        self.d = dock.default_dock(self.tmux)
        self.d.panel_argv = list(STAND_IN)

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
        fmt = "#{pane_id} #{window_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} #{window_width} #{window_height} #{pane_active} #{@swarmbox_sysop_panel}"
        out = []
        for line in self.tmux.run("list-panes", "-s", "-t", "=main", "-F", fmt).out.splitlines():
            p = line.split(" ")
            out.append({"id": p[0], "win": p[1], "left": int(p[2]), "top": int(p[3]), "w": int(p[4]), "h": int(p[5]), "ww": int(p[6]), "wh": int(p[7]),
                        "active": p[8] == "1", "panel": p[9] == "1"})
        return out

    def panels(self):
        return [p for p in self.panes() if p["panel"]]

    def panels_of(self, win):
        return [p for p in self.panels() if p["win"] == win]

    def new_window(self, detached=True):
        out = self.tmux.run("new-window", *(["-d"] if detached else []), "-t", "=main:", "-P", "-F", "#{window_id} #{pane_id}", "cat -v").out.split()
        return out[0], out[1]

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

    def active_pane(self, win):
        return [p["id"] for p in self.panes() if p["win"] == win and p["active"]]


class Placement(RealTmux):
    def test_a_portrait_window_gets_a_full_width_pane_of_30_percent_at_the_bottom(self):
        self.attach(70, 50)
        self.assertEqual(self.d.open(), "created")
        panel, = self.panels()
        self.assertEqual((panel["ww"], panel["wh"]), (50, 70))
        self.assertEqual((panel["left"], panel["w"]), (0, 50), "full width")
        self.assertEqual(panel["top"] + panel["h"], 70, "at the bottom edge")
        self.assertTrue(20 <= panel["h"] <= 22, "about 30 %% of the height: %d" % panel["h"])
        self.assertTrue(panel["active"], "the panel has the focus: the keys are for it")
        self.assertEqual([p["id"] for p in self.panes() if not p["panel"]], [self.user], "the user's pane is the only other one")

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

    def test_a_wide_window_short_of_the_minimum_uses_40_columns(self):
        self.attach(40, 150)
        self.d.open()
        panel, = self.panels()
        self.assertEqual(panel["w"], 40, "20 %% of 150 is 30: the 40-column minimum")
        self.assertEqual(panel["left"] + panel["w"], 150)

    def test_the_panel_is_marked_by_the_option_and_the_command(self):
        self.attach(50, 200)
        self.d.open()
        panel, = self.panels()
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", panel["id"], "#{@swarmbox_sysop_panel}").out.strip(), "1")
        self.assertIn("SWARMBOX_SYSOP_PANEL=1", self.tmux.run("display-message", "-p", "-t", panel["id"], "#{pane_start_command}").out)
        # only the option removed: the argument of the start command still identifies it
        self.tmux.run("set-option", "-p", "-t", panel["id"], "-u", "@swarmbox_sysop_panel")
        self.assertEqual(len(self.d.panels()), 1)
        self.assertEqual(self.d.open(), "shown", "found by the marker argument: no second panel")
        self.assertEqual(len(self.d.panels()), 1)

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

    def test_opening_again_never_makes_a_second_panel_in_the_window(self):
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

    def test_a_stray_second_panel_in_the_window_is_removed(self):
        self.attach(50, 200)
        self.d.open()
        extra = self.tmux.run("split-window", "-d", "-t", self.user, "-P", "-F", "#{pane_id}", "sleep 600").out.strip()
        self.tmux.run("set-option", "-p", "-t", extra, "@swarmbox_sysop_panel", "1")
        self.assertEqual(len(self.panels()), 2)
        self.d.open()
        self.assertEqual(len(self.panels()), 1)

    def test_close_removes_the_panel_and_the_hook(self):
        self.attach(50, 200)
        self.d.open()
        self.assertIn("window-resized[418]", self.hooks())
        self.assertEqual(self.d.close(), 1)
        self.assertEqual(self.panels(), [])
        self.assertNotIn("window-resized[418]", self.hooks())
        self.assertEqual(self.d.close(), 0)

    def test_a_window_with_no_room_is_an_error_not_a_crash(self):
        self.tmux.run("new-session", "-d", "-s", "tiny", "-x", "10", "-y", "2", "cat")
        d = dock.default_dock(self.tmux, session="tiny")
        d.panel_argv = list(STAND_IN)
        with self.assertRaises(dock.DockError):
            d.open()

    def test_no_tmux_session_is_a_dock_error(self):
        with self.assertRaises(dock.DockError):
            dock.default_dock(self.tmux, session="nosuch").open()


class PerWindow(RealTmux):
    def test_each_window_has_its_own_panel_and_never_two(self):
        self.attach(70, 50)
        win2, _ = self.new_window()
        self.assertEqual(self.d.open(window=self.win1), "created")
        self.assertEqual(self.d.open(window=win2, focus=False), "created", "a panel in another window does not stop this one from having its own")
        self.assertEqual([len(self.panels_of(w)) for w in (self.win1, win2)], [1, 1])
        ids = {p["win"]: p["id"] for p in self.panels()}
        pids = {w: self.pid_of(i) for w, i in ids.items()}
        for _ in range(3):
            self.assertEqual(self.d.open(window=self.win1), "shown")
            self.assertEqual(self.d.open(window=win2), "shown")
        self.assertEqual([len(self.panels_of(w)) for w in (self.win1, win2)], [1, 1])
        self.assertEqual({p["win"]: p["id"] for p in self.panels()}, ids, "the same panes: nothing was moved between windows")
        self.assertEqual({w: self.pid_of(i) for w, i in ids.items()}, pids, "the same programs")

    def test_opening_without_a_window_uses_the_window_the_session_shows_and_leaves_the_others_alone(self):
        self.attach(70, 50)
        self.d.open()
        self.assertEqual([p["win"] for p in self.panels()], [self.win1])
        win2, _ = self.new_window(detached=False)             # now the session shows the second window
        pid = self.pid_of(self.panels()[0]["id"])
        self.assertEqual(self.d.open(), "created")
        self.assertEqual(sorted(p["win"] for p in self.panels()), sorted([self.win1, win2]))
        self.assertEqual(self.pid_of(self.panels_of(self.win1)[0]["id"]), pid, "the panel of the first window did not move")

    def test_toggle_acts_on_the_window_it_is_given_only(self):
        self.attach(70, 50)
        win2, _ = self.new_window()
        self.assertEqual(self.d.toggle(self.win1), "created")
        self.assertEqual(self.d.toggle(win2), "created")
        self.assertEqual(self.d.toggle(win2), "closed")
        self.assertEqual([p["win"] for p in self.panels()], [self.win1], "the panel of the first window stays")
        self.assertIn("window-resized[418]", self.hooks(), "a panel is left: the hook stays")
        self.assertEqual(self.d.toggle(self.win1), "closed")
        self.assertEqual(self.panels(), [])
        self.assertNotIn("window-resized[418]", self.hooks())

    def test_close_without_a_window_closes_all_and_with_one_closes_that_one(self):
        self.attach(70, 50)
        win2, _ = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        self.assertEqual(self.d.close(window=win2), 1)
        self.assertEqual([p["win"] for p in self.panels()], [self.win1])
        self.d.open(window=win2, focus=False)
        self.assertEqual(self.d.close(), 2)
        self.assertEqual(self.panels(), [])

    def test_a_stray_second_panel_is_removed_only_from_its_own_window(self):
        self.attach(70, 50)
        win2, p2 = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        extra = self.tmux.run("split-window", "-d", "-t", p2, "-P", "-F", "#{pane_id}", "sleep 600").out.strip()
        self.tmux.run("set-option", "-p", "-t", extra, "@swarmbox_sysop_panel", "1")
        self.assertEqual(len(self.panels_of(win2)), 2)
        self.d.open(window=win2)
        self.assertEqual([len(self.panels_of(w)) for w in (self.win1, win2)], [1, 1])

    def test_the_users_panes_in_every_window_are_untouched(self):
        self.attach(70, 50)
        win2, p2 = self.new_window()
        self.tmux.run("send-keys", "-t", p2, "-l", "typed in the second tab")
        time.sleep(0.2)
        before = self.tmux.run("capture-pane", "-p", "-t", p2).out.strip()
        for w in (self.win1, win2):
            self.d.open(window=w, focus=False)
        self.d.close(window=win2)
        self.assertEqual(self.tmux.run("capture-pane", "-p", "-t", p2).out.strip(), before)
        self.assertEqual([p["id"] for p in self.panes() if not p["panel"]], [self.user, p2])

    def test_swarmbox_tabs_never_lists_the_panel_as_a_tab(self):
        spec = importlib.util.spec_from_file_location("swarmbox_tabs_x", os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        drv = mod.Tabs(session="main", socket=self.sock)
        self.attach(70, 50)
        win2, p2 = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        tabs = drv.list_tabs()
        self.assertEqual(sorted(t["tab"] for t in tabs), sorted([self.win1, win2]))
        self.assertEqual(sorted(t["pane"] for t in tabs), sorted([self.user, p2]), "the tab's pane is the user's, never the panel")
        self.assertEqual([len(t["panes"]) for t in tabs], [1, 1])
        self.tmux.run("send-keys", "-t", self.panels_of(win2)[0]["id"], "-l", "TEXT-IN-THE-PANEL")
        self.assertNotIn("TEXT-IN-THE-PANEL", drv.screen(win2, None)["text"])


class HookRedock(RealTmux):
    def test_the_hook_passes_the_window_that_changed(self):
        self.attach(70, 50)
        self.d.open()
        out = self.hooks()
        self.assertIn("window-resized[418]", out)
        self.assertIn("#{hook_window}", out)
        self.assertIn("--window", out)
        opt = self.tmux.run("show-options", "-gv", "@swarmbox_sysop_redock").out.strip()
        self.assertIn("swarmbox_sysop", opt)
        self.assertIn("redock", opt)
        self.assertIn("--socket", opt)

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
        self.assertEqual((moved[0]["left"] + moved[0]["w"], moved[0]["w"]), (200, 40))
        c.resize(70, 50)
        back = self.wait(lambda: [p for p in self.panels() if p["ww"] == 50 and p["w"] == 50], "the panel to come back to the bottom")
        self.assertEqual(back[0]["id"], panel["id"])
        self.assertEqual(self.pid_of(back[0]["id"]), pid)
        self.assertEqual(len(self.panels()), 1)

    def test_the_hook_fits_the_window_that_was_resized_and_the_other_when_it_is_shown(self):
        c = self.attach(70, 50)
        win2, _ = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        ids = {p["win"]: p["id"] for p in self.panels()}
        c.resize(50, 200)
        self.wait(lambda: [p for p in self.panels_of(self.win1) if p["ww"] == 200 and p["h"] == p["wh"]], "the panel of the shown window to move to the right edge")
        time.sleep(0.5)
        other, = self.panels_of(win2)
        self.assertEqual((other["ww"], other["w"]), (50, 50), "tmux has not resized the window nobody looks at: its panel stays where it is")
        self.tmux.run("select-window", "-t", win2)                     # now it is shown: it is resized, and the hook runs for it
        self.wait(lambda: [p for p in self.panels_of(win2) if p["ww"] == 200 and p["h"] == p["wh"]], "the panel of the second window to move when it is shown")
        self.assertEqual({p["win"]: p["id"] for p in self.panels()}, ids)

    def test_a_redock_for_one_window_fits_only_that_window(self):
        c = self.attach(70, 50)
        win2, _ = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        self.tmux.run("set-hook", "-gu", "window-resized[418]")          # no hook: the calls below are the only ones
        c.resize(50, 200)
        self.wait(lambda: all(p["ww"] == 200 for p in self.panes() if p["win"] == self.win1), "the first window to be resized")
        self.tmux.run("select-window", "-t", win2)
        self.wait(lambda: all(p["ww"] == 200 for p in self.panes()), "both windows to be resized")
        self.tmux.run("select-window", "-t", self.win1)
        self.assertTrue(all(p["w"] == p["ww"] for p in self.panels()), "both still at the bottom: nothing fitted yet")
        self.assertEqual(self.d.redock(window=self.win1), "moved")
        shapes = {p["win"]: p["h"] == p["wh"] for p in self.panels()}
        self.assertEqual(shapes, {self.win1: True, win2: False}, "only the window that was named moved its panel")
        self.assertEqual(self.d.redock(window=self.win1), "unchanged")
        self.assertEqual(self.d.redock(window=win2), "moved")
        self.assertTrue(all(p["h"] == p["wh"] for p in self.panels()))
        self.assertEqual(self.d.redock(window="@999"), "unchanged", "a window that is gone")
        self.assertEqual(self.d.redock(), "unchanged")

    def test_a_resize_that_keeps_the_layout_changes_nothing(self):
        c = self.attach(70, 50)
        self.d.open()
        panel, = self.panels()
        c.resize(80, 60)
        time.sleep(1.0)
        now, = self.panels()
        self.assertEqual((now["id"], now["w"]), (panel["id"], 60), "still full width at the bottom")

    def test_a_redock_never_takes_the_focus_from_the_pane_the_user_is_in(self):
        c = self.attach(70, 50)
        self.d.open()
        self.tmux.run("select-pane", "-t", self.user)
        c.resize(50, 200)
        self.wait(lambda: [p for p in self.panels() if p["ww"] == 200 and p["h"] == p["wh"]], "the move")
        time.sleep(0.5)
        self.assertEqual(self.active_pane(self.win1), [self.user], "the user keeps the focus through a redock")

    def test_a_redock_keeps_the_focus_in_the_panel_when_it_had_it(self):
        c = self.attach(70, 50)
        self.d.open()
        panel, = self.panels()
        self.assertEqual(self.active_pane(self.win1), [panel["id"]])
        c.resize(50, 200)
        self.wait(lambda: [p for p in self.panels() if p["ww"] == 200 and p["h"] == p["wh"]], "the move")
        time.sleep(0.5)
        self.assertEqual(self.active_pane(self.win1), [panel["id"]])

    def test_a_redock_of_one_window_changes_nothing_about_what_is_shown_or_the_other_windows(self):
        c = self.attach(70, 50)
        win2, p2 = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        before = self.panels_of(win2)[0]
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip(), self.win1)
        c.resize(50, 200)
        self.wait(lambda: [p for p in self.panels_of(self.win1) if p["h"] == p["wh"]], "the move")
        time.sleep(0.4)
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip(), self.win1, "the client still shows the first window")
        self.assertEqual(self.panels_of(win2)[0], before, "the other window's panel is exactly as it was")
        self.assertEqual(self.active_pane(win2), [p2], "in the other window the user's pane has the focus, as it had")
        # a redock aimed at the window nobody looks at moves its pane without switching windows or taking its focus
        self.tmux.run("set-hook", "-gu", "window-resized[418]")
        self.tmux.run("resize-window", "-t", win2, "-x", "200", "-y", "50")
        time.sleep(0.3)
        self.assertEqual(self.d.redock(window=win2), "moved")
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", "=main:", "#{window_id}").out.strip(), self.win1)
        self.assertEqual(self.active_pane(win2), [p2])

    def test_the_hook_stays_while_any_window_has_a_panel_and_goes_with_the_last(self):
        c = self.attach(70, 50)
        win2, _ = self.new_window()
        self.d.open(window=self.win1)
        self.d.open(window=win2, focus=False)
        self.tmux.run("kill-pane", "-t", self.panels_of(self.win1)[0]["id"])       # the panel of one window exits by itself
        c.resize(50, 200)
        time.sleep(1.0)                                         # the hook ran for the first window, which has no panel any more
        self.assertIn("window-resized[418]", self.hooks(), "a panel is left in the other window: the hook stays")
        self.tmux.run("kill-pane", "-t", self.panels_of(win2)[0]["id"])
        c.resize(70, 50)
        self.wait(lambda: "window-resized[418]" not in self.hooks(), "the hook to remove itself")
        self.assertEqual(self.tmux.run("show-options", "-gv", "@swarmbox_sysop_redock").out.strip(), "")

    def test_only_one_panel_survives_a_redock_race(self):
        c = self.attach(70, 50)
        self.d.open()
        for rows, cols in ((50, 200), (70, 50), (50, 200), (70, 50)):
            c.resize(rows, cols)
            time.sleep(0.4)
        time.sleep(1.0)
        self.assertEqual(len(self.panels()), 1)
        self.assertEqual(len([p for p in self.panes() if not p["panel"]]), 1)

    def test_the_voice_hook_and_the_sysop_hook_live_side_by_side(self):
        self.tmux.run("set-hook", "-g", "window-resized[417]", "run-shell true")
        self.attach(70, 50)
        self.d.open()
        out = self.hooks()
        self.assertIn("window-resized[417]", out)
        self.assertIn("window-resized[418]", out)
        self.d.close()
        out = self.hooks()
        self.assertIn("window-resized[417]", out, "the sysop does not remove the hook of voice")
        self.assertNotIn("window-resized[418]", out)


class TabName(RealTmux):
    """Found by tests/e2e/e2e_sysop.py: tmux names a window after the command of its ACTIVE pane and the panel takes the focus, so the Claude Code tab was
    called "python3" while the panel was open (status line, list_tabs label, the panel header). The dock freezes the name while a panel is in the window."""

    def name(self, win):
        return self.tmux.run("display-message", "-p", "-t", win, "#{window_name}").out.strip()

    def cat_window(self):
        """a window whose pane runs `cat` itself (not through `sh -c`, which tmux would call "sh")"""
        r = self.tmux.run("new-window", "-d", "-t", "=main:", "-P", "-F", "#{window_id}", "exec cat -v")
        self.assertEqual(r.rc, 0, r.err)
        return r.out.strip()

    def local_option(self, win, opt="automatic-rename"):
        return self.tmux.run("show-options", "-wqv", "-t", win, opt).out.strip()

    def poke(self, win):
        """tmux looks at the name of a window when its pane prints something: a silent `cat` is never looked at, so make it echo a key"""
        pane = self.tmux.run("list-panes", "-t", win, "-F", "#{pane_id} #{@swarmbox_sysop_panel}").out.split("\n")[0].split()[0]
        self.tmux.run("send-keys", "-t", pane, "a")

    def settle(self, win, want, seconds=5.0):
        """wait until the window has the name `want` (the pane of the window echoes now and then, see poke)"""
        end = time.time() + seconds
        while time.time() < end and self.name(win) != want:
            self.poke(win)
            time.sleep(0.25)
        return self.name(win)

    def test_opening_the_panel_does_not_rename_the_tab_and_closing_gives_the_automatic_name_back(self):
        self.attach(50, 200)
        win = self.cat_window()
        self.assertEqual(self.settle(win, "cat"), "cat")
        self.d.open(window=win)
        self.assertEqual(self.local_option(win), "off")
        for _ in range(8):
            self.poke(win)
            time.sleep(0.3)
        self.assertEqual(self.name(win), "cat", "the panel (sleep) has the focus and must not name the tab")
        self.d.close()
        self.assertEqual(self.local_option(win), "", "automatic-rename is inherited again, as before")
        self.assertEqual(self.local_option(win, dock.AR_OPTION), "")
        self.assertEqual(self.settle(win, "cat"), "cat")

    def test_a_tab_the_user_renamed_stays_renamed(self):
        self.attach(50, 200)
        self.tmux.run("rename-window", "-t", self.win1, "mine")
        self.assertEqual(self.local_option(self.win1), "off")
        self.d.open()
        self.d.close()
        self.assertEqual(self.name(self.win1), "mine")
        self.assertEqual(self.local_option(self.win1), "off", "it had automatic-rename off by its own: that is what comes back")

    def test_opening_twice_remembers_the_first_value(self):
        self.attach(50, 200)
        self.d.open()
        self.d.open()
        self.d.close()
        self.assertEqual(self.local_option(self.win1), "")

    def test_the_other_windows_are_never_touched(self):
        self.attach(50, 200)
        other, _ = self.new_window()
        self.d.open(window=self.win1)
        self.assertEqual(self.local_option(other), "")
        self.assertEqual(self.local_option(other, dock.AR_OPTION), "")

    def test_the_quit_key_of_the_panel_gives_the_name_back(self):
        self.attach(50, 200)
        self.d.open()
        panel = self.panels_of(self.win1)[0]["id"]
        env = dict(self.env, TMUX_PANE=panel, TMUX="%s,1,0" % self.tmux.run("display-message", "-p", "#{socket_path}").out.strip())
        subprocess.run([sys.executable, "-B", "-c", "from swarmbox_sysop import dock; dock.thaw_own_window()"], env=env, check=True)
        self.assertEqual(self.local_option(self.win1), "")

    def test_a_panel_killed_by_hand_is_healed_at_the_next_close(self):
        self.attach(50, 200)
        self.d.open()
        self.tmux.run("kill-pane", "-t", self.panels_of(self.win1)[0]["id"])
        self.assertEqual(self.local_option(self.win1), "off", "nobody thawed it yet")
        self.d.close()
        self.assertEqual(self.local_option(self.win1), "")

    def test_a_failed_open_leaves_the_name_alone(self):
        self.attach(50, 200)
        d = dock.default_dock(self.tmux)
        d.panel_argv = []
        with self.assertRaises(dock.DockError):
            d.open()
        self.assertEqual(self.local_option(self.win1), "")


class Following(RealTmux):
    """The Follower: the panel opens when status.json says a goal is there and closes (the one it opened) when the goal and the queue are over."""

    def setUp(self):
        super().setUp()
        self.pth = paths.Paths(self.env).make()
        self.now = 0.0
        self.log = []
        self.f = Follower(self.pth, dock=self.d, grace=3.0, clock=lambda: self.now, log=self.log.append)

    def status(self, current=None, queue=()):
        ipc.write_json(self.pth.status, {"pid": 1, "current": current, "queue": list(queue)})

    def step(self, advance=0.0):
        self.now += advance
        self.f.step()

    def test_a_goal_opens_the_panel_in_the_shown_window_and_the_end_closes_it(self):
        self.attach(70, 50)
        self.step()
        self.assertEqual(self.panels(), [], "idle: nothing")
        self.status(current="g1")
        self.step(1)
        panel, = self.panels()
        self.assertEqual(panel["win"], self.win1)
        self.assertEqual(self.tmux.run("display-message", "-p", "-t", panel["id"], "#{@swarmbox_sysop_auto}").out.strip(), "1")
        self.assertFalse(panel["active"], "it never takes the focus: what you type in your tab must not reach it")
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.step(1)
        self.assertEqual(len(self.panels()), 1, "no second panel while the goal runs")
        self.status(current=None)
        self.step(1)
        self.assertEqual(len(self.panels()), 1, "the end stays on screen for the grace time")
        self.step(3.5)
        self.assertEqual(self.panels(), [], "closed after the grace")
        self.assertNotIn("window-resized[418]", self.hooks())

    def test_a_queued_goal_keeps_it_open_and_a_new_goal_in_the_grace_cancels_the_close(self):
        self.attach(70, 50)
        self.status(current="g1", queue=[{"id": "g2"}])
        self.step()
        self.status(current=None, queue=[{"id": "g2"}])
        self.step(10)
        self.assertEqual(len(self.panels()), 1)
        self.status(current="g2")
        self.step(1)
        self.status()
        self.step(1)
        self.status(current="g3")
        self.step(2.5)
        self.step(5)
        self.assertEqual(len(self.panels()), 1, "a goal came before the grace ended")

    def test_a_panel_opened_by_hand_is_not_closed_when_the_goal_ends(self):
        self.attach(70, 50)
        self.d.open()                       # by hand: the key
        self.status(current="g1")
        self.step()
        self.assertEqual(len(self.panels()), 1)
        self.status()
        self.step(1)
        self.step(10)
        self.assertEqual(len(self.panels()), 1)

    def test_a_panel_the_user_closed_is_not_opened_again_for_the_same_goal_but_is_for_the_next(self):
        self.attach(70, 50)
        self.status(current="g1")
        self.step()
        self.tmux.run("kill-pane", "-t", self.panels()[0]["id"])            # q in the panel
        self.step(1)
        self.step(1)
        self.assertEqual(self.panels(), [])
        self.status()
        self.step(1)
        self.step(5)
        self.status(current="g2")
        self.step(1)
        self.assertEqual(len(self.panels()), 1)

    def test_an_existing_panel_does_not_get_the_focus_back(self):
        self.attach(70, 50)
        self.d.open()
        self.tmux.run("select-pane", "-t", self.user)
        self.status(current="g1")
        self.step()
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_no_session_is_logged_and_does_not_raise(self):
        self.f.dock = dock.default_dock(self.tmux, session="nosuch")
        self.status(current="g1")
        self.step()
        self.assertTrue(any("panel open" in x for x in self.log), self.log)

    def test_the_thread_follows_status_json(self):
        self.attach(70, 50)
        th = Follower(self.pth, dock=self.d, interval=0.05, grace=0.3).start()
        self.addCleanup(th.shutdown)
        self.status(current="g1")
        self.wait(self.panels, "the panel")
        self.status()
        self.wait(lambda: not self.panels(), "the panel to close", 5)


class Cli(RealTmux):
    """`swarmbox-sysop dock ...` as the key and the hook run it, with the real panel program in the pane."""

    def cli(self, *args):
        sock = self.tmux.run("display-message", "-p", "#{socket_path}").out.strip()
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "dock", *args, "--socket", sock], env=self.env, capture_output=True, text=True, timeout=30)

    def test_toggle_creates_the_real_panel_and_toggles_it_closed(self):
        self.attach(70, 50)
        r = self.cli("toggle", "--window", self.win1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("panel created", r.stderr)
        panel, = self.wait(self.panels, "the panel")
        # the real program is in the pane and says the service is down (nothing runs in this run folder)
        self.wait(lambda: "The sysop is not running" in self.tmux.run("capture-pane", "-p", "-t", panel["id"]).out, "the panel's message")
        self.assertIn("swarmbox_sysop", self.tmux.run("display-message", "-p", "-t", panel["id"], "#{pane_start_command}").out)
        r = self.cli("toggle", "--window", self.win1)
        self.assertIn("panel closed", r.stderr)
        self.wait(lambda: not self.panels(), "the panel to go")

    def test_the_real_panel_in_tmux_shows_the_state_of_the_service(self):
        self.attach(70, 50)
        pth = paths.Paths(self.env).make()
        fd = os.open(pth.lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ipc.write_json(pth.status, {"pid": os.getpid(), "bus": "connected", "current": None, "queue": [], "settings": {}})
        r = self.cli("open", "--window", self.win1)
        self.assertEqual(r.returncode, 0, r.stderr)
        panel, = self.wait(self.panels, "the panel")
        self.wait(lambda: "Say or type a goal." in self.tmux.run("capture-pane", "-p", "-t", panel["id"]).out, "the idle text")
        self.tmux.run("send-keys", "-t", panel["id"], "q")
        self.wait(lambda: not self.panels(), "the panel to close by itself with q")

    def test_a_panel_that_exits_by_itself_closes_its_pane(self):
        self.attach(70, 50)
        self.d.panel_argv = ["env", "SWARMBOX_SYSOP_PANEL=1", "sh", "-c", "sleep 0.5"]
        self.d.open()
        self.assertEqual(len(self.panels()), 1)
        self.wait(lambda: not self.panels(), "the pane to close when the program ends")
        self.assertEqual(len(self.panes()), 1)

    def test_even_with_remain_on_exit_the_panel_pane_goes(self):
        self.tmux.run("set-option", "-g", "remain-on-exit", "on")
        self.attach(70, 50)
        self.d.panel_argv = ["env", "SWARMBOX_SYSOP_PANEL=1", "sh", "-c", "sleep 0.5"]
        self.d.open()
        self.wait(lambda: not self.panels(), "the pane to close although remain-on-exit is on")


class KeyBinding(RealTmux):
    def conf(self):
        return TMUX_CONF

    def test_the_default_config_binds_prefix_S_to_the_toggle_with_the_socket_and_the_window(self):
        out = "\n".join(ln for ln in self.tmux.run("list-keys", "-T", "prefix").out.splitlines() if ln.split()[3:4] == ["S"])
        self.assertIn("run-shell", out)
        self.assertIn("swarmbox-sysop dock toggle", out)
        self.assertIn("--socket", out)
        self.assertIn("socket_path", out)
        self.assertIn("window_id", out)

    def test_the_key_is_free_in_tmuxs_own_table_and_the_voice_key_is_gone(self):
        defaults = subprocess.run(["tmux", "-L", self.sock + "d", "-f", "/dev/null", "start-server", ";", "list-keys", "-T", "prefix"], env=self.env,
                                  capture_output=True, text=True, timeout=30).stdout
        self.assertEqual([ln for ln in defaults.splitlines() if ln.split()[3:4] == ["S"]], [], "S is unbound in the table of tmux itself")
        keys = self.tmux.run("list-keys", "-T", "prefix").out
        self.assertEqual(len([ln for ln in keys.splitlines() if ln.split()[3:4] == ["S"]]), 1)
        self.assertEqual([ln for ln in keys.splitlines() if ln.split()[3:4] == ["v"]], [], "tmux's own table has no v either")
        self.assertNotIn(" M-S ", self.tmux.run("list-keys", "-T", "root").out)

    def test_the_sysop_keys_are_free_in_tmuxs_own_table_and_bound_by_the_box(self):
        defaults = subprocess.run(["tmux", "-L", self.sock + "d", "-f", "/dev/null", "start-server", ";", "list-keys", "-T", "prefix"], env=self.env,
                                  capture_output=True, text=True, timeout=30).stdout
        mine = self.tmux.run("list-keys", "-T", "prefix").out
        for k, cmd in (("V", "swarmbox-sysop veto"), ("X", "swarmbox-sysop stop"), ("a", "swarmbox-sysop approve"), ("g", "swarmbox-sysop goal")):
            self.assertEqual([ln for ln in defaults.splitlines() if ln.split()[3:4] == [k]], [], k + " is unbound in tmux itself")
            self.assertEqual(len([ln for ln in mine.splitlines() if ln.split()[3:4] == [k] and cmd in ln]), 1, k)

    def test_pressing_the_key_calls_the_toggle_for_this_window_on_this_server(self):
        log = os.path.join(self.tmp, "args.log")
        exe = os.path.join(self.bin, "swarmbox-sysop")
        with open(exe, "w") as f:
            f.write('#!/bin/sh\nprintf "%%s\\n" "$*" >> %s\n' % log)
        os.chmod(exe, 0o755)
        c = self.attach(40, 100)
        window = self.tmux.run("display-message", "-p", "#{window_id}").out.strip()
        c.send("\x01S")           # the prefix of the box is Ctrl+A
        self.wait(lambda: slurp(log).strip(), "the command to run")
        line = slurp(log).strip()
        self.assertTrue(line.startswith("dock toggle --socket "), line)
        self.assertTrue(line.endswith("--window " + window), line)
        self.assertTrue(line.split("--socket ")[1].split(" ")[0].endswith(self.sock), "the socket of THIS server: " + line)


LAUNCHER = '#!/bin/sh\nexec "%s" -B -m swarmbox_sysop "$@"\n' % sys.executable


class NoSysopAddon(RealTmux):
    """The sysop is an optional addon. Without it the keys of tmux.conf (Panel button of the phone strip = Ctrl+A S, and V X a g) say so in the status line and leave
    the pane alone: a failed command printed into the pane puts it in view-mode, where nothing typed reaches the shell."""
    OWN_PATH = True

    def conf(self):
        return TMUX_CONF

    def test_every_sysop_key_without_the_addon_leaves_the_pane_typing(self):
        self.assertIsNone(shutil.which("swarmbox-sysop", path=self.env["PATH"]))
        client = self.attach(40, 100)
        for key in "SVXag":
            client.send("\x01" + key)
            time.sleep(0.8)
            if key == "g":
                client.send("\x1b")                      # a popup would have taken the keys: it must not open
            marker = "TYPED-AFTER-%s" % key
            client.send("echo %s\r" % marker)
            self.wait(lambda: marker in self.tmux.run("capture-pane", "-p", "-t", self.user).out, "the typed text after the key " + key)
            mode = self.tmux.run("display-message", "-p", "-t", self.user, "#{pane_in_mode} #{window_name}").out.strip()
            self.assertTrue(mode.startswith("0 "), "after Ctrl+A %s the pane is %r" % (key, mode))
            self.assertNotIn("[tmux]", mode)

    def test_the_hint_names_the_command_that_installs_it(self):
        client = self.attach(40, 100)
        client.send("\x01S")
        time.sleep(0.5)
        self.wait(lambda: "swarmbox addon install sysop" in self.tmux.run("show-messages").out, "the hint in the message log")


class NoFocus(RealTmux):
    """The panel never takes the focus by itself, and the sysop keys of tmux.conf (Ctrl+A then V X a g, typed fast as a user does) work from any tab. The REAL panel, the REAL
    commands and the box's tmux.conf, with the files of a service written by ss.FakeService."""

    def conf(self):
        return TMUX_CONF

    def setUp(self):
        super().setUp()
        exe = os.path.join(self.bin, "swarmbox-sysop")
        with open(exe, "w") as f:
            f.write(LAUNCHER)
        os.chmod(exe, 0o755)
        self.pth = paths.Paths(self.env)
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)
        self.d = dock.default_dock(self.tmux)            # the real panel program in the pane
        self.client = self.attach(40, 100)
        self.follower = Follower(self.pth, dock=self.d, grace=3.0)

    def goal_with(self, **pending):
        self.svc.goal()
        if pending:
            self.svc.pending(**pending)
        self.follower.step()
        return self.wait(self.panels, "the panel")[0]

    def screen(self, pane):
        return self.tmux.run("capture-pane", "-p", "-t", pane).out

    def user_text(self):
        return self.tmux.run("capture-pane", "-p", "-J", "-S", "-", "-t", self.user).out

    def typing(self, text, every=0.03):
        """a user who keeps typing in the tab; returns (stop function that gives the number of times `text` was sent)"""
        state = {"n": 0, "run": True}

        def go():
            while state["run"]:
                self.client.send(text)
                state["n"] += 1
                time.sleep(every)
        t = threading.Thread(target=go, daemon=True)
        t.start()

        def stop():
            state["run"] = False
            t.join()
            return state["n"]
        return stop

    def _typed_while_a_goal_arrives(self, **pending):
        stop = self.typing("xcgxqrXGayn")          # every key the panel knows (x stop, c n cancel, a y allow, g goal, q close) and more
        time.sleep(0.4)
        panel = self.goal_with(**pending)
        self.wait(lambda: "sending in" in self.screen(panel["id"]) or "allow?" in self.screen(panel["id"]), "the panel to show the action")
        time.sleep(1.5)
        sent = stop()
        time.sleep(0.5)
        panel, = self.panels()
        self.assertFalse(panel["active"], "the panel did not take the focus")
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.assertEqual(self.user_text().count("x"), 2 * sent, "every key typed in the tab reached the tab (x twice per send)")
        self.assertFalse(os.path.exists(self.pth.stop_request), "not one x reached the panel: no stop")
        self.assertIsNone(self.svc.decision(), "not one c, n, a or y reached the panel: no decision")
        self.assertEqual(len(self.panels()), 1, "q did not close the panel")
        self.assertIn("run the tests", self.screen(panel["id"]), "and it is alive and showing the goal")

    def test_keys_typed_in_the_tab_while_a_goal_arrives_never_reach_a_countdown_panel(self):
        self._typed_while_a_goal_arrives(mode="veto")

    def test_keys_typed_in_the_tab_while_a_goal_arrives_never_reach_an_approval_panel(self):
        self._typed_while_a_goal_arrives(mode="approve", risk="high", text="rm -rf ~/x")

    def test_the_panel_offers_buttons_for_what_it_waits_for(self):
        # (it replaces the hint of the keys that work from any tab, which the panel no longer prints: the buttons are the hint)
        panel = self.goal_with(mode="veto")
        text = self.wait(lambda: (lambda t: t if "Cancel" in t else "")(self.screen(panel["id"])), "the buttons")
        self.assertNotIn("Allow", text, "a countdown has only Cancel")
        self.svc.pending(mode="approve", risk="high", text="rm -rf ~/x")
        text = self.wait(lambda: (lambda t: t if "Allow" in t else "")(self.screen(panel["id"])), "the approval buttons")
        self.assertIn("Cancel", text)
        self.assertIn("allow? high risk", text)

    def test_the_veto_key_vetoes_a_countdown_and_refuses_an_approval(self):
        self.goal_with(mode="veto")
        self.client.send("\x01V")
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["id"], d["decision"], d["by"]), ("p1", "veto", "key"))
        os.unlink(os.path.join(self.pth.goal_dir("g1"), "decision.json"))
        self.svc.pending(mode="approve", risk="high")
        self.client.send("\x01V")
        self.assertEqual(self.wait(self.svc.decision, "the decision")["decision"], "deny")
        self.assertEqual(self.active_pane(self.win1), [self.user], "the focus never moved")

    def test_the_cancel_key_with_nothing_waiting_stops_the_goal_and_with_no_goal_does_nothing(self):
        self.svc.write_status(None)                            # no goal at all: nothing to cancel, nothing to stop
        self.client.send("\x01V")
        time.sleep(1.0)
        self.assertIsNone(self.svc.decision())
        self.assertFalse(os.path.exists(self.pth.stop_request))
        self.goal_with()                                       # a goal that runs and nothing waiting: Cancel is Stop
        self.client.send("\x01V")
        self.wait(lambda: os.path.exists(self.pth.stop_request), "the stop request")
        self.assertIsNone(self.svc.decision())
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_the_stop_key_asks_for_the_stop(self):
        self.goal_with(mode="veto")
        self.client.send("\x01X")
        self.wait(lambda: os.path.exists(self.pth.stop_request), "the stop request")
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_the_approval_gesture_allows_in_one_step_without_focusing_the_panel(self):
        panel = self.goal_with(mode="approve", risk="high", text="rm -rf ~/x")
        self.wait(lambda: "allow?" in self.screen(panel["id"]), "the approval")
        time.sleep(0.7)                                      # past the key guard of a new action
        self.client.send("run\r")                           # typed BEFORE the gesture: it is for the tab
        time.sleep(0.5)
        self.assertIsNone(self.svc.decision(), "nothing typed before the gesture reached the panel")
        self.assertIn("run", self.user_text())
        self.client.send("\x01a")
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["id"], d["decision"], d["by"], d["word"]), ("p1", "approve", "key", "run"), "one gesture allows: no typed word")
        self.assertEqual(self.active_pane(self.win1), [self.user], "the gesture never takes the focus")
        self.assertFalse(self.panels()[0]["active"])

    def test_the_approval_gesture_does_nothing_without_an_approval_and_opens_no_panel(self):
        self.svc.goal()
        self.client.send("\x01a")                          # no pending action
        time.sleep(1.0)
        self.assertEqual(self.panels(), [])
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.assertIsNone(self.svc.decision())
        self.svc.pending(mode="approve", risk="high")
        self.client.send("\x01a")                          # a pending approval, no panel: the decision is written all the same, no panel is made
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["decision"], d["by"]), ("approve", "key"))
        time.sleep(0.5)
        self.assertEqual(self.panels(), [])
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_the_approval_gesture_sends_a_countdown_action_now(self):
        self.goal_with(mode="veto")
        self.client.send("\x01a")
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["id"], d["decision"], d["by"]), ("p1", "approve", "key"), "a countdown is cut short: it is sent now")
        self.assertEqual(self.active_pane(self.win1), [self.user])

    def test_a_click_on_the_panel_focuses_it_and_then_its_own_keys_work(self):
        panel = self.goal_with(mode="veto")
        self.wait(lambda: "sending in" in self.screen(panel["id"]), "the panel")
        time.sleep(0.7)
        self.client.send("x")
        time.sleep(0.4)
        self.assertFalse(os.path.exists(self.pth.stop_request), "x in the tab is for the tab")
        col, row = panel["left"] + 4, panel["top"] + 1               # the head row of the panel, 1-based for the terminal
        self.client.send("\x1b[<0;%d;%dM" % (col, row))
        time.sleep(0.05)
        self.client.send("\x1b[<0;%d;%dm" % (col, row))
        self.wait(lambda: self.active_pane(self.win1) == [panel["id"]], "the click to focus the panel")
        time.sleep(0.6)
        self.client.send("x")
        self.wait(lambda: os.path.exists(self.pth.stop_request), "x in the focused panel to stop the goal")

    def test_a_click_on_the_cancel_button_of_the_panel_cancels(self):
        panel = self.goal_with(mode="veto")
        self.wait(lambda: "Cancel" in self.screen(panel["id"]), "the button")
        time.sleep(0.7)

        def cell():
            for r, line in enumerate(self.screen(panel["id"]).splitlines()):
                if " Cancel" in line:                                  # the colour block " Cancel " (the capture drops the last space)
                    return panel["left"] + line.index(" Cancel") + 3, panel["top"] + r + 1      # 1-based, for the terminal
        col, row = self.wait(cell, "the place of the button")

        def click():
            self.client.send("\x1b[<0;%d;%dM" % (col, row))
            time.sleep(0.05)
            self.client.send("\x1b[<0;%d;%dm" % (col, row))
        click()                                              # the first click gives the panel the focus: it is not a click on the button
        self.wait(lambda: self.active_pane(self.win1) == [panel["id"]], "the click to focus the panel")
        time.sleep(0.7)
        self.assertIsNone(self.svc.decision())
        click()
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["id"], d["decision"], d["by"]), ("p1", "veto", "panel"))

    def test_the_goal_key_asks_for_a_goal_in_a_popup_and_publishes_it(self):
        bus = ss.FakeBus(os.path.join(self.tmp, "bus.sock"))
        self.addCleanup(bus.stop)
        self.tmux.run("set-environment", "-g", "SB_BUS_SOCKET", bus.path)
        import socket
        sub = socket.socket(socket.AF_UNIX)
        sub.settimeout(20)
        sub.connect(bus.path)
        sub.sendall(b'{"op":"sub","topic":"goal"}\n')
        f = sub.makefile("rb")
        self.addCleanup(sub.close)
        f.readline()
        self.client.send("\x01g")
        time.sleep(1.0)
        self.client.send("say hello in the second tab\r")
        import json
        env = json.loads(f.readline())
        self.assertEqual((env["topic"], env["body"], env["source"]), ("goal", {"text": "say hello in the second tab"}, "panel"))
        self.assertEqual(self.active_pane(self.win1), [self.user])
        self.assertNotIn("say hello", self.user_text(), "the popup took the keys, not the tab")


if __name__ == "__main__":
    unittest.main()
