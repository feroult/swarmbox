#!/usr/bin/python3 -S
"""swarmbox-bus: the bus of the box (publish and subscribe) and its command line, one file, standard library only.

  swarmbox-bus serve                                    run the broker (asyncio, one process, one unix socket); the entrypoint runs this
  swarmbox-bus pub [--source S] [--allow-none] [--] TOPIC [MESSAGE|-]
                                                        publish; MESSAGE is one line of JSON or plain text (after `--` it may start with
                                                        a dash); "-" (the default) reads stdin. Prints {"id":ID,"receivers":N}
  swarmbox-bus sub [--group NAME] [--raw] [-v] TOPIC    stream the messages of a topic; --raw prints the bodies only, one line each
                                                        (plain one-line text as it is, anything else as JSON)
  swarmbox-bus topics                                   the topics that have subscribers: a JSON list of {topic, subscribers, groups}
  swarmbox-bus watch [-v]                               every message that passes, with its topic, receivers and result, one JSON line each
  swarmbox-bus ping                                     exit 0 when the broker answers
  swarmbox-bus restart                                  ask the entrypoint's supervisor to start the broker again (SIGUSR1)

The bus is plain publish and subscribe. It knows nothing about tmux, tabs or what a message means, keeps no state and answers no questions
about the box (reading and typing into tmux tabs is the command swarmbox-tabs, a capability of the host, never a topic).

Exit codes: 0 ok, 1 other error, 2 usage, 3 nobody received the message (pub; --allow-none accepts it), 4 the broker is not running (or went
away), 5 message too large, 6 bad topic, group or request, 7 busy (a share of the message was not delivered: see Delivery),
8 a broker already runs (serve).

Topics.  A topic is a free name chosen by the plugins through their settings (voice.topic, sysop.topic; both default to "goal"): 1 to 64
characters of A-Z a-z 0-9 _ . : - , starting with a letter or a digit. The bus has no list of topics and no reserved name. A group name
follows the same rules.

Delivery.  A message goes to every subscriber of its topic that listens at that moment, and subscribers that gave the same --group share the
work: each group gets the message once, to ONE of its members, round robin. Nothing is buffered and nothing is acknowledged: a message is
written to the socket of a subscriber that may die before it reads it (the one loss window). A member that stopped reading is skipped, never
fed: the message goes to a member that reads, or, when every member of the group still has an earlier message unread, the group's share fails
after 0.2 s. A subscriber without a group that is far behind (more than 4 MiB unread) is skipped too. `pub` counts the receivers (the
subscribers without a group that took it, plus one for each group that took it) and answers:
  receivers > 0 and no share failed          ok, exit 0
  no receivers and nobody skipped            no_subscriber, exit 3 (ok with 0 receivers when --allow-none)
  a group or a subscriber was skipped as slow busy, exit 7; the reply still says how many received it (the others did get it)

Protocol (line-delimited JSON, UTF-8, a line is at most 1 MiB).  The client sends one request line and the broker answers:
  {"op":"pub","topic":T,"source":S,"body":B,"allow_none":BOOL}
                                                 one reply line  {"ok":true,"id":ID,"delivered":N}  or  {"ok":false,"err":CODE,"msg":TEXT},
                                                 then close; N is the number of receivers; a busy reply also has "delivered" and "busy" (the groups)
  {"op":"topics"}                                {"ok":true,"result":[{"topic":T,"subscribers":N,"groups":{NAME:MEMBERS}}]}
  {"op":"ping"}                                  {"ok":true,"v":1,"pid":P}
  {"op":"sub","topic":T,"group":G} | {"op":"watch"}
                                                 one {"ok":true,"subscribed":T,"group":G} line, then one line per event until either side closes
Error codes (err):  bad_request bad_topic bad_group too_large forbidden no_subscriber busy.  The CLI exits 6 for bad_request, bad_topic and
bad_group, 5 for too_large, 3 for no_subscriber, 7 for busy, and 1 for the others.
A subscriber receives the envelope, one per line:
  {"v":1,"id":"a02557-2","topic":"goal","source":"voice","peer":{"pid":66000,"uid":1000},"time":"2026-11-15T03:59:19.977Z","body":...}
id, time and peer are set by the broker (peer from SO_PEERCRED); source is a label declared by the sender, for display, never for authorization.
A watcher receives {"kind":"pub","topic":T,"envelope":E,"receivers":N,"result":"ok"|CODE}.
A consumer ignores unknown fields and refuses a larger v.

The client path imports no asyncio (start-up cost, about 13 ms in all); only `serve` does.
"""
import json, os, re, socket, sys, time

