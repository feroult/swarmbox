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
DEFAULT_LABELS = ["Allow", "Cancel", "Esc", "Tab", "^C", "Panel", "\u2190", "\u2191", "\u2193", "\u2192"]
KEY_CARETS = [("Esc", "^["), ("Tab", "^I"), ("^C", "^C"), ("\u2191", "^[[A"), ("\u2193", "^[[B"), ("\u2190", "^[[D"), ("\u2192", "^[[C")]

VIEWPORTS = {  # name: (width, height, touch)
    "desktop": (1280, 800, False),
    "phone-portrait": (390, 844, True),
    "phone-landscape": (844, 390, True),
    "tablet": (820, 1180, True),
    "small-phone": (360, 740, True),
    "pixel": (412, 915, True, 2.625),      # a Pixel in the device mode of Chrome: the device pixel ratio is not a whole number
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
            self.assertTrue(wait_until(lambda: term.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05), "the phone font was not applied")
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
    def test_a_narrow_window_with_a_mouse_gets_the_phone_letters_and_a_wide_one_keeps_its_size(self):
        """the device mode of a desktop browser (a responsive window) has a mouse, not a touch screen: the width decides"""
        self.open()
        fs = "window.term.options.fontSize"
        base = self.page.js(fs)
        self.assertGreaterEqual(base, 13, "a desktop window keeps the configured size (13 is ttyd's own without a conf)")
        self.page.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=False)
        self.assertTrue(wait_until(lambda: self.page.js(fs) <= 11, 10, 0.05), "a window 390 px wide gets the phone size: %r" % self.page.js(fs))
        self.assertGreaterEqual(self.geo(lambda g: g["cols"] >= 50)["cols"], 50)
        self.page.call("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
        self.assertTrue(wait_until(lambda: self.page.js(fs) == base, 10, 0.05), "and it goes back when the window is wide again (base %r): %r" % (base, self.page.js("[term.options.fontSize, innerWidth, document.documentElement.clientWidth, matchMedia('(pointer: coarse)').matches]")))


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
        assert wait_until(lambda: cls.term.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05), "the phone font was not applied"
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

    def test_the_phone_letters_leave_no_column_cut_off_at_the_right_and_fill_the_width(self):
        """seen on a phone: after the size changed the terminal was refitted with the old letter width, and the last characters of every row fell off the right edge"""
        g = self.geo(lambda g: g["cols"] >= 55)
        self.assertGreaterEqual(g["cols"], 55, "a phone held upright shows about 65 columns (it was 29 at 21 px)")
        self.assertLessEqual(g["cols"], 90)
        self.assertLessEqual(g["screen"]["right"], g["win"][0] - 8, "the last column ends before the right edge (the padding of the page is 10 px)")
        self.assertGreaterEqual(g["screen"]["right"], g["win"][0] - 30, "and not much before it: the width is used")
        self.assertTrue(wait_until(lambda: self.t.tmux("list-clients", "-F", "#{client_width}").split()[:1] == [str(g["cols"])], 10, 0.05),
                        "tmux has the columns xterm shows: %s" % self.t.tmux("list-clients", "-F", "#{client_width}").strip())

    def test_the_columns_can_be_tried_in_the_console_kept_and_forgotten(self):
        self.assertTrue(wait_until(lambda: self.page.js("term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(0.6)
        auto = self.page.js("term.options.fontSize")
        self.page.js("swarmboxStrip.setColumns(48)")
        self.assertTrue(wait_until(lambda: self.page.js("term.options.fontSize") > auto + 2, 10, 0.05), "fewer columns asked: bigger letters")
        self.assertEqual(self.page.js("JSON.parse(localStorage.getItem('swarmbox.columns')).up"), 48, "kept in this browser")
        self.page.js("swarmboxStrip.setColumns()")
        self.assertIsNone(self.page.js("localStorage.getItem('swarmbox.columns')"))
        self.assertTrue(wait_until(lambda: self.page.js("term.options.fontSize") == auto, 10, 0.05), "and the default again")

    def test_a_size_set_by_hand_stays_through_resizes_and_setcolumns_makes_the_page_fit_again(self):
        """seen: the same value typed in the console sometimes took and sometimes went back, because the page fitted again at every resize"""
        self.assertTrue(wait_until(lambda: self.page.js("term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(3.3)      # the page has settled: ttyd's own fontSize is long applied
        for size in (9, 5, 12, 7):
            self.page.js("term.options.fontSize = %d" % size)
            for _ in range(3):
                self.page.js("window.dispatchEvent(new Event('resize'))")
                time.sleep(0.4)
            self.assertEqual(self.page.js("term.options.fontSize"), size, "the size set by hand is left alone")
        self.page.js("swarmboxStrip.setColumns()")
        self.assertTrue(wait_until(lambda: self.page.js("term.options.fontSize") >= 9, 10, 0.05), "and the page fits again (7 was the last size set by hand)")
        self.assertGreaterEqual(self.geo(lambda g: g["cols"] >= 55)["cols"], 55)

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
        g0 = self.geo(lambda g: g["stripShown"] and self.page.js("window.term.options.fontSize") <= 12)     # the phone font (11 px) is in place
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


@bs.browser_tests()
class OtherClient(StripCase):
    def test_a_page_that_is_looked_at_takes_the_window_back_from_a_wider_client(self):
        """seen on a phone: the terminal of the host (193 columns) got focus after the page and tmux kept the window at 193 columns: lines ran behind the right edge and
        the prompt was out of sight. The page sends the focus-in report when it is looked at, and the window follows it again"""
        import fcntl
        import pty
        import struct
        import termios
        self.open(viewport="phone-portrait", tmux_conf=BARE_TMUX + "set -g focus-events on\n")
        g = self.geo(lambda g: g["cols"] >= 55)
        cols = g["cols"]
        win = lambda: self.t.tmux("display-message", "-p", "-t", "t:", "#{window_width}")
        self.assertTrue(wait_until(lambda: win().strip() == str(cols), 10, 0.05), "the page owns the window: %r" % win())
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.update(self.t.env)
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-L", self.t.sock, "attach", "-t", "t"])
        self.addCleanup(lambda: (os.close(fd), os.kill(pid, 9), os.waitpid(pid, 0)))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 99, 193, 0, 0))
        time.sleep(0.5)
        os.write(fd, b"\x1b[I")          # the host terminal got focus
        self.assertTrue(wait_until(lambda: win().strip() == "193", 10, 0.05), "the wide client took the window: %r" % win())
        self.page.js("window.dispatchEvent(new Event('focus'))")     # the page is looked at again
        self.assertTrue(wait_until(lambda: win().strip() == str(cols), 10, 0.05), "the page took the window back: %r (page %d)" % (win(), cols))
        os.write(fd, b"\x1b[I")          # the host terminal takes it again while the page still has the focus: the page keeps the size by itself
        self.assertTrue(wait_until(lambda: win().strip() == "193", 5, 0.05), "the wide client took the window again: %r" % win())
        self.assertTrue(wait_until(lambda: win().strip() == str(cols), 8, 0.1), "a page that has the focus takes it back with no event: %r (page %d)" % (win(), cols))


@bs.browser_tests()
class FontFromTheStart(StripCase):
    def test_a_phone_gets_its_font_in_the_settings_message_and_the_terminal_never_changes_size_after_it_opens(self):
        """seen on a phone: tmux was told 28 x 112 and then 123 x 99 at every refresh, because the font was changed after ttyd had applied its own: the size now
        arrives already right in the settings message of ttyd, so the terminal is measured once"""
        self.open(viewport="phone-portrait", command="bash --norc", init_script="window.__sizes = []; ")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(3.0)
        import re
        sizes = [(int(c), int(r)) for c, r in re.findall(r'"columns":(\d+),"rows":(\d+)', self.t.sent())]
        self.assertEqual(sizes[-1][0], self.page.js("term.cols"), "the last size told to tmux is the size of the terminal: %r" % (sizes,))
        self.assertLessEqual(len(sizes), 3, "the two sizes of ttyd before its settings, then the final one: %r" % (sizes,))
        self.assertGreater(sizes[-1][0], sizes[-2][0] + 5, "no size with the width of a scrollbar between them (58 columns, then 61, was the blink): %r" % (sizes,))
        self.assertEqual(self.page.js("swarmboxStrip.prefs"), [1, 1], "the settings message of ttyd was seen and rewritten once")
        self.assertEqual(self.page.js("document.querySelectorAll('.xterm-screen canvas').length"), 0, "and the renderer is the DOM one on a phone")
        self.assertEqual(self.page.js("swarmboxStrip.fontSets"), 0, "the page never had to change the font after ttyd applied its settings")
        self.assertLessEqual(self.page.js("term.options.fontSize"), 12)
        self.assertGreaterEqual(self.page.js("term.cols"), 55)
        self.assertEqual(self.t.tmux("list-clients", "-F", "#{client_width}").strip(), str(self.page.js("term.cols")))

    def test_a_wide_window_keeps_the_size_of_the_settings(self):
        self.open(command="bash --norc")
        time.sleep(1.5)
        self.assertEqual(self.page.js("swarmboxStrip.fontSets"), 0)
        self.assertGreaterEqual(self.page.js("term.options.fontSize"), 13)
        self.assertEqual(self.page.js("document.querySelectorAll('.xterm-screen canvas').length"), 4, "a wide window keeps the canvas renderer of the box")


@bs.browser_tests()
class FractionalPixels(StripCase):
    def test_a_pixel_in_device_mode_gets_a_terminal_that_fits_its_width(self):
        """the device mode of Chrome emulates 2.625 device pixels per css pixel: the grid must still end at the screen"""
        self.open(viewport="pixel", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(2.0)
        g = self.geo(lambda g: g["cols"] >= 55)
        self.assertEqual(self.page.js("devicePixelRatio"), 2.625)
        self.assertLessEqual(g["screen"]["right"], g["win"][0] - 8)
        self.assertGreaterEqual(g["screen"]["right"], g["win"][0] - 30, "and the width is used")
        self.assertEqual(self.t.tmux("list-clients", "-F", "#{client_width}").strip(), str(g["cols"]))


@bs.browser_tests()
class Renderer(StripCase):
    def test_the_default_renderer_draws_the_letters_on_the_grid_after_the_phone_font_is_set(self):
        """seen on a phone: with ttyd's own renderer (webgl) the letters were drawn at twice the pitch of the grid, so the 123 columns did not fit the screen and the
        lines seemed not to wrap. A long line of known text must show its first and its last characters inside the screen"""
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.5)
        self.assertEqual(self.page.js("document.querySelectorAll('.xterm-screen canvas').length"), 0, "a phone gets the DOM renderer: no bitmap to be sized by a pixel ratio")
        self.assertTrue(self.page.js("!!document.querySelector('.xterm-rows')"))
        cols = self.geo(lambda g: g["cols"] >= 55)["cols"]
        self.t.type("echo %s\r" % ("0123456789" * (cols // 10 + 2) + "END"))
        self.assertTrue(self.t.wait_line("END", 10) or self.t.wait_screen("END", 10), "the end of the long line is in the terminal")
        self.assertTrue(self.t.wait_screen("0123456789", 10))
        # the pitch of the letters equals the pitch of the grid: ten characters of a row take ten cells (a row of M is as wide as `cols` cells)
        self.t.type("clear; printf '%%*s\\n' %d '' | tr ' ' M\r" % cols)
        self.assertTrue(self.t.wait_line("M" * cols, 10), "a row of M fills exactly the columns of the pane")
        g = self.geo()
        shot = base64.b64decode(self.page.call("Page.captureScreenshot", format="png")["data"])
        if SHOTS:
            with open(os.path.join(SHOTS, "phone-renderer.png"), "wb") as f:
                f.write(shot)
        self.assertEqual(self.page.js("term.options.fontSize") <= 12, True)
        self.assertLessEqual(g["screen"]["right"], g["win"][0] - 8)


@bs.browser_tests()
class Answers(StripCase):
    def test_allow_and_cancel_are_on_only_when_the_sysop_waits_for_them(self):
        """Allow and Cancel read the head of the sysop panel off the screen: `SYSOP  allow?` both on, `SYSOP  sending` only Cancel, `SYSOP  working` Cancel
        (it stops), nothing: both off and a tap types nothing"""
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        off = lambda: self.page.js("(() => { const q = c => document.querySelector('#swarmbox-strip .sb-' + c); return [q('yes').dataset.off, q('no').dataset.off, q('yes').getAttribute('aria-disabled'), document.getElementById('swarmbox-strip').dataset.sysop]; })()")
        self.assertTrue(wait_until(lambda: off() == ["1", "1", "true", "none"], 5, 0.1), "nothing to answer: both off %r" % (off(),))
        self.t.clear_sent()
        self.page.js("document.querySelector('#swarmbox-strip .sb-yes').dispatchEvent(new PointerEvent('pointerdown', {button: 0, pointerId: 1, bubbles: true})); "
                     "document.querySelector('#swarmbox-strip .sb-yes').dispatchEvent(new PointerEvent('pointerup', {button: 0, pointerId: 1, bubbles: true}))")
        time.sleep(0.4)
        self.assertEqual(self.t.sent().count("\x01"), 0, "a tap on an Allow that is off types nothing: %r" % self.t.sent())
        for head, want in (("SYSOP  allow? high risk", ["0", "0", "false", "allow?"]), ("SYSOP  sending in 3 s", ["1", "0", "true", "sending"]), ("SYSOP  working", ["1", "0", "true", "working"])):
            self.t.type("clear; printf '\\033[1;38;2;167;139;250mSYSOP\\033[0m%%s\\n' '%s'\r" % head[len("SYSOP"):])
            self.assertTrue(wait_until(lambda: off() == want, 6, 0.1), "%r -> %r wanted %r" % (head, off(), want))
            if head.startswith("SYSOP  allow?"):
                self.shot("phone-portrait-allow-on")
        self.t.type("clear\r")
        self.assertTrue(wait_until(lambda: off() == ["1", "1", "true", "none"], 6, 0.1), "and off again when the panel is gone: %r" % (off(),))

    def test_the_words_of_the_panel_in_plain_text_do_not_count(self):
        """history that scrolling brings into view may say SYSOP  idle: only the bold violet word of the panel lights the switch"""
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        self.t.type("clear; echo 'SYSOP  working'\r")
        time.sleep(1.0)
        self.assertEqual(self.page.js("document.querySelector('#swarmbox-strip .sb-toggle').dataset.on"), "0")
        self.assertEqual(self.page.js("document.getElementById('swarmbox-strip').dataset.sysop"), "none")

    def test_the_panel_button_is_a_switch_that_says_whether_the_panel_is_up(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        on = lambda: self.page.js("(() => { const b = document.querySelector('#swarmbox-strip .sb-toggle'); return [b.textContent, b.dataset.on, b.getAttribute('aria-pressed'), getComputedStyle(b).borderRadius]; })()")
        self.assertTrue(wait_until(lambda: on()[1:3] == ["0", "false"], 5, 0.1), "no panel on the screen: the switch is off %r" % (on(),))
        self.assertEqual(on()[0], "Panel")
        self.assertGreaterEqual(float(on()[3].replace("px", "")), 20, "a pill, not a square key")
        self.t.type("clear; printf '\\033[1;38;2;167;139;250mSYSOP\\033[0m  idle\\n'\r")
        self.assertTrue(wait_until(lambda: on()[1:3] == ["1", "true"], 6, 0.1), "a panel (idle too) on the screen: the switch is on %r" % (on(),))
        self.shot("phone-portrait-panel-switch-on")

    def test_rows_of_block_characters_are_drawn_taller_in_the_dom_renderer_and_other_rows_are_not(self):
        """the banner of the box is made of block characters: in the DOM renderer a hairline of background cut across every letter between two rows"""
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("!!document.querySelector('.xterm-rows')"), 10, 0.05), "the DOM renderer")
        time.sleep(1.0)
        self.t.type("clear; printf '\\u2580\\u2584\\u2588\\n\\u2588\\u2580\\u2584\\nplain text row\\n'\r")
        blk = lambda: self.page.js("Array.from(document.querySelectorAll('.xterm-rows > div')).map((d, i) => [i, d.textContent.trim().slice(0, 3), d.classList.contains('sb-blk')]).filter(x => x[1] !== '')")
        self.assertTrue(wait_until(lambda: [x for x in blk() if x[1].startswith("\u2580") or x[1].startswith("\u2588")] != [], 8, 0.1), "the rows were drawn: %r" % (blk(),))
        time.sleep(0.5)
        rows = blk()
        for i, text, on in rows:
            if text[:1] in ("\u2580", "\u2588"):
                self.assertTrue(on, "a row of blocks is marked: %r" % (rows,))
            if text.startswith("pla"):
                self.assertFalse(on, "a row of plain text is not: %r" % (rows,))
        self.assertEqual(self.page.js("getComputedStyle(document.querySelector('.xterm-rows > div.sb-blk')).transform !== 'none'"), True)

    def test_the_keys_are_a_grid_of_five_columns_on_any_phone_width(self):
        """Allow over Cancel on the left, Esc Tab ^C Panel on top, the arrows under them: every edge of one row is the edge of a key in the other"""
        for vp in ("phone-portrait", "small-phone", "pixel"):
            term = self.open(viewport=vp, command="bash --norc")
            self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', order: 10})")      # the microphone takes 48 px of the width
            g = self.geo(lambda g: g["stripShown"] and g["keysShown"] and g["addons"])
            k = {x["t"]: x for x in g["keys"]}
            columns = [("Allow", "Cancel"), ("Esc", "\u2190"), ("Tab", "\u2191"), ("^C", "\u2193"), ("Panel", "\u2192")]
            for top, bottom in columns:
                self.assertAlmostEqual(k[top]["left"], k[bottom]["left"], delta=1.0, msg="%s: %s over %s, left edges %r" % (vp, top, bottom, (k[top], k[bottom])))
                self.assertAlmostEqual(k[top]["right"], k[bottom]["right"], delta=1.0, msg="%s: %s over %s, right edges" % (vp, top, bottom))
                self.assertGreater(k[bottom]["top"], k[top]["bottom"] - 1, "%s: %s is under %s" % (vp, bottom, top))
            for label in ("Allow", "Esc", "Tab", "^C", "Panel"):
                self.assertAlmostEqual(k[label]["top"], k["Allow"]["top"], delta=1.0, msg="%s: %s on the first row" % (vp, label))
            for label in ("Cancel", "\u2190", "\u2191", "\u2193", "\u2192"):
                self.assertAlmostEqual(k[label]["top"], k["Cancel"]["top"], delta=1.0, msg="%s: %s on the second row" % (vp, label))
            lefts = [k[t]["left"] for t, _ in columns]
            gaps = [round(lefts[i + 1] - lefts[i], 1) for i in range(4)]
            self.assertLessEqual(max(gaps) - min(gaps), 1.5, "%s: the columns are one width: %r" % (vp, gaps))
            texts = self.page.js("Array.from(document.querySelectorAll('#swarmbox-strip .sb-key')).map(b => [b.textContent, b.scrollWidth <= b.clientWidth + 1])")
            self.assertEqual([t for t, ok in texts if not ok], [], "%s: the labels fit their buttons" % vp)
            self.assertGreaterEqual(min(x["w"] for x in g["keys"]), 36, "%s: a thumb still hits every button" % vp)
            self.assertGreaterEqual(min(x["h"] for x in g["keys"]), 40)
            if vp == "small-phone":
                self.shot("small-phone-grid")
            term.close()

    def test_the_arrows_share_one_line_and_the_resize_box_of_ttyd_is_off(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        g = self.geo(lambda g: g["stripShown"] and g["keysShown"])
        arrows = [k for k in g["keys"] if k["t"] in ("\u2190", "\u2191", "\u2193", "\u2192")]
        self.assertEqual(len(arrows), 4)
        self.assertEqual(len({round(k["top"]) for k in arrows}), 1, "the four arrows are on one line: %r" % [(k["t"], k["top"]) for k in arrows])
        self.assertEqual(self.page.js("!!document.querySelector('.xterm-overlay') && getComputedStyle(document.querySelector('.xterm-overlay')).opacity !== '0'"), False,
                         "no box with the size of the terminal")

@bs.browser_tests()
class FingerScroll(StripCase):
    def test_dragging_a_finger_scrolls_the_history_of_tmux_and_a_tap_does_not(self):
        """on a phone the history could not be reached: a finger dragged over the terminal made no wheel event, which is what tmux scrolls on"""
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        self.t.type("clear; seq 1 400\r")
        self.assertTrue(self.t.wait_screen("400", 10), "the output is there")
        mode = lambda: self.t.tmux("display-message", "-p", "-t", "t:", "#{pane_in_mode} #{scroll_position}").split()

        def drag(y_from, y_to, steps=12, x=200):
            self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y_from}])
            for i in range(1, steps + 1):
                self.page.call("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": x, "y": y_from + (y_to - y_from) * i / steps}])
                time.sleep(0.02)
            self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        self.assertEqual(mode()[0], "0")
        drag(300, 500)      # a finger down: older text comes into view
        self.assertTrue(wait_until(lambda: mode()[0] == "1" and int(mode()[1]) > 0, 6, 0.1), "tmux is in copy mode, scrolled back: %r" % (mode(),))
        far = int(mode()[1])
        drag(300, 560)
        self.assertTrue(wait_until(lambda: int(mode()[1]) > far, 6, 0.1), "a longer drag goes further back: %r after %d" % (mode(), far))
        far = int(mode()[1])
        drag(560, 300)      # a finger up: back toward the present
        self.assertTrue(wait_until(lambda: int(mode()[1]) < far, 6, 0.1), "and the other way: %r from %d" % (mode(), far))

    def test_the_text_goes_further_than_the_finger(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        self.t.type("clear; seq 1 400\r")
        self.assertTrue(self.t.wait_screen("400", 10))
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 200, "y": 300}])
        for i in range(1, 11):
            self.page.call("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 200, "y": 300 + 10 * i}])
            time.sleep(0.02)
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        rowpx = self.page.js("window.term._core._renderService.dimensions.css.cell.height")
        self.assertTrue(wait_until(lambda: int(self.t.tmux("display-message", "-p", "-t", "t:", "#{scroll_position}").strip() or 0) > 0, 6, 0.1))
        time.sleep(0.5)
        got = int(self.t.tmux("display-message", "-p", "-t", "t:", "#{scroll_position}").strip())
        self.assertGreater(got, 1.3 * 100 / rowpx, "100 px of finger is %d lines of %.1f px: further than the finger" % (got, rowpx))

    def test_a_long_fast_drag_is_followed_to_the_end_even_if_the_finger_stops(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        self.t.type("clear; seq 1 3000\r")
        self.assertTrue(self.t.wait_screen("3000", 10))
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 200, "y": 100}])
        for i in range(1, 7):
            self.page.call("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 200, "y": 100 + 100 * i}])
            time.sleep(0.01)
        time.sleep(0.3)      # the finger rests at the bottom
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        rowpx = self.page.js("window.term._core._renderService.dimensions.css.cell.height")
        pos = lambda: int(self.t.tmux("display-message", "-p", "-t", "t:", "#{scroll_position}").strip() or 0)
        time.sleep(1.5)
        self.assertGreater(pos(), 600 / rowpx * 1.8, "600 px of finger at speed: the text got there, in pages (%d lines of %.1f px)" % (pos(), rowpx))

    def test_a_slow_drag_is_followed_line_by_line_and_not_in_jumps_of_five(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        self.assertTrue(wait_until(lambda: self.page.js("window.term && window.term.options.fontSize") <= 12, 10, 0.05))
        time.sleep(1.0)
        self.t.type("clear; seq 1 3000\r")
        self.assertTrue(self.t.wait_screen("3000", 10))
        pos = lambda: int(self.t.tmux("display-message", "-p", "-t", "t:", "#{scroll_position}").strip() or 0)
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 200, "y": 200}])
        seen = []
        for i in range(1, 41):
            self.page.call("Input.dispatchTouchEvent", type="touchMove", touchPoints=[{"x": 200, "y": 200 + 3 * i}])
            time.sleep(0.06)
            seen.append(pos())
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        steps = {b - a for a, b in zip(seen, seen[1:]) if b > a}
        self.assertTrue(any(s < 5 for s in steps), "the text moved by single lines at times, not only by 5: steps %r" % (sorted(steps),))
        self.assertGreater(seen[-1], 1.2 * 120 / self.page.js("window.term._core._renderService.dimensions.css.cell.height"), "and followed the finger: %r" % (seen,))

    def test_two_fingers_still_zoom_the_page(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        time.sleep(1.5)
        self.assertEqual(self.page.js("getComputedStyle(document.getElementById('terminal-container')).touchAction"), "pinch-zoom", "the browser keeps the pinch, the page takes the single finger")
        self.assertNotRegex(self.page.js("document.querySelector('meta[name=viewport]').content"), r"user-scalable|maximum-scale")
        # (a pinch itself cannot be made in this headless Chromium: the scale stays 1 even with touch-action auto, so the two properties above are what is checked)

    def test_a_tap_scrolls_nothing(self):
        self.open(viewport="phone-portrait", command="bash --norc")
        time.sleep(1.5)
        self.t.type("clear; seq 1 400\r")
        self.assertTrue(self.t.wait_screen("400", 10))
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": 200, "y": 300}])
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        time.sleep(0.5)
        self.assertEqual(self.t.tmux("display-message", "-p", "-t", "t:", "#{pane_in_mode}").strip(), "0", "a tap does not enter copy mode")


TITLES_TMUX = BARE_TMUX + """set -g set-titles on
set -g set-titles-string "#{?@sysop_line,#{@sysop_line},#S:#I:#W}"
"""
KEEP_SOCKETS = "(() => { const O = WebSocket; window.__ws = []; window.WebSocket = function (...a) { const s = new O(...a); window.__ws.push(s); return s; }; window.WebSocket.prototype = O.prototype; Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3}); })();"


@bs.browser_tests()
class Toast(StripCase):
    STATE = ("(() => { const s = document.getElementById('swarmbox-strip'), v = e => !!e && getComputedStyle(e).display !== 'none'; "
             "const t = s.querySelector('.sb-toast'), p = s.querySelector('.sb-sysop'); "
             "return [s.dataset.compact, v(s.querySelector('.sb-keys')), v(t), t ? t.textContent : null, p ? p.dataset.state : null, p ? p.dataset.on : null]; })()")

    def state(self):
        return self.page.js(self.STATE)

    def test_a_phone_with_a_sysop_shows_the_sysop_button_the_line_and_the_microphone_and_not_the_keys(self):
        self.open(viewport="phone-portrait", command="bash --norc", tmux_conf=TITLES_TMUX)
        time.sleep(1.0)
        self.assertEqual(self.state()[:3], ["0", True, False], "no sysop: the strip with the keys, as before: %r" % (self.state(),))
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:idle:")
        self.assertTrue(wait_until(lambda: self.state()[:3] == ["1", False, True], 6, 0.1), "a sysop, idle: the bar and no keys: %r" % (self.state(),))
        self.assertEqual(self.state()[4:], ["idle", "0"])
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:working:reads tab 1")
        self.assertTrue(wait_until(lambda: self.state()[3:5] == ["reads tab 1", "working"], 6, 0.1), "the line: %r" % (self.state(),))
        self.shot("phone-portrait-toast")
        self.t.clear_sent()
        self.page.js("document.querySelector('#swarmbox-strip .sb-sysop').click()")
        time.sleep(0.4)
        self.assertIn("0\x01S", self.t.sent(), "the Sysop button is the key of the panel: Ctrl+A S")
        self.t.clear_sent()
        self.page.js("document.querySelector('#swarmbox-strip .sb-toast').click()")
        time.sleep(0.3)
        self.assertNotIn("\x01S", self.t.sent(), "the line itself is not a button")
        self.page.js("document.querySelector('#swarmbox-strip .sb-keytoggle').click()")
        self.assertTrue(wait_until(lambda: self.state()[:3] == ["keys", True, True], 6, 0.1), "the keyboard button brings the row of keys above the bar: %r" % (self.state(),))
        row = self.page.js("Array.from(document.querySelectorAll('#swarmbox-strip .sb-keys .sb-btn')).filter(b => getComputedStyle(b).display !== 'none').map(b => [b.textContent.trim(), Math.round(b.getBoundingClientRect().top), Math.round(b.getBoundingClientRect().height)])")
        self.assertEqual([r[0] for r in row], ["Esc", "Tab", "^C", "\u2190", "\u2191", "\u2193", "\u2192"], "one slim row, no Allow, Cancel or Panel: %r" % (row,))
        self.assertEqual(len({r[1] for r in row}), 1, "all in one row: %r" % (row,))
        self.assertLessEqual(row[0][2], 38)
        self.shot("phone-portrait-toast-keys")
        self.page.js("document.querySelector('#swarmbox-strip .sb-keytoggle').click()")
        self.assertTrue(wait_until(lambda: self.state()[:3] == ["1", False, True], 6, 0.1), "and away again: %r" % (self.state(),))
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:allow?:run: rm -rf build")
        self.assertTrue(wait_until(lambda: self.state()[3:5] == ["run: rm -rf build", "allow?"], 6, 0.1), "%r" % (self.state(),))
        self.t.tmux("set-option", "-gu", "@sysop_line")
        self.assertTrue(wait_until(lambda: self.state()[:3] == ["0", True, False], 6, 0.1), "the sysop is gone: the keys are back: %r" % (self.state(),))

    def test_the_row_of_keys_opens_by_itself_when_the_panel_is_open_and_the_button_says_so(self):
        self.open(viewport="phone-portrait", command="bash --norc", tmux_conf=TITLES_TMUX)
        time.sleep(1.0)
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:idle:")
        self.assertTrue(wait_until(lambda: self.state()[:3] == ["1", False, True], 6, 0.1))
        self.t.type("clear; printf '\\033[1;38;2;167;139;250mSYSOP\\033[0m%s\\n' '  idle'\r")
        self.assertTrue(wait_until(lambda: self.state()[0] == "keys" and self.state()[5] == "1", 6, 0.1), "a panel on the screen: the keys and the button lit: %r" % (self.state(),))
        self.shot("phone-portrait-panel-open")
        self.t.type("clear\r")
        self.assertTrue(wait_until(lambda: self.state()[0] == "1" and self.state()[5] == "0", 6, 0.1), "no panel: back to the bar alone: %r" % (self.state(),))

    def test_the_page_is_black_with_the_name_until_the_first_screen(self):
        self.open(viewport="phone-portrait", command="bash --norc", tmux_conf=TITLES_TMUX,
                  init_script="document.addEventListener('DOMContentLoaded', () => { window.__splash = getComputedStyle(document.documentElement, '::before').content; });")
        self.assertEqual(self.page.js("window.__splash"), '"SwarmBox"', "the page starts with the name")
        self.assertTrue(wait_until(lambda: self.page.js("document.documentElement.classList.contains('swarmbox-ready')"), 10, 0.1), "and is ready once the terminal drew")
        self.assertEqual(self.page.js("getComputedStyle(document.documentElement, '::before').content"), "none")

    def test_a_line_that_was_there_before_the_page_opened_is_known_at_once(self):
        """tmux sends the title when a client attaches, before the terminal exists to hear it: the page reads it off the websocket"""
        self.open(viewport="phone-portrait", command="bash --norc", tmux_conf=TITLES_TMUX)
        time.sleep(1.0)
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:working:was already going")
        self.assertTrue(wait_until(lambda: self.page.js("document.getElementById('swarmbox-strip').dataset.compact") == "1", 6, 0.1))
        self.page.js("location.reload()")
        self.assertTrue(wait_until(lambda: self.page.js("document.getElementById('swarmbox-strip') && document.getElementById('swarmbox-strip').dataset.compact") == "1", 12, 0.2),
                        "after a reload the line is shown without waiting for a change")
        self.assertEqual(self.page.js("document.querySelector('#swarmbox-strip .sb-toast').textContent"), "was already going")

    def test_the_terminal_keeps_its_rows_straight_when_the_strip_turns_compact(self):
        self.open(viewport="phone-portrait", command="bash --norc", tmux_conf=TITLES_TMUX)
        time.sleep(1.0)
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:idle:")
        time.sleep(1.5)
        g = self.geo()
        self.assert_nothing_covered(g)

    def test_a_desktop_does_not_show_it(self):
        self.open(viewport="desktop", command="bash --norc", tmux_conf=TITLES_TMUX)
        time.sleep(1.0)
        self.t.tmux("set-option", "-g", "@sysop_line", "sysop:working:reads tab 1")
        time.sleep(1.5)
        self.assertEqual(self.page.js("(() => { const e = document.querySelector('#swarmbox-strip .sb-toast'); return !e || getComputedStyle(e).display === 'none'; })()"), True)


@bs.browser_tests()
class Reconnect(StripCase):
    def test_the_page_presses_enter_when_ttyd_asks_for_it(self):
        self.open(viewport="phone-portrait", command="bash --norc", init_script=KEEP_SOCKETS)
        time.sleep(1.0)
        n = self.page.js("window.__ws.length")
        self.assertGreaterEqual(n, 1)
        self.page.js("window.__ws[window.__ws.length - 1].close(1000)")      # a normal close: ttyd waits for Enter instead of reconnecting by itself
        self.assertTrue(wait_until(lambda: self.page.js("window.__ws.length") > n, 8, 0.1), "a new connection was opened without a key from the user")
        self.assertTrue(wait_until(lambda: self.page.js("window.__ws[window.__ws.length - 1].readyState") == 1, 8, 0.1), "the new connection is open")
        time.sleep(1.0)
        self.t.type("echo back-again\r")
        self.assertTrue(self.t.wait_line("back-again", 10), "and the terminal works again")


if __name__ == "__main__":
    unittest.main(verbosity=2)

