#!/usr/bin/env python3
"""Links written as OSC 8 (label + address, as Claude Code writes them) must reach the terminal: tmux's defaults for xterm* leave the `hyperlinks` feature
out, so the config of the box turns it on (container/config/tmux.conf). The proof with a real tmux and a pty is tests/slow/test_tmux_hyperlinks_real.py."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402


class Conf(unittest.TestCase):
    def test_xterm_clients_get_the_hyperlinks_feature(self):
        with open(os.path.join(ROOT, "container", "config", "tmux.conf")) as f:
            lines = [ln for ln in f.read().splitlines() if not ln.lstrip().startswith("#")]
        self.assertTrue([ln for ln in lines if re.search(r"terminal-features.*xterm\*:hyperlinks", ln)],
                        "without it tmux drops the address of every OSC 8 link and only the label reaches the browser or the terminal")


if __name__ == "__main__":
    unittest.main()