VERSION = 1
MAX_LINE = 1 << 20           # one line (request or envelope) at most 1 MiB, JSON included
ENVELOPE_SLACK = 1024        # what the broker adds to a request to make the envelope
MAX_REQUEST = MAX_LINE - ENVELOPE_SLACK
SLOW_BUFFER = 4 << 20        # a subscriber with more than this unread is slow
REQUEST_TIMEOUT = 10         # seconds to receive the request line
GROUP_GRACE = 0.2            # seconds a group whose members have unread messages waits for one to read before its share is answered busy
CLIENT_TIMEOUT = 45          # seconds a one-reply client waits for the broker
USAGE_EXIT = 2
EXIT = {"no_subscriber": 3, "too_large": 5, "bad_topic": 6, "bad_group": 6, "bad_request": 6, "busy": 7}
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def sock_path():
    p = os.environ.get("SB_BUS_SOCKET")
    if p:
        return p
    return os.path.join(os.environ.get("SB_RUN_DIR") or "/tmp/swarmbox", "bus.sock")


def name_ok(t):
    """a topic or a group name"""
    return isinstance(t, str) and NAME_RE.match(t) is not None


# ------------------------------------------------------------------------------------------------ the broker

asyncio = fcntl = struct = uuid = itertools = signal = traceback = None


def _load_server_modules():
    global asyncio, fcntl, struct, uuid, itertools, signal, traceback
    import asyncio, fcntl, itertools, signal, struct, traceback, uuid  # noqa: F811


def now():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int(t % 1 * 1000)


def _no_constant(name):
    raise ValueError("%s is not JSON" % name)


def _finite(text):
    v = float(text)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("%s is not a finite number" % text)
    return v


def loads(text):
    """json.loads that refuses NaN, Infinity and numbers that overflow to it (Python writes them back bare, which is not JSON): ValueError"""
    return json.loads(text, parse_constant=_no_constant, parse_float=_finite)


def encode(obj):
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode()


class Sub:
    __slots__ = ("w", "peer", "topic", "group")

    def __init__(self, w, peer, topic, group=None):
        self.w, self.peer, self.topic, self.group = w, peer, topic, group

    def slow(self):
        return self.w.transport.get_write_buffer_size() > SLOW_BUFFER

    def unread(self):
        """bytes written to this subscriber that it has not read: what waits in the transport plus what waits in the socket (SIOCOUTQ: for a
        unix socket, the bytes sent and not yet taken by the peer)"""
        n = self.w.transport.get_write_buffer_size()
        sock = self.w.get_extra_info("socket")
        try:
            import termios
            n += struct.unpack("i", fcntl.ioctl(sock.fileno(), termios.TIOCOUTQ, b"\0\0\0\0"))[0]
        except (OSError, AttributeError, ImportError, ValueError):
            pass
        return n


