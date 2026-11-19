"""The panel of the sysop: `swarmbox-sysop panel`, a text program for a tmux pane. Stdlib only (raw ANSI, termios, select).

It is small and quiet: the state in one word, the goal, a line for each step, and at the bottom what needs YOU, as a coloured bar, the text of
the action and two big buttons (Allow, Cancel). In the countdown (sending in N s) only Cancel is there. What you type becomes a goal.
The panel NEVER takes the focus by itself (dock.py opens it with -d). To act without focusing it: the buttons of the web strip, or `Ctrl+A` then
a (allow), V (cancel: refuses what waits, or stops the goal), g (goal). With the focus, or a click on a button:
Keys:   a or y  allow the action that waits        c or n  cancel it (it is NOT sent); with nothing waiting, stop the goal
        x  stop the goal that runs (X: the goal and the whole queue)         g  type a goal (Enter sends it with source `panel`, Esc aborts)
        q  close the panel (the goal goes on)         Up/Down/PgUp/PgDn  scroll the log (Down to the end follows the log again)
Keys are ignored for GUARD seconds after a new action appears: typing meant for another pane must not answer it.

It reads the files of the service (ipc.py: status.json, goals/<id>/state.json, calls.jsonl, say.jsonl, pending_action.json), writes decision.json
and stop.request, and publishes goals on the bus. Everything it prints that came from a tab or from the model is untrusted: control and
bidi characters are replaced (clean). When the service is down it says so and goes on looking; `q` closes it.

Parts, each testable alone: Model (state and keys, no I/O), render (state and size -> text), KeyParser, LineEditor, snapshot (the files ->
state) and Panel (the terminal loop).
"""
import errno
import os
import select
import signal
import subprocess
import sys
import termios
import time
import tty
import unicodedata
from collections import namedtuple

from . import busclient, config, dock, ipc, paths as pathsmod, service

GUARD = 0.5             # seconds after a new pending action appears in which keys are ignored
ESC_WAIT = 0.05         # a lone ESC is a key when nothing follows within this long
POLL = 0.2              # seconds between two looks at the files while something happens (a goal, a countdown, you typing)
IDLE_POLL = 1.0         # idle: once a second only a stat of two files and a lock probe; the files are read when one of them changed
WEB_EVERY = 2.0          # seconds between two looks at the clients of tmux to tell the browser from a terminal
MAX_EDIT = service.MAX_GOAL_TEXT
GOAL_LINES = 3
HEAD_GAP_ROWS = 7       # a panel of a phone this tall (or taller) has a blank line under its head
WIDE_GAP_ROWS = 14      # elsewhere (the tall panel at the right of a desktop) it takes this many rows: a short panel keeps its rows for the content
WIDE_COLS = 80          # ... and is this many columns wide at most: the panel docked at the bottom of a wide window has no strip for buttons
STRIP_ROWS = 3           # the lines of that strip: two for the bar of buttons, and a third of space between the bar and the content
DONE_LINES = 3          # lines of how a goal ended
MIN_LOG = 2             # lines of the log kept in a short pane (the end of it: the result of a goal)
LAST_FRESH = 30 * 86400  # seconds a finished goal is still shown as the last one when the panel opens
TERMINAL = ("done", "stopped", "failed")

PALETTE = {"violet": "a78bfa", "deep": "6d28d9", "lavender": "c4b5fd", "dim": "a1a1aa", "text": "d4d4d8", "red": "ff6b78",
           "amber": "fbbf24", "green": "4ade80", "line": "52525b", "ink": "0c0b10", "band": "2a1a52"}
RESET = "\x1b[0m"
CLOSE = " ✕ close "      # the close control of the panel of a narrow window; nine cells, a thumb can hit it


def fg(name):
    h = PALETTE[name]
    return "\x1b[38;2;%d;%d;%dm" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def bg(name):
    h = PALETTE[name]
    return "\x1b[48;2;%d;%d;%dm" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


# ---------------------------------------------------------------------------------------------------------------------- text helpers

def clean(text, limit=4000):
    """Text from the service made safe to print: control and format characters (escape sequences, bidi overrides) become U+FFFD."""
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    out = []
    for ch in text[:limit]:
        if ch == "\n":
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            out.append("�")
        else:
            out.append(ch)
    return "".join(out)


def cell_width(ch):
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def text_width(text):
    return sum(cell_width(c) for c in text)


def wrap(text, width):
    """Lines of at most `width` cells: at a space when there is one, in the middle of a word when there is none. '\\n' ends a line."""
    width = max(1, width)
    out = []
    for para in text.split("\n"):
        line, w, last_space = "", 0, -1
        for ch in para:
            cw = cell_width(ch)
            if w + cw > width and line:
                if ch == " ":                      # the line is full and the next character is the space between words: break there
                    out.append(line.rstrip())
                    line, w, last_space = "", 0, -1
                    continue
                if last_space > 0:
                    out.append(line[:last_space].rstrip())
                    line = line[last_space + 1:]
                    w = text_width(line)
                else:
                    out.append(line)
                    line, w = "", 0
                last_space = -1
            if ch == " ":
                last_space = len(line)
            line += ch
            w += cw
        out.append(line)
    return out


def clock(seconds):
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


# ---------------------------------------------------------------------------------------------------------------------- line editor

