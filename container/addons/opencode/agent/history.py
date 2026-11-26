"""OpenCode's prompt history for the sysop's tab naming (docs/agents-design.md 3.2): the user's last requests in a folder.

OpenCode 2.3 keeps its sessions in the SQLite `~/.local/share/opencode/opencode.db` (XDG_DATA_HOME): `session_v2.directory` is the cwd,
`session_message` rows with `type = 'user'` carry `{"text": ...}` in `data`. When two sessions were active in the same folder in the last
AMBIGUOUS_WINDOW seconds, the store cannot tell which one is the tab: nothing. Best effort: a missing file, a changed format or a locked
database gives [] (the caller falls back to the screen). Loaded by the agent registry (swarmbox_agents.hook); standard library only.
"""
import json
import os
import sqlite3

AMBIGUOUS_WINDOW = 600.0
MAX_ROWS = 8


def db_path(home):
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(data, "opencode", "opencode.db")


def messages(cwd, home, now):
    """the texts of the user's messages of the latest session in `cwd`, oldest first"""
    path = db_path(home)
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
            (rows[0][0], MAX_ROWS),
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