class Broker:
    """One broker on one unix socket. `acquire()` takes the single-instance lock; `run()` is the asyncio main."""

    def __init__(self, path, allowed_uids=None, log=None):
        _load_server_modules()
        self.path = path
        self.allowed = set(allowed_uids) if allowed_uids is not None else {os.getuid(), 0}
        self.log = log or self._log
        self.boot = uuid.uuid4().hex[:6]
        self.seq = itertools.count(1)
        self.subs = {}               # topic -> [Sub]; a group is round robin by moving the member that took a message to the end of the list
        self.watchers = []
        self.writers = set()
        self.lock_fd = None
        self.loop = None
        self.stop_event = None
        self.started = None          # a threading.Event for in-process callers, set once the socket accepts

    # ---- life
    @staticmethod
    def _log(msg):
        print("%s swarmbox-bus[%d]: %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid(), msg), file=sys.stderr, flush=True)

    def acquire(self):
        """flock on <socket>.lock (the kernel drops it however the process dies), then remove a stale socket. Returns 0, 8 or 1."""
        import stat
        d = os.path.dirname(self.path) or "."
        try:
            if not os.path.isdir(d):
                os.makedirs(d, mode=0o700, exist_ok=True)
            self.lock_fd = os.open(self.path + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except OSError as e:
            print("swarmbox-bus: cannot create %s.lock: %s" % (self.path, e.strerror or e), file=sys.stderr)
            return 1
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("swarmbox-bus: another broker holds %s.lock" % self.path, file=sys.stderr)
            os.close(self.lock_fd)
            self.lock_fd = None
            return 8
        # we own the lock: whatever socket file is there is stale (a crash) and goes; anything else is not ours to delete
        try:
            if stat.S_ISSOCK(os.lstat(self.path).st_mode):
                os.unlink(self.path)
            else:
                print("swarmbox-bus: %s exists and is not a socket" % self.path, file=sys.stderr)
                return 1
        except FileNotFoundError:
            pass
        return 0

    async def run(self, install_signals=False):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        old = os.umask(0o177)
        try:
            server = await asyncio.start_unix_server(self.handle, path=self.path, limit=MAX_LINE)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        if install_signals:
            for sg in (signal.SIGTERM, signal.SIGINT):
                self.loop.add_signal_handler(sg, self.stop_event.set)
        self.log("listening on %s" % self.path)
        if self.started:
            self.started.set()
        await self.stop_event.wait()
        server.close()
        for w in list(self.writers):       # subscribers see EOF and know the broker is gone
            try:
                w.close()
            except Exception:
                pass
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        if self.lock_fd is not None:        # the process ends right after; an in-process broker must let go too
            os.close(self.lock_fd)
            self.lock_fd = None
        self.log("stopped")

    def stop(self):
        """thread-safe"""
        try:
            if self.loop and self.stop_event:
                self.loop.call_soon_threadsafe(self.stop_event.set)
        except RuntimeError:        # the loop is already closed: stopped
            pass

    # ---- pieces
    @staticmethod
    def send(w, obj):
        w.write(encode(obj))

    async def reply(self, w, obj):
        self.send(w, obj)
        try:
            await w.drain()
        except Exception:
            pass

    def to_watchers(self, ev):
        for sub in list(self.watchers):
            if sub.slow() or sub.w.is_closing():
                self.watchers.remove(sub)
                sub.w.close()
                continue
            self.send(sub.w, ev)

    @staticmethod
    def peer_of(w):
        s = w.get_extra_info("socket")
        try:
            pid, uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        except (OSError, AttributeError):
            return {"pid": 0, "uid": -1}
        return {"pid": pid, "uid": uid}

    # ---- one connection
    async def handle(self, r, w):
        self.writers.add(w)
        try:
            await self.serve_one(r, w)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            self.log("internal error: " + traceback.format_exc().rstrip().replace("\n", " | "))
            await self.reply(w, {"ok": False, "err": "internal"})
        finally:
            self.writers.discard(w)
            try:
                w.close()
            except Exception:
                pass

    async def serve_one(self, r, w):
        peer = self.peer_of(w)
        if peer["uid"] not in self.allowed:
            return await self.reply(w, {"ok": False, "err": "forbidden", "msg": "the bus is private to its user"})
        try:
            line = await asyncio.wait_for(r.readuntil(b"\n"), REQUEST_TIMEOUT)
        except (asyncio.LimitOverrunError, ValueError):
            return await self.reply(w, {"ok": False, "err": "too_large"})
        except asyncio.IncompleteReadError as e:
            if e.partial:
                await self.reply(w, {"ok": False, "err": "bad_request"})
            return
        except asyncio.TimeoutError:
            return await self.reply(w, {"ok": False, "err": "bad_request", "msg": "no request line in %d s" % REQUEST_TIMEOUT})
        if len(line) > MAX_REQUEST:
            return await self.reply(w, {"ok": False, "err": "too_large"})
        try:
            req = loads(line)
            op = req["op"]
            if not isinstance(req, dict) or not isinstance(op, str):
                raise ValueError
        except Exception:
            return await self.reply(w, {"ok": False, "err": "bad_request"})
        if op == "ping":
            return await self.reply(w, {"ok": True, "v": VERSION, "pid": os.getpid()})
        if op == "pub":
            return await self.op_pub(w, req, peer)
        if op == "topics":
            return await self.reply(w, {"ok": True, "result": self.topics()})
        if op in ("sub", "watch"):
            return await self.op_stream(r, w, req, op, peer)
        await self.reply(w, {"ok": False, "err": "bad_request", "msg": "unknown op"})

    def live_subs(self, topic):
        return [x for x in self.subs.get(topic, []) if not x.w.is_closing()]

    def topics(self):
        out = []
        for topic in sorted(self.subs):
            subs = self.live_subs(topic)
            if subs:
                groups = {}
                for x in subs:
                    if x.group is not None:
                        groups[x.group] = groups.get(x.group, 0) + 1
                out.append({"topic": topic, "subscribers": len(subs), "groups": groups})
        return out

    async def plan(self, topic):
        """(plain, picks, busy, slow): the subscribers without a group that take the message, one member for each group that has a live
        one, the groups whose members all have an earlier message unread (after GROUP_GRACE: a member that is reading takes it in a moment),
        and how many subscribers without a group were skipped as slow"""
        end = self.loop.time() + GROUP_GRACE
        while True:
            subs = self.live_subs(topic)
            groups = {}
            for x in subs:
                if x.group is not None:
                    groups.setdefault(x.group, []).append(x)
            picks, busy = [], []
            for g, members in groups.items():
                live = [m for m in members if m.unread() == 0]
                (picks if live else busy).append(live[0] if live else g)
            if not busy or self.loop.time() >= end:
                break
            await asyncio.sleep(0.01)
        plain = [x for x in subs if x.group is None]
        ok = [x for x in plain if not x.slow()]
        return ok, picks, busy, len(plain) - len(ok)

    async def op_pub(self, w, req, peer):
        topic = req.get("topic", "")
        if not name_ok(topic):
            return await self.reply(w, {"ok": False, "err": "bad_topic"})
        if "body" not in req:
            return await self.reply(w, {"ok": False, "err": "bad_request", "msg": "no body"})
        # source is declared by the client (not trusted); id, time and peer are the broker's
        env = {"v": VERSION, "id": "%s-%d" % (self.boot, next(self.seq)), "topic": topic,
               "source": str(req.get("source") or "cli")[:64], "peer": peer, "time": now(), "body": req["body"]}
        if len(encode(env)) > MAX_LINE:
            return await self.reply(w, {"ok": False, "err": "too_large"})
        plain, picks, busy, slow = await self.plan(topic)
        lst = self.subs.get(topic, [])
        for x in plain + picks:
            self.send(x.w, env)
        for x in picks:
            if x in lst:             # round robin: the member that took this one goes last
                lst.remove(x)
                lst.append(x)
        n = len(plain) + len(picks)
        res = {"ok": True, "id": env["id"], "delivered": n}
        if busy or (n == 0 and slow):
            res = {"ok": False, "err": "busy", "delivered": n, "busy": busy,
                   "msg": "%s %s behind, not given the message" % (", ".join("group " + g for g in busy) or "a subscriber", "are" if len(busy) > 1 else "is")}
        elif n == 0 and req.get("allow_none") is not True:
            res = {"ok": False, "err": "no_subscriber", "delivered": 0}
        self.to_watchers({"kind": "pub", "topic": topic, "envelope": env, "receivers": n, "result": res.get("err", "ok")})
        await self.reply(w, res)

    async def op_stream(self, r, w, req, op, peer):
        group = None
        if op == "sub":
            topic, group = req.get("topic"), req.get("group")
            if not name_ok(topic):
                return await self.reply(w, {"ok": False, "err": "bad_topic"})
            if group is not None and not name_ok(group):
                return await self.reply(w, {"ok": False, "err": "bad_group"})
        else:
            topic = "*"
        sub = Sub(w, peer, topic, group)
        (self.subs.setdefault(topic, []) if op == "sub" else self.watchers).append(sub)
        self.send(w, {"ok": True, "subscribed": topic, "group": group})
        try:
            while await r.read(4096):       # what a subscriber says is ignored; EOF means it left or died
                pass
        finally:
            lst = self.subs.get(topic) if op == "sub" else self.watchers
            if lst is not None and sub in lst:
                lst.remove(sub)
            if op == "sub" and not self.subs.get(topic):
                self.subs.pop(topic, None)


def serve(argv):
    if argv:
        return usage_error("serve: unknown argument %s" % argv[0])
    b = Broker(sock_path())
    rc = b.acquire()
    if rc:
        return rc
    try:
        asyncio.run(b.run(install_signals=True))
    except OSError as e:
        print("swarmbox-bus: cannot listen on %s: %s" % (b.path, e.strerror or e), file=sys.stderr)
        rc = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)


# ------------------------------------------------------------------------------------------------ client

def usage_error(msg):
    print("swarmbox-bus: " + msg, file=sys.stderr)
    print("try: swarmbox-bus --help", file=sys.stderr)
    return USAGE_EXIT


def die(code, msg):
    print("swarmbox-bus: " + msg, file=sys.stderr)
    sys.exit(code)


def connect():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(sock_path())
    except (FileNotFoundError, ConnectionRefusedError):
        die(4, "the bus is not running (%s)" % sock_path())
    except PermissionError:
        die(1, "permission denied on %s (the socket is private to its user)" % sock_path())
    except OSError as e:
        die(1, "cannot connect to %s: %s" % (sock_path(), e.strerror or e))
    return s


def request(req, timeout=CLIENT_TIMEOUT):
    """send one request line; return the socket and a binary file for reading"""
    data = encode(req)
    if len(data) > MAX_REQUEST:
        die(5, "message too large (%d bytes, limit %d)" % (len(data), MAX_REQUEST))
    s = connect()
    s.settimeout(timeout)          # None for the streams, which wait as long as they like
    try:
        s.sendall(data)
    except (BrokenPipeError, ConnectionResetError):
        pass        # the broker may have answered and closed already: read the reply
    except socket.timeout:
        die(1, "the broker did not take the request")
    return s, s.makefile("rb")


def fail(rep):
    err = str(rep.get("err", "error"))
    msg = rep.get("msg")
    die(EXIT.get(err, 1), err + (": %s" % msg if msg else ""))


def one_reply(f):
    try:
        line = f.readline()
    except socket.timeout:
        die(1, "the broker did not answer in %d s" % CLIENT_TIMEOUT)
    except ConnectionError:
        line = b""
    if not line:
        die(4, "the broker closed the connection")
    try:
        rep = json.loads(line)
    except ValueError:
        die(1, "the broker sent something that is not JSON")
    if not rep.get("ok"):
        fail(rep)
    return rep


def raw_body(b):
    """one line for a body: a string that is plain single-line text as it is, anything else (a number, an object, null, a string with a line
    break, a string that could be read as JSON, such as "null" or "5") as one line of JSON, so a line reader sees one message per line"""
    if isinstance(b, str) and "\n" not in b and "\r" not in b:
        try:
            loads(b)
        except ValueError:
            return b
    return json.dumps(b, ensure_ascii=False)


def stream(f, raw=False, verbose=False):
    rep = one_reply(f)
    if verbose or os.environ.get("SB_BUS_VERBOSE"):
        print(json.dumps(rep), file=sys.stderr, flush=True)
    out = sys.stdout.buffer
    try:
        while True:
            line = f.readline()
            if not line:
                break
            if raw:
                line = (raw_body(json.loads(line).get("body")) + "\n").encode()
            out.write(line)
            out.flush()
    except BrokenPipeError:        # `| head`: the reader left, which is not an error
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())      # so that the flush at exit does not complain
        return 0
    except ConnectionError:
        pass
    print("swarmbox-bus: the broker closed the connection", file=sys.stderr)
    return 4


