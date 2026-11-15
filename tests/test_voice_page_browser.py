#!/usr/bin/env python3
"""Browser test for the voice control of the web page (container/tools/voice/web/page.js and page.css), in headless Chromium.

Run:  python3 tests/test_voice_page_browser.py     (needs chromium; skipped otherwise)

Not part of the fast gate: run_all.sh lists it in its browser group (--browser), like the other browser tests, which run in the
scheduled job. No network, no model and no real microphone: Chromium reads a WAV file made here with the wave module
(--use-fake-device-for-media-stream, --use-fake-ui-for-media-stream, --use-file-for-fake-audio-capture), and a STUB voice
service on 127.0.0.1 answers the page (health and audio only) and records every request.

The page is the microphone and a state light: the plan, its risk and the confirmation are in the tmux panel. Covers: the button appears
only when the service answers; hold records and POSTs a 16 kHz mono 16-bit WAV to /voice/audio and nothing else; the light goes
recording, sending, sent (or nothing heard, or an error with a short sentence); the page shows no card, no plan, no transcript, no
Run/Edit/Cancel; text of an error is shown as text; denied and missing microphone give a short message; touch works; it fits a phone.
"""
import json
import math
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_clipboard_bridge import CDP  # noqa: E402

WEB = os.path.join(ROOT, "container", "tools", "voice", "web")
CHROMIUM = next((c for c in (shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome")) if c), None)

HOSTILE = '<img src=x onerror="window.__pwn=1"><script>window.__pwn=2</script>'

BASE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>stub terminal</title><style>html,body{margin:0;height:100%%;background:#0c0b10}%s</style></head>
<body><div id="terminal" style="height:100%%"></div><script>%s</script></body></html>"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_wav(path, seconds=3.0, rate=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))


class Stub:
    """A stub voice service plus a page that carries the real page.js and page.css. answer: (status, body) of POST /voice/audio."""

    def __init__(self, healthy=True, answer=None):
        self.healthy = healthy
        self.answer = answer or (200, {"ok": True, "state": "pending"})
        self.requests = []   # (method, path, content type, body bytes)
        self.lock = threading.Lock()
        stub = self
        with open(os.path.join(WEB, "page.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(WEB, "page.css"), encoding="utf-8") as f:
            css = f.read()
        self.page = (BASE_PAGE % (css, js)).encode()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                with stub.lock:
                    stub.requests.append(("GET", self.path, "", b""))
                if self.path == "/":
                    return self.send(200, stub.page, "text/html; charset=utf-8")
                if self.path == "/voice/health":
                    return self.send(200 if stub.healthy else 404, {"ok": stub.healthy})
                self.send(404, {"error": "no"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(n)
                with stub.lock:
                    stub.requests.append(("POST", self.path, self.headers.get("Content-Type", ""), body))
                if self.path == "/voice/audio":
                    time.sleep(0.4)   # long enough to see the "sending" light
                    return self.send(*stub.answer)
                self.send(404, {"error": "no"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def posts(self):
        with self.lock:
            return [r for r in self.requests if r[0] == "POST"]

    def paths(self):
        with self.lock:
            return sorted({(r[0], r[1]) for r in self.requests if r[1] not in ("/", "/favicon.ico")})


@unittest.skipUnless(CHROMIUM, "needs chromium")
class VoicePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="swarmbox-test-voicepage-")
        cls.wav = os.path.join(cls.tmp, "speech.wav")
        make_wav(cls.wav)
        dbg = free_port()
        cls.proc = subprocess.Popen(
            [CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % dbg,
             "--user-data-dir=" + os.path.join(cls.tmp, "chrome"), "--use-fake-device-for-media-stream",
             "--use-fake-ui-for-media-stream", "--use-file-for-fake-audio-capture=" + cls.wav, "--autoplay-policy=no-user-gesture-required",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        cls.dbg = dbg
        version = None
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % dbg, timeout=1) as r:
                    version = json.load(r)
                break
            except OSError:
                time.sleep(0.25)
        if version is None:
            cls.tearDownClass()
            raise RuntimeError("chromium did not start")
        cls.browser = CDP(version["webSocketDebuggerUrl"])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.s.close()
        proc = getattr(cls, "proc", None)
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.stub = None
        self.page = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.page is not None:
            self.page.s.close()
        if self.stub is not None:
            self.stub.close()

    # ---- helpers -------------------------------------------------------------------------------
    def open(self, stub, init_script="", width=1000, height=700, touch=False):
        self.stub = stub
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % self.dbg, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            tab = json.load(r)
        self.page = CDP(tab["webSocketDebuggerUrl"])
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=touch)
        if touch:
            self.page.call("Emulation.setTouchEmulationEnabled", enabled=True)
        if init_script:
            self.page.call("Page.addScriptToEvaluateOnNewDocument", source=init_script)
        self.page.call("Page.navigate", url="http://127.0.0.1:%d/" % stub.port)

    def wait(self, expr, timeout=10, what=""):
        end = time.time() + timeout
        while time.time() < end:
            if self.page.js(expr):
                return
            time.sleep(0.1)
        self.fail("timed out waiting for %s: %s" % (what or expr, self.page.js("document.body.innerText.slice(0, 400)")))

    def center(self, selector):
        r = self.page.js("(() => { const b = document.querySelector(%s).getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()"
                         % json.dumps(selector))
        return r

    def mouse(self, kind, x, y):
        self.page.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", buttons=1 if kind != "mouseReleased" else 0, clickCount=1)

    def click(self, selector):
        x, y = self.center(selector)
        self.mouse("mousePressed", x, y)
        self.mouse("mouseReleased", x, y)

    def hold(self, seconds=1.3, release=True):
        self.wait("!!document.querySelector('#swarmbox-voice-mic')", what="the mic button")
        x, y = self.center("#swarmbox-voice-mic")
        self.mouse("mousePressed", x, y)
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'recording'", what="recording")
        time.sleep(seconds)
        if release:
            self.mouse("mouseReleased", x, y)

    def state(self):
        return self.page.js("document.querySelector('#swarmbox-voice').dataset.state")

    def note(self):
        return self.page.js("(() => { const n = document.querySelector('.sv-note'); return n.hidden ? '' : n.textContent; })()")

    # ---- tests ---------------------------------------------------------------------------------
    def test_the_button_is_absent_when_the_service_is_absent(self):
        self.open(Stub(healthy=False))
        time.sleep(1.5)
        self.assertFalse(self.page.js("!!document.querySelector('#swarmbox-voice')"))
        self.assertTrue(self.page.js("!!document.querySelector('#terminal')"), "the terminal is untouched")

    def test_hold_records_posts_wav_and_only_the_light_changes(self):
        self.open(Stub())
        self.wait("!!document.querySelector('#swarmbox-voice-mic')", what="the mic button")
        self.assertEqual(self.state(), "idle")
        self.hold(1.3, release=False)
        self.assertEqual(self.state(), "recording")
        self.assertEqual(self.note(), "Listening")
        x, y = self.center("#swarmbox-voice-mic")
        self.mouse("mouseReleased", x, y)
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'sending'", what="sending")
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'sent'", what="sent")
        self.assertEqual(self.note(), "Sent")
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'idle'", timeout=6, what="back to idle")
        up = self.stub.posts()
        self.assertEqual([(r[1], r[2]) for r in up], [("/voice/audio", "audio/wav")], "the only request is the audio upload")
        body = up[0][3]
        self.assertEqual(body[:4], b"RIFF")
        self.assertEqual(body[8:16], b"WAVEfmt ")
        fmt, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[20:36])
        self.assertEqual((fmt, ch, rate, bits), (1, 1, 16000, 16))
        seconds = (len(body) - 44) / 2 / 16000
        self.assertTrue(0.9 < seconds < 3.0, seconds)
        samples = struct.unpack("<%dh" % ((len(body) - 44) // 2), body[44:])
        self.assertGreater(max(abs(s) for s in samples), 1000, "the fake microphone's audio arrived")
        self.assertEqual(self.stub.paths(), [("GET", "/voice/health"), ("POST", "/voice/audio")])

    def test_the_page_shows_only_a_microphone_and_a_light(self):
        self.open(Stub(answer=(200, {"ok": True, "state": "pending", "text": "SECRET transcript", "id": "p1"})))
        self.hold()
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'sent'", what="sent")
        self.assertEqual(self.page.js("document.querySelectorAll('#swarmbox-voice button').length"), 1)
        for gone in (".sv-card", ".sv-run", ".sv-btn", ".sv-risk", "textarea", "input"):
            self.assertEqual(self.page.js("document.querySelectorAll(%s).length" % json.dumps("#swarmbox-voice " + gone)), 0, gone)
        text = self.page.js("document.querySelector('#swarmbox-voice').innerText")
        self.assertNotIn("SECRET", text)
        self.assertNotIn("SECRET", self.page.js("document.documentElement.outerHTML"), "an extra field of the answer is never shown")
        self.assertEqual(text.strip(), "Sent")

    def test_nothing_heard_is_its_own_light(self):
        self.open(Stub(answer=(200, {"ok": True, "state": "nothing_heard"})))
        self.hold()
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'nothing'", what="nothing heard")
        self.assertEqual(self.note(), "Nothing heard")
        self.assertEqual(len(self.stub.posts()), 1)

    def test_a_service_error_is_a_short_sentence_in_the_light(self):
        self.open(Stub(answer=(422, {"error": "stt_failed", "message": "The speech recognizer failed."})))
        self.hold()
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'error'", what="error")
        self.assertEqual(self.note(), "The speech recognizer failed.")
        # and the next try works (the page is not stuck)
        self.stub.answer = (200, {"ok": True, "state": "pending"})
        self.hold()
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'sent'", what="sent after an error")
        self.assertEqual(len(self.stub.posts()), 2)

    def test_text_from_the_service_is_text_not_markup(self):
        self.open(Stub(answer=(422, {"error": "x", "message": HOSTILE})))
        self.hold()
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'error'", what="error")
        time.sleep(0.4)
        self.assertFalse(self.page.js("'__pwn' in window"), "no handler or script ran")
        self.assertEqual(self.page.js("document.querySelectorAll('#swarmbox-voice img, #swarmbox-voice script').length"), 0)
        self.assertIn("<img src=x", self.note())

    def test_a_denied_microphone_gives_a_short_message(self):
        self.open(Stub(), init_script="navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('no', 'NotAllowedError'));")
        self.wait("!!document.querySelector('#swarmbox-voice-mic')")
        self.click("#swarmbox-voice-mic")
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'error'", what="a message")
        self.assertEqual(self.note(), "Microphone blocked. Allow it in the site settings.")
        self.assertEqual(self.stub.posts(), [])

    def test_a_browser_without_a_microphone_api_says_so(self):
        self.open(Stub(), init_script="Object.defineProperty(navigator, 'mediaDevices', {value: undefined});")
        self.wait("!!document.querySelector('#swarmbox-voice-mic')")
        self.assertEqual(self.page.js("document.querySelector('#swarmbox-voice').dataset.support"), "no")
        self.click("#swarmbox-voice-mic")
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'error'")
        self.assertIn("cannot record", self.note())

    def test_a_tap_that_is_too_short_sends_nothing(self):
        self.open(Stub())
        self.wait("!!document.querySelector('#swarmbox-voice-mic')")
        x, y = self.center("#swarmbox-voice-mic")
        self.mouse("mousePressed", x, y)
        self.mouse("mouseReleased", x, y)
        time.sleep(1.0)
        self.assertEqual(self.stub.posts(), [])
        self.assertNotEqual(self.state(), "recording")

    def test_touch_hold_works_and_everything_fits_a_phone(self):
        self.open(Stub(answer=(422, {"error": "x", "message": "The recording is too long to be sent from this phone, try a shorter one."})),
                  width=360, height=640, touch=True)
        self.wait("!!document.querySelector('#swarmbox-voice-mic')")
        x, y = self.center("#swarmbox-voice-mic")
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'recording'", what="recording by touch")
        time.sleep(1.3)
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        self.wait("document.querySelector('#swarmbox-voice').dataset.state === 'error'", what="the error light")
        self.assertEqual(len(self.stub.posts()), 1)
        geo = self.page.js("""(() => { const out = {w: innerWidth, h: innerHeight, scroll: document.documentElement.scrollWidth};
          for (const sel of ['.sv-mic', '.sv-note']) { const b = document.querySelector(sel).getBoundingClientRect();
            out[sel] = {left: b.left, right: b.right, top: b.top, bottom: b.bottom, w: b.width, h: b.height}; }
          return out; })()""")
        for sel in (".sv-mic", ".sv-note"):
            b = geo[sel]
            self.assertGreaterEqual(b["left"], 0, sel)
            self.assertLessEqual(b["right"], geo["w"], sel)
            self.assertGreaterEqual(b["top"], 0, sel)
            self.assertLessEqual(b["bottom"], geo["h"], sel)
        self.assertLessEqual(geo["scroll"], geo["w"], "no horizontal scroll")
        self.assertGreaterEqual(min(geo[".sv-mic"]["w"], geo[".sv-mic"]["h"]), 44, "a touch target")
        self.assertLess(geo[".sv-note"]["bottom"], geo[".sv-mic"]["top"], "the sentence is above the button, not on it")


if __name__ == "__main__":
    unittest.main()
