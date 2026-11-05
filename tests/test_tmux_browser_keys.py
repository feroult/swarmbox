#!/usr/bin/env python3
"""Tests for container/tmux-browser-keys.conf against a real tmux server and a real tmux client.

Run:  python3 tests/test_tmux_browser_keys.py
To check YOUR config instead of the file alone:  TMUX_CONF=~/.tmux.conf python3 tests/test_tmux_browser_keys.py

A private tmux server (own socket) is started and a client is attached through a pty. The keys are sent
as the bytes xterm.js produces (Alt+letter = ESC+letter, Alt+arrows = ESC[1;3x, ...) and a click as an
SGR mouse sequence, then the effect is read back from tmux. Skipped when tmux is not installed.
"""
import fcntl
import os
import pty
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = os.path.join(HERE, "..", "container", "tmux-browser-keys.conf")
ROWS, COLS = 20, 100


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class BrowserKeys(unittest.TestCase):
    counter = 0

    def setUp(self):
        BrowserKeys.counter += 1
        self.sock = "swbk%d_%d" % (os.getpid(), BrowserKeys.counter)  # one private server per test
        self.tmp = tempfile.mkdtemp()
        conf = os.environ.get("TMUX_CONF")
        if conf:
            self.conf = os.path.expanduser(conf)
        else:
            self.conf = os.path.join(self.tmp, "base.conf")
            with open(self.conf, "w") as f:
                # base-index 1 so that Alt+1..9 match the window numbers shown in the status bar
                f.write("set -g mouse on\nset -g base-index 1\nsetw -g pane-base-index 1\nsource-file %s\n" % os.path.abspath(KEYS))
        self.addCleanup(self.cleanup)
        r = self.tm("-f", self.conf, "new-session", "-d", "-s", "t", "-x", str(COLS), "-y", str(ROWS), "bash --norc", pre=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        time.sleep(0.8)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe("tmux", ["tmux", "-L", self.sock, "attach", "-t", "t"],
                       {"TERM": "xterm-256color", "COLORTERM": "truecolor", "HOME": os.environ["HOME"], "PATH": os.environ["PATH"]})
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        time.sleep(0.8)

    def cleanup(self):
        try:
            os.write(self.fd, b"\x01d")
        except OSError:
            pass
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tm(self, *args, pre=False):
        cmd = ["tmux", "-L", self.sock] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def out(self, *args):
        return self.tm(*args).stdout.strip()

    def windows(self):
        return [int(x) for x in self.out("list-windows", "-F", "#{window_index}").split()]

    def active(self):
        return int(self.out("display-message", "-p", "#{window_index}"))

    def panes(self):
        return int(self.out("display-message", "-p", "#{window_panes}"))

    def press(self, data, wait=0.45):
        os.write(self.fd, data)
        time.sleep(wait)

    def click(self, col, row=ROWS):
        self.press(b"\x1b[<0;%d;%dM" % (col, row), 0.15)
        self.press(b"\x1b[<0;%d;%dm" % (col, row), 0.45)

    # ---- loading -------------------------------------------------------------------------------
    def test_the_config_loads_without_errors_and_binds_the_keys(self):
        self.assertEqual(self.tm("source-file", self.conf).stderr.strip(), "")
        alt = [l for l in self.out("list-keys", "-T", "root").splitlines() if " M-" in l]
        self.assertGreaterEqual(len(alt), 30)
        self.assertIn("MouseDown1StatusLeft", self.out("list-keys", "-T", "root"))

    # ---- windows (tabs) ------------------------------------------------------------------------
    def test_alt_n_creates_a_window_and_alt_h_l_move_between_them(self):
        self.press(b"\x1bn")
        self.press(b"\x1bn")
        self.assertEqual(self.windows(), [1, 2, 3])
        self.assertEqual(self.active(), 3)
        self.press(b"\x1bh")
        self.assertEqual(self.active(), 2)
        self.press(b"\x1bl")
        self.assertEqual(self.active(), 3)

    def test_alt_digits_jump_and_alt_0_returns_to_the_last_window(self):
        for _ in range(2):
            self.press(b"\x1bn")
        self.press(b"\x1b1")
        self.assertEqual(self.active(), 1)
        self.press(b"\x1b0")
        self.assertEqual(self.active(), 3)

    def test_alt_shift_l_moves_the_window_and_keeps_it_selected(self):
        self.press(b"\x1bn")
        self.out("rename-window", "-t", ":1", "first")
        self.press(b"\x1b1")
        self.press(b"\x1bL")
        names = self.out("list-windows", "-F", "#{window_index}:#{window_name}").splitlines()
        self.assertEqual(names[1].split(":")[1], "first")
        self.assertEqual(self.active(), 2, "focus follows the moved window")

    def test_alt_w_asks_before_closing_a_window(self):
        self.press(b"\x1bn")
        self.press(b"\x1bw")
        self.press(b"n")
        self.assertEqual(self.windows(), [1, 2], "answering n keeps the window")
        self.press(b"\x1bw")
        self.press(b"y")
        self.assertEqual(self.windows(), [1])

    # ---- panes ---------------------------------------------------------------------------------
    def test_splits_focus_resize_zoom_and_close(self):
        self.press(b"\x1b\\")
        self.assertEqual(self.panes(), 2)
        self.press(b"\x1b-")
        self.assertEqual(self.panes(), 3)
        last = self.out("display-message", "-p", "#{pane_index}")
        self.press(b"\x1b[1;3D")  # Alt+Left
        self.assertNotEqual(self.out("display-message", "-p", "#{pane_index}"), last)
        before = int(self.out("display-message", "-p", "#{pane_width}"))
        self.press(b"\x1b[1;4C")  # Alt+Shift+Right
        self.assertGreater(int(self.out("display-message", "-p", "#{pane_width}")), before)
        self.press(b"\x1bz")
        self.assertEqual(self.out("display-message", "-p", "#{window_zoomed_flag}"), "1")
        self.press(b"\x1bz")
        self.assertEqual(self.out("display-message", "-p", "#{window_zoomed_flag}"), "0")
        self.press(b"\x1bx")
        self.press(b"y")
        self.assertEqual(self.panes(), 2)

    # ---- mouse ---------------------------------------------------------------------------------
    def test_the_plus_button_creates_a_window_only_in_the_first_three_columns(self):
        for col in (1, 2, 3):
            before = len(self.windows())
            self.click(col)
            self.assertEqual(len(self.windows()), before + 1, "column %d is the [+] button" % col)
        for col in (4, 8, 40):
            before = len(self.windows())
            self.click(col)
            self.assertEqual(len(self.windows()), before, "column %d must not create a window" % col)


if __name__ == "__main__":
    unittest.main(verbosity=2)
