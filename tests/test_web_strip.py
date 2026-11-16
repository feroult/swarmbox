#!/usr/bin/env python3
"""The controls strip of the web terminal page (container/web/ttyd-clipboard.js part 2, ttyd-style.css, the `strip` and `stripKeys` settings of
web-terminal.conf rendered by container/scripts/swarmbox-web.sh).

Three layers:
  1. Render: the settings become the placeholders of the page (fast, a fake ttyd).
  2. The key notation: parseKeys / keyBytes of the page script, run by node when it is installed (fast, no browser).
  3. Browser (Chromium + the real ttyd + a REAL tmux, so SWARMBOX_TEST_REAL_TMUX=1, which only the Podman runs set): the strip at several viewports
     (desktop, phone portrait and landscape with touch, tablet) by bounding boxes: it never covers the last row of the terminal, the tmux window has
     exactly the rows xterm shows, the buttons are at least 44 px, an addon control sits in the strip, every key button delivers its bytes to a pane
     running `cat -vT` (by mouse and by touch), the Panel button runs the binding of the sysop panel of container/config/tmux.conf, the settings show
     and hide the strip, and the keyboard of a phone (visualViewport) moves the strip with it. SWARMBOX_TEST_SHOTS=<dir> also saves a screenshot per viewport.

Run:  python3 tests/test_web_strip.py      (the browser layer needs chromium, ttyd and tmux, and runs in Podman: tests/run_all.sh --browser)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
import test_clipboard_bridge as base  # noqa: E402
import test_web_build as wb  # noqa: E402

JS = os.path.join(ROOT, "container", "web", "ttyd-clipboard.js")
TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
DEFAULT_KEYS = "Esc=Escape, Tab=Tab, ^C=C-c, ↑=Up, ↓=Down, ←=Left, →=Right, Panel=C-a S, Veto=C-a V, Stop=C-a X"


class Render(wb.WebCase):
    def cfg(self):
        page = self.index()
        i = page.index("window.__swarmboxStripCfg=") + len("window.__swarmboxStripCfg=")
        return json.JSONDecoder().raw_decode(page[i:])[0]

    def test_defaults(self):
        self.assertEqual(self.web("render").returncode, 0)
        self.assertNotIn("__SWARMBOX_", self.index())
        self.assertEqual(self.cfg(), {"mode": "auto", "custom": False, "keys": DEFAULT_KEYS})

    def test_the_default_list_is_what_the_docs_say(self):
        with open(os.path.join(ROOT, "docs", "web-terminal.md"), encoding="utf-8") as f:
            doc = f.read()
        self.assertIn(DEFAULT_KEYS, doc)

    def test_strip_modes(self):
        for value, want in (("on", "on"), ("off", "off"), ("auto", "auto"), ("maybe", "auto"), ("", "auto"), ("ON", "auto")):
            self.conf("strip=%s\n" % value)
            r = self.web("render")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.cfg()["mode"], want, value)
            if want == "auto" and value not in ("auto", ""):
                self.assertIn("not auto, on or off", r.stderr)

    def test_listed_keys_are_custom_and_replace_the_default(self):
        self.conf("stripKeys=Esc=Escape, F5=F5\n")
        self.web("render")
        self.assertEqual(self.cfg(), {"mode": "auto", "custom": True, "keys": "Esc=Escape, F5=F5"})

    def test_an_empty_list_means_no_buttons_and_counts_as_listed(self):
        self.conf("stripKeys=\n")
        self.web("render")
        self.assertEqual(self.cfg(), {"mode": "auto", "custom": True, "keys": ""})

    def test_a_commented_line_is_not_a_listing(self):
        self.conf("# stripKeys=Esc=Escape\n")
        self.web("render")
        self.assertFalse(self.cfg()["custom"])

    def test_hostile_values_stay_inside_the_string(self):
        evil = 'a"b\\c</script><img src=x>&/;x=C-c'
        self.conf("stripKeys=%s\n" % evil)
        self.assertEqual(self.web("render").returncode, 0)
        page = self.index()
        self.assertNotIn("</script><img", page)
        self.assertNotIn("__SWARMBOX_", page)
        self.assertEqual(self.cfg()["keys"], evil, "the string arrives unchanged")

    def test_the_two_settings_are_not_passed_to_ttyd(self):
        self.conf("strip=on\nstripKeys=Esc=Escape\nfontSize=17\n")
        self.assertEqual(self.web("run").returncode, 0)
        opts = self.opts(self.ttyd_call()["argv"])
        self.assertNotIn("strip", opts)
        self.assertNotIn("stripKeys", opts)
        self.assertEqual(opts.get("fontSize"), "17")


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

    def test_names_become_the_bytes_xterm_sends(self):
        names = ["Escape", "Esc", "Tab", "BTab", "Enter", "Space", "BSpace", "Up", "Down", "Right", "Left", "Home", "End", "PageUp", "PageDown", "DC", "IC",
                 "F1", "F4", "F5", "F12", "C-c", "C-a", "C-Space", "C-[", "M-x", "C-M-x", "a", "S", "Comma", "é"]
        got = self.run_js("%s.map(n => s.keyBytes(n, false))" % json.dumps(names))
        self.assertEqual(got, ["\x1b", "\x1b", "\t", "\x1b[Z", "\r", " ", "\x7f", "\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\x1b[H", "\x1b[F", "\x1b[5~",
                               "\x1b[6~", "\x1b[3~", "\x1b[2~", "\x1bOP", "\x1bOS", "\x1b[15~", "\x1b[24~", "\x03", "\x01", "\x00", "\x1b", "\x1bx",
                               "\x1b\x18", "a", "S", ",", "é"])

    def test_arrows_follow_the_application_cursor_mode(self):
        self.assertEqual(self.run_js("['Up', 'Left', 'Home', 'PageUp'].map(n => s.keyBytes(n, true))"), ["\x1bOA", "\x1bOD", "\x1bOH", "\x1b[5~"])

    def test_unknown_names_are_refused(self):
        bad = ["Nope", "C-Up", "C-", "M-", "", "C-Escape1", "F13"]
        self.assertEqual(self.run_js("%s.map(n => s.keyBytes(n, false))" % json.dumps(bad)), [None] * len(bad))

    def test_the_list(self):
        got = self.run_js("s.parseKeys(%s)" % json.dumps(DEFAULT_KEYS))
        self.assertEqual([(d["label"], d["keys"]) for d in got], [("Esc", "Escape"), ("Tab", "Tab"), ("^C", "C-c"), ("↑", "Up"), ("↓", "Down"), ("←", "Left"),
                                                                 ("→", "Right"), ("Panel", "C-a S"), ("Veto", "C-a V"), ("Stop", "C-a X")])
        self.assertEqual(got[-1]["seq"], ["C-a", "X"])

    def test_bad_entries_are_dropped_not_fatal(self):
        got = self.run_js("[s.parseKeys('Esc=Escape, Bad=Nope, , =Tab, justtext, Ok=C-c Up'), win.__warned]")
        self.assertEqual([d["label"] for d in got[0]], ["Esc", "Ok"])
        self.assertEqual(got[1], 3, "one warning per entry that cannot be read: Bad=Nope, =Tab, justtext")


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
const win = {__swarmboxStripCfg: JSON.parse(process.argv[2]), matchMedia() { return {matches: true}; }, dispatchEvent() {}, Event: function () {}};
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

    def test_the_same_page_not_framed_builds_the_strip(self):
        got = self.run_js("process.stdout.write(JSON.stringify({buttons: made.filter(e => e.className === 'sb-btn sb-key').length, visible: s.visible}));")
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


# ---------------------------------------------------------------------------------------------------------------------
REAL = os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"
SHOTS = os.environ.get("SWARMBOX_TEST_SHOTS", "")
RAW_CAT = "stty raw -echo; exec cat -vT"   # a pane that shows, in caret notation, the bytes tmux hands it

VIEWPORTS = {  # name: (width, height, touch)
    "desktop": (1280, 800, False),
    "phone-portrait": (390, 844, True),
    "phone-landscape": (844, 390, True),
    "tablet": (820, 1180, True),
}


@unittest.skipUnless(REAL and all(shutil.which(c) for c in base.NEEDED), "needs chromium, ttyd, tmux and SWARMBOX_TEST_REAL_TMUX=1 (Podman)")
class Browser(base.ClipboardBridge):
    # only the browser harness is reused, not the clipboard tests of the same class
    for _name in [n for n in dir(base.ClipboardBridge) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    PASS_OPTIONS = True

    def setUp(self):
        super().setUp()
        self.tmuxtmp = os.path.join(self.tmp, "tmuxtmp")
        os.makedirs(self.tmuxtmp)
        self.addCleanup(lambda: subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=self.tmux_env()) if hasattr(self, "sock") else None)
        self.fake = os.path.join(self.tmp, "sysopbin")
        os.makedirs(self.fake)
        self.sysop_log = os.path.join(self.tmp, "sysop.log")
        with open(os.path.join(self.fake, "swarmbox-sysop"), "w") as f:
            f.write('#!/bin/sh\necho "$@" >> "%s"\n' % self.sysop_log)
        os.chmod(os.path.join(self.fake, "swarmbox-sysop"), 0o755)

    def spawn(self, argv, stderr_file=None, **kw):
        p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=open(stderr_file, "w") if stderr_file else subprocess.DEVNULL,
                             start_new_session=True, **kw)
        self.procs.append(p)
        return p

    def tmux_env(self):
        return dict(os.environ, TMUX_TMPDIR=self.tmuxtmp)

    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, env=self.tmux_env()).stdout

    def open_strip(self, conf="", viewport="desktop", pane=RAW_CAT, real_conf=False, init_script="", media=None):
        """The real page (build-index.sh + swarmbox-web) served by the real ttyd over a real tmux whose one pane runs `pane`, in Chromium
        at the viewport. real_conf: tmux gets the image's container/config/tmux.conf (the Panel binding, the status bar) instead of a bare one."""
        width, height, touch = VIEWPORTS[viewport]
        index = self.build_index(conf)
        extra = self.web_options()
        self.sock = "strip%d_%d" % (os.getpid(), base.free_port())
        tmux_conf = os.path.join(self.tmp, "tmux.conf")
        with open(tmux_conf, "w") as f:
            f.write("source-file %s\n" % TMUX_CONF if real_conf else "set -g mouse on\nset -g status-right '%H:%M'\n")
        port = base.free_port()
        env = dict(self.tmux_env(), PATH=self.fake + os.pathsep + os.environ["PATH"])
        self.ttyd_err = os.path.join(self.tmp, "ttyd.err")
        self.ttyd = self.spawn(["ttyd", "-p", str(port), "-W", "-O", "-i", "lo", "--index", index, *extra,
                                "tmux", "-L", self.sock, "-f", tmux_conf, "new", "-A", "-s", "t", "bash --norc -c '%s'" % pane], env=env,
                               stderr_file=self.ttyd_err)
        dbg = base.free_port()
        self.spawn(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % dbg,
                    "--user-data-dir=" + os.path.join(self.tmp, "chrome"), "about:blank"])
        version = None
        for _ in range(80):
            try:
                import urllib.request
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % dbg, timeout=1) as r:
                    version = json.load(r)
                break
            except OSError:
                time.sleep(0.25)
        self.assertIsNotNone(version, "chromium did not start")
        self.browser = base.CDP(version["webSocketDebuggerUrl"])
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % dbg, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            tab = json.load(r)
        self.page = base.CDP(tab["webSocketDebuggerUrl"])
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2 if touch else 1, mobile=touch)
        if touch:
            self.page.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            self.page.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
        if init_script:
            self.page.call("Page.addScriptToEvaluateOnNewDocument", source=init_script)
        self.page.call("Page.navigate", url="http://127.0.0.1:%d/" % port)
        for _ in range(60):
            time.sleep(0.25)
            if self.page.js("typeof term === 'object' && term.buffer.active.length > 0"):
                break
        time.sleep(1.5)

    # ---- measuring ----------------------------------------------------------------------------
    GEO = """(() => {
      const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, w: b.width, h: b.height}; };
      const q = s => document.querySelector(s);
      return {win: [innerWidth, innerHeight], docw: document.documentElement.scrollWidth, strip: r(q('#swarmbox-strip')), stripShown: !!q('#swarmbox-strip') && !q('#swarmbox-strip').hidden,
              container: r(q('#terminal-container')), screen: r(q('.xterm-screen')), rows: term.rows, cols: term.cols,
              keys: Array.from(document.querySelectorAll('#swarmbox-strip .sb-key')).map(e => Object.assign({t: e.textContent}, r(e))),
              addons: Array.from(document.querySelectorAll('#swarmbox-strip .sb-addon')).map(e => Object.assign({id: e.id}, r(e))),
              keysShown: !!q('#swarmbox-strip .sb-keys') && !q('#swarmbox-strip .sb-keys').hidden,
              coarse: matchMedia('(pointer: coarse)').matches};
    })()"""

    def geo(self):
        return self.page.js(self.GEO)

    def settle(self):
        time.sleep(0.8)

    def shot(self, name):
        if not SHOTS:
            return
        r = self.page.call("Page.captureScreenshot", format="png")
        import base64
        with open(os.path.join(SHOTS, name + ".png"), "wb") as f:
            f.write(base64.b64decode(r["data"]))

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
        for _ in range(20):   # tmux learns the new size over the websocket
            h = self.tmux("list-clients", "-F", "#{client_height}").split()
            if h and int(h[0]) == g["rows"]:
                break
            time.sleep(0.25)
        self.assertEqual([int(x) for x in h][:1], [g["rows"]], "tmux sees exactly the rows xterm shows: the smaller window")

    def pane_text(self):
        return "".join(self.tmux("capture-pane", "-p", "-J", "-t", "t:").split("\n")).strip()

    def wait_pane(self, want, timeout=6):
        end = time.time() + timeout
        while time.time() < end:
            if self.pane_text().endswith(want) or want in self.pane_text():
                return True
            time.sleep(0.15)
        return False

    def center(self, sel_index):
        return self.page.js("(() => { const b = document.querySelectorAll('#swarmbox-strip .sb-key')[%d].getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()" % sel_index)

    def press(self, x, y, touch, hold=0.0):
        if touch:
            self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
            time.sleep(hold)
            self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            common = dict(x=x, y=y, button="left", clickCount=1)
            self.page.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
            self.page.call("Input.dispatchMouseEvent", type="mousePressed", buttons=1, **common)
            time.sleep(hold)
            self.page.call("Input.dispatchMouseEvent", type="mouseReleased", buttons=0, **common)

    # ---- the tests ----------------------------------------------------------------------------
    def test_desktop_has_no_strip_until_something_needs_it(self):
        self.open_strip(viewport="desktop")
        self.settle()
        g = self.geo()
        self.assertFalse(g["stripShown"])
        self.assertFalse(g["coarse"])
        self.assertAlmostEqual(g["container"]["bottom"], g["win"][1], delta=1, msg="the terminal has the whole window as before")
        self.assertFalse(self.page.js("document.documentElement.classList.contains('swarmbox-strip-on')"))
        self.shot("desktop-no-strip")

    def test_a_addon_control_alone_shows_the_strip_on_desktop_without_the_key_buttons(self):
        self.open_strip(viewport="desktop")
        self.page.js("""(() => { const b = swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', label: 'mic'}); window.__b = b; })()""")
        self.settle()
        g = self.geo()
        self.assert_nothing_covered(g)
        self.assertFalse(g["keysShown"], "a mouse user did not ask for key buttons")
        self.assertEqual([p["id"] for p in g["addons"]], ["demo-mic"])
        p, s = g["addons"][0], g["strip"]
        self.assertGreaterEqual(min(p["w"], p["h"]), 44)
        self.assertTrue(s["top"] <= p["top"] and p["bottom"] <= s["bottom"], "the control is inside the strip")
        self.assertGreater(p["left"], g["win"][0] / 2, "at the right end")
        self.shot("desktop-addon-control")
        self.page.js("swarmboxStrip.remove('demo-mic')")
        self.settle()
        self.assertFalse(self.geo()["stripShown"], "with its last control gone the strip goes too and the terminal grows back")
        self.assertAlmostEqual(self.geo()["container"]["bottom"], 800, delta=1)

    def test_listed_keys_show_the_strip_on_desktop(self):
        self.open_strip(conf="stripKeys=Esc=Escape, Hi=h i\n", viewport="desktop")
        self.settle()
        g = self.geo()
        self.assert_nothing_covered(g)
        self.assertEqual([k["t"] for k in g["keys"]], ["Esc", "Hi"])
        self.shot("desktop-listed-keys")
        self.press(*self.center(1), touch=False)
        self.assertTrue(self.wait_pane("hi"), self.pane_text())

    def test_strip_on_forces_it_and_off_hides_it_even_for_a_addon_and_touch(self):
        self.open_strip(conf="strip=on\n", viewport="desktop")
        self.settle()
        g = self.geo()
        self.assert_nothing_covered(g)
        self.assertTrue(g["keysShown"])
        self.assertEqual(len(g["keys"]), 10)
        self.shot("desktop-strip-on")

    def test_strip_off_wins_over_touch_and_addons(self):
        self.open_strip(conf="strip=off\n", viewport="phone-portrait")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'x'})")
        self.settle()
        g = self.geo()
        self.assertTrue(g["coarse"])
        self.assertFalse(g["stripShown"])
        self.assertAlmostEqual(g["container"]["bottom"], g["win"][1], delta=1)

    def check_viewport(self, name, conf=""):
        w, h, touch = VIEWPORTS[name]
        self.open_strip(conf=conf, viewport=name)
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'Hold to talk', order: 10})")
        self.settle()
        g = self.geo()
        self.assertEqual(g["coarse"], touch)
        self.assert_nothing_covered(g)
        self.assertTrue(g["keysShown"])
        self.assertEqual([k["t"] for k in g["keys"]], ["Esc", "Tab", "^C", "↑", "↓", "←", "→", "Panel", "Veto", "Stop"])
        for k in g["keys"] + g["addons"]:
            self.assertGreaterEqual(k["w"], 44 - 0.01, k)
            self.assertGreaterEqual(k["h"], 44 - 0.01, k)
            self.assertTrue(g["strip"]["top"] <= k["top"] and k["bottom"] <= g["strip"]["bottom"], "inside the strip: %r" % k)
            self.assertGreaterEqual(k["left"], 0)
            self.assertLessEqual(k["right"], g["win"][0] + 0.5, "a button off the screen: %r" % k)
        mic = g["addons"][0]
        for k in g["keys"]:
            self.assertFalse(k["left"] < mic["right"] and mic["left"] < k["right"] and k["top"] < mic["bottom"] and mic["top"] < k["bottom"], "keys and mic overlap")
        return g

    def test_phone_portrait(self):
        g = self.check_viewport("phone-portrait")
        self.assertLess(g["strip"]["h"], 844 * 0.2)
        self.shot("phone-portrait")

    def test_phone_landscape_is_one_small_row(self):
        g = self.check_viewport("phone-landscape")
        self.assertLessEqual(g["strip"]["h"], 64, "a slim strip: %r" % g["strip"])
        self.assertLess(g["strip"]["h"], 390 * 0.17)
        tops = {round(k["top"]) for k in g["keys"] + g["addons"]}
        self.assertEqual(len(tops), 1, "a single row")
        self.assertGreater(g["rows"], 8)
        # the clock of the tmux status bar (its last row) is on screen: nothing covers it and it is not cut off at the right
        last = self.page.js("(() => { const b = term.buffer.active; const l = b.getLine(b.viewportY + term.rows - 1); return l ? l.translateToString(true) : ''; })()")
        self.assertRegex(last, r"\d\d:\d\d\s*$", "the status bar and its clock are in the last row of the terminal: %r" % last)
        self.shot("phone-landscape")

    def test_tablet(self):
        g = self.check_viewport("tablet")
        self.shot("tablet")

    def test_desktop_with_the_keys_forced_on_and_a_control(self):
        g = self.check_viewport("desktop", conf="strip=on\n")
        self.shot("desktop-keys-and-control")

    def check_keys(self, touch, vp):
        self.open_strip(conf="strip=on\n", viewport=vp)
        self.settle()
        expected = [("Esc", "^["), ("Tab", "^I"), ("^C", "^C"), ("↑", "^[[A"), ("↓", "^[[B"), ("←", "^[[D"), ("→", "^[[C")]
        labels = [k["t"] for k in self.geo()["keys"]]
        total = ""
        for label, caret in expected:
            self.press(*self.center(labels.index(label)), touch=touch)
            total += caret
            self.assertTrue(self.wait_pane(total), "after %s the pane shows %r, wanted %r" % (label, self.pane_text(), total))
            self.assertEqual(self.pane_text().replace(" ", ""), total)
        # the terminal kept the focus: pressing a button must not steal it (nor close the on-screen keyboard)
        self.assertTrue(self.page.js("document.activeElement && document.activeElement.classList.contains('xterm-helper-textarea')"), "the focus stayed in the terminal")

    def test_every_default_key_button_delivers_its_bytes_by_mouse(self):
        self.check_keys(False, "desktop")

    def test_every_default_key_button_delivers_its_bytes_by_touch(self):
        self.check_keys(True, "phone-portrait")

    def test_holding_an_arrow_repeats_and_a_tap_types_once(self):
        self.open_strip(conf="strip=on\n", viewport="desktop")
        self.settle()
        labels = [k["t"] for k in self.geo()["keys"]]
        self.press(*self.center(labels.index("↓")), touch=False)
        self.assertTrue(self.wait_pane("^[[B"))
        self.assertEqual(self.pane_text(), "^[[B", "one tap, one key")
        self.press(*self.center(labels.index("→")), touch=False, hold=1.2)
        time.sleep(0.4)
        self.assertGreaterEqual(self.pane_text().count("^[[C"), 5, self.pane_text())

    def test_the_panel_button_runs_the_sysop_panel_binding_of_the_image(self):
        with open(TMUX_CONF, encoding="utf-8") as f:
            conf = f.read()
        self.assertIn("bind S if-shell -b", conf, "the binding the Panel button reaches")
        self.assertIn("swarmbox-sysop dock toggle", conf)
        self.assertIn("set -g prefix C-a", conf.replace("unbind C-b\n", ""))
        self.open_strip(conf="strip=on\n", viewport="phone-portrait", real_conf=True, pane="exec sleep 600")
        self.settle()
        labels = [k["t"] for k in self.geo()["keys"]]
        self.assertEqual(self.tmux("show", "-gv", "prefix").strip(), "C-a")
        self.assertFalse(os.path.exists(self.sysop_log))
        self.press(*self.center(labels.index("Panel")), touch=True)
        for _ in range(40):
            if os.path.exists(self.sysop_log):
                break
            time.sleep(0.2)
        self.assertTrue(os.path.exists(self.sysop_log), "the binding did not run")
        line = open(self.sysop_log).read().strip()
        self.assertTrue(line.startswith("dock toggle --socket "), line)
        self.assertIn("--window @", line)
        self.press(*self.center(labels.index("Panel")), touch=True)   # and again: toggles
        for _ in range(40):
            if len(open(self.sysop_log).read().split("\n")) > 2:
                break
            time.sleep(0.2)
        self.assertEqual(len(open(self.sysop_log).read().strip().split("\n")), 2)
        self.shot("phone-portrait-panel-pressed")

    def test_a_note_covers_the_keys_but_not_the_addon_controls_and_goes_away(self):
        self.open_strip(conf="strip=on\n", viewport="phone-portrait")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'x'})")
        self.settle()
        before = self.geo()
        self.page.js("swarmboxStrip.note('Nobody is listening', 'warn')")
        time.sleep(0.3)
        n = self.page.js("(() => { const n = document.querySelector('#swarmbox-strip .sb-note'); const b = n.getBoundingClientRect(); const m = document.getElementById('demo-mic').getBoundingClientRect();"
                         " return {hidden: n.hidden, text: n.textContent, tone: n.dataset.tone, right: b.right, top: b.top, bottom: b.bottom, micLeft: m.left}; })()")
        self.assertEqual((n["hidden"], n["text"], n["tone"]), (False, "Nobody is listening", "warn"))
        self.assertLessEqual(n["right"], n["micLeft"] + 0.5, "the sentence ends where the control begins")
        after = self.geo()
        self.assertEqual(before["strip"], after["strip"], "a sentence never changes the size of the strip, so the terminal is not refitted")
        self.assertEqual(before["rows"], after["rows"])
        self.shot("phone-portrait-note")
        self.page.js("document.querySelector('#swarmbox-strip .sb-note').click()")
        self.assertTrue(self.page.js("document.querySelector('#swarmbox-strip .sb-note').hidden"), "a tap dismisses it")

    def test_the_sentences_of_the_voice_addon_are_read_whole_on_a_phone_in_two_lines(self):
        self.open_strip(conf="strip=on\n", viewport="phone-portrait")
        self.page.js("swarmboxStrip.add({id: 'demo-mic', title: 'x'})")
        self.settle()
        before = self.geo()
        for text in ("Microphone blocked. Allow it in the site settings.", "The speech recognizer is busy: try again in a moment.",
                     "The voice service is restarting: try again in a few seconds.", "The voice service is slow: try again in a moment."):
            self.page.js("swarmboxStrip.note(%s, 'error')" % json.dumps(text))
            m = self.page.js("(() => { const n = document.querySelector('#swarmbox-strip .sb-note'); const t = n.firstChild; const r = n.getBoundingClientRect();"
                             " return {cut: t.scrollHeight > t.clientHeight + 1, h: t.getBoundingClientRect().height, line: parseFloat(getComputedStyle(n).lineHeight), box: r.height, full: n.title}; })()")
            self.assertFalse(m["cut"], "%r is cut: %r" % (text, m))
            self.assertLessEqual(m["h"], 2 * m["line"] + 1, text)
            self.assertEqual(m["full"], text, "the whole text is also the tooltip")
            self.assertEqual(self.geo()["strip"], before["strip"], "the strip did not grow")

    def test_a_note_nobody_clears_goes_away_by_itself(self):
        self.open_strip(conf="strip=on\n", viewport="phone-portrait")
        self.page.js("window.__t = []; const st = window.setTimeout; window.setTimeout = (f, ms, ...a) => { window.__t.push(ms); return st(f, ms > 1000 ? 50 : ms, ...a); }")
        self.page.js("swarmboxStrip.note('hello', 'warn')")
        self.assertFalse(self.page.js("document.querySelector('#swarmbox-strip .sb-note').hidden"))
        time.sleep(0.5)
        self.assertTrue(self.page.js("document.querySelector('#swarmbox-strip .sb-note').hidden"), "the host ended it")
        self.assertIn(12000, self.page.js("window.__t"))

    def test_the_keyboard_of_a_phone_moves_the_strip_above_it(self):
        fake = """(() => { const l = {}; const vv = {get height() { return this._h === undefined ? innerHeight : this._h; }, set height(v) { this._h = v; }, offsetTop: 0, width: innerWidth,
          addEventListener(t, f) { (l[t] = l[t] || []).push(f); }, fire() { for (const t of ['resize', 'scroll']) (l[t] || []).forEach(f => f()); }};
          Object.defineProperty(window, 'visualViewport', {value: vv}); window.__vv = vv; })()"""
        self.open_strip(conf="strip=on\n", viewport="phone-portrait", init_script=fake)
        self.settle()
        g0 = self.geo()
        self.page.js("__vv.height = 500; __vv.fire()")
        self.settle()
        g = self.geo()
        self.assertAlmostEqual(g["strip"]["bottom"], 500, delta=1, msg="the strip sits on the keyboard")
        self.assertLessEqual(g["container"]["bottom"], g["strip"]["top"] + 0.5)
        self.assertLess(g["rows"], g0["rows"], "the terminal got smaller and was refitted")
        self.assert_nothing_covered(dict(g, win=[g["win"][0], 500]))
        self.shot("phone-portrait-keyboard-open")
        self.page.js("__vv.height = innerHeight; __vv.fire()")
        self.settle()
        g2 = self.geo()
        self.assertAlmostEqual(g2["strip"]["bottom"], 844, delta=1)
        self.assertEqual(g2["rows"], g0["rows"])

    def test_the_terminal_still_works_and_the_clipboard_bridge_is_intact_with_the_strip(self):
        self.open_strip(conf="strip=on\n", viewport="desktop", pane="bash --norc")
        self.settle()
        self.page.js("term.focus(); term.input('echo STRIP-OK\\r', true)")
        self.assertTrue(self.wait_pane("STRIP-OK"))
        self.assertIsNotNone(self.page.js("window.__swarmboxClipboard"))
        self.assertEqual(self.page.js("typeof window.swarmboxStrip.add"), "function")


if __name__ == "__main__":
    unittest.main(verbosity=2)
