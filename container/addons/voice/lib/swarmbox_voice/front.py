"""The front: one listener on the web port that takes the audio of the microphone, in front of the web server of the box (the herdr Web
Studio, container/web/herdr/server.mjs). Stdlib only.

                     browser --> front (0.0.0.0:7681 in the box) --+--> /voice/*   a FIXED table, below (two routes, nothing else)
                                                                    +--> the rest  raw pipe to the web server (127.0.0.1:7680), websockets included

`swarmbox-voice front [--listen HOST:PORT] [--server-port N] [--service-listen HOST:PORT] -- SERVER ARGS...` starts the web server (its
-p/-i replaced by 127.0.0.1 and --server-port) and the voice service as children and routes each connection by its FIRST request head. The
browser only captures the microphone, so this is an audio entry, not a router; what happens to the goal that the audio becomes is decided on
the box (by whoever subscribes to the topic) and never crosses the tunnel. The table of /voice/:

   GET  /voice/health      forwarded to the service; only {"ok": ...} is passed back (no language or model)
   POST /voice/audio       16 kHz mono 16-bit WAV (audio/wav), forwarded to the service; only {"ok", "state", "message"} or {"error", "message"} comes back
                           (short strings and booleans: no object, no list, nothing else of what the service says)

Every other path under /voice/ answers 404 (or 405 for a known path with the wrong method, or for OPTIONS) FROM THE FRONT, before the Host
or Origin are even looked at, and never reaches the service (which has only health and audio anyway). What is forwarded is rebuilt (the path alone, no query; Host and Origin rewritten to the
loopback address of the service, which keeps its own loopback-only guard), and the answer is filtered, so even a faulty service could not
hand a transcript to the browser.

Rules kept for the two routes: an `Origin`, when there is one, must name the `Host` (else 403), as the web server does for its own routes; a POST
needs the WAV content type and a Content-Length (a cross-site form cannot send that type), no chunked bodies; the body is capped (8 MiB);
at most 16 voice requests at a time (a 503 beyond that, never a queue on the terminal); a failure is a JSON error for that request only.
Anything that is not /voice/ is piped to the web server byte for byte (the answer to a plain request gets the frame headers, FRAME_GUARD). A request without `Upgrade: websocket` gets `Connection: close` (one connection
is one request, so the first head is the only one this front ever reads); a websocket upgrade keeps its head untouched, since the server's
same-origin check needs the original Host and Origin.

When the web server exits the front stops the service and exits with the status of the server, so the supervisor of the box keeps its restart policy.
SIGTERM and SIGINT stop both children and exit 0. The service is restarted (with a back-off) if it dies: voice trouble never touches
the terminal path. Security: what the tunnel can do is send audio, which makes at most a goal on the bus (what a subscriber does with it is its own policy: risk, confirmation); it is as reachable as the terminal itself (whoever reaches the web port), and the front is the one place that sees the public Host.
"""
import ctypes
import http.client
import json
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from . import stt

MAX_HEAD = 16 * 1024
HEAD_TIMEOUT = 10.0
MAX_AUDIO = stt.MAX_WAV_BYTES
BODY_IDLE = 15.0               # no byte for this long while a body is arriving: give up
BODY_TOTAL = 30.0              # and the whole body must be there by then (a byte every few seconds would hold a slot for ever)
UPSTREAM_TIMEOUT = 180.0       # a request may wait for whisper
MAX_RESPONSE = 4 * 1024 * 1024
IDLE = 120.0                   # a plain (non-websocket) piped request that stalls this long is cut
GRACE = 30.0                   # after one side closed its end, the other side has this long to finish
MAX_CONNECTIONS = 512
MAX_VOICE = 8
AUDIO_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
# THE table of what the web can reach under /voice/: path -> method. Nothing else is served or forwarded, whatever the service has.
ROUTES = {"/voice/health": "GET", "/voice/audio": "POST"}
PASS_KEYS = {"/voice/health": ("ok",), "/voice/audio": ("ok", "state", "error", "message")}   # what is passed back of the service's answer
MAX_FIELD = 200
REASONS = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 411: "Length Required",
           413: "Payload Too Large", 415: "Unsupported Media Type", 431: "Request Header Fields Too Large", 500: "Internal Server Error",
           502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout", 408: "Request Timeout"}


