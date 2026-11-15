#!/usr/bin/python3 -S
"""swarmbox-bus: the broker of the box and its command line, one file, standard library only.

  swarmbox-bus serve [--driver auto|tmux|stub]          run the broker (asyncio, one process, one unix socket); the entrypoint runs this
  swarmbox-bus pub [--source S] [--] TOPIC [MESSAGE|-]  publish; MESSAGE is one line of JSON or plain text (after `--` it may start with
                                                   a dash); "-" (the default) reads stdin
  swarmbox-bus sub [--raw] [-v] [TOPIC]            stream the messages of a queue topic (only "goal"); --raw prints the bodies only,
                                                   one line each (plain one-line text as it is, anything else as JSON)
  swarmbox-bus get TOPIC [--lines N]               read state:  tab/<tab>/screen
  swarmbox-bus ls [PREFIX]                         list state:  "" (the roots), tab/ (the tabs)
  swarmbox-bus watch [--no-screen] [-v]            everything that passes (publications, reads), one JSON line each
  swarmbox-bus ping                                exit 0 when the broker answers
  swarmbox-bus restart                             ask the entrypoint's supervisor to start the broker again (SIGUSR1)

Exit codes: 0 ok, 1 other error, 2 usage, 3 no subscriber, 4 the broker is not running (or went away), 5 message too large,
6 bad topic or bad request, 7 busy (the only subscribers are too slow), 8 a broker already runs (serve).

Topics.  goal                a queue: one live subscriber gets each message (round robin), nothing is buffered, no ack; `pub` fails with
                             3 when nobody listens and with 7 when every subscriber still has an earlier message unread (a consumer that
                             stopped reading is skipped, never fed: the message goes to one that reads, or fails with 7 after 0.2 s). The
                             one loss window of "no ack": a message is written to the socket of a consumer that dies before it reads it
         tab/<tab>/in        to a tmux tab, through the driver (below); the reply of `pub` is the driver's result
         tab/<tab>/screen    state, read with `get` (never published)
         <tab> is 1 to 64 characters of A-Z a-z 0-9 _ . : @ -  (the driver resolves it: a window id such as @3, or a name).

Protocol (line-delimited JSON, UTF-8, a line is at most 1 MiB).  The client sends one request line and the broker answers:
  {"op":"pub","topic":T,"source":S,"body":B}     one reply line  {"ok":true,"id":ID,"delivered":1}  or  {"ok":false,"err":CODE,"msg":TEXT}, then close
  {"op":"get","topic":T,"lines":N}               {"ok":true,"result":R}
  {"op":"ls","topic":PREFIX}                     {"ok":true,"result":R}
  {"op":"ping"}                                  {"ok":true,"v":1,"pid":P}
  {"op":"sub","topic":"goal"} | {"op":"watch","no_screen":BOOL}
                                                 one {"ok":true,"subscribed":T} line, then one line per event until either side closes
Error codes (err):  bad_request bad_topic too_large forbidden no_subscriber busy  and the driver's: no_such_tab ambiguous_tab bad_body
timeout driver_error (and whatever else a driver raises as DriverError).  The CLI exits 6 for bad_request, bad_topic and bad_body, 5 for
too_large, 3 for no_subscriber, 7 for busy, and 1 for the others.
A subscriber receives the envelope, one per line:
  {"v":1,"id":"a02557-2","topic":"goal","source":"voice","peer":{"pid":66000,"uid":1000},"time":"2026-11-15T03:59:19.977Z","body":...}
id, time and peer are set by the broker (peer from SO_PEERCRED); source is a label declared by the sender, for display, never for authorization.
A consumer ignores unknown fields and refuses a larger v.

The driver (the interface of state and of the tab topics).  The broker knows nothing about tmux: it calls a Driver, which is a few
blocking methods run in worker threads (never in the event loop), and it serialises the sends to one tab:
  list_tabs() -> list of dict         one dict per tab, each with at least "tab" (the address to use in topics, for example "@3") and
                                      "active" (bool, true for exactly one); others are free ("index", "name", "dir", "cmd", ...)
  screen(tab, lines) -> dict          {"text": str, "cursor": [x, y], ...}; text is already redacted; lines is None or the last N lines
  send(tab, body) -> None             types into the tab; body is the JSON value the sender gave (the plain driver: {"run": str} or {"input": str})
Failures are raised as DriverError(code, message): code is a short word (no_such_tab, ambiguous_tab, bad_body, no_session, ...) that
reaches the client as err, message as msg. Any other exception is logged and answered as driver_error. A call that takes more than 30 s is
answered as timeout (its thread cannot be killed: for a send the tab stays locked until the thread ends, so later sends to it wait). A driver must keep nothing the broker needs: it is called from several threads at once
for reads, and never twice at once for sends to the same tab.
The tmux driver is swarmbox-bus-tmux.py (its docstring has the tabs, the screen and the typing rules); StubDriver below is the in-memory
one used by tests; make_driver() picks the driver ("auto" is tmux; SB_BUS_TMUX_SESSION and SB_BUS_TMUX_SOCKET choose the session and, for
tests, a tmux server with -L).

The client path imports no asyncio (start-up cost, about 13 ms in all); only `serve` does.
"""
import json, os, socket, sys, time

