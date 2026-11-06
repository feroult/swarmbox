#!/usr/bin/env python3
"""Browser tests for the look of the web terminal (container/ttyd-style.css): the padding around the terminal
and the minimal scrollbar. Same setup as test_clipboard_bridge.py: the real web-terminal.sh builds the page, a
real ttyd serves it, headless Chromium measures it.

Run:  python3 tests/test_web_style.py        (needs chromium, ttyd and tmux; skipped otherwise)
"""
import json
import os
import shutil
import time
import unittest

import test_clipboard_bridge as base

MEASURE = """(() => {
  const q = s => document.querySelector(s), rect = e => e.getBoundingClientRect();
  const screen = rect(q('.xterm-screen')), viewport = q('.xterm-viewport');
  return {win: [innerWidth, innerHeight], left: screen.left, top: screen.top, right: innerWidth - screen.right,
          bottom: innerHeight - screen.bottom, cols: term.cols, rows: term.rows,
          bar: getComputedStyle(viewport, '::-webkit-scrollbar').width,
          thumb: getComputedStyle(viewport, '::-webkit-scrollbar-thumb').backgroundColor,
          radius: getComputedStyle(viewport, '::-webkit-scrollbar-thumb').borderRadius,
          track: getComputedStyle(viewport, '::-webkit-scrollbar-track').backgroundColor};
})()"""


@unittest.skipUnless(all(shutil.which(c) for c in base.NEEDED), "needs chromium, ttyd and tmux")
class WebStyle(base.ClipboardBridge):
    # only the browser harness is reused, not the clipboard tests that live in the same class
    for _name in [n for n in dir(base.ClipboardBridge) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def measure(self, conf=""):
        self.open_terminal(conf)
        return self.page.js(MEASURE)

    def test_the_terminal_is_5px_from_every_edge_by_default(self):
        m = self.measure()
        self.assertEqual((m["left"], m["top"]), (5, 5))
        # the grid is a whole number of cells, so the right/bottom gap is at least the padding
        self.assertGreaterEqual(m["right"], 5)
        self.assertGreaterEqual(m["bottom"], 5)

    def test_the_padding_can_be_changed_in_the_config_file(self):
        m = self.measure("padding=12\n")
        self.assertEqual((m["left"], m["top"]), (12, 12))
        self.assertGreaterEqual(m["bottom"], 12)

    def test_a_bad_padding_falls_back_to_5(self):
        m = self.measure("padding=lots\n")
        self.assertEqual((m["left"], m["top"]), (5, 5))

    def test_the_scrollbar_is_thin_translucent_and_has_no_track(self):
        m = self.measure()
        self.assertEqual(m["bar"], "6px")
        self.assertEqual(m["track"], "rgba(0, 0, 0, 0)")
        self.assertEqual(m["thumb"], "rgba(255, 255, 255, 0.16)")
        self.assertEqual(m["radius"], "3px")

    def test_the_terminal_still_fills_the_window(self):
        self.open_terminal()
        self.page.js("window.dispatchEvent(new Event('resize'))")   # as a real window does when it is laid out
        time.sleep(0.5)
        m = self.page.js(MEASURE)
        # no cell of slack beyond what rounding to whole cells leaves
        cw = self.page.js("document.querySelector('.xterm-screen').offsetWidth / term.cols")
        ch = self.page.js("document.querySelector('.xterm-screen').offsetHeight / term.rows")
        self.assertLess(m["right"] - 5, cw + 6 + 1)
        self.assertLess(m["bottom"] - 5, ch + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
