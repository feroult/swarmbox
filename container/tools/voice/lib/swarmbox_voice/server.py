"""The voice HTTP service: audio -> text (Whisper) -> a goal on the bus. Stdlib only, loopback only. Voice is an INPUT: it hears and publishes,
it never plans, shows or executes anything, and it does not know who handles the goal (whoever subscribes to the topic).

Endpoints (under /voice/, answers are JSON, no caching):
  GET  /voice/health   {"ok": true, "language", "model"}
  POST /voice/audio    body: 16 kHz mono 16-bit WAV (Content-Type audio/wav). Transcribes, publishes {"text": ...} on the bus topic of the setting voice.topic (default goal) with
                       source `voice`, and answers ONLY a state, with a fixed text, never the transcript and never text from a pane:
                         200 {"ok": true,  "state": "sent"}
                         200 {"ok": false, "state": "nothing_heard"}       nothing recognized
                         503 {"ok": false, "state": "no_listener"}         the bus has no subscriber on the topic
                         503 {"ok": false, "state": "busy"}                the subscriber is busy with another goal
                         503 {"ok": false, "state": "bus_down"}            the bus does not answer
                       and each of those also has a fixed "message". A failure of the recognizer is {"error": code, "message": fixed text}
                       with 400 (bad audio), 413, 422, 502 (recognizer or model missing), 403 (host or origin), 415.
Only /voice/health and /voice/audio (and the two page files, served by the front) are reachable from the web: the front forwards nothing else.
Everything else answers 404 (405 for a listed path with the wrong method).

The listener binds only to a loopback address. Every request needs a Host of a loopback name (or one given in allow_hosts) and, when it has an
Origin, an Origin whose host is the Host (no cross-site calls, no DNS rebinding); POST needs the audio content type, which a cross-site form
cannot send, and OPTIONS is refused, so a page of another origin cannot even preflight. The audio is not kept: it lives in a private temporary
folder while Whisper runs.
"""
import json
import os
import re
import sys
import tempfile
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import busclient
from . import config as vconfig
from . import stt

MAX_GOAL = 4000           # characters of one goal; a longer transcript is cut
AUDIO_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
# what /voice/audio says when it fails: fixed texts by error code, never the text of the error itself (it could hold the transcript)
AUDIO_MESSAGES = {"stt_bad_audio": "The audio could not be read.", "stt_too_large": "The recording is too long.",
                  "stt_no_whisper": "The speech recognizer is not installed.", "stt_no_model": "The speech model is missing.",
                  "stt_failed": "The speech recognizer failed.", "stt_timeout": "The speech recognizer took too long."}
# the states of a goal that was not sent, by name: (HTTP status, fixed message). "sent" is the only ok one.
STATES = {"nothing_heard": (200, "Nothing heard."),
          "no_listener": (503, "Nobody is listening."),
          "busy": (503, "The listener is busy."),
          "bus_down": (503, "The bus of the box is not answering.")}
LOOPBACK = ("127.0.0.1", "localhost", "[::1]", "::1")


class HttpError(Exception):
    def __init__(self, status, code, message):
        Exception.__init__(self, message)
        self.status, self.code, self.message = status, code, message


