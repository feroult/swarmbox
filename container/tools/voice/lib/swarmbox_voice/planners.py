"""Planner discovery and execution.

A planner is an executable file named planner-<name> (name matches [a-z0-9][a-z0-9_-]*). Two places are searched:
the built-in folder (<tool prefix>/planners, in the repository container/tools/voice/planners) and the user folder
(user_dir(): $SWARMBOX_VOICE_CONFIG_DIR, else $SB_CONFIG_DIR/voice, else $XDG_CONFIG_HOME/swarmbox/voice, else
~/.config/swarmbox/voice). On a name clash the USER planner wins, so a user can override a built-in; `source` says which.

run_planner never raises: it returns a PlannerResult with ok, plan (validated) or error and code. The planner gets the input
JSON on stdin, runs in its own session with a minimal environment (PATH, HOME, LANG, and SWARMBOX_VOICE_* only, never the
rest of the box environment), a timeout and an output cap. Pane text is data: it is never put on argv.
"""
import os
import re
import signal
import subprocess
import threading
import time
from collections import namedtuple

from . import contract

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
TIMEOUT = 20.0
Planner = namedtuple("Planner", "name path source")
PlannerResult = namedtuple("PlannerResult", "ok plan error code")


def builtin_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "planners")


def user_dir(env=None):
    env = os.environ if env is None else env
    if env.get("SWARMBOX_VOICE_CONFIG_DIR"):
        return env["SWARMBOX_VOICE_CONFIG_DIR"]
    if env.get("SB_CONFIG_DIR"):
        return os.path.join(env["SB_CONFIG_DIR"], "voice")
    if env.get("XDG_CONFIG_HOME"):
        return os.path.join(env["XDG_CONFIG_HOME"], "swarmbox", "voice")
    return os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config", "swarmbox", "voice")


def _scan(folder, source, found):
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return
    for entry in names:
        if not entry.startswith("planner-"):
            continue
        name = entry[len("planner-"):]
        path = os.path.join(folder, entry)
        if NAME_RE.fullmatch(name) and os.path.isfile(path) and os.access(path, os.X_OK):
            found[name] = Planner(name, path, source)


def discover(user=None, builtin=None):
    """{name: Planner}. Built-ins first, user planners override on a name clash."""
    found = {}
    _scan(builtin or builtin_dir(), "builtin", found)
    _scan(user or user_dir(), "user", found)
    return found


def find(name, user=None, builtin=None):
    """The Planner called name, or None (also for an invalid name)."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return None
    return discover(user, builtin).get(name)


# Login variables a BUILT-IN planner needs to reach its model. A box can log in to Claude Code with a variable instead of a
# file (`swarmbox env add CLAUDE_CODE_OAUTH_TOKEN`); without it the headless `claude -p` answers "Not logged in". Only the
# built-in planner of that name gets them, never a user planner (even one called "claude") and never the session-internal
# CLAUDE_CODE_MESSAGING_* variables.
CREDENTIALS = {"claude": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CONFIG_DIR")}


def planner_env(base_env=None, settings=None, planner=None):
    base = os.environ if base_env is None else base_env
    env = {"PATH": base.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": base.get("HOME", ""),
           "LANG": base.get("LANG", "C.UTF-8")}
    if getattr(planner, "source", None) == "builtin":
        for k in CREDENTIALS.get(getattr(planner, "name", None), ()):
            if base.get(k):
                env[k] = base[k]
    for k, v in base.items():
        if k.startswith("SWARMBOX_VOICE_"):
            env[k] = v
    for k, v in (settings or {}).items():
        if k.startswith("SWARMBOX_VOICE_"):
            env[k] = str(v)
    return env


def _drain(stream, limit, sink, overflow, proc):
    try:
        while True:
            chunk = os.read(stream.fileno(), 4096)   # returns what is there; a buffered read would wait for 4096 bytes or EOF
            if not chunk:
                return
            if sum(len(c) for c in sink) < limit + 1:
                sink.append(chunk)
            if sum(len(c) for c in sink) > limit:
                overflow.set()
                _kill(proc)
                return
    except (OSError, ValueError):
        return


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_planner(planner, input_obj, base_env=None, settings=None, timeout=TIMEOUT, max_output=contract.MAX_OUTPUT_BYTES):
    """Run planner (a Planner or a path) on input_obj and validate its output against the input panes."""
    import json
    path = getattr(planner, "path", planner)
    pane_ids = [p["id"] for p in input_obj.get("panes", []) if isinstance(p, dict) and "id" in p]
    try:
        payload = json.dumps(input_obj).encode("utf-8")
        proc = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=planner_env(base_env, settings, planner), cwd=os.environ.get("HOME") or "/",
                                start_new_session=True)
    except (OSError, ValueError, TypeError) as e:
        return PlannerResult(False, None, "cannot start the planner: %s" % e, "start_failed")
    out, err, overflow = [], [], threading.Event()
    threads = [threading.Thread(target=_drain, args=(proc.stdout, max_output, out, overflow, proc), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, 4096, err, threading.Event(), proc), daemon=True)]
    for t in threads:
        t.start()

    def feed():
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
        proc.wait()
    else:
        _kill(proc)   # a descendant that outlives the planner must not keep the pipes open
    deadline = time.monotonic() + 2
    for t in threads + [writer]:
        t.join(max(0.0, deadline - time.monotonic()))
    for stream in (proc.stdout, proc.stderr):
        try:
            stream.close()
        except OSError:
            pass
    if timed_out:
        return PlannerResult(False, None, "the planner took longer than %gs" % timeout, "timeout")
    if overflow.is_set():
        return PlannerResult(False, None, "the planner output is larger than %d bytes" % max_output, "output_too_large")
    if proc.returncode != 0:
        tail = b"".join(err).decode("utf-8", "replace").strip()[-200:]
        return PlannerResult(False, None, "the planner exited with %d%s" % (proc.returncode, ": " + tail if tail else ""),
                             "exit_nonzero")
    try:
        plan = contract.parse_output(b"".join(out), pane_ids)
    except contract.ContractError as e:
        return PlannerResult(False, None, e.message, e.code)
    return PlannerResult(True, plan, None, None)
