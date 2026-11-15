"""A client of swarmbox-bus that speaks its socket protocol directly (standard library only): publish, and subscribe with a group.

The bus is plain publish/subscribe (container/scripts/swarmbox-bus.py, its docstring is the specification): it keeps no state, answers no
questions and knows nothing about tmux. The sysop uses it for one thing, goals: the service subscribes to the topic of `sysop.topic` with the
group of `sysop.group`, and the panel, the key g and `swarmbox-sysop goal` publish there. Reading and typing into the tabs of the box does NOT
go through here: that is the capability swarmbox-tabs (tabsclient.py).

Why not run the `swarmbox-bus` command: (1) `sub` is one long connection that the service must close from another thread and reconnect with
backoff, which is a socket and not a pipe to a child; (2) the answers keep their shape: a failure is {"err": CODE, "msg": TEXT} and the callers
look at the code (no_subscriber: nobody listens, so the sysop is not running). The cost is that this file repeats the protocol;
tests/test_sysop_bus.py runs this client against the real broker, so a change of the protocol breaks a test here.

Protocol: line-delimited JSON, one request line per connection. pub, ping and topics get one reply {"ok": true, ...} or {"ok": false, "err",
"msg"}; pub's reply has "id" and "delivered" (the number of receivers); sub gets {"ok": true, "subscribed": T, "group": G} and then one envelope
per line. A line is at most 1 MiB.
"""
import json
import os
import socket

from . import paths

MAX_LINE = 1 << 20
TIMEOUT = 45.0


class BusError(Exception):
    """code is the bus's err word, or: bus_down (nobody listens on the socket), bus_closed (the broker went away), bus_protocol (garbage)."""

    def __init__(self, code, msg=""):
        Exception.__init__(self, "%s: %s" % (code, msg) if msg else code)
        self.code, self.msg = code, msg


def _line(f):
    raw = f.readline(MAX_LINE + 1)
    if not raw:
        raise BusError("bus_closed", "the bus closed the connection")
    if len(raw) > MAX_LINE:
        raise BusError("bus_protocol", "a line longer than 1 MiB")
    try:
        obj = json.loads(raw)
    except ValueError:
        raise BusError("bus_protocol", "the bus sent something that is not JSON")
    if not isinstance(obj, dict):
        raise BusError("bus_protocol", "the bus sent something that is not an object")
    return obj


def _connect(path, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
    except (FileNotFoundError, ConnectionRefusedError):
        s.close()
        raise BusError("bus_down", "the bus is not running (%s)" % path)
    except OSError as e:
        s.close()
        raise BusError("bus_down", "cannot connect to %s: %s" % (path, e.strerror or e))
    return s


class Subscription:
    """The stream of a `sub`: iterate it for envelopes; close() from any thread ends the iteration."""

    def __init__(self, sock, f):
        self.sock, self.f = sock, f

    def __iter__(self):
        return self

    def __next__(self):
        try:
            raw = self.f.readline(MAX_LINE + 1)
        except (OSError, ValueError):          # closed by close(), reset by the broker
            raise StopIteration
        if not raw:
            raise StopIteration
        if len(raw) > MAX_LINE:
            raise BusError("bus_protocol", "an envelope longer than 1 MiB")
        try:
            env = json.loads(raw)
        except ValueError:
            return {"_bad": True}
        return env if isinstance(env, dict) else {"_bad": True}

    def close(self):
        for fn in (lambda: self.sock.shutdown(socket.SHUT_RDWR), self.f.close, self.sock.close):
            try:
                fn()
            except (OSError, ValueError):
                pass


class Bus:
    def __init__(self, path=None, timeout=TIMEOUT, env=None):
        self.path = path or paths.bus_socket(env)
        self.timeout = timeout

    def request(self, req, timeout=None):
        data = (json.dumps(req, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_LINE - 1024:
            raise BusError("too_large", "the request is longer than the bus accepts")
        s = _connect(self.path, timeout or self.timeout)
        try:
            try:
                s.sendall(data)
            except (BrokenPipeError, ConnectionResetError):
                pass                           # the broker may have answered and closed already: read the reply
            try:
                with s.makefile("rb") as f:
                    rep = _line(f)
            except socket.timeout:
                raise BusError("timeout", "the bus did not answer in %g s" % (timeout or self.timeout))
            except ConnectionError:
                raise BusError("bus_closed", "the bus closed the connection")
        finally:
            s.close()
        if not rep.get("ok"):
            raise BusError(str(rep.get("err", "error")), str(rep.get("msg", "")))
        return rep

    def ping(self):
        return self.request({"op": "ping"}, 5)

    def pub(self, topic, body, source="cli"):
        """Publish; the reply has "id" and "delivered" (how many received it). Nobody subscribed is the error no_subscriber."""
        return self.request({"op": "pub", "topic": topic, "source": source, "body": body})

    def subscribe(self, topic, group=None):
        """Open the stream of `topic`, as a member of `group` (members of a group share the messages: one gets each) or alone; raises
        BusError when the bus is down or refuses. The timeout of the socket is lifted: the stream waits."""
        s = _connect(self.path, 10)
        f = s.makefile("rb")
        try:
            req = {"op": "sub", "topic": topic}
            if group:
                req["group"] = group
            s.sendall((json.dumps(req) + "\n").encode())
            rep = _line(f)
        except (OSError, BusError) as e:
            f.close()
            s.close()
            if isinstance(e, BusError):
                raise
            raise BusError("bus_closed", str(e))
        if not rep.get("ok"):
            f.close()
            s.close()
            raise BusError(str(rep.get("err", "error")), str(rep.get("msg", "")))
        s.settimeout(None)
        return Subscription(s, f)
