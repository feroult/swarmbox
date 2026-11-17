#!/usr/bin/env python3
"""The controls strip of the web terminal page in a real browser (container/web/ttyd-clipboard.js part 2 and ttyd-style.css): Chromium + the real ttyd + a
real tmux. Its settings, its key notation and its script without a browser are in tests/fast/test_web_strip_script.py.

The strip is checked by bounding boxes at several viewports (desktop, phone portrait and landscape with touch, tablet): it never covers the last row of the
terminal, the tmux window has exactly the rows xterm shows, the buttons are at least 44 px, an addon control sits in the strip, every key button delivers
its bytes to a pane running `cat -vT` (by mouse and by touch), the Panel button runs the binding of the sysop panel of container/config/tmux.conf, the
settings show and hide the strip, a note fits and goes away, and the keyboard of a phone (visualViewport) moves the strip with it.
SWARMBOX_TEST_SHOTS=<dir> also saves a screenshot at the end of each geometry check.

Run in a container (sh dev/test-slow.sh): SWARMBOX_TEST_REAL_TMUX=1 python3 tests/slow/test_web_strip.py
"""
import base64
import json
import time
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import browser_support as bs  # noqa: E402
from helpers import ROOT  # noqa: E402
from waiting import wait_until  # noqa: E402

TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
SHOTS = os.environ.get("SWARMBOX_TEST_SHOTS", "")
RAW_CAT = "stty raw -echo; exec cat -vT"   # a pane that shows, in caret notation, the bytes tmux hands it
BARE_TMUX = "set -g mouse on\nset -g status-right '%H:%M'\n"
DEFAULT_LABELS = ["Esc", "Tab", "^C", "\u2191", "\u2193", "\u2190", "\u2192", "Panel", "Allow", "Cancel"]
KEY_CARETS = [("Esc", "^["), ("Tab", "^I"), ("^C", "^C"), ("\u2191", "^[[A"), ("\u2193", "^[[B"), ("\u2190", "^[[D"), ("\u2192", "^[[C")]

VIEWPORTS = {  # name: (width, height, touch)
    "desktop": (1280, 800, False),
    "phone-portrait": (390, 844, True),
    "phone-landscape": (844, 390, True),
    "tablet": (820, 1180, True),
}

GEO = """(() => {
  const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, w: b.width, h: b.height}; };
  const q = s => document.querySelector(s);
  return {win: [innerWidth, innerHeight], docw: document.documentElement.scrollWidth, strip: r(q('#swarmbox-strip')),
          stripShown: !!q('#swarmbox-strip') && !q('#swarmbox-strip').hidden, container: r(q('#terminal-container')), screen: r(q('.xterm-screen')),
          rows: term.rows, cols: term.cols,
          keys: Array.from(document.querySelectorAll('#swarmbox-strip .sb-key')).map(e => Object.assign({t: e.textContent, cls: e.className}, r(e))),
          addons: Array.from(document.querySelectorAll('#swarmbox-strip .sb-addon')).map(e => Object.assign({id: e.id}, r(e))),
          keysShown: !!q('#swarmbox-strip .sb-keys') && !q('#swarmbox-strip .sb-keys').hidden, coarse: matchMedia('(pointer: coarse)').matches};
})()"""

CHROMIUM = None


def setUpModule():
    global CHROMIUM
    if bs.REAL and bs.CHROMIUM:
        CHROMIUM = bs.Chromium()


def tearDownModule():
    if CHROMIUM:
        CHROMIUM.close()


