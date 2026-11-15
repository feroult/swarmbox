#!/usr/bin/env python3
"""Soak and fault test of version 1: the whole stack under time and abuse, inside a container. NOT part of the fast gate (dev/check.sh does not run it).

Run it with tests/soak_v1.sh (it starts the container and, for the few real goals, passes the login). Inside the container:

    python3 tests/soak_v1.py [--minutes 40] [--faults NAMES] [--list] [--real N] [--no-idle]

The stack is the box's own, not a copy of it: `container/entrypoint.sh serve` (the real supervisors of the bus and of the web terminal, the readiness
marker, the steps) with the real swarmbox-bus, swarmbox-tabs, swarmbox-sysop (installed by swarmbox-tool, started by its prepare.sh) and swarmbox-voice
(the front on the web port, the voice service, the real ttyd attached to the real tmux through swarmbox-attach); tmux uses the box's tmux.conf.
Stand-ins, and only these: the brain of most goals is the fake claude of tests/fixtures/sysop behind tests/fixtures/soak/brain.py (a goal can ask for the real
`claude -p`, a few are made); whisper-cli is tests/fixtures/voice/whisper-fake (the transcript is in the WAV); the nested Podman is off
(SWARMBOX_TEST_NO_NESTED); the state folder is a small tmpfs of its own (/state, XDG_STATE_HOME) so that a full disk can be made.

Timeline (--minutes N, default 40; the parts are scaled): A steady load with no fault (the baseline of memory, descriptors and idle CPU), B the faults one
after another with the same load running, C the load again and an idle stretch (the final numbers). Steady load: a goal every few seconds on the bus, a
spoken goal through the front, a browser-like websocket client that attaches to the terminal, types, resizes and leaves.
Sampled every 10 s into $SOAK_RESULTS/samples.csv: RSS, descriptors, threads and CPU of every long-lived process, zombies, the number of processes, the
sizes of the logs and of the state folder, the folders and files of the run folder, the goals by state, the panels per window.
Faults (each prints one row: fault -> what happened -> recovery time -> ok; `--list` names them, `--faults a,b` picks): kill -9 of the bus, of the sysop service (idle,
mid-goal, five in a row), of the brain mid-goal, of the voice service, of ttyd with a browser attached, of the voice front; a tmux window killed while swarmbox-tabs types
into it and while a goal works in it; 50 windows opened and closed with the hooks racing; a burst of resizes; 500 goals (huge ones, ones that are not text) in a second;
subscribers that stop reading (SIGSTOP), the sysop service stopped, the voice service stopped; the audit file driven past its limit; the state folder full; the bus
crashing until its supervisor gives up; kill -9 of the tmux server (every tab gone) and a browser that comes back; SIGTERM of the entrypoint. The clock cannot be set in a container without root: a clock that jumps is tested with an injected clock
(tests/test_sysop_soak.py).
After the last fault come the final checks: memory growth, descriptors and idle CPU of every long-lived process, zombies, processes left behind, panels per window, tracebacks
in any log, goals stuck in running, the size of the audit files and of the logs, lock files, sockets. `--minutes` scales the phases (the faults take what they take);
`--quick` is for debugging the harness. Results (samples.jsonl and .csv, report.json, the log of the run) go to $SOAK_RESULTS.

The login (CLAUDE_CODE_OAUTH_TOKEN) is only used for the real goals, passed to the service as the box would have it, and scrubbed from everything printed.
"""
import argparse
import base64
import csv
import http.client
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("SOAK_REPO") or os.path.dirname(HERE)
WORK = os.environ.get("SOAK_WORK", "/work")
STATE_MOUNT = os.environ.get("SOAK_STATE", "/state")
RESULTS = os.environ.get("SOAK_RESULTS") or os.path.join(WORK, "results")
TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
PORT, TTYD_PORT, VOICE_PORT = 7681, 7680, 17682
RUN = "/tmp/swarmbox"
T0 = time.time()
FAILED = []
ROWS = []
MAX_SECONDS = 40          # sysop.max_seconds of the soak: a hung brain is killed after this (the real claude needs 20 to 30 s)
SYNC_TICK = 4.0           # the Follower's slow tick (dock.SYNC_TICK)


def scrub(s):
    return s.replace(TOKEN, "<token>") if TOKEN and TOKEN in s else s


def log(msg):
    print("%7.1f %s" % (time.time() - T0, scrub(msg)), flush=True)


def check(name, ok, detail=""):
    log("%s %s%s" % ("PASS" if ok else "FAIL", name, (": " + str(detail)) if detail != "" else ""))
    if not ok:
        FAILED.append(name)
    return ok


def wait_for(fn, seconds=10.0, step=0.1):
    """(elapsed, value) when fn() is true, or None"""
    t = time.time()
    while time.time() - t < seconds:
        v = fn()
        if v:
            return time.time() - t, v
        time.sleep(step)
    return None


def read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def dir_bytes(path):
    n = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                n += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return n


# ---------------------------------------------------------------------------------------------------------------------- processes
def pids():
    return [int(x) for x in os.listdir("/proc") if x.isdigit()]


class Proc:
    __slots__ = ("pid", "ppid", "comm", "state", "cmd", "utime", "stime", "threads", "rss", "fds", "start")


def proc_info(pid):
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            raw = f.read().decode("utf-8", "replace")
        head, _, tail = raw.rpartition(")")
        f = tail.split()
        p = Proc()
        p.pid, p.comm = pid, head.split("(", 1)[1]
        p.state, p.ppid = f[0], int(f[1])
        p.utime, p.stime, p.threads, p.start = int(f[11]), int(f[12]), int(f[17]), int(f[19])
        with open("/proc/%d/cmdline" % pid, "rb") as c:
            p.cmd = [x.decode("utf-8", "replace") for x in c.read().split(b"\0") if x]
        p.rss = 0
        if p.state != "Z":
            with open("/proc/%d/statm" % pid) as m:
                p.rss = int(m.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)      # KiB
        try:
            p.fds = len(os.listdir("/proc/%d/fd" % pid))
        except OSError:
            p.fds = -1
        return p
    except (OSError, IndexError, ValueError):
        return None


def role_of(p, entry_pid):
    c = " ".join(p.cmd)
    if p.pid == entry_pid:
        return "entrypoint"
    if p.comm.startswith("tmux: server"):
        return "tmux-server"
    if p.comm.startswith("tmux: client"):
        return "tmux-client"
    if "swarmbox-bus.py" in c and " serve" in c:
        return "bus"
    if "swarmbox_sysop" in c:
        if " serve" in c:
            return "sysop-watch" if " --watch" in c else "sysop"
        if " panel" in c:
            return "panel"
        if " mcp" in c:
            return "mcp"
        return "sysop-cli"
    if "swarmbox_voice" in c:
        if " front" in c:
            return "voice-front"
        if " serve" in c:
            return "voice-service"
        return "voice-cli"
    if p.cmd and os.path.basename(p.cmd[0]) == "ttyd":
        return "ttyd"
    if "fixtures/soak/brain.py" in c or "fixtures/sysop/bin/claude" in c or (p.cmd and os.path.basename(p.cmd[0]) == "claude"):
        return "brain"
    if "swarmbox-attach" in c:
        return "attach"
    if p.comm in ("bash", "sh") and p.ppid == entry_pid:
        return "supervisor"
    return "other:" + p.comm


def scan(entry_pid):
    out = []
    me = os.getpid()
    for pid in pids():
        if pid == me:
            continue
        p = proc_info(pid)
        if p:
            out.append((role_of(p, entry_pid), p))
    return out


LONG_LIVED = ("entrypoint", "supervisor", "tmux-server", "bus", "sysop-watch", "sysop", "voice-front", "voice-service", "ttyd")