def flags(a, known):
    """split options from positional arguments: known is {"--raw": False, "--lines": True} (True: takes a value). (opts, rest) or None"""
    opts, rest, i = {}, [], 0
    while i < len(a):
        x = a[i]
        if x == "--":            # the end of the options: what follows is positional, even when it starts with a dash
            rest.extend(a[i + 1:])
            break
        if x in known:
            if known[x]:
                if i + 1 >= len(a):
                    return None
                opts[x] = a[i + 1]
                i += 1
            else:
                opts[x] = True
        elif x.startswith("-") and x != "-":
            return None
        else:
            rest.append(x)
        i += 1
    return opts, rest


def read_stdin():
    data = sys.stdin.buffer.read(MAX_LINE + 1)
    if len(data) > MAX_REQUEST:
        die(5, "message too large (more than %d bytes on stdin)" % MAX_REQUEST)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        die(6, "the message is not valid UTF-8")
    return text[:-1] if text.endswith("\n") else text


def cmd_pub(a):
    default = os.environ.get("SB_BUS_SOURCE", "cli")
    p = flags(a, {"--source": True, "--allow-none": False})
    if p is None or not 1 <= len(p[1]) <= 2:
        return usage_error("usage: pub [--source S] [--allow-none] TOPIC [MESSAGE|-]")
    opts, (topic, *rest) = p
    msg = rest[0] if rest else "-"
    if msg == "-":
        msg = read_stdin()
    try:
        body = loads(msg)         # one line of JSON, or else plain text (NaN and Infinity are text)
    except ValueError:
        body = msg
    s, f = request({"op": "pub", "topic": topic, "source": opts.get("--source", default), "body": body, "allow_none": "--allow-none" in opts})
    rep = one_reply(f)
    print(json.dumps({"id": rep["id"], "receivers": rep["delivered"]}))
    return 0


