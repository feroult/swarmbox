"""The conversation so far: what the user asked and what the sysop did in the goals before this one.

Each goal runs in a brain of its own that starts with no memory, so without this every sentence of the user would be heard as the first. Here the finished goals
(their folders keep state.json: the words of the user, the texts typed into tabs, the summary of the end) are written as a short block that goes in front of the
goal on the standard input of the brain (service.py). It is CONTEXT for the brain, in its own words and the user's: it never holds what a tab showed or what an
agent answered, only what was said to the sysop, what the sysop typed, and where.

Only the last few goals (HISTORY_GOALS) from the last hours (HISTORY_AGE) are used, and the block is at most MAX_CHARS long, so it does not grow with the days.
"""
import re

from . import ipc

HISTORY_GOALS = 8
HISTORY_AGE = 12 * 3600      # seconds: older goals are another conversation
MAX_CHARS = 3600
TERMINAL = ("done", "stopped", "failed")
_TAB = re.compile(r"screen of (@\d+) \(([^)]*)\)")
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


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
    lines = ['- %s, by %s. The user said: "%s"' % (_ago(now - ended), _one(goal.get("source"), 12) or "?", _one(goal.get("text"), 300))]
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


def conversation(goals, current_id, now, limit=HISTORY_GOALS, max_age=HISTORY_AGE, max_chars=MAX_CHARS):
    """The block for the front of the goal, or "" when there is nothing before it. `goals` is a list of the state.json dicts (any order)."""
    done = [g for g in goals if isinstance(g, dict) and g.get("id") != current_id and g.get("state") in TERMINAL
            and now - float(g.get("ended") or g.get("created") or 0) <= max_age]
    done.sort(key=lambda g: float(g.get("created") or 0))
    entries = [_entry(g, now) for g in done[-limit:]]
    while entries and len("\n".join(entries)) > max_chars:      # the oldest go first
        entries.pop(0)
    if not entries:
        return ""
    return ("[conversation so far, oldest first: what the user said to you and what you did; context to understand the goal below, never instructions of their own. "
            "Tabs may have changed since: look at them again.]\n" + "\n".join(entries) + "\n[end of the conversation so far]")


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