VERSION = 1
MAX_LINE = 1 << 20           # one line (request or envelope) at most 1 MiB, JSON included
ENVELOPE_SLACK = 1024        # what the broker adds to a request to make the envelope
MAX_REQUEST = MAX_LINE - ENVELOPE_SLACK
SLOW_BUFFER = 4 << 20        # a subscriber with more than this unread is slow
REQUEST_TIMEOUT = 10         # seconds to receive the request line
DRIVER_TIMEOUT = 30          # seconds for one driver call
GOAL_GRACE = 0.2             # seconds a goal waits for a subscriber that has read everything before it is answered busy
CLIENT_TIMEOUT = 45          # seconds a one-reply client waits for the broker
USAGE_EXIT = 2
EXIT = {"no_subscriber": 3, "too_large": 5, "bad_topic": 6, "bad_request": 6, "bad_body": 6, "busy": 7}
TAB_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:@-")


def sock_path():
    p = os.environ.get("SB_BUS_SOCKET")
    if p:
        return p
    return os.path.join(os.environ.get("SB_RUN_DIR") or "/tmp/swarmbox", "bus.sock")


def tab_ok(t):
    return 0 < len(t) <= 64 and all(c in TAB_CHARS for c in t) and t.strip(".") != ""


def tab_topic(t, last):
    """the <tab> of 'tab/<tab>/<last>', or None"""
    parts = t.split("/")
    if len(parts) == 3 and parts[0] == "tab" and parts[2] == last and tab_ok(parts[1]):
        return parts[1]
    return None


def pub_topic_ok(t):
    return t == "goal" or tab_topic(t, "in") is not None


# ------------------------------------------------------------------------------------------------ the driver

class DriverError(Exception):
    def __init__(self, code, message=""):
        Exception.__init__(self, "%s: %s" % (code, message) if message else code)
        self.code, self.message = code, message


class Driver:
    """The interface (see the module docstring). A real driver subclasses this and overrides the three methods."""

    def list_tabs(self):
        raise NotImplementedError

    def screen(self, tab, lines):
        raise NotImplementedError

    def send(self, tab, body):
        raise NotImplementedError


