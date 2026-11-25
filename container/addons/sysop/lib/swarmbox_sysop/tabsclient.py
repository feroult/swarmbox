"""The sysop's use of the box capabilities: `swarmbox-tabs`, `swarmbox-state`, `swarmbox-worktree`, and `swarmbox-pins`
(all run as child commands with JSON output, never imported by path from host files).

  box_state(section)           -> {"schema": 1, "active", "repos": [...], "shells": [...], "parked": [...], ...}
  list_tabs()                  -> [{"tab": "t3", "label": "1:api", "index", "name", "dir", "cmd", "pane", "panes", "active"}]
  screen(tab, lines=None)      -> {"tab", "pane", "text", "cursor", "alternate", "in_mode", "mode", "size", "lines"}
  send(tab, run=T | input=T)   -> {"ok": true, "tab", "pane", "submitted"}
  open_tab(...) / focus_tab / rename_tab / close_tab / wake_pin / worktree

A failure is TabsError(code, msg), with the command's {"err", "msg"} or tabs_unavailable / tabs_timeout / tabs_protocol.
"""
import json
import os
import re
import shlex
import shutil
import subprocess

READ_TIMEOUT = 20.0        # list, screen, state: hc calls have a timeout of 5 s each inside the command
SEND_TIMEOUT = 120.0       # send: the lock wait (30 s), the pauses between keys and the check that the text left the input box
MAX_OUT = 4 << 20
ENV_CMD = "SWARMBOX_SYSOP_TABS_CMD"
ENV_STATE_CMD = "SWARMBOX_SYSOP_STATE_CMD"
ENV_WORKTREE_CMD = "SWARMBOX_SYSOP_WORKTREE_CMD"
ENV_PINS_CMD = "SWARMBOX_SYSOP_PINS_CMD"

_AGENT_CMDS = ("claude", "agy", "opencode", "codex", "gemini", "aider")
_SHELL_CMDS = ("bash", "sh", "zsh", "dash", "fish", "ksh", "ash", "-bash", "-sh", "-zsh")
_GENERIC_SHELL = re.compile(r"shell(?:-\d+)?", re.I)


class TabsError(Exception):
    """code is the command's err word, or tabs_unavailable / tabs_timeout / tabs_protocol."""

    def __init__(self, code, msg=""):
        Exception.__init__(self, "%s: %s" % (code, msg) if msg else code)
        self.code, self.msg = code, msg


def _fallback_display_name(t):
    title = str(t.get("title") or "").strip()
    if title:
        return title
    raw = str(t.get("name") or "").strip()
    if raw and not _GENERIC_SHELL.fullmatch(raw):
        return raw
    d = str(t.get("dir") or "").rstrip("/")
    if d and d not in ("~", "/", os.path.expanduser("~")):
        base = d.rsplit("/", 1)[-1]
        if base and base != "~":
            return base
    cmd = str(t.get("cmd") or "").strip()
    if cmd and cmd.lower() not in _SHELL_CMDS:
        return cmd
    return raw or "shell"


def _fallback_workspace_from_tabs(tabs_list):
    """Build the canonical workspace state dict from list_tabs() when swarmbox-state is not installed (e.g. unit tests)."""
    active = None
    repos = {}
    shells = []
    for t in tabs_list:
        if t.get("active"):
            active = t["tab"]
        lbl_ag = str(t.get("agent") or "").strip().lower()
        cmd = os.path.basename(str(t.get("cmd") or "").strip()).lstrip("-").lower()
        st = t.get("status") if isinstance(t.get("status"), dict) else {}
        app = str(st.get("app") or "").strip().lower()
        if lbl_ag in _AGENT_CMDS:
            ag = lbl_ag
        elif lbl_ag == "antigravity":
            ag = "agy"
        elif cmd in _AGENT_CMDS:
            ag = cmd
        elif app in _AGENT_CMDS:
            ag = app
        elif app == "antigravity":
            ag = "agy"
        else:
            ag = ""
        name = _fallback_display_name(t)
        d = str(t.get("dir") or "")
        if not ag:
            shells.append({"tab": t["tab"], "name": name, "dir": d, "cmd": str(t.get("cmd") or "bash")})
            continue
        wt = t.get("worktree") if isinstance(t.get("worktree"), dict) else None
        repo_path = str(wt.get("repo") or d or "~") if wt else (d or "~")
        repo_name = os.path.basename(repo_path.rstrip("/")) or repo_path
        grp = repos.setdefault(repo_path, {"name": repo_name, "path": repo_path, "agents": []})
        row = {"tab": t["tab"], "name": name, "agent": ag, "state": str(st.get("state") or "idle").lower()}
        if isinstance(st.get("progress"), (int, float)):
            row["progress"] = int(st["progress"])
        if st.get("msg"):
            row["msg"] = str(st["msg"])[:120]
        if wt and wt.get("branch"):
            row["branch"] = str(wt["branch"])
            wt_id = os.path.basename(str(wt.get("path") or "").rstrip("/")) or str(wt["branch"])
            row["worktree"] = wt_id
        grp["agents"].append(row)
    out = {"schema": 1}
    if active:
        out["active"] = active
    out["repos"] = list(repos.values())
    if shells:
        out["shells"] = shells
    return out