class StripCase(unittest.TestCase):
    """The helpers: open a terminal, measure, press a button."""

    def open(self, conf="", viewport="desktop", command=RAW_CAT, tmux_conf=BARE_TMUX, **kw):
        term = bs.WebTerminal(CHROMIUM, conf=conf, tmux_conf=tmux_conf, command=command, viewport=VIEWPORTS[viewport], **kw)
        self.addCleanup(term.close)
        self.use(term)
        if viewport.startswith("phone"):      # the letters of a phone follow the width: wait for that, or a measure taken before it is of a terminal that is about to change
            self.assertTrue(wait_until(lambda: term.page.js("window.term && window.term.options.fontSize") <= 14, 10, 0.05), "the phone font was not applied")
            term.page.js("window.dispatchEvent(new Event('resize'))")
        return term

    def use(self, term):
        self.t, self.page = term, term.page

    def geo(self, until=None):
        """The geometry of the page once it has settled: the terminal is refitted (it ends above the strip, or at the window's end without one)
        and, with `until`, until(g) is true. The last measure when the time is up: the assertions that follow say what is wrong."""
        last = {}

        def get():
            last.update(self.page.js(GEO))
            end = last["strip"]["top"] if last["stripShown"] else last["win"][1]
            return last["screen"]["bottom"] <= end + 0.5 and last["container"]["bottom"] <= end + 0.5 and (until is None or until(last))
        wait_until(get, 10, 0.05)
        return dict(last)

    def assert_nothing_covered(self, g, strip_expected=True):
        """The strip is outside the terminal: bounding boxes, and tmux has exactly the rows xterm shows."""
        self.assertEqual(g["stripShown"], strip_expected, g)
        self.assertLessEqual(g["docw"], g["win"][0], "no horizontal page scroll")
        c, s = g["container"], g["strip"]
        self.assertLessEqual(c["bottom"], g["win"][1] + 0.5)
        if strip_expected:
            self.assertLessEqual(c["bottom"], s["top"] + 0.5, "the terminal container ends where the strip begins")
            self.assertLessEqual(g["screen"]["bottom"], s["top"] + 0.5, "the last row of the terminal is above the strip")
            self.assertLessEqual(s["bottom"], g["win"][1] + 0.5, "the strip is inside the window")
            self.assertGreaterEqual(s["left"], 0)
            self.assertLessEqual(s["right"], g["win"][0] + 0.5)
        heights = wait_until(lambda: self.t.tmux("list-clients", "-F", "#{client_height}").split()[:1] == [str(g["rows"])], 10, 0.05)
        self.assertTrue(heights, "tmux sees %s rows, xterm shows %d: the smaller window" % (self.t.tmux("list-clients", "-F", "#{client_height}").strip(), g["rows"]))

    def assert_buttons(self, g, labels=DEFAULT_LABELS):
        """Every key button and addon control is at least 44 px (40 px on a touch screen: the phone strip is tighter so ten keys take two short rows),
        inside the strip and the window, and none overlaps the control."""
        min_h = 40 if g["coarse"] else 44
        self.assertTrue(g["keysShown"])
        self.assertEqual([k["t"] for k in g["keys"]], labels)
        for k in g["keys"] + g["addons"]:
            self.assertGreaterEqual(k["w"], min_h - 0.01, k)
            self.assertGreaterEqual(k["h"], min_h - 0.01, k)
            self.assertTrue(g["strip"]["top"] <= k["top"] and k["bottom"] <= g["strip"]["bottom"], "inside the strip: %r" % k)
            self.assertGreaterEqual(k["left"], 0)
            self.assertLessEqual(k["right"], g["win"][0] + 0.5, "a button off the screen: %r" % k)
        for mic in g["addons"]:
            for k in g["keys"]:
                self.assertFalse(k["left"] < mic["right"] and mic["left"] < k["right"] and k["top"] < mic["bottom"] and mic["top"] < k["bottom"], "keys and control overlap")

    def shot(self, name):
        if SHOTS:
            with open(os.path.join(SHOTS, name + ".png"), "wb") as f:
                f.write(base64.b64decode(self.page.call("Page.captureScreenshot", format="png")["data"]))

    def center(self, label):
        labels = [k["t"] for k in self.page.js(GEO)["keys"]]
        return self.page.js("(() => { const b = document.querySelectorAll('#swarmbox-strip .sb-key')[%d].getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()"
                            % labels.index(label))

    def press(self, label, touch, until=None, within=3):
        """Tap a key button (by touch or mouse); with `until`, keep it down until the condition is true: a held arrow repeats."""
        x, y = self.center(label)
        if touch:
            self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        else:
            self.page.mouse("mouseMoved", x, y)
            self.page.mouse("mousePressed", x, y)
        if until:
            # the script waits 420 ms, then repeats every 70 ms: a delay grown tenfold must fail, a loaded machine has seconds to spare
            self.assertTrue(wait_until(until, within, 0.05), "the held button did not repeat within %s s" % within)
        if touch:
            self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            self.page.mouse("mouseReleased", x, y)

    def wait_pane(self, want):
        return wait_until(lambda: want in self.t.pane_text(), 10, 0.05)

    def assert_keys_deliver_their_bytes(self, touch):
        self.t.tmux("respawn-pane", "-k", "-t", "t:", RAW_CAT)
        self.assertTrue(wait_until(lambda: self.t.pane_text() == "", 10, 0.05))
        total = ""
        for label, caret in KEY_CARETS:
            self.press(label, touch)
            total += caret
            self.assertTrue(self.wait_pane(total), "after %s the pane shows %r, wanted %r" % (label, self.t.pane_text(), total))
            self.assertEqual(self.t.pane_text().replace(" ", ""), total)
        # the terminal kept the focus: pressing a button must not steal it (nor close the on-screen keyboard)
        self.assertTrue(self.page.js("document.activeElement && document.activeElement.classList.contains('xterm-helper-textarea')"), "the focus stayed in the terminal")


