"""Shared by tests/test_bus.py, tests/test_bus_cli.py and the tests of the plugins: load swarmbox-bus.py as a module, run a broker in a thread
or as a process, and a raw protocol client. Nothing here needs tmux, a network or a model."""
import importlib.util
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

BUS_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-bus.py")


def load_bus():
    spec = importlib.util.spec_from_file_location("swarmbox_bus", BUS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bus = load_bus()


def wait_for(fn, seconds=5.0, step=0.01):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def short_tmp(prefix="sbbus-"):
    """a short folder: a unix socket path holds at most 107 bytes"""
    return tempfile.mkdtemp(prefix=prefix, dir="/tmp")


class Conn:
    """a raw client: send a request line, read lines"""

    def __init__(self, path, timeout=10):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.settimeout(timeout)
        self.s.connect(path)
        self.f = self.s.makefile("rb")

    def send(self, req):
        try:
            self.s.sendall(req if isinstance(req, bytes) else (json.dumps(req) + "\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass        # the broker answered (a refusal) and closed before the request was sent: the reply is still there to read
        return self

    def line(self):
        raw = self.f.readline()
        return json.loads(raw) if raw else None

    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)       # a thread blocked in readline() returns, so f.close() does not wait for its timeout
        except OSError:
            pass
        try:
            self.f.close()
            self.s.close()
        except OSError:
            pass


def rpc(path, req, timeout=10):
    c = Conn(path, timeout)
    try:
        return c.send(req).line()
    finally:
        c.close()


class Harness:
    """an in-process broker (own thread and loop) on a fresh socket path"""

    def __init__(self, allowed_uids=None):
        self.dir = short_tmp()
        self.path = os.path.join(self.dir, "bus.sock")
        self.logs = []
        self.broker = bus.Broker(self.path, allowed_uids=allowed_uids, log=self.logs.append)
        self.broker.started = threading.Event()
        self.rc = self.broker.acquire()
        self.thread = None
        self.conns = []
        if self.rc == 0:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            assert self.broker.started.wait(10), "the broker did not start"

    def _run(self):
        import asyncio
        asyncio.run(self.broker.run())

    def conn(self):
        c = Conn(self.path)
        self.conns.append(c)
        return c

    def sub(self, topic="goal", group=None):
        c = self.conn().send({"op": "sub", "topic": topic, "group": group})
        rep = c.line()
        assert rep and rep.get("ok"), rep
        return c

    def rpc(self, req):
        return rpc(self.path, req)

    def pub(self, topic, body, **kw):
        return self.rpc(dict({"op": "pub", "topic": topic, "body": body}, **kw))

    def close(self):
        for c in self.conns:
            c.close()
        if self.thread:
            self.broker.stop()
            self.thread.join(10)
        shutil.rmtree(self.dir, ignore_errors=True)


class Process:
    """a broker as a real process (python3 -S swarmbox-bus.py serve) on a fresh socket path"""

    def __init__(self, env_extra=None):
        self.dir = short_tmp()
        self.path = os.path.join(self.dir, "bus.sock")
        self.env = dict(os.environ, SB_BUS_SOCKET=self.path)
        self.env.pop("SB_BUS_SOURCE", None)
        self.env.pop("SB_BUS_VERBOSE", None)
        self.env.update(env_extra or {})
        self.proc = None

    def start(self, wait=True):
        with open(os.path.join(self.dir, "serve.log"), "ab") as logf:
            self.proc = subprocess.Popen([sys.executable, "-S", BUS_PATH, "serve"], env=self.env, stdout=subprocess.DEVNULL, stderr=logf)
        if wait:
            assert wait_for(lambda: self.alive(), 10), "the broker did not answer: " + self.log()
        return self

    def alive(self):
        try:
            return rpc(self.path, {"op": "ping"}, 2).get("ok")
        except (OSError, AttributeError, ValueError):
            return False

    def log(self):
        try:
            with open(os.path.join(self.dir, "serve.log")) as f:
                return f.read()
        except OSError:
            return ""

    def cli(self, *args, stdin=None, timeout=30, env=None):
        e = dict(self.env, **(env or {}))
        return subprocess.run([sys.executable, "-S", BUS_PATH, *args], env=e, input=stdin, capture_output=True, timeout=timeout)

    def popen(self, *args, **kw):
        # SIGINT back to its default in the child: a test runner started as a background job of a non-interactive shell has SIGINT ignored,
        # and Python then never raises KeyboardInterrupt (the child would inherit the ignore, and a Ctrl-C test would hang)
        return subprocess.Popen([sys.executable, "-S", BUS_PATH, *args], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL), **kw)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    def close(self):
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
