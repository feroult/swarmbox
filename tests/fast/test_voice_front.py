"""The voice front (container/addons/voice/lib/swarmbox_voice/front.py): routing, the same-origin rules, caps, the terminal pass-through
and the life of its two children. Fakes: tests/support/fixtures/voice/fake-web-server.py (a page, a big body, websocket echo, the same-origin rule) and a stub
service in this process. The process tests run the real command `swarmbox-voice front` (with the real service, whose /voice/health
needs no model). The front is an AUDIO ENTRY with a fixed table (health, audio): the tests pin that
table, that every other /voice/ path is refused by the front and never reaches the service, and that the answers are filtered.
Run with: python3 -W error tests/fast/test_voice_front.py
"""
import concurrent.futures
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import voice_support  # noqa: E402
from waiting import wait_until  # noqa: E402

from swarmbox_voice import front, stt  # noqa: E402

FAKE_SERVER = os.path.join(voice_support.FIXTURES, "fake-web-server.py")
LIB = os.path.join(voice_support.VOICE, "lib")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return True
        except OSError:
            time.sleep(0.005)
    return False


def exchange(port, request, timeout=15, half_close=False):
    """Send bytes, read until the server closes: (status, headers dict lower-cased, body)."""
    c = socket.create_connection(("127.0.0.1", port), timeout)
    try:
        c.sendall(request)
        if half_close:
            c.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            try:
                d = c.recv(65536)
            except (ConnectionResetError, socket.timeout):
                break
            if not d:
                break
            data += d
    finally:
        c.close()
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1]) if lines and lines[0] else 0
    hdrs = {}
    for l in lines[1:]:
        k, _, v = l.partition(":")
        hdrs[k.strip().lower()] = v.strip()
    return status, hdrs, body


def get(port, path, host=None, extra=""):
    host = host or "127.0.0.1:%d" % port
    return exchange(port, ("GET %s HTTP/1.1\r\nHost: %s\r\n%s\r\n" % (path, host, extra)).encode())


def post(port, path, body, ctype="application/json", host=None, extra=""):
    host = host or "127.0.0.1:%d" % port
    head = "POST %s HTTP/1.1\r\nHost: %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n%s\r\n" % (path, host, ctype, len(body), extra)
    return exchange(port, head.encode() + body)


