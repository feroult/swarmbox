"""Native OSC 7501 agent bridge for herdr-core (`swarmbox-sysop agent` and `HerdrBridge`).

Publishes the resident SwarmBox Sysop as a first-class interactive agent terminal inside `herdr-core`
with label `swarmbox.role=sysop`:
  - SwarmBox Web UI, Terminal Cockpit, and `swarmbox-tabs` hide `swarmbox.role=sysop` terminals so
    Sysop never duplicates as a regular tab and never operates on itself.
  - External `herdr-app` clients (or `hc ls`) see `sysop` natively in their Agent Inbox with live
    OSC 7501 state updates (`idle`, `working`, `blocked:permission`, `done`, `error`) and can send
    goals or approve/veto actions directly.

Pure Python standard library; no import of any terminal UI.
"""
import base64
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import threading
import time

from . import actions, busclient, paths, service, state

SYSOP_ROLE_KEY = "swarmbox.role"
SYSOP_ROLE_VALUE = "sysop"
SYSOP_TERMINAL_NAME = "sysop"

TEMPLATE_CONTENT = """---
name: sysop
description: SwarmBox Sysop orchestrator (routes goals across live box terminals with risk approvals)
command: ["swarmbox-sysop", "agent"]
---
You are talking directly to the SwarmBox Sysop. Send a natural-language goal for any terminal
in this SwarmBox, or reply `y`/`n` when Sysop asks for approval on a guarded action.
"""


def osc_status(sysop_state, msg=""):
    """Return the verified herdr-core OSC 7501 sequence for a `state.line_of` state name.

    When `msg` is non-empty, encodes it as base64 in `:msg=<b64>` per the herdr-core OSC 7501 spec
    so herdr-app displays the live human-readable sentence directly in its Agent Inbox.
    """
    if sysop_state in ("allow?", "sending"):
        body = "state=blocked:kind=permission"
    elif sysop_state in ("working", "queued"):
        body = "state=working"
    elif sysop_state == "done":
        body = "state=done"
    elif sysop_state in ("failed", "stopped"):
        body = "state=error"
    else:
        body = "state=idle"
    clean_msg = state.one_line(msg, 120) if msg else ""
    if clean_msg:
        b64 = base64.b64encode(clean_msg.encode("utf-8")).decode("ascii")
        body += ":msg=" + b64
    return "\x1b]7501;%s\x07" % body


def osc_title(sysop_state, sentence=""):
    """Return an OSC 0 terminal title string safe for terminal output."""
    clean_sent = state.one_line(sentence, 72) if sentence else ""
    label = "sysop · %s" % sysop_state + ((" — " + clean_sent) if clean_sent else "")
    return "\x1b]0;%s\x07" % label


def config_root(env=None):
    e = os.environ if env is None else env
    xdg = e.get("XDG_CONFIG_HOME") or ""
    if xdg.startswith("/"):
        return xdg.rstrip("/")
    return os.path.join(e.get("HOME") or os.path.expanduser("~"), ".config")


def seed_template(env=None):
    """Seed `~/.config/herdr-core/templates/sysop.md` once without overwriting user edits."""
    tpl_dir = os.path.join(config_root(env), "herdr-core", "templates")
    tpl_path = os.path.join(tpl_dir, "sysop.md")
    if os.path.exists(tpl_path):
        return tpl_path
    try:
        os.makedirs(tpl_dir, exist_ok=True)
        with open(tpl_path, "w", encoding="utf-8") as f:
            f.write(TEMPLATE_CONTENT)
    except OSError:
        return None
    return tpl_path