@bs.browser_tests()
class Desktop(StripCase):
    def test_a_microphone_alone_floats_in_the_top_right_corner_and_takes_no_space(self):
        self.open()
        cls = "document.documentElement.classList.contains(%r)"
        win = VIEWPORTS["desktop"]
        self.assertFalse(self.page.js(cls % "swarmbox-strip-float"))
        self.assertAlmostEqual(self.geo()["container"]["bottom"], win[1], delta=1, msg="the terminal has the whole window as before")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', label: 'mic'})")   # what an addon does
        self.assertTrue(wait_until(lambda: self.page.js(cls % "swarmbox-strip-float"), 10, 0.05))
        self.assertFalse(self.page.js(cls % "swarmbox-strip-on"), "no bar: the layout is not a column")
        g = self.geo()
        self.assertAlmostEqual(g["container"]["bottom"], win[1], delta=1, msg="the terminal keeps the whole window, nothing below it")
        self.assertAlmostEqual(g["container"]["right"], win[0], delta=1)
        p = g["addons"][0]
        self.assertGreaterEqual(min(p["w"], p["h"]), 44)
        self.assertGreater(p["left"], win[0] * 0.8, "at the right")
        self.assertLess(p["top"], 40, "at the top")
        self.assertLessEqual(p["right"], win[0])
        self.shot("desktop-addon-control")
        self.page.js("swarmboxStrip.remove('demo-mic')")
        self.assertTrue(wait_until(lambda: not self.page.js(cls % "swarmbox-strip-float"), 10, 0.05), "with its last control gone nothing is left")

    def test_strip_on_shows_the_default_keys_with_a_control_and_every_key_delivers_its_bytes_and_an_arrow_repeats_when_held(self):
        self.open(conf="strip=on\n")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', order: 10})")
        g = self.geo(lambda g: g["stripShown"] and g["keysShown"] and g["addons"])
        self.assert_nothing_covered(g)
        self.assert_buttons(g)
        self.assertIsNotNone(self.page.js("window.__swarmboxClipboard"), "the clipboard bridge is intact with the strip")
        # Allow and Cancel are the two coloured answers to the sysop; the other keys are plain
        classes = {k["t"]: k["cls"].split() for k in g["keys"]}
        self.assertIn("sb-yes", classes["Allow"])
        self.assertIn("sb-no", classes["Cancel"])
        self.assertEqual([t for t, c in classes.items() if "sb-yes" in c or "sb-no" in c], ["Allow", "Cancel"])
        self.shot("desktop-keys-and-control")
        self.assert_keys_deliver_their_bytes(touch=False)
        self.t.tmux("respawn-pane", "-k", "-t", "t:", RAW_CAT)   # one tap is one key; a held arrow repeats
        self.assertTrue(wait_until(lambda: self.t.pane_text() == "", 10, 0.05))
        self.press("\u2193", touch=False)
        self.assertTrue(self.wait_pane("^[[B"))
        self.assertEqual(self.t.pane_text(), "^[[B", "one tap, one key")
        self.press("\u2192", touch=False, until=lambda: self.t.pane_text().count("^[[C") >= 5)

    def test_listed_keys_show_the_strip_on_desktop_and_a_button_types_its_keys(self):
        self.open(conf="stripKeys=Esc=Escape, Hi=h i\n")
        g = self.geo(lambda g: g["stripShown"])
        self.assert_nothing_covered(g)
        self.assertEqual([k["t"] for k in g["keys"]], ["Esc", "Hi"])
        self.press("Hi", touch=False)
        self.assertTrue(self.wait_pane("hi"), self.t.pane_text())


