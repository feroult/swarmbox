#!/usr/bin/env python3
"""A fake ttyd for the front tests: serves a page, a big body, and echoes websocket bytes after a 101. Listens on -p/-i.

FAKE_TTYD_LOG      file that gets one JSON line per request head received (the head as latin-1 text), and FAKE_TTYD_LOG.argv the argv
FAKE_TTYD_PID      file that gets the pid
FAKE_TTYD_EXIT_AFTER / FAKE_TTYD_EXIT_CODE   exit with that code after that many seconds
-O in the arguments makes it refuse (403) a request whose Origin is not its Host, like ttyd -O.
"""
import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import urlsplit

args = sys.argv[1:]
port = int(args[args.index("-p") + 1])
iface = args[args.index("-i") + 1]
log = os.environ.get("FAKE_TTYD_LOG")
if log:
    open(log + ".argv", "w").write(json.dumps(sys.argv))
if os.environ.get("FAKE_TTYD_PID"):
    open(os.environ["FAKE_TTYD_PID"], "w").write(str(os.getpid()))
if os.environ.get("FAKE_TTYD_EXIT_AFTER"):
    threading.Timer(float(os.environ["FAKE_TTYD_EXIT_AFTER"]), lambda: os._exit(int(os.environ.get("FAKE_TTYD_EXIT_CODE", "0")))).start()
LOCK = threading.Lock()
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def serve(c):
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = c.recv(4096)
            if not d:
                return
            buf += d
        head, _, rest = buf.partition(b"\r\n\r\n")
        text = head.decode("latin-1")
        if log:
            with LOCK, open(log, "a") as f:
                f.write(json.dumps({"head": text}) + "\n")
        lines = text.split("\r\n")
        hdr = {}
        for l in lines[1:]:
            k, _, v = l.partition(":")
            hdr[k.strip().lower()] = v.strip()
        path = lines[0].split(" ")[1]
        if "-O" in args and "origin" in hdr and urlsplit(hdr["origin"]).netloc != hdr.get("host"):
            c.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        if hdr.get("upgrade", "").lower() == "websocket":
            acc = base64.b64encode(hashlib.sha1((hdr["sec-websocket-key"] + GUID).encode()).digest()).decode()
            c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
            if rest:
                c.sendall(rest)
            while True:
                d = c.recv(65536)
                if not d:
                    break
                c.sendall(d)
            return
        if path == "/big":
            body = b"x" * (5 * 1024 * 1024)
        elif path == "/hang":
            time.sleep(30)
            return
        else:
            body = b"<html><body>fake terminal page</body></html>"
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
    except OSError:
        pass
    finally:
        c.close()


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((iface, port))
s.listen(64)
while True:
    conn, _ = s.accept()
    threading.Thread(target=serve, args=(conn,), daemon=True).start()