def handle_line(raw_line, pth, bus, out=None, wall=None):
    """Process one line typed into the Sysop agent terminal. Returns `(ok, message)`."""
    stream = sys.stdout if out is None else out
    line = (raw_line or "").strip()
    if not line:
        return True, ""

    low = line.lower()
    _, pending = actions.pending_of(pth)
    if pending and actions.is_live(pending, wall=wall):
        if low in ("y", "yes", "allow", "approve", "ok"):
            res = actions.approve(pth, by="agent", wall=wall)
            stream.write("[sysop] %s\n" % res.message)
            stream.flush()
            return res.ok, res.message
        if low in ("n", "no", "veto", "deny", "reject", "cancel"):
            res = actions.veto(pth, by="agent", wall=wall)
            stream.write("[sysop] %s\n" % res.message)
            stream.flush()
            return res.ok, res.message

    if low in ("/stop", "stop"):
        res = actions.stop(pth)
        stream.write("[sysop] %s\n" % res.message)
        stream.flush()
        return res.ok, res.message

    if low == "/status":
        snap = state.snapshot(pth)
        ln = state.line_of(snap, time.time() if wall is None else wall)
        st_name, sent = ln if ln else ("off", "service not running")
        stream.write("[sysop] status=%s%s\n" % (st_name, (" · " + sent) if sent else ""))
        stream.flush()
        return snap.up, st_name

    if low in ("/help", "help"):
        stream.write("[sysop] Type any goal and press Enter. Reply y/n on approval prompts. /status /stop\n")
        stream.flush()
        return True, "help"

    try:
        gid, _ = actions.publish_goal(bus, line, source="agent")
    except (ValueError, busclient.BusError) as e:
        msg = "could not publish goal: %s" % e
        stream.write("[sysop] %s\n" % msg)
        stream.flush()
        return False, msg
    except Exception as e:
        msg = "error: %s" % e
        stream.write("[sysop] %s\n" % msg)
        stream.flush()
        return False, msg

    stream.write("[sysop] goal %s accepted\n" % gid)
    stream.flush()
    return True, gid