def server_command(argv, port, iface="127.0.0.1"):
    """The web server's command line with its own -p/-i (--port/--interface) replaced: [exe, -p PORT, -i IFACE, other arguments...]."""
    if not argv:
        raise ValueError("no web server command after --")
    exe, rest, out, i = argv[0], list(argv[1:]), [], 0
    while i < len(rest):
        a = rest[i]
        if a in ("-p", "-i", "--port", "--interface"):
            i += 2
            continue
        if a.startswith(("--port=", "--interface=")) or (len(a) > 2 and a[:2] in ("-p", "-i")):
            i += 1
            continue
        out.append(a)
        i += 1
    return [exe, "-p", str(port), "-i", iface] + out


def pdeathsig():
    """Child setup: SIGTERM when this process dies, so a killed front never leaves the web server or the service behind (Linux; best effort)."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:
        pass


class Children:
    """The web server and the voice service as children of the front."""

    def __init__(self, server_argv, service_argv, env):
        self.server_argv, self.service_argv, self.env = server_argv, service_argv, env
        self.server = None
        self.service = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    def start_server(self):
        self.server = subprocess.Popen(self.server_argv, preexec_fn=pdeathsig)

    def _spawn_service(self):
        return subprocess.Popen(self.service_argv, env=self.env, stdin=subprocess.DEVNULL)

    def start_service(self):
        with self.lock:
            if not self.stop.is_set():
                self.service = self._spawn_service()
        self.thread = threading.Thread(target=self._watch_service, daemon=True)
        self.thread.start()

    def _watch_service(self):
        delay = 1.0
        while not self.stop.is_set():
            started = time.monotonic()
            with self.lock:
                proc = self.service
            if proc is not None:
                while proc.poll() is None and not self.stop.wait(0.2):
                    pass
            if self.stop.is_set():
                return
            if time.monotonic() - started > 60:
                delay = 1.0
            print("swarmbox-voice front: the voice service exited (%s); restarting in %.0f s" % (proc.returncode if proc else "?", delay),
                  file=sys.stderr, flush=True)
            if self.stop.wait(delay):
                return
            delay = min(delay * 2, 30.0)
            with self.lock:
                if self.stop.is_set():
                    return
                try:
                    self.service = self._spawn_service()
                except OSError as e:
                    print("swarmbox-voice front: cannot start the voice service: %s" % e, file=sys.stderr, flush=True)
                    self.service = None

    @staticmethod
    def _end(proc, wait=5.0):
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except OSError:
            pass

    def stop_service(self):
        self.stop.set()
        with self.lock:
            proc = self.service
        self._end(proc, 3.0)

    def stop_all(self):
        self.stop_service()
        self._end(self.server)


# ---------------------------------------------------------------------------------------------------------------------- HTTP helpers

class BadRequest(Exception):
    def __init__(self, status, code, message):
        Exception.__init__(self, message)
        self.status, self.code, self.message = status, code, message


class Head:
    def __init__(self, raw, extra):
        self.raw, self.extra = raw, extra          # raw: the bytes up to and including the blank line; extra: bytes read past it
        lines = raw[:-4].split(b"\r\n")
        try:
            self.method, self.target, self.version = lines[0].decode("ascii").split(" ")
        except (ValueError, UnicodeDecodeError):
            raise BadRequest(400, "bad_request", "malformed request line") from None
        if not self.version.startswith("HTTP/1."):
            raise BadRequest(400, "bad_request", "unsupported HTTP version")
        self.lines = lines[1:]
        self.headers = {}
        for line in self.lines:
            name, sep, value = line.partition(b":")
            if not sep or not name or name != name.strip():
                raise BadRequest(400, "bad_request", "malformed header")
            self.headers.setdefault(name.decode("latin-1").lower(), []).append(value.decode("latin-1").strip())

    def get(self, name):
        v = self.headers.get(name)
        return v[0] if v else None

    def is_upgrade(self):
        return any(v.lower() == "websocket" for v in self.headers.get("upgrade", []))

    def with_connection_close(self):
        keep = [l for l in self.lines if l.partition(b":")[0].strip().lower() != b"connection"]
        first = self.raw.split(b"\r\n", 1)[0]
        return b"\r\n".join([first] + keep + [b"Connection: close"]) + b"\r\n\r\n"


def read_head(conn, deadline):
    buf = b""
    while b"\r\n\r\n" not in buf:
        left = deadline - time.monotonic()
        if left <= 0:
            raise BadRequest(408, "timeout", "the request head took too long")
        conn.settimeout(left)
        try:
            data = conn.recv(4096)
        except socket.timeout:
            raise BadRequest(408, "timeout", "the request head took too long") from None
        if not data:
            return None
        buf += data
        if b"\r\n\r\n" not in buf and len(buf) > MAX_HEAD:
            raise BadRequest(431, "head_too_large", "the request head is too large")
    i = buf.index(b"\r\n\r\n") + 4
    if i > MAX_HEAD:
        raise BadRequest(431, "head_too_large", "the request head is too large")
    return Head(buf[:i], buf[i:])


# No other origin may frame the terminal page: a click in a frame would press a button of the page. The front adds these to every plain HTTP response (a websocket upgrade is not a page and is piped untouched).
FRAME_GUARD = ("Content-Security-Policy: frame-ancestors 'self'", "X-Frame-Options: SAMEORIGIN")


def _apply_frame_guard(buf):
    """Add FRAME_GUARD once to an HTTP/1.x response head; leave anything else unchanged."""
    i = buf.find(b"\r\n\r\n")
    if i < 0 or not buf.startswith(b"HTTP/1."):
        return buf
    lines = buf[:i].split(b"\r\n")
    drop = (b"content-security-policy", b"x-frame-options")
    keep = [l for l in lines[1:] if l.partition(b":")[0].strip().lower() not in drop]
    head = b"\r\n".join([lines[0]] + keep + [h.encode("latin-1") for h in FRAME_GUARD]) + b"\r\n\r\n"
    return head + buf[i + 4:]


def guard_response(up, conn, limit=16384, wait=10.0):
    """Read the response head from the web server, add FRAME_GUARD to it (once; the ones the server sent are kept out) and send it on. Anything that is
    not a readable head is handed on as it came."""
    buf = b""
    deadline = time.monotonic() + wait
    while b"\r\n\r\n" not in buf and len(buf) < limit:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        up.settimeout(left)
        try:
            data = up.recv(4096)
        except (socket.timeout, OSError):
            break
        if not data:
            break
        buf += data
    conn.sendall(_apply_frame_guard(buf))


def send(conn, status, body=b"", ctype="application/json; charset=utf-8", extra=()):
    head = ["HTTP/1.1 %d %s" % (status, REASONS.get(status, "Error")), "Content-Type: " + ctype, "Content-Length: %d" % len(body),
            "Cache-Control: no-store", "X-Content-Type-Options: nosniff", "Connection: close"] + list(FRAME_GUARD)
    head += ["%s: %s" % kv for kv in extra]
    conn.settimeout(30)
    conn.sendall(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body)


def send_error(conn, status, code, message):
    send(conn, status, json.dumps({"error": code, "message": message}).encode())


def _host_of(netloc):
    return netloc.strip().lower()


class Front:
    def __init__(self, listen, server_addr, service_addr):
        self.server_addr, self.service_addr = server_addr, service_addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(listen)
        self.sock.listen(128)
        self.address = self.sock.getsockname()
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.voice_slots = threading.BoundedSemaphore(MAX_VOICE)
        self.closing = False

    def serve_forever(self):
        while not self.closing:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                if self.closing:
                    return
                time.sleep(0.05)
                continue
            if not self.slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._connection, args=(conn,), daemon=True).start()

    def close(self):
        self.closing = True
        try:
            self.sock.close()
        except OSError:
            pass

    # one connection = one request
    def _connection(self, conn):
        try:
            try:
                head = read_head(conn, time.monotonic() + HEAD_TIMEOUT)
            except BadRequest as e:
                try:
                    send_error(conn, e.status, e.code, e.message)
                except OSError:
                    pass
                return
            if head is None:
                return
            if urlsplit(head.target).path.startswith("/voice/") and head.target.startswith("/"):
                self._voice(conn, head)
            else:
                self._terminal(conn, head)
        except Exception:   # a bug here must cost one connection, never the front
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            self.slots.release()

    # ------------------------------------------------------------------------------------------------------------- the terminal path
    def _terminal(self, conn, head):
        try:
            up = socket.create_connection(self.server_addr, timeout=5)
        except OSError:
            try:
                send_error(conn, 502, "terminal_unavailable", "the terminal is not answering")
            except OSError:
                pass
            return
        try:
            upgrade = head.is_upgrade()
            up.sendall((head.raw if upgrade else head.with_connection_close()) + head.extra)
            # Pump both directions concurrently while guarding the first HTTP response head so
            # large POST bodies (e.g. /api/paste-image) never deadlock waiting for an upstream reply.
            pump(conn, up, None if upgrade else IDLE, guard_src=None if upgrade else up)
        except OSError:
            pass
        finally:
            up.close()

    # ------------------------------------------------------------------------------------------------------------- the voice path
    def _voice(self, conn, head):
        if not self.voice_slots.acquire(blocking=False):
            send_error(conn, 503, "busy", "too many voice requests")
            return
        try:
            self._voice_checked(conn, head)
        except BadRequest as e:
            send_error(conn, e.status, e.code, e.message)
        except OSError:
            pass
        except Exception:
            try:
                send_error(conn, 500, "internal", "internal error")
            except OSError:
                pass
        finally:
            self.voice_slots.release()

    def _voice_checked(self, conn, head):
        url = urlsplit(head.target)
        path = url.path
        # the table first: an unlisted path is refused here, before anything else about the request is considered
        if path not in ROUTES:
            raise BadRequest(404, "not_found", "no such endpoint")
        if head.method not in ("GET", "POST") or head.method != ROUTES[path]:
            raise BadRequest(405, "no_cors" if head.method == "OPTIONS" else "bad_method", "this method is not allowed here")
        host = head.get("host")
        if host is None or len(head.headers["host"]) != 1 or not host:
            raise BadRequest(400, "bad_host", "exactly one Host header is required")
        origins = head.headers.get("origin", [])
        if len(origins) > 1 or (origins and urlsplit(origins[0]).netloc.lower() != _host_of(host)):
            raise BadRequest(403, "bad_origin", "cross-origin calls are not allowed")
        body = b""
        if head.method == "POST":
            if "transfer-encoding" in head.headers:
                raise BadRequest(411, "length_required", "Content-Length is required")
            ctype = (head.get("content-type") or "").split(";")[0].strip().lower()
            if ctype not in AUDIO_TYPES:
                raise BadRequest(415, "bad_content_type", "Content-Type must be one of: " + ", ".join(AUDIO_TYPES))
            try:
                length = int(head.get("content-length") or "")
            except ValueError:
                raise BadRequest(411, "length_required", "Content-Length is required") from None
            if length < 0 or length > MAX_AUDIO:
                raise BadRequest(413, "too_large", "the body is larger than %d bytes" % MAX_AUDIO)
            body = read_body(conn, head.extra, length)
        elif head.get("content-length") not in (None, "0") or "transfer-encoding" in head.headers:
            raise BadRequest(400, "bad_request", "a GET has no body")
        self._forward(conn, head, path, body)

    def _forward(self, conn, head, path, body):
        loop = "%s:%d" % self.service_addr
        headers = {"Host": loop, "Connection": "close"}
        if head.headers.get("origin"):
            headers["Origin"] = "http://" + loop
        if head.method == "POST":
            headers["Content-Type"] = head.get("content-type")
            headers["Content-Length"] = str(len(body))
        try:
            c = http.client.HTTPConnection(self.service_addr[0], self.service_addr[1], timeout=UPSTREAM_TIMEOUT)
            try:
                c.request(head.method, path, body=body if head.method == "POST" else None, headers=headers)
                r = c.getresponse()
                data = r.read(MAX_RESPONSE + 1)
                status = r.status
            finally:
                c.close()
        except socket.timeout:
            raise BadRequest(504, "voice_timeout", "The voice service is slow: try again in a moment.") from None
        except (OSError, http.client.HTTPException, ValueError):
            raise BadRequest(502, "voice_unavailable", "The voice service is restarting: try again in a few seconds.") from None
        try:
            if len(data) > MAX_RESPONSE:
                raise ValueError("too large")
            answer = json.loads(data.decode("utf-8"))
            if not isinstance(answer, dict):
                raise ValueError("not an object")
        except ValueError:
            raise BadRequest(502, "voice_unavailable", "the voice service sent an answer that is not JSON") from None
        keep = {}
        for k in PASS_KEYS[path]:
            v = answer.get(k)
            if isinstance(v, bool):
                keep[k] = v
            elif isinstance(v, str):
                keep[k] = v[:MAX_FIELD]
        send(conn, status, json.dumps(keep).encode())


def read_body(conn, extra, length):
    buf = extra[:length]
    if len(extra) > length:
        raise BadRequest(400, "bad_request", "more bytes than Content-Length")
    parts = [buf]
    got = len(buf)
    end = time.monotonic() + BODY_TOTAL
    while got < length:
        left = end - time.monotonic()
        if left <= 0:
            raise BadRequest(408, "timeout", "the body took too long to arrive")
        conn.settimeout(min(BODY_IDLE, left))
        try:
            data = conn.recv(min(65536, length - got))
        except socket.timeout:
            raise BadRequest(408, "timeout", "the body stopped arriving") from None
        if not data:
            raise BadRequest(400, "bad_request", "the body is incomplete")
        parts.append(data)
        got += len(data)
    return b"".join(parts)


def pump(a, b, idle, guard_src=None, guard_limit=16384):
    """Copy both ways between two sockets until both ends are done. EOF on one side half-closes the other; `idle` seconds without a
    byte (None: never) ends it, and after one side closed the other has GRACE seconds. When `guard_src` is set, its initial HTTP response
    head gets FRAME_GUARD injected before forwarding while request bytes keep flowing in the opposite direction. Nothing is left open."""
    for s in (a, b):
        s.setblocking(True)
        s.settimeout(60)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
    live = {a: b, b: a}          # source -> destination
    last = time.monotonic()
    ended = None
    guard_buf = bytearray()
    guard_done = guard_src is None
    try:
        while live:
            limit = GRACE if ended is not None else idle
            timeout = None if limit is None else max(0.0, limit - (time.monotonic() - (ended if ended is not None else last)))
            ready, _, _ = select.select(list(live), [], [], timeout)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    dst = live.pop(s)
                    if s is guard_src and not guard_done and guard_buf:
                        dst.sendall(_apply_frame_guard(bytes(guard_buf)))
                        guard_buf.clear()
                        guard_done = True
                    if ended is None:
                        ended = time.monotonic()
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    continue
                last = time.monotonic()
                dst = live[s]
                if s is guard_src and not guard_done:
                    guard_buf.extend(data)
                    if b"\r\n\r\n" in guard_buf or len(guard_buf) >= guard_limit:
                        dst.sendall(_apply_frame_guard(bytes(guard_buf)))
                        guard_buf.clear()
                        guard_done = True
                else:
                    dst.sendall(data)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------------------- the command

def parse_addr(text, what):
    host, _, port = text.rpartition(":")
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError("%s: HOST:PORT expected, got %r" % (what, text))
    return (host or "127.0.0.1", int(port))


def run(args, server_args):
    try:
        listen = parse_addr(args.listen, "--listen")
        service = parse_addr(args.service_listen, "--service-listen")
        if service[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("--service-listen must be a loopback address")
        service = ("127.0.0.1", service[1])
        server = server_command(server_args, args.server_port)
    except ValueError as e:
        print("swarmbox-voice front: %s" % e, file=sys.stderr)
        return 2
    try:
        front = Front(listen, ("127.0.0.1", args.server_port), service)
    except OSError as e:
        print("swarmbox-voice front: cannot listen on %s: %s" % (args.listen, e), file=sys.stderr)
        return 98
    lib = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = lib + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    service_argv = [sys.executable, "-B", "-m", "swarmbox_voice", "serve", "--listen", "%s:%d" % service, "--die-with-parent"]
    children = Children(server, service_argv, env)
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        try:
            children.start_server()
        except OSError as e:
            print("swarmbox-voice front: cannot start the web server: %s" % e, file=sys.stderr)
            return 127
        children.start_service()
        threading.Thread(target=front.serve_forever, daemon=True).start()
        print("swarmbox-voice front: listening on %s:%d, web server on 127.0.0.1:%d, voice service on 127.0.0.1:%d"
              % (front.address[0], front.address[1], args.server_port, service[1]), file=sys.stderr, flush=True)
        while not stopping.is_set() and children.server.poll() is None:
            stopping.wait(0.2)
        rc = 0 if stopping.is_set() else children.server.returncode
        if rc is not None and rc < 0:
            rc = 128 - rc
        return rc
    finally:
        front.close()
        children.stop_all()


def add_arguments(p):
    p.add_argument("--listen", default="0.0.0.0:7681", help="the web terminal port (what the browser reaches)")
    p.add_argument("--server-port", type=int, default=7680, help="the loopback port of the web server behind the front")
    p.add_argument("--service-listen", default="127.0.0.1:17682")


def split_command(argv):
    """argv without the part after `--` and that part."""
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []
