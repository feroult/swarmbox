"""The context a planner sees: a tmux snapshot, limited by the host, with obvious secrets cut.

snapshot(tmux, session)     -> [pane dict]   raw panes of a tmux session (id, window, cwd, command, tail, active); the voice panel is left out
                                             (it is never a target and its text never reaches a planner); `active` is the active pane of the
                                             window the session shows, and when that is the panel, the pane that was active before it
limit_context(panes, ...)   -> [pane dict]   at most max_panes panes (the active one first), tail_lines lines, secrets redacted
build_input(utterance, active_pane, panes, ...) -> the planner input dict (contract keys only)
redact(text)                -> text with secrets replaced by [REDACTED]
"""
import os
import re

from . import contract
from .tmuxrun import PANEL_COMMAND, PANEL_MARK, PANEL_OPTION, SEP, Tmux

MAX_PANES = 8
TAIL_LINES = 40
TAIL_CHARS = 4000
MAX_UTTERANCE = 1000
MAX_FIELD = 200
REDACTED = "[REDACTED]"
_SEP = SEP

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    # the body of a key whose BEGIN line fell outside the captured window: two or more long base64 lines in a row
    re.compile(r"(?m)^[ \t]*[A-Za-z0-9+/=]{32,}[ \t]*(?:\n[ \t]*[A-Za-z0-9+/=]{32,}[ \t]*)+"),
]
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_AUTH = re.compile(r"(?i)\b(authorization|x-api-key|api-key|proxy-authorization)\s*[:=]\s*[^\r\n]+")
_ASSIGN = re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:key|token|secret|passw(?:or)?d|passwd|credential)[A-Za-z0-9_.-]*)([\"']?\s*[=:]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"']+)")
_FLAG = re.compile(r"(?i)(--[a-z0-9-]*(?:key|token|secret|passw(?:or)?d|passwd|credential)[a-z0-9-]*)(\s+)(?!-)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
_USERFLAG = re.compile(r"(?<!\S)(-u|--user|--proxy-user)(\s+)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
_URLCRED = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):[^/\s@]+@")


def redact(text):
    for pat in _PATTERNS:
        text = pat.sub(REDACTED, text)
    text = _AUTH.sub(lambda m: m.group(1) + ": " + REDACTED, text)
    text = _BEARER.sub(lambda m: m.group(1) + " " + REDACTED, text)
    text = _URLCRED.sub(lambda m: m.group(1) + ":" + REDACTED + "@", text)
    text = _FLAG.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    text = _USERFLAG.sub(lambda m: m.group(1) + m.group(2) + REDACTED if ":" in m.group(3) else m.group(0), text)
    text = _ASSIGN.sub(lambda m: m.group(1) + m.group(2) + REDACTED if m.group(3) != REDACTED else m.group(0), text)
    return text


def _clip(value, limit=MAX_FIELD):
    return str(value if value is not None else "")[:limit].replace("\x00", "")


def limit_context(panes, active_pane=None, max_panes=MAX_PANES, tail_lines=TAIL_LINES, tail_chars=TAIL_CHARS):
    """Copy of panes with only the contract fields, limited and redacted. The active pane is kept first."""
    clean = [p for p in panes if isinstance(p, dict) and contract.PANE_ID.fullmatch(str(p.get("id", "")))]
    clean.sort(key=lambda p: p["id"] != active_pane)  # stable: active first
    out = []
    for p in clean[:max(0, max_panes)]:
        tail = str(p.get("tail") or "").replace("\x00", "")
        lines = tail.splitlines()[-tail_lines:] if tail_lines > 0 else []
        tail = redact("\n".join(lines))
        if len(tail) > tail_chars:
            tail = tail[-tail_chars:]
        out.append({"id": p["id"], "window": _clip(redact(_clip(p.get("window")))), "cwd": _clip(p.get("cwd")),
                    "command": _clip(p.get("command")), "tail": tail})
    return out


def build_input(utterance, active_pane, panes, **limits):
    """The planner input: contract keys only, the panes limited and redacted. active_pane must be a listed pane or null."""
    limited = limit_context(panes, active_pane, **limits)
    if active_pane not in [p["id"] for p in limited]:
        active_pane = None
    return contract.build_input(str(utterance)[:MAX_UTTERANCE], active_pane, limited)


def snapshot(tmux=None, session="main", tail_lines=TAIL_LINES):
    """Raw panes of a tmux session, tails captured; [] when tmux or the session is missing. Never raises.
    The voice panel is left out. `active` marks the active pane of the window the session shows; when the panel has the focus in that
    window the pane that was active before it (tmux's "last pane") stands in, or the first pane of the window."""
    tmux = tmux or Tmux()
    fmt = _SEP.join(["#{pane_id}", "#{window_name}", "#{pane_current_path}", "#{pane_current_command}", "#{pane_active}", "#{window_active}",
                     "#{pane_last}", "#{%s}" % PANEL_OPTION, "#{pane_start_command}", "#{window_id}"])
    res = tmux.run("list-panes", "-s", "-t", "=" + session, "-F", fmt)
    if res.rc != 0:
        return []
    home = os.path.expanduser("~")
    rows, seen, panel_has_focus_in = [], set(), None
    for line in res.out.splitlines():
        parts = line.split(_SEP)
        if len(parts) != 10 or parts[0] in seen or not contract.PANE_ID.fullmatch(parts[0]):
            continue
        seen.add(parts[0])
        if parts[7] == PANEL_MARK or PANEL_COMMAND in parts[8]:
            if parts[4] == "1" and parts[5] == "1":
                panel_has_focus_in = parts[9]
            continue
        rows.append(parts)
    shown = [p for p in rows if p[5] == "1"]
    active = None
    if panel_has_focus_in is not None:
        mine = [p for p in shown if p[9] == panel_has_focus_in]
        active = next((p[0] for p in mine if p[6] == "1"), mine[0][0] if mine else None)
    panes = []
    for parts in rows:
        cwd = parts[2]
        if home and home != "/" and (cwd == home or cwd.startswith(home + "/")):
            cwd = "~" + cwd[len(home):]
        cap = tmux.run("capture-pane", "-p", "-J", "-t", parts[0], "-S", "-%d" % max(1, tail_lines))
        tail = "\n".join(cap.out.rstrip("\n").splitlines()[-tail_lines:]) if cap.rc == 0 else ""
        is_active = parts[0] == active if panel_has_focus_in is not None else (parts[4] == "1" and parts[5] == "1")
        panes.append({"id": parts[0], "window": parts[1], "cwd": cwd, "command": parts[3], "tail": tail, "active": is_active})
    return panes
