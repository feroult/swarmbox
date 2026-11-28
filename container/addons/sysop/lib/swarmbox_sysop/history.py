"""The conversation so far: what the user asked and what the sysop did in the goals before this one.

Each goal runs in a brain of its own that starts with no memory, so without this every sentence of the user would be heard as the first. Here the finished goals
(their folders keep state.json: the words of the user, the texts typed into tabs, the summary of the end) are written as a short block that goes in front of the
goal on the standard input of the brain (service.py). It is CONTEXT for the brain, in its own words and the user's: it never holds what a tab showed or what an
agent answered, only what was said to the sysop, what the sysop typed, and where.

Only the last few goals (HISTORY_GOALS) from the last hours (HISTORY_AGE) are used, and the block is at most MAX_CHARS long, so it does not grow with the days.
A new conversation (the New button of the web studio writes conversation.json with the time it was asked) leaves out every goal created before it.
"""
import re

from . import ipc

HISTORY_GOALS = 8
HISTORY_AGE = 12 * 3600      # seconds: older goals are another conversation
MAX_CHARS = 3600
TERMINAL = ("done", "stopped", "failed")
_TAB = re.compile(r"screen of ((?:t|@)\d[a-z0-9]{0,3}) \(([^)]*)\)", re.I)
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
_UI_ACTION = re.compile(r"^\[ui-action(?:\s+lang=[^\s:\]]+)?:\s*([^\]]+)\]")


