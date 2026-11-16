#!/usr/bin/env python3
"""container/config/tmux-browser-keys.conf and container/config/tmux.conf against a real tmux server and a real tmux client (a pty).

Two configurations: the keys file alone on a small base config (what docs/web-terminal.md tells a user with a config of their own to do: it needs
`set -g base-index 1`), and the box's tmux.conf, which loads the keys file and sets the SwarmBox options. A private tmux server (own socket and
TMUX_TMPDIR) is started per test and a client is attached through a pty. The keys are sent as the bytes xterm.js produces (Alt+letter = ESC+letter,
Alt+arrows = ESC[1;3x, ...) and a click as an SGR mouse sequence, then the effect is read back from tmux.

No fixed sleeps: every key is followed by the wait for its effect. A key that must have NO effect is followed by a key that has one (the next
test of the same ordered input): tmux handles the keys of one client in order, so when the later effect is there the earlier key was handled.

Run in a container (sh dev/test-slow.sh), or with SWARMBOX_TEST_REAL_TMUX=1 where tmux is installed:
    SWARMBOX_TEST_REAL_TMUX=1 python3 tests/slow/test_tmux_browser_keys.py
"""
import fcntl
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
from waiting import wait_until  # noqa: E402

KEYS = os.path.join(ROOT, "container", "config", "tmux-browser-keys.conf")
DEFAULT_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
ROWS, COLS = 20, 100
REAL = os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"


@unittest.skipUnless(REAL and shutil.which("tmux"), "needs tmux and SWARMBOX_TEST_REAL_TMUX=1 (a container: sh dev/test-slow.sh)")
class TmuxCase(unittest.TestCase):
    counter = 0
    CONF = None   # None: a small base config that sources only tmux-browser-keys.conf

    def setUp(self):
        TmuxCase.counter += 1
        self.sock = "swbk%d_%d" % (os.getpid(), TmuxCase.counter)  # one private server per test
        self.tmp = tempfile.mkdtemp()
        self.env = dict(os.environ, TMUX_TMPDIR=self.tmp)
        self.addCleanup(self.cleanup)
        self.conf = self.CONF
        if not self.conf:
            self.conf = os.path.join(self.tmp, "base.conf")
            with open(self.conf, "w") as f:
                # base-index 1 so that Alt+1..9 match the window numbers shown in the status bar
                f.write("set -g mouse on\nset -g base-index 1\nsetw -g pane-base-index 1\nsource-file %s\n" % os.path.abspath(KEYS))
        r = self.tm("-f", self.conf, "new-session", "-d", "-s", "t", "-x", str(COLS), "-y", str(ROWS), "bash --norc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("tmux", ["tmux", "-L", self.sock, "attach", "-t", "t"],
                       dict(self.env, TERM="xterm-256color", COLORTERM="truecolor"))
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self.drawn = ""
        self.assertTrue(wait_until(lambda: self.out("list-clients", "-F", "#{client_width}x#{client_height}") == "%dx%d" % (COLS, ROWS), 10, 0.02),
                        "the client never attached")
        self.assertTrue(wait_until(lambda: "bash" in self.read_drawn(), 10, 0.01), "the client never drew the status line (its first keys would be lost)")

    def cleanup(self):
        try:
            os.write(self.fd, b"\x01d")
        except OSError:
            pass
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=self.env)
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except OSError:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tm(self, *args):
        return subprocess.run(["tmux", "-L", self.sock] + list(args), capture_output=True, text=True, env=self.env)

    def out(self, *args):
        return self.tm(*args).stdout.strip()

    def windows(self):
        return [int(x) for x in self.out("list-windows", "-F", "#{window_index}").split()]

    def active(self):
        return int(self.out("display-message", "-p", "#{window_index}"))

    def panes(self):
        return int(self.out("display-message", "-p", "#{window_panes}"))

    def fmt(self, f):
        return self.out("display-message", "-p", f)

    def press(self, data, until=None, what=None):
        """Send the bytes; with `until`, wait for its effect."""
        os.write(self.fd, data)
        if until:
            self.assertTrue(wait_until(until, 10, 0.01), what or "tmux never did what %r should do" % data)

    def read_drawn(self):
        """What the client has drawn on its terminal so far, since self.drawn was last emptied."""
        while select.select([self.fd], [], [], 0)[0]:
            try:
                self.drawn += os.read(self.fd, 65536).decode("utf-8", "replace")
            except OSError:
                break
        return self.drawn

    def ask(self, data, question, answer, until=None, what=None):
        """Keys that open a prompt (confirm-before): wait until the client has drawn the question, then answer it. The prompt opens after the
        key is handled, so an answer sent at once would reach the pane as an ordinary key."""
        self.read_drawn()
        self.drawn = ""
        self.press(data)
        self.assertTrue(wait_until(lambda: question in self.read_drawn(), 10, 0.01), "the client never drew %r" % question)
        self.press(answer, until, what)

    last_click = 0.0

    def click(self, col, row=ROWS, until=None):
        """A click on the status line. tmux takes two clicks less than 300 ms apart (a limit of its own that no option moves) for a double click,
        which is another binding: the next click waits until that time is over."""
        time.sleep(max(0.0, self.last_click + 0.31 - time.monotonic()))
        self.last_click = time.monotonic()
        self.press(b"\x1b[<0;%d;%dM" % (col, row))
        self.press(b"\x1b[<0;%d;%dm" % (col, row), until)


