#!/usr/bin/env python3
"""The browser bridge of the web terminal (container/web/ttyd-clipboard.js: clipboard, Ctrl+V / Ctrl+C, right click) in a real browser.

The page is built by the real build-index.sh and rendered by the real swarmbox-web, served by a REAL ttyd over a real tmux, and driven in headless
Chromium over the DevTools protocol (tests/support/browser_support.py). Selections are made with the SGR mouse sequences xterm.js sends, the keys
with real key events, the clipboard is read back with navigator.clipboard. One Chromium for the file and one terminal for each of the two
configurations (the defaults, and both Ctrl keys turned off), because every test works on the same terminal and leaves it as it found it.

Run in a container (sh dev/test-slow.sh), or with SWARMBOX_TEST_REAL_TMUX=1 where chromium, ttyd and tmux are installed:
    SWARMBOX_TEST_REAL_TMUX=1 python3 tests/slow/test_clipboard_bridge.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import browser_support as bs  # noqa: E402
from waiting import wait_until  # noqa: E402

CHROMIUM = None


def setUpModule():
    global CHROMIUM
    if bs.REAL and bs.CHROMIUM:
        CHROMIUM = bs.Chromium()


def tearDownModule():
    if CHROMIUM:
        CHROMIUM.close()


class Terminal(unittest.TestCase):
    CONF = ""
    term = None

    @classmethod
    def setUpClass(cls):
        cls.term = bs.WebTerminal(CHROMIUM, conf=cls.CONF, options=False)
        cls.term.wait_screen("$")

    @classmethod
    def tearDownClass(cls):
        if cls.term:
            cls.term.close()

    def setUp(self):
        self.t = self.term
        self.t.tmux("send-keys", "-t", "t:", "C-u")   # a test may leave text on the command line (a paste): the next one starts from an empty one
        self.t.page.js("term.clearSelection()")
        self.t.clear_sent()

    def say(self, text):
        """Type `text` as a command and wait until it is on the screen with its output; return nothing."""
        self.t.type("%s\r" % text)

    def select(self, text):
        """Select `text` on the screen of xterm (the last line that has it); the clipboard is not touched."""
        found = self.t.page.js("""(() => { const b = term.buffer.active; let at = null;
            for (let i = 0; i < b.length; i++) { const x = b.getLine(i).translateToString(true).indexOf(%r); if (x >= 0) at = [x, i]; }
            if (at) term.select(at[0], at[1], %d); return at; })()""" % (text, len(text)))
        self.assertTrue(found, "%r is not on the screen" % text)


@bs.browser_tests()
class Defaults(Terminal):
    def test_what_tmux_copies_reaches_the_browser_clipboard(self):
        t = self.t
        t.set_clipboard("BEFORE")
        self.say("clear; echo SELECT-ME-PLEASE")
        self.assertTrue(t.wait_line("SELECT-ME-PLEASE"), t.screen())
        t.type("\x1b[<0;1;1M")    # press, drag and release of the mouse on the first row: the drag takes tmux into copy mode, the release copies
        t.type("\x1b[<32;8;1M")
        self.assertTrue(wait_until(lambda: t.tmux("display-message", "-p", "#{pane_in_mode}").strip() == "1", 10), "the drag did not start a selection")
        t.type("\x1b[<32;16;1M")
        t.type("\x1b[<0;16;1m")
        self.assertTrue(wait_until(lambda: "SELECT-ME" in t.clipboard(), 10), "a mouse selection in tmux never reached the clipboard: %r" % t.clipboard())
        self.assertIn("SELECT-ME", t.tmux("show-buffer"), "tmux itself did copy")
        t.tmux("set-buffer", "-w", "from-tmux-é-ç")   # the other way in: set-buffer -w, with characters that are not ASCII
        self.assertTrue(wait_until(lambda: t.clipboard() == "from-tmux-é-ç", 10), t.clipboard())

    def test_an_osc52_read_request_is_never_answered(self):
        t = self.t
        t.set_clipboard("SECRET-FROM-ELSEWHERE")
        t.page.js("new Promise(done => term.write('\\x1b]52;c;?\\x07', done))", wait=True)   # the parser has seen it when the callback runs
        self.assertNotIn("52", t.sent(), "nothing may be sent back")
        self.assertNotIn("SECRET", t.sent())
        self.assertEqual(t.clipboard(), "SECRET-FROM-ELSEWHERE", "and a read request must not change it")

    def test_ctrl_v_pastes_instead_of_sending_a_control_character(self):
        t = self.t
        t.set_clipboard("PASTE-ME-42")
        t.page.ctrl_key("v")
        self.assertTrue(wait_until(lambda: "PASTE-ME-42" in t.sent(), 10), t.sent())
        self.assertNotIn("\x16", t.sent())

    def test_ctrl_c_copies_a_selection_without_interrupting_and_without_one_it_interrupts(self):
        t = self.t
        self.say("echo COPY-ME-NOW")
        self.assertTrue(t.wait_line("COPY-ME-NOW"))
        t.set_clipboard("BEFORE")
        self.select("COPY-ME-NOW")
        t.page.ctrl_key("c")
        self.assertTrue(wait_until(lambda: t.clipboard() == "COPY-ME-NOW", 10), t.clipboard())
        self.assertNotIn("\x03", t.sent(), "a copy must not also send ^C")
        t.page.js("term.clearSelection()")
        t.page.ctrl_key("c")
        self.assertTrue(wait_until(lambda: "\x03" in t.sent(), 10), "without a selection ^C is an interrupt")

def right_click(t, shift=False):
    """Right click in the middle of the terminal; returns whether the browser's own menu was prevented."""
    t.page.js("window.__ctx = []; if (window.__ctxh) window.removeEventListener('contextmenu', window.__ctxh);"
              " window.__ctxh = e => window.__ctx.push(e.defaultPrevented); window.addEventListener('contextmenu', window.__ctxh);")
    x, y = t.page.js("(() => { const r = term.element.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    t.clear_sent()
    t.page.mouse("mousePressed", x, y, button="right", modifiers=8 if shift else 0)
    t.page.mouse("mouseReleased", x, y, button="right", modifiers=8 if shift else 0)
    assert t.page.wait_js("window.__ctx.length > 0", 10), "the page saw no contextmenu event"
    return t.page.js("window.__ctx.slice()")


# A right click makes tmux open its own menu, which holds the keys that follow: these two tests have a terminal each.
@bs.browser_tests()
class RightClickWhileTmuxHasTheMouse(Terminal):
    def test_only_tmuxs_menu_opens_and_shift_keeps_the_browsers(self):
        t = self.t
        self.assertNotEqual(t.page.js("term.modes.mouseTrackingMode"), "none", "tmux mouse mode is on")
        self.assertEqual(right_click(t), [True], "the browser's menu must be suppressed")
        self.assertTrue(wait_until(lambda: "\x1b[<2;" in t.sent(), 10), "and the right click still reaches tmux")
        self.assertEqual(right_click(t, shift=True), [False], "Shift+right click is the browser's")


@bs.browser_tests()
class RightClickWhenNothingHasTheMouse(Terminal):
    def test_the_browsers_menu_is_kept(self):
        t = self.t
        t.tmux("set", "-g", "mouse", "off")
        self.assertTrue(t.page.wait_js("term.modes.mouseTrackingMode === 'none'", 10), "the mouse is still captured")
        self.assertEqual(right_click(t), [False], "a plain shell keeps the browser menu (copy/paste)")


@bs.browser_tests()
class OptOuts(Terminal):
    CONF = "ctrlVPaste=false\nctrlCCopy=false\n"

    def test_ctrl_v_stays_a_control_character(self):
        t = self.t
        t.set_clipboard("PASTE-ME-42")
        t.page.ctrl_key("v")
        self.assertTrue(wait_until(lambda: "\x16" in t.sent(), 10), t.sent())
        self.assertNotIn("PASTE-ME-42", t.sent())

    def test_ctrl_c_always_interrupts(self):
        t = self.t
        self.say("echo COPY-ME-NOW")
        self.assertTrue(t.wait_line("COPY-ME-NOW"))
        t.set_clipboard("BEFORE")
        self.select("COPY-ME-NOW")
        t.page.ctrl_key("c")
        self.assertTrue(wait_until(lambda: "\x03" in t.sent(), 10), t.sent())
        self.assertEqual(t.clipboard(), "BEFORE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