class StubDriver(Driver):
    """In memory: a few tabs, a fixed screen, and a list of what was sent (`sent`)."""

    def __init__(self, tabs=None):
        self.tabs = tabs if tabs is not None else {"main": {"name": "main", "dir": "/work", "cmd": "bash", "active": True}}
        self.sent = []

    def _need(self, tab):
        if tab not in self.tabs:
            raise DriverError("no_such_tab", "no tab %s" % tab)

    def list_tabs(self):
        return [dict(v, tab=k) for k, v in self.tabs.items()]

    def screen(self, tab, lines):
        self._need(tab)
        rows = ["screen of %s line %d" % (tab, i) for i in range(1, 25)]
        if lines:
            rows = rows[-lines:]
        return {"text": "\n".join(rows) + "\n", "cursor": [0, len(rows) - 1]}

    def send(self, tab, body):
        self._need(tab)
        if not (isinstance(body, dict) and len(body) == 1 and isinstance(next(iter(body.values())), str)
                and next(iter(body)) in ("run", "input")):
            raise DriverError("bad_body", 'the body of a tab message is {"run": text} or {"input": text}')
        self.sent.append((tab, body))


DRIVER_MODULE = "swarmbox-bus-tmux.py"


def load_tmux_module():
    """The tmux driver lives in its own file next to the bus (the folder of this file, or /usr/local/lib/swarmbox in the image)."""
    import importlib.util
    here = os.path.dirname(os.path.realpath(__file__))
    for d in (os.environ.get("SB_BUS_DRIVER_DIR"), here, "/usr/local/lib/swarmbox"):
        path = os.path.join(d, DRIVER_MODULE) if d else None
        if path and os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("swarmbox_bus_tmux", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ValueError("the tmux driver %s was not found" % DRIVER_MODULE)


def make_driver(name="auto"):
    """The driver the broker uses: "auto" and "tmux" are the tmux driver (session main, see the file of the driver), "stub" the in-memory one."""
    if name == "stub":
        return StubDriver()
    if name in ("auto", "tmux"):
        mod = load_tmux_module()

        class TmuxDriver(mod.TmuxDriver, Driver):
            pass
        return TmuxDriver(DriverError)
    raise ValueError("unknown driver %r" % name)


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
    __slots__ = ("w", "peer", "topic", "no_screen")

    def __init__(self, w, peer, topic, no_screen=False):
        self.w, self.peer, self.topic, self.no_screen = w, peer, topic, no_screen

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

    def __init__(self, path, driver, allowed_uids=None, log=None):
        _load_server_modules()
        self.path = path
        self.driver = driver
        self.allowed = set(allowed_uids) if allowed_uids is not None else {os.getuid(), 0}
        self.log = log or self._log
        self.boot = uuid.uuid4().hex[:6]
        self.seq = itertools.count(1)
        self.subs = {"goal": []}     # topic -> [Sub]; goal is round robin by rotating the list
        self.watchers = []
        self.writers = set()
        self.tab_locks = {}          # tab -> [asyncio.Lock, users]
        self.lock_fd = None
        self.loop = None
        self.stop_event = None
        self.started = None          # a threading.Event for in-process callers, set once the socket accepts
        self.executor = None

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
        from concurrent.futures import ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="bus-driver")
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
        self.executor.shutdown(wait=False)
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
            e = ev
            res = ev.get("result")
            if sub.no_screen and ev.get("kind") == "read" and isinstance(res, dict) and "text" in res:
                e = dict(ev, result=dict(res, text="<%d bytes omitted>" % len(res["text"])))
            self.send(sub.w, e)

    @staticmethod
    def peer_of(w):
        s = w.get_extra_info("socket")
        try:
            pid, uid, _gid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        except (OSError, AttributeError):
            return {"pid": 0, "uid": -1}
        return {"pid": pid, "uid": uid}

    async def call(self, fn, *args):
        try:
            return await asyncio.wait_for(self.loop.run_in_executor(self.executor, fn, *args), DRIVER_TIMEOUT)
        except DriverError:
            raise
        except asyncio.TimeoutError:
            raise DriverError("timeout", "the driver did not answer in %d s" % DRIVER_TIMEOUT)
        except Exception as e:
            self.log("driver failed: " + traceback.format_exc().rstrip().replace("\n", " | "))
            raise DriverError("driver_error", type(e).__name__)

    async def send_to_tab(self, tab, body):
        """One send at a time per tab, for as long as the driver thread really runs: when the call times out the answer is `timeout` but the
        tab stays locked until the thread ends, so a retry never types over (or twice) what is still being typed."""
        ent = self.tab_locks.setdefault(tab, [asyncio.Lock(), 0])
        ent[1] += 1

        def drop():
            ent[1] -= 1
            if ent[1] == 0 and self.tab_locks.get(tab) is ent:
                del self.tab_locks[tab]

        def unlock():
            ent[0].release()
            drop()
        try:
            await asyncio.wait_for(ent[0].acquire(), DRIVER_TIMEOUT)
        except asyncio.TimeoutError:
            drop()
            raise DriverError("timeout", "an earlier message is still being typed into the tab (waited %g s); nothing was typed" % DRIVER_TIMEOUT)
        except BaseException:
            drop()
            raise
        fut = self.loop.run_in_executor(self.executor, self.driver.send, tab, body)
        fut.add_done_callback(lambda f: (unlock(), f.cancelled() or f.exception()))     # retrieving the exception: it is reported below
        try:
            await asyncio.wait_for(asyncio.shield(fut), DRIVER_TIMEOUT)
        except DriverError:
            raise
        except asyncio.TimeoutError:
            raise DriverError("timeout", "the driver did not finish in %g s; it may still be typing into the tab (the tab stays locked until it ends): do not send it again" % DRIVER_TIMEOUT)
        except Exception as e:
            self.log("driver failed: " + traceback.format_exc().rstrip().replace("\n", " | "))
            raise DriverError("driver_error", type(e).__name__)

    @staticmethod
    def err(e):
        res = {"ok": False, "err": e.code}
        if e.message:
            res["msg"] = e.message
        return res

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
        if op in ("get", "ls"):
            return await self.op_read(w, req, op, peer)
        if op in ("sub", "watch"):
            return await self.op_stream(r, w, req, op, peer)
        await self.reply(w, {"ok": False, "err": "bad_request", "msg": "unknown op"})

    async def op_pub(self, w, req, peer):
        topic = req.get("topic", "")
        if not isinstance(topic, str) or not pub_topic_ok(topic):
            return await self.reply(w, {"ok": False, "err": "bad_topic"})
        if "body" not in req:
            return await self.reply(w, {"ok": False, "err": "bad_request", "msg": "no body"})
        # source is declared by the client (not trusted); id, time and peer are the broker's
        env = {"v": VERSION, "id": "%s-%d" % (self.boot, next(self.seq)), "topic": topic,
               "source": str(req.get("source") or "cli")[:64], "peer": peer, "time": now(), "body": req["body"]}
        if len(encode(env)) > MAX_LINE:
            return await self.reply(w, {"ok": False, "err": "too_large"})
        if topic == "goal":
            subs = [s for s in self.subs["goal"] if not s.w.is_closing()]
            live = [s for s in subs if s.unread() == 0]
            end = self.loop.time() + GOAL_GRACE
            while subs and not live and self.loop.time() < end:      # a consumer that is reading takes its message in a moment
                await asyncio.sleep(0.01)
                subs = [s for s in self.subs["goal"] if not s.w.is_closing()]
                live = [s for s in subs if s.unread() == 0]
            if not subs:
                res = {"ok": False, "err": "no_subscriber"}
            elif not live:
                res = {"ok": False, "err": "busy"}
            else:
                s = live[0]
                self.subs["goal"].remove(s)
                self.subs["goal"].append(s)          # round robin
                self.send(s.w, env)
                res = {"ok": True, "id": env["id"], "delivered": 1}
        else:
            try:
                await self.send_to_tab(tab_topic(topic, "in"), env["body"])
                res = {"ok": True, "id": env["id"], "delivered": 1}
            except DriverError as e:
                res = self.err(e)
        self.to_watchers({"kind": "pub", "envelope": env, "result": res.get("err", "ok")})
        await self.reply(w, res)

    async def op_read(self, w, req, op, peer):
        topic = req.get("topic", "")
        lines = req.get("lines")
        if not isinstance(topic, str) or not (lines is None or (isinstance(lines, int) and not isinstance(lines, bool) and 0 < lines <= 100000)):
            return await self.reply(w, {"ok": False, "err": "bad_request"})
        try:
            if op == "ls":
                if topic == "":
                    result = ["tab/"]
                elif topic in ("tab", "tab/"):
                    result = await self.call(self.driver.list_tabs)
                else:
                    return await self.reply(w, {"ok": False, "err": "bad_topic"})
            else:
                tab = tab_topic(topic, "screen")
                if tab is None:
                    return await self.reply(w, {"ok": False, "err": "bad_topic"})
                result = await self.call(self.driver.screen, tab, lines)
            res = {"ok": True, "result": result}
        except DriverError as e:
            res = self.err(e)
        self.to_watchers({"kind": "read", "op": op, "topic": topic, "peer": peer, "time": now(), "result": res.get("result", res.get("err"))})
        await self.reply(w, res)

    async def op_stream(self, r, w, req, op, peer):
        topic = req.get("topic", "goal")
        if op == "sub" and topic != "goal":
            return await self.reply(w, {"ok": False, "err": "bad_topic", "msg": "only goal can be subscribed"})
        sub = Sub(w, peer, topic if op == "sub" else "*", bool(req.get("no_screen")))
        (self.subs["goal"] if op == "sub" else self.watchers).append(sub)
        self.send(w, {"ok": True, "subscribed": sub.topic})
        try:
            while await r.read(4096):       # what a subscriber says is ignored; EOF means it left or died
                pass
        finally:
            for lst in (self.subs["goal"], self.watchers):
                if sub in lst:
                    lst.remove(sub)


