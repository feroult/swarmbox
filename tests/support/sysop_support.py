"""Shared bits of the sysop tests: the library path, a scriptable fake of the bus (the socket protocol of swarmbox-bus, in a thread), private
folders for a service, and the fake claude. Nothing here needs tmux, a network or a model."""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, close_listener  # noqa: E402
from waiting import wait_until  # noqa: E402

SYSOP = os.path.join(ROOT, "container", "addons", "sysop")
LIB = os.path.join(SYSOP, "lib")
sys.path.insert(0, LIB)
FIXTURES = os.path.join(ROOT, "tests", "support", "fixtures", "sysop")
FAKE_BIN = os.path.join(FIXTURES, "bin")

from swarmbox_sysop import config, paths  # noqa: E402


def wait_for(fn, seconds=10.0, step=0.02):
    return wait_until(fn, seconds, step)


def fast_cond(svc, cap=0.02):
    """The waits of a Service (the poll of its main loop, the pause that grows after a failed turn: up to seconds) cut to `cap` seconds: a test of a
    failing turn does not wait for them. Call it before svc.run starts."""
    class Cond(threading.Condition):
        def wait(self, timeout=None):
            return threading.Condition.wait(self, None if timeout is None else min(timeout, cap))
    svc.cond = Cond()
    return svc


def short_tmp(prefix="sbsy-"):
    """a short folder: a unix socket path holds at most 107 bytes"""
    base = os.path.realpath(tempfile.gettempdir())
    if len(base) > 30 or not os.access(base, os.W_OK):
        base = "/tmp"
    return os.path.realpath(tempfile.mkdtemp(prefix=prefix, dir=base))