@bs.browser_tests()
class Phone(StripCase):
    """One phone (390 x 844, touch, strip on by itself) with an addon control: geometry, the keys by touch, the note, then the phone is turned and a
    tablet is made of it. Each test leaves the page as it found it."""

    @classmethod
    def setUpClass(cls):
        cls.term = bs.WebTerminal(CHROMIUM, command=RAW_CAT, tmux_conf=BARE_TMUX, viewport=VIEWPORTS["phone-portrait"])
        cls.term.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', order: 10})")
        assert wait_until(lambda: cls.term.page.js("window.term && window.term.options.fontSize") <= 14, 10, 0.05), "the phone font was not applied"
        cls.term.page.js("window.dispatchEvent(new Event('resize'))")
        time.sleep(0.5)       # the terminal is refitted to the phone font before any test measures it

    @classmethod
    def tearDownClass(cls):
        cls.term.close()

    def setUp(self):
        self.use(self.term)
        self.page.js("swarmboxStrip.note('')")

    def turn(self, name):
        w, h, touch = VIEWPORTS[name]
        self.page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2, mobile=True)
        return self.geo(lambda g: g["win"] == [w, h] and g["stripShown"])

    def test_portrait_the_strip_is_slim_and_covers_nothing(self):
        g = self.turn("phone-portrait")
        self.assertTrue(g["coarse"])
        self.assert_nothing_covered(g)
        self.assert_buttons(g)
        self.assertLess(g["strip"]["h"], 844 * 0.2)
        self.shot("phone-portrait")

    def test_the_keys_deliver_their_bytes_by_touch(self):
        self.turn("phone-portrait")
        self.assert_keys_deliver_their_bytes(touch=True)

    def test_landscape_is_one_small_row_and_the_status_bar_clock_is_on_screen(self):
        try:
            g = self.turn("phone-landscape")
            self.assert_nothing_covered(g)
            self.assert_buttons(g)
            self.assertLessEqual(g["strip"]["h"], 64, "a slim strip: %r" % g["strip"])
            self.assertLess(g["strip"]["h"], 390 * 0.17)
            self.assertEqual(len({round(k["top"]) for k in g["keys"] + g["addons"]}), 1, "a single row")
            self.assertGreater(g["rows"], 8)
            last = "(() => { const b = term.buffer.active; const l = b.getLine(b.viewportY + term.rows - 1); return l ? l.translateToString(true) : ''; })()"
            self.assertTrue(self.page.wait_js("/\\d\\d:\\d\\d\\s*$/.test(%s)" % last, 10), "the status bar and its clock are in the last row of the terminal")
            self.shot("phone-landscape")
        finally:
            self.turn("phone-portrait")

    def test_a_tablet_gets_the_same_strip(self):
        try:
            g = self.turn("tablet")
            self.assert_nothing_covered(g)
            self.assert_buttons(g)
            self.shot("tablet")
        finally:
            self.turn("phone-portrait")

    NOTE = ("(() => { const n = document.querySelector('#swarmbox-strip .sb-note'); const m = document.getElementById('demo-mic').getBoundingClientRect();"
            " const b = n.getBoundingClientRect(); return {hidden: n.hidden, text: n.textContent, tone: n.dataset.tone, right: b.right, micLeft: m.left}; })()")

    def test_a_note_covers_the_keys_but_not_the_addon_controls_never_resizes_the_strip_and_a_tap_dismisses_it(self):
        before = self.geo()
        self.page.js("swarmboxStrip.note('Nobody is listening', 'warn')")
        n = self.page.js(self.NOTE)
        self.assertEqual((n["hidden"], n["text"], n["tone"]), (False, "Nobody is listening", "warn"))
        self.assertLessEqual(n["right"], n["micLeft"] + 0.5, "the sentence ends where the control begins")
        after = self.geo()
        self.assertEqual(before["strip"], after["strip"], "a sentence never changes the size of the strip, so the terminal is not refitted")
        self.assertEqual(before["rows"], after["rows"])
        self.shot("phone-portrait-note")
        self.page.js("document.querySelector('#swarmbox-strip .sb-note').click()")
        self.assertTrue(self.page.js("document.querySelector('#swarmbox-strip .sb-note').hidden"), "a tap dismisses it")

    def test_the_sentences_of_the_voice_addon_are_read_whole_in_two_lines_and_a_note_nobody_clears_goes_away(self):
        before = self.geo()
        for text in ("Microphone blocked. Allow it in the site settings.", "The speech recognizer is busy: try again in a moment.",
                     "The voice service is restarting: try again in a few seconds.", "The voice service is slow: try again in a moment."):
            self.page.js("swarmboxStrip.note(%s, 'error')" % json.dumps(text))
            m = self.page.js("(() => { const n = document.querySelector('#swarmbox-strip .sb-note'); const t = n.firstChild;"
                             " return {cut: t.scrollHeight > t.clientHeight + 1, h: t.getBoundingClientRect().height, line: parseFloat(getComputedStyle(n).lineHeight), full: n.title}; })()")
            self.assertFalse(m["cut"], "%r is cut: %r" % (text, m))
            self.assertLessEqual(m["h"], 2 * m["line"] + 1, text)
            self.assertEqual(m["full"], text, "the whole text is also the tooltip")
            self.assertEqual(self.geo()["strip"], before["strip"], "the strip did not grow")
        # the host ends a note that nobody clears (12 s for a tone): the clock is shortened here, its length is read back
        self.page.js("window.__t = []; const st = window.setTimeout; window.setTimeout = (f, ms, ...a) => { window.__t.push(ms); return st(f, ms > 1000 ? 50 : ms, ...a); }")
        self.page.js("swarmboxStrip.note('hello', 'warn')")
        self.assertTrue(self.page.wait_js("document.querySelector('#swarmbox-strip .sb-note').hidden", 10), "the host did not end it")
        self.assertIn(12000, self.page.js("window.__t"))


