"""Publish a goal on the bus of the box: the socket protocol spoken directly, standard library only (a few lines, no command to run).

Protocol (the docstring of container/scripts/swarmbox-bus.py is the specification): line-delimited JSON, one request line per connection,
one reply line {"ok": true, "id": ...} or {"ok": false, "err": CODE, "msg": TEXT}. The topic is a free name from the setting voice.topic
(SWARMBOX_VOICE_TOPIC, default goal); a message goes to every subscriber, and with none the answer is no_subscriber at once (the exit 3 of `pub`). The envelope's `source` is a label for display (the bus never uses it to authorize), so voice has no
secret to add: any process of the box can publish, which is the trust it already has with typing into a terminal.

publish() returns one of the fixed states the service tells the browser: "sent", "no_listener", "busy", "bus_down". Nothing of the bus's
own text (the `msg`) is returned.
"""
import json
import os
import socket

SOURCE = "voice"
TIMEOUT = 10.0
MAX_REPLY = 1 << 16


def socket_path(env=None):
    e = os.environ if env is None else env
    return e.get("SB_BUS_SOCKET") or os.path.join(e.get("SB_RUN_DIR") or "/tmp/swarmbox", "bus.sock")


def publish(topic, text, path=None, timeout=TIMEOUT):
    req = {"op": "pub", "topic": topic, "source": SOURCE, "body": {"text": text}}
    data = (json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path or socket_path())
        try:
            s.sendall(data)
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # the broker may have answered and closed already: read the reply
        with s.makefile("rb") as f:
            raw = f.readline(MAX_REPLY)
        rep = json.loads(raw)
    except (OSError, ValueError):                 # nobody on the socket, a timeout, a closed connection, garbage
        return "bus_down"
    finally:
        s.close()
    if not isinstance(rep, dict):
        return "bus_down"
    if rep.get("ok") is True:
        return "sent"
    return {"no_subscriber": "no_listener", "busy": "busy"}.get(rep.get("err"), "bus_down")
