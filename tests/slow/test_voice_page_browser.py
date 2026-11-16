#!/usr/bin/env python3
"""The voice control of the web page (container/addons/voice/web/page.js and page.css) in headless Chromium.

No network, no model and no real microphone: Chromium reads a WAV file made here with the wave module (--use-fake-device-for-media-stream,
--use-fake-ui-for-media-stream, --use-file-for-fake-audio-capture), and a STUB voice service on 127.0.0.1 answers the page (health and audio only) and
records every request. The page that carries page.js is a stub terminal page with the real strip script and styles of the host page.

The page is the microphone and a state light: voice is an input, the audio becomes a goal on the bus. Covers: the button appears only when the service
answers; hold records and POSTs a 16 kHz mono 16-bit WAV to /voice/audio and nothing else; the light goes recording, sending, sent, idle (or nothing
heard, nobody listening, busy, bus down, or an error with a short sentence) and the next try works; the page shows no card, no plan, no transcript, no
Run/Edit/Cancel; text of an error is shown as text; losing the focus ends the recording; a tap that is too short, a denied or missing microphone give a
short message; touch works and it fits a phone. The source of the page is also checked without a browser in tests/fast/test_voice_page.py.

Run in a container (sh dev/test-slow.sh): SWARMBOX_TEST_REAL_TMUX=1 python3 tests/slow/test_voice_page_browser.py
"""
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import browser_support as bs  # noqa: E402
from helpers import ROOT  # noqa: E402
from waiting import wait_until  # noqa: E402

WEB = os.path.join(ROOT, "container", "addons", "voice", "web")
HOST = os.path.join(ROOT, "container", "web")

HOSTILE = '<img src=x onerror="window.__pwn=1"><script>window.__pwn=2</script>'
MIC = "document.querySelector('#swarmbox-voice-mic')"
OK = (200, {"ok": True, "state": "sent"})