class Env:
    """private run and state folders and a socket path in one short temporary folder, as an environment mapping"""

    def __init__(self, **extra):
        self.dir = short_tmp()
        self.env = {"SB_RUN_DIR": os.path.join(self.dir, "run"), "SB_STATE_DIR": os.path.join(self.dir, "state"),
                    "SB_BUS_SOCKET": os.path.join(self.dir, "bus.sock"), "HOME": os.path.join(self.dir, "home"),
                    "PATH": FAKE_BIN + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
                    # never the tmux server of whoever runs the suite: a dock of a service started here finds its own, empty one
                    "SB_TABS_SOCKET": "sbsy-%d" % os.getpid(), "TMUX_TMPDIR": os.path.join(self.dir, "sb-tmux"), "TMPDIR": os.path.join(self.dir, "sb-tmp")}
        os.makedirs(self.env["HOME"])
        os.makedirs(self.env["TMUX_TMPDIR"])
        os.makedirs(self.env["TMPDIR"])
        self.env.update(extra)

    @property
    def paths(self):
        return paths.Paths(self.env)

    def cfg(self, **over):
        e = {k: v for k, v in self.env.items() if k.startswith("SWARMBOX_SYSOP_")}
        e.update({"SWARMBOX_SYSOP_" + k.upper(): str(v) for k, v in over.items()})
        return config.load(e)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class FakeBus:
    """The socket protocol of swarmbox-bus for goals: sub (a topic, a group), pub (counted, round robin inside a group), ping. No tabs: those are
    FakeTabs.

    sub_reqs    [(topic, group)] of every subscription accepted (the service must ask for the topic and the group of its settings)
    pubs        [(topic, source, body)] of every publication accepted
    subs        the connections that listen now (same order as sub_info: [(topic, group)])
    """

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.subs, self.sub_info, self.conns = [], [], []
        self.sub_reqs, self.pubs = [], []
        self.rr = {}
        self.srv = None
        self.thread = None
        self.up = False
        self.counter = 0
        self.start()

    # ---- life
    def start(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        os.chmod(self.path, 0o600)
        self.srv.listen(16)
        self.up = True
        self.thread = threading.Thread(target=self._accept, args=(self.srv,), daemon=True)
        self.thread.start()

    def stop(self):
        """the broker goes away: the listener and every connection close, the socket file is removed"""
        self.up = False
        close_listener(self.srv, self.thread)
        with self.lock:
            conns, self.conns, self.subs, self.sub_info = self.conns, [], [], []
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def _accept(self, srv):
        while self.up:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with self.lock:
                self.conns.append(c)
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        f = c.makefile("rb")
        try:
            line = f.readline()
            if not line:
                return
            req = json.loads(line)
            op = req.get("op")
            if op == "sub":
                topic, group = req.get("topic"), req.get("group")
                self._send(c, {"ok": True, "subscribed": topic, "group": group})
                with self.lock:
                    self.subs.append(c)
                    self.sub_info.append((topic, group))
                    self.sub_reqs.append((topic, group))
                while f.readline():
                    pass
                return
            self._send(c, self.reply(req))
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                if c in self.subs:
                    i = self.subs.index(c)
                    self.subs.pop(i)
                    self.sub_info.pop(i)
                if c in self.conns:
                    self.conns.remove(c)
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _send(c, obj):
        c.sendall((json.dumps(obj) + "\n").encode())

    # ---- the protocol
    def reply(self, req):
        op, topic = req.get("op"), req.get("topic", "")
        if op == "ping":
            return {"ok": True, "v": 1, "pid": os.getpid()}
        if op == "pub":
            self.counter += 1
            env = {"v": 1, "id": "fb-%d" % self.counter, "topic": topic, "source": str(req.get("source") or "cli"), "peer": {"pid": 1, "uid": os.getuid()},
                   "time": "now", "body": req.get("body")}
            r = self.deliver(env)
            if r.get("ok"):
                self.pubs.append((topic, env["source"], req.get("body")))
            return r
        return {"ok": False, "err": "bad_request"}

    def deliver(self, env):
        """to every subscriber of the topic that has no group, and to ONE member (round robin) of each group"""
        with self.lock:
            mine = [(c, g) for c, (t, g) in zip(self.subs, self.sub_info) if t == env["topic"]]
        targets, seen = [], set()
        for c, g in mine:
            if g is None:
                targets.append(c)
            elif g not in seen:
                seen.add(g)
                members = [x for x, gg in mine if gg == g]
                k = self.rr.get((env["topic"], g), 0)
                self.rr[(env["topic"], g)] = k + 1
                targets.append(members[k % len(members)])
        n = 0
        for c in targets:
            try:
                self._send(c, env)
                n += 1
            except OSError:
                pass
        if not n:
            return {"ok": False, "err": "no_subscriber", "msg": "nobody is subscribed to %s" % env["topic"]}
        return {"ok": True, "id": env["id"], "delivered": n}

    def publish_goal(self, text, source="cli", body=None, topic="goal"):
        """a goal as the broker delivers it; returns the reply"""
        self.counter += 1
        env = {"v": 1, "id": "fb-%d" % self.counter, "topic": topic, "source": source, "peer": {"pid": 1, "uid": os.getuid()}, "time": "now",
               "body": body if body is not None else {"text": text}}
        return self.deliver(env)

    def wait_subscriber(self, n=1, seconds=10):
        return wait_for(lambda: len(self.subs) >= n, seconds)


class FakeTabs:
    """A fake `swarmbox-tabs`: the stub command tests/support/fixtures/sysop/bin/swarmbox-tabs forwards its arguments and its stdin to this object (a
    unix socket in a thread), which records the call and answers with scripted JSON, as the real command does ({"err","msg"} for a failure).
    Use `cmd_env` (SWARMBOX_SYSOP_TABS_CMD) in an environment, or `client()` for a tabsclient.Tabs on it.

    tabs        {id: {"tab", "label", "index", "name", "dir", "cmd", "active", "pane", "panes"}}
    screens     {id: text or callable(fake, id) -> text}
    sent        [(tab, {"run": text} | {"input": text})] of every accepted send
    calls       [(argv, stdin)] of every call
    reads       the tab of every screen call
    errors      {tab: (code, msg)}: a send to that tab fails; `ls_error` and `get_error` do the same for list and screen
    on_send     callback(fake, tab, body) after an accepted send (change a screen, ...)
    send_delay  seconds a send takes (the pauses of the real command)
    """

    def __init__(self, path, tabs=None):
        self.path = path
        self.tabs = tabs if tabs is not None else {
            "@1": dict(tab="@1", label="0:shell", index=0, name="shell", dir="/work", cmd="bash", active=True, pane="%1", panes=1),
            "@2": dict(tab="@2", label="1:agent", index=1, name="agent", dir="/work", cmd="claude", active=False, pane="%2", panes=1)}
        self.screens = {"@1": "$ ", "@2": "> "}
        self.sent, self.calls, self.reads, self.errors, self.ls_error, self.get_error = [], [], [], {}, None, None
        self.on_send, self.send_delay = None, 0.0
        self.up = False
        self.srv = None
        self.start()

    @property
    def cmd_env(self):
        return {"SWARMBOX_SYSOP_TABS_CMD": "%s --fake-socket %s" % (os.path.join(FAKE_BIN, "swarmbox-tabs"), self.path)}

    def client(self, **kw):
        from swarmbox_sysop import tabsclient
        return tabsclient.Tabs(env=dict(os.environ, **self.cmd_env), **kw)

    def start(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(16)
        self.up = True
        self.thread = threading.Thread(target=self._accept, args=(self.srv,), daemon=True)
        self.thread.start()

    def stop(self):
        """the command cannot reach the fake any more: it answers no_tmux, as the real one does when tmux is gone"""
        self.up = False
        close_listener(self.srv, self.thread)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def _accept(self, srv):
        while self.up:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        try:
            f = c.makefile("rb")
            req = json.loads(f.readline())
            out, rc = self.call(req["argv"], req.get("stdin", ""))
            c.sendall((json.dumps({"out": out, "rc": rc}) + "\n").encode())
        except (OSError, ValueError, KeyError):
            pass
        finally:
            c.close()

    @staticmethod
    def _err(code, msg):
        return {"err": code, "msg": msg}, (2 if code in ("usage", "bad_body") else 1)

    def call(self, argv, stdin):
        self.calls.append((list(argv), stdin))
        cmd = argv[0] if argv else ""
        if cmd == "list":
            if self.ls_error:
                return self._err(*self.ls_error)
            return [dict(t) for t in self.tabs.values()], 0
        if cmd == "screen":
            tab = argv[1]
            self.reads.append(tab)
            if self.get_error:
                return self._err(*self.get_error)
            if tab not in self.tabs:
                return self._err("no_such_tab", "no tab %s" % tab)
            s = self.screens.get(tab, "")
            text = s(self, tab) if callable(s) else s
            return {"tab": tab, "pane": "%1", "text": text, "cursor": [0, 0], "alternate": False, "in_mode": False, "mode": "", "size": [80, 24], "lines": None}, 0
        if cmd == "send":
            tab, key = argv[1], argv[2]
            if key not in ("--run", "--input") or argv[3:4] != ["-"]:
                return self._err("usage", "the fake takes send TAB (--run|--input) -")
            text = stdin[:-1] if stdin.endswith("\n") else stdin
            body = {key[2:]: text}
            if tab in self.errors:
                return self._err(*self.errors[tab])
            if tab not in self.tabs:
                return self._err("no_such_tab", "no tab %s" % tab)
            time.sleep(self.send_delay)
            self.sent.append((tab, body))
            if self.on_send:
                self.on_send(self, tab, body)
            return {"ok": True, "tab": tab, "pane": "%1", "submitted": key == "--run"}, 0
        return self._err("usage", "unknown command %s" % cmd)

    def set_screen(self, tab, text):
        self.screens[tab] = text


class FakeService:
    """The files of a running sysop service, written by hand: the lock (held by this process, so service.running() is true), status.json, the state
    of a goal and its pending action. What a REAL panel and the key commands read, with no brain behind them."""

    def __init__(self, pth):
        import fcntl
        self.paths = pth.make()
        self.fd = os.open(pth.lock, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.gid = "g1"
        self.write_status(None)

    def close(self):
        os.close(self.fd)

    def write_status(self, current, queue=()):
        from swarmbox_sysop import ipc
        ipc.write_json(self.paths.status, {"pid": os.getpid(), "bus": "connected", "current": current, "queue": list(queue), "settings": {"autonomy": "confirm-risky",
                                                                                                                                           "countdown": 4}})

    def goal(self, text="run the tests", state="running"):
        from swarmbox_sysop import ipc
        d = self.paths.goal_dir(self.gid)
        os.makedirs(d, mode=0o700, exist_ok=True)
        ipc.write_json(os.path.join(d, "state.json"), {"id": self.gid, "source": "voice", "text": text, "state": state, "created": time.time(), "started": time.time(),
                                                       "ended": None, "say": [], "calls": [], "pending": None, "summary": "", "error": "", "note": "", "steps": 0, "brain": {}})
        self.write_status(self.gid)

    def pending(self, mode="veto", risk="low", seconds=120, text="echo hello"):
        from swarmbox_sysop import ipc
        now = time.time()
        p = {"id": "p1", "goal": self.gid, "tab": "@1", "label": "1:shell", "kind": "run", "text": text, "risk": risk, "reasons": ["a test"], "mode": mode,
             "created": now, "deadline": now + seconds}
        ipc.write_json(os.path.join(self.paths.goal_dir(self.gid), "pending_action.json"), p)
        return p

    def decision(self):
        from swarmbox_sysop import ipc
        return ipc.read_json(os.path.join(self.paths.goal_dir(self.gid), "decision.json"))