def _fallback_system(env):
    """Minimal read-only system snapshot when swarmbox-state is not installed."""
    home = (env.get("HOME") or os.path.expanduser("~"))
    resources = {}
    try:
        du = shutil.disk_usage(home)
        resources["disk_free_gb"] = round(du.free / (1024 ** 3), 2)
        resources["disk_total_gb"] = round(du.total / (1024 ** 3), 2)
        resources["disk_used_pct"] = round((du.used / du.total) * 100, 1) if du.total else 0
    except OSError:
        pass
    try:
        mem = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("MemTotal:", "MemAvailable:"):
                    mem[parts[0][:-1]] = int(parts[1])
        if "MemTotal" in mem:
            resources["mem_avail_mb"] = round(mem.get("MemAvailable", 0) / 1024)
            resources["mem_total_mb"] = round(mem["MemTotal"] / 1024)
    except OSError:
        pass
    addons = set()
    for tok in (env.get("SWARMBOX_WITH") or "").replace(",", " ").split():
        if tok:
            addons.add(tok)
    adir = os.path.join(home, ".local", "share", "swarmbox", "addons")
    try:
        for entry in os.listdir(adir):
            if os.path.isdir(os.path.join(adir, entry)):
                addons.add(entry)
    except OSError:
        pass
    containers = []
    podman = shutil.which("podman", path=env.get("PATH"))
    if podman:
        try:
            p = subprocess.run([podman, "ps", "--format", "json"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3.0)
            if p.returncode == 0:
                raw = json.loads(p.stdout.decode("utf-8", "replace") or "[]")
                if isinstance(raw, list):
                    for c in raw[:12]:
                        names = c.get("Names") or []
                        containers.append({
                            "name": str(names[0] if isinstance(names, list) and names else names)[:40],
                            "image": str(c.get("Image") or "")[:60],
                            "state": str(c.get("State") or "")[:20],
                        })
        except Exception:
            pass
    out = {"schema": 1, "mux": env.get("SWARMBOX_MUX") or "herdr", "health": {"ready": "unknown"}, "addons": sorted(addons), "containers": containers}
    if resources:
        out["resources"] = resources
    return out


class Tabs:
    def __init__(self, cmd=None, env=None, read_timeout=READ_TIMEOUT, send_timeout=SEND_TIMEOUT):
        e = os.environ if env is None else env
        self.cmd = list(cmd) if cmd else shlex.split(e.get(ENV_CMD) or "swarmbox-tabs")
        self.env = dict(e)
        self.read_timeout, self.send_timeout = read_timeout, send_timeout

    def _run_json(self, argv, stdin=None, timeout=None, label="swarmbox-tabs"):
        try:
            p = subprocess.run(argv, input=(stdin.encode("utf-8", "replace") if stdin is not None else b""), env=self.env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout or self.read_timeout)
        except subprocess.TimeoutExpired:
            raise TabsError("tabs_timeout", "%s did not answer in %g s" % (label, timeout or self.read_timeout))
        except OSError as e:
            raise TabsError("tabs_unavailable", "cannot run %s: %s" % (argv[0], e.strerror or e))
        out = p.stdout[:MAX_OUT]
        try:
            obj = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
            raise TabsError("tabs_protocol", "%s exited %d and printed no JSON (%s)" % (label, p.returncode, tail[0][:200]))
        if isinstance(obj, dict) and "err" in obj:
            raise TabsError(str(obj["err"]), str(obj.get("msg", "")))
        if p.returncode != 0:
            raise TabsError("tabs_protocol", "%s exited %d without an error object" % (label, p.returncode))
        return obj

    def call(self, args, stdin=None, timeout=None):
        """Run swarmbox-tabs; return parsed JSON or raise TabsError."""
        return self._run_json(self.cmd + list(args), stdin=stdin, timeout=timeout, label="swarmbox-tabs")

    def box_state(self, section="workspace"):
        """Canonical box state via swarmbox-state (falls back to list_tabs/local stats when swarmbox-state is absent)."""
        sec = str(section or "workspace").strip().lower()
        explicit = self.env.get(ENV_STATE_CMD)
        state_bin = shlex.split(explicit) if explicit else (["swarmbox-state"] if shutil.which("swarmbox-state", path=self.env.get("PATH")) else None)
        if state_bin:
            return self._run_json(state_bin + ["--section", sec], timeout=self.read_timeout, label="swarmbox-state")
        if sec == "system":
            return _fallback_system(self.env)
        ws = _fallback_workspace_from_tabs(self.list_tabs())
        if sec == "all":
            sys_part = _fallback_system(self.env)
            ws["system"] = {k: v for k, v in sys_part.items() if k != "schema"}
        return ws

    def list_tabs(self):
        res = self.call(["list"])
        if not isinstance(res, list):
            raise TabsError("tabs_protocol", "list did not give a list")
        return [t for t in res if isinstance(t, dict) and isinstance(t.get("tab"), str)]

    def screen(self, tab, lines=None):
        args = ["screen", tab]
        if lines:
            args += ["--lines", str(int(lines))]
        res = self.call(args)
        if not isinstance(res, dict) or not isinstance(res.get("text"), str):
            raise TabsError("tabs_protocol", "screen did not give a screen")
        return res

    def send(self, tab, run=None, input=None):
        """Type `run` and press Enter, or type `input` as it is ({Esc} {C-c} {Enter} ... are keys). A `run` is always sent with --queue."""
        if (run is None) == (input is None):
            raise TabsError("usage", "send takes run or input")
        text = run if run is not None else input
        args = ["send", tab, "--run" if run is not None else "--input", "-"] + (["--queue"] if run is not None else [])
        return self.call(args, stdin=text + "\n", timeout=self.send_timeout)

    def open_tab(self, name=None, cwd=None, agent=None, worktree=False, title=None, pin_id=None):
        args = ["open"]
        if name:
            args += ["--name", str(name)]
        if cwd:
            args += ["--cwd", str(cwd)]
        if agent:
            args += ["--agent", str(agent)]
        if title:
            args += ["--title", str(title)]
        if pin_id:
            args += ["--pin-id", str(pin_id)]
        if worktree:
            args += ["--worktree"]
        return self.call(args)

    def rename_tab(self, tab, title, source="auto"):
        return self.call(["rename", str(tab), str(title), "--source", str(source)])

    def list_pins(self):
        pcmd = shlex.split(self.env.get(ENV_PINS_CMD) or "swarmbox-pins")
        try:
            res = self._run_json(pcmd + ["list"], timeout=5.0, label="swarmbox-pins")
            return res if isinstance(res, list) else []
        except TabsError:
            return []

    def worktree(self, action, path=None, clean=False, force=False):
        wt_cmd = shlex.split(self.env.get(ENV_WORKTREE_CMD) or "swarmbox-worktree")
        args = [str(action)]
        if path is not None:
            args.append(str(path))
        if action == "merge" and clean:
            args.append("--clean")
        if action == "remove" and force:
            args.append("--force")
        return self._run_json(wt_cmd + args, timeout=self.read_timeout, label="swarmbox-worktree")

    def focus_tab(self, tab):
        return self.call(["focus", str(tab)])

    def close_tab(self, tab):
        return self.call(["close", str(tab)])
