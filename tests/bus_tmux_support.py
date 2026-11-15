"""Shared by the tests of the tmux driver of swarmbox-bus: the module loaded by path, and a FAKE tmux (an executable script on a private
path) that answers the few commands the driver uses from a JSON state file, keeps a log of every call with its time, and can play a
Claude Code screen (input box, busy, dialog, an Enter that is swallowed). No tmux, no network, no model: these tests run on any host."""
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

DRIVER_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-bus-tmux.py")


def load_module():
    spec = importlib.util.spec_from_file_location("swarmbox_bus_tmux", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FAKE = r'''#!/usr/bin/env python3
import fcntl, json, os, re, sys, time
ST = os.environ["FAKE_TMUX_STATE"]
RULE = "─" * 40
args = sys.argv[1:]
socket_seen = None
if args[:1] == ["-L"]:
    socket_seen, args = args[1], args[2:]
fd = os.open(ST + ".lock", os.O_CREAT | os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX)
st = json.load(open(ST))
st["log"].append([time.time(), args])
st["socket_seen"] = socket_seen
cmd = args[0] if args else ""


def save():
    json.dump(st, open(ST, "w"))


def die(msg):
    save()
    sys.stderr.write(msg + "\n")
    sys.exit(1)


if st.get("env_check") is not None:
    st["env_seen"] = {"TMUX": os.environ.get("TMUX"), "TMUX_TMPDIR": os.environ.get("TMUX_TMPDIR")}
if cmd in st.get("fail", {}):
    die(st["fail"][cmd])
if cmd in st.get("sleep", {}):
    save()
    fcntl.flock(fd, fcntl.LOCK_UN)
    time.sleep(st["sleep"][cmd])
    sys.exit(0)


def panes():
    for w in st["windows"]:
        for p in w["panes"]:
            yield w, p


def find_pane(t):
    for w, p in panes():
        if p["id"] == t:
            return w, p
    die("can't find pane: " + t)


def render(p):
    c = p.get("claude")
    if not c:
        return p.get("screen", "")
    rows = list(c.get("history", [])) + [""]
    if c["mode"] == "dialog":
        rows += [RULE, " Bash command", " Do you want to proceed?", " ❯ 1. Yes", "   2. No", "", " Esc to cancel · Tab to amend"]
    else:
        box = c["box"].split("\n")
        rows += [RULE] + [("❯ " if i == 0 else "  ") + b for i, b in enumerate(box)] + [RULE]
        rows += ["  auto mode on (shift+tab to cycle)" + (" · esc to interrupt" if c["mode"] == "busy" else "")]
    return "\n".join(rows)


def variables(w, p):
    return {"window_id": w["id"], "window_index": str(w["index"]), "window_name": w["name"], "pane_id": p["id"],
            "pane_active": "1" if p.get("active") else "0", "pane_current_path": p.get("cwd", "/"), "pane_current_command": p.get("cmd", "bash"),
            "pane_last": "1" if p.get("last") else "0", "@swarmbox_sysop_panel": p.get("sysop", ""), "@swarmbox_voice_panel": p.get("voice", ""),
            "cursor_x": str(p.get("cx", 0)), "cursor_y": str(p.get("cy", 0)), "pane_in_mode": "1" if p.get("in_mode") else "0",
            "alternate_on": "1" if p.get("alt") else "0", "pane_width": str(p.get("w", 80)), "pane_height": str(p.get("h", 24)),
            "pane_mode": "copy-mode" if p.get("in_mode") else ""}


def expand(fmt, v):
    # #{?#{name},1,0} (true when the variable is not empty and not 0), then plain #{name}
    fmt = re.sub(r"#\{\?#\{([^}]*)\},1,0\}", lambda m: "1" if v.get(m.group(1), "") not in ("", "0") else "0", fmt)
    return re.sub(r"#\{([^}]*)\}", lambda m: v.get(m.group(1), ""), fmt)


def opt(name):
    return args[args.index(name) + 1] if name in args else None


if cmd == "list-panes":
    if opt("-t") != "=" + st["session"]:
        die("can't find session: " + str(opt("-t")))
    for w, p in panes():
        print(expand(opt("-F"), variables(w, p)))
elif cmd == "list-clients":
    for c in st["clients"]:
        print(expand(opt("-F"), {"client_activity": str(c["activity"]), "window_id": c["window"], "client_control_mode": "1" if c.get("control") else "0"}))
elif cmd == "display-message":
    t = opt("-t")
    if t.startswith("="):
        print(st["current"])
    else:
        w, p = find_pane(t)
        print(expand(args[-1], variables(w, p)))
elif cmd == "capture-pane":
    w, p = find_pane(opt("-t"))
    text = render(p)
    if "-e" not in args:
        text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    n = opt("-S")
    hist = p.get("history_raw", [])
    rows = (hist[int(n):] if n and int(n) < 0 and hist else []) + text.split("\n")
    print("\n".join(rows))
elif cmd == "send-keys":
    t = opt("-t")
    w, p = find_pane(t)
    c = p.get("claude")
    if "-X" in args:
        p["in_mode"] = False
        p.setdefault("typed", []).append("<cancel>")
    elif "-l" in args or "-H" in args:
        text = args[-1] if "-l" in args else "".join(chr(int(h, 16)) for h in args[args.index("-H") + 1:])
        if c:
            c["box"] += text
            c["box_seen"] = c.get("box_seen", []) + [text]
        p.setdefault("typed", []).append(text)
    else:
        key = args[-1]
        p.setdefault("typed", []).append("<%s>" % key)
        if c and key == "Enter":
            if c.get("swallow", 0) > 0:
                c["swallow"] -= 1
            elif c["box"] and c["mode"] != "dialog":
                c["history"] = c.get("history", []) + ["❯ " + c["box"].replace("\n", " "), ""]
                c["box"] = ""
                c["mode"] = c.get("after_enter", c["mode"])
        elif c and key == "Escape" and c["mode"] == "busy":
            c["mode"] = "idle"
else:
    die("fake tmux: unsupported command " + cmd)
save()
'''


class FakeTmux:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="sbft-")
        self.state_path = os.path.join(self.dir, "state.json")
        self.bin = os.path.join(self.dir, "tmux")
        with open(self.bin, "w") as f:
            f.write(FAKE)
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IXUSR)
        self.state = {"session": "main", "current": "@1", "clients": [], "windows": [], "log": []}
        self._env = {}

    def window(self, wid, index, name, **pane):
        p = dict({"id": "%" + wid[1:], "active": True, "cwd": "/work", "cmd": "bash", "screen": ""}, **pane)
        w = {"id": wid, "index": index, "name": name, "panes": [p]}
        self.state["windows"].append(w)
        return p

    def client(self, window, activity, control=False):
        self.state["clients"].append({"activity": activity, "window": window, "control": control})

    def save(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f)
        return self

    def load(self):
        with open(self.state_path) as f:
            self.state = json.load(f)
        return self.state

    def calls(self, cmd=None):
        return [(t, a) for t, a in self.load()["log"] if cmd is None or a[0] == cmd]

    def sent(self):
        """the send-keys calls: (time, args after -t %pane)"""
        return [(t, a[3:]) for t, a in self.calls("send-keys")]

    def pane(self, pid):
        for w in self.load()["windows"]:
            for p in w["panes"]:
                if p["id"] == pid:
                    return p

    def driver(self, **kw):
        os.environ["FAKE_TMUX_STATE"] = self.state_path
        mod = load_module()

        class Err(Exception):
            def __init__(self, code, message=""):
                Exception.__init__(self, code)
                self.code, self.message = code, message
        d = mod.TmuxDriver(Err, binary=self.bin, **dict({"pause": 0.02, "verify_timeout": 0.6}, **kw))
        d.Err = Err
        return d

    def close(self):
        os.environ.pop("FAKE_TMUX_STATE", None)
        shutil.rmtree(self.dir, ignore_errors=True)


def claude_pane(mode="idle", box="", **kw):
    return {"claude": dict({"mode": mode, "box": box, "history": ["", "● earlier answer"]}, **kw), "cmd": "claude"}
