"""The last requests the user typed into an agent tab, read from the agent's own session store.

The auto-namer names a tab after what the user asked, which is shorter and more specific than the screen. Each agent keeps its
prompts in a different place (measured on the box, November 2026):

- claude (Claude Code 2.1): the prompt history `~/.claude/history.jsonl` (`$CLAUDE_CONFIG_DIR`), one line per typed prompt:
  `display`, `project` (the cwd), `sessionId`, `timestamp` (ms). Small, unlike a session transcript, which tool results grow to
  megabytes.
- agy (Antigravity CLI): `~/.gemini/antigravity-cli/history.jsonl`, the same shape with `workspace` and `conversationId`, and
  `type: slash_command` for commands.
- opencode (2.3): the SQLite `~/.local/share/opencode/opencode.db`: `session_v2.directory` is the cwd, `session_message` rows with
  `type = 'user'` carry `{"text": ...}` in `data`.

A tab event carries only the cwd, not the agent's session id. When two sessions of the same agent were active in the same folder in
the last AMBIGUOUS_WINDOW seconds, the store cannot tell which one is this tab: the result is empty and the caller falls back to the
screen. Slash commands and `!` shell lines are not requests, and short replies ("ok", "pode sim") are dropped while longer requests
exist. Every reader is best effort: a missing file, a changed format or a locked database gives [] and never raises.
"""
import json
import os
import re
import sqlite3
import time

MAX_MESSAGES = 4
MAX_MESSAGE_CHARS = 280
TAIL_BYTES = 512 * 1024   # the newest prompts of every folder; a history line is a few hundred bytes
AMBIGUOUS_WINDOW = 600.0

# Claude Code writes these as user lines, but the user did not type them as a request.
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


def _history_messages(path, cwd, now, folder_key, session_key):
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
        text = str(rec.get("display") or "").strip()
        if not text or text.startswith(("/", "!")):
            continue
        sid = str(rec.get(session_key) or "")
        try:
            ts = float(rec.get("timestamp") or 0) / 1000.0
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


def claude_messages(cwd, home, now):
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    return _history_messages(os.path.join(base, "history.jsonl"), cwd, now, "project", "sessionId")


def agy_messages(cwd, home, now):
    path = os.path.join(home, ".gemini", "antigravity-cli", "history.jsonl")
    return _history_messages(path, cwd, now, "workspace", "conversationId")


def opencode_db_path(home):
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(data, "opencode", "opencode.db")


def opencode_messages(cwd, home, now):
    path = opencode_db_path(home)
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1.0)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT id, time_updated FROM session_v2 WHERE directory = ? AND parent_id IS NULL AND time_archived IS NULL "
            "ORDER BY time_updated DESC LIMIT 2",
            (cwd,),
        ).fetchall()
        if not rows:
            return []
        if len(rows) > 1 and now - float(rows[1][1] or 0) / 1000.0 < AMBIGUOUS_WINDOW:
            return []
        datas = con.execute(
            "SELECT data FROM session_message WHERE session_id = ? AND type = 'user' ORDER BY seq DESC LIMIT ?",
            (rows[0][0], MAX_MESSAGES * 2),
        ).fetchall()
    except (sqlite3.Error, TypeError, ValueError):
        return []
    finally:
        con.close()
    out = []
    for (raw,) in reversed(datas):
        try:
            text = str(json.loads(raw).get("text") or "").strip()
        except (ValueError, AttributeError):
            continue
        if text:
            out.append(text)
    return out


READERS = {"claude": claude_messages, "agy": agy_messages, "opencode": opencode_messages}


def recent(agent, cwd, home=None, now=None, limit=MAX_MESSAGES):
    """Up to `limit` of the user's last requests in this agent and folder, oldest first, each clipped; [] when unknown."""
    reader = READERS.get(str(agent or "").strip().lower())
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
