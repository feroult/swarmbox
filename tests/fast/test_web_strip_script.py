#!/usr/bin/env python3
"""The controls strip of the web terminal page without a browser: the settings of web-terminal.conf that configure it (`strip`, `stripKeys`, rendered by
container/scripts/swarmbox-web.sh into the page), the key notation (`parseKeys` / `keyBytes` of container/web/ttyd-clipboard.js, run by node), and the
script against a small fake DOM (a framed page gets no strip, the lifetime of a note). The strip in a real browser (viewports, the bytes a button
delivers, the keyboard of a phone) is tests/slow/test_web_strip.py.

Run:  python3 tests/fast/test_web_strip_script.py     (the node part skips without node)
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
import test_web_build as wb  # noqa: E402

JS = os.path.join(ROOT, "container", "web", "ttyd-clipboard.js")
DEFAULT_KEYS = "Esc=Escape, Tab=Tab, ^C=C-c, \u2191=Up, \u2193=Down, \u2190=Left, \u2192=Right, Panel=C-a S, Allow=C-a a, Cancel=C-a V"


class Render(wb.WebCase):
    def cfg(self):
        page = self.index()
        i = page.index("window.__swarmboxStripCfg=") + len("window.__swarmboxStripCfg=")
        return json.JSONDecoder().raw_decode(page[i:])[0]

    def render(self, conf):
        self.conf(conf)
        r = self.web("render")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_defaults_and_the_default_list_is_what_the_docs_say(self):
        self.assertEqual(self.web("render").returncode, 0)
        self.assertNotIn("__SWARMBOX_", self.index())
        self.assertEqual(self.cfg(), {"mode": "auto", "custom": False, "keys": DEFAULT_KEYS})
        with open(os.path.join(ROOT, "docs", "web-terminal.md"), encoding="utf-8") as f:
            self.assertIn(DEFAULT_KEYS, f.read())

    def test_strip_modes(self):
        for value, want in (("on", "on"), ("off", "off"), ("auto", "auto"), ("maybe", "auto"), ("", "auto"), ("ON", "auto")):
            with self.subTest(value=value):
                r = self.render("strip=%s\n" % value)
                self.assertEqual(self.cfg()["mode"], want)
                if want == "auto" and value not in ("auto", ""):
                    self.assertIn("not auto, on or off", r.stderr)

    def test_listed_keys_replace_the_default_an_empty_list_is_no_buttons_and_a_comment_is_not_a_listing(self):
        for conf, want in (("stripKeys=Esc=Escape, F5=F5\n", {"custom": True, "keys": "Esc=Escape, F5=F5"}),
                           ("stripKeys=\n", {"custom": True, "keys": ""}),
                           ("# stripKeys=Esc=Escape\n", {"custom": False, "keys": DEFAULT_KEYS})):
            with self.subTest(conf=conf):
                self.render(conf)
                self.assertEqual(self.cfg(), dict(want, mode="auto"))

    def test_hostile_values_stay_inside_the_string(self):
        evil = 'a"b\\c</script><img src=x>&/;x=C-c'
        self.render("stripKeys=%s\n" % evil)
        page = self.index()
        self.assertNotIn("</script><img", page)
        self.assertNotIn("__SWARMBOX_", page)
        self.assertEqual(self.cfg()["keys"], evil, "the string arrives unchanged")


NODE = shutil.which("node")


@unittest.skipUnless(NODE, "needs node")
class KeyNotation(unittest.TestCase):
    """The page script run in node with the least of a browser: only the pure functions are used."""

    def run_js(self, expr):
        harness = """