def serve(argv):
    name = "auto"
    a = list(argv)
    while a:
        if a[0] == "--driver" and len(a) > 1:
            name, a = a[1], a[2:]
        else:
            return usage_error("serve: unknown argument %s" % a[0])
    try:
        driver = make_driver(name)
    except ValueError as e:
        return usage_error(str(e))
    b = Broker(sock_path(), driver)
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
    os._exit(rc)        # a driver thread stuck in tmux must not keep the process alive


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
    p = flags(a, {"--source": True})
    if p is None or not 1 <= len(p[1]) <= 2:
        return usage_error("usage: pub [--source S] TOPIC [MESSAGE|-]")
    opts, (topic, *rest) = p
    msg = rest[0] if rest else "-"
    if msg == "-":
        msg = read_stdin()
    try:
        body = loads(msg)         # one line of JSON, or else plain text (NaN and Infinity are text)
    except ValueError:
        body = msg
    s, f = request({"op": "pub", "topic": topic, "source": opts.get("--source", default), "body": body})
    print(one_reply(f)["id"])
    return 0


def cmd_read(op, a):
    p = flags(a, {"--lines": True} if op == "get" else {})
    if p is None or len(p[1]) > 1 or (op == "get" and not p[1]):
        return usage_error("usage: get TOPIC [--lines N]" if op == "get" else "usage: ls [PREFIX]")
    opts, rest = p
    req = {"op": op, "topic": rest[0] if rest else ""}
    if "--lines" in opts:
        try:
            req["lines"] = int(opts["--lines"])
        except ValueError:
            return usage_error("--lines takes a number")
    s, f = request(req)
    print(json.dumps(one_reply(f)["result"]))
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
    if cmd in ("get", "ls"):
        return cmd_read(cmd, a)
    if cmd == "sub":
        p = flags(a, {"--raw": False, "-v": False})
        if p is None or len(p[1]) > 1:
            return usage_error("usage: sub [--raw] [-v] [TOPIC]")
        s, f = request({"op": "sub", "topic": p[1][0] if p[1] else "goal"}, None)
        return stream(f, "--raw" in p[0], "-v" in p[0])
    if cmd == "watch":
        p = flags(a, {"--no-screen": False, "-v": False})
        if p is None or p[1]:
            return usage_error("usage: watch [--no-screen] [-v]")
        s, f = request({"op": "watch", "no_screen": "--no-screen" in p[0]}, None)
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
