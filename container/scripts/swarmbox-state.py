#!/usr/bin/python3 -S
"""swarmbox-state: canonical read-only world model of a SwarmBox (CLI and library, Python stdlib only).

Composes live terminals (swarmbox-tabs), parked sessions (swarmbox-pins), git worktrees (swarmbox-worktree),
workspace git repositories, installed agents/addons, and box health/resources into one compact JSON snapshot
matching the SwarmBox UI model: repos -> agents & pending_worktrees, shells, parked, and system diagnostics.

  swarmbox-state [--section workspace|system|all]

Output: JSON on stdout. Failures print {"err": CODE, "msg": TEXT} and exit non-zero.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SCHEMA = 1
AGENT_COMMANDS = ("claude", "agy", "opencode", "codex", "gemini", "aider")
# Other names of an agent: what it reports as its OSC 7501 `app` (Claude Code says claude-code) and the addon name of agy.
AGENT_ALIASES = {"claude-code": "claude", "antigravity": "agy"}
SHELL_COMMANDS = ("bash", "sh", "zsh", "dash", "fish", "ksh", "ash", "-bash", "-sh", "-zsh")
SKIP_SCAN_DIRS = frozenset({"node_modules", ".git", "venv", ".venv", "dist", "build", "target", "__pycache__"})
_GENERIC_SHELL = re.compile(r"shell(?:-\d+)?", re.I)
CMD_TIMEOUT = 10.0
PODMAN_TIMEOUT = 3.0
MAX_OUT = 4 << 20
EXIT = {"usage": 2, "no_session": 4, "no_backend": 4, "timeout": 5}


class StateError(Exception):
    def __init__(self, code, message=""):
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def _xdg(env, var, fallback_rel):
    home = (env.get("HOME") or os.path.expanduser("~")).rstrip("/") or "/"
    v = (env.get(var) or "").strip()
    base = (v.rstrip("/") or "/") if v.startswith("/") else os.path.join(home, fallback_rel)
    return os.path.join(base, "swarmbox")


def _run_json_cmd(cmd, args, env, timeout=CMD_TIMEOUT):
    argv = list(cmd) + list(args)
    try:
        p = subprocess.run(argv, input=b"", env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise StateError("timeout", "%s did not answer in %g s" % (argv[0], timeout))
    except OSError as e:
        raise StateError("unavailable", "cannot run %s: %s" % (argv[0], e.strerror or e))
    out = p.stdout[:MAX_OUT]
    try:
        obj = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        raise StateError("protocol", "%s exited %d (%s)" % (argv[0], p.returncode, tail[0][:160]))
    if isinstance(obj, dict) and "err" in obj:
        raise StateError(str(obj["err"]), str(obj.get("msg", "")))
    if p.returncode != 0:
        raise StateError("protocol", "%s exited %d" % (argv[0], p.returncode))
    return obj


def _norm_real(p):
    if not p or not isinstance(p, str):
        return ""
    p = os.path.expanduser(p)
    if not p.startswith("/"):
        return ""
    try:
        return os.path.realpath(p)
    except OSError:
        return p.rstrip("/") or "/"


def _short_dir(path, home):
    if not path:
        return ""
    p = str(path)
    h = (home or "").rstrip("/")
    if h and (p == h or p.startswith(h + "/")):
        return "~" + p[len(h):]
    return p


def _read_git_branch(git_dir):
    try:
        with open(os.path.join(git_dir, "HEAD"), encoding="utf-8", errors="replace") as f:
            head = f.readline().strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    if head.startswith("ref: "):
        return head[5:]
    return head[:8] if head else ""


def _resolve_git_info(dir_path):
    """Fast pure-Python git repo/worktree detector (no subprocesses).
    Returns {"root": str, "name": str, "branch": str, "is_worktree": bool} or None."""
    cur = _norm_real(dir_path)
    if not cur or not os.path.isdir(cur):
        return None
    while True:
        dot_git = os.path.join(cur, ".git")
        if os.path.isdir(dot_git):
            return {
                "root": cur,
                "name": os.path.basename(cur) or cur,
                "branch": _read_git_branch(dot_git) or "main",
                "is_worktree": False,
            }
        if os.path.isfile(dot_git):
            try:
                with open(dot_git, encoding="utf-8", errors="replace") as f:
                    line = f.readline().strip()
            except OSError:
                line = ""
            if line.startswith("gitdir:"):
                gd = line[7:].strip()
                if not os.path.isabs(gd):
                    gd = os.path.normpath(os.path.join(cur, gd))
                branch = _read_git_branch(gd)
                # For a worktree, commondir points to the main .git folder.
                root = cur
                try:
                    with open(os.path.join(gd, "commondir"), encoding="utf-8", errors="replace") as cf:
                        cd = cf.readline().strip()
                    if cd:
                        common = os.path.normpath(os.path.join(gd, cd))
                        if os.path.basename(common) == ".git":
                            root = os.path.dirname(common)
                except OSError:
                    pass
                return {
                    "root": root,
                    "name": os.path.basename(root) or root,
                    "branch": branch,
                    "is_worktree": True,
                }
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def display_name(t, home=""):
    """Canonical display name of a tab (matches Web Studio tabTitleParts & Sysop display_name)."""
    title = str(t.get("title") or "").strip()
    if title:
        return title
    raw = str(t.get("name") or "").strip()
    if raw and not _GENERIC_SHELL.fullmatch(raw):
        return raw
    d = str(t.get("dir") or "").rstrip("/")
    h = (home or os.path.expanduser("~")).rstrip("/")
    if d and d not in ("~", "/", h):
        base = d.rsplit("/", 1)[-1]
        if base and base != "~":
            return base
    cmd = str(t.get("cmd") or "").strip()
    if cmd and cmd.lower() not in SHELL_COMMANDS:
        return cmd
    return raw or "shell"


def detect_agent(t):
    """Return canonical agent name (claude, agy, opencode, codex, gemini, aider) or '' for a shell."""
    st = t.get("status")
    app = str(st.get("app") or "") if isinstance(st, dict) else ""
    for raw in (t.get("agent"), os.path.basename(str(t.get("cmd") or "").strip()).lstrip("-"), app):
        name = str(raw or "").strip().lower()
        name = AGENT_ALIASES.get(name, name)
        if name in AGENT_COMMANDS:
            return name
    return ""


def _installed_agents(env, data_dir):
    found = set()
    for tok in (env.get("SWARMBOX_WITH") or "").replace(",", " ").split():
        if tok == "antigravity":
            found.add("agy")
        elif tok in AGENT_COMMANDS:
            found.add(tok)
    adir = os.path.join(data_dir, "addons")
    try:
        for entry in os.listdir(adir):
            if os.path.isdir(os.path.join(adir, entry)):
                if entry == "antigravity":
                    found.add("agy")
                elif entry in AGENT_COMMANDS:
                    found.add(entry)
    except OSError:
        pass
    path_env = env.get("PATH") or ""
    for ag in ("claude", "agy", "opencode", "codex", "gemini"):
        if shutil.which(ag, path=path_env):
            found.add(ag)
    return sorted(found)


def _discover_workspace_repos(home):
    """Scan HOME (depth 1..2) for git repositories, matching server.mjs discoverProjects."""
    repos = {}
    if not home or not os.path.isdir(home):
        return repos

    def scan(base, depth):
        try:
            entries = list(os.scandir(base))
        except OSError:
            return
        for ent in entries:
            name = ent.name
            if not name or name.startswith(".") or name in SKIP_SCAN_DIRS:
                continue
            try:
                if not ent.is_dir(follow_symlinks=True):
                    continue
            except OSError:
                continue
            full = ent.path
            if os.path.isdir(os.path.join(full, ".git")):
                rp = _norm_real(full)
                if rp and rp not in repos:
                    repos[rp] = {
                        "name": os.path.basename(rp) or name,
                        "path": rp,
                        "branch": _read_git_branch(os.path.join(rp, ".git")) or "main",
                        "git": True,
                    }
            elif depth < 2:
                scan(full, depth + 1)

    scan(home, 1)
    return repos


def build_workspace(env=None, tabs_list=None, pins_list=None, worktrees_list=None):
    """Build the compact workspace state: active, repos (with agents & pending_worktrees), shells, parked, installed_agents."""
    e = os.environ if env is None else env
    home = (e.get("HOME") or os.path.expanduser("~")).rstrip("/") or "/"
    data_dir = _xdg(e, "XDG_DATA_HOME", ".local/share")

    if tabs_list is None:
        tcmd = shlex.split(e.get("SWARMBOX_STATE_TABS_CMD") or e.get("SWARMBOX_SYSOP_TABS_CMD") or "swarmbox-tabs")
        tabs_list = _run_json_cmd(tcmd, ["list"], e)
        if not isinstance(tabs_list, list):
            raise StateError("protocol", "swarmbox-tabs list did not return a list")

    if pins_list is None:
        pcmd = shlex.split(e.get("SWARMBOX_STATE_PINS_CMD") or "swarmbox-pins")
        try:
            raw_pins = _run_json_cmd(pcmd, ["list"], e, timeout=5.0)
            pins_list = raw_pins if isinstance(raw_pins, list) else []
        except StateError:
            pins_list = []

    if worktrees_list is None:
        wcmd = shlex.split(e.get("SWARMBOX_STATE_WORKTREE_CMD") or e.get("SWARMBOX_SYSOP_WORKTREE_CMD") or "swarmbox-worktree")
        try:
            raw_wt = _run_json_cmd(wcmd, ["list"], e, timeout=5.0)
            worktrees_list = raw_wt if isinstance(raw_wt, list) else []
        except StateError:
            worktrees_list = []

    # 1. Discover git repos in HOME
    repo_map = {}  # key (realpath) -> repo entry
    for rp, meta in _discover_workspace_repos(home).items():
        repo_map[rp] = {
            "name": meta["name"],
            "path": meta["path"],
            "branch": meta["branch"],
            "git": True,
            "agents": [],
            "pending_worktrees": [],
        }

    active_tab = None
    live_pin_ids = set()
    live_wt_paths = set()
    shells = []

    # 2. Classify live tabs into repo-grouped agents vs plain shells
    for t in tabs_list:
        if not isinstance(t, dict) or not isinstance(t.get("tab"), str):
            continue
        tid = t["tab"]
        if t.get("active"):
            active_tab = tid
        if t.get("pin_id"):
            live_pin_ids.add(str(t["pin_id"]))
        wt = t.get("worktree") if isinstance(t.get("worktree"), dict) else None
        if wt and wt.get("path"):
            live_wt_paths.add(_norm_real(wt["path"]))
        tab_dir = str(t.get("dir") or "")
        tab_dir_real = _norm_real(tab_dir)
        if tab_dir_real:
            live_wt_paths.add(tab_dir_real)

        ag = detect_agent(t)
        name = display_name(t, home)
        if not ag:
            shells.append({
                "tab": tid,
                "name": name,
                "dir": _short_dir(tab_dir, home),
                "cmd": str(t.get("cmd") or "bash"),
            })
            continue

        # Resolve repo group for this agent
        repo_root = ""
        repo_branch = ""
        is_git = False
        if wt and wt.get("repo"):
            repo_root = _norm_real(wt["repo"]) or str(wt["repo"])
            is_git = True
            repo_branch = _read_git_branch(os.path.join(repo_root, ".git")) or wt.get("base") or "main"
        else:
            ginfo = _resolve_git_info(tab_dir)
            if ginfo:
                repo_root = ginfo["root"]
                repo_branch = ginfo["branch"]
                is_git = True
            else:
                repo_root = tab_dir_real or tab_dir or home
                is_git = False

        grp = repo_map.get(repo_root)
        if grp is None:
            grp = {
                "name": os.path.basename(repo_root.rstrip("/")) or _short_dir(repo_root, home) or "~",
                "path": repo_root,
                "git": is_git,
                "agents": [],
                "pending_worktrees": [],
            }
            if is_git and repo_branch:
                grp["branch"] = repo_branch
            repo_map[repo_root] = grp

        st = t.get("status") if isinstance(t.get("status"), dict) else {}
        state = str(st.get("state") or "idle").lower()
        agent_row = {
            "tab": tid,
            "name": name,
            "agent": ag,
            "state": state,
        }
        if isinstance(st.get("progress"), (int, float)):
            agent_row["progress"] = int(st["progress"])
        if st.get("msg"):
            agent_row["msg"] = str(st["msg"])[:120]
        if wt and wt.get("branch"):
            agent_row["branch"] = str(wt["branch"])
            wt_id = os.path.basename(str(wt.get("path") or "").rstrip("/")) or str(wt["branch"])
            agent_row["worktree"] = wt_id
        elif is_git and repo_branch:
            agent_row["branch"] = repo_branch
        grp["agents"].append(agent_row)

    # 3. Parked sessions (pins not currently live)
    parked = []
    parked_paths = set()
    for p in pins_list:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        pid = str(p["id"])
        if pid in live_pin_ids:
            continue
        cwd = str(p.get("cwd") or "")
        pwt = p.get("worktree") if isinstance(p.get("worktree"), dict) else None
        if pwt and pwt.get("path"):
            parked_paths.add(_norm_real(pwt["path"]))
        if cwd:
            parked_paths.add(_norm_real(cwd))
        row = {
            "id": pid,
            "title": str(p.get("title") or os.path.basename(cwd.rstrip("/")) or pid),
            "agent": str(p.get("agent") or "shell"),
            "cwd": _short_dir(cwd, home),
        }
        if p.get("resume"):
            row["resume"] = str(p["resume"])
        if pwt and pwt.get("branch"):
            row["worktree"] = str(pwt["branch"])
        parked.append(row)

    # 4. Pending (detached) worktrees grouped under their repo
    for w in worktrees_list:
        if not isinstance(w, dict) or not w.get("path"):
            continue
        wp = _norm_real(w["path"])
        if wp in live_wt_paths or wp in parked_paths:
            continue
        repo_root = _norm_real(w.get("repo_root") or w.get("repo") or "")
        if not repo_root:
            ginfo = _resolve_git_info(w["path"])
            repo_root = ginfo["root"] if ginfo else ""
        if not repo_root:
            continue
        grp = repo_map.get(repo_root)
        if grp is None:
            grp = {
                "name": str(w.get("repo_name") or os.path.basename(repo_root.rstrip("/")) or repo_root),
                "path": repo_root,
                "git": True,
                "branch": _read_git_branch(os.path.join(repo_root, ".git")) or "main",
                "agents": [],
                "pending_worktrees": [],
            }
            repo_map[repo_root] = grp
        wt_entry = {
            "id": str(w.get("id") or os.path.basename(wp.rstrip("/"))),
            "path": wp,
            "branch": str(w.get("branch") or ""),
            "base": str(w.get("base") or "main"),
        }
        if "dirty" in w:
            wt_entry["dirty"] = bool(w["dirty"])
        if "can_merge" in w:
            wt_entry["can_merge"] = bool(w["can_merge"])
        grp["pending_worktrees"].append(wt_entry)

    # 5. Clean & sort repos: repos with active agents/pending worktrees first, then alphabetical
    repos = []
    for grp in sorted(repo_map.values(), key=lambda g: (0 if (g["agents"] or g["pending_worktrees"]) else 1, g["name"].lower())):
        item = {"name": grp["name"], "path": grp["path"]}
        if not grp.get("git", True):
            item["git"] = False
        elif grp.get("branch"):
            item["branch"] = grp["branch"]
        item["agents"] = grp["agents"]
        if grp["pending_worktrees"]:
            item["pending_worktrees"] = grp["pending_worktrees"]
        repos.append(item)

    out = {"schema": SCHEMA}
    if active_tab:
        out["active"] = active_tab
    out["repos"] = repos
    if shells:
        out["shells"] = shells
    if parked:
        out["parked"] = parked
    agents_avail = _installed_agents(e, data_dir)
    if agents_avail:
        out["installed_agents"] = agents_avail
    return out


def build_system(env=None):
    """Build the on-demand system diagnostics snapshot: health, resources, addons, mcp, containers."""
    e = os.environ if env is None else env
    home = (e.get("HOME") or os.path.expanduser("~")).rstrip("/") or "/"
    run_dir = (e.get("SB_RUN_DIR") or "/tmp/swarmbox").rstrip("/")
    state_dir = (e.get("SB_STATE_DIR") or _xdg(e, "XDG_STATE_HOME", ".local/state")).rstrip("/")
    data_dir = _xdg(e, "XDG_DATA_HOME", ".local/share")
    cfg_dir = _xdg(e, "XDG_CONFIG_HOME", ".config")

    # Health
    ready = "unknown"
    try:
        with open(os.path.join(run_dir, "ready"), encoding="utf-8", errors="replace") as f:
            ready = f.read().strip() or "ok"
    except OSError:
        pass
    warnings = []
    try:
        with open(os.path.join(state_dir, "health"), encoding="utf-8", errors="replace") as f:
            warnings = [ln.strip() for ln in f if ln.strip()][:10]
    except OSError:
        pass
    bus_up = os.path.exists(e.get("SB_BUS_SOCKET") or os.path.join(run_dir, "bus.sock"))
    sysop_up = os.path.exists(os.path.join(run_dir, "sysop", "status.json"))
    health = {"ready": ready, "bus": "up" if bus_up else "down", "sysop": "up" if sysop_up else "down"}
    if warnings:
        health["warnings"] = warnings

    # Resources (disk + memory)
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

    # Addons
    addons = set()
    for tok in (e.get("SWARMBOX_WITH") or "").replace(",", " ").split():
        if tok:
            addons.add(tok)
    adir = os.path.join(data_dir, "addons")
    try:
        for entry in os.listdir(adir):
            if os.path.isdir(os.path.join(adir, entry)):
                addons.add(entry)
    except OSError:
        pass

    # MCP servers
    mcp = set()
    for base in (os.path.join(cfg_dir, "mcp"), "/etc/swarmbox/mcp"):
        try:
            for entry in os.listdir(base):
                if os.path.isdir(os.path.join(base, entry)):
                    mcp.add(entry)
        except OSError:
            pass

    # Nested Podman containers
    containers = []
    podman = shutil.which("podman", path=e.get("PATH"))
    if podman:
        try:
            p = subprocess.run([podman, "ps", "--format", "json"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=PODMAN_TIMEOUT)
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

    out = {"schema": SCHEMA, "health": health}
    if resources:
        out["resources"] = resources
    out["addons"] = sorted(addons)
    if mcp:
        out["mcp"] = sorted(mcp)
    out["containers"] = containers
    return out


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    section = "workspace"
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print(__doc__.strip())
            return 0
        if a == "--section" and i + 1 < len(args):
            section = args[i + 1].strip().lower()
            i += 2
            continue
        if a.startswith("--section="):
            section = a.split("=", 1)[1].strip().lower()
            i += 1
            continue
        print(json.dumps({"err": "usage", "msg": "unknown argument: %s" % a}))
        return EXIT["usage"]

    if section not in ("workspace", "system", "all"):
        print(json.dumps({"err": "usage", "msg": "section must be workspace, system, or all"}))
        return EXIT["usage"]

    try:
        if section == "workspace":
            res = build_workspace()
        elif section == "system":
            res = build_system()
        else:
            res = build_workspace()
            sys_part = build_system()
            res["system"] = {k: v for k, v in sys_part.items() if k != "schema"}
    except StateError as e:
        print(json.dumps({"err": e.code, "msg": e.message}))
        return EXIT.get(e.code, 1)

    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
