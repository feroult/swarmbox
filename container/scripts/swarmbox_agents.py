"""swarmbox_agents: the agent registry of SwarmBox (installed as /usr/local/lib/swarmbox/swarmbox_agents.py).

An addon is a coding AGENT if and only if it has `agent/agent.conf` (docs/agents-design.md 3.2). This module reads those declarations
from the two addon levels (the image's manifests and the user's), and is the only place in Python that knows which programs are agents:
swarmbox-tabs, swarmbox-state, swarmbox-pins, swarmbox-worktree and the sysop ask it, never a list of their own. Its twin in Node is
container/web/herdr/agents.mjs; both are checked against the same vectors (tests/support/fixtures/agents/cases.json).

THE FILE FORMAT of agent.conf is a small subset of shell assignments that a parser reads without running anything:
  * one `KEY=value` per line; blank lines and lines starting with `#` are skipped;
  * the value may be wrapped in double quotes; inside, no `"`, `$`, backslash or backtick (no expansion, no escapes);
  * lists are words separated by spaces.
An unknown key is ignored at run time and reported by `check` (swarmbox-addon validate runs it).

THE LEVELS. The image level is SWARMBOX_TEST_IMAGE_ADDONS / SWARMBOX_IMAGE_ADDONS_DIR, else the `addons` folder next to this file (the
image: /usr/local/lib/swarmbox/addons) or one level up (the repository: container/addons). The user level is SWARMBOX_TEST_USER_ADDONS,
else $XDG_CONFIG_HOME/swarmbox/addons (~/.config/swarmbox/addons). A user addon of the same name replaces the image one.

INSTALLED means the install record of swarmbox-addon exists (workspace or image install), or, for a self-updating addon, the program is in
~/.local/bin. Only installed agents are offered (default agent, New agent, the sysop's tab open); every declared agent is RECOGNISED
(detection of a running agent works for one installed by hand from its addon's command name).

Pseudo-agents are built in, not declared: `shell` (a login shell), `yolo` (runs the default agent; resolved at launch, never persisted)
and the role `sysop`.
"""

import importlib.util
import json
import os
import re
import shlex
import sys
import time

SCHEMA = 1
PSEUDO = ("shell", "yolo")
# The names of a plain shell process (the foreground of a tab that runs no program): one list for every reader.
SHELL_NAMES = frozenset({"bash", "sh", "zsh", "dash", "fish", "ash", "ksh", "nu", "nushell", "busybox", "login",
                         "-bash", "-sh", "-zsh", "-dash", "-fish", "-ksh"})

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
BAD_VALUE_RE = re.compile(r'["$\\`]')
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# The built-in terminal profiles (docs/agents-design.md 3.2). `tui` holds today's agy-tuned numbers; an agent's TERM_* keys override it.
TERM_DEFAULTS = {
    "resize_quiet_ms": 900, "resize_cap_ms": 3500, "resize_client_fallback_ms": 4200,
    "hydrate_gap_ms": 60, "hydrate_min_bytes": 256, "hydrate_flush_ms": 460, "hydrate_cap_ms": 1400,
    "late_redraw_ms": 2500, "settle_ms": 650,
    "copy_prompt_glyphs": "❯", "copy_gutter_glyphs": "│┃║▕▎▏", "image_paste": "path",
}
TERM_INT_KEYS = ("resize_quiet_ms", "resize_cap_ms", "resize_client_fallback_ms", "hydrate_gap_ms", "hydrate_min_bytes",
                 "hydrate_flush_ms", "hydrate_cap_ms", "late_redraw_ms", "settle_ms")

# key -> kind. str: one line; words: a list; int: a whole number; enum:a|b: one of; template: a command template with placeholders.
KEYS = {
    "SCHEMA": "int",
    "ID": "id",
    "CMD": "word",
    "LABEL": "str",
    "ALIASES": "words",
    "COLOR": "color",
    "YOLO_ARGS": "words",
    "MCP_ARGS": "words",
    "CONTEXT_ARGS": "words",
    "PASSTHROUGH": "words",
    "PRINT_FLAGS": "words",
    "RESUME_ARGS": "words",
    "RESUME_FAST_FAIL_S": "int",
    "RESUME_SCOPE": "enum:cwd|global",
    "STATUS": "enum:osc7501|none",
    "RESERVED_PREFIXES": "words",
    "ANSWER_ALLOW": "keys",
    "ANSWER_DENY": "keys",
    "HISTORY": "enum:jsonl",
    "HISTORY_FILE": "path",
    "HISTORY_FILE_ENV": "word",
    "HISTORY_FIELDS": "words",
    "NAMER": "template",
    "BRAIN": "template",
    "BRAIN_FORMAT": "enum:claude-stream-json|text",
    "BRAIN_RESUME": "template",
    "BRAIN_STOP": "enum:INT|TERM",
    "BRAIN_HOME_ENV": "word",
    "BRAIN_LOGIN_FAILURE": "str",
    "DIGEST": "template",
    "LOGIN_HINT": "str",
    "MODEL": "word",
    "NAMER_MODEL": "word",
    "DIGEST_MODEL": "word",
    "SECRET_ENV": "words",
    "SECRET_FILES": "words",
    "SETTINGS_FILE": "path",
}
for _k in TERM_INT_KEYS:
    KEYS["TERM_" + _k.upper()] = "int"
KEYS["TERM_COPY_PROMPT_GLYPHS"] = "str"
KEYS["TERM_COPY_GUTTER_GLYPHS"] = "str"
KEYS["TERM_IMAGE_PASTE"] = "enum:path|none"

PLACEHOLDERS = {"NAMER": ("prompt", "system_prompt", "model"),
                "DIGEST": ("prompt", "system_prompt", "model"),
                "CONTEXT_ARGS": ("context_file", "context_dir", "context_toml"),
                "BRAIN": ("mcp_config", "model", "system_prompt", "system_prompt_file", "max_turns", "goal_dir", "agent_dir"),
                "BRAIN_RESUME": ("session_id",),
                "MCP_ARGS": ("mcp_file", "home")}