# ---------------------------------------------------------------------------------------------------------------------- a minimal websocket client for ttyd
class Ws:
    """What a browser does with the terminal: a websocket to ttyd (through the front), the first JSON message, some input, resizes, a close."""

    def __init__(self, cols=120, rows=40, port=PORT, timeout=10):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: http://127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: tty\r\n\r\n" % (port, port, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            d = self.s.recv(4096)
            if not d:
                raise OSError("closed during the handshake")
            head += d
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("handshake refused: " + head.split(b"\r\n", 1)[0].decode("latin-1"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.send(json.dumps({"AuthToken": "", "columns": cols, "rows": rows}).encode())

    def send(self, data, op=1):
        n = len(data)
        hdr = bytes([0x80 | op])
        mask = os.urandom(4)
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def input(self, text):
        self.send(b"0" + text.encode())

    def resize(self, cols, rows):
        self.send(b"1" + json.dumps({"columns": cols, "rows": rows}).encode())

    def recv_some(self, seconds=1.0):
        """the bytes the server sent in `seconds` (frames are not decoded: only the amount and a coarse look at the text matter)"""
        out, end = b"", time.time() + seconds
        self.s.settimeout(0.2)
        while time.time() < end:
            try:
                d = self.s.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                break
            out += d
        return out + self.buf

    def close(self):
        try:
            self.send(struct.pack(">H", 1000), op=8)
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


def wav_with(text):
    data = text.encode("utf-8")
    if len(data) % 2:
        data += b" "
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(data)) + data


def http_req(method, path, body=None, headers=None, port=PORT, timeout=15):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read()
    except (OSError, http.client.HTTPException) as e:
        return 0, str(e).encode()
    finally:
        c.close()


def voice_say(text, port=PORT):
    """what the microphone button does: a WAV to the front. (HTTP status, state or error)"""
    st, body = http_req("POST", "/voice/audio", wav_with(text), {"Content-Type": "audio/wav", "Origin": "http://127.0.0.1:%d" % port}, port)
    try:
        j = json.loads(body)
        return st, j.get("state") or j.get("error") or ("ok" if j.get("ok") else "?")
    except ValueError:
        return st, body[:60].decode("latin-1")


# ---------------------------------------------------------------------------------------------------------------------- the stack
class Stack:
    def __init__(self, real_goals=0):
        self.work, self.home = WORK, os.path.join(WORK, "home")
        self.bin = os.path.join(WORK, "bin")
        self.tmux_tmp = os.path.join(WORK, "tmux")
        self.state = os.path.join(STATE_MOUNT, "swarmbox")          # SB_STATE_DIR: XDG_STATE_HOME=/state
        self.sysop_state = os.path.join(self.state, "sysop")
        self.sysop_run = os.path.join(RUN, "sysop")
        self.proj = os.path.join(WORK, "proj")
        self.entry = None
        self.entry_log = None
        self.real_goals = real_goals
        self.env = {
            "PATH": self.bin + ":/usr/local/bin:/usr/bin:/bin", "HOME": self.home, "TERM": "xterm-256color", "LANG": "C.UTF-8",
            "XDG_STATE_HOME": STATE_MOUNT, "TMUX_TMPDIR": self.tmux_tmp, "SWARMBOX_TEST_LIB": os.path.join(REPO, "container", "scripts"),
            "SWARMBOX_TEST_IMAGE_TOOLS": os.path.join(WORK, "imagetools"), "SWARMBOX_TEST_USER_TOOLS": os.path.join(WORK, "usertools"),
            "SWARMBOX_TEST_HOST_DIR": os.path.join(WORK, "host"), "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(WORK, "out", "shims"),
            "SWARMBOX_TEST_USER_SHIMS": os.path.join(WORK, "out", "ushims"), "SWARMBOX_TEST_LOCK": os.path.join(WORK, "tool.lock"),
            "SWARMBOX_TEST_NO_NESTED": "1", "SWARMBOX_TEST_TUN": "/dev/null", "SWARMBOX_TEST_WEB_PAGE": os.path.join(WORK, "built", "index.html"),
            "SWARMBOX_WEB": "1", "SWARMBOX_WITH": "",
            "SWARMBOX_SYSOP_BRAIN": "python3 %s {mcp_config} {model} {max_turns} {system_prompt_file}" % os.path.join(REPO, "tests", "fixtures", "soak", "brain.py"),
            "SWARMBOX_SYSOP_AUTONOMY": "auto", "SWARMBOX_SYSOP_COUNTDOWN": "0", "SWARMBOX_SYSOP_MAX_SECONDS": str(MAX_SECONDS),
            "SWARMBOX_SYSOP_MAX_GOALS": "5", "SOAK_WHISPER": os.path.join(REPO, "tests", "fixtures", "voice", "whisper-fake"),
        }
        if TOKEN:
            self.env["CLAUDE_CODE_OAUTH_TOKEN"] = TOKEN

    # ---- files
    @property
    def audit_path(self):
        return os.path.join(self.sysop_state, "events.jsonl")

    def audit(self, goal=None, path=None):
        out = []
        for line in read(path or self.audit_path).splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if goal is None or e.get("goal") == goal:
                out.append(e)
        return out

    def goal_state(self, gid):
        try:
            with open(os.path.join(self.sysop_state, "goals", gid, "state.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def goal_states(self):
        out = {}
        d = os.path.join(self.sysop_state, "goals")
        try:
            names = os.listdir(d)
        except OSError:
            return out
        for n in names:
            try:
                with open(os.path.join(d, n, "state.json"), encoding="utf-8") as f:
                    st = json.load(f)
            except (OSError, ValueError):
                continue
            out[n] = st
        return out

    # ---- commands
    def sh(self, argv, timeout=60, env=None, inp=None):
        e = dict(self.env)
        e.update(env or {})
        try:
            return subprocess.run(argv, env=e, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL if inp is None else None, input=inp)
        except subprocess.TimeoutExpired as ex:
            return subprocess.CompletedProcess(argv, 124, "", "timeout after %ss: %s" % (timeout, ex))

    def tmux(self, *a):
        p = self.sh(["tmux"] + [str(x) for x in a], timeout=20)
        return (p.stdout + p.stderr).rstrip("\n")

    def windows(self):
        rows = self.tmux("list-windows", "-t", "main", "-F", "#{window_id}|#{window_name}|#{window_active}").splitlines()
        return [dict(zip(("id", "name", "active"), r.split("|"))) for r in rows if r.count("|") == 2]

    def panes(self):
        rows = self.tmux("list-panes", "-s", "-t", "main", "-F", "#{pane_id}|#{window_id}|#{@swarmbox_sysop_panel}|#{pane_current_command}|#{pane_dead}").splitlines()
        return [dict(zip(("pane", "win", "panel", "cmd", "dead"), r.split("|"))) for r in rows if r.count("|") == 4]

    def panel_report(self):
        """(windows, windows with exactly one panel, panels in all, windows with more than one pane of the user)"""
        wins = [w["id"] for w in self.windows()]
        panes = self.panes()
        panels = {}
        user = {}
        for p in panes:
            if p["panel"] == "1":
                panels[p["win"]] = panels.get(p["win"], 0) + 1
            else:
                user[p["win"]] = user.get(p["win"], 0) + 1
        return len(wins), sum(1 for w in wins if panels.get(w) == 1), sum(panels.values()), sum(1 for w in wins if user.get(w, 0) > 1)

    def cap(self, win):
        pane = None
        for p in self.panes():
            if p["win"] == win and p["panel"] != "1":
                pane = p["pane"]
                break
        return self.tmux("capture-pane", "-p", "-J", "-t", pane) if pane else ""

    def sysop_bin(self):
        base = os.path.join(self.home, ".local", "share", "swarmbox", "tools", "sysop")
        v = sorted(os.listdir(base)) if os.path.isdir(base) else []
        v = [x for x in v if x != "current"]
        return os.path.join(base, v[0], "bin", "swarmbox-sysop") if v else None

    def sysop(self, *a, timeout=30):
        return self.sh(["swarmbox-sysop"] + list(a), timeout=timeout)

    def bus_ok(self):
        return self.sh(["swarmbox-bus", "ping"], timeout=10).returncode == 0

    def sysop_status(self):
        try:
            with open(os.path.join(self.sysop_run, "status.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def sysop_up(self):
        st = self.sysop_status()
        return self.sysop("status", "-q").returncode == 0 and bool(st) and st.get("bus") == "connected"

    def front_ok(self):
        st, body = http_req("GET", "/voice/health", timeout=3)
        return st == 200

    def term_ok(self):
        st, body = http_req("GET", "/", timeout=3)
        return st == 200 and b"<html" in body[:2000].lower()

    # ---- processes
    def by_role(self, role):
        return [p for r, p in scan(self.entry.pid if self.entry else -1) if r == role]

    def one(self, role):
        ps = self.by_role(role)
        return ps[0] if ps else None

    # ---- setup
    def setup(self):
        if not (os.path.exists("/run/.containerenv") or os.path.exists("/.dockerenv")):
            raise SystemExit("soak_v1: this harness starts a tmux server, a bus and a web terminal of its own: run it in a container (tests/soak_v1.sh)")
        for d in (self.home, self.bin, self.tmux_tmp, self.proj, os.path.join(self.home, ".claude"), RESULTS, os.path.join(WORK, "built")):
            os.makedirs(d, exist_ok=True)
        os.chmod(self.tmux_tmp, 0o700)
        proj = {d: {"hasTrustDialogAccepted": True, "allowedTools": []} for d in (self.proj, self.home)}
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"hasCompletedOnboarding": True, "theme": "dark", "projects": proj}, f)
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"skipDangerousModePermissionPrompt": True}, f)
        # the image's tools: copies of the two tools (the voice one with its installer replaced: no download, no build)
        tools = self.env["SWARMBOX_TEST_IMAGE_TOOLS"]
        shutil.rmtree(tools, ignore_errors=True)
        os.makedirs(tools)
        for t in ("sysop", "voice"):
            shutil.copytree(os.path.join(REPO, "container", "tools", t), os.path.join(tools, t), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(REPO, "tests", "fixtures", "soak", "voice-install.sh"), os.path.join(tools, "voice", "install.sh"))
        scripts = os.path.join(REPO, "container", "scripts")
        launchers = (("swarmbox-bus", 'exec /usr/bin/python3 -S "%s/swarmbox-bus.py" "$@"' % scripts),
                     ("swarmbox-tabs", 'exec /usr/bin/python3 -S "%s/swarmbox-tabs.py" "$@"' % scripts),
                     ("swarmbox-tool", 'exec bash "%s/swarmbox-tool.sh" "$@"' % scripts),
                     ("swarmbox-web", 'exec bash "%s/swarmbox-web.sh" "$@"' % scripts),
                     ("swarmbox-attach", 'exec bash "%s/swarmbox-attach.sh" "$@"' % scripts),
                     ("swarmbox-pubkey", "exit 0"), ("swarmbox-mcp", "exit 0"),
                     ("tmux", 'exec /usr/bin/tmux -f "%s" "$@"' % os.path.join(REPO, "container", "config", "tmux.conf")))
        for name, body in launchers:
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(p, 0o755)
        for d in (STATE_MOUNT,):
            os.makedirs(d, exist_ok=True)
        self.build_page()
        log("versions: tmux %s; python %s" % (self.sh(["tmux", "-V"]).stdout.strip(), sys.version.split()[0]))
        # install the tools as the box does (swarmbox-tool install: install.sh then prepare.sh at the next start); serve runs prepare
        r = self.sh(["swarmbox-tool", "install", "sysop"], timeout=90, env={"SWARMBOX_SYSOP_PANEL_MODE": "off"})
        check("setup: swarmbox-tool install sysop", r.returncode == 0, r.stderr.strip().replace("\n", " | ")[-200:])
        self.stop_sysop_started_by_install()
        r = self.sh(["swarmbox-tool", "install", "voice"], timeout=90)
        check("setup: swarmbox-tool install voice (stand-in installer)", r.returncode == 0, r.stderr.strip().replace("\n", " | ")[-200:])
        # the shims `swarmbox-sysop` and `swarmbox-voice` of the box's PATH (swarmbox-tool link): launchers of the installed copies
        for name, tool in (("swarmbox-sysop", "sysop"), ("swarmbox-voice", "voice")):
            real = self.sh(["swarmbox-tool", "where", tool, name]).stdout.strip()
            with open(os.path.join(self.bin, name), "w") as f:
                f.write('#!/bin/sh\nexec "%s" "$@"\n' % real)
            os.chmod(os.path.join(self.bin, name), 0o755)

    def stop_sysop_started_by_install(self):
        """the install ran prepare.sh once with a panel mode of its own: stop that service so that serve starts the one the soak watches"""
        pid = None
        try:
            pid = int(read(os.path.join(self.sysop_run, "serve.pid")).strip() or 0)
        except ValueError:
            pass
        if pid:
            for s in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, s)
                except OSError:
                    break
                if wait_for(lambda: not self.alive(pid), 5):
                    break

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            with open("/proc/%d/stat" % pid) as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False

    def build_page(self):
        """ttyd's own page plus the clipboard bridge and the style (build-index.sh), as the image builds it"""
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        stock = os.path.join(WORK, "stock.html")
        t = subprocess.Popen(["ttyd", "-p", str(port), "-i", "lo", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1) as r, open(stock, "wb") as f:
                        f.write(r.read())
                    break
                except OSError:
                    time.sleep(0.2)
        finally:
            os.killpg(t.pid, signal.SIGKILL)
            t.wait(timeout=5)
        web = os.path.join(REPO, "container", "web")
        r = subprocess.run(["sh", os.path.join(web, "build-index.sh"), stock, os.path.join(web, "ttyd-clipboard.js"), os.path.join(web, "ttyd-style.css"),
                            self.env["SWARMBOX_TEST_WEB_PAGE"]], capture_output=True, text=True)
        check("setup: build-index.sh built the page", r.returncode == 0, r.stderr.strip())

    # ---- the entrypoint
    def start_entry(self):
        env = dict(self.env)
        self.entry_log = open(os.path.join(RESULTS, "entrypoint.out"), "ab")
        self.entry = subprocess.Popen(["bash", os.path.join(REPO, "container", "entrypoint.sh"), "serve"], env=env, stdout=self.entry_log, stderr=self.entry_log,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
        ok = wait_for(lambda: os.path.exists(os.path.join(RUN, "ready")) and self.front_ok(), 60, 0.25)
        check("setup: serve is ready and the front answers", ok is not None, "" if ok else read(os.path.join(self.state, "serve.log"))[-400:])
        return ok is not None

    def stop_entry(self, sig=signal.SIGTERM, wait=20):
        """send `sig` to the entrypoint (PID 1 of a box) and wait for it to end: (seconds, exit status or None)"""
        if not self.entry or self.entry.poll() is not None:
            return 0.0, self.entry.returncode if self.entry else None
        t = time.time()
        self.entry.send_signal(sig)
        try:
            self.entry.wait(wait)
        except subprocess.TimeoutExpired:
            return time.time() - t, None
        return time.time() - t, self.entry.returncode

    def make_windows(self, names):
        for n in names:
            self.tmux("new-window", "-d", "-t", "main:", "-n", n, "-c", self.proj, "env PS1='$ ' bash --norc --noprofile")
        return self.windows()

    def work_window(self):
        """the id of the window named w1 (a shell the goals type in)"""
        for w in self.windows():
            if w["name"] == "w1":
                return w["id"]
        return None


# ---------------------------------------------------------------------------------------------------------------------- sampling
SAMPLE_FILES = {"audit": "sysop/events.jsonl", "audit1": "sysop/events.jsonl.1", "sysop_log": "sysop/serve.log", "sysop_log1": "sysop/serve.log.1",
                "bus_log": "bus.log", "serve_log": "serve.log", "web_log": "web-terminal.log", "health": "health"}


class Sampler(threading.Thread):
    def __init__(self, box, interval=10.0):
        threading.Thread.__init__(self, daemon=True)
        self.box, self.interval = box, interval
        self.rows = []
        self.stop_flag = threading.Event()
        self.out = open(os.path.join(RESULTS, "samples.jsonl"), "a")

    def sample(self):
        box = self.box
        t = time.time() - T0
        row = {"t": round(t, 1)}
        procs = scan(box.entry.pid if box.entry else -1)
        counts, zombies, panel_rss, panel_cpu = {}, 0, 0, 0
        for role, p in procs:
            counts[role] = counts.get(role, 0) + 1
            if p.state == "Z":
                zombies += 1
            if role == "panel":
                panel_rss += p.rss
                panel_cpu += p.utime + p.stime
            elif role in LONG_LIVED:
                key = role if counts[role] == 1 else "%s#%d" % (role, counts[role])
                row[key] = {"pid": p.pid, "rss": p.rss, "fds": p.fds, "thr": p.threads, "cpu": p.utime + p.stime, "start": p.start}
        row["panels"] = {"n": counts.get("panel", 0), "rss": panel_rss, "cpu": panel_cpu}
        row["procs"] = len(procs)
        row["zombies"] = zombies
        row["counts"] = {k: v for k, v in counts.items() if not k.startswith("other:") or v > 3}
        row["files"] = {k: size(os.path.join(box.state, v)) for k, v in SAMPLE_FILES.items()}
        try:
            row["goal_dirs"] = len(os.listdir(os.path.join(box.sysop_state, "goals")))
        except OSError:
            row["goal_dirs"] = -1
        row["state_bytes"] = dir_bytes(box.state)
        try:
            row["run_entries"] = len(os.listdir(RUN))
            row["tab_locks"] = len(os.listdir(os.path.join(RUN, "tabs")))
        except OSError:
            row["tab_locks"] = 0
        row["panel_report"] = box.panel_report()
        st = box.goal_states()
        row["goals"] = {s: sum(1 for g in st.values() if g.get("state") == s) for s in ("queued", "running", "waiting_approval", "done", "failed", "stopped")}
        return row

    def run(self):
        while not self.stop_flag.is_set():
            try:
                row = self.sample()
                self.rows.append(row)
                self.out.write(json.dumps(row) + "\n")
                self.out.flush()
            except Exception as e:      # a sample that fails is a gap, never the end of the run
                log("sampler: %r" % (e,))
            self.stop_flag.wait(self.interval)


def series(rows, role, field):
    """[(t, pid, value)] of a role"""
    return [(r["t"], r[role]["pid"], r[role][field]) for r in rows if role in r]


def segments(ser):
    """split a series at every change of pid: {pid: [(t, value)]}"""
    out = {}
    for t, pid, v in ser:
        out.setdefault(pid, []).append((t, v))
    return out


def slope_per_min(pts):
    """least squares slope of (t seconds, value) in value per minute"""
    n = len(pts)
    if n < 3:
        return 0.0
    mt = sum(t for t, _ in pts) / n
    mv = sum(v for _, v in pts) / n
    den = sum((t - mt) ** 2 for t, _ in pts)
    return 60.0 * sum((t - mt) * (v - mv) for t, v in pts) / den if den else 0.0


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def analyze(rows, idle_from, idle_to):
    """memory, descriptors and idle CPU of the long-lived processes. Returns a list of table rows and fills FAILED through check()."""
    table = []
    hz = os.sysconf("SC_CLK_TCK")
    for role in LONG_LIVED:
        ser = series(rows, role, "rss")
        segs = segments(ser)
        if not segs:
            continue
        pid, pts = max(segs.items(), key=lambda kv: kv[1][-1][0] - kv[1][0][0])
        span = pts[-1][0] - pts[0][0]
        third = max(1, len(pts) // 3)
        first, last = median([v for _, v in pts[:third]]), median([v for _, v in pts[-third:]])
        fds = [v for t, p, v in series(rows, role, "fds") if p == pid]
        cpu = [(t, v) for t, p, v in series(rows, role, "cpu") if p == pid and idle_from <= t <= idle_to]
        idle_cpu = None
        if len(cpu) >= 2 and cpu[-1][0] > cpu[0][0]:
            idle_cpu = 100.0 * (cpu[-1][1] - cpu[0][1]) / hz / (cpu[-1][0] - cpu[0][0])
        table.append({"role": role, "pid": pid, "span_s": round(span), "rss_first": first, "rss_last": last, "rss_slope_kib_min": round(slope_per_min(pts), 1),
                      "rss_max": max(v for _, v in pts), "fds_first": fds[0] if fds else None, "fds_last": fds[-1] if fds else None, "fds_max": max(fds) if fds else None,
                      "idle_cpu_pct": None if idle_cpu is None else round(idle_cpu, 2)})
    return table


# ---------------------------------------------------------------------------------------------------------------------- the steady load
class Load(threading.Thread):
    """What a box in use looks like while the faults happen: a goal on the bus every few seconds, a spoken goal through the front, a browser-like
    websocket client that attaches, types, resizes and leaves."""

    def __init__(self, box):
        threading.Thread.__init__(self, daemon=True)
        self.box = box
        self.paused = threading.Event()
        self.stop_flag = threading.Event()
        self.idle = threading.Event()        # set while the thread is between operations (a pause waits for it)
        self.ops = []                        # (t, op, result, seconds)
        self.n = 0
        self.tab = None

    def record(self, op, result, secs):
        self.ops.append((round(time.time() - T0, 1), op, result, round(secs, 2)))

    def op_goal(self):
        t = time.time()
        r = self.box.sh(["swarmbox-bus", "pub", "--source", "cli", "goal", "--", "steady %d #s=ok #tab=%s" % (self.n, self.tab)], timeout=30)
        self.record("goal", "ok" if r.returncode == 0 else "exit%d" % r.returncode, time.time() - t)

    def op_voice(self):
        t = time.time()
        st, state = voice_say("steady voice %d #s=read #tab=%s" % (self.n, self.tab))
        self.record("voice", "%s/%s" % (st, state), time.time() - t)

    def op_ws(self):
        t = time.time()
        try:
            ws = Ws()
            ws.recv_some(0.6)
            ws.input("echo ws%d\r" % self.n)
            for cols, rows in ((100, 30), (140, 45), (90, 28)):
                ws.resize(cols, rows)
                ws.recv_some(0.3)
            ws.close()
            self.record("ws", "ok", time.time() - t)
        except OSError as e:
            self.record("ws", "err:%s" % str(e)[:40], time.time() - t)

    def run(self):
        while not self.stop_flag.is_set():
            self.idle.set()
            if self.paused.is_set():
                time.sleep(0.2)
                continue
            self.idle.clear()
            self.n += 1
            if not self.tab:
                self.tab = self.box.work_window() or ""
            try:
                if self.n % 6 == 0:
                    self.op_goal()
                if self.n % 17 == 3:
                    self.op_voice()
                if self.n % 23 == 5:
                    self.op_ws()
            except Exception as e:
                self.record("load", "exception %r" % (e,), 0)
            self.idle.set()
            time.sleep(1.0)

    def pause(self):
        self.paused.set()
        self.idle.wait(60)
        time.sleep(0.3)

    def resume(self):
        self.paused.clear()


def sanitize(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s or ""))[:64].strip(".")


def pub_goal(box, text, source="cli", timeout=30):
    """(exit code, goal id or the error line, seconds)"""
    t = time.time()
    r = box.sh(["swarmbox-bus", "pub", "--source", source, "goal", "--", text], timeout=timeout)
    if r.returncode != 0:
        return r.returncode, (r.stderr.strip() or r.stdout.strip()), time.time() - t
    try:
        return 0, sanitize(json.loads(r.stdout)["id"]), time.time() - t
    except (ValueError, KeyError):
        return 0, "", time.time() - t


def wait_goal(box, gid, timeout=60, states=("done", "failed", "stopped")):
    """(state, seconds) once the goal has one of `states`; (last state or None, seconds) on timeout"""
    t = time.time()
    st = None
    while time.time() - t < timeout:
        g = box.goal_state(gid)
        st = g.get("state") if g else None
        if st in states:
            return st, time.time() - t
        time.sleep(0.2)
    return st, time.time() - t


def probe_flow(box, timeout=40, mode="read"):
    """one goal through the whole path: (ok, seconds, detail)"""
    t = time.time()
    end = t + timeout
    last = ""
    while time.time() < end:
        rc, gid, _ = pub_goal(box, "probe #s=%s #tab=%s" % (mode, box.work_window()))
        if rc == 0 and gid:
            st, _ = wait_goal(box, gid, max(5, end - time.time()))
            if st == "done":
                return True, time.time() - t, gid
            last = "goal %s ended %s" % (gid, st)
        else:
            last = "pub exit %s: %s" % (rc, gid)
        time.sleep(0.5)
    return False, time.time() - t, last


def kill9(p, sig=signal.SIGKILL):
    try:
        os.kill(p.pid, sig)
        return True
    except OSError:
        return False


def tracebacks(box):
    """lines mentioning a Python traceback or an unhandled exception in the logs of the stack"""
    found = []
    for name in ("serve.log", "bus.log", "web-terminal.log", "sysop/serve.log", "sysop/serve.log.1"):
        lines = read(os.path.join(box.state, name)).splitlines()
        for i, line in enumerate(lines):
            if "Traceback (most recent call last)" in line:
                found.append("%s:%d: %s" % (name, i + 1, " | ".join(x.strip() for x in lines[i:i + 10])[:600]))
    for line in read(os.path.join(RESULTS, "entrypoint.out")).splitlines():
        if "Traceback (most recent call last)" in line:
            found.append("entrypoint.out: " + line[:160])
    return found


def row(fault, what, recovery, ok, fixed=None, note=""):
    r = {"fault": fault, "what": what, "recovery_s": None if recovery is None else round(recovery, 1), "ok": bool(ok), "note": note}
    ROWS.append(r)
    log("ROW %-24s %-5s recovery %-7s %s%s" % (fault, "ok" if ok else "FAIL", r["recovery_s"], what, (" | " + note) if note else ""))
    if not ok:
        FAILED.append("fault " + fault)
    return r


# ---------------------------------------------------------------------------------------------------------------------- the bus, in process (a flood needs more than the CLI's start-up per message)
def bus_pub(topic, body, source="soak", timeout=20):
    """one publication straight on the socket: the reply dict, or {"err": ...} when nobody answered"""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(os.path.join(RUN, "bus.sock"))
        s.sendall((json.dumps({"op": "pub", "topic": topic, "source": source, "body": body}) + "\n").encode())
        with s.makefile("rb") as f:
            return json.loads(f.readline())
    except (OSError, ValueError) as e:
        return {"ok": False, "err": "client:%s" % type(e).__name__}
    finally:
        s.close()


def heal(box, wait=70):
    """put the stack back before the next fault, the way a person would (and say what had to be done)"""
    repairs = []
    if not box.bus_ok():
        if not wait_for(box.bus_ok, 8):
            box.sh(["swarmbox-bus", "restart"])
            repairs.append("swarmbox-bus restart")
            wait_for(box.bus_ok, 15)
    if not box.sysop_up():
        if not wait_for(box.sysop_up, 12):
            box.sh(["swarmbox-tool", "prepare"], timeout=60)
            repairs.append("swarmbox-tool prepare")
            wait_for(box.sysop_up, 20)
    if not (box.front_ok() and box.term_ok()):
        if not wait_for(lambda: box.front_ok() and box.term_ok(), 20):
            box.sh(["swarmbox-web", "restart"])
            repairs.append("swarmbox-web restart")
            wait_for(lambda: box.front_ok() and box.term_ok(), 20)
    return repairs


def idle_state(box):
    st = box.sysop_status() or {}
    return not st.get("current") and not st.get("queue")


def wait_running(box, gid, timeout=20):
    return wait_goal(box, gid, timeout, states=("running", "waiting_approval", "done", "failed", "stopped"))


# ---------------------------------------------------------------------------------------------------------------------- the faults
def f_bus_kill(box, load):
    p = box.one("bus")
    t0 = time.time()
    kill9(p)
    rc, msg, _ = pub_goal(box, "during the outage #s=read")
    vs = voice_say("voice during the outage #s=read")
    t_bus = wait_for(box.bus_ok, 30)
    t_sysop = wait_for(box.sysop_up, 60)
    ok, secs, det = probe_flow(box, 60)
    rec = time.time() - t0
    new = box.one("bus")
    good = bool(t_bus and t_sysop and ok and new and new.pid != p.pid) and rec < 25
    row("bus-kill", "kill -9 of the broker; pub in the outage: exit %s (%s); voice in the outage: %s; the supervisor restarted it after %s s; the sysop was connected again after %s s; first goal through the whole path done %.1f s later"
        % (rc, msg[:70], vs, "%.1f" % t_bus[0] if t_bus else "never", "%.1f" % t_sysop[0] if t_sysop else "never", secs), rec, good)


def f_sysop_kill(box, load):
    p = box.one("sysop")
    t0 = time.time()
    kill9(p)
    got = wait_for(lambda: (box.one("sysop") or p).pid != p.pid and box.sysop_up(), 45)
    rec = time.time() - t0
    note = ""
    if not got:
        r = box.sh(["swarmbox-tool", "prepare"], timeout=60)
        wait_for(box.sysop_up, 20)
        note = "nobody restarted it; `swarmbox-tool prepare` by hand did"
    ok, secs, det = probe_flow(box, 40)
    row("sysop-kill", "kill -9 of the resident service while idle; %s" % ("a new service was up after %.1f s" % got[0] if got else "no service for 45 s"), got[0] if got else None, bool(got and ok), note=note)


def f_sysop_kill_midgoal(box, load):
    load.pause()
    try:
        p = box.one("sysop")
        rc, gid, _ = pub_goal(box, "long goal #s=slow #tab=%s" % box.work_window())
        st, _ = wait_running(box, gid)
        t0 = time.time()
        kill9(p)
        got = wait_for(lambda: (box.one("sysop") or p).pid != p.pid and box.sysop_up(), 45)
        note = ""
        if not got:
            box.sh(["swarmbox-tool", "prepare"], timeout=60)
            wait_for(box.sysop_up, 20)
            note = "nobody restarted it; prepare by hand"
        rec = time.time() - t0
        left = wait_for(lambda: not [x for r, x in scan(box.entry.pid) if r in ("brain", "mcp")], 20)
        g = box.goal_state(gid) or {}
        final = g.get("state")
        ok, secs, det = probe_flow(box, 40)
        good = bool(got and final == "failed" and "lost" in (g.get("error") or "") and left and ok)
        row("sysop-kill-midgoal", "kill -9 of the service while a goal runs; goal state afterwards: %s (%s); brain and MCP server gone: %s; service back after %s s"
            % (final, (g.get("error") or "")[:60], bool(left), "%.1f" % got[0] if got else "never"), got[0] if got else rec, good, note=note)
    finally:
        load.resume()


def f_sysop_crashloop(box, load):
    load.pause()
    try:
        t0, kills, last = time.time(), 0, None
        crash = os.path.join(box.sysop_run, "crashloop")
        for _ in range(8):
            got = wait_for(lambda: (lambda p: p if p is not None and (last is None or p.pid != last) else None)(box.one("sysop")), 40, 0.1)
            if not got:
                break
            last = got[1].pid
            kill9(got[1])
            kills += 1
            if os.path.exists(crash):
                break
            time.sleep(0.2)
        gave = wait_for(lambda: os.path.exists(crash), 60, 0.5)
        time.sleep(2)
        down = box.one("sysop") is None
        st = box.sysop("status")
        said = (st.stdout + st.stderr).strip().split("\n")[0][:150]
        pub = pub_goal(box, "while the sysop has given up #s=read")
        v = voice_say("voice while the sysop has given up #s=read")
        t1 = time.time()
        box.sh(["swarmbox-tool", "prepare"], timeout=60)
        back = wait_for(box.sysop_up, 30)
        ok, secs, det = probe_flow(box, 40)
        cleared = not os.path.exists(crash)
        row("sysop-crashloop", "kill -9 of the service %d times in a row: the watcher %s; status said: %s; pub then said exit %s, voice %s; `swarmbox-tool prepare` brought it back in %s s (crashloop file gone: %s)"
            % (kills, "gave up" if gave else "kept restarting", said, pub[0], v, "%.1f" % back[0] if back else "never", cleared), time.time() - t1,
            bool(gave) and down and bool(back) and ok and cleared and "keeps crashing" in said)
    finally:
        load.resume()


def f_brain_kill(box, load):
    load.pause()
    try:
        wait_for(lambda: idle_state(box), 30, 0.2)               # no goal of the steady load is running: its brain must not be the one that is killed
        rc, gid, _ = pub_goal(box, "goal whose brain dies #s=slow #tab=%s" % box.work_window())
        wait_running(box, gid, 30)

        def own_brain():
            pid = ((box.goal_state(gid) or {}).get("brain") or {}).get("pid")          # the `timeout` wrapper of this goal; the fake claude is its child
            return next((x for r, x in scan(box.entry.pid) if r == "brain" and x.ppid == pid and "fixtures/sysop/bin/claude" in " ".join(x.cmd)), None)
        brain = wait_for(own_brain, 20, 0.05)
        t0 = time.time()
        if brain:
            kill9(brain[1])
        st, secs = wait_goal(box, gid, 40)
        g = box.goal_state(gid) or {}
        gone = wait_for(lambda: not [x for r, x in scan(box.entry.pid) if r in ("brain", "mcp")], 20)
        ok, psecs, det = probe_flow(box, 30)
        row("brain-kill", "kill -9 of the brain mid-goal; goal ended %s after %.1f s: %s; brain and MCP server gone: %s" % (st, secs, (g.get("error") or "")[:110], bool(gone)),
            secs, bool(brain) and st == "failed" and bool(gone) and ok, note="message: " + (g.get("error") or "")[:160])
    finally:
        load.resume()


def f_voice_service_kill(box, load):
    p = box.one("voice-service")
    t0 = time.time()
    kill9(p)
    seen = []
    t_end = time.time() + 40
    ok = False
    while time.time() < t_end:
        st, state = voice_say("after the voice service died #s=read #tab=%s" % box.work_window())
        seen.append("%s/%s" % (st, state))
        if state == "sent":
            ok = True
            break
        time.sleep(0.4)
    rec = time.time() - t0
    new = box.one("voice-service")
    uniq = []
    for x in seen:
        if x not in uniq:
            uniq.append(x)
    row("voice-service-kill", "kill -9 of the voice service; answers of the front meanwhile: %s; the front restarted it" % ", ".join(uniq), rec, ok and new is not None and new.pid != p.pid and rec < 15)


def f_ttyd_kill(box, load):
    ws = None
    try:
        ws = Ws()
        ws.recv_some(0.5)
    except OSError:
        pass
    clients0 = len(box.by_role("tmux-client"))
    p = box.one("ttyd")
    t0 = time.time()
    kill9(p)
    got = wait_for(lambda: box.front_ok() and box.term_ok() and (box.one("ttyd") or p).pid != p.pid, 40)
    rec = time.time() - t0
    try:
        w2 = Ws()
        w2.recv_some(0.5)
        w2.close()
        ws_ok = True
    except OSError as e:
        ws_ok = False
    if ws:
        ws.close()
    time.sleep(2)
    clients = len(box.by_role("tmux-client"))
    one = len(box.by_role("ttyd")) == 1 and len(box.by_role("voice-front")) == 1 and len(box.by_role("voice-service")) == 1
    row("ttyd-kill", "kill -9 of ttyd with a browser attached; the front exited and the supervisor restarted the web terminal; a new websocket works: %s; tmux clients %d -> %d; one of each process: %s"
        % (ws_ok, clients0, clients, one), rec, bool(got) and ws_ok and one and clients <= clients0 and rec < 15)


def f_voice_front_kill(box, load):
    old = {r: box.one(r) for r in ("voice-front", "ttyd", "voice-service")}
    t0 = time.time()
    kill9(old["voice-front"])
    got = wait_for(lambda: box.front_ok() and box.term_ok() and (box.one("voice-front") or old["voice-front"]).pid != old["voice-front"].pid, 40)
    rec = time.time() - t0
    time.sleep(3)
    left = [r for r in ("ttyd", "voice-service") if any(x.pid == old[r].pid for x in box.by_role(r))]
    one = len(box.by_role("ttyd")) == 1 and len(box.by_role("voice-front")) == 1 and len(box.by_role("voice-service")) == 1
    row("voice-front-kill", "kill -9 of the front (the owner of the web port); old ttyd or old voice service left running: %s; one of each process: %s; web terminal back after %s s"
        % (left or "none", one, "%.1f" % got[0] if got else "never"), rec, bool(got) and not left and one and rec < 15)


def f_tab_window_kill(box, load):
    load.pause()
    try:
        box.tmux("new-window", "-d", "-t", "main:", "-n", "wk", "-c", box.proj, "env PS1='$ ' bash --norc --noprofile")
        wk = next((w["id"] for w in box.windows() if w["name"] == "wk"), None)
        wait_for(lambda: box.panel_report()[0] == box.panel_report()[1], 10)
        keys = "".join("{Up}" for _ in range(60))
        env = dict(box.env)
        proc = subprocess.Popen(["swarmbox-tabs", "send", wk, "--input", keys], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        time.sleep(1.2)
        t0 = time.time()
        box.tmux("kill-window", "-t", wk)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            out = "HUNG"
        send_secs = time.time() - t0
        # a goal whose tab disappears while it works
        box.tmux("new-window", "-d", "-t", "main:", "-n", "wk2", "-c", box.proj, "env PS1='$ ' bash --norc --noprofile")
        wk2 = next((w["id"] for w in box.windows() if w["name"] == "wk2"), None)
        rc, gid, _ = pub_goal(box, "goal on a tab that goes away #s=slow #tab=%s" % wk2)
        wait_running(box, gid)
        time.sleep(1.0)
        box.tmux("kill-window", "-t", wk2)
        st, secs = wait_goal(box, gid, 40)
        g = box.goal_state(gid) or {}
        calls = [(c.get("tool"), c.get("is_error"), (c.get("summary") or "")[:90]) for c in g.get("calls", [])]
        ok, psecs, det = probe_flow(box, 30)
        lock_free = box.sh(["swarmbox-tabs", "send", box.work_window(), "--input", "{Escape}"]).returncode == 0
        msg = ""
        try:
            msg = json.loads(out).get("msg", "")[:100] + " [" + json.loads(out).get("err", "") + "]"
        except (ValueError, AttributeError):
            msg = str(out)[:100]
        row("tab-window-kill", "kill-window while swarmbox-tabs sends 60 keys: ended after %.1f s with %s; a goal whose tab vanished mid-goal ended %s after %.1f s; lock free afterwards: %s"
            % (send_secs, msg, st, secs, lock_free), max(send_secs, secs), out != "HUNG" and st in ("done", "failed") and ok and lock_free, note="calls of the goal: %s" % calls)
    finally:
        load.resume()


def f_window_churn(box, load):
    load.pause()
    try:
        base = box.panel_report()[0]
        t0 = time.time()
        ids = []
        for i in range(30):
            box.tmux("new-window", "-d", "-t", "main:", "-n", "ch%d" % i, "-c", box.proj, "env PS1='$ ' bash --norc --noprofile")
        for w in box.windows():
            if w["name"].startswith("ch"):
                ids.append(w["id"])
        for i, w in enumerate(ids):
            if i % 2 == 0:
                box.tmux("kill-window", "-t", w)
        for i in range(20):
            box.tmux("new-window", "-d", "-t", "main:", "-n", "cn%d" % i, "-c", box.proj, "env PS1='$ ' bash --norc --noprofile")
        for w in box.windows():
            if w["name"].startswith(("ch", "cn")):
                box.tmux("kill-window", "-t", w["id"])
        settle = wait_for(lambda: (lambda r: r[0] == base and r[1] == r[0] and r[2] == r[0] and r[3] == 0)(box.panel_report()), 40, 0.5)
        rep = box.panel_report()
        time.sleep(SYNC_TICK + 2)
        panels = len(box.by_role("panel"))
        extra = [p for p in box.panes() if p["panel"] == "1" and p["win"] not in [w["id"] for w in box.windows()]]
        rec = time.time() - t0
        row("window-churn", "30 windows opened, 15 closed, 20 opened, all closed (and the dock hooks racing); windows %s, with one panel %s, panels %s, extra user panes %s; panel processes %d; settled after %s s"
            % (rep[0], rep[1], rep[2], rep[3], panels, "%.1f" % settle[0] if settle else "never"), rec, bool(settle) and panels == base and not extra)
    finally:
        load.resume()


def f_resize_storm(box, load):
    load.pause()
    try:
        w1 = box.work_window()
        t0 = time.time()
        peak = [0]
        stop = threading.Event()

        peak_rss = [0]

        def watch():
            while not stop.is_set():
                ps = [p for r, p in scan(box.entry.pid) if r == "sysop-cli" and p.cmd and os.path.basename(p.cmd[0]).startswith("python")]      # the sh -c of run-shell is not counted
                peak[0] = max(peak[0], len(ps))
                peak_rss[0] = max(peak_rss[0], sum(p.rss for p in ps))
                time.sleep(0.1)
        th = threading.Thread(target=watch, daemon=True)
        th.start()
        for i in range(80):
            x, y = ((200, 50), (60, 90))[i % 2]
            box.tmux("resize-window", "-t", w1, "-x", x, "-y", y)
        ws = []
        try:
            for i in range(3):
                ws.append(Ws())
            for i in range(40):
                for w in ws:
                    w.resize(*((180, 50), (50, 80), (120, 40))[i % 3])
                time.sleep(0.05)
        except OSError:
            pass
        for w in ws:
            w.close()
        settle = wait_for(lambda: not [1 for r, p in scan(box.entry.pid) if r == "sysop-cli"] and (lambda r: r[0] == r[1] == r[2] and r[3] == 0)(box.panel_report()), 40, 0.5)
        stop.set()
        rep = box.panel_report()
        locks = [f for f in os.listdir(os.path.join(box.sysop_run)) if f.endswith(".lock")] if os.path.isdir(box.sysop_run) else []
        rec = time.time() - t0
        row("resize-storm", "80 resize-window calls and 120 websocket resizes in a burst (window-resized hook racing); peak of dock processes (python) at once %d, %d MiB; panels %s; settled after %s s"
            % (peak[0], peak_rss[0] >> 10, rep, "%.1f" % settle[0] if settle else "never"), rec, bool(settle) and peak[0] < 30 and peak_rss[0] < (600 << 10))
    finally:
        load.resume()


def f_flood(box, load):
    load.pause()
    try:
        sysop0, bus0 = box.one("sysop"), box.one("bus")
        t0 = time.time()
        replies = {}

        def one(i):
            if i % 10 == 0:
                body = {"text": "huge %d %s" % (i, "x" * 12000)}
            elif i % 37 == 0:
                body = {"text": "very huge %d %s" % (i, "y" * 900000)}
            elif i % 41 == 0:
                body = [1, 2, 3] if i % 2 else None
            else:
                body = {"text": "flood %d #s=read #tab=%s" % (i, box.work_window())}
            r = bus_pub("goal", body, source="cli" if i % 3 else "voice")
            k = r.get("err") or "ok"
            replies[k] = replies.get(k, 0) + 1
        threads = []
        for base in range(0, 500, 8):
            batch = [threading.Thread(target=one, args=(base + j,)) for j in range(8)]
            for b in batch:
                b.start()
            for b in batch:
                b.join()
        big = bus_pub("goal", {"text": "z" * (2 << 20)})
        sent_s = time.time() - t0
        idle = wait_for(lambda: idle_state(box), 120, 0.5)
        time.sleep(2)
        sysop1, bus1 = box.one("sysop"), box.one("bus")
        dirs = len(os.listdir(os.path.join(box.sysop_state, "goals")))
        ok, secs, det = probe_flow(box, 60)
        grew = (sysop1.rss - sysop0.rss, bus1.rss - bus0.rss) if sysop1 and bus1 and sysop0 and bus0 else (None, None)
        alive = sysop1 is not None and sysop0 is not None and sysop1.pid == sysop0.pid and bus1.pid == bus0.pid
        row("flood", "500 goals in %.1f s (every 10th 12 KB, every 37th 900 KB, some not text) and one of 2 MiB (%s); bus replies %s; idle again after %s s; goal folders %d; RSS change sysop %s KiB, bus %s KiB; same processes: %s"
            % (sent_s, big.get("err"), replies, "%.1f" % idle[0] if idle else "never", dirs, grew[0], grew[1], alive), time.time() - t0, bool(idle) and ok and alive and dirs <= 60)
    finally:
        load.resume()


def f_stopped_subscriber(box, load):
    load.pause()
    try:
        bus0 = box.one("bus")
        procs = []
        for group in (None, "sysop"):
            argv = ["swarmbox-bus", "sub", "--raw"] + (["--group", group] if group else []) + ["goal"]
            p = subprocess.Popen(argv, env=box.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
            procs.append(p)
        time.sleep(1.0)
        for p in procs:
            os.kill(p.pid, signal.SIGSTOP)
        t0 = time.time()
        codes = {}
        for i in range(60):
            r = bus_pub("goal", {"text": "to stopped readers %d %s #s=read #tab=%s" % (i, "p" * 150000, box.work_window())})
            k = r.get("err") or "ok"
            codes[k] = codes.get(k, 0) + 1
        time.sleep(1)
        bus1 = box.one("bus")
        rss = (bus1.rss - bus0.rss) if bus1 and bus0 else None
        ok1, secs1, det1 = probe_flow(box, 40)
        for p in procs:
            os.kill(p.pid, signal.SIGCONT)
        time.sleep(1)
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait(5)
        ok, secs, det = probe_flow(box, 40)
        recovered = wait_for(lambda: idle_state(box), 30)
        rec = time.time() - t0
        row("stopped-subscriber", "a subscriber and a group member stopped (SIGSTOP) while 60 goals of 150 KB (9 MB) were published; replies %s; broker RSS change %s KiB; the real sysop still got goals: %s; flow after they went: %s"
            % (codes, rss, ok1, ok), rec, ok1 and ok and rss is not None and rss < 30000 and bus1 is not None and bus1.pid == bus0.pid)
    finally:
        load.resume()


def f_sysop_stop(box, load):
    load.pause()
    try:
        p = box.one("sysop")
        t0 = time.time()
        os.kill(p.pid, signal.SIGSTOP)
        replies = []
        for i in range(3):
            r = bus_pub("goal", {"text": "to a stopped sysop %d #s=read #tab=%s" % (i, box.work_window())})
            replies.append(r.get("err") or "ok")
        vs = voice_say("voice to a stopped sysop #s=read")
        time.sleep(8)
        os.kill(p.pid, signal.SIGCONT)
        ok, secs, det = probe_flow(box, 60)
        wait_for(lambda: idle_state(box), 60)
        rec = time.time() - t0
        row("sysop-stop", "the service stopped (SIGSTOP) 8 s; pub replies %s; voice said %s; after SIGCONT the first fresh goal was done after %.1f s (goals written to its socket meanwhile are run now)"
            % (replies, vs, secs), secs, ok)
    finally:
        load.resume()


def f_voice_stop(box, load):
    load.pause()
    try:
        svc, front = box.one("voice-service"), box.one("voice-front")
        fds0 = front.fds
        os.kill(svc.pid, signal.SIGSTOP)
        t0 = time.time()
        results = []

        def post():
            st, state = voice_say("a request to a stopped voice service")
            results.append("%s/%s" % (st, state))
        ths = [threading.Thread(target=post, daemon=True) for _ in range(3)]
        for t in ths:
            t.start()
        time.sleep(3)
        term = wait_for(box.term_ok, 5)
        os.kill(svc.pid, signal.SIGCONT)
        for t in ths:
            t.join(30)
        ok = wait_for(lambda: voice_say("after the voice service woke #s=read #tab=%s" % box.work_window())[1] == "sent", 30)
        time.sleep(1)
        front2 = box.one("voice-front")
        row("voice-stop", "voice service stopped 3 s with 3 requests pending; the terminal path answered meanwhile: %s; the 3 requests ended %s; voice works after SIGCONT: %s; front descriptors %s -> %s"
            % (bool(term), results, bool(ok), fds0, front2.fds if front2 else None), time.time() - t0, bool(term) and bool(ok) and front2 is not None and front2.fds <= fds0 + 2)
    finally:
        load.resume()


def audit_limits():
    sys.path.insert(0, os.path.join(REPO, "container", "tools", "sysop", "lib"))
    from swarmbox_sysop import audit
    return audit.MAX_FILE, getattr(audit, "KEEP", 1)


def f_audit_rotation(box, load):
    load.pause()
    try:
        limit, keep = audit_limits()
        path = box.audit_path
        line = (json.dumps({"t": 1.0, "time": "2026-01-01T00:00:00.000Z", "goal": "old", "source": "cli", "event": "pad", "text": "p" * 900}) + "\n").encode()
        def pad():
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)          # opened again each time: a rotation moves the file under an open descriptor
            try:
                os.write(fd, line * 500)
            finally:
                os.close(fd)
        t0 = time.time()
        rounds = 0
        biggest = 0
        while rounds < keep + 2:
            # fill to just under the limit, then let real goals push it over
            while size(path) < limit - 60000:
                pad()
            for i in range(25):
                bus_pub("goal", {"text": "rotate %d #s=read #tab=%s" % (i, box.work_window())})
            wait_for(lambda: idle_state(box), 90, 0.5)
            rounds += 1
            biggest = max(biggest, size(path))
        files = sorted(f for f in os.listdir(os.path.join(box.sysop_state)) if f.startswith("events.jsonl") and not f.endswith(".lock"))
        total = sum(size(os.path.join(box.sysop_state, f)) for f in files)
        alive = box.sysop_up()
        bound = limit * (keep + 1) + (2 << 20)
        row("audit-rotation", "the audit file driven past its limit (%d MiB, keeping %d old files) %d times; files %s, total %.1f MiB (bound %.1f MiB), biggest current file %.1f MiB; service up: %s"
            % (limit >> 20, keep, rounds, files, total / 1048576.0, bound / 1048576.0, biggest / 1048576.0, alive), time.time() - t0, total <= bound and alive and len(files) <= keep + 1)
    finally:
        load.resume()


def f_disk_full(box, load):
    load.pause()
    try:
        sysop0 = box.one("sysop")
        ballast = os.path.join(box.state, "ballast.bin")
        chunk = b"\0" * (1 << 20)
        with open(ballast, "wb") as f:
            try:
                while True:
                    f.write(chunk)
                    f.flush()
            except OSError:
                pass
            f.flush()
        # leave a little room: the disk is "almost full", not "full"
        with open(ballast, "r+b") as f:
            f.truncate(max(0, os.path.getsize(ballast) - 60000))
        t0 = time.time()
        free = shutil.disk_usage(box.state).free
        outcomes = []
        for i in range(6):
            rc, gid, _ = pub_goal(box, "goal on a full disk %d #s=ok #tab=%s" % (i, box.work_window()))
            st, secs = wait_goal(box, gid, 25) if rc == 0 else (None, 0)
            outcomes.append(st)
        vs = voice_say("voice on a full disk #s=read")
        with open(ballast, "wb") as f:                          # now really full
            try:
                while True:
                    f.write(chunk)
                    f.flush()
            except OSError:
                pass
        for i in range(4):
            rc, gid, _ = pub_goal(box, "goal on a really full disk %d #s=read #tab=%s" % (i, box.work_window()))
            time.sleep(2)
        time.sleep(3)
        sysop1 = box.one("sysop")
        survived = sysop1 is not None and sysop0 is not None and sysop1.pid == sysop0.pid
        tb = tracebacks(box)
        os.unlink(ballast)
        t1 = time.time()
        got = wait_for(box.sysop_up, 60)
        if not got:
            box.sh(["swarmbox-tool", "prepare"], timeout=60)
            wait_for(box.sysop_up, 20)
        ok, secs, det = probe_flow(box, 60)
        tmp = [f for r, d, fs in os.walk(box.state) for f in fs if f.startswith(".tmp-")]
        rec = time.time() - t1
        row("disk-full", "the state folder (%d MiB tmpfs) filled to %d KiB free, then to zero; 6 goals meanwhile ended %s; voice said %s; the service survived: %s; traceback lines in the logs: %d; stray temp files after: %d; flow again after the space came back: %s (%.1f s)"
            % (int(shutil.disk_usage(box.state).total) >> 20, free >> 10, outcomes, vs, survived, len(tb), len(tmp), ok, secs), rec, survived and ok and not tb,
            note="; ".join(tb[:3]))
    finally:
        load.resume()


def f_tmux_kill(box, load):
    load.pause()
    try:
        sysop0 = box.one("sysop")
        t0 = time.time()
        kill9(box.one("tmux-server"))
        time.sleep(1.5)
        r = box.sh(["swarmbox-tabs", "list"])
        said = (r.stdout.strip() or r.stderr.strip())[:170]
        rc, gid, _ = pub_goal(box, "a goal while tmux is gone #s=read")
        st, secs = wait_goal(box, gid, 30)
        g = box.goal_state(gid) or {}
        alive = box.one("sysop") is not None and sysop0 is not None and box.one("sysop").pid == sysop0.pid
        # a browser comes back: ttyd runs swarmbox-attach --web, which makes the session again
        ws = None
        try:
            ws = Ws()
            ws.recv_some(2.0)
        except OSError:
            pass
        back = wait_for(lambda: (lambda r: r[0] >= 1 and r[0] == r[1] == r[2] and r[3] == 0)(box.panel_report()), 40, 0.5)
        def hook_list():       # session hooks, window hooks (window-resized) and pane hooks (pane-exited) are listed apart
            return "\n".join(box.tmux("show-hooks", *flag) for flag in (("-g",), ("-gw",), ("-gp",)))
        hooks_back = wait_for(lambda: all(h in hook_list() for h in ("after-new-window[418]", "pane-exited[418]", "after-kill-pane[418]", "window-resized[418]")), 20, 0.5)
        hooks = ""
        if ws:
            ws.close()
        rec = time.time() - t0
        box.make_windows(["w1", "w2", "w3"])
        box.tmux("select-window", "-t", "main:w1")
        wait_for(lambda: (lambda r: r[0] == r[1] == r[2])(box.panel_report()), 30, 0.5)
        load.tab = None
        ok, psecs, det = probe_flow(box, 40)
        row("tmux-kill", "kill -9 of the tmux server (every tab gone): swarmbox-tabs said %r; a goal meanwhile ended %s: %s; the sysop service survived: %s; a browser attached again and the panel was back in the new session after %s s (its hooks set again: %s); the whole path works again: %s"
            % (said, st, ((g.get("summary") or g.get("error") or "")[:110]), alive, "%.1f" % back[0] if back else "never", "all, %.1f s" % hooks_back[0] if hooks_back else "NOT ALL", ok), rec,
            alive and bool(back) and ok and st in ("done", "failed") and bool(hooks_back))
    finally:
        load.resume()


def f_bus_crashloop(box, load):
    load.pause()
    try:
        t0 = time.time()
        kills = 0
        for i in range(8):
            p = box.one("bus")
            if p is None:
                if not wait_for(lambda: box.one("bus") is not None, 40, 0.1):
                    break
                p = box.one("bus")
            kill9(p)
            kills += 1
            if "keeps crashing" in read(os.path.join(box.state, "health")):
                break
            time.sleep(0.3)
        gave_up = wait_for(lambda: "bus keeps crashing" in read(os.path.join(box.state, "health")), 40, 0.5)
        down = not box.bus_ok()
        pub = pub_goal(box, "while the bus is given up #s=read")
        v = voice_say("voice while the bus is given up #s=read")
        t1 = time.time()
        r = box.sh(["swarmbox-bus", "restart"])
        back = wait_for(box.bus_ok, 20)
        sysop_back = wait_for(box.sysop_up, 60)
        ok, secs, det = probe_flow(box, 60)
        health = read(os.path.join(box.state, "health"))
        row("bus-crashloop", "kill -9 of the broker %d times in a row: the supervisor %s (health line: %s), pub then said exit %s (%s), voice %s; `swarmbox-bus restart` brought it back in %s s, the sysop was connected %s s after that"
            % (kills, "gave up" if gave_up else "kept restarting", "yes" if "keeps crashing" not in health else "STILL THERE", pub[0], pub[1][:60], v,
               "%.1f" % back[0] if back else "never", "%.1f" % sysop_back[0] if sysop_back else "never"), time.time() - t1,
            bool(gave_up) and down and bool(back) and bool(sysop_back) and ok and "keeps crashing" not in health and sysop_back[0] < 20)
    finally:
        load.resume()


def f_entry_sigterm(box, load):
    load.pause()
    try:
        before = {r: [p.pid for p in box.by_role(r)] for r in ("bus", "ttyd", "voice-front", "voice-service", "supervisor", "sysop", "tmux-server")}
        secs, rc = box.stop_entry(signal.SIGTERM, 30)
        time.sleep(1.5)
        after = {r: [p.pid for p in box.by_role(r)] for r in before}
        left = {r: v for r, v in after.items() if v and r not in ("sysop", "tmux-server")}
        files = sorted(os.listdir(RUN))
        stale = [f for f in files if f in ("bus.sock", "web-supervisor.pid", "bus-supervisor.pid")]
        t0 = time.time()
        box.entry = None
        ok_start = box.start_entry()
        rec = time.time() - t0
        heal(box)
        ok, psecs, det = probe_flow(box, 60)
        dup = {r: len(box.by_role(r)) for r in ("bus", "sysop", "ttyd", "voice-front", "voice-service", "tmux-server")}
        row("entry-sigterm", "SIGTERM to the entrypoint: exit status %s after %.1f s; processes still running (not counting the detached sysop and tmux): %s; stale files %s; started again, ready after %.1f s; processes now %s"
            % (rc, secs, left or "none", stale or "none", rec, dup), rec, rc is not None and secs < 15 and not left and not stale and ok_start and ok and all(v == 1 for v in dup.values()))
    finally:
        load.resume()


FAULTS = [("bus-kill", f_bus_kill), ("sysop-kill", f_sysop_kill), ("sysop-kill-midgoal", f_sysop_kill_midgoal), ("sysop-crashloop", f_sysop_crashloop), ("brain-kill", f_brain_kill),
          ("voice-service-kill", f_voice_service_kill), ("ttyd-kill", f_ttyd_kill), ("voice-front-kill", f_voice_front_kill),
          ("tab-window-kill", f_tab_window_kill), ("window-churn", f_window_churn), ("resize-storm", f_resize_storm), ("flood", f_flood),
          ("stopped-subscriber", f_stopped_subscriber), ("sysop-stop", f_sysop_stop), ("voice-stop", f_voice_stop), ("audit-rotation", f_audit_rotation),
          ("disk-full", f_disk_full), ("tmux-kill", f_tmux_kill), ("bus-crashloop", f_bus_crashloop), ("entry-sigterm", f_entry_sigterm)]


# ---------------------------------------------------------------------------------------------------------------------- real goals, the final checks, the report
def real_goal(box, n):
    """a goal for the real claude: type a command in the tab named w2, check it ran"""
    if not TOKEN:
        log("real goal %d skipped: no login in the environment" % n)
        return
    w2 = next((w["id"] for w in box.windows() if w["name"] == "w2"), None)
    t0 = time.time()
    rc, gid, _ = pub_goal(box, "In the tab named w2 run the command: echo real-soak-%d. Then finish. #s=real" % n, source="voice")
    st, secs = wait_goal(box, gid, 160) if rc == 0 else (None, 0)
    g = box.goal_state(gid) or {}
    ran = re.search(r"(?m)^real-soak-%d\s*$" % n, box.cap(w2)) is not None if w2 else False
    check("real goal %d (claude -p, haiku): done, the command ran in the tab" % n, st == "done" and ran,
          "state %s after %.0f s, steps %s, cost %s, ran %s, %s" % (st, secs, g.get("steps"), (g.get("brain") or {}).get("cost"), ran, (g.get("summary") or g.get("error") or "")[:100]))


def final_checks(box, sampler, idle_from, idle_to):
    table = analyze(sampler.rows, idle_from, idle_to)
    log("%-14s %-6s %6s %9s %9s %10s %6s %6s %6s %8s" % ("process", "pid", "span_s", "rss_first", "rss_last", "KiB/min", "fds0", "fds_n", "fdmax", "idle_cpu%"))
    for t in table:
        log("%-14s %-6s %6s %9s %9s %10s %6s %6s %6s %8s" % (t["role"], t["pid"], t["span_s"], t["rss_first"], t["rss_last"], t["rss_slope_kib_min"], t["fds_first"], t["fds_last"], t["fds_max"], t["idle_cpu_pct"]))
    for t in table:
        pts = [(r["t"], r[t["role"]]["rss"]) for r in sampler.rows if t["role"] in r and r[t["role"]]["pid"] == t["pid"]]
        n = len(pts)
        mid = median([v for _, v in pts[n // 3: 2 * n // 3]])
        end = median([v for _, v in pts[2 * n // 3:]])
        grew = end - mid
        check("memory of %s (pid %s): second third %d KiB, last third %d KiB" % (t["role"], t["pid"], mid, end), n < 9 or not (grew > max(4096, 0.25 * mid) and t["rss_slope_kib_min"] > 20), "slope %s KiB/min over %d s" % (t["rss_slope_kib_min"], t["span_s"]))
        allow = 4 if t["role"] != "tmux-server" else 4 + 2 * box.panel_report()[2] + 6        # tmux: a pty per pane, a socket per client
        check("descriptors of %s: %s at the start, %s at the end" % (t["role"], t["fds_first"], t["fds_last"]), t["fds_last"] is None or t["fds_last"] <= (t["fds_first"] or 0) + allow)
        if t["idle_cpu_pct"] is not None:
            check("idle CPU of %s: %s %%" % (t["role"], t["idle_cpu_pct"]), t["idle_cpu_pct"] < 2.0)
    # panels: idle CPU of each, descriptors
    hz = os.sysconf("SC_CLK_TCK")
    prow = [r for r in sampler.rows if idle_from <= r["t"] <= idle_to and r["panels"]["n"]]
    if len(prow) >= 2 and prow[-1]["t"] > prow[0]["t"]:
        n = prow[-1]["panels"]["n"]
        cpu = 100.0 * (prow[-1]["panels"]["cpu"] - prow[0]["panels"]["cpu"]) / hz / (prow[-1]["t"] - prow[0]["t"])
        check("idle CPU of the %d panels together: %.2f %% (%.2f %% each)" % (n, cpu, cpu / max(1, n)), cpu / max(1, n) < 2.0)
    last = sampler.rows[-1] if sampler.rows else {}
    z = box_scan_zombies(box)
    check("no zombie at the end", not z, z)
    rep = box.panel_report()
    check("panels at the end: %s windows, %s with one panel, %s panels, %s windows with extra panes" % rep, rep[0] == rep[1] == rep[2] and rep[3] == 0)
    leftovers = [(r, p.pid, " ".join(p.cmd)[:80]) for r, p in scan(box.entry.pid) if r in ("brain", "mcp", "tmux-client", "attach", "sysop-cli", "voice-cli") or r.startswith("other:") and r not in ("other:bash", "other:sh", "other:sleep", "other:python3", "other:zsh")]
    check("no process left behind (brains, MCP servers, tmux clients, dock commands)", not leftovers, leftovers[:6])
    exp = {"bus": 1, "ttyd": 1, "voice-front": 1, "voice-service": 1, "tmux-server": 1}
    got = {r: len(box.by_role(r)) for r in list(exp) + ["sysop"]}
    got["sysop-watch"] = len(box.by_role("sysop-watch"))
    check("one of each long-lived process: %s" % got, all(got[r] == v for r, v in exp.items()) and got["sysop"] == 1 and got["sysop-watch"] in (0, 1))
    tb = tracebacks(box)
    check("no traceback in any log", not tb, tb[:4])
    states = box.goal_states()
    cur = (box.sysop_status() or {}).get("current")
    stuck = [g for g, st in states.items() if st.get("state") in ("running", "waiting_approval", "queued") and g != cur]
    check("no goal stuck in running, waiting or queued", not stuck, stuck[:5])
    try:
        lim, keep = audit_limits()
    except Exception:
        lim, keep = 16 << 20, 1
    audit_total = sum(size(os.path.join(box.sysop_state, f)) for f in os.listdir(box.sysop_state) if f.startswith("events.jsonl") and not f.endswith(".lock"))
    check("audit files within their bound: %.1f MiB (%d x %d MiB)" % (audit_total / 1048576.0, keep + 1, lim >> 20), audit_total <= lim * (keep + 1) + (2 << 20))
    for name, cap in (("serve.log", 1 << 20), ("bus.log", 1 << 20), ("web-terminal.log", 1 << 20), ("sysop/serve.log", 2 << 20)):
        check("log %s stays small: %d bytes" % (name, size(os.path.join(box.state, name))), size(os.path.join(box.state, name)) <= cap)
    check("goal folders pruned: %d" % len(states), len(states) <= 60)
    locks = len(os.listdir(os.path.join(RUN, "tabs"))) if os.path.isdir(os.path.join(RUN, "tabs")) else 0
    nwin = rep[0]
    check("tab lock files: %d for %d windows" % (locks, nwin), locks <= nwin + 70)
    runfiles = sorted(os.listdir(RUN))
    log("run folder: %s" % runfiles)
    socks = [f for f in runfiles if f.endswith(".sock")]
    check("sockets in the run folder: %s" % socks, socks == ["bus.sock"])
    return table


def write_csv(rows, path):
    """samples.csv: one line per sample, the numbers a person plots (RSS in KiB, descriptors, CPU ticks, sizes in bytes)"""
    cols = ["t", "procs", "zombies", "panels", "panels_rss", "goal_dirs", "state_bytes", "tab_locks", "run_entries"] + sorted(SAMPLE_FILES)
    keys = []
    for r in rows:
        for role in LONG_LIVED:
            for k in (role, role + "#2"):
                if k in r and k not in keys:
                    keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols + ["%s_%s" % (k, m) for k in keys for m in ("pid", "rss", "fds", "cpu")])
        for r in rows:
            line = [r["t"], r["procs"], r["zombies"], r["panels"]["n"], r["panels"]["rss"], r.get("goal_dirs"), r.get("state_bytes"), r.get("tab_locks"), r.get("run_entries")]
            line += [r["files"].get(k) for k in sorted(SAMPLE_FILES)]
            for k in keys:
                v = r.get(k) or {}
                line += [v.get("pid"), v.get("rss"), v.get("fds"), v.get("cpu")]
            w.writerow(line)


def save_logs(box):
    """the logs of the stack, to the results folder (the container's own disk goes away with it)"""
    d = os.path.join(RESULTS, "logs")
    os.makedirs(d, exist_ok=True)
    for name in ("serve.log", "bus.log", "web-terminal.log", "health", "sysop/serve.log", "sysop/serve.log.1"):
        text = read(os.path.join(box.state, name))
        if text:
            with open(os.path.join(d, name.replace("/", "-")), "w") as f:
                f.write(scrub(text))
    try:
        for f in sorted(os.listdir(box.sysop_state)):
            if f.startswith("events.jsonl") and not f.endswith(".lock"):
                with open(os.path.join(d, "audit-" + f), "w") as out:
                    out.write(scrub(read(os.path.join(box.sysop_state, f))[-200000:]))
    except OSError:
        pass


def box_scan_zombies(box):
    return [(r, p.pid, p.comm, p.ppid) for r, p in scan(box.entry.pid if box.entry else -1) if p.state == "Z"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=40.0)
    ap.add_argument("--faults", default="all")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--real", type=int, default=3, help="goals for the real claude (0 for none)")
    ap.add_argument("--quick", action="store_true", help="short phases around the faults (for debugging the harness)")
    ap.add_argument("--sample", type=float, default=10.0)
    args = ap.parse_args()
    if args.list:
        for n, f in FAULTS:
            print("%-22s %s" % (n, (f.__doc__ or "").strip()))
        return 0
    names = [n for n, _ in FAULTS] if args.faults == "all" else args.faults.split(",")
    unknown = [n for n in names if n not in dict(FAULTS)]
    if unknown:
        print("unknown faults: %s" % unknown)
        return 2
    os.makedirs(RESULTS, exist_ok=True)
    M = args.minutes * 60
    A, C, IDLE = (15, 20, 40) if args.quick else (0.18 * M, 0.12 * M, max(60, 0.12 * M))
    gap = 8 if args.quick else max(10, 0.02 * M)
    box = Stack(args.real)
    box.setup()
    if not box.start_entry():
        return 1
    sampler = Sampler(box, args.sample)
    sampler.start()
    box.make_windows(["w1", "w2", "w3"])
    box.tmux("select-window", "-t", "main:w1")
    wait_for(lambda: (lambda r: r[0] == r[1] == r[2])(box.panel_report()), 20, 0.5)
    check("setup: every window has a panel: %s" % (box.panel_report(),), (lambda r: r[0] == r[1] == r[2])(box.panel_report()))
    check("setup: the whole path works (probe goal)", probe_flow(box, 30)[0])
    load = Load(box)
    load.start()
    for i in range(1, min(args.real, 2) + 1):
        real_goal(box, i)
    log("phase A: steady load, no fault, %.0f s" % A)
    time.sleep(A)
    log("phase B: %d faults, %.0f s between" % (len(names), gap))
    for n in names:
        log("---- fault %s" % n)
        try:
            dict(FAULTS)[n](box, load)
        except Exception as e:
            import traceback
            log("fault %s raised: %s" % (n, traceback.format_exc()))
            row(n, "the harness failed: %r" % (e,), None, False)
        rep = heal(box)
        if rep:
            log("healed with: %s" % rep)
        time.sleep(gap)
    log("phase C: steady load, %.0f s, then idle %.0f s" % (C, IDLE))
    time.sleep(C)
    load.pause()
    for i in range(args.real, args.real + 1):
        if args.real > 2:
            real_goal(box, 3)
    wait_for(lambda: idle_state(box), 120, 0.5)
    time.sleep(10)
    idle_from = time.time() - T0
    time.sleep(IDLE)
    idle_to = time.time() - T0
    sampler.stop_flag.set()
    sampler.join(15)
    save_logs(box)
    log("final checks")
    table = final_checks(box, sampler, idle_from + 10, idle_to)
    ops = {}
    for t, op, res, secs in load.ops:
        ops.setdefault(op, {}).setdefault(res.split(":")[0], 0)
        ops[op][res.split(":")[0]] += 1
    log("steady load results: %s" % ops)
    goals = {}
    for g in box.goal_states().values():
        goals[g.get("state")] = goals.get(g.get("state"), 0) + 1
    log("goal folders by state at the end: %s" % goals)
    with open(os.path.join(RESULTS, "report.json"), "w") as f:
        json.dump({"faults": ROWS, "processes": table, "failed": FAILED, "load": ops, "seconds": round(time.time() - T0)}, f, indent=1)
    write_csv(sampler.rows, os.path.join(RESULTS, "samples.csv"))
    with open(os.path.join(RESULTS, "load.json"), "w") as f:
        json.dump(load.ops, f)
    print("\nFAULT TABLE")
    lines = ["| fault | what happened | recovery | result |", "|---|---|---|---|"]
    for r in ROWS:
        lines.append("| %s | %s | %s | %s |" % (r["fault"], r["what"], "-" if r["recovery_s"] is None else "%s s" % r["recovery_s"], "ok" if r["ok"] else "NOT OK" + ((" (" + r["note"][:80] + ")") if r["note"] else "")))
    print("\n".join(lines[2:]))
    with open(os.path.join(RESULTS, "report.md"), "w") as f:
        f.write(scrub("\n".join(lines) + "\n"))
    box.stop_entry()
    print("\n%s: %d failed %s after %.0f s" % ("FAIL" if FAILED else "PASS", len(FAILED), FAILED, time.time() - T0))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
