"""Mux-agnostic presentation state of the sysop: reading the files of the service and turning them into clean text,
a one-line summary (`line_of`, `value_of`) or a structured dictionary (`state_dict`) for any UI (terminal panel, web, mobile).

Zero dependency on the multiplexer or any terminal emulator.
"""
import os
import unicodedata
from collections import namedtuple

from . import ipc, service

TERMINAL = ("done", "stopped", "failed")
IDLE = ("idle", "")
PREFIX = "sysop"
MAX_TEXT = 140
SHOW_END = 10.0

Snap = namedtuple("Snap", "up bus gid goal pending queue settings")


def clean(text, limit=4000):
    """Text from the service made safe to print: control and format characters (escape sequences, bidi overrides) become U+FFFD."""
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    out = []
    for ch in text[:limit]:
        if ch == "\n":
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            out.append("\ufffd")
        else:
            out.append(ch)
    return "".join(out)


def one_line(text, limit):
    return clean(text, 4000).replace("\n", " ").strip()[:limit]


def step_text(call):
    """One tool call as a few plain words: `read tab 1`, `run: ls -la`, `type: fix the tests`."""
    a = call.get("args") if isinstance(call.get("args"), dict) else {}
    tool = one_line(call.get("tool"), 30)
    tab = one_line(a.get("tab"), 12)
    if tool in ("box_state", "list_tabs"):
        sec = one_line(a.get("section"), 16)
        return "inspect %s state" % sec if sec and sec != "workspace" else "inspect box state"
    if tool == "read_tab":
        return "read tab %s" % tab if tab else "read a tab"
    if tool == "tab":
        act = one_line(a.get("action"), 16)
        what = one_line(a.get("name") or a.get("title") or a.get("repo") or a.get("agent") or a.get("pin_id") or tab, 40)
        return "%s tab %s" % (act, what) if what else ("%s tab" % act if act else "tab")
    if tool == "worktree":
        act = one_line(a.get("action"), 16)
        tgt = one_line(a.get("target") or tab, 24)
        return "worktree %s %s" % (act, tgt) if tgt else ("worktree %s" % act if act else "worktree")
    if tool in ("run", "input"):
        what = one_line(a.get("command") if tool == "run" else a.get("text"), 200)
        return "%s: %s" % ("run" if tool == "run" else "type", what)
    if tool == "wait":
        return "wait"
    return tool


def snapshot(pth, last_gid=None):
    """What the files say now. The goal is the running one, else `last_gid` (the last one seen), so that its end stays visible.
    The calls and the says of a running goal are read from the files of the MCP server (fresher than state.json)."""
    up = service.running(pth)
    st = ipc.read_json(pth.status) if up else None
    st = st if isinstance(st, dict) else {}
    cur = service.sanitize(st.get("current"), "") if st.get("current") else ""
    gid = cur or last_gid or ""
    goal, pending = None, None
    if up and gid:
        gdir = pth.goal_dir(gid)
        goal = ipc.read_json(os.path.join(gdir, "state.json"))
        goal = goal if isinstance(goal, dict) else None
        if goal is not None and cur and goal.get("state") not in TERMINAL:
            goal = dict(goal)
            calls = ipc.read_jsonl(os.path.join(gdir, "calls.jsonl"), last=service.RECENT_CALLS)
            says = ipc.read_jsonl(os.path.join(gdir, "say.jsonl"), last=20)
            goal["calls"], goal["say"] = calls or goal.get("calls") or [], says or goal.get("say") or []
            p = ipc.read_json(os.path.join(gdir, "pending_action.json"))
            pending = p if isinstance(p, dict) and p.get("id") else None
    queue = st.get("queue") if isinstance(st.get("queue"), list) else []
    return Snap(up, str(st.get("bus", "")), gid if goal else "", goal, pending, [q for q in queue if isinstance(q, dict)],
                st.get("settings") if isinstance(st.get("settings"), dict) else {})


def _cut(text, limit=MAX_TEXT):
    text = one_line(text, 4000)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _last_thing(goal):
    """The latest of what the sysop said and of its steps (the tool done is not a step), in plain words."""
    best = None
    items = [("say", s) for s in goal.get("say") or [] if isinstance(s, dict)]
    items += [("call", c) for c in goal.get("calls") or [] if isinstance(c, dict) and c.get("tool") != "done"]
    for kind, it in items:
        t = it.get("t") if isinstance(it.get("t"), (int, float)) else 0
        if best is None or t >= best[0]:
            best = (t, kind, it)
    if best is None:
        return ""
    return one_line(best[2].get("text"), 4000) if best[1] == "say" else step_text(best[2])


def line_of(snap, wall=0.0):
    """(state, sentence) of what the files say, or None when there is nothing to show. `wall`: the time now, for how long an ended goal stays."""
    if not snap.up:
        return None
    if snap.pending:
        pmode = "veto" if snap.pending.get("mode") == "veto" else "approve"
        what = _cut(snap.pending.get("text"))
        return ("allow?" if pmode == "approve" else "sending", what or "an action")
    g = snap.goal
    if g:
        st = g.get("state")
        if st in TERMINAL:
            ended = g.get("ended")
            if isinstance(ended, (int, float)) and wall and wall - ended > SHOW_END:
                return IDLE
            return (st, _cut(g.get("summary") or g.get("error") or st))
        if st == "queued":
            return ("queued", _cut(g.get("text")))
        if st == "waiting_approval":
            return ("allow?", _cut(g.get("text")))
        return ("working", _cut(_last_thing(g) or g.get("text")))
    if snap.queue:
        return ("queued", "%d queued" % len(snap.queue))
    return IDLE


def value_of(line):
    return None if line is None else "%s:%s:%s" % (PREFIX, line[0], line[1])


def state_dict(snap, wall=0.0):
    """JSON-serializable representation of `snap` for the UIs (web gateway, cockpit, mobile client, CLI)."""
    ln = line_of(snap, wall)
    return {
        "up": bool(snap.up),
        "bus": snap.bus,
        "state": ln[0] if ln else "off",
        "sentence": ln[1] if ln else "",
        "goal_id": snap.gid,
        "goal": snap.goal,
        "pending": snap.pending,
        "queue": snap.queue,
        "settings": snap.settings,
    }