# {mcp_file} in MCP_ARGS: the box's list of MCP servers, $SB_DATA_DIR/mcp-servers.json (swarmbox-mcp)
# {context_file} in CONTEXT_ARGS: the repository digest of the commit the agent starts on (CONTEXT_DIR/<commit>.md, written by the
# sysop's autocontext); {context_dir}: a folder holding it as AGENTS.md (CONTEXT_DIR/dirs/<commit>); {context_toml}: its text as a TOML
# basic string. The words are passed only when that file exists
CONTEXT_DIR_REL = os.path.join("sysop", "digests")     # under SB_STATE_DIR
HOOKS = {"screen": "screen.py", "history": "history.py", "shell": "shell.sh", "mcp": "mcp.sh", "statusline": "statusline.sh",
         "terminal": "terminal.mjs", "icon": "icon.svg", "settings": "settings.json"}
HOOK_FUNCS = {"screen.py": ("state",), "history.py": ("messages",)}


# ---- reading ----------------------------------------------------------------------------------------------------------------------

def parse_conf(text):
    """(values, problems): the KEY=value pairs of an agent.conf text, and every line that breaks the format."""
    values, problems = {}, []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        k, eq, v = line.partition("=")
        if not eq or not KEY_RE.match(k):
            problems.append("line %d is not KEY=value" % n)
            continue
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        if BAD_VALUE_RE.search(v):
            problems.append('line %d (%s): a value has no quotes inside, no $, no backslash and no backtick' % (n, k))
            continue
        values[k] = v.strip()
    return values, problems


def _here():
    return os.path.dirname(os.path.abspath(__file__))


def _xdg(var, fallback, env):
    base = env.get(var) or ""
    if not base.startswith("/"):
        base = fallback
    return os.path.join(base.rstrip("/") or "/", "swarmbox")


def image_addons_dir(env=None):
    env = os.environ if env is None else env
    for var in ("SWARMBOX_TEST_IMAGE_ADDONS", "SWARMBOX_IMAGE_ADDONS_DIR"):
        if env.get(var):
            return env[var]
    for cand in (os.path.join(_here(), "addons"), os.path.join(os.path.dirname(_here()), "addons")):
        if os.path.isdir(cand):
            return cand
    return "/usr/local/lib/swarmbox/addons"


def user_addons_dir(env=None):
    env = os.environ if env is None else env
    if env.get("SWARMBOX_TEST_USER_ADDONS"):
        return env["SWARMBOX_TEST_USER_ADDONS"]
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(_xdg("XDG_CONFIG_HOME", os.path.join(home, ".config"), env), "addons")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _addon_conf(dirpath):
    """NAME, COMMANDS, UPDATE of an addon.conf, read without running it (the same reading as the Web Studio's)."""
    txt = _read(os.path.join(dirpath, "addon.conf"))
    if txt is None:
        return None
    out = {}
    for raw in txt.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out if out.get("NAME") else None


def _installed(addon, conf, cmd, env):
    home = env.get("HOME") or os.path.expanduser("~")
    data = _xdg("XDG_DATA_HOME", os.path.join(home, ".local", "share"), env)
    image_state = env.get("SWARMBOX_TEST_IMAGE_STATE") or "/opt/swarmbox/addons"
    self_upd = conf.get("UPDATE") == "self"
    sub = "self" if self_upd else "current"
    for root in (os.path.join(data, "addons"), image_state):
        if os.path.isfile(os.path.join(root, addon, sub, ".swarmbox-env")):
            return True
    if self_upd:
        p = os.path.join(home, ".local", "bin", cmd)
        return os.path.isfile(p) and os.access(p, os.X_OK)
    return False


def _words(v):
    return v.split() if v else []


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _agent_from(dirpath, level, conf, values, env):
    adir = os.path.join(dirpath, "agent")
    aid = values.get("ID", "")
    cmd = values.get("CMD") or aid
    aliases = []
    for w in [conf["NAME"], cmd] + _words(values.get("ALIASES", "")):
        w = w.lower()
        if w != aid and w not in aliases:
            aliases.append(w)
    term = dict(TERM_DEFAULTS)
    for k in TERM_INT_KEYS:
        if values.get("TERM_" + k.upper()):
            term[k] = _int(values["TERM_" + k.upper()], term[k])
    for k in ("copy_prompt_glyphs", "copy_gutter_glyphs", "image_paste"):
        if values.get("TERM_" + k.upper()):
            term[k] = values["TERM_" + k.upper()]
    hooks = {h: os.path.isfile(os.path.join(adir, f)) for h, f in HOOKS.items()}
    hooks["shell"] = hooks["shell"] or os.path.isfile(os.path.join(dirpath, "shell.sh"))
    return {
        "id": aid,
        "cmd": cmd,
        "label": values.get("LABEL") or aid,
        "aliases": aliases,
        "color": values.get("COLOR", ""),
        "addon": conf["NAME"],
        "level": level,
        "dir": adir,
        "installed": _installed(conf["NAME"], conf, cmd, env),
        "yolo_args": _words(values.get("YOLO_ARGS")),
        "mcp_args": _words(values.get("MCP_ARGS")),
        "context_args": _words(values.get("CONTEXT_ARGS")),
        "passthrough": _words(values.get("PASSTHROUGH")),
        "print_flags": _words(values.get("PRINT_FLAGS")),
        "resume": {"args": _words(values.get("RESUME_ARGS")), "fast_fail_s": _int(values.get("RESUME_FAST_FAIL_S"), 4),
                   "scope": values.get("RESUME_SCOPE") or "cwd"},
        "status": values.get("STATUS") or "osc7501",
        "reserved_prefixes": _words(values["RESERVED_PREFIXES"]) if "RESERVED_PREFIXES" in values else ["/", "!"],
        "answer": {"allow": _words(values.get("ANSWER_ALLOW")), "deny": _words(values.get("ANSWER_DENY"))},
        "history": {"kind": values.get("HISTORY", ""), "file": values.get("HISTORY_FILE", ""), "file_env": values.get("HISTORY_FILE_ENV", ""),
                    "fields": _words(values.get("HISTORY_FIELDS"))},
        "namer": values.get("NAMER", ""),
        "brain": values.get("BRAIN", ""),
        # how the sysop runs that brain (docs/sysop-brain-design.md 5): the adapter of its output, how it resumes, how it is stopped
        # politely, the variable that points it at a home of its own, the words of its output that mean "not logged in"
        "brain_opts": {"format": values.get("BRAIN_FORMAT") or "text", "resume": values.get("BRAIN_RESUME", ""),
                       "stop": values.get("BRAIN_STOP") or "TERM", "home_env": values.get("BRAIN_HOME_ENV", ""),
                       "login_failure": values.get("BRAIN_LOGIN_FAILURE", "")},
        "digest": values.get("DIGEST", ""),
        "login_hint": values.get("LOGIN_HINT", ""),
        "model": values.get("MODEL", ""),
        "namer_model": values.get("NAMER_MODEL", ""),
        "digest_model": values.get("DIGEST_MODEL", ""),
        "secrets": {"env": _words(values.get("SECRET_ENV")), "files": _words(values.get("SECRET_FILES"))},
        "settings_file": values.get("SETTINGS_FILE", ""),
        "term": term,
        "hooks": hooks,
    }