class LineEditor:
    """One line of text with a cursor: left, right, home, end, backspace, delete and typing. No history, no multi-line."""

    def __init__(self, text="", limit=MAX_EDIT):
        self.text, self.pos, self.limit = text[:limit], len(text[:limit]), limit

    def key(self, k):
        """Apply one key (a name such as 'left' or a single character). True when it changed something."""
        t, p = self.text, self.pos
        if k == "left":
            self.pos = max(0, p - 1)
        elif k == "right":
            self.pos = min(len(t), p + 1)
        elif k in ("home", "ctrl-a"):
            self.pos = 0
        elif k in ("end", "ctrl-e"):
            self.pos = len(t)
        elif k == "backspace":
            if p:
                self.text, self.pos = t[:p - 1] + t[p:], p - 1
        elif k == "delete":
            self.text = t[:p] + t[p + 1:]
        elif k == "ctrl-u":
            self.text, self.pos = t[p:], 0
        elif len(k) == 1 and k >= " " and k != "\x7f" and len(t) < self.limit:
            self.text, self.pos = t[:p] + k + t[p:], p + 1
        else:
            return False
        return (self.text, self.pos) != (t, p)

    def view(self, width):
        """(visible text, cursor offset in it, cut on the left, cut on the right) for a line `width` cells wide."""
        width = max(4, width)
        start = 0
        while start < self.pos and text_width(self.text[start:self.pos]) > width - 1:   # keep the cursor inside, one cell to spare
            start += 1
        shown, w = "", 0
        for ch in self.text[start:]:
            cw = cell_width(ch)
            if w + cw > width:
                break
            shown += ch
            w += cw
        return shown, text_width(self.text[start:self.pos]), start > 0, start + len(shown) < len(self.text)


# ---------------------------------------------------------------------------------------------------------------------- keys

class KeyParser:
    """Terminal input bytes -> keys. A key is a one-character string (typed text) or a name: up down left right home end delete backspace
    enter esc tab pgup pgdn ctrl-a ctrl-c ctrl-e ctrl-u focus-in focus-out, or a tuple ('click', col, row) / ('wheel', 'up'|'down')."""

    CSI = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end", "I": "focus-in", "O": "focus-out"}
    TILDE = {"1": "home", "3": "delete", "4": "end", "5": "pgup", "6": "pgdn", "7": "home", "8": "end"}
    CTRL = {"\x01": "ctrl-a", "\x03": "ctrl-c", "\x05": "ctrl-e", "\x15": "ctrl-u", "\r": "enter", "\n": "enter", "\x7f": "backspace",
            "\x08": "backspace", "\t": "tab"}

    def __init__(self):
        self.buf = b""

    def pending(self):
        return bool(self.buf)

    def feed(self, data):
        self.buf += data
        return self._parse(False)

    def flush(self):
        """Called after ESC_WAIT with no new bytes: a lone ESC is the Escape key."""
        return self._parse(True)

    def _parse(self, final):
        keys = []
        b = self.buf
        while b:
            c = b[0]
            if c == 0x1b:
                if len(b) == 1:
                    if final:
                        keys.append("esc")
                        b = b""
                    break
                if b[1:2] in (b"[", b"O"):
                    j = 2
                    while j < len(b) and not (0x40 <= b[j] <= 0x7e):
                        j += 1
                    if j >= len(b):
                        if final:
                            b = b""
                        break
                    body, last = b[2:j].decode("latin-1"), chr(b[j])
                    b = b[j + 1:]
                    k = self._csi(body, last)
                    if k:
                        keys.append(k)
                    continue
                b = b[1:]   # ESC followed by something else: the ESC alone
                keys.append("esc")
                continue
            if c < 0x20 or c == 0x7f:
                k = self.CTRL.get(chr(c))
                if k:
                    keys.append(k)
                b = b[1:]
                continue
            n = 1 if c < 0x80 else (2 if c >> 5 == 0b110 else 3 if c >> 4 == 0b1110 else 4 if c >> 3 == 0b11110 else 1)
            if len(b) < n:
                if final:
                    b = b""
                break
            try:
                keys.append(b[:n].decode("utf-8"))
            except UnicodeDecodeError:
                pass
            b = b[n:]
        self.buf = b
        return keys

    def _csi(self, body, last):
        if body.startswith("<") and last in "Mm":      # SGR mouse: button;col;row
            try:
                btn, col, row = (int(x) for x in body[1:].split(";"))
            except ValueError:
                return None
            if btn & 64:
                return ("wheel", "up" if btn & 1 == 0 else "down")
            if last == "M" and btn & 3 == 0 and not btn & 32:
                return ("click", col, row)
            return None
        if last == "~":
            return self.TILDE.get(body.split(";")[0])
        return self.CSI.get(last)