class KeysFileAlone(TmuxCase):
    def test_the_file_loads_without_errors_and_binds_the_keys(self):
        self.assertEqual(self.tm("source-file", self.conf).stderr.strip(), "")
        keys = self.out("list-keys", "-T", "root")
        self.assertGreaterEqual(len([l for l in keys.splitlines() if " M-" in l]), 30)
        self.assertIn("MouseDown1StatusLeft", keys)

    def test_alt_n_creates_a_window_alt_h_l_move_between_them_alt_digits_jump_and_alt_0_returns_to_the_last(self):
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2])
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2, 3] and self.active() == 3)
        self.press(b"\x1bh", until=lambda: self.active() == 2)
        self.press(b"\x1bl", until=lambda: self.active() == 3)
        self.press(b"\x1b1", until=lambda: self.active() == 1)
        self.press(b"\x1b0", until=lambda: self.active() == 3)

    def test_alt_shift_l_moves_the_window_and_keeps_it_selected(self):
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2])
        self.out("rename-window", "-t", ":1", "first")
        self.press(b"\x1b1", until=lambda: self.active() == 1)
        self.press(b"\x1bL", until=lambda: self.out("list-windows", "-F", "#{window_name}").splitlines()[1:] == ["first"])
        self.assertEqual(self.active(), 2, "focus follows the moved window")

    def test_alt_w_asks_before_closing_a_window(self):
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2])
        self.ask(b"\x1bw", "close window", b"n")   # the window stays; the next key, which has an effect, shows that the n was handled
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2, 3], what="the window was closed although the answer was n")
        self.ask(b"\x1bw", "close window", b"y", until=lambda: self.windows() == [1, 2])

    def test_splits_focus_resize_zoom_and_close(self):
        self.press(b"\x1b\\", until=lambda: self.panes() == 2)
        self.press(b"\x1b-", until=lambda: self.panes() == 3)
        last = self.fmt("#{pane_index}")
        self.press(b"\x1b[1;3D", until=lambda: self.fmt("#{pane_index}") != last)  # Alt+Left
        before = int(self.fmt("#{pane_width}"))
        self.press(b"\x1b[1;4C", until=lambda: int(self.fmt("#{pane_width}")) > before)  # Alt+Shift+Right
        self.press(b"\x1bz", until=lambda: self.fmt("#{window_zoomed_flag}") == "1")
        self.press(b"\x1bz", until=lambda: self.fmt("#{window_zoomed_flag}") == "0")
        self.ask(b"\x1bx", "close pane", b"y", until=lambda: self.panes() == 2)


