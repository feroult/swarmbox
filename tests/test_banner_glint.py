"""The glint of the banner (container/scripts/banner.sh), in a real tmux.

Every test starts its own tmux server on a socket of its own (swarmbox-test-glint-...) with the banner as the program of the pane, and the
switch `@swarmbox-glint` OFF, so the screen is still while the reference is taken; the glint is then turned on with `tmux set -g`.
They are skipped without tmux. Run: python3 tests/test_banner_glint.py
"""
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

BANNER = os.path.join(ROOT, "container", "scripts", "banner.sh")
GLINT_CENTRE = "38;5;231"   # the colour of the one column where the glint is white
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def visible_cells(colored):
    """(character, foreground) of every cell that has a character: what the eye sees. The foreground of a space is left out, because
    a space has no ink and tmux serializes it either way."""
    out, fg, pos = [], None, 0
    for m in SGR.finditer(colored + "\x1b[0m"):
        for ch in colored[pos:m.start()]:
            if ch not in " \n":
                out.append((ch, fg))
        pos = m.end()
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c in ("0", "39"):
                fg = None
            elif c == "38" and i + 2 < len(codes) and codes[i + 1] == "5":
                fg = codes[i + 2]
                i += 2
            elif c == "38" and i + 4 < len(codes) and codes[i + 1] == "2":
                fg = tuple(codes[i + 2:i + 5])
                i += 4
            i += 1
    return out


@unittest.skipUnless(shutil.which("tmux"), "needs tmux")
class Glint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="glint-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.sock = "swarmbox-test-glint-" + "".join(random.choice(string.ascii_lowercase) for _ in range(6))
        self.env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
        self.env.update(TERM="xterm-256color", LANG="C.UTF-8")
        with open(os.path.join(self.tmp, "tmux.conf"), "w") as f:
            f.write("set -g @swarmbox-glint off\n")
        r = self.tm("-f", os.path.join(self.tmp, "tmux.conf"), "new-session", "-d", "-s", "x", "-x", "80", "-y", "24",
                    "bash %s; sleep 120" % BANNER)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.addCleanup(self.stop)
        self.assertTrue(self.wait(lambda: "from anywhere" in self.capture(), 10), "the banner did not appear")

    def stop(self):
        self.tm("kill-server")
        for d in [d for d in os.listdir("/tmp") if d.startswith("tmux-")]:   # a server that died on its own leaves its socket file behind
            path = os.path.join("/tmp", d, self.sock)
            if os.path.exists(path):
                os.unlink(path)

    def tm(self, *args):
        return subprocess.run(["tmux", "-L", self.sock] + list(args), env=self.env, capture_output=True, text=True)

    def capture(self, colors=False):
        return self.tm("capture-pane", "-p", *(["-e"] if colors else []), "-t", "x").stdout

    @staticmethod
    def wait(cond, timeout, step=0.05):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(step)
        return False

    def one_pass(self):
        """turn the glint on and wait for it to start and to end (white seen, then not seen for a while)"""
        self.assertEqual(self.tm("set", "-g", "@swarmbox-glint", "on").returncode, 0)
        self.assertTrue(self.wait(lambda: GLINT_CENTRE in self.capture(True), 15), "the glint never lit the letters")
        # the pass is over when no white has been seen for half a second (a pass is about 1.4 s; the white moves along the letters)
        quiet = {"since": None}

        def over():
            if GLINT_CENTRE in self.capture(True):
                quiet["since"] = None
                return False
            quiet["since"] = quiet["since"] or time.time()
            return time.time() - quiet["since"] > 0.6
        self.assertTrue(self.wait(over, 15), "the glint did not end")
        self.assertTrue(self.tm("set", "-g", "@swarmbox-glint", "off").returncode == 0)

    def test_with_the_switch_off_nothing_is_ever_drawn(self):
        end = time.time() + 5
        while time.time() < end:
            self.assertNotIn(GLINT_CENTRE, self.capture(True), "the glint drew with @swarmbox-glint off")
            time.sleep(0.15)

    def test_a_pass_writes_only_the_cells_that_change_and_leaves_the_letters_as_they_were(self):
        before_plain, before_colors = self.capture(), self.capture(True)
        log = os.path.join(self.tmp, "pane.bin")
        self.assertEqual(self.tm("pipe-pane", "-O", "-t", "x", "cat >> %s" % log).returncode, 0)   # what the program writes INTO the pane
        for direction in ("left to right", "right to left"):   # the glint alternates
            self.one_pass()
            time.sleep(0.4)
            self.assertEqual(self.capture(), before_plain, "the text of the screen changed (%s)" % direction)
            self.assertEqual(visible_cells(self.capture(True)), visible_cells(before_colors),
                             "the colors of the letters did not come back after the pass %s" % direction)
        with open(log, "rb") as f:
            data = f.read()
        frames = data.split(b"\x1b7")[1:]
        self.assertGreaterEqual(len(frames), 40, "two passes have dozens of steps each")
        # a step that rewrote the three rows whole was about 940 bytes; the cells that change are about 210 (300 at the most)
        self.assertLess(max(len(f) for f in frames), 600, "a step writes whole rows again: a terminal that draws while it receives can show it half done")
        self.assertTrue(all(b"\x1b8" in f for f in frames), "every step puts the cursor back")

    def test_the_glint_ends_when_the_pane_is_gone(self):
        self.assertEqual(self.tm("set", "-g", "@swarmbox-glint", "on").returncode, 0)
        out = {}

        def pid():
            out["pid"] = self.tm("show-options", "-pqv", "-t", "x", "@swarmbox_glint_pid").stdout.strip()
            return out["pid"].isdigit()
        self.assertTrue(self.wait(pid, 10), "the glint did not record its pid")
        pid_n = int(out["pid"])
        self.tm("kill-server")

        def gone():
            # a process that has exited but whose parent has not collected it yet (a zombie) still answers kill(pid, 0): under
            # tests/run_all.sh the parent of an orphan is reap_run.py, which collects only when the test file is over. It is gone for our purpose.
            try:
                with open("/proc/%d/stat" % pid_n) as f:
                    return f.read().rsplit(")", 1)[1].split()[0] == "Z"
            except FileNotFoundError:
                return True
            except OSError:
                pass
            try:
                os.kill(pid_n, 0)   # without /proc
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            return False
        self.assertTrue(self.wait(gone, 20, step=0.3), "the glint is still running after its pane was gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