def cmd_restart():
    pidfile = os.path.join(os.path.dirname(sock_path()), "bus-supervisor.pid")
    try:
        with open(pidfile) as fh:
            pid = int(fh.read().strip())
        if pid <= 1:
            raise ValueError
    except (OSError, ValueError):
        die(1, "no supervisor is running (no usable %s; is serve running?)" % pidfile)
    try:
        os.kill(pid, 10)        # SIGUSR1
    except OSError:
        die(1, "the supervisor (process %d) is not running" % pid)
    print("swarmbox-bus: asked the supervisor (process %d) to start the broker again" % pid)
    return 0


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return USAGE_EXIT
    cmd, a = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "serve":
        return serve(a)
    if cmd == "pub":
        return cmd_pub(a)
    if cmd == "topics":
        if a:
            return usage_error("usage: topics")
        s, f = request({"op": "topics"})
        print(json.dumps(one_reply(f)["result"]))
        return 0
    if cmd == "sub":
        p = flags(a, {"--raw": False, "-v": False, "--group": True})
        if p is None or len(p[1]) != 1:
            return usage_error("usage: sub [--group NAME] [--raw] [-v] TOPIC")
        s, f = request({"op": "sub", "topic": p[1][0], "group": p[0].get("--group")}, None)
        return stream(f, "--raw" in p[0], "-v" in p[0])
    if cmd == "watch":
        p = flags(a, {"-v": False})
        if p is None or p[1]:
            return usage_error("usage: watch [-v]")
        s, f = request({"op": "watch"}, None)
        return stream(f, False, "-v" in p[0])
    if cmd == "ping":
        if a:
            return usage_error("usage: ping")
        s, f = request({"op": "ping"})
        one_reply(f)
        return 0
    if cmd == "restart":
        return cmd_restart() if not a else usage_error("usage: restart")
    return usage_error("unknown command %s" % cmd)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
