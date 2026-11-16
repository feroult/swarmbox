#!/usr/bin/env python3
"""The look of the web terminal in a real browser (container/web/ttyd-style.css): the padding around the terminal and the scrollbar (off by default:
tmux owns the scrollback; scrollbar=true is a minimal one). The settings reach the page in tests/fast/test_web_build.py; here the browser measures what
they do. Same set-up as test_clipboard_bridge.py: the real build-index.sh and swarmbox-web build the page, a real ttyd serves it over a real tmux.

Run in a container (sh dev/test-slow.sh): SWARMBOX_TEST_REAL_TMUX=1 python3 tests/slow/test_web_style.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import browser_support as bs  # noqa: E402
from waiting import wait_until  # noqa: E402

MEASURE = """(() => {
  const q = s => document.querySelector(s), rect = e => e.getBoundingClientRect();
  const screen = rect(q('.xterm-screen')), viewport = q('.xterm-viewport');
  return {left: screen.left, top: screen.top, right: innerWidth - screen.right, bottom: innerHeight - screen.bottom,
          cellw: q('.xterm-screen').offsetWidth / term.cols, cellh: q('.xterm-screen').offsetHeight / term.rows, scrollback: term.options.scrollback,
          bar: getComputedStyle(viewport, '::-webkit-scrollbar').width,
          thumb: getComputedStyle(viewport, '::-webkit-scrollbar-thumb').backgroundColor,
          radius: getComputedStyle(viewport, '::-webkit-scrollbar-thumb').borderRadius,
          track: getComputedStyle(viewport, '::-webkit-scrollbar-track').backgroundColor};
})()"""

CHROMIUM = None


def setUpModule():
    global CHROMIUM
    if bs.REAL and bs.CHROMIUM:
        CHROMIUM = bs.Chromium()


def tearDownModule():
    if CHROMIUM:
        CHROMIUM.close()


@bs.browser_tests()
class WebStyle(unittest.TestCase):
    def measure(self, conf):
        term = bs.WebTerminal(CHROMIUM, conf=conf, command="cat")   # the scrollback and the font come from swarmbox-web, as in the box
        self.addCleanup(term.close)
        term.page.js("window.dispatchEvent(new Event('resize'))")   # as a real window does when it is laid out

        def fitted():   # the grid fills the window but for less than a cell
            m = term.page.js(MEASURE)
            return m if m["right"] - m["left"] < m["cellw"] + 7 and m["bottom"] - m["top"] < m["cellh"] + 1 else None
        return wait_until(fitted, 5) or term.page.js(MEASURE)

    def test_by_default_the_padding_is_10px_the_terminal_fills_the_window_and_there_is_no_scrollbar_or_history(self):
        m = self.measure("")
        self.assertEqual((m["left"], m["top"]), (10, 10))
        # the grid is a whole number of cells, so the gap at the right and the bottom is the padding plus less than a cell
        self.assertGreaterEqual(m["right"], 10)
        self.assertGreaterEqual(m["bottom"], 10)
        self.assertLess(m["right"] - 10, m["cellw"] + 6 + 1)
        self.assertLess(m["bottom"] - 10, m["cellh"] + 1)
        self.assertEqual(m["bar"], "0px")
        self.assertEqual(m["scrollback"], 0, "xterm.js would reserve 15 px for a bar it measures as zero if it kept a history")

    def test_the_conf_sets_the_padding_a_thin_translucent_bar_without_a_track_and_the_history(self):
        m = self.measure("padding=12\nscrollbar=true\nscrollback=500\n")
        self.assertEqual((m["left"], m["top"]), (12, 12))
        self.assertGreaterEqual(m["bottom"], 12)
        self.assertEqual((m["bar"], m["radius"]), ("6px", "3px"))
        self.assertEqual(m["track"], "rgba(0, 0, 0, 0)")
        self.assertEqual(m["thumb"], "rgba(167, 139, 250, 0.28)")
        self.assertEqual(m["scrollback"], 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