const vm = require('vm'), fs = require('fs');
const win = {};
const ctx = vm.createContext({window: win, document: {body: null, addEventListener() {}}, setTimeout() { return 0; }, console: {warn() { win.__warned = (win.__warned || 0) + 1; }}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const s = win.swarmboxStrip;
process.stdout.write(JSON.stringify(%s));
""" % expr
        r = subprocess.run([NODE, "-e", harness, JS], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_names_become_the_bytes_xterm_sends_and_unknown_names_are_refused(self):
        names = ["Escape", "Esc", "Tab", "BTab", "Enter", "Space", "BSpace", "Up", "Down", "Right", "Left", "Home", "End", "PageUp", "PageDown", "DC", "IC",
                 "F1", "F4", "F5", "F12", "C-c", "C-a", "C-Space", "C-[", "M-x", "C-M-x", "a", "S", "Comma", "\u00e9"]
        bad = ["Nope", "C-Up", "C-", "M-", "", "C-Escape1", "F13"]
        got = self.run_js("[%s.map(n => s.keyBytes(n, false)), %s.map(n => s.keyBytes(n, false)), ['Up', 'Left', 'Home', 'PageUp'].map(n => s.keyBytes(n, true))]"
                          % (json.dumps(names), json.dumps(bad)))
        self.assertEqual(got[0], ["\x1b", "\x1b", "\t", "\x1b[Z", "\r", " ", "\x7f", "\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\x1b[H", "\x1b[F", "\x1b[5~",
                                 "\x1b[6~", "\x1b[3~", "\x1b[2~", "\x1bOP", "\x1bOS", "\x1b[15~", "\x1b[24~", "\x03", "\x01", "\x00", "\x1b", "\x1bx",
                                 "\x1b\x18", "a", "S", ",", "\u00e9"])
        self.assertEqual(got[1], [None] * len(bad))
        self.assertEqual(got[2], ["\x1bOA", "\x1bOD", "\x1bOH", "\x1b[5~"], "the arrows follow the application cursor mode")

    def test_the_list_is_parsed_and_a_bad_entry_is_dropped_with_one_warning_not_fatal(self):
        got = self.run_js("[s.parseKeys(%s), s.parseKeys('Esc=Escape, Bad=Nope, , =Tab, justtext, Ok=C-c Up'), win.__warned]" % json.dumps(DEFAULT_KEYS))
        self.assertEqual([(d["label"], d["keys"]) for d in got[0]], [("Esc", "Escape"), ("Tab", "Tab"), ("^C", "C-c"), ("\u2191", "Up"), ("\u2193", "Down"),
                                                                  ("\u2190", "Left"), ("\u2192", "Right"), ("Panel", "C-a S"), ("Allow", "C-a a"), ("Cancel", "C-a V")])
        self.assertEqual(got[0][-1]["seq"], ["C-a", "V"])
        self.assertEqual([d["label"] for d in got[1]], ["Esc", "Ok"])
        self.assertEqual(got[2], 3, "one warning per entry that cannot be read: Bad=Nope, =Tab, justtext")


class FakeDom(unittest.TestCase):
    """The page script run in node against a small fake DOM: what must hold without a browser (framing, the lifetime of a note)."""

    HARNESS = """
const vm = require('vm'), fs = require('fs');
const made = [], timers = [];
function mk(tag) {
  const e = {tag, children: [], style: {setProperty() {}, removeProperty() {}}, hidden: false, className: '', textContent: '', attrs: {}, listeners: {},
    classList: {toggle() {}}, appendChild(c) { this.children.push(c); if (this.tag === 'span-parent') {} return c; },
    removeChild() {}, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    getBoundingClientRect() { return {right: 100, left: 0, top: 0, bottom: 0, width: 100, height: 40}; }};
  made.push(e); return e;
}
const win = {__swarmboxStripCfg: JSON.parse(process.argv[2]), matchMedia() { return {matches: true}; }, dispatchEvent() {}, addEventListener() {}, Event: function () {}};
win.self = win; win.top = process.argv[3] === 'framed' ? {} : win;
if (process.argv[3] === 'throws') Object.defineProperty(win, 'top', {get() { throw new Error('cross-origin'); }});
const doc = {body: mk('body'), documentElement: mk('html'), createElement: mk, addEventListener() {}, getElementById() { return null; }};
const ctx = vm.createContext({window: win, document: doc, setTimeout(f, ms) { timers.push({f, ms, live: true}); return timers.length; },
  clearTimeout(id) { if (timers[id - 1]) timers[id - 1].live = false; }, clearInterval() {}, setInterval() { return 0; }, requestAnimationFrame(f) { f(); }, Event: function () {}, console});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const s = win.swarmboxStrip;
%s
"""

    def run_js(self, body, cfg=None, how="plain"):
        r = subprocess.run([NODE, "-e", self.HARNESS % body, JS, json.dumps(cfg or {"mode": "auto", "keys": DEFAULT_KEYS}), how],
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_a_framed_page_gets_no_strip_and_no_key_button(self):
        for how in ("framed", "throws"):
            got = self.run_js("process.stdout.write(JSON.stringify({made: made.length, visible: s.visible, add: s.add({id: 'x'}), keys: s.keyBytes('C-c', false)}));", how=how)
            self.assertEqual(got, {"made": 2, "visible": False, "add": None, "keys": "\x03"}, how)  # 2: the body and the root the harness made

    def test_the_letters_on_a_phone_follow_the_width_as_a_number_of_columns(self):
        """size = (width - 20) / (columns * 0.6), rounded, between 10 and the configured size; a mouse screen keeps the configured size"""
        got = self.run_js("process.stdout.write(JSON.stringify([s.fontFor(390, 844, 21, true), s.fontFor(844, 390, 21, true), s.fontFor(360, 640, 21, true),"
                          " s.fontFor(320, 568, 21, true), s.fontFor(768, 1024, 21, true), s.fontFor(390, 844, 12, true), s.fontFor(200, 400, 21, true),"
                          " s.fontFor(390, 844, 21, false), s.fontFor(1920, 1080, 21, false)]));")
        self.assertEqual(got, [6, 7, 6, 5, 12, 6, 5, 21, 21], "an upright 390 px phone 6 px (about 100 columns), sideways 7 px, a tablet the configured size")

    def test_the_same_page_not_framed_builds_the_strip(self):
        got = self.run_js("process.stdout.write(JSON.stringify({buttons: made.filter(e => /(^| )sb-key( |$)/.test(e.className)).length, visible: s.visible}));")
        self.assertEqual(got["buttons"], 10)
        self.assertTrue(got["visible"])

    def test_a_note_ends_by_itself_and_a_new_one_restarts_the_clock(self):
        got = self.run_js("""s.note('Sending', '');
          const a = timers.filter(t => t.live && t.ms >= 1000).map(t => t.ms);
          s.note('Microphone blocked', 'error');
          const b = timers.filter(t => t.live && t.ms >= 1000).map(t => t.ms);
          s.note('');
          const c = timers.filter(t => t.live && t.ms >= 1000).map(t => t.ms);
          process.stdout.write(JSON.stringify([a, b, c]));""")
        self.assertEqual(got[0], [130000], "a plain state is capped at a little over the longest send")
        self.assertEqual(got[1], [12000], "the earlier clock was cleared, the tone has its own")
        self.assertEqual(got[2], [], "an empty note starts no clock")

    def test_the_clock_clears_the_note(self):
        got = self.run_js("""s.note('Nobody is listening', 'warn');
          const note = made.find(e => e.className === 'sb-note');
          const before = !note.hidden;
          timers.filter(t => t.live && t.ms >= 1000).forEach(t => t.f());
          process.stdout.write(JSON.stringify([before, note.hidden]));""")
        self.assertEqual(got, [True, True])


if __name__ == "__main__":
    unittest.main(verbosity=2)
