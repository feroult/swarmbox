#!/usr/bin/env python3
"""Browser tests for the look of the web terminal (container/web/ttyd-style.css): the padding around the terminal
and the scrollbar (off by default: tmux owns the scrollback; scrollbar=true is a minimal one). Same setup as test_clipboard_bridge.py: the real build-index.sh and swarmbox-web build the page, a
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
          bottom: innerHeight - screen.bottom, cols: term.cols, rows: term.rows, scrollback: term.options.scrollback,
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

    PASS_OPTIONS = True   # the scrollback and the font come from swarmbox-web, as in the box

    def measure(self, conf=""):
        self.open_terminal(conf)
        return self.page.js(MEASURE)

    def test_the_terminal_is_5px_from_every_edge_by_default(self):
        m = self.measure()
        self.assertEqual((m["left"], m["top"]), (10, 10))
        # the grid is a whole number of cells, so the right/bottom gap is at least the padding
        self.assertGreaterEqual(m["right"], 10)
        self.assertGreaterEqual(m["bottom"], 10)

    def test_the_padding_can_be_changed_in_the_config_file(self):
        m = self.measure("padding=12\n")
        self.assertEqual((m["left"], m["top"]), (12, 12))
        self.assertGreaterEqual(m["bottom"], 12)

    def test_a_bad_padding_falls_back_to_the_default(self):
        m = self.measure("padding=lots\n")
        self.assertEqual((m["left"], m["top"]), (10, 10))

    def test_there_is_no_scrollbar_by_default_because_tmux_owns_the_scrollback(self):
        m = self.measure()
        self.assertEqual(m["bar"], "0px")
        self.assertEqual(m["scrollback"], 0, "xterm.js would reserve 15 px for a bar it measures as zero if it kept a history")

    def test_scrollbar_true_gives_a_thin_translucent_bar_with_no_track_and_keeps_the_history(self):
        m = self.measure("scrollbar=true\n")
        self.assertEqual(m["bar"], "6px")
        self.assertEqual(m["track"], "rgba(0, 0, 0, 0)")
        self.assertEqual(m["thumb"], "rgba(167, 139, 250, 0.28)")
        self.assertEqual(m["radius"], "3px")
        self.assertGreater(m["scrollback"], 0)

    def test_a_scrollback_in_the_conf_wins(self):
        self.assertEqual(self.measure("scrollback=500\n")["scrollback"], 500)

    def test_the_terminal_still_fills_the_window(self):
        self.open_terminal()
        self.page.js("window.dispatchEvent(new Event('resize'))")   # as a real window does when it is laid out
        time.sleep(0.5)
        m = self.page.js(MEASURE)
        # no cell of slack beyond what rounding to whole cells leaves
        cw = self.page.js("document.querySelector('.xterm-screen').offsetWidth / term.cols")
        ch = self.page.js("document.querySelector('.xterm-screen').offsetHeight / term.rows")
        self.assertLess(m["right"] - 10, cw + 6 + 1)
        self.assertLess(m["bottom"] - 10, ch + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