class BoxConfig(TmuxCase):
    """container/config/tmux.conf alone: nothing from the user's workspace is needed."""
    CONF = DEFAULT_CONF

    def test_it_sets_the_swarmbox_options_and_the_alt_keys_of_the_keys_file_it_loads_work(self):
        expected = {"prefix": "C-a", "base-index": "1", "mouse": "on", "history-limit": "50000",
                    "escape-time": "0", "status": "2", "extended-keys": "on", "renumber-windows": "on"}
        for option, value in expected.items():
            flag = "-sgv" if option in ("escape-time", "extended-keys") else "-gv"
            self.assertEqual(self.out("show", flag, option), value, option)
        self.assertIn("+", self.out("show", "-gv", "status-left"), "the [+] button comes with it")
        self.press(b"\x1bn", until=lambda: self.windows() == [1, 2])   # Alt+n of the keys file

    def test_the_prefix_bindings_work(self):
        self.press(b"\x01c", until=lambda: self.windows() == [1, 2])  # Ctrl+A c
        self.press(b"\x01|", until=lambda: self.panes() == 2)         # Ctrl+A |
        self.press(b"\x01-", until=lambda: self.panes() == 3)         # Ctrl+A -

    def test_the_plus_button_creates_a_window_only_in_the_first_three_columns(self):
        before = len(self.windows())
        self.click(1, until=lambda: len(self.windows()) == before + 1)
        self.click(3, until=lambda: len(self.windows()) == before + 2)
        self.click(4)
        self.click(40)
        self.click(2, until=lambda: len(self.windows()) > before + 2)   # the button again: by now the clicks before it were handled
        self.assertEqual(len(self.windows()), before + 3, "a column after the third must not create a window")

    def wheel_up(self, until=None):
        self.press(b"\x1b[<64;10;5M", until)   # SGR mouse report: button 64 is the wheel turned up

    def scroll_position(self):
        return int(self.fmt("#{scroll_position}") or 0)

    def test_the_mouse_wheel_scrolls_five_lines_per_event_in_copy_mode(self):
        self.press(b"seq 1 500\n", until=lambda: "500" in self.out("capture-pane", "-p"))
        self.wheel_up(until=lambda: self.fmt("#{pane_in_mode}") == "1")   # the first event of a stopped pane only enters copy mode
        self.wheel_up(until=lambda: self.scroll_position() > 0)
        first = self.scroll_position()
        self.wheel_up()
        self.wheel_up(until=lambda: self.scroll_position() >= first + 10)
        self.assertEqual(self.scroll_position() - first, 10, "two events, five lines each (it was 2 lines: too little for 50,000 lines)")

    APP = (
        "import os, sys, termios, tty, select, time\n"
        "log = open(sys.argv[1], 'a', buffering=1)\n"
        "fd = sys.stdin.fileno(); old = termios.tcgetattr(fd); tty.setraw(fd)\n"
        "sys.stdout.write('\\x1b[?1049h\\x1b[2J\\x1b[?1000h\\x1b[?1006h'); sys.stdout.flush()\n"
        "log.write('READY\\n'); end = time.time() + 20\n"
        "while time.time() < end:\n"
        "    if select.select([fd], [], [], 0.2)[0]: log.write('GOT %r\\n' % os.read(fd, 4096))\n"
    )

    def test_a_program_that_asks_for_the_mouse_gets_the_wheel_and_tmux_does_not_scroll_over_it(self):
        log = os.path.join(self.tmp, "mouse.log")
        app = os.path.join(self.tmp, "app.py")
        with open(app, "w") as f:
            f.write(self.APP)

        def logged():
            with open(log) as f:
                return f.read()
        self.press(("python3 %s %s\r" % (app, log)).encode())   # a full-screen program, as a TUI with its own scrolling is
        self.assertTrue(wait_until(lambda: os.path.exists(log) and "READY" in logged(), 15, 0.05))
        self.assertTrue(wait_until(lambda: self.fmt("#{mouse_any_flag}") == "1", 10, 0.02), "the program asked for the mouse")
        for _ in range(3):
            self.wheel_up()
        self.assertTrue(wait_until(lambda: logged().count("\\x1b[<64;10;5M") == 3, 10, 0.05), "the program got the three wheel events")
        self.assertEqual(self.fmt("#{pane_in_mode}"), "0", "tmux must not enter copy mode over such a program")

    def test_the_scrollbar_is_off_and_set_quietly_so_an_older_tmux_still_loads_the_file(self):
        with open(DEFAULT_CONF) as f:
            text = f.read()
        self.assertRegex(text, r"(?m)^set -gq pane-scrollbars off$")
        self.assertNotRegex(text, r"(?m)^set -g\w* pane-scrollbars (on|modal)", "the default is no bar: it takes a column of the pane")
        self.assertRegex(text, r"(?m)^# -q: ", "the file says why the line is quiet")
        if not self.out("show", "-gqv", "pane-scrollbars-style"):
            self.skipTest("this tmux (%s) has no pane scrollbar (3.6 and later have)" % self.out("-V").replace("tmux ", ""))
        self.assertEqual(self.out("show", "-gqv", "pane-scrollbars"), "off")

    def test_it_finds_the_keys_file_next_to_itself_from_any_directory_and_loads_when_it_is_absent(self):
        for with_keys in (True, False):
            directory = os.path.join(self.tmp, "etc" if with_keys else "etc-alone")
            os.makedirs(directory)
            shutil.copy(DEFAULT_CONF, directory)
            if with_keys:
                shutil.copy(KEYS, directory)
            sock = self.sock + ("k" if with_keys else "n")
            self.addCleanup(lambda s=sock: subprocess.run(["tmux", "-L", s, "kill-server"], capture_output=True, env=self.env))
            r = subprocess.run(["tmux", "-L", sock, "-f", os.path.join(directory, "tmux.conf"), "new-session", "-d", "-s", "t", "-x", "100", "-y", "20",
                                "bash --norc"], capture_output=True, text=True, env=self.env)
            self.assertEqual((r.returncode, r.stderr.strip()), (0, ""), r.stderr)
            keys = subprocess.run(["tmux", "-L", sock, "list-keys", "-T", "root"], capture_output=True, text=True, env=self.env).stdout
            self.assertEqual(" M-n " in keys, with_keys)
            self.assertEqual("MouseDown1StatusLeft" in keys, with_keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
