"""Shared by the tests of swarmbox-tabs: the module loaded by path, the command run as a process, and a FAKE herdr-core `hc` (an executable script
on a private path) that answers the commands HerdrBackend uses (ls, get, read, keys, run, kill, rm, connect) from a JSON state file, keeps a log of
every call and of every text and key typed with its time, and can play a Claude Code screen (input box, busy, dialog, an Enter that is swallowed).
No herdr-core, no network, no model: these tests run on any host."""
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TABS_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")


def load_module():
    spec = importlib.util.spec_from_file_location("swarmbox_tabs", TABS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The fake. `typed` of a terminal is what reached it: a text as it is, a key as "<name>" in the spelling of `hc keys` (enter, esc, ctrl+c ...).
# st["events"] is [time, address, "text"|"key", value] for each of them; st["frames"] the byte sizes of the DATA frames of `hc connect`.
# `__data ADDRESS TEXT` is not an hc command: it is what the in-process driver uses instead of `hc connect` (see FakeHc.driver).
FAKE = r'''#!/usr/bin/env python3
import fcntl, json, os, struct, sys, time
ST = os.environ["FAKE_HC_STATE"]
RULE = "─" * 40
INTERNAL = ("screen", "claude", "typed", "history_raw", "alt")
args = sys.argv[1:]
fd = os.open(ST + ".lock", os.O_CREAT | os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX)
with open(ST) as f:
    st = json.load(f)
st["log"].append([time.time(), args])
cmd = args[0] if args else ""


def save():
    with open(ST, "w") as f:
        json.dump(st, f)


def answer(obj, rc=0):
    save()
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    sys.exit(rc)


def error(kind, message):
    answer({"error": {"kind": kind, "message": message}}, 1)


def find(addr):
    for t in st["terminals"]:
        if t["address"] == addr and t.get("state", "live") == "live":
            return t
    error("not_found", 'no terminal "%s"' % addr)


def public(t, full):
    """a terminal as hc shows it: `hc get` (full) has the labels and the foreground program; `hc ls` has neither (measured with herdr-core
    0.1.21: its summaries carry no `foreground` and the status only as a word)"""
    out = {k: v for k, v in t.items() if k not in INTERNAL and (full or k not in ("labels", "foreground"))}
    if not full and isinstance(out.get("status"), dict):
        # `hc ls` gives the state as a word and the app it reported as `agent` (herdr-core 0.1.21)
        st = out["status"]
        out["status"] = st.get("state")
        if st.get("app") and not out.get("agent"):
            out["agent"] = st["app"]
    return out


def render(t):
    c = t.get("claude")
    if not c:
        return t.get("screen", "")
    rows = list(c.get("history", [])) + [""]
    if c["mode"] == "dialog":
        rows += [RULE, " Bash command", " Do you want to proceed?", " ❯ 1. Yes", "   2. No", "", " Esc to cancel · Tab to amend"]
    else:
        box = c["box"].split("\n")
        rows += [RULE] + [("❯ " if i == 0 else "  ") + b for i, b in enumerate(box)] + [RULE]
        rows += ["  auto mode on (shift+tab to cycle)" + (" · esc to interrupt" if c["mode"] == "busy" else "")]
    return "\n".join(rows)


def type_text(t, text):
    st.setdefault("events", []).append([time.time(), t["address"], "text", text])
    c = t.get("claude")
    if c:
        c["box"] += text
    t.setdefault("typed", []).append(text)


def press(t, key):
    st.setdefault("events", []).append([time.time(), t["address"], "key", key])
    t.setdefault("typed", []).append("<%s>" % key)
    c = t.get("claude")
    if c and key == "enter":
        if c.get("swallow", 0) > 0:
            c["swallow"] -= 1
        elif c["box"] and c["mode"] != "dialog":
            c["history"] = c.get("history", []) + ["❯ " + c["box"].replace("\n", " "), ""]
            c["box"] = ""
            c["mode"] = c.get("after_enter", c["mode"])
    elif c and key == "esc" and c["mode"] == "busy":
        c["mode"] = "idle"


def opt(name):
    return args[args.index(name) + 1] if name in args else None


if st.get("down"):
    error("not_running", "herdr-core server is not running")
fail = st.get("fail", {}).get(cmd)
if fail:
    error(fail.get("kind", ""), fail.get("message", ""))
if cmd in st.get("sleep", {}):
    save()
    fcntl.flock(fd, fcntl.LOCK_UN)
    time.sleep(st["sleep"][cmd])
    sys.exit(0)

if cmd == "ls":
    want = {}
    if "--label" in args:
        k, _, v = opt("--label").partition("=")
        want[k] = v
    out = [public(t, False) for t in st["terminals"] if all((t.get("labels") or {}).get(k) == v for k, v in want.items())]
    answer({"hidden_finished": 0, "terminals": out})
elif cmd == "get":
    answer(public(find(args[-1]), True))
elif cmd == "read":
    t = find(args[-1])
    rows = render(t).split("\n")
    n = opt("--lines")
    if t.get("alt"):
        answer({"complete": True, "how": "stitched", "text": "\n".join(rows)})
    hist = t.get("history_raw", []) if n else []
    answer({"complete": True, "how": "history" if n else "screen", "text": "\n".join(hist + rows)})
elif cmd == "keys":
    rest = [a for a in args[1:] if a != "--json"]
    t = find(rest[0])
    for k in rest[1:]:
        press(t, k)
    answer({"status": None, "turn": 0})
elif cmd == "__data":
    type_text(find(args[1]), args[2])
    answer({"ok": True})
elif cmd == "run":
    cut = args.index("--") if "--" in args else len(args)
    argv = args[cut + 1:]
    n = max([int(t["address"][1:]) for t in st["terminals"]] + [0]) + 1
    t = {"address": "t%d" % n, "name": opt("--name") or "term-%d" % n, "cwd": opt("--cwd") or "/work", "argv": argv, "state": "live",
         "cols": 100, "rows": 30, "created_ms": n * 1000, "reported": False, "status": None, "labels": {}, "screen": "$ "}
    st["terminals"].append(t)
    answer(public(t, True))
elif cmd == "kill":
    find(args[-1])["state"] = "finished"
    answer({"ok": True})
elif cmd == "rm":
    st["terminals"] = [t for t in st["terminals"] if t["address"] != args[-1]]
    answer({"ok": True})
elif cmd == "connect":
    save()
    fcntl.flock(fd, fcntl.LOCK_UN)
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    hello = json.loads(inp.readline().decode())
    out.write((json.dumps({"jsonrpc": "2.0", "id": hello["id"], "result": {"framed": True}}) + "\n").encode())
    out.flush()
    addr, data, frames = None, b"", []
    while True:
        hdr = inp.read(9)
        if len(hdr) < 9:
            break
        ch, kind, n = struct.unpack("<IBI", hdr)
        payload = inp.read(n) if n else b""
        if ch == 0 and kind == 0:
            req = json.loads(payload.decode())
            addr = req["params"]["terminal"]
            with open(ST) as f:
                live = any(t["address"] == addr and t.get("state", "live") == "live" for t in json.load(f)["terminals"])
            if live:
                msg = {"jsonrpc": "2.0", "id": req["id"], "result": {"channel": 7}}
            else:
                msg = {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": 'no terminal "%s"' % addr, "data": {"kind": "not_found"}}}
            b = json.dumps(msg).encode()
            out.write(struct.pack("<IBI", 0, 0, len(b)) + b)
            out.flush()
        elif ch == 7 and kind == 0:
            data += payload
            frames.append(len(payload))
        elif ch == 7 and kind == 2:
            break
    fcntl.flock(fd, fcntl.LOCK_EX)
    with open(ST) as f:
        st = json.load(f)
    if data:
        st.setdefault("frames", []).extend(frames)
        type_text(find(addr), data.decode("utf-8"))
    answer({"ok": True})
else:
    error("unsupported", "fake hc: unsupported command " + cmd)
'''


class InProcessHc:
    """The fake hc without a process: the same script (FAKE) run by exec in this process, for a driver whose `subprocess.run` is replaced by `run`.
    An hc call of the driver costs microseconds instead of a Python start. Only calls to the fake are caught: any other binary (a path that does not
    exist) goes to the real subprocess. The calls are serialised. A `sleep` of the fake that is longer than the timeout of the call is a
    TimeoutExpired at once (the call is logged first, as the script does)."""
    lock = threading.Lock()
    code = compile(FAKE.replace("time.sleep(", "_sleep("), "fake-hc", "exec")

    def __init__(self, binary):
        self.binary = binary

    def run(self, argv, timeout=None, env=None, **kw):
        if argv[0] != self.binary:
            return subprocess.run(argv, timeout=timeout, env=env, **kw)
        out, err = io.StringIO(), io.StringIO()
        rc = [0]

        def sleep(seconds):
            if timeout is not None and seconds > timeout:
                raise subprocess.TimeoutExpired(argv, timeout)
            time.sleep(seconds)
        ns = {"__name__": "fake_hc", "_sleep": sleep}
        with self.lock:
            saved = (sys.argv, sys.stdout, sys.stderr)
            sys.argv, sys.stdout, sys.stderr = argv, out, err
            try:
                exec(self.code, ns)
            except SystemExit as e:
                rc[0] = e.code if isinstance(e.code, int) else 0
            finally:
                sys.argv, sys.stdout, sys.stderr = saved
                if "fd" in ns:
                    os.close(ns["fd"])
        return subprocess.CompletedProcess(argv, rc[0], out.getvalue().encode(), err.getvalue().encode())


class FakeHc:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="sbfh-")
        self.state_path = os.path.join(self.dir, "state.json")
        self.bin = os.path.join(self.dir, "hc")
        with open(self.bin, "w") as f:
            f.write(FAKE)
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IXUSR)
        self.state = {"terminals": [], "log": []}

    def term(self, addr, name, **kw):
        """a live terminal; kw: cwd, agent, foreground, argv, labels, status, reported, cols, rows, screen, claude, alt, history_raw"""
        n = int(addr[1:])
        t = dict({"address": addr, "name": name, "cwd": "/work", "argv": ["bash"], "state": "live", "cols": 80, "rows": 24, "created_ms": n * 1000,
                  "reported": False, "status": None, "labels": {}, "screen": ""}, **kw)
        self.state["terminals"].append(t)
        return t

    def active(self, addr):
        """write the active-tab marker, as the web studio and the cockpit do"""
        with open(os.path.join(self.dir, "herdr-active-tab"), "w") as f:
            f.write(addr + "\n")
        return self

    def save(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f)
        return self

    def load(self):
        with open(self.state_path) as f:
            self.state = json.load(f)
        return self.state

    def calls(self, cmd=None):
        return [(t, a) for t, a in self.load()["log"] if cmd is None or a[:1] == [cmd]]

    def sent(self):
        """what was typed, in order: (time, address, "text"|"key", value)"""
        return [tuple(e) for e in self.load().get("events", [])]

    def t(self, addr):
        for t in self.load()["terminals"]:
            if t["address"] == addr:
                return t

    def typed(self, addr):
        return (self.t(addr) or {}).get("typed", [])

    def driver(self, **kw):
        """a Tabs on this fake hc, with a short pause, its run folder (locks, active marker) in this fake's folder, and a TabsError class as .Err"""
        os.environ["FAKE_HC_STATE"] = self.state_path
        mod = load_module()
        d = mod.Tabs(binary=self.bin, **dict({"pause": 0.02, "verify_timeout": 0.6, "run_dir": self.dir}, **kw))
        d.Err = mod.TabsError
        if os.environ.get("SB_TEST_HC_PROCESS") != "1":      # =1: every call a real process, text over the framed `hc connect` (what the command does)
            shim = InProcessHc(d.binary)
            mod.subprocess = type("subprocess", (), {"run": staticmethod(shim.run), "Popen": subprocess.Popen, "TimeoutExpired": subprocess.TimeoutExpired,
                                                     "DEVNULL": subprocess.DEVNULL, "PIPE": subprocess.PIPE})
            d.backend._framed_write = lambda tid, data: d.backend.hc("__data", tid, data.decode("utf-8"))
        return d

    def env(self, **extra):
        """the environment of the command: this fake hc, its folder as the run folder"""
        e = {k: v for k, v in os.environ.items() if not k.startswith("SB_") and k != "SWARMBOX_MUX"}
        e.update(FAKE_HC_STATE=self.state_path, SB_TABS_BIN=self.bin, SB_RUN_DIR=self.dir)
        e.update(extra)
        return e

    def cli(self, *args, stdin=None, timeout=30, **extra):
        """run `swarmbox-tabs ARGS` as a process (python3 -S, as the image does): (returncode, parsed stdout or None, stderr text)"""
        r = subprocess.run([sys.executable, "-S", TABS_PATH, *args], env=self.env(**extra), input=stdin, capture_output=True, timeout=timeout)
        out = r.stdout.decode()
        return r.returncode, (json.loads(out) if out.strip() else None), r.stderr.decode()

    def close(self):
        os.environ.pop("FAKE_HC_STATE", None)
        shutil.rmtree(self.dir, ignore_errors=True)


def claude_term(mode="idle", box="", **kw):
    """the fields of a terminal that runs Claude Code (a screen of it the fake plays)"""
    return {"claude": dict({"mode": mode, "box": box, "history": ["", "● earlier answer"]}, **kw), "argv": ["claude"]}