def strip_ansi(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == "\x1b" and text[i + 1:i + 2] == "[":
            j = i + 2
            while j < len(text) and not (0x40 <= ord(text[j]) <= 0x7e):
                j += 1
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------------------------------------------------- the files -> state

Snap = namedtuple("Snap", "up bus gid goal pending queue settings")


def snapshot(pth, last_gid=None):
    """What the files say now. The goal is the running one, else `last_gid` (the last one seen), so that its end stays on screen. The calls and the
    says of a running goal are read from the files of the MCP server (fresher than state.json, which the service rewrites every few tenths of a second)."""
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


# ---------------------------------------------------------------------------------------------------------------------- model

class Model:
    """What the panel knows and what its keys do. No I/O: key() returns a command for the caller to carry out:
    ("decide", gid, pending id, "veto"|"deny"|"approve", word or None), ("stop", goal id or None), ("goal", text), ("quit",) or None."""

    def __init__(self, now=0.0):
        self.up = None              # None: not looked yet
        self.bus, self.gid, self.goal, self.pending, self.queue, self.settings = "", "", None, None, [], {}
        self.mode = "view"          # view | edit
        self.notice, self.draft = "", ""
        self.editor = None
        self.scroll = 0             # lines back from the end of the log; 0 follows it
        self.ready_at = 0.0
        self.pending_key = None
        self.focused = None       # True/False after the first focus event of tmux; None until then (not known)
        self.hidden = 0           # characters of the pending action the last render did not show (set by _pending_lines)
        self.finished = False
        self.quit_key = False     # the panel ends because q was pressed (not because it was killed): in the mode always that hides the panels
        self.panel_mode = "auto"  # the setting sysop.panel; "always" makes q hide the panels of all windows
        self.approval_only = False  # the approval pane (dock.APPROVAL_ENV): it answers the action that waits and does nothing else

    # -------- the state
    def update(self, snap, now):
        self.up, self.bus, self.gid, self.goal, self.queue, self.settings = snap.up, snap.bus, snap.gid, snap.goal, snap.queue, snap.settings
        p = snap.pending
        key = (snap.gid, str(p.get("id"))) if p else None
        if key != self.pending_key:
            self.pending_key = key
            if p:
                self.ready_at = now + GUARD
                if self.mode == "edit":      # the countdown runs while you type: the editor yields, the text is kept
                    self.draft, self.editor, self.mode = self.editor.text, None, "view"
                    self.notice = "An action is waiting: answer it first. Your text is kept (g)."
        self.pending = p

    def pmode(self):
        return "veto" if self.pending and self.pending.get("mode") == "veto" else "approve"      # an unknown mode gets the strongest treatment

    def risk(self):
        r = self.pending.get("risk") if self.pending else None
        return r if r in ("low", "medium", "high") else "high"

    def remaining(self, wall):
        try:
            return float(self.pending.get("deadline")) - wall
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def live(self, wall):
        return bool(self.pending) and self.remaining(wall) > 0

    def running(self):
        return bool(self.goal) and self.goal.get("state") not in TERMINAL

    def quiet(self):
        """Nothing is going on that the next look could change before a file does: the service is down, or it is idle (no goal, no queue,
        no action waiting) and you are not typing. The loop then looks once a second, and reads the files only when one of them changed."""
        if self.up is None:
            return False
        if not self.up:
            return True
        return not self.pending and not self.queue and self.mode == "view" and (not self.goal or self.goal.get("state") in TERMINAL)

    # -------- keys
    def key(self, k, now, wall):
        if self.finished or now < self.ready_at or isinstance(k, tuple):
            return None
        if self.mode == "edit":
            return self._key_edit(k)
        return self._key_view(k, wall)

    def _key_view(self, k, wall):
        self.notice = ""
        low = k.lower() if isinstance(k, str) and len(k) == 1 else k
        if self.approval_only:
            if low in ("a", "y") and self.live(wall) and self.pmode() == "approve":
                if self.hidden:
                    self.notice = "The whole action is not on the screen, so it cannot be allowed: cancel it."
                else:
                    return ("decide", self.gid, str(self.pending["id"]), "approve", "run")
            elif low in ("c", "n") and self.live(wall) and self.pmode() == "approve":
                return ("decide", self.gid, str(self.pending["id"]), "deny", None)
            return None            # nothing else: no scrolling, no goal, no stop, and a stray q does not close it (it closes by itself)
        if low in ("q", "ctrl-c"):
            return ("quit",)
        if low in ("up", "k"):
            self.scroll += 1
        elif low in ("down", "j"):
            self.scroll = max(0, self.scroll - 1)
        elif low == "pgup":
            self.scroll += 5
        elif low in ("pgdn", " "):
            self.scroll = max(0, self.scroll - 5)
        elif low == "home":
            self.scroll = 10 ** 6
        elif low == "end":
            self.scroll = 0
        elif low in ("a", "y"):
            if self.live(wall):
                if self.hidden:
                    self.notice = "The whole action is not on the screen, so it cannot be allowed: cancel it or make the pane bigger."
                else:
                    return ("decide", self.gid, str(self.pending["id"]), "approve", "run")
        elif low in ("c", "n"):
            if self.live(wall):
                return ("decide", self.gid, str(self.pending["id"]), "veto" if self.pmode() == "veto" else "deny", None)
            if self.running() or self.queue:
                return ("stop", None)
        elif low == "x":
            target = self.gid if self.running() else (self.queue[0].get("id") if self.queue else None)
            if not target:
                self.notice = "There is no goal to stop."
            else:
                return ("stop", None if k == "X" else str(target))
        elif low == "g":
            if not self.up:
                self.notice = "The sysop is not running: a goal would have nobody to run it."
            elif self.live(wall):
                self.notice = "An action is waiting: answer it first."
            else:
                self.mode, self.editor = "edit", LineEditor(self.draft, MAX_EDIT)
        return None

    def _key_edit(self, k):
        if k in ("esc", "ctrl-c"):
            self.mode, self.editor, self.draft = "view", None, ""
        elif k == "enter":
            text = self.editor.text.strip()
            self.mode, self.editor, self.draft = "view", None, ""
            if text:
                return ("goal", text)
        elif isinstance(k, str):
            self.editor.key(k)
        return None


# ---------------------------------------------------------------------------------------------------------------------- render

Frame = namedtuple("Frame", "lines cursor hits")   # lines: `rows` ANSI strings; cursor: (row, col) 1-based or None; hits: [(row, c0, c1, key)]

RISK_COLOR = {"low": "green", "medium": "amber", "high": "red"}


def _paint(color, name, text, bold=False):
    if not color or not (name or bold):
        return text
    return ("\x1b[1m" if bold else "") + (fg(name) if name else "") + text + RESET


SHOW_LINES = 4      # rows of the pending action's text; a longer one shows how many characters are left out, and cannot be approved


def one_line(text, limit):
    return clean(text, 4000).replace("\n", " ").strip()[:limit]


def cut(text, width):
    """text cut to `width` cells, with an ellipsis."""
    if text_width(text) <= width:
        return text
    out, w = "", 0
    for ch in text:
        cw = cell_width(ch)
        if w + cw > width - 1:
            break
        out, w = out + ch, w + cw
    return out + "…"


def state_of(model):
    """The state as one lowercase word and a colour: what the sysop is doing, in the words of someone who just asked for something."""
    if not model.up:
        return "off", "red"
    if model.pending:
        return ("allow?", "red") if model.pmode() == "approve" else ("sending", "amber")
    return {"running": ("working", "green"), "queued": ("queued", "dim"), "waiting_approval": ("waiting", "amber"), "done": ("done", "green"),
            "failed": ("failed", "red"), "stopped": ("stopped", "amber")}.get(model.goal.get("state") if model.goal else None, ("idle", "dim"))


def step_text(call):
    """One tool call as a few plain words: `read tab 1`, `run: ls -la`, `type: fix the tests`."""
    a = call.get("args") if isinstance(call.get("args"), dict) else {}
    tool = one_line(call.get("tool"), 30)
    tab = one_line(a.get("tab"), 12)
    if tool == "list_tabs":
        return "look at the tabs"
    if tool == "read_tab":
        return "read tab %s" % tab if tab else "read a tab"
    if tool in ("run", "input"):
        what = one_line(a.get("command") if tool == "run" else a.get("text"), 200)
        return "%s: %s" % ("run" if tool == "run" else "type", what)
    if tool == "wait":
        return "wait"
    return tool


def _log(model, W, color):
    """The log, oldest first: a line for each step (a tick, or a cross when it failed) and for what the sysop said, then how the goal ended."""
    rows = []
    g = model.goal
    if g:
        items = [("call", c) for c in g.get("calls") or [] if isinstance(c, dict) and c.get("tool") != "done"]
        items += [("say", s) for s in g.get("say") or [] if isinstance(s, dict)]
        items.sort(key=lambda it: it[1].get("t") if isinstance(it[1].get("t"), (int, float)) else 0)
        for kind, it in items:
            if kind == "say":
                rows += [" " + _paint(color, "lavender", ln) for ln in wrap(one_line(it.get("text"), 400), W)[:2]]
            else:
                bad = bool(it.get("is_error"))
                rows.append(" " + _paint(color, "red" if bad else "green", "✗" if bad else "✓") + " " + _paint(color, "red" if bad else "dim", cut(step_text(it), W - 3)))
        st = g.get("state")
        if st in TERMINAL:
            why = one_line(g.get("summary") or g.get("error"), 400)
            name = {"done": "green", "failed": "red", "stopped": "amber"}[st]
            lines = wrap(st + (": " + why if why else ""), W)
            if len(lines) > DONE_LINES:           # the brain is made to write two or three lines; this is only the net under it
                lines = lines[:DONE_LINES]
                lines[-1] = cut(lines[-1] + " …", W)
            rows += [" " + _paint(color, name, ln, True) for ln in lines]
    if not model.up:
        rows += [" " + _paint(color, "red", ln) for ln in wrap("The sysop is not running. It starts with the box.", W)]
    return rows


def ago(seconds):
    seconds = max(0, int(seconds))
    if seconds < 10:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= size:
            return "%d %s ago" % (seconds // size, unit)
    return "%d s ago" % seconds


def _bar(text, name, color, cols):
    """A full-width bar of colour with text on it (the state that needs you; the colour is the same on every screen, and the words say it too)."""
    text = " " + cut(text, cols - 2)
    if not color:
        return text
    return "\x1b[1m" + bg(name) + fg("ink") + text + " " * max(0, cols - text_width(text)) + RESET


def _buttons(buttons, cols, color, row):
    """One line of buttons: ([ANSI line], [(row, c0, c1, key)]). A button is a filled block; with no colour it is [Label]."""
    line, hits, col = "", [], 1
    for key, label, name in buttons:
        piece = " %s " % label
        w = text_width(piece)
        if col + w > cols:
            break
        line += " "
        col += 1
        shown = _paint(color, None, "[%s]" % label) if not color else "\x1b[1m" + bg(name) + fg("ink") + piece + RESET
        w = text_width(strip_ansi(shown))
        line += shown
        hits.append((row, col, col + w - 1, key))
        col += w
    return line, hits


def _pending_lines(model, W, wall, color):
    """The action that waits, as a bar (what is needed from you) and the text of the action."""
    p = model.pending
    lv = model.risk()
    left = max(0, int(model.remaining(wall) + 0.999))
    tab = one_line(p.get("label") or p.get("tab"), 20)
    if model.pmode() == "veto":
        head, name = "sending in %d s" % left if left else "sending", "amber"
    else:
        head, name = "allow? %s risk" % lv, ("red" if lv == "high" else "amber")
    bar = _bar("%s · tab %s" % (head, tab), name, color, W + 2)
    full = one_line(p.get("text"), 4100)
    text = wrap(full, W - 3)
    model.hidden = 0
    if len(text) <= SHOW_LINES:
        shown = text
    else:
        shown = text[:SHOW_LINES - 1]
        model.hidden = max(1, len(full) - sum(len(x) for x in shown))
    rows = [bar] + [" " + _paint(color, "violet", "›") + " " + _paint(color, "text", ln) for ln in shown]
    if model.hidden:
        rows += [" " + _paint(color, "red", ln, True) for ln in wrap("+%d more characters not shown: cancel it" % model.hidden, W)]
    reasons = [one_line(r, 120) for r in (p.get("reasons") if isinstance(p.get("reasons"), list) else [])[:1]]
    if lv != "low" and reasons and model.pmode() == "approve":
        rows += [" " + _paint(color, RISK_COLOR[lv], ln) for ln in wrap(reasons[0], W)[:2]]
    return rows


APPROVAL_LINES = 5      # lines of the action in the approval pane
BUTTON_ROWS = 3         # height of the two big buttons of the approval pane (one row in a pane too short for three)


def _big_buttons(buttons, cols, color, first_row, height):
    """The two big buttons of the approval pane side by side, each half of the width, `height` rows high: ([ANSI lines], [(row, c0, c1, key)]).
    One button takes the whole width. Allow is a violet block, Cancel the deep violet one; with no colour they are drawn as boxes."""
    n = len(buttons)
    gap = 1
    width = (cols - 2 - gap * (n - 1)) // n
    lines, hits = [], []
    for r in range(height):
        line, col = " ", 2
        for i, (key, label, name) in enumerate(buttons):
            mid = r == height // 2
            if color:
                paint = "\x1b[1m" + bg(name) + (fg("ink") if name == "violet" else fg("lavender"))
                text = label[:width].center(width) if mid else " " * width
                line += paint + text + RESET
            else:
                if height == 1:
                    text = "[" + label[:max(0, width - 2)].center(max(0, width - 2)) + "]"
                elif r == 0:
                    text = "+" + "-" * (width - 2) + "+"
                elif r == height - 1:
                    text = "+" + "-" * (width - 2) + "+"
                else:
                    text = "|" + (label[:max(0, width - 2)].center(max(0, width - 2)) if mid else " " * (width - 2)) + "|"
                line += text
            if r == 0:
                hits.append((first_row, col, col + width - 1, key))
            if i < n - 1:
                line += " " * gap
            col += width + gap
        lines.append(line)
    hits = [(first_row + r, a, b, k) for r in range(height) for (_, a, b, k) in hits]
    return lines, hits


def render_approval(model, cols, rows, wall, color=True):
    """The screen of the approval pane (a narrow window, while an action waits for you): a bar with the risk, the action, and two big buttons, Allow and
    Cancel. Nothing else: not the goal, not the log, and no word SYSOP (the web page reads that word to know the sysop panel is up). With nothing that waits
    for approval it is empty and calm: the dock takes the pane away a moment later."""
    cols, rows = max(16, cols), max(3, rows)
    p = model.pending
    if not (p and model.up and model.pmode() == "approve" and model.live(wall)):
        return Frame([""] * rows, None, [])
    W = cols - 2
    lv = model.risk()
    tab = one_line(p.get("label") or p.get("tab"), 20)
    bar = _bar("ALLOW?  %s risk%s" % (lv, " · tab %s" % tab if tab else ""), "red" if lv == "high" else "amber", color, cols)
    height = BUTTON_ROWS if rows >= 7 else 1
    spacer = 1 if rows >= height + 3 else 0
    room = max(1, min(APPROVAL_LINES, rows - 1 - height - spacer))
    full = one_line(p.get("text"), 4100)
    text = wrap(full, W - 3)
    model.hidden = 0
    if len(text) <= room:
        shown = text
    else:
        shown = text[:max(0, room - 1)]
        model.hidden = max(1, len(full) - sum(len(x) for x in shown))
    body = [" " + _paint(color, "violet", "\u203a") + " " + _paint(color, "text", ln) for ln in shown]
    if model.hidden:
        body += [" " + _paint(color, "red", ln, True) for ln in wrap("+%d more characters not shown: cancel it" % model.hidden, W)[:1]]
    buttons = ([] if model.hidden else [("a", "Allow", "violet")]) + [("c", "Cancel", "deep")]
    out = [bar] + body[:rows - 1 - height - spacer]
    out += [""] * (rows - height - len(out))
    big, hits = _big_buttons(buttons, cols, color, len(out) + 1, height)
    return Frame(out + big, None, hits)


WEB_MARK = b"SWARMBOX_WEB_CLIENT=1"      # in the environment of the tmux client that swarmbox-attach --web (the browser) starts (SWARMBOX_WEB is the setting of the box: all have it)
WEB_PARENT = "ttyd"                # and the parent of that client is ttyd (the older script did not set the mark)


def latest_client_is_web(listing, is_web):
    """Whether the client that used the window last is the browser. `listing`: the output of `tmux list-clients -F '#{client_activity} #{client_pid}'`;
    `is_web(pid)`: True for a browser, False for a terminal, None when it cannot be told. None when there is no client or it cannot be told."""
    best = None
    for line in listing.splitlines():
        try:
            act, pid = (int(x) for x in line.split())
        except ValueError:
            continue
        if best is None or act > best[0]:
            best = (act, pid)
    return None if best is None else is_web(best[1])


def _proc_web(pid):
    """The browser's client: the environment has the mark, or ttyd is its parent. False for a terminal's client (one that came in from outside the container has no parent
    to read: that is a terminal too); None when /proc says nothing about the client itself."""
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            if WEB_MARK in f.read().split(b"\0"):
                return True
    except OSError:
        return None
    try:
        with open("/proc/%d/stat" % pid) as f:
            ppid = int(f.read().rsplit(")", 1)[1].split()[1])      # after the name between parentheses: state, ppid, ...
        with open("/proc/%d/comm" % ppid) as f:
            return f.read().strip() == WEB_PARENT
    except (OSError, ValueError, IndexError):
        return False


def web_attached():
    """True when the browser used the window last (the page draws the bar of buttons of the panel), False when a terminal did, None when it cannot be told."""
    if not os.environ.get("TMUX"):      # a panel is in a pane of tmux, which says where its server is; elsewhere (a test) there is nothing to ask
        return None
    try:
        out = subprocess.run(["tmux", "list-clients", "-F", "#{client_activity} #{client_pid}"], capture_output=True, text=True, timeout=1).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return latest_client_is_web(out, _proc_web)


def render(model, cols, rows, wall, color=True, closer=False, web=True):
    """The screen as a Frame of exactly `rows` lines: the state, the goal, the steps, and at the bottom what needs you (a bar, the action, buttons).
    `closer`: the panel of a narrow window (a phone) has a close control at the right end of its head line: a hit on the key q.
    `web`: the tall panel of a desktop leaves room for the bar of buttons that the web page draws under the title; a terminal has no page, so it gets one blank line."""
    cols, rows = max(16, cols), max(4, rows)
    W = cols - 2
    word, name = state_of(model)
    head, used = " " + _paint(color, "violet", "SYSOP", True) + "  " + _paint(color, name, word, True), 8 + len(word)
    for text, tone in (("+%d queued" % len(model.queue) if model.up and model.queue else "", "dim"),
                       ("bus %s" % one_line(model.bus, 12) if model.up and model.bus and model.bus != "connected" else "", "red")):
        if text and used + 2 + len(text) <= cols:
            head += "  " + _paint(color, tone, text)
            used += 2 + len(text)
    close_at = None
    if closer and cols - used >= len(CLOSE) + 2:
        head += " " * (cols - used - len(CLOSE)) + (_paint(color, "dim", CLOSE) if not color else "\x1b[1m" + bg("deep") + fg("lavender") + CLOSE + RESET)
        close_at = (cols - len(CLOSE) + 1, cols)
    if color:      # the head is a bar of a dark purple, edge to edge: it stands out and parts the panel from what is above it
        head = bg("band") + head.replace(RESET, RESET + bg("band")) + " " * max(0, cols - text_width(strip_ansi(head))) + RESET

    top = []
    g = model.goal
    if g and model.up:
        lines = wrap(one_line(g.get("text"), 1000), W)
        if len(lines) > GOAL_LINES:
            lines = lines[:GOAL_LINES]
            lines[-1] = cut(lines[-1] + " …", W)
        top = [" " + _paint(color, "lavender", ln, True) for ln in lines]

    pend_l = _pending_lines(model, W, wall, color) if (model.pending and model.up) else []
    notice_l = [" " + _paint(color, "red", ln) for ln in wrap(model.notice, W)] if model.notice else []
    prompt_l, buttons, cursor_at = [], [], None
    if model.mode == "edit":
        prompt_l = [" " + _paint(color, "violet", "Goal (Enter sends, Esc cancels):")]
        shown, curw, left, right = model.editor.view(W - 1)
        prompt_l.append(("<" if left else " ") + _paint(color, "lavender", shown) + (">" if right else ""))
        cursor_at = (len(prompt_l), curw + 2)
    else:
        if model.up and model.live(wall):
            buttons = ([] if (model.hidden or model.pmode() == "veto") else [("a", "Allow", "green")]) + [("c", "Cancel", "red")]
        elif model.up and (model.running() or model.queue):
            buttons = [("c", "Stop", "red")]
        elif model.up:
            buttons = [("g", "Goal", "violet")]

    # Room under the head when the panel is tall enough to spare it. On a phone one blank line (the content is not stuck to the title). On a desktop, in the tall narrow
    # panel at the right edge, STRIP_ROWS blank lines: a bar of buttons (two lines) that the web page fills (the microphone now, more later) and a line of space under it
    # (ttyd-clipboard.js, paintPanel).
    gap = (1 if rows >= HEAD_GAP_ROWS else 0) if closer else ((STRIP_ROWS if web else 1) if rows >= WIDE_GAP_ROWS and cols <= WIDE_COLS else 0)

    def total():
        return len(top) + len(pend_l) + len(notice_l) + len(prompt_l) + (1 if buttons else 0)
    while rows - 1 - gap - total() < 1 and notice_l:
        notice_l.pop()
    while rows - 1 - gap - total() < 1 and len(top) > 1:
        top.pop()
    while rows - 1 - gap - total() < MIN_LOG and len(top) > 1:
        top.pop()
    avail = max(1, rows - 1 - gap - total())
    body = _log(model, W, color)
    if not body and model.up and not g:
        body = [" " + _paint(color, "dim", ln) for ln in wrap("Say or type a goal.", W)]
    elif not body and g and g.get("state") in TERMINAL:
        body = []
    s = max(0, min(model.scroll, max(0, len(body) - 1)))
    model.scroll = s
    if len(body) <= avail:
        visible = body
    else:
        end = len(body) - s
        room = avail - (1 if s else 0)
        start = max(0, end - room)
        if start > 0 and room >= MIN_LOG + 1:
            room -= 1
            start = max(0, end - room)
        visible = body[start:end]
        if start > 0 and room >= MIN_LOG:
            visible = [" " + _paint(color, "dim", cut("%d earlier (Up)" % start, W))] + visible
        if s:
            visible = visible + [" " + _paint(color, "dim", cut("%d later (Down)" % s, W))]
    out = [head] + [""] * gap + top + visible
    while len(out) < rows - (total() - len(top)):
        out.append("")
    base = len(out)
    out += pend_l + notice_l + prompt_l
    hits = []
    if buttons:
        line, hits = _buttons(buttons, cols, color, len(out) + 1)
        out.append(line)
    cursor = (base + len(pend_l) + len(notice_l) + cursor_at[0], cursor_at[1]) if cursor_at else None
    if len(out) > rows:                       # too small for everything: the head and the end (action, buttons) win
        drop = len(out) - rows
        out = [out[0]] + out[1 + drop:]
        hits = [(r - drop, a, b, k) for r, a, b, k in hits if r - drop > 1]
        cursor = (cursor[0] - drop, cursor[1]) if cursor and cursor[0] - drop > 1 else None
    if close_at:
        hits = hits + [(1, close_at[0], close_at[1], "q")]
    return Frame(out + [""] * (rows - len(out)), cursor, hits)


# ---------------------------------------------------------------------------------------------------------------------- the terminal loop

class Panel:
    def __init__(self, pth=None, in_fd=0, out_fd=1, now=time.monotonic, wall=time.time, color=None, mouse=True, bus=None):
        self.paths = pth or pathsmod.Paths()
        self.in_fd, self.out_fd, self.now, self.wall = in_fd, out_fd, now, wall
        self.color = (not os.environ.get("NO_COLOR")) if color is None else color
        self.mouse = mouse
        self.bus = bus or busclient.Bus(self.paths.socket, timeout=5.0)
        self.model = Model(now())
        self.approval = os.environ.get(dock.APPROVAL_ENV) == "1"      # the approval pane of a narrow window: see render_approval
        self.model.approval_only = self.approval
        try:
            self.model.panel_mode = config.panel_mode()
        except config.ConfigError:
            pass
        self.keys = KeyParser()
        self.sig = None               # what the files looked like at the last full look (see changed)
        self.hits = []
        self.focus_at = None          # when the pane got the focus (a click that gave it the focus is not a click on a button)
        self.last_gid = None
        self.drawn = None
        self._web, self._web_at = True, None      # whether the browser used the window last, and when that was looked at
        self.wake_r, self.wake_w = os.pipe()
        for fd in (self.wake_r, self.wake_w):
            os.set_blocking(fd, False)
        self.exit_code = 0

    # -------- plumbing
    def wake(self):
        try:
            os.write(self.wake_w, b"x")
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EPIPE):
                raise

    def size(self):
        try:
            s = os.get_terminal_size(self.out_fd)
            return s.columns, s.lines
        except OSError:
            return 80, 24

    def write(self, text):
        data = text.encode("utf-8", "replace")
        while data:
            try:
                n = os.write(self.out_fd, data)
            except BlockingIOError:
                select.select([], [self.out_fd], [], 1.0)
                continue
            data = data[n:]

    def changed(self):
        """True when the next look can show something new: the service came or went or status.json changed. A stat of one file
        and a lock probe; this is all the idle panel does each second."""
        sig = [service.running(self.paths)]
        for f in (self.paths.status,):
            try:
                st = os.stat(f)
                sig.append((st.st_ino, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append(None)
        sig = tuple(sig)
        if sig == self.sig:
            return False
        self.sig = sig
        return True

    def web(self):
        """Whether the browser used the window last (a look at the clients of tmux every WEB_EVERY seconds); when it cannot be told, yes (the usual case, a bar of buttons the page may fill)."""
        now = self.now()
        if self._web_at is None or now - self._web_at >= WEB_EVERY:
            self._web_at, seen = now, web_attached()
            self._web = True if seen is None else seen
        return self._web

    def look(self):
        snap = snapshot(self.paths, self.last_gid)
        if snap.up:
            st = ipc.read_json(self.paths.status)
            if not (isinstance(st, dict) and st.get("current")):          # no goal runs: the end of the latest one stays on screen (even one that
                for g in service.recent_goals(self.paths, 1):              # started and ended between two looks)
                    if g.get("state") in TERMINAL and isinstance(g.get("ended"), (int, float)) and self.wall() - g["ended"] < LAST_FRESH:
                        gid = service.sanitize(g.get("id"), "")
                        if gid != snap.gid:
                            snap = snapshot(self.paths, gid)
        if snap.gid:
            self.last_gid = snap.gid
        self.model.update(snap, self.now())

    def draw(self, force=False):
        cols, rows = self.size()
        if self.approval:
            frame = render_approval(self.model, cols, rows, self.wall(), self.color)
        else:
            frame = render(self.model, cols, rows, self.wall(), self.color, closer=os.environ.get(dock.COMPACT_ENV) == "1", web=self.web())
        sig = (cols, rows, tuple(frame.lines), frame.cursor)
        if sig == self.drawn and not force:
            return
        out = ["\x1b[?25l"]
        for i, line in enumerate(frame.lines):
            out.append("\x1b[%d;1H%s\x1b[0m\x1b[K" % (i + 1, line))
        if frame.cursor:
            out.append("\x1b[%d;%dH\x1b[?25h" % frame.cursor)
        self.write("".join(out))
        self.hits, self.drawn = frame.hits, sig

    # -------- commands
    def carry_out(self, cmd):
        m = self.model
        kind = cmd[0]
        if kind == "quit":
            m.finished = m.quit_key = True
        elif kind == "decide":
            _, gid, pid, decision, word = cmd
            if not gid:
                return
            body = {"id": pid, "decision": decision, "by": "panel"}
            if word:
                body["word"] = word
            try:
                ipc.write_json(os.path.join(self.paths.goal_dir(service.sanitize(gid, "x")), "decision.json"), body)
            except OSError as e:
                m.notice = "Could not write the decision: %s" % clean(e.strerror or str(e), 100)
                return
            m.notice = {"veto": "Vetoed: it will not be sent.", "deny": "Refused.", "approve": "Allowed."}[decision]
        elif kind == "stop":
            try:
                ipc.request_stop(self.paths, cmd[1])
                m.notice = "Stop requested (%s)." % ("the goal and the queue" if cmd[1] is None else "this goal")
            except OSError as e:
                m.notice = "Could not ask for the stop: %s" % clean(e.strerror or str(e), 100)
        elif kind == "goal":
            text = cmd[1]
            if len(text) > service.MAX_GOAL_TEXT:
                m.draft, m.notice = text, "The goal has %d characters, at most %d." % (len(text), service.MAX_GOAL_TEXT)
                return
            try:
                self.bus.pub(self.topic(), {"text": text}, "panel")
                m.notice = "Goal sent."
            except (busclient.BusError, config.ConfigError) as e:
                m.draft = text
                m.notice = ("The sysop is not running: nobody takes the goal (your text is kept: g)." if getattr(e, "code", "") == "no_subscriber"
                            else "The goal was not sent: %s. Your text is kept: g." % clean(busclient.words(e), 120))

    @staticmethod
    def topic():
        """the topic goals go to (SWARMBOX_SYSOP_TOPIC, read at each goal: the setting of the box)"""
        return config.goal_topic()

    def handle_key(self, k):
        now = self.now()
        if k == "focus-in":
            self.focus_at = now
            self.model.focused = True
            return
        if k == "focus-out":
            self.focus_at = None
            self.model.focused = False
            return
        if isinstance(k, tuple):
            if k[0] == "wheel":
                self.model.scroll = max(0, self.model.scroll + (1 if k[1] == "up" else -1))
            elif k[0] == "click" and self.model.mode == "view" and now >= self.model.ready_at:
                if self.focus_at is not None and now - self.focus_at < 0.4 and not self.approval:      # the first tap on the approval pane gives it the focus AND answers
                    return
                for row, c0, c1, key in self.hits:
                    if k[2] == row and c0 <= k[1] <= c1:
                        self.handle_key(key)
                        return
            return
        cmd = self.model.key(k, now, self.wall())
        if cmd:
            self.carry_out(cmd)

    # -------- run
    def run(self):
        if not os.isatty(self.in_fd):
            print("swarmbox-sysop panel: it needs a terminal (run it in a tmux pane; swarmbox-sysop dock open)", file=sys.stderr)
            return 2
        saved = termios.tcgetattr(self.in_fd)
        old_winch = signal.signal(signal.SIGWINCH, lambda *_: (setattr(self, "drawn", None), self.wake()))
        old_term = [signal.signal(s, lambda *_: (setattr(self.model, "finished", True), self.wake())) for s in (signal.SIGTERM, signal.SIGHUP)]
        try:
            tty.setraw(self.in_fd)
            self.write("\x1b[?1049h\x1b[?25l" + ("\x1b[?1000h\x1b[?1006h" if self.mouse else "") + "\x1b[?1004h\x1b[2J")
            self.loop()
        finally:
            try:
                self.write("\x1b[?1004l" + ("\x1b[?1006l\x1b[?1000l" if self.mouse else "") + "\x1b[?25h\x1b[?1049l")
            except OSError:
                pass
            termios.tcsetattr(self.in_fd, termios.TCSADRAIN, saved)
            signal.signal(signal.SIGWINCH, old_winch)
            for s, h in zip((signal.SIGTERM, signal.SIGHUP), old_term):
                signal.signal(s, h)
            if os.environ.get("SWARMBOX_SYSOP_PANEL") and not self.approval:          # a panel opened by the dock (the approval pane has no window to thaw and nothing to hide)
                if self.model.quit_key:
                    dock.panel_quit()                            # q: the mode always hides the panels of all windows, the others thaw the name of the window
                else:
                    dock.thaw_own_window()
        return self.exit_code

    def loop(self):
        """Turns until the model is finished. A turn that fails (a file that went away, a disk that refuses, a state of an unexpected shape) is ONE line in the
        panel ("The panel hit a problem and goes on"), never a traceback on the screen of the user's tab and a pane that dies and comes back every few seconds;
        twenty failures in a row end it (the dock makes a new one)."""
        fails = 0
        while not self.model.finished:
            try:
                more = self.turn()
                fails = 0
            except Exception as e:
                fails += 1
                self.model.notice = "The panel hit a problem and goes on (%s)." % clean("%s: %s" % (type(e).__name__, getattr(e, "strerror", None) or e), 80)
                self.drawn = None
                if fails >= 20:
                    raise
                time.sleep(min(2.0, 0.1 * fails))
                continue
            if not more:
                break

    def turn(self):
        """One look, one drawing and one wait for a key; False when the pane's terminal is gone."""
        if not self.model.quiet() or self.changed():
            self.look()
        self.draw()
        timeout = ESC_WAIT if self.keys.pending() else IDLE_POLL if self.model.quiet() else POLL
        try:
            ready, _, _ = select.select([self.in_fd, self.wake_r], [], [], timeout)
        except InterruptedError:
            return True
        if self.wake_r in ready:
            try:
                os.read(self.wake_r, 4096)
            except BlockingIOError:
                pass
        if self.in_fd in ready:
            try:
                data = os.read(self.in_fd, 4096)
            except OSError:
                return False
            if not data:
                return False          # the pane's terminal is gone
            for k in self.keys.feed(data):
                self.handle_key(k)
        elif not ready and self.keys.pending():
            for k in self.keys.flush():
                self.handle_key(k)
        return True


def run(argv=None):
    return Panel().run()