class Service:
    """The logic, without HTTP. The outside dependencies can be replaced (tests do): the recognizer and the publisher of goals."""

    def __init__(self, cfg=None, transcribe=None, publish=None, log=None):
        self.cfg = cfg or vconfig.load(os.environ)
        self.transcribe_fn = transcribe or stt.transcribe
        self.publish_fn = publish or (lambda text: busclient.publish(self.cfg.topic, text))
        self.log = log or (lambda text: print("swarmbox-voice: " + text, file=sys.stderr, flush=True))

    def health(self):
        return {"ok": True, "language": self.cfg.language, "model": self.cfg.stt_model}

    def transcribe(self, wav):
        """WAV bytes -> text. The audio lives in a private temporary folder only while the recognizer runs."""
        try:
            stt.check_wav(wav)
            stt.check_speech(wav)
            with tempfile.TemporaryDirectory(prefix="swarmbox-voice-") as folder:
                path = os.path.join(folder, "audio.wav")
                with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
                    f.write(wav)
                return self.transcribe_fn(path, self.cfg.language, self.cfg.stt_model, self.cfg.stt_vocabulary)
        except stt.SttError as e:
            status = {"too_large": 413, "bad_audio": 400, "no_speech": 422, "no_whisper": 502, "no_model": 502}.get(e.code, 422)
            raise HttpError(status, "stt_" + e.code, e.message) from None

    def state(self, name):
        """The answer for a state: (status, body)."""
        if name == "sent":
            return 200, {"ok": True, "state": "sent"}
        status, message = STATES[name]
        return status, {"ok": False, "state": name, "message": message}

    def goal(self, text):
        """Publish `text` as a goal. Returns the state: sent, nothing_heard, no_listener, busy or bus_down."""
        # invisible format characters (zero-width, direction marks, ZWJ) are common in transcripts
        text = "".join(" " if unicodedata.category(c) == "Cc" else c for c in text if unicodedata.category(c) != "Cf")
        text = " ".join(text.split())
        if not text:
            return "nothing_heard"
        return self.publish_fn(text[:MAX_GOAL])

    def audio(self, wav):
        """WAV -> text -> goal on the bus, one call. Returns (status, body); the body is a state and never the transcript."""
        try:
            text = self.transcribe(wav)
        except HttpError as e:
            if e.code == "stt_no_speech":
                return self.state("nothing_heard")
            raise HttpError(e.status, e.code, AUDIO_MESSAGES.get(e.code, "The speech could not be recognized.")) from None
        name = self.goal(text)
        if name != "sent":
            self.log("audio: the goal was not sent (%s)" % name)
        return self.state(name)


def _host_of(netloc):
    netloc = netloc.strip().lower()
    return netloc.rsplit(":", 1)[0] if re.search(r":\d+$", netloc) else netloc


def make_handler(service, allow_hosts=()):
    allowed = set(LOOPBACK) | {h.lower() for h in allow_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "swarmbox-voice"
        sys_version = ""
        protocol_version = "HTTP/1.0"   # one request per connection

        def log_message(self, fmt, *args):   # no access log: URLs and timing only, but quiet is better in a terminal box
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self):
            host = self.headers.get("Host", "")
            if _host_of(host) not in allowed:
                raise HttpError(403, "bad_host", "this Host is not allowed")
            origin = self.headers.get("Origin")
            if origin is not None and urlsplit(origin).netloc.lower() != host.strip().lower():
                raise HttpError(403, "bad_origin", "cross-origin calls are not allowed")

        def _body(self, limit, types):
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in types:
                raise HttpError(415, "bad_content_type", "Content-Type must be one of: " + ", ".join(types))
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise HttpError(411, "length_required", "Content-Length is required") from None
            if length < 0 or length > limit:
                raise HttpError(413, "too_large", "the body is larger than %d bytes" % limit)
            data = self.rfile.read(length)
            if len(data) != length:
                raise HttpError(400, "bad_request", "the body is incomplete")
            return data

        def _route(self, method):
            self._guard()
            path = urlsplit(self.path).path
            if method == "GET" and path == "/voice/health":
                return 200, service.health()
            if method == "POST" and path == "/voice/audio":
                return service.audio(self._body(stt.MAX_WAV_BYTES, AUDIO_TYPES))
            if path in ("/voice/health", "/voice/audio"):
                raise HttpError(405, "not_found", "no such endpoint or method")
            raise HttpError(404, "not_found", "no such endpoint")

        def _handle(self, method):
            try:
                status, obj = self._route(method)
                self._send(status, obj)
            except HttpError as e:
                self._send(e.status, {"error": e.code, "message": e.message})
            except Exception:   # never leak a traceback to the client
                self._send(500, {"error": "internal", "message": "internal error"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self._send(405, {"error": "no_cors", "message": "cross-origin calls are not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A browser that gives up while Whisper runs leaves a broken connection: that is not an error worth a traceback."""
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def is_loopback(host):
    return host in ("127.0.0.1", "localhost")


def make_server(service, host="127.0.0.1", port=0, allow_hosts=()):
    """A bound (not yet serving) HTTP server. Refuses any address that is not loopback."""
    if not is_loopback(host):
        raise ValueError("the voice service listens only on a loopback address, not %r" % host)
    if host == "localhost":
        host = "127.0.0.1"
    return _Server((host, port), make_handler(service, allow_hosts))
