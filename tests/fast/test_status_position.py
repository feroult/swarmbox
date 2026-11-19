"""the tabs of tmux are at the top on a narrow window (a phone) and at the bottom otherwise: the hooks of container/config/tmux.conf"""
import fcntl
import os
import pty
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONF = os.path.join(ROOT, "container", "config", "tmux.conf")


@unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
class StatusPosition(unittest.TestCase):
    def setUp(self):
        self.sock = os.path.join(tempfile.mkdtemp(), "t.sock")
        self.addCleanup(lambda: subprocess.run(["tmux", "-S", self.sock, "kill-server"], capture_output=True))
        self.tm("-f", CONF, "new-session", "-d", "-x", "100", "-y", "30", "-s", "t")
        self.clients = []
        self.addCleanup(lambda: [p.terminate() for p in self.clients])

    def tm(self, *args):
        return subprocess.run(["tmux", "-S", self.sock] + list(args), capture_output=True, text=True).stdout.strip()

    def attach(self, cols):
        for p in self.clients:
            p.terminate()
        self.clients = []
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, cols, 0, 0))
        self.clients.append(subprocess.Popen(["tmux", "-S", self.sock, "attach", "-t", "t"], stdin=slave, stdout=slave, stderr=slave,
                                             env=dict(os.environ, TERM="xterm-256color")))
        deadline = time.time() + 5
        while time.time() < deadline and self.tm("display", "-p", "#{window_width}") != str(cols):
            time.sleep(0.1)
        time.sleep(0.4)

    def position(self):
        return self.tm("show", "-gv", "status-position")

    def test_the_tabs_are_at_the_bottom_until_a_narrow_client_comes(self):
        self.assertEqual(self.position(), "bottom")

    def test_a_phone_puts_the_tabs_on_top_and_a_desktop_takes_them_down_again(self):
        self.attach(64)
        self.assertEqual(self.position(), "top")
        self.attach(120)
        self.assertEqual(self.position(), "bottom")

    def test_eighty_columns_is_narrow_and_eighty_one_is_not(self):
        self.attach(80)
        self.assertEqual(self.position(), "top")
        self.attach(81)
        self.assertEqual(self.position(), "bottom")

    def test_the_empty_line_is_on_the_side_of_the_terminal(self):
        f0, f1 = self.tm("show", "-gv", "status-format[0]"), self.tm("show", "-gv", "status-format[1]")
        self.assertIn("#{E:@sb_bar}", f0 + f1)
        self.assertTrue(self.tm("show", "-gv", "@sb_bar").startswith("#[align=left"), "the bar is kept: %r" % self.tm("show", "-gv", "@sb_bar")[:40])


if __name__ == "__main__":
    unittest.main()