_CACHE = {}


def _stamp(dirs):
    """A cheap fingerprint of every file the registry reads: a changed, added or removed manifest gives a different stamp."""
    parts = []
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            for rel in ("addon.conf", "agent", os.path.join("agent", "agent.conf"), "shell.sh"):
                try:
                    st = os.stat(os.path.join(d, n, rel))
                    parts.append((d, n, rel, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
    return tuple(parts)


def _install_stamp(env):
    """the folders an install or a remove changes (the install records, ~/.local/bin of a self-updating agent): `installed` follows at once"""
    home = env.get("HOME") or os.path.expanduser("~")
    data = os.path.join(_xdg("XDG_DATA_HOME", os.path.join(home, ".local", "share"), env), "addons")
    parts = []
    for root in (data, env.get("SWARMBOX_TEST_IMAGE_STATE") or "/opt/swarmbox/addons", os.path.join(home, ".local", "bin")):
        for p in [root] + ([os.path.join(root, n) for n in sorted(os.listdir(root))] if os.path.isdir(root) and root != os.path.join(home, ".local", "bin") else []):
            try:
                st = os.stat(p)
                parts.append((p, st.st_mtime_ns))
            except OSError:
                pass
    return tuple(parts)


def load(env=None):
    """The registry: {"agents": [agent, ...] (sorted by id), "by_name": {name: id}}. Cached while no manifest changes."""
    env = os.environ if env is None else env
    levels = (("image", image_addons_dir(env)), ("user", user_addons_dir(env)))
    key = tuple(d for _, d in levels) + (env.get("HOME", ""), env.get("XDG_DATA_HOME", ""), env.get("XDG_CONFIG_HOME", ""))
    stamp = _stamp([d for _, d in levels]) + _install_stamp(env)
    hit = _CACHE.get(key)
    if hit and hit[0] == stamp and time.monotonic() - hit[2] < 5.0:   # 5 s: an install changes `installed` without touching a manifest
        return hit[1]
    found = {}
    for level, root in levels:
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            d = os.path.join(root, n)
            conf = _addon_conf(d)
            if not conf:
                continue
            txt = _read(os.path.join(d, "agent", "agent.conf"))
            if txt is None:
                found.pop(conf["NAME"], None)      # a user addon without agent/ hides the image agent of the same name
                continue
            values, _ = parse_conf(txt)
            if not ID_RE.match(values.get("ID", "")) or values["ID"] in PSEUDO or values["ID"] == "sysop":
                continue
            found[conf["NAME"]] = _agent_from(d, level, conf, values, env)
    agents = sorted(found.values(), key=lambda a: a["id"])
    by_name = {}
    for a in agents:
        by_name.setdefault(a["id"], a["id"])
    for a in agents:
        for al in a["aliases"]:
            by_name.setdefault(al, a["id"])
    reg = {"agents": agents, "by_name": by_name}
    _CACHE[key] = (stamp, reg, time.monotonic())
    return reg


# ---- the resolver -----------------------------------------------------------------------------------------------------------------

def agents(env=None, installed_only=False):
    return [a for a in load(env)["agents"] if a["installed"] or not installed_only]


def get(aid, env=None):
    for a in load(env)["agents"]:
        if a["id"] == aid:
            return a
    return None


def resolve(name, env=None):
    """The agent id of a name (an id, a command, an alias: the OSC 7501 app it reports, its addon name, a process name), or ''.
    A path is reduced to its last part and a login shell's leading '-' is dropped. Pseudo-agents give ''."""
    n = os.path.basename(str(name or "").strip()).lower().lstrip("-")
    if not n:
        return ""
    return load(env)["by_name"].get(n, "")


def is_agent(name, env=None):
    return bool(resolve(name, env))


def ids(env=None, installed_only=False):
    return [a["id"] for a in agents(env, installed_only)]


def default_agent(env=None):
    """The default agent of the box: AGENT if it names an agent, else the first WITH entry that is an agent, else the first installed
    agent, else ''. One answer for every place that starts or offers the default agent (yolo, New agent, worktree open, the sysop)."""
    env = os.environ if env is None else env
    a = resolve(env.get("SWARMBOX_AGENT", ""), env)
    if a:
        return a
    for tok in (env.get("SWARMBOX_WITH") or "").replace(",", " ").split():
        a = resolve(tok, env)
        if a:
            return a
    inst = ids(env, installed_only=True)
    return inst[0] if inst else ""


def _bare_shell(argv, fg):
    argv = argv if isinstance(argv, (list, tuple)) else []
    fg = os.path.basename(str(fg or "")).lower()
    return len(argv) <= 2 and (not fg or fg in SHELL_NAMES)


def detect(term, env=None, live=False):
    """The agent a terminal runs, by the one detection order of docs/agents-design.md 3.3: the OSC 7501 `app` it reports, then its
    foreground process, then (not for `live`) the `swarmbox.agent` label, trusted only when the terminal is not a bare login shell (its
    argv is longer than `bash -l`, or its foreground is a program that is not a shell: an agent that runs as `node`).
    Never the tab name. `term` is a herdr-core terminal object or a row of `swarmbox-tabs list` (keys status, foreground/cmd, labels/agent)."""
    if not isinstance(term, dict):
        return ""
    st = term.get("status")
    if isinstance(st, dict):
        a = resolve(st.get("app"), env)
        if a:
            return a
    fg = term.get("foreground")
    fgname = fg.get("name") if isinstance(fg, dict) else term.get("cmd")
    a = resolve(fgname, env)
    if a or live:
        return a
    labels = term.get("labels")
    lbl = labels.get("swarmbox.agent") if isinstance(labels, dict) else term.get("agent")
    if isinstance(lbl, str) and resolve(lbl, env):
        if not _bare_shell(term.get("argv"), fgname):
            return resolve(lbl, env)
    return ""


def resume_argv(aid, env=None):
    """The words that resume the last conversation of agent `aid` (its RESUME_ARGS), [] when it cannot resume."""
    a = get(aid, env)
    return list(a["resume"]["args"]) if a else []


def launch_script(aid, resume=True, env=None, context=True):
    """The bash -lic script that starts agent `aid` in a tab (through its shell function, so auto-approve and MCP apply): with `resume`
    and RESUME_ARGS, it first tries to continue; when that fails within RESUME_FAST_FAIL_S seconds (no conversation here, or a failure
    such as a login that expired), it says so in the tab and starts fresh. A login shell takes the agent's place when it exits. Without
    `context` the session starts without the sysop's repository context (SWARMBOX_CONTEXT=0, read by _sb_agent_run). The JS twin is
    launchScript in agents.mjs."""
    a = get(aid, env)
    if not a:
        return "exec /bin/bash -l"
    cmd = shlex.quote(a["cmd"]) if context else "SWARMBOX_CONTEXT=0 " + shlex.quote(a["cmd"])
    rargs = " ".join(shlex.quote(w) for w in a["resume"]["args"])
    if resume and rargs:
        return ("_sb_t0=$(date +%%s); SWARMBOX_WORKTREE_GUARD=0 %s %s; _sb_rc=$?; "
                "if [ \"$_sb_rc\" -ne 0 ] && [ $(( $(date +%%s) - _sb_t0 )) -lt %d ]; then "
                "printf '\\n[swarmbox] %%s ended at once (exit %%s): starting a new conversation\\n' %s \"$_sb_rc\" >&2; "
                "SWARMBOX_WORKTREE_GUARD=0 %s; fi; exec /bin/bash -l"
                % (cmd, rargs, a["resume"]["fast_fail_s"], shlex.quote("%s %s" % (a["cmd"], " ".join(a["resume"]["args"]))), cmd))
    return "SWARMBOX_WORKTREE_GUARD=0 %s; exec /bin/bash -l" % cmd


def build_argv(agent, resume="continue", env=None, context=True):
    """The argv of a terminal that runs `agent` (an id, an alias, `shell` or `yolo`): a login shell for `shell` and for a name that is no
    agent; `yolo` is the default agent of the box (when there is none, the `yolo` function runs and says so in the tab). An agent starts
    through an interactive shell (-i), so that its shell function applies (auto-approve, the box MCP servers); the worktree guard is off,
    the caller chose the folder. `resume` is "continue" (resume the last conversation when the agent can) or "fresh"."""
    name = str(agent or "shell").strip().lower()
    if name == "yolo":
        aid = default_agent(env)
        if not aid:
            return ["/bin/bash", "-lic", "SWARMBOX_WORKTREE_GUARD=0 yolo; exec /bin/bash -l"]
    else:
        aid = resolve(name, env)
    if not aid:
        return ["/bin/bash", "-l"]
    return ["/bin/bash", "-lic", launch_script(aid, resume == "continue", env, context)]


def hook(aid, name, env=None):
    """The Python module of a hook of agent `aid` (`screen` or `history`), or None. Loaded from the agent's folder by path; a hook that
    fails to import is treated as absent (logged to stderr)."""
    a = get(aid, env)
    if not a or not a["hooks"].get(name) or not HOOKS[name].endswith(".py"):
        return None
    path = os.path.join(a["dir"], HOOKS[name])
    key = ("hook", path)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    hit = _CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        spec = importlib.util.spec_from_file_location("swarmbox_agent_%s_%s" % (aid.replace("-", "_"), name), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001  - a broken hook degrades to "absent"
        sys.stderr.write("swarmbox_agents: the %s hook of %s does not load: %s\n" % (name, aid, e))
        mod = None
    _CACHE[key] = (mtime, mod)
    return mod


def public(a):
    """An agent as the browser and agents.json see it (no file system paths)."""
    out = {k: v for k, v in a.items() if k != "dir"}
    return out


def registry_json(env=None):
    return {"schema": SCHEMA, "default": default_agent(env), "shell_names": sorted(SHELL_NAMES), "agents": [public(a) for a in agents(env)]}


# ---- check ------------------------------------------------------------------------------------------------------------------------

def check_dir(addon_dir, commands=None):
    """The problems of the agent/ folder of an addon (empty when it is good, or when there is no agent/)."""
    adir = os.path.join(addon_dir, "agent")
    if not os.path.isdir(adir):
        return []
    errs = []
    txt = _read(os.path.join(adir, "agent.conf"))
    if txt is None:
        return ["agent/ has no agent.conf (an addon is an agent when agent/agent.conf exists)"]
    values, problems = parse_conf(txt)
    errs += ["agent.conf: " + p for p in problems]
    if commands is None:
        conf = _addon_conf(addon_dir) or {}
        commands = (conf.get("COMMANDS") or "").split()
    for k, v in values.items():
        kind = KEYS.get(k)
        if kind is None:
            errs.append("agent.conf: unknown key %s" % k)
            continue
        if kind == "int" and not re.match(r"^[0-9]+$", v):
            errs.append("agent.conf: %s must be a whole number, found '%s'" % (k, v))
        elif kind == "id" and not ID_RE.match(v):
            errs.append("agent.conf: ID '%s' is not a plain lowercase word" % v)
        elif kind == "word" and v and not WORD_RE.match(v):
            errs.append("agent.conf: %s '%s' is not one plain word" % (k, v))
        elif kind == "color" and v and not COLOR_RE.match(v):
            errs.append("agent.conf: COLOR must be #rrggbb, found '%s'" % v)
        elif kind.startswith("enum:") and v and v not in kind[5:].split("|"):
            errs.append("agent.conf: %s must be one of %s, found '%s'" % (k, kind[5:].replace("|", ", "), v))
        elif kind == "path" and v and (v.startswith("/") or ".." in v.split("/") or not re.match(r"^[A-Za-z0-9._/-]+$", v)):
            errs.append("agent.conf: %s must be a plain path under the home, found '%s'" % (k, v))
        elif kind == "keys":
            for w in v.split():
                if not re.match(r"^[a-z0-9]+(?:\+[a-z0-9]+)*$", w):
                    errs.append("agent.conf: %s entry '%s' is not a key name (enter, esc, up, ctrl+c, 1, y...)" % (k, w))
        elif kind == "words" and k == "ALIASES":
            for w in v.split():
                if not ID_RE.match(w):
                    errs.append("agent.conf: ALIASES entry '%s' is not a plain lowercase word" % w)
        if k in PLACEHOLDERS:
            for ph in PLACEHOLDER_RE.findall(v):
                if ph not in PLACEHOLDERS[k]:
                    errs.append("agent.conf: %s uses the unknown placeholder {%s} (known: %s)" % (k, ph, ", ".join(PLACEHOLDERS[k])))
    if values.get("HISTORY") == "jsonl" and (not values.get("HISTORY_FILE") or len(values.get("HISTORY_FIELDS", "").split()) != 4):
        errs.append("agent.conf: HISTORY=jsonl needs HISTORY_FILE and HISTORY_FIELDS (folder, session, text and time keys)")
    if "ID" not in values:
        errs.append("agent.conf: ID is missing")
    elif values["ID"] in PSEUDO or values["ID"] == "sysop":
        errs.append("agent.conf: ID '%s' is a built-in name (shell, yolo, sysop)" % values["ID"])
    cmd = values.get("CMD") or values.get("ID", "")
    if cmd and commands and cmd not in commands:
        errs.append("agent.conf: CMD '%s' is not one of the addon's COMMANDS (%s)" % (cmd, " ".join(commands)))
    if values.get("SCHEMA") and _int(values["SCHEMA"], 0) > SCHEMA:
        errs.append("agent.conf: SCHEMA=%s is newer than this SwarmBox reads (%d)" % (values["SCHEMA"], SCHEMA))
    icon = os.path.join(adir, "icon.svg")
    if os.path.isfile(icon):
        data = _read(icon) or ""
        if len(data) > 16384:
            errs.append("agent/icon.svg is larger than 16 KiB")
        elif not re.match(r"^\s*<svg[\s>]", data) or "</svg>" not in data:
            errs.append("agent/icon.svg is not one <svg> element")
        elif re.search(r"<script|\son[a-z]+\s*=|javascript:", data, re.I):
            errs.append("agent/icon.svg has a script or an event handler")
    for f, funcs in HOOK_FUNCS.items():
        p = os.path.join(adir, f)
        if os.path.isfile(p):
            src = _read(p) or ""
            for fn in funcs:
                if not re.search(r"^def %s\(" % fn, src, re.M):
                    errs.append("agent/%s does not define %s()" % (f, fn))
    sj = os.path.join(adir, "settings.json")
    if os.path.isfile(sj):
        try:
            if not isinstance(json.loads(_read(sj) or ""), dict):
                errs.append("agent/settings.json is not a JSON object")
        except ValueError:
            errs.append("agent/settings.json is not valid JSON")
        if not values.get("SETTINGS_FILE"):
            errs.append("agent/settings.json needs SETTINGS_FILE in agent.conf (the agent's settings file, under the home)")
    return errs


# ---- the default settings of an agent (swarmbox-addon prepare runs `seed`) -------------------------------------------------------------

def _fill(value, subst):
    """the placeholders {home} and {addon_dir} in every string of a JSON value"""
    if isinstance(value, str):
        for k, v in subst.items():
            value = value.replace("{%s}" % k, v)
        return value
    if isinstance(value, list):
        return [_fill(x, subst) for x in value]
    if isinstance(value, dict):
        return {k: _fill(v, subst) for k, v in value.items()}
    return value


def seed_settings(addon_dir, env=None):
    """Seed the defaults of agent/settings.json into the agent's own settings file (SETTINGS_FILE, under the home): once, tracked by
    <data>/addons/<addon>/.defaults-applied, so a default the user removed stays removed (deleting the settings file seeds again);
    never over a key the user has; atomic, mode 0600. A settings file that is not a JSON object is left untouched (an error).
    Returns (exit code, message)."""
    env = os.environ if env is None else env
    conf = _addon_conf(addon_dir) or {}
    name = conf.get("NAME") or os.path.basename(addon_dir.rstrip("/"))
    values, _ = parse_conf(_read(os.path.join(addon_dir, "agent", "agent.conf")) or "")
    rel = values.get("SETTINGS_FILE", "")
    src = os.path.join(addon_dir, "agent", "settings.json")
    if not rel or not os.path.isfile(src):
        return 0, ""
    home = env.get("HOME") or os.path.expanduser("~")
    target = os.path.join(home, rel)
    stamp_dir = os.path.join(_xdg("XDG_DATA_HOME", os.path.join(home, ".local", "share"), env), "addons", name)
    stamp = os.path.join(stamp_dir, ".defaults-applied")
    if os.path.isfile(stamp) and os.path.isfile(target):
        return 0, ""
    try:
        defaults = json.loads(_read(src) or "")
    except ValueError:
        return 2, "%s: agent/settings.json is not valid JSON" % name
    defaults = _fill(defaults, {"home": home, "addon_dir": os.path.abspath(addon_dir)})
    old_umask = os.umask(0o077)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.makedirs(stamp_dir, exist_ok=True)
        if os.path.exists(target):
            try:
                with open(target, encoding="utf-8") as f:
                    user = json.load(f)
            except (OSError, ValueError):
                user = None
            if not isinstance(user, dict):
                return 1, "%s: %s is not a JSON object; leaving it untouched" % (name, target)
            merged = dict(defaults)
            merged.update(user)      # the user's keys always win
        else:
            merged = defaults
        tmp = "%s.tmp.%d" % (target, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        with open(stamp, "w"):
            pass
    except OSError as e:
        return 1, "%s: cannot write %s: %s" % (name, target, e)
    finally:
        os.umask(old_umask)
    return 0, "%s: seeded its default settings in %s" % (name, target)


# ---- the generated shell wrappers (bashrc.sh evaluates `swarmbox-agents sh`) ------------------------------------------------------

FUNC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

# _sb_agent_run ID CMD PASSTHROUGH PRINT_FLAGS NYOLO YOLO... NMCP MCP... NCTX CTX... ARGS...: how every generated agent function starts
# its agent. A first word of PASSTHROUGH (a subcommand that refuses the flags) runs the program untouched; a word of PRINT_FLAGS (a
# one-shot call, not a session) skips the worktree guard and the context; then the program runs with its auto-approve words (unless
# SWARMBOX_YOLO=0), the words that give it the box's MCP servers (always: they are not a permission) and, for a session started in a Git
# repository whose commit has a digest (the sysop's autocontext writes $SB_STATE_DIR/sysop/digests/<commit>.md), its CONTEXT_ARGS with
# the digest in the form the agent takes best (docs/agents-design.md): {context_file} the file (Claude Code:
# --append-system-prompt-file, its system prompt), {context_dir} a folder holding it as AGENTS.md (Antigravity: --add-dir, its rules;
# digests/dirs/<commit>/), {context_toml} its text as a TOML string (Codex: -c developer_instructions=, a developer message). No file,
# no words: the agent starts as it would without the sysop. The commit is read after the guard, which may have moved the shell into a
# new worktree. An addon with a shell.sh of its own calls _sb_context itself (OpenCode).
# _sb_context ID: when the digests folder exists (autocontext is on) the session is told to the box on tab.events (swarmbox-bus, source
# launcher): a commit without a file, or whose file is marked <commit>.wait, first publishes `prepare` and, when somebody received it,
# waits for the file (_sb_wait: the sysop carries the repository's digest forward at once; the first time in a repository, or when the
# digest is far behind the commit, the model writes it, about 10 s, shown on the terminal, and Enter skips: without context the first
# time, with the carried file when it is behind); then `session` says which file the agent got (or none, and whether the user skipped), in the background,
# for the panel and the mark on the tab. SWARMBOX_CONTEXT=0 (the Web Studio's New agent box, unticked) starts without the context and
# says so (`off`). No folder, no bus: nothing is published and nothing waits. It sets _sb_context_file (empty: no context).
# `command CMD` reaches the program (or its shim), not the function. Written for bash and zsh.
SHELL_HELPER = r"""_sb_wait() (
    # _sb_wait DIR COMMIT: after a `prepare`, wait for DIR/COMMIT.md. Up to 2 s for a carry-forward or a mark of the sysop; while the mark
    # is COMMIT.wait (the model is writing the first digest of the repository, or a new one: the carried COMMIT.md beside it is far behind)
    # it says so in one still line on the terminal (cut to the terminal's real width, so it never wraps: a redrawn line that wraps floods
    # the screen), up to 30 s, and Enter starts the agent at once (without context, or with the carried file). The Web Studio shows its
    # own loader over the terminal. COMMIT.none, or no mark after 2 s (an older sysop), starts at once. 1 when the user skipped.
    # a subshell: the echo it turns off while its line shows is the terminal's again whatever ends it (a Ctrl-C kills the subshell, and
    # the interactive shell puts back the terminal modes it had before that job)
    local _w_i=0 _w_shown= _w_repo= _w_why= _w_raw= _w_line _w_k _w_cols _w_tty=
    while [ "$_w_i" -lt 300 ]; do
        if [ ! -e "$1/$2.wait" ]; then
            [ -s "$1/$2.md" ] && break
            [ -e "$1/$2.none" ] && break
        fi
        if [ -e "$1/$2.wait" ]; then
            # behind: the sysop writes the mark, then the carried file; without a terminal the launcher starts with that file at once
            if ! { [ -t 0 ] && [ -t 2 ]; }; then
                [ -s "$1/$2.md" ] && break
                IFS="$(printf '\t')" read -r _w_repo _w_raw < "$1/$2.wait" || :
                [ "$_w_raw" = behind ] && [ "$_w_i" -lt 20 ] || break
                command sleep 0.1
                _w_i=$((_w_i + 1))
                continue
            fi
            if [ -z "$_w_shown" ]; then
                IFS="$(printf '\t')" read -r _w_repo _w_raw < "$1/$2.wait" || :
                _w_repo=${_w_repo//[[:cntrl:]]/}
                case "$_w_raw" in prefetch|new) _w_why='first time' ;; behind) _w_why='many files or its docs changed since the last one' ;; stale) _w_why='the last one is old' ;; changed) _w_why='many files changed' ;; *) _w_why='' ;; esac
                _w_cols=$(command stty size 2>/dev/null <&2) || _w_cols=
                _w_cols=${_w_cols##* }
                case "$_w_cols" in ""|*[!0-9]*) _w_cols=${COLUMNS:-80} ;; esac
                if [ "$_w_raw" = behind ]; then
                    _w_line="sysop: rewriting the context of ${_w_repo:-this repository} ($_w_why) - Enter starts with the last one"
                else
                    _w_line="sysop: preparing the context of ${_w_repo:-this repository}${_w_why:+ ($_w_why)} - Enter starts without it"
                fi
                [ "$_w_cols" -gt 1 ] && _w_line=${_w_line:0:$((_w_cols - 1))}
                _w_tty=$(command stty -g 2>/dev/null) && command stty -echo 2>/dev/null || _w_tty=
                printf '\r\033[2K\033[2m%s\033[0m' "$_w_line" >&2
                _w_shown=1
            fi
            # Enter skips. bash's `read -t 0.1` drops a key that comes as its timeout fires (measured: 3 of 24 under load), so bash
            # asks `read -t 0` (is a line there? it reads nothing) and reads only then; zsh's -t tests before it reads
            if [ -n "${ZSH_VERSION-}" ]; then
                read -rs -t 0.1 _w_k 2>/dev/null && _w_k=1 || _w_k=
            elif read -t 0 2>/dev/null; then
                read -rs _w_k 2>/dev/null; _w_k=1
            else
                command sleep 0.1; _w_k=
            fi
            if [ -n "$_w_k" ]; then
                [ -z "$_w_tty" ] || command stty "$_w_tty" 2>/dev/null
                printf '\r\033[2K' >&2
                return 1
            fi
        else
            [ "$_w_i" -ge 20 ] && break
            command sleep 0.1
        fi
        _w_i=$((_w_i + 1))
    done
    [ -z "$_w_tty" ] || command stty "$_w_tty" 2>/dev/null
    [ -z "$_w_shown" ] || printf '\r\033[2K' >&2
    return 0
)
_sb_context() {
    # _sb_context ID: the digest of the commit a session of agent ID starts on, in _sb_context_file (empty: none), told to the box
    local _c_head _c_dir _c_file _c_cwd _c_tab _c_msg _c_skip=
    _sb_context_file=
    _c_head=$(command git rev-parse --verify -q HEAD 2>/dev/null) || return 0
    case "$_c_head" in ""|*[!0-9a-f]*) return 0 ;; esac
    _c_dir="${SB_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/swarmbox}/sysop/digests"
    [ -d "$_c_dir" ] || return 0
    _c_file="$_c_dir/$_c_head.md"
    _c_cwd=${PWD//[[:cntrl:]]/}
    _c_cwd=${_c_cwd//\\/\\\\}
    _c_cwd=${_c_cwd//\"/\\\"}
    _c_tab=${HC_TERMINAL_ID:-}
    case "$_c_tab" in *[!A-Za-z0-9_.:@-]*) _c_tab= ;; esac
    _c_msg="\"tab\":\"$_c_tab\",\"cwd\":\"$_c_cwd\",\"agent\":\"$1\",\"commit\":\"$_c_head\""
    if [ "${SWARMBOX_CONTEXT:-1}" = 0 ]; then
        _c_file=
        _c_msg="$_c_msg,\"off\":true"
    elif { [ ! -s "$_c_file" ] || [ -e "$_c_dir/$_c_head.wait" ]; } && command swarmbox-bus pub --source launcher tab.events "{\"event\":\"prepare\",$_c_msg}" >/dev/null 2>&1; then
        _sb_wait "$_c_dir" "$_c_head" || _c_skip=1
    fi
    [ -n "$_c_file" ] && [ -f "$_c_file" ] && [ -s "$_c_file" ] || _c_file=
    _c_msg="$_c_msg,\"context\":\"$_c_file\""
    [ -z "$_c_skip" ] || _c_msg="$_c_msg,\"skipped\":true"
    ( command swarmbox-bus pub --allow-none --source launcher tab.events "{\"event\":\"session\",$_c_msg}" >/dev/null 2>&1 & ) 2>/dev/null
    _sb_context_file=$_c_file
}
_sb_context_dir() {
    # _sb_context_dir FILE: a folder that holds FILE (DIR/<commit>.md) as AGENTS.md, DIR/dirs/<commit> (the sysop prunes it with FILE)
    local _d="${1%/*}/dirs/${1##*/}"
    _d=${_d%.md}
    command mkdir -p "$_d" 2>/dev/null && command cp -f "$1" "$_d/AGENTS.md.$$" 2>/dev/null && command mv -f "$_d/AGENTS.md.$$" "$_d/AGENTS.md" 2>/dev/null || return 1
    printf '%s' "$_d"
}
_sb_context_toml() {
    # _sb_context_toml FILE: the text of FILE as one TOML basic string ("...": backslash, quote, newline and tab escaped, other
    # control characters dropped)
    local _t
    _t=$(command tr -d '\000-\010\013-\037\177' < "$1" 2>/dev/null) || return 1
    _t=${_t//\\/\\\\}
    _t=${_t//\"/\\\"}
    _t=${_t//$'\n'/\\n}
    _t=${_t//$'\t'/\\t}
    printf '"%s"' "$_t"
}
_sb_agent_run() {
    local _sb_id=$1 _sb_cmd=$2 _sb_pass=" $3 " _sb_print=" $4 " _sb_n=$5 _sb_a _sb_guard=1 _sb_v _sb_ok=1 _sb_cdir= _sb_ctoml=
    shift 5
    local -a _sb_yolo _sb_mcp _sb_ctx _sb_ctx_on
    _sb_yolo=()
    _sb_mcp=()
    _sb_ctx=()
    _sb_ctx_on=()
    while [ "$_sb_n" -gt 0 ]; do _sb_yolo+=("$1"); shift; _sb_n=$((_sb_n - 1)); done
    _sb_n=$1
    shift
    while [ "$_sb_n" -gt 0 ]; do _sb_mcp+=("$1"); shift; _sb_n=$((_sb_n - 1)); done
    _sb_n=$1
    shift
    while [ "$_sb_n" -gt 0 ]; do _sb_ctx+=("$1"); shift; _sb_n=$((_sb_n - 1)); done
    if [ -n "${1:-}" ]; then
        case "$_sb_pass" in *" $1 "*) command "$_sb_cmd" "$@"; return ;; esac
    fi
    for _sb_a in "$@"; do
        [ -n "$_sb_a" ] || continue
        case "$_sb_print" in *" $_sb_a "*) _sb_guard=0 ;; esac
    done
    if [ "$_sb_guard" = 1 ] && type _sb_worktree_guard >/dev/null 2>&1; then
        _sb_worktree_guard "$_sb_id" "$@" || return $?
    fi
    if [ "$_sb_guard" = 1 ] && [ "${#_sb_ctx[@]}" -gt 0 ]; then
        _sb_context "$_sb_id"
        if [ -n "$_sb_context_file" ]; then
            for _sb_a in "${_sb_ctx[@]}"; do
                _sb_v=$_sb_a
                case "$_sb_v" in *'{context_file}'*) _sb_v=${_sb_v//'{context_file}'/"$_sb_context_file"} ;; esac
                case "$_sb_v" in *'{context_dir}'*)
                    [ -n "$_sb_cdir" ] || _sb_cdir=$(_sb_context_dir "$_sb_context_file") || { _sb_ok=0; break; }
                    _sb_v=${_sb_v//'{context_dir}'/"$_sb_cdir"} ;;
                esac
                case "$_sb_v" in *'{context_toml}'*)
                    [ -n "$_sb_ctoml" ] || _sb_ctoml=$(_sb_context_toml "$_sb_context_file") || { _sb_ok=0; break; }
                    _sb_v=${_sb_v//'{context_toml}'/"$_sb_ctoml"} ;;
                esac
                _sb_ctx_on+=("$_sb_v")
            done
            [ "$_sb_ok" = 1 ] || _sb_ctx_on=()
        fi
    fi
    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then
        command "$_sb_cmd" "${_sb_mcp[@]}" "${_sb_ctx_on[@]}" "$@"
    else
        command "$_sb_cmd" "${_sb_yolo[@]}" "${_sb_mcp[@]}" "${_sb_ctx_on[@]}" "$@"
    fi
}
"""


def _sh_word(w):
    """A word of agent.conf as shell text: {home} and {mcp_file} become paths under $HOME, expanded when the function runs. A value
    has no quote, $, backslash or backtick (parse_conf), so double quotes are safe."""
    if "{home}" in w or "{mcp_file}" in w:
        return '"%s"' % w.replace("{mcp_file}", "${SB_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox}/mcp-servers.json").replace("{home}", "$HOME")
    return shlex.quote(w)


def shell_functions(env=None):
    """The shell text that defines one function per agent of the registry whose addon has no shell.sh of its own (an addon's shell.sh
    wins: OpenCode's), each calling _sb_agent_run with the agent's data inlined, plus the helpers (_sb_agent_run, and _sb_context that
    an addon's shell.sh calls), written whenever the registry has an agent."""
    out = []
    every = agents(env)
    for a in every:
        if a["hooks"]["shell"] or not FUNC_NAME_RE.match(a["cmd"]):
            continue
        words = [shlex.quote(a["id"]), shlex.quote(a["cmd"]), shlex.quote(" ".join(a["passthrough"])), shlex.quote(" ".join(a["print_flags"])),
                 str(len(a["yolo_args"]))] + [_sh_word(w) for w in a["yolo_args"]] + [str(len(a["mcp_args"]))] + [_sh_word(w) for w in a["mcp_args"]]
        words += [str(len(a["context_args"]))] + [shlex.quote(w) for w in a["context_args"]]
        out.append("%s() {\n    _sb_agent_run %s \"$@\"\n}\n" % (a["cmd"], " ".join(words)))
    if not every:
        return ""
    return "# generated by swarmbox-agents sh: the shell functions of the agents of the box (docs/agents-design.md)\n" + SHELL_HELPER + "".join(out)


# ---- command line: swarmbox-agents ---------------------------------------------------------------------------------------------------

USAGE = """usage: swarmbox-agents COMMAND
  list [--installed] [--json]   the declared agents (id, command, installed)
  get ID                        one agent as JSON
  resolve NAME                  the agent id of a name (exit 1 when it is not an agent)
  default [--cmd]               the default agent of the box, or its command (exit 1 when there is none)
  generate [--output FILE]      write the registry as JSON (default: $SB_RUN_DIR/agents.json, /tmp/swarmbox/agents.json)
  sh                            the shell functions of the agents (bashrc.sh evaluates it in every shell)
  check DIR                     check the agent/ folder of the addon in DIR (exit 1 with the problems)
  seed DIR                      seed the agent/settings.json of the addon in DIR into the agent's settings file, once
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(USAGE)
        return 64
    cmd, rest = argv[0], argv[1:]
    if cmd == "list":
        inst = "--installed" in rest
        lst = agents(installed_only=inst)
        if "--json" in rest:
            print(json.dumps([public(a) for a in lst], indent=2))
        else:
            for a in lst:
                print("%-12s %-12s %s" % (a["id"], a["cmd"], "installed" if a["installed"] else "-"))
        return 0
    if cmd == "get" and len(rest) == 1:
        a = get(resolve(rest[0]) or rest[0])
        if not a:
            sys.stderr.write("swarmbox-agents: no agent named %s\n" % rest[0])
            return 1
        print(json.dumps(public(a), indent=2))
        return 0
    if cmd == "resolve" and len(rest) == 1:
        a = resolve(rest[0])
        if a:
            print(a)
        return 0 if a else 1
    if cmd == "default" and rest in ([], ["--cmd"]):
        a = default_agent()
        if a:
            print(get(a)["cmd"] if rest else a)
        return 0 if a else 1
    if cmd == "generate":
        out = os.path.join(os.environ.get("SB_RUN_DIR") or "/tmp/swarmbox", "agents.json")
        if rest[:1] == ["--output"] and len(rest) == 2:
            out = rest[1]
        elif rest:
            sys.stderr.write(USAGE)
            return 64
        data = json.dumps(registry_json(), indent=2) + "\n"
        try:
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            tmp = "%s.tmp.%d" % (out, os.getpid())
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, out)
        except OSError as e:
            sys.stderr.write("swarmbox-agents: cannot write %s: %s\n" % (out, e))
            return 1
        return 0
    if cmd == "sh" and not rest:
        sys.stdout.write(shell_functions())
        return 0
    if cmd == "seed" and len(rest) == 1:
        rc, msg = seed_settings(rest[0])
        if msg:
            sys.stderr.write("swarmbox-agents seed: %s\n" % msg)
        return rc
    if cmd == "check" and len(rest) == 1:
        errs = check_dir(rest[0])
        for e in errs:
            print(e)
        return 1 if errs else 0
    sys.stderr.write(USAGE)
    return 64


if __name__ == "__main__":
    sys.exit(main())
