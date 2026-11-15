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
from helpers import ROOT  # noqa: E402

SYSOP = os.path.join(ROOT, "container", "tools", "sysop")
LIB = os.path.join(SYSOP, "lib")
sys.path.insert(0, LIB)
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "sysop")
FAKE_BIN = os.path.join(FIXTURES, "bin")

from swarmbox_sysop import config, paths  # noqa: E402


def wait_for(fn, seconds=10.0, step=0.02):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def short_tmp(prefix="sbsy-"):
    """a short folder: a unix socket path holds at most 107 bytes"""
    return os.path.realpath(tempfile.mkdtemp(prefix=prefix, dir="/tmp"))


class Env:
    """private run and state folders and a socket path in one short temporary folder, as an environment mapping"""

    def __init__(self, **extra):
        self.dir = short_tmp()
        self.env = {"SB_RUN_DIR": os.path.join(self.dir, "run"), "SB_STATE_DIR": os.path.join(self.dir, "state"),
                    "SB_BUS_SOCKET": os.path.join(self.dir, "bus.sock"), "HOME": os.path.join(self.dir, "home"),
                    "PATH": FAKE_BIN + ":" + os.environ.get("PATH", "/usr/bin:/bin")}
        os.makedirs(self.env["HOME"])
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
    """The socket protocol of swarmbox-bus with scriptable tabs.

    tabs        {id: {"tab", "label", "index", "name", "dir", "cmd", "active", "pane", "panes"}}
    screens     {id: text or callable(bus, id) -> text}
    sent        [(tab, body)] of every accepted tab message
    errors      {tab: (code, msg)}: a send to that tab fails; `ls_error` and `get_error` do the same for the reads
    on_send     callback(bus, tab, body) after an accepted send (change a screen, ...)
    send_delay  seconds a tab message takes (the driver's pauses)
    """

    def __init__(self, path, tabs=None):
        self.path = path
        self.tabs = tabs if tabs is not None else {
            "@1": dict(tab="@1", label="0:shell", index=0, name="shell", dir="/work", cmd="bash", active=True, pane="%1", panes=1),
            "@2": dict(tab="@2", label="1:agent", index=1, name="agent", dir="/work", cmd="claude", active=False, pane="%2", panes=1)}
        self.screens = {"@1": "$ ", "@2": "> "}
        self.sent, self.reads, self.errors, self.ls_error, self.get_error = [], [], {}, None, None
        self.on_send, self.send_delay = None, 0.0
        self.lock = threading.Lock()
        self.subs = []
        self.conns = []
        self.srv = None
        self.thread = None
        self.up = False
        self.counter = 0
        self.goal_replies = None
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
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def stop(self):
        """the broker goes away: the listener and every connection close, the socket file is removed"""
        self.up = False
        try:
            self.srv.close()
        except OSError:
            pass
        with self.lock:
            conns, self.conns, self.subs = self.conns, [], []
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

    def _accept(self):
        while self.up:
            try:
                c, _ = self.srv.accept()
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
                self._send(c, {"ok": True, "subscribed": "goal"})
                with self.lock:
                    self.subs.append(c)
                while f.readline():
                    pass
                return
            self._send(c, self.reply(req))
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                if c in self.subs:
                    self.subs.remove(c)
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
        if op == "ls":
            if self.ls_error:
                return {"ok": False, "err": self.ls_error[0], "msg": self.ls_error[1]}
            return {"ok": True, "result": [dict(t) for t in self.tabs.values()]}
        if op == "get":
            tab = topic.split("/")[1] if topic.count("/") == 2 else None
            self.reads.append(tab)
            if self.get_error:
                return {"ok": False, "err": self.get_error[0], "msg": self.get_error[1]}
            if tab not in self.tabs:
                return {"ok": False, "err": "no_such_tab", "msg": "no tab %s" % tab}
            s = self.screens.get(tab, "")
            text = s(self, tab) if callable(s) else s
            return {"ok": True, "result": {"tab": tab, "pane": "%1", "text": text, "cursor": [0, 0], "alternate": False, "in_mode": False, "mode": "", "size": [80, 24], "lines": None}}
        if op == "pub":
            self.counter += 1
            env = {"v": 1, "id": "fb-%d" % self.counter, "topic": topic, "source": str(req.get("source") or "cli"), "peer": {"pid": 1, "uid": os.getuid()},
                   "time": "now", "body": req.get("body")}
            if topic == "goal":
                return self.deliver(env)
            tab = topic.split("/")[1] if topic.count("/") == 2 else None
            if tab in self.errors:
                return {"ok": False, "err": self.errors[tab][0], "msg": self.errors[tab][1]}
            if tab not in self.tabs:
                return {"ok": False, "err": "no_such_tab", "msg": "no tab %s" % tab}
            time.sleep(self.send_delay)
            self.sent.append((tab, req.get("body")))
            if self.on_send:
                self.on_send(self, tab, req.get("body"))
            return {"ok": True, "id": env["id"], "delivered": 1}
        return {"ok": False, "err": "bad_request"}

    def deliver(self, env):
        with self.lock:
            subs = list(self.subs)
        if not subs:
            return {"ok": False, "err": "no_subscriber"}
        try:
            self._send(subs[0], env)
        except OSError:
            return {"ok": False, "err": "no_subscriber"}
        return {"ok": True, "id": env["id"], "delivered": 1}

    def publish_goal(self, text, source="cli", body=None):
        """a goal as the broker delivers it (to the first subscriber); returns the reply"""
        self.counter += 1
        env = {"v": 1, "id": "fb-%d" % self.counter, "topic": "goal", "source": source, "peer": {"pid": 1, "uid": os.getuid()}, "time": "now",
               "body": body if body is not None else {"text": text}}
        return self.deliver(env)

    def wait_subscriber(self, n=1, seconds=10):
        return wait_for(lambda: len(self.subs) >= n, seconds)

    def set_screen(self, tab, text):
        self.screens[tab] = text