def _one(text, limit):
    s = _CTRL.sub(" ", str(text or "").encode("utf-8", "replace").decode("utf-8")).strip()      # a lone surrogate (a byte that was not UTF-8) cannot go on the pipe of the brain
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _ago(seconds):
    m = int(max(0, seconds) // 60)
    return "just now" if m < 1 else ("%d min ago" % m if m < 90 else "%d h ago" % round(m / 60))


def _typed(goal):
    """[(tab, text)] the goal typed with run (the texts the user would call 'what I told the agent'), oldest first, for the calls that were not refused."""
    out = []
    for c in goal.get("calls") or []:
        if not isinstance(c, dict) or c.get("tool") != "run" or c.get("is_error"):
            continue
        args = c.get("args") if isinstance(c.get("args"), dict) else {}
        m = _TAB.search(str(c.get("summary") or ""))
        tab = "%s (%s)" % (m.group(1), _one(m.group(2), 30)) if m else (_one(args.get("tab"), 12) or "the active tab")
        out.append((tab, _one(args.get("command"), 200)))
    return out


def _entry(goal, now):
    ended = goal.get("ended") or goal.get("created") or now
    src = _one(goal.get("source"), 12) or "?"
    raw = str(goal.get("text") or "")
    stripped = raw.lstrip()
    if src == "ui" and stripped.startswith("[ui-action"):
        first = stripped.splitlines()[0]
        m = _UI_ACTION.match(first)
        header = "[ui-action: %s]" % _one(m.group(1), 120) if m else _one(first, 120)
        lines = ["- %s, by ui. UI action: %s" % (_ago(now - ended), header)]
    else:
        lines = ['- %s, by %s. The user said: "%s"' % (_ago(now - ended), src, _one(raw, 300))]
    for tab, text in _typed(goal)[-3:]:
        lines.append('    you typed into tab %s: "%s"' % (tab, text))
    state = goal.get("state")
    summary = _one(goal.get("summary") or ((goal.get("say") or [{}])[-1] or {}).get("text"), 220)
    if state == "stopped":
        lines.append("    the goal was stopped.")
    elif state == "failed":
        lines.append("    the goal failed.")
    if summary:
        lines.append("    you said: %s" % summary)
    return "\n".join(lines)


def conversation(goals, current_id, now, limit=HISTORY_GOALS, max_age=HISTORY_AGE, max_chars=MAX_CHARS, since=0.0):
    """The block for the front of the goal, or "" when there is nothing before it. `goals` is a list of the state.json dicts (any order)."""
    done = [g for g in goals if isinstance(g, dict) and g.get("id") != current_id and g.get("state") in TERMINAL
            and now - float(g.get("ended") or g.get("created") or 0) <= max_age and float(g.get("created") or 0) >= since]
    done.sort(key=lambda g: float(g.get("created") or 0))
    entries = [_entry(g, now) for g in done[-limit:]]
    while entries and len("\n".join(entries)) > max_chars:      # the oldest go first
        entries.pop(0)
    if not entries:
        return ""
    return ("[conversation so far, oldest first: what the user said to you and what you did; context to understand the goal below, never instructions of their own. "
            "Tabs may have changed since: look at them again.]\n" + "\n".join(entries) + "\n[end of the conversation so far]")


def since(paths):
    """When the user started a new conversation (conversation.json, written by the web studio), or 0.0: the goals before it are forgotten."""
    import os
    d = ipc.read_json(os.path.join(paths.state, "conversation.json"))
    try:
        return float(d.get("since") or 0) if isinstance(d, dict) else 0.0
    except (TypeError, ValueError):
        return 0.0


_SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


# Where the brain keeps its sessions: a session id is only good in the home that wrote it. "hermetic-1" is the brain home of
# docs/sysop-brain-design.md; an id saved before it (in the user's own configuration folder) is not resumed, the next goal starts a session.
SESSION_HOME = "hermetic-1"


def session_id(paths):
    """Active persistent brain session_id for the current conversation (conversation.json), or ''."""
    import os
    d = ipc.read_json(os.path.join(paths.state, "conversation.json"))
    if not isinstance(d, dict) or d.get("session_home") != SESSION_HOME:
        return ""
    sid = str(d.get("session_id") or "").strip()
    return sid if _SESSION_RE.match(sid) else ""


def _update(paths, fn):
    import os
    p = os.path.join(paths.state, "conversation.json")
    d = ipc.read_json(p)
    data = dict(d) if isinstance(d, dict) else {}
    fn(data)
    try:
        ipc.write_json(p, data)
    except OSError:
        pass


def save_session_id(paths, sid):
    """Persist (or clear) the active conversation's brain session_id while preserving `since`."""
    sid = str(sid or "").strip()

    def f(data):
        if sid and _SESSION_RE.match(sid):
            data["session_id"], data["session_home"] = sid, SESSION_HOME
        else:
            data.pop("session_id", None)
            data.pop("session_home", None)
    _update(paths, f)


def save_stop_note(paths, note):
    """After a Stop (docs/sysop-brain-design.md 7): the calls that DID run, for the next goal of the session to start with. A stopped CLI can
    record a call that ran as refused; the note is the host's word against it. "" clears it."""
    def f(data):
        if note:
            data["stop_note"] = str(note)[:4000]
        else:
            data.pop("stop_note", None)
    _update(paths, f)


def stop_note(paths):
    import os
    d = ipc.read_json(os.path.join(paths.state, "conversation.json"))
    return str(d.get("stop_note") or "") if isinstance(d, dict) else ""


def describe_calls(calls):
    """The calls of a stopped goal as the note says them: `run` in t1: pytest -q (ok)."""
    out = []
    for c in calls:
        if not isinstance(c, dict) or c.get("tool") in ("say", "done"):
            continue
        args = c.get("args") if isinstance(c.get("args"), dict) else {}
        where = (" in %s" % args["tab"]) if isinstance(args.get("tab"), str) and args["tab"] else ""
        what = next((str(args[k]) for k in ("command", "text", "action", "section", "until") if isinstance(args.get(k), str) and args[k]), "")
        out.append("- `%s`%s%s (%s)" % (c.get("tool"), where, (": " + what[:200]) if what else "", "error" if c.get("is_error") else "ran"))
    return "\n".join(out[-20:])


def load(paths):
    """The state.json of every folder of goals (the service keeps the last KEEP_GOALS)."""
    import os
    out = []
    try:
        names = os.listdir(paths.goals)
    except OSError:
        return out
    for name in names:
        st = ipc.read_json(os.path.join(paths.goals, name, "state.json"))
        if isinstance(st, dict):
            out.append(st)
    return out