def run_agent(pth=None, bus=None, poll=0.4):
    """Run the interactive OSC 7501 Sysop agent bridge until EOF or SIGTERM/SIGINT."""
    pth = pth or paths.Paths()
    bus = bus or busclient.Bus()
    stop_flag = [False]

    def _stop(*_):
        stop_flag[0] = True

    for sg in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sg, _stop)
        except (ValueError, OSError):
            pass

    sys.stdout.write("SwarmBox Sysop agent ready. Type a goal, or reply y/n to approvals. (/status, /stop)\n")
    sys.stdout.write(osc_status("idle") + osc_title("idle"))
    sys.stdout.flush()

    last_gid = ""
    last_osc = None
    seen_calls = {}
    seen_says = {}
    seen_pending = set()
    seen_end = set()
    in_buf = ""

    stdin_fd = None
    try:
        stdin_fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        stdin_fd = None

    while not stop_flag[0]:
        now = time.time()
        snap = state.snapshot(pth, last_gid=last_gid or None)
        if snap.gid:
            last_gid = snap.gid
        ln = state.line_of(snap, now)
        st_name, sent = ln if ln else ("off", "")

        osc_key = (st_name, sent)
        if osc_key != last_osc:
            sys.stdout.write(osc_status(st_name, sent) + osc_title(st_name, sent))
            sys.stdout.flush()
            last_osc = osc_key

        if snap.goal and snap.gid:
            gid = snap.gid
            calls = snap.goal.get("calls") or []
            prev_c = seen_calls.get(gid, 0)
            for c in calls[prev_c:]:
                if isinstance(c, dict) and c.get("tool") != "done":
                    sys.stdout.write("  · %s\n" % state.step_text(c))
            seen_calls[gid] = len(calls)

            says = snap.goal.get("say") or []
            prev_s = seen_says.get(gid, 0)
            for s in says[prev_s:]:
                if isinstance(s, dict) and s.get("text"):
                    sys.stdout.write("  ✓ %s\n" % state.one_line(s.get("text"), 300))
            seen_says[gid] = len(says)

            if snap.pending and snap.pending.get("id"):
                pid = "%s:%s" % (gid, snap.pending.get("id"))
                if pid not in seen_pending:
                    seen_pending.add(pid)
                    mode = "SENDING (veto?)" if snap.pending.get("mode") == "veto" else "ALLOW?"
                    sys.stdout.write("\n[sysop %s] %s\nReply `y` to allow or `n` to veto.\n" % (
                        mode, state.one_line(snap.pending.get("text"), 300),
                    ))

            gstate = snap.goal.get("state")
            if gstate in state.TERMINAL and gid not in seen_end:
                seen_end.add(gid)
                summary = snap.goal.get("summary") or snap.goal.get("error") or gstate
                sys.stdout.write("[sysop %s] %s\n" % (gstate, state.one_line(summary, 400)))
            sys.stdout.flush()

        if stdin_fd is not None:
            try:
                ready, _, _ = select.select([stdin_fd], [], [], poll)
            except (InterruptedError, OSError, ValueError):
                ready = []
            if ready:
                try:
                    chunk = os.read(stdin_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                in_buf += chunk.decode("utf-8", "replace")
                while "\n" in in_buf or "\r" in in_buf:
                    sep = "\n" if "\n" in in_buf else "\r"
                    line, in_buf = in_buf.split(sep, 1)
                    handle_line(line, pth, bus, out=sys.stdout)
        else:
            time.sleep(poll)

    sys.stdout.write(osc_status("idle"))
    sys.stdout.flush()
    return 0


class HerdrBridge:
    """Maintains one persistent `swarmbox-sysop agent` terminal inside herdr-core (labeled swarmbox.role=sysop).

    Started by `ui_host.start_ui()` when SWARMBOX_MUX=herdr. Idempotent and non-fatal if herdr-core
    is temporarily absent.
    """

    def __init__(self, pth, log=None, hc_bin=None, sysop_bin=None, interval=3.0, env=None):
        self.pth = pth
        self.log = log
        self.hc_bin = hc_bin or os.environ.get("SWARMBOX_TEST_HC_BIN") or "hc"
        self.sysop_bin = sysop_bin or os.environ.get("SWARMBOX_TEST_SYSOP_BIN") or shutil.which("swarmbox-sysop") or "swarmbox-sysop"
        self.interval = interval
        self.env = env
        self._stop = threading.Event()
        self._thread = None

    def _log(self, msg):
        if self.log:
            try:
                self.log(msg)
            except Exception:
                pass

    def ensure_once(self):
        """Ensure the template exists and a single live `swarmbox.role=sysop` terminal is running. Returns True when ensured."""
        seed_template(self.env)
        env = os.environ if self.env is None else self.env
        try:
            ls = subprocess.run(
                [self.hc_bin, "ls", "--json", "--label", "%s=%s" % (SYSOP_ROLE_KEY, SYSOP_ROLE_VALUE)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=4.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if ls.returncode != 0:
            return False
        try:
            data = json.loads(ls.stdout.decode("utf-8", "replace") or "{}")
        except ValueError:
            return False
        for t in data.get("terminals") or []:
            if not isinstance(t, dict) or t.get("state", "live") != "live":
                continue
            labels = t.get("labels")
            if labels is None or (isinstance(labels, dict) and labels.get(SYSOP_ROLE_KEY) == SYSOP_ROLE_VALUE):
                return True

        argv = [
            self.hc_bin, "run", "--bg", "--keep", "--no-parent",
            "--name", SYSOP_TERMINAL_NAME,
            "--label", "%s=%s" % (SYSOP_ROLE_KEY, SYSOP_ROLE_VALUE),
            "--", self.sysop_bin, "agent",
        ]
        try:
            res = subprocess.run(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=5.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if res.returncode == 0:
            self._log("sysop herdr-bridge: published native OSC 7501 sysop agent terminal")
            return True
        return False

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="sysop-herdr-bridge", daemon=True)
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            self.ensure_once()
            self._stop.wait(self.interval)

    def shutdown(self):
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
