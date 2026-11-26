"""The last requests the user typed into an agent tab, read from the agent's own session store.

The auto-namer names a tab after what the user asked, which is shorter and more specific than the screen. Where an agent keeps its
prompts is its addon's knowledge (docs/agents-design.md 3.2), declared in its agent/agent.conf:

- HISTORY=jsonl: a prompt history with one JSON line per typed prompt (Claude Code's `~/.claude/history.jsonl`, agy's): HISTORY_FILE
  (under the home; HISTORY_FILE_ENV names a variable that, when set, is the folder of the file instead), HISTORY_FIELDS (the keys of the
  folder, the session, the text and the time in ms). Read here.
- else its agent/history.py, `messages(cwd, home, now)`, for any other store (OpenCode's SQLite database).

A tab event carries only the cwd, not the agent's session id. When two sessions of the same agent were active in the same folder in
the last AMBIGUOUS_WINDOW seconds, the store cannot tell which one is this tab: the result is empty and the caller falls back to the
screen. The agent's reserved prefixes (slash commands, `!` shell lines) are not requests, and short replies ("ok", "pode sim") are
dropped while longer requests exist. Every reader is best effort: a missing file, a changed format or a locked database gives [] and
never raises.
"""
import json
import os
import re
import time

from .agents import registry

MAX_MESSAGES = 4
MAX_MESSAGE_CHARS = 280
TAIL_BYTES = 512 * 1024   # the newest prompts of every folder; a history line is a few hundred bytes
AMBIGUOUS_WINDOW = 600.0

MIN_WORDS = 3   # "ok", "pode sim", "go on" carry no goal: they are dropped while longer requests exist


def _clip(text):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > MAX_MESSAGE_CHARS:
        s = s[:MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return s


def _tail_lines(path, max_bytes=TAIL_BYTES):
    """The complete lines in the last max_bytes of a file (the first, partial line is dropped)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start)
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines


def _history_messages(path, cwd, now, folder_key, session_key, text_key="display", ts_key="timestamp", reserved=("/", "!")):
    """The prompts of the latest session in `cwd` from a prompt history JSONL (one line per prompt, timestamps in ms)."""
    try:
        lines = _tail_lines(path)
    except OSError:
        return []
    by_session = {}
    last_ts = {}
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get(folder_key) != cwd or rec.get("type") == "slash_command":
            continue
        text = str(rec.get(text_key) or "").strip()
        if not text or (reserved and text.startswith(reserved)):
            continue
        sid = str(rec.get(session_key) or "")
        try:
            ts = float(rec.get(ts_key) or 0) / 1000.0
        except (TypeError, ValueError):
            ts = 0.0
        by_session.setdefault(sid, []).append(text)
        last_ts[sid] = max(last_ts.get(sid, 0.0), ts)
    if not by_session:
        return []
    ranked = sorted(last_ts.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and now - ranked[1][1] < AMBIGUOUS_WINDOW:
        return []
    return by_session[ranked[0][0]]


def _jsonl_messages(a, cwd, home, now):
    h = a["history"]
    rel = h["file"]
    path = os.path.join(home, rel)
    if h["file_env"] and os.environ.get(h["file_env"]):
        path = os.path.join(os.environ[h["file_env"]], os.path.basename(rel))
    folder, session, text, ts = h["fields"]
    return _history_messages(path, cwd, now, folder, session, text, ts, tuple(p for p in a["reserved_prefixes"] if p))


def _reader(agent):
    """the reader of an agent's prompts: its history.py, its declared JSONL history, or None"""
    a = registry.get(registry.resolve(agent))
    if not a:
        return None
    mod = registry.hook(a["id"], "history")
    if mod is not None and hasattr(mod, "messages"):
        return mod.messages
    if a["history"]["kind"] == "jsonl" and a["history"]["file"] and len(a["history"]["fields"]) == 4:
        return lambda cwd, home, now: _jsonl_messages(a, cwd, home, now)
    return None


def recent(agent, cwd, home=None, now=None, limit=MAX_MESSAGES):
    """Up to `limit` of the user's last requests in this agent and folder, oldest first, each clipped; [] when unknown."""
    reader = _reader(str(agent or "").strip().lower())
    if reader is None or not cwd:
        return []
    home = home or os.environ.get("HOME") or os.path.expanduser("~")
    now = time.time() if now is None else float(now)
    try:
        msgs = reader(str(cwd).rstrip("/") or "/", home, now)
    except Exception:
        return []
    clipped = [c for c in (_clip(m) for m in msgs) if c]
    kept = [c for c in clipped if len(c.split()) >= MIN_WORDS] or clipped
    out = []
    for c in kept:
        if not out or out[-1] != c:      # a prompt sent twice in a row counts once
            out.append(c)
    return out[-limit:]