class Stub:
    """The voice service as the front sees it: records requests, answers JSON."""

    def __init__(self):
        self.seen = []
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def handle_any(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                stub.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
                if body.startswith(b"SLOW"):
                    time.sleep(3)
                if body.startswith(b"GARBAGE"):
                    self.wfile.write(b"this is not http")
                    return
                if body.startswith(b"NOTJSON"):
                    out = b"<html>no</html>"
                    self.send_response(200)
                elif body.startswith(b"TEAPOT"):
                    out = json.dumps({"error": "x", "message": "short and stout", "text": "LEAK-transcript", "plan": {"actions": []}}).encode()
                    self.send_response(418)
                elif body.startswith(b"NOLISTENER"):
                    out = json.dumps({"ok": False, "state": "no_listener", "message": "Nobody is listening.",
                                      "text": "LEAK-transcript", "goal": {"text": "LEAK-goal"}, "id": 7}).encode()
                    self.send_response(503)
                else:
                    # more than the front may pass on: it must keep only ok/state/error/message (audio) or ok (health)
                    out = json.dumps({"ok": True, "state": "sent", "len": len(body), "planner": "claude", "pending": 1,
                                      "text": "LEAK-transcript", "id": "LEAK-id", "actions": [{"text": "LEAK-command"}]}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def do_GET(self):
                try:
                    self.handle_any()
                except OSError:   # the front gave up on a slow answer
                    pass

            do_POST = do_GET

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FrontCase(unittest.TestCase):
    """A Front in this process in front of a fake web server (subprocess) and a stub service."""

    with_server = True

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="voice-front-")
        cls._log = os.path.join(cls._tmp, "server.log")
        cls._stub = Stub()
        cls._server_port = free_port()
        cls._server = None
        if cls.with_server:
            cls._server = subprocess.Popen([sys.executable, FAKE_SERVER, "-p", str(cls._server_port), "-i", "127.0.0.1", "-O"],
                                           env=dict(os.environ, FAKE_SERVER_LOG=cls._log))
            if not wait_port(cls._server_port):
                cls._server.kill()
                cls._server.wait()
                raise RuntimeError("fake server did not start")
        cls._front = front.Front(("127.0.0.1", 0), ("127.0.0.1", cls._server_port), ("127.0.0.1", cls._stub.port))
        cls._port = cls._front.address[1]
        threading.Thread(target=cls._front.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls._front.close()
        if cls._server is not None:
            cls._server.kill()
            cls._server.wait()
        cls._stub.close()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.tmp = self._tmp
        self.log = self._log
        self.stub = self._stub
        self.server_port = self._server_port
        self.server = self._server
        self.front = self._front
        self.port = self._port
        self.stub.seen.clear()
        if os.path.exists(self.log):
            open(self.log, "w").close()

    def heads(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l)["head"] for l in f.read().splitlines()]


class TerminalPath(FrontCase):
    def test_a_plain_request_reaches_the_server_with_connection_close_and_nothing_else_changed(self):
        status, _, body = get(self.port, "/", extra="Connection: keep-alive\r\nUser-Agent: x\r\nAccept: text/html\r\n")
        self.assertEqual(status, 200)
        self.assertIn(b"fake terminal page", body)
        head = self.heads()[-1].split("\r\n")
        self.assertEqual(head[0], "GET / HTTP/1.1")
        self.assertEqual(head[1:], ["Host: 127.0.0.1:%d" % self.port, "User-Agent: x", "Accept: text/html", "Connection: close"])

    def test_no_other_origin_may_frame_a_page_of_the_terminal_nor_an_answer_of_voice(self):
        want = ("content-security-policy", "frame-ancestors 'self'"), ("x-frame-options", "SAMEORIGIN")
        for status, hdrs, _ in (get(self.port, "/"), get(self.port, "/voice/health"), get(self.port, "/nothing-here/at-all")):
            for k, v in want:
                self.assertEqual(hdrs.get(k), v, (status, hdrs))

    def test_connection_close_is_added_when_the_client_sent_none(self):
        get(self.port, "/")
        self.assertEqual(self.heads()[-1].split("\r\n")[-1], "Connection: close")
        self.assertEqual(self.heads()[-1].lower().count("connection:"), 1)

    def test_a_websocket_upgrade_is_passed_through_untouched_and_echoes(self):
        req = ("GET /ws HTTP/1.1\r\nHost: h.example:7681\r\nOrigin: http://h.example:7681\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
        c = socket.create_connection(("127.0.0.1", self.port), 10)
        self.addCleanup(c.close)
        c.sendall(req.encode())
        got = b""
        while b"\r\n\r\n" not in got:
            got += c.recv(4096)
        self.assertTrue(got.startswith(b"HTTP/1.1 101"), got)
        self.assertIn(b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", got)
        self.assertEqual(self.heads()[-1] + "\r\n\r\n", req, "the head reaches the server byte for byte")
        payload = os.urandom(300000)
        c.sendall(payload)
        echoed = b""
        c.settimeout(10)
        while len(echoed) < len(payload):
            echoed += c.recv(65536)
        self.assertEqual(echoed, payload)
        c.shutdown(socket.SHUT_WR)   # half close: the server sees the end and closes its side, so we see EOF
        self.assertEqual(c.recv(10), b"")

    def test_the_server_origin_rule_sees_the_original_host_and_origin(self):
        self.assertEqual(get(self.port, "/", host="a.example", extra="Origin: http://a.example\r\n")[0], 200)
        self.assertEqual(get(self.port, "/", host="a.example", extra="Origin: http://evil.example\r\n")[0], 403)

    def test_a_big_body_comes_through_whole(self):
        status, _, body = get(self.port, "/big")
        self.assertEqual((status, len(body)), (200, 5 * 1024 * 1024))

    def test_a_large_post_body_to_terminal_does_not_deadlock(self):
        # Upstream HTTP server waits to read the full 256 KiB POST body before answering:
        # front._terminal must pump request bytes concurrently while guarding the response head.
        import http.server
        received = []

        class PostHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                received.append(len(self.rfile.read(n)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *args):
                pass

        up = http.server.HTTPServer(("127.0.0.1", 0), PostHandler)
        self.addCleanup(up.server_close)
        self.addCleanup(up.shutdown)
        threading.Thread(target=up.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

        f = front.Front(("127.0.0.1", 0), ("127.0.0.1", up.server_address[1]), ("127.0.0.1", self.stub.port))
        self.addCleanup(f.close)
        threading.Thread(target=f.serve_forever, daemon=True).start()

        payload = b"P" * (256 * 1024)
        t0 = time.monotonic()
        status, hdrs, body = post(f.address[1], "/api/paste-image", payload, "image/png")
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertEqual(status, 200)
        self.assertEqual(received, [len(payload)])
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(hdrs.get("x-frame-options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", hdrs.get("content-security-policy", ""))

    def test_half_closing_the_request_still_gets_the_answer(self):
        status, _, body = exchange(self.port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n", half_close=True)
        self.assertEqual(status, 200)
        self.assertIn(b"fake terminal", body)

    def test_head_limits(self):
        status, _, _ = exchange(self.port, b"GET / HTTP/1.1\r\nHost: x\r\nX: " + b"a" * 20000 + b"\r\n\r\n")
        self.assertEqual(status, 431)
        self.assertEqual(exchange(self.port, b"NOT A REQUEST\r\n\r\n")[0], 400)
        self.assertEqual(exchange(self.port, b"GET / HTTP/1.1\r\nbad header\r\n\r\n")[0], 400)

    def test_a_silent_client_is_cut_after_the_head_timeout(self):
        old = front.HEAD_TIMEOUT
        front.HEAD_TIMEOUT = 0.05
        self.addCleanup(setattr, front, "HEAD_TIMEOUT", old)
        t = time.time()
        c = socket.create_connection(("127.0.0.1", self.port), 5)
        self.addCleanup(c.close)
        c.sendall(b"GET / HT")
        data = c.recv(4096)
        self.assertIn(b" 408 ", data)
        self.assertLess(time.time() - t, 5)

    def test_connections_do_not_leak_threads(self):
        before = threading.active_count()
        for _ in range(30):
            get(self.port, "/")
            get(self.port, "/voice/health")
            exchange(self.port, b"garbage\r\n\r\n")
        self.assertTrue(wait_until(lambda: threading.active_count() <= before + 2, 3), "threads left: %d" % (threading.active_count() - before))


WAV = voice_support.wav_with("hello")
UNLISTED = ["/voice/run", "/voice/edit", "/voice/cancel", "/voice/pending", "/voice/pending?wait=5&since=x", "/voice/plan", "/voice/transcribe",
            "/voice/confirm", "/voice/", "/voice/page.js", "/voice/page.css", "/voice/page.js/", "/voice/health/", "/voice/audio/", "/voice/../voice/run", "/voice/%72un",
            "/voice/%61udio", "/voice/run?x=/voice/audio", "/voice/PAGE.JS", "/voice/health;x", "/voice/audio%2f", "/voice/a/../run",
            "/voice/page.js.map", "/voice/run#audio", "/voice/slow", "/voice/teapot"]


class VoicePath(FrontCase):
    def test_get_health_is_forwarded_rebuilt_and_only_ok_comes_back(self):
        status, hdrs, body = get(self.port, "/voice/health?x=1", host="voice-test.example:7681")
        self.assertEqual((status, json.loads(body)), (200, {"ok": True}))
        self.assertEqual(hdrs["cache-control"], "no-store")
        seen = self.stub.seen[-1]
        self.assertEqual(seen["path"], "/voice/health", "the query is dropped: the front rebuilds what it forwards")
        self.assertEqual(seen["headers"]["Host"], "127.0.0.1:%d" % self.stub.port)
        self.assertNotIn("Origin", seen["headers"])
        self.assertEqual(self.heads(), [], "the server saw nothing")
        self.assertNotIn(b"claude", body)

    def test_a_same_origin_origin_is_rewritten_to_the_service_loopback(self):
        status, _, _ = get(self.port, "/voice/health", host="voice-test.example:7681", extra="Origin: http://voice-test.example:7681\r\n")
        self.assertEqual(status, 200)
        self.assertEqual(self.stub.seen[-1]["headers"]["Origin"], "http://127.0.0.1:%d" % self.stub.port)

    def test_a_cross_origin_request_is_403_and_never_forwarded(self):
        for origin in ("http://evil.example", "http://voice-test.example:9999", "null"):
            status, _, body = get(self.port, "/voice/health", host="voice-test.example:7681", extra="Origin: %s\r\n" % origin)
            self.assertEqual(status, 403, origin)
            self.assertEqual(json.loads(body)["error"], "bad_origin")
        status, _, _ = post(self.port, "/voice/audio", WAV, "audio/wav", host="voice-test.example:7681", extra="Origin: http://evil.example\r\n")
        self.assertEqual(status, 403)
        status, _, _ = get(self.port, "/voice/health", extra="Origin: http://a\r\nOrigin: http://a\r\n")
        self.assertEqual(status, 403)
        self.assertEqual(self.stub.seen, [])

    def test_host_is_required_exactly_once(self):
        self.assertEqual(exchange(self.port, b"GET /voice/health HTTP/1.1\r\n\r\n")[0], 400)
        self.assertEqual(exchange(self.port, b"GET /voice/health HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n")[0], 400)
        self.assertEqual(self.stub.seen, [])

    def test_the_table_is_exactly_these_two_routes(self):
        self.assertEqual(front.ROUTES, {"/voice/health": "GET", "/voice/audio": "POST"})

    def test_the_front_exposes_only_audio(self):
        """Every other /voice/ path, with every method and with or without a JSON body, is refused by the FRONT: the service never sees it."""
        for path in UNLISTED:
            for method in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
                body = b'{"id": "x"}'
                req = "%s %s HTTP/1.1\r\nHost: h\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % (method, path, len(body))
                status, _, out = exchange(self.port, req.encode() + body)
                self.assertIn(status, (404, 405), (method, path, status))
                self.assertNotIn(b"LEAK", out)
        for path in ("/voice/run", "/voice/pending", "/voice/plan", "/voice/edit", "/voice/cancel", "/voice/transcribe"):
            # even a cross-origin or host-less request is answered 404 by the table, not forwarded for the service to judge
            self.assertEqual(get(self.port, path, host="x", extra="Origin: http://evil.example\r\n")[0], 404, path)
            self.assertEqual(exchange(self.port, ("GET %s HTTP/1.1\r\n\r\n" % path).encode())[0], 404, path)
            self.assertEqual(post(self.port, path, b"{}")[0], 404, path)
            self.assertEqual(post(self.port, path, WAV, "audio/wav")[0], 404, path)
        self.assertEqual(self.stub.seen, [], "the service saw nothing at all")
        self.assertEqual(self.heads(), [], "and neither did the server")

    def test_the_two_routes_with_the_wrong_method_are_refused(self):
        for method, path in (("POST", "/voice/health"), ("GET", "/voice/audio"),
                             ("PUT", "/voice/audio"), ("DELETE", "/voice/health"), ("OPTIONS", "/voice/audio"), ("HEAD", "/voice/health")):
            req = ("%s %s HTTP/1.1\r\nHost: h\r\nOrigin: http://h\r\nAccess-Control-Request-Method: POST\r\nContent-Length: 0\r\n\r\n"
                   % (method, path)).encode()
            self.assertEqual(exchange(self.port, req)[0], 405, (method, path))
        self.assertEqual(self.stub.seen, [])

    def test_audio_needs_a_wav_content_type(self):
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "application/json", ""):
            self.assertEqual(post(self.port, "/voice/audio", b"{}", ctype)[0], 415, ctype)
        for ctype in ("audio/wav", "audio/x-wav", "audio/wave", "audio/wav; codecs=1"):
            self.assertEqual(post(self.port, "/voice/audio", WAV, ctype)[0], 200, ctype)
        self.assertEqual(len(self.stub.seen), 4)

    def test_audio_is_forwarded_whole_and_only_ok_and_state_come_back(self):
        wav = voice_support.wav_with("x" * 100000)
        status, hdrs, out = post(self.port, "/voice/audio", wav, "audio/x-wav")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out), {"ok": True, "state": "sent"})
        self.assertNotIn(b"LEAK", out, "a transcript, a goal or an id never comes back through the front")
        self.assertEqual(hdrs["cache-control"], "no-store")
        seen = self.stub.seen[0]
        self.assertEqual((seen["path"], seen["body"]), ("/voice/audio", wav))
        self.assertEqual(seen["headers"]["Content-Type"], "audio/x-wav")

    def test_an_error_answer_keeps_its_status_and_only_error_and_message(self):
        status, _, out = post(self.port, "/voice/audio", b"TEAPOT" + WAV, "audio/wav")
        self.assertEqual((status, json.loads(out)), (418, {"error": "x", "message": "short and stout"}))

    def test_a_state_that_is_not_ok_keeps_its_status_state_and_message_and_nothing_else(self):
        status, _, out = post(self.port, "/voice/audio", b"NOLISTENER" + WAV, "audio/wav")
        self.assertEqual((status, json.loads(out)), (503, {"ok": False, "state": "no_listener", "message": "Nobody is listening."}))
        self.assertNotIn(b"LEAK", out)

    def test_the_answer_filter_is_exactly_the_keys_of_the_new_answer(self):
        self.assertEqual(front.PASS_KEYS, {"/voice/health": ("ok",), "/voice/audio": ("ok", "state", "error", "message")})
        self.assertEqual(sorted(front.ROUTES), ["/voice/audio", "/voice/health"], "the table of the front did not grow")

    def test_the_answer_must_be_a_json_object(self):
        status, _, out = post(self.port, "/voice/audio", b"NOTJSON" + WAV, "audio/wav")
        self.assertEqual((status, json.loads(out)["error"]), (502, "voice_unavailable"))

    def test_size_caps(self):
        # an audio body over the cap is refused from the head alone: the body is never read
        head = "POST /voice/audio HTTP/1.1\r\nHost: h\r\nContent-Type: audio/wav\r\nContent-Length: %d\r\n\r\n" % (stt.MAX_WAV_BYTES + 1)
        self.assertEqual(exchange(self.port, head.encode())[0], 413)
        self.assertEqual(front.MAX_AUDIO, stt.MAX_WAV_BYTES)
        self.assertFalse(hasattr(front, "MAX_JSON"), "no JSON body goes through the front any more")
        self.assertEqual(self.stub.seen, [])

    def test_length_rules(self):
        base = b"POST /voice/audio HTTP/1.1\r\nHost: h\r\nContent-Type: audio/wav\r\n"
        self.assertEqual(exchange(self.port, base + b"\r\n{}")[0], 411)
        self.assertEqual(exchange(self.port, base + b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n")[0], 411)
        self.assertEqual(exchange(self.port, base + b"Content-Length: -1\r\n\r\n")[0], 413)
        # fewer bytes than announced: refused, nothing forwarded
        self.assertEqual(exchange(self.port, base + b"Content-Length: 50\r\n\r\n{}", half_close=True)[0], 400)
        self.assertEqual(exchange(self.port, b"GET /voice/health HTTP/1.1\r\nHost: h\r\nContent-Length: 5\r\n\r\nhello")[0], 400)
        self.assertEqual(self.stub.seen, [])

    def test_a_stalled_body_times_out(self):
        old = front.BODY_IDLE
        front.BODY_IDLE = 0.05
        self.addCleanup(setattr, front, "BODY_IDLE", old)
        c = socket.create_connection(("127.0.0.1", self.port), 5)
        self.addCleanup(c.close)
        c.sendall(b"POST /voice/audio HTTP/1.1\r\nHost: h\r\nContent-Type: audio/wav\r\nContent-Length: 50\r\n\r\nRIFF")
        self.assertIn(b" 408 ", c.recv(4096))

    def test_a_body_that_trickles_in_has_a_total_deadline(self):
        # one byte every 0.1 s is never idle for BODY_IDLE, and used to hold the slot for ever
        old = (front.BODY_IDLE, front.BODY_TOTAL)
        front.BODY_IDLE, front.BODY_TOTAL = 5.0, 0.08
        self.addCleanup(lambda: setattr(front, "BODY_IDLE", old[0]) or setattr(front, "BODY_TOTAL", old[1]))
        c = socket.create_connection(("127.0.0.1", self.port), 5)
        self.addCleanup(c.close)
        c.sendall(b"POST /voice/audio HTTP/1.1\r\nHost: h\r\nContent-Type: audio/wav\r\nContent-Length: 5000\r\n\r\n")
        t0, got = time.time(), b""
        c.settimeout(0.015)
        while time.time() - t0 < 4 and b" 408 " not in got:
            try:
                c.sendall(b"R")
            except OSError:
                pass
            try:
                got += c.recv(4096)
            except socket.timeout:
                pass
        self.assertIn(b" 408 ", got)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(self.stub.seen, [])

    def test_a_dead_service_is_a_502_and_the_terminal_still_works(self):
        dead_port = free_port()
        f = front.Front(("127.0.0.1", 0), ("127.0.0.1", self.server_port), ("127.0.0.1", dead_port))
        self.addCleanup(f.close)
        threading.Thread(target=f.serve_forever, daemon=True).start()
        port = f.address[1]
        status, _, body = get(port, "/voice/health")
        self.assertEqual((status, json.loads(body)["error"]), (502, "voice_unavailable"))
        self.assertEqual(post(port, "/voice/audio", WAV, "audio/wav")[0], 502)
        self.assertEqual(get(port, "/")[0], 200)

    def test_a_garbage_answer_is_a_502_and_the_terminal_still_works(self):
        self.assertEqual(post(self.port, "/voice/audio", b"GARBAGE" + WAV, "audio/wav")[0], 502)
        self.assertEqual(get(self.port, "/")[0], 200)

    def test_a_slow_service_is_a_504_and_does_not_block_the_terminal(self):
        old = front.UPSTREAM_TIMEOUT
        front.UPSTREAM_TIMEOUT = 0.06
        self.addCleanup(setattr, front, "UPSTREAM_TIMEOUT", old)
        out = {}
        t = threading.Thread(target=lambda: out.update(r=post(self.port, "/voice/audio", b"SLOW" + WAV, "audio/wav")))
        t.start()
        time.sleep(0.01)
        t0 = time.time()
        self.assertEqual(get(self.port, "/")[0], 200)
        self.assertLess(time.time() - t0, 2)
        t.join()
        self.assertEqual(out["r"][0], 504)

    def test_too_many_voice_requests_are_refused_not_queued_on_the_terminal(self):
        held = [self.front.voice_slots.acquire() for _ in range(front.MAX_VOICE)]
        self.assertEqual(len(held), front.MAX_VOICE)
        self.assertEqual(get(self.port, "/voice/health")[0], 503)
        self.assertEqual(get(self.port, "/")[0], 200)
        for _ in held:
            self.front.voice_slots.release()

    def test_paths_that_only_look_like_voice_go_to_the_terminal(self):
        for path in ("/voice", "/voices/x", "//voice/health", "/%76oice/health"):
            self.assertEqual(get(self.port, path)[0], 200, path)
        self.assertEqual(self.stub.seen, [])


class ServerDown(FrontCase):
    with_server = False

    def test_without_the_server_the_terminal_is_a_502_and_voice_works(self):
        status, _, body = get(self.port, "/")
        self.assertEqual((status, json.loads(body)["error"]), (502, "terminal_unavailable"))
        self.assertEqual(get(self.port, "/voice/health")[0], 200)


class ServerCommand(unittest.TestCase):
    def test_p_and_i_are_replaced_and_the_rest_kept(self):
        got = front.server_command(["/srv/server.mjs", "-p", "7681", "-i", "0.0.0.0", "--quiet"], 7680)
        self.assertEqual(got, ["/srv/server.mjs", "-p", "7680", "-i", "127.0.0.1", "--quiet"])

    def test_glued_and_long_forms(self):
        got = front.server_command(["server.mjs", "-p7681", "--interface=lo", "--port", "5", "-W"], 7680)
        self.assertEqual(got, ["server.mjs", "-p", "7680", "-i", "127.0.0.1", "-W"])

    def test_no_command_is_an_error(self):
        with self.assertRaises(ValueError):
            front.server_command([], 7680)


def children_of(pid):
    out = []
    try:
        for t in os.listdir("/proc/%d/task" % pid):
            with open("/proc/%d/task/%s/children" % (pid, t)) as f:
                out += [int(x) for x in f.read().split()]
    except OSError:
        pass
    return out


def alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


class Processes(unittest.TestCase):
    """The real command, with the real service and the fake web server."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="voice-front-proc-")
        self.addCleanup(subprocess.call, ["rm", "-rf", self.tmp])
        self.port, self.server_port, self.service_port = free_port(), free_port(), free_port()
        self.procs = []

    def start(self, **env):
        e = {"PATH": os.environ["PATH"], "HOME": self.tmp, "PYTHONPATH": LIB, "FAKE_SERVER_LOG": os.path.join(self.tmp, "t.log"),
             "FAKE_SERVER_PID": os.path.join(self.tmp, "server.pid"), "SWARMBOX_TEST_RESTART_DELAY": "0.02"}
        e.update(env)
        p = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_voice", "front", "--listen", "127.0.0.1:%d" % self.port,
                              "--server-port", str(self.server_port), "--service-listen", "127.0.0.1:%d" % self.service_port,
                              "--", FAKE_SERVER, "-p", "7681", "-i", "0.0.0.0", "-O"],
                             env=e, stderr=subprocess.PIPE)
        self.procs.append(p)
        self.addCleanup(self.reap, p)
        self.assertTrue(wait_port(self.port), "the front did not listen")
        self.assertTrue(wait_port(self.service_port), "the service did not start")
        return p

    def server_pid(self):
        with open(os.path.join(self.tmp, "server.pid")) as f:
            return int(f.read())

    def reap(self, p):
        if p.poll() is None:
            p.kill()
        p.wait()
        p.stderr.close()
        for pid in children_of(p.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def test_the_real_stack_routes_both_ways(self):
        self.start()
        status, _, body = get(self.port, "/voice/health", host="voice-test.example:7681", extra="Origin: http://voice-test.example:7681\r\n")
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(get(self.port, "/voice/page.js")[0], 404, "the old page parts are gone")
        self.assertIn(b"fake terminal page", get(self.port, "/")[2])
        with open(os.path.join(self.tmp, "t.log.argv")) as f:
            argv = json.load(f)
        self.assertEqual(argv[1:5], ["-p", str(self.server_port), "-i", "127.0.0.1"], argv)
        self.assertEqual(get(self.port, "/voice/health", extra="Origin: http://evil.example\r\n")[0], 403)

    def test_the_server_exiting_stops_the_service_and_gives_its_status(self):
        p = self.start(FAKE_SERVER_EXIT_AFTER="0.03", FAKE_SERVER_EXIT_CODE="7")
        kids = children_of(p.pid)
        self.assertEqual(len(kids), 2, kids)
        self.assertEqual(p.wait(timeout=15), 7)
        for pid in kids:
            self.assertFalse(alive(pid), pid)
        self.assertFalse(wait_port(self.service_port, 0.03))

    def test_a_signal_stops_both_children_and_exits_cleanly(self):
        for i, sig in enumerate((signal.SIGTERM, signal.SIGINT)):
            if i:
                self.setUp()
            p = self.start()
            kids = children_of(p.pid)
            self.assertEqual(len(kids), 2, kids)
            p.send_signal(sig)
            self.assertEqual(p.wait(timeout=15), 0, sig)
            for pid in kids:
                self.assertFalse(alive(pid), (sig, pid))

    def test_killing_the_front_takes_its_children_with_it(self):
        p = self.start()
        kids = children_of(p.pid)
        p.kill()
        p.wait()
        deadline = time.time() + 10
        while time.time() < deadline and any(alive(k) for k in kids):
            time.sleep(0.01)
        self.assertFalse([k for k in kids if alive(k)])

    def test_a_dead_service_is_restarted_and_the_terminal_never_noticed(self):
        p = self.start()
        service = [k for k in children_of(p.pid) if k != self.server_pid()]
        self.assertEqual(len(service), 1)
        os.kill(service[0], signal.SIGKILL)
        self.assertEqual(get(self.port, "/")[0], 200)
        end = time.time() + 15
        ok = False
        while time.time() < end and not ok:
            ok = get(self.port, "/voice/health")[0] == 200
            if not ok:
                time.sleep(0.005)
        self.assertTrue(ok, "the service did not come back")
        self.assertIsNone(p.poll())

    def test_a_busy_port_is_an_error_before_any_child_starts(self):
        s = socket.socket()
        s.bind(("127.0.0.1", self.port))
        s.listen(1)
        self.addCleanup(s.close)
        p = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_voice", "front", "--listen", "127.0.0.1:%d" % self.port, "--",
                              FAKE_SERVER], env={"PATH": os.environ["PATH"], "PYTHONPATH": LIB}, stderr=subprocess.PIPE)
        err = p.communicate(timeout=15)[1].decode()
        self.assertEqual(p.returncode, 98)
        self.assertIn("cannot listen", err)

    def test_bad_arguments(self):
        cases = (["--listen", "nonsense", "--", "server"], ["--service-listen", "0.0.0.0:1", "--", "server"], ["--listen", "127.0.0.1:0"])
        env = {"PATH": os.environ["PATH"], "PYTHONPATH": LIB}
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            res = [(a, subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "front"] + a, env=env,
                                      capture_output=True, text=True, timeout=15)) for a in cases]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                res = list(pool.map(lambda a: (a, subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "front"] + a, env=env,
                                                                 capture_output=True, text=True, timeout=15)), cases))
        for args, p in res:
            self.assertEqual(p.returncode, 2, args)

    def test_a_missing_server_is_127(self):
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "front", "--listen", "127.0.0.1:%d" % self.port, "--",
                            "/nonexistent/server.mjs"], env={"PATH": os.environ["PATH"], "PYTHONPATH": LIB}, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 127)


if __name__ == "__main__":
    unittest.main()