@bs.browser_tests()
class Settings(StripCase):
    def test_strip_off_wins_over_touch_and_over_an_addon_control(self):
        self.open(conf="strip=off\n", viewport="phone-portrait")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'x'})")
        g = self.geo()
        self.assertTrue(g["coarse"])
        self.assertFalse(g["stripShown"])
        self.assertAlmostEqual(g["container"]["bottom"], g["win"][1], delta=1)

    def test_the_keyboard_of_a_phone_moves_the_strip_above_it(self):
        fake = """(() => { const l = {}; const vv = {get height() { return this._h === undefined ? innerHeight : this._h; }, set height(v) { this._h = v; }, offsetTop: 0, width: innerWidth,
          addEventListener(t, f) { (l[t] = l[t] || []).push(f); }, fire() { for (const t of ['resize', 'scroll']) (l[t] || []).forEach(f => f()); }};
          Object.defineProperty(window, 'visualViewport', {value: vv}); window.__vv = vv; })()"""
        self.open(conf="strip=on\n", viewport="phone-portrait", init_script=fake)
        g0 = self.geo(lambda g: g["stripShown"] and self.page.js("window.term.options.fontSize") <= 14)     # the phone font (13 px) is in place
        self.page.js("__vv.height = 500; __vv.fire()")
        g = self.geo(lambda g: abs(g["strip"]["bottom"] - 500) <= 1 and g["rows"] < g0["rows"])
        self.assertAlmostEqual(g["strip"]["bottom"], 500, delta=1, msg="the strip sits on the keyboard")
        self.assertLessEqual(g["container"]["bottom"], g["strip"]["top"] + 0.5)
        self.assertLess(g["rows"], g0["rows"], "the terminal got smaller and was refitted")
        self.assert_nothing_covered(dict(g, win=[g["win"][0], 500]))
        self.shot("phone-portrait-keyboard-open")
        self.page.js("__vv.height = innerHeight; __vv.fire()")
        g2 = self.geo(lambda g: abs(g["strip"]["bottom"] - 844) <= 1 and g["rows"] == g0["rows"])
        self.assertAlmostEqual(g2["strip"]["bottom"], 844, delta=1)
        self.assertEqual(g2["rows"], g0["rows"])

    def test_the_panel_button_runs_the_sysop_panel_binding_of_the_image_and_toggles(self):
        with open(TMUX_CONF, encoding="utf-8") as f:
            conf = f.read()
        self.assertIn("bind S if-shell -b", conf, "the binding the Panel button reaches")
        self.assertIn("swarmbox-sysop dock toggle", conf)
        self.assertIn("set -g prefix C-a", conf.replace("unbind C-b\n", ""))
        fake = tempfile.mkdtemp(prefix="swarmbox-test-sysopbin-")
        self.addCleanup(lambda: __import__("shutil").rmtree(fake, True))
        log = os.path.join(fake, "sysop.log")
        with open(os.path.join(fake, "swarmbox-sysop"), "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "%s"\n' % log)
        os.chmod(os.path.join(fake, "swarmbox-sysop"), 0o755)
        self.open(conf="strip=on\n", viewport="phone-portrait", tmux_conf="source-file %s\n" % TMUX_CONF, command="exec sleep 600",
                  env={"PATH": fake + os.pathsep + os.environ["PATH"]})
        self.geo(lambda g: g["stripShown"] and g["keysShown"])
        self.assertEqual(self.t.tmux("show", "-gv", "prefix").strip(), "C-a")
        self.assertFalse(os.path.exists(log))

        def calls():
            if not os.path.exists(log):
                return []
            with open(log) as f:
                return f.read().splitlines()
        self.press("Panel", touch=True)
        self.assertTrue(wait_until(lambda: len(calls()) == 1, 10, 0.05), "the binding did not run")
        self.assertTrue(calls()[0].startswith("dock toggle --socket "), calls())
        self.assertIn("--window @", calls()[0])
        self.press("Panel", touch=True)   # and again: toggles
        self.assertTrue(wait_until(lambda: len(calls()) == 2, 10, 0.05), calls())
        self.shot("phone-portrait-panel-pressed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
