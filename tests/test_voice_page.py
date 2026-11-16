#!/usr/bin/env python3
"""Static gate for the voice control of the web page (container/addons/voice/web/page.js and page.css).

Fast: no browser, no network. The behaviour in a real browser is in test_voice_page_browser.py (opt in).

The page is the microphone and a state light only: voice is an input, the audio becomes a goal on the bus and the page says what became of it
(sent, nothing heard, nobody is listening, busy, error). It has no card, no plan, no Run/Edit/Cancel and no way to call anything but health and audio.

Checks: both assets exist; no external URL (nothing is loaded from, or sent to, anywhere but the page's own origin); no way to
turn a string into markup or code (innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function); the assets can be
injected into a page (no closing tag inside); the colours are the purple-glow palette of docs/theme.md; the required elements,
endpoints, buttons and events are there; the script parses (when node is installed).

Run:  python3 tests/test_voice_page.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

WEB = os.path.join(ROOT, "container", "addons", "voice", "web")
JS = os.path.join(WEB, "page.js")
CSS = os.path.join(WEB, "page.css")
THEME = os.path.join(ROOT, "docs", "theme.md")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def code_only(js):
    """The script without comments (a comment may talk about innerHTML)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|(?<=[;{}),\s])//\s.*$", "", js)


class PageAssets(unittest.TestCase):
    def test_the_assets_exist(self):
        for p in (JS, CSS):
            self.assertTrue(os.path.isfile(p), p)
            self.assertGreater(os.path.getsize(p), 500)
            self.assertLess(os.path.getsize(p), 60 * 1024, "the page must stay small")

    def test_no_external_url(self):
        js, css = code_only(read(JS)), read(CSS)
        urls = re.findall(r"""(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s'")]*""", js)
        self.assertEqual([u for u in urls if u != "http://www.w3.org/2000/svg"], [], "only the SVG namespace may look like a URL")
        for bad in ("@import", "url(", "http://", "https://", "//"):
            if bad != "//":
                self.assertFalse(bad in css, "page.css must not contain " + bad)
        for bad in ("XMLHttpRequest", "WebSocket", "sendBeacon", "importScripts", "<script", "<iframe", "<link"):
            self.assertFalse(bad in js, 'page.js must not contain ' + bad)
        # every request goes to BASE (the page's own origin), never to an absolute URL
        self.assertEqual(re.findall(r"fetch\(([^,)]*)", js), ["BASE + 'audio'", "BASE + 'health'"])

    def test_no_string_becomes_markup_or_code(self):
        js = code_only(read(JS))
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout('",
                    'setTimeout("', "srcdoc", "javascript:", "DOMParser", "createContextualFragment", "location ="):
            self.assertFalse(bad in js, 'page.js must not contain ' + bad)
        # text reaches the page only through textContent (el() and show()); there is no form control to fill
        self.assertIn("e.textContent = String(text)", js)
        self.assertIn("strip.note(msg, tone)", js)
        self.assertEqual(re.findall(r"\.(?:value)\s*=", js), [], "no form control is filled")

    def test_the_assets_can_be_injected_into_a_page(self):
        for p in (JS, CSS):
            text = read(p).lower()
            for bad in ("</script", "</style", "<!--", "-->", "\x00"):
                self.assertNotIn(bad, text, "%s must not contain %r" % (os.path.basename(p), bad))

    def test_colours_are_the_purple_glow_palette(self):
        theme = read(THEME).lower()
        allowed = set(re.findall(r"#[0-9a-f]{6}", theme)) | {"#fff"}
        used = set(re.findall(r"#[0-9a-f]{3,6}\b", read(CSS).lower()))
        self.assertEqual(sorted(used - allowed), [], "colours that are not in docs/theme.md")
        for c in ("#0c0b10", "#a78bfa", "#6d28d9", "#ff6b78"):
            self.assertIn(c, used)

    def test_everything_is_under_one_id(self):
        css = re.sub(r"/\*.*?\*/", "", read(CSS), flags=re.S)
        for sel in re.findall(r"(?m)^([^{}@\n][^{}]*)\{", css):
            for part in sel.split(","):
                self.assertTrue(part.strip().startswith("#swarmbox-voice-mic"), "rule escapes its root: " + part.strip())

    def test_required_pieces(self):
        js = read(JS)
        for needle in ("getUserMedia", "'audio/wav'", "pointerdown", "pointerup", "pointercancel", "lostpointercapture", "'health'", "'audio'",
                       "NotAllowedError", "NotFoundError", "isSecureContext", "swarmbox-voice", "RIFF", "WAVE", "'nothing_heard'", "'no_listener'", "'busy'", "'bus_down'", "'nolistener'", "Nobody is listening",
                       "'recording'", "'sending'", "'sent'", "'error'", "'nothing'", "'idle'", "Space", "keydown", "keyup"):
            if needle == "Space":
                needle = "' '"
            self.assertTrue(needle in js, 'page.js lacks ' + needle)
        css = read(CSS)
        for needle in ("touch-action: none", "user-select: none", "min-width: 44px", ".sv-light",
                       'data-state="recording"', 'data-state="sent"', 'data-state="error"', 'data-state="nothing"', 'data-state="sending"', 'data-state="nolistener"', 'data-state="busy"'):
            self.assertTrue(needle in css, 'page.css lacks ' + needle)

    def test_the_page_is_only_the_microphone_and_a_light(self):
        """Nothing of the old confirmation card is left, in the script or the style (dead code is a bug)."""
        js, css = code_only(read(JS)), read(CSS)
        self.assertNotIn("'pending'", js, "a plan is not pending anywhere any more")
        for gone in ("transcribe", "'plan'", "'run'", "'edit'", "'cancel'", "utterance", "voice/pending", "postJson", "openCard", "closeCard", "describe",
                     "textarea", "checkbox", "'Run'", "'Edit'", "'Cancel'", "'Apply'", "risk", "sv-card", "sv-run", "sv-banner", "Escape", "X-Swarmbox-Voice"):
            self.assertNotIn(gone, js, "page.js still has " + gone)
        for gone in ("sv-card", "sv-run", "sv-btn", "sv-risk", "sv-banner", "sv-action", "sv-code", "textarea", "data-risk", "sv-edit", "sv-heard"):
            self.assertNotIn(gone, css, "page.css still has " + gone)
        # every class the script puts in the page is styled, and every class styled is used
        used = set(re.findall(r"el\('[a-z]+', '(sv-[a-z-]+)'", js))
        styled = set(re.findall(r"\.(sv-[a-z-]+)", css))
        self.assertEqual(used - styled, set(), "classes without a style")
        self.assertEqual(styled - used, set(), "styles of classes nothing uses")

    def test_the_microphone_lives_in_the_strip_of_the_host_and_floats_nowhere(self):
        js, css = code_only(read(JS)), read(CSS)
        self.assertIn("window.swarmboxStrip", js)
        self.assertIn("strip.add(", js)
        for floating in ("position: fixed", "position:fixed", "position: sticky", "z-index"):
            self.assertNotIn(floating, css, "the microphone must not float over the terminal")
        self.assertNotIn("document.body.appendChild", js, "the page adds nothing to the body itself: the strip is the place")
        # the voice page knows no other control of the strip, nor the sysop
        for other in ("Panel", "sysop", "Escape", "term.input", "swarmbox-strip"):
            self.assertNotIn(other, js, "page.js must not know " + other)

    def test_the_page_only_posts_audio(self):
        js = code_only(read(JS))
        self.assertEqual(re.findall(r"method: '(\w+)'", js), ["POST"], "one call sends something: the audio")
        self.assertEqual(re.findall(r"BASE \+ '(\w+)'", js), ["audio", "health"])
        self.assertEqual(re.findall(r"body: (\w+)", js), ["wav"])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_the_script_parses(self):
        r = subprocess.run(["node", "--check", JS], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
