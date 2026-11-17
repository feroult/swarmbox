#!/usr/bin/env python3
"""A real tmux and a pty: an OSC 8 link written by a program in a pane reaches an xterm-256color client with its address when the box's tmux.conf is
loaded (and does not without the line that turns the feature on). Needs the gate of dev/test-slow.sh."""
import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

REAL = os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1" and shutil.which("tmux")
PRINT = r"""printf '\033]8;;https://example.com/x\033\\label\033]8;;\033\\\n'; sleep 3"""


def client_output(conf_text):
    tmp = tempfile.mkdtemp(prefix="sbhl-")
    sock = os.path.join(tmp, "s")
    conf = os.path.join(tmp, "t.conf")
    with open(conf, "w") as f:
        f.write(conf_text)
    try:
        subprocess.run(["tmux", "-S", sock, "-f", conf, "new-session", "-d", "-x", "80", "-y", "10", "-s", "p", PRINT], check=True)
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-S", sock, "-f", conf, "attach", "-t", "p"])
        buf, end = b"", time.time() + 2.5
        while time.time() < end:
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    buf += os.read(fd, 65536)
                except OSError:
                    break
        return buf
    finally:
        subprocess.run(["tmux", "-S", sock, "kill-server"], stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, True)


@unittest.skipUnless(REAL, "needs a real tmux and SWARMBOX_TEST_REAL_TMUX=1 (sh dev/test-slow.sh)")
class Links(unittest.TestCase):
    def test_a_link_keeps_its_address_with_the_config_of_the_box_and_loses_it_without(self):
        base = 'set -g default-terminal "tmux-256color"\n'
        self.assertNotIn(b"example.com", client_output(base), "tmux's own defaults: the label arrives alone (the bug)")
        with open(os.path.join(ROOT, "container", "config", "tmux.conf")) as f:
            box = [ln for ln in f.read().splitlines() if "terminal-features" in ln and "hyperlinks" in ln and not ln.lstrip().startswith("#")]
        self.assertTrue(box)
        out = client_output(base + "\n".join(box) + "\n")
        self.assertIn(b"\x1b]8;", out)
        self.assertIn(b"example.com", out)


if __name__ == "__main__":
    unittest.main()