BASE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>stub terminal</title><style>html,body{margin:0;height:100%%;background:#0c0b10}#terminal-container{height:100%%}%s%s</style></head>
<body><div id="terminal-container"><div id="terminal" style="height:100%%"></div></div><script>%s</script><script>%s</script></body></html>"""


def make_wav(path, seconds=3.0, rate=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))))


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


class Stub:
    """A stub voice service plus a page that carries the real page.js and page.css. answer: (status, body) of POST /voice/audio. While `gate` is
    cleared the answer is held back, so a test can look at the light while the audio is being sent."""

    def __init__(self, healthy=True, answer=OK):
        self.healthy = healthy
        self.answer = answer
        self.gate = threading.Event()
        self.gate.set()
        self.requests = []   # (method, path, content type, body bytes)
        self.lock = threading.Lock()
        stub = self
        # the controls strip is part of the HOST page: the real one is in the stub page, as build-index.sh puts it in ttyd's
        self.page = (BASE_PAGE % (read(HOST, "ttyd-style.css"), read(WEB, "page.css"), read(HOST, "ttyd-clipboard.js"), read(WEB, "page.js"))).encode()

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
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                with stub.lock:
                    stub.requests.append(("POST", self.path, self.headers.get("Content-Type", ""), body))
                if self.path == "/voice/audio":
                    stub.gate.wait(10)
                    return self.send(*stub.answer)
                self.send(404, {"error": "no"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.gate.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def posts(self):
        with self.lock:
            return [r for r in self.requests if r[0] == "POST"]

    def paths(self):
        with self.lock:
            return sorted({(r[0], r[1]) for r in self.requests if r[1] not in ("/", "/favicon.ico")})


@bs.chromium_tests()
class VoicePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="swarmbox-test-voicepage-")
        wav = os.path.join(cls.tmp, "speech.wav")
        make_wav(wav)
        cls.chromium = bs.Chromium(extra=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                          "--use-file-for-fake-audio-capture=" + wav, "--autoplay-policy=no-user-gesture-required"])

    @classmethod
    def tearDownClass(cls):
        cls.chromium.close()
        __import__("shutil").rmtree(cls.tmp, ignore_errors=True)

    def open(self, stub, init_script="", width=1000, height=700, touch=False):
        self.stub = stub
        self.addCleanup(stub.close)
        self.page, tid = self.chromium.tab()
        self.addCleanup(self.chromium.close_tab, self.page, tid)
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=touch)
        if touch:
            self.page.call("Emulation.setTouchEmulationEnabled", enabled=True)
        if init_script:
            self.page.call("Page.addScriptToEvaluateOnNewDocument", source=init_script)
        self.page.call("Page.navigate", url="http://127.0.0.1:%d/" % stub.port)

    def button(self):
        self.assertTrue(self.page.wait_js("!!" + MIC, 15), "the mic button never appeared")

    def wait_state(self, *states, seconds=10):
        want = "[%s].includes(%s.dataset.state)" % (", ".join(json.dumps(s) for s in states), MIC)
        self.assertTrue(self.page.wait_js(want, seconds), "the light never became %s: it is %r" % (states, self.page.js(MIC + ".dataset.state")))

    def center(self, selector):
        return self.page.js("(() => { const b = document.querySelector(%s).getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()"
                            % json.dumps(selector))

    def press(self):
        self.button()
        x, y = self.center("#swarmbox-voice-mic")
        self.page.mouse("mousePressed", x, y)
        self.wait_state("recording")
        return x, y

    def hold(self, seconds=0.45):
        """Hold the button while the fake microphone speaks, then let go."""
        x, y = self.press()
        time.sleep(seconds)
        self.page.mouse("mouseReleased", x, y)

    def state(self):
        return self.page.js(MIC + ".dataset.state")

    def note(self):
        return self.page.js("(() => { const n = document.querySelector('#swarmbox-strip .sb-note'); return n.hidden ? '' : n.textContent; })()")

    def test_the_button_is_absent_when_the_service_is_absent(self):
        self.open(Stub(healthy=False))
        self.assertTrue(wait_until(lambda: ("GET", "/voice/health") in self.stub.paths(), 15, 0.05), "the page never asked the service")
        self.page.js("new Promise(done => setTimeout(done, 200))", wait=True)   # time for a page that would build the button anyway
        self.assertFalse(self.page.js("!!" + MIC))
        self.assertTrue(self.page.js("!!document.querySelector('#terminal')"), "the terminal is untouched")

    def test_hold_records_and_posts_a_wav_the_light_goes_recording_sending_sent_idle_and_nothing_else_is_requested(self):
        self.open(Stub())
        self.stub.gate.clear()
        self.button()
        self.assertEqual(self.state(), "idle")
        x, y = self.press()
        self.assertEqual(self.note(), "Listening")
        time.sleep(0.6)
        self.page.mouse("mouseReleased", x, y)
        self.wait_state("sending")
        self.assertEqual(self.note(), "Sending")
        self.stub.gate.set()
        self.wait_state("sent")
        self.assertEqual(self.note(), "Sent")
        up = self.stub.posts()
        self.assertEqual([(r[1], r[2]) for r in up], [("/voice/audio", "audio/wav")], "the only request is the audio upload")
        body = up[0][3]
        self.assertEqual((body[:4], body[8:16]), (b"RIFF", b"WAVEfmt "))
        fmt, ch, rate, _, _, bits = struct.unpack("<HHIIHH", body[20:36])
        self.assertEqual((fmt, ch, rate, bits), (1, 1, 16000, 16))
        seconds = (len(body) - 44) / 2 / 16000
        self.assertTrue(0.3 < seconds < 3.0, seconds)
        samples = struct.unpack("<%dh" % ((len(body) - 44) // 2), body[44:])
        self.assertGreater(max(abs(s) for s in samples), 1000, "the fake microphone's audio arrived")
        self.assertEqual(self.stub.paths(), [("GET", "/voice/health"), ("POST", "/voice/audio")])

    def test_the_light_goes_back_to_idle_by_itself_2_5_seconds_after_sent(self):
        # the clock is shortened here (only that one) and the length the page asked for is read back
        self.open(Stub(), init_script="window.__t = []; const st = window.setTimeout;"
                                      " window.setTimeout = (f, ms, ...a) => { window.__t.push(ms); return st(f, ms === 2500 ? 50 : ms, ...a); };")
        self.hold()
        self.assertTrue(self.page.wait_js("window.__t.includes(2500) && %s.dataset.state === 'idle'" % MIC, 10), self.state())
        self.assertEqual(len(self.stub.posts()), 1)

    def test_the_page_shows_only_a_microphone_and_a_light_never_the_text_of_the_answer(self):
        self.open(Stub(answer=(200, {"ok": True, "state": "sent", "text": "SECRET transcript", "id": "p1"})))
        self.hold()
        self.wait_state("sent")
        self.assertEqual(self.page.js("document.querySelectorAll('#swarmbox-strip button').length"), 1)
        for gone in (".sv-card", ".sv-run", ".sv-btn", ".sv-risk", "textarea", "input"):
            self.assertEqual(self.page.js("document.querySelectorAll(%s).length" % json.dumps("#swarmbox-strip " + gone)), 0, gone)
        text = self.page.js("document.querySelector('#swarmbox-strip').innerText")
        self.assertEqual(text.strip(), "Sent")
        self.assertNotIn("SECRET", self.page.js("document.documentElement.outerHTML"), "an extra field of the answer is never shown")

    ANSWERS = (   # what the service answers -> the light and its sentence
        ("nothing heard", (200, {"ok": False, "state": "nothing_heard", "message": "Nothing heard."}), "nothing", "Nothing heard"),
        ("nobody listens", (503, {"ok": False, "state": "no_listener", "message": "ignored: the page has its own sentence"}), "nolistener", "Nobody is listening"),
        ("busy", (503, {"ok": False, "state": "busy", "message": "x"}), "busy", None),
        ("bus down", (503, {"ok": False, "state": "bus_down", "message": "x"}), "error", "The bus of the box is not answering."),
        ("an unknown state", (200, {"ok": True, "state": "SECRET-state"}), "error", None),
        ("a service error", (422, {"error": "stt_failed", "message": "The speech recognizer failed."}), "error", "The speech recognizer failed."),
    )

    def test_every_answer_has_its_light_and_after_a_busy_or_an_error_the_next_try_works(self):
        self.open(Stub())   # one page for all the answers: the light is not busy any more once it shows one
        posts = 0
        for what, answer, state, note in self.ANSWERS:
            with self.subTest(what):
                self.stub.answer = answer
                self.hold()
                posts += 1
                self.wait_state(state)
                if note:
                    self.assertEqual(self.note(), note)
                self.assertNotIn("SECRET", self.note(), "an unknown state is never shown as text")
                self.assertEqual(len(self.stub.posts()), posts)
                if state in ("busy", "error"):
                    self.stub.answer = OK   # the page is not stuck
                    self.hold()
                    posts += 1
                    self.wait_state("sent")
                    self.assertEqual(len(self.stub.posts()), posts)

    def test_text_from_the_service_is_text_not_markup(self):
        self.open(Stub(answer=(422, {"error": "x", "message": HOSTILE})))
        self.hold()
        self.wait_state("error")
        self.assertIn("<img src=x", self.note())
        self.page.js("new Promise(done => setTimeout(done, 200))", wait=True)   # time for a handler to run if one was made
        self.assertFalse(self.page.js("'__pwn' in window"), "no handler or script ran")
        self.assertEqual(self.page.js("document.querySelectorAll('#swarmbox-strip img, #swarmbox-strip script').length"), 0)

    def test_losing_the_focus_ends_the_recording_and_sends_it(self):
        self.open(Stub())
        self.press()
        self.page.js(MIC + ".focus()")
        time.sleep(0.5)
        self.page.js(MIC + ".blur()")
        self.wait_state("sent")
        self.assertEqual(len(self.stub.posts()), 1)

    def test_a_tap_that_is_too_short_sends_nothing(self):
        self.open(Stub())
        self.button()
        x, y = self.center("#swarmbox-voice-mic")
        self.page.mouse("mousePressed", x, y)
        self.page.mouse("mouseReleased", x, y)
        self.assertTrue(self.page.wait_js("!['starting', 'recording'].includes(%s.dataset.state)" % MIC, 10), "the page is still starting to record")
        self.assertIn(self.state(), ("idle", "error"))
        self.assertEqual(self.stub.posts(), [])

    def test_a_denied_microphone_and_a_browser_without_the_api_give_a_short_message_and_send_nothing(self):
        self.open(Stub(), init_script="navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('no', 'NotAllowedError'));")
        self.button()
        x, y = self.center("#swarmbox-voice-mic")
        self.page.mouse("mousePressed", x, y)
        self.page.mouse("mouseReleased", x, y)
        self.wait_state("error")
        self.assertEqual(self.note(), "Microphone blocked. Allow it in the site settings.")
        self.assertEqual(self.stub.posts(), [])
        self.open(Stub(), init_script="Object.defineProperty(navigator, 'mediaDevices', {value: undefined});")
        self.button()
        self.assertEqual(self.page.js(MIC + ".dataset.support"), "no")
        x, y = self.center("#swarmbox-voice-mic")
        self.page.mouse("mousePressed", x, y)
        self.page.mouse("mouseReleased", x, y)
        self.wait_state("error")
        self.assertIn("cannot record", self.note())
        self.assertEqual(self.stub.posts(), [])

    def test_touch_hold_works_and_everything_fits_a_phone(self):
        self.open(Stub(answer=(422, {"error": "x", "message": "The recording is too long to be sent from this phone, try a shorter one."})),
                  width=360, height=640, touch=True)
        self.button()
        x, y = self.center("#swarmbox-voice-mic")
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        self.wait_state("recording")
        time.sleep(0.6)
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        self.wait_state("error")
        self.assertEqual(len(self.stub.posts()), 1)
        geo = self.page.js("""(() => { const out = {w: innerWidth, h: innerHeight, scroll: document.documentElement.scrollWidth};
          for (const sel of ['#swarmbox-voice-mic', '#swarmbox-strip .sb-note', '#swarmbox-strip', '#terminal-container']) { const b = document.querySelector(sel).getBoundingClientRect();
            out[sel] = {left: b.left, right: b.right, top: b.top, bottom: b.bottom, w: b.width, h: b.height}; }
          return out; })()""")
        for sel in ("#swarmbox-voice-mic", "#swarmbox-strip .sb-note"):
            b = geo[sel]
            self.assertGreaterEqual(b["left"], 0, sel)
            self.assertLessEqual(b["right"], geo["w"], sel)
            self.assertGreaterEqual(b["top"], 0, sel)
            self.assertLessEqual(b["bottom"], geo["h"], sel)
        self.assertLessEqual(geo["scroll"], geo["w"], "no horizontal scroll")
        self.assertGreaterEqual(min(geo["#swarmbox-voice-mic"]["w"], geo["#swarmbox-voice-mic"]["h"]), 44, "a touch target")
        mic, strip, term = geo["#swarmbox-voice-mic"], geo["#swarmbox-strip"], geo["#terminal-container"]
        self.assertGreaterEqual(mic["top"], strip["top"], "the microphone is in the strip")
        self.assertLessEqual(mic["bottom"], strip["bottom"])
        self.assertLessEqual(term["bottom"], strip["top"] + 0.5, "the strip is below the terminal and covers none of it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
