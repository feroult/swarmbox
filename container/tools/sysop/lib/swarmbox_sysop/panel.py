"""The panel of the sysop: `swarmbox-sysop panel`, a text program for a tmux pane. Stdlib only (raw ANSI, termios, select).

It shows the goal the sysop is working on and is the place where you answer it: the goal (text and source), the live log of the steps (each tool
call with a short result, and what the sysop said), the queue of goals, and the PENDING ACTION with its countdown. What you type becomes a goal.
Keys:   c  veto the action that waits in a countdown (it is NOT sent); in an approval, refuse it
        r  then the word `run` and Enter: allow a HIGH-RISK action (nothing less than the typed word counts; Esc goes back)
        x  stop the goal that runs (X: the goal and the whole queue)
        g  type a goal (Enter sends it with source `panel`, Esc aborts)
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
import sys
import termios
import time
import tty
import unicodedata
from collections import namedtuple

from . import busclient, dock, ipc, paths as pathsmod, service

GUARD = 0.5             # seconds after a new pending action appears in which keys are ignored
ESC_WAIT = 0.05         # a lone ESC is a key when nothing follows within this long
POLL = 0.2              # seconds between two looks at the files
MIC_RESERVE = 7         # the browser's microphone button covers the last columns of the bottom row: the key line stays clear of them
MAX_EDIT = service.MAX_GOAL_TEXT
GOAL_LINES = 3
IDLE_TEXT = "no goal; speak or type one: g"
LAST_FRESH = 3600       # seconds a finished goal is still shown as the last one when the panel opens
TERMINAL = ("done", "stopped", "failed")

PALETTE = {"violet": "a78bfa", "deep": "6d28d9", "lavender": "c4b5fd", "dim": "a1a1aa", "text": "d4d4d8", "red": "ff6b78",
           "amber": "fbbf24", "green": "4ade80", "line": "52525b", "ink": "0c0b10"}
RESET = "\x1b[0m"


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
        self.mode = "view"          # view | word | edit
        self.word, self.notice, self.draft = "", "", ""
        self.editor = None
        self.scroll = 0             # lines back from the end of the log; 0 follows it
        self.ready_at = 0.0
        self.pending_key = None
        self.hidden = 0           # characters of the pending action the last render did not show (set by _pending_lines)
        self.finished = False

    # -------- the state
    def update(self, snap, now):
        self.up, self.bus, self.gid, self.goal, self.queue, self.settings = snap.up, snap.bus, snap.gid, snap.goal, snap.queue, snap.settings
        p = snap.pending
        key = (snap.gid, str(p.get("id"))) if p else None
        if key != self.pending_key:
            self.pending_key = key
            if p:
                self.ready_at = now + GUARD
                if self.mode == "word":
                    self.mode, self.word = "view", ""
                elif self.mode == "edit":      # the countdown runs while you type: the editor yields, the text is kept
                    self.draft, self.editor, self.mode = self.editor.text, None, "view"
                    self.notice = "An action is waiting: answer it first. Your text is kept (g)."
            elif self.mode == "word":
                self.mode, self.word = "view", ""
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

    # -------- keys
    def key(self, k, now, wall):
        if self.finished or now < self.ready_at or isinstance(k, tuple):
            return None
        if self.mode == "edit":
            return self._key_edit(k)
        if self.mode == "word":
            return self._key_word(k, wall)
        return self._key_view(k, wall)

    def _key_view(self, k, wall):
        self.notice = ""
        low = k.lower() if isinstance(k, str) and len(k) == 1 else k
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
        elif low == "c":
            if self.live(wall):
                pid = str(self.pending["id"])
                return ("decide", self.gid, pid, "veto" if self.pmode() == "veto" else "deny", None)
        elif low == "r":
            if self.live(wall) and self.pmode() == "approve":
                if self.hidden:
                    self.notice = "The whole action is not on the screen, so it cannot be allowed: refuse it (c) or make the pane bigger."
                else:
                    self.mode, self.word = "word", ""
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

    def _key_word(self, k, wall):
        if k in ("esc", "ctrl-c"):
            self.mode, self.word = "view", ""
        elif k == "enter":
            ok = self.word.strip().lower() == "run"
            self.mode, self.word = "view", ""
            if not self.live(wall):
                self.notice = "The time is up: the action was refused."
            elif ok and self.hidden:
                self.notice = "The whole action is not on the screen, so it cannot be allowed."
            elif ok:
                return ("decide", self.gid, str(self.pending["id"]), "approve", "run")
            else:
                self.notice = "Not allowed. To allow a high-risk action type the word run and press Enter."
        elif k == "backspace":
            self.word = self.word[:-1]
        elif isinstance(k, str) and len(k) == 1 and k >= " " and len(self.word) < 12:
            self.word += k
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
STATE_WORD = {"running": ("RUNNING", "green"), "queued": ("QUEUED", "dim"), "waiting_approval": ("WAITING", "amber"), "done": ("DONE", "green"),
              "failed": ("FAILED", "red"), "stopped": ("STOPPED", "amber")}


def _paint(color, name, text, bold=False):
    if not color or not (name or bold):
        return text
    return ("\x1b[1m" if bold else "") + (fg(name) if name else "") + text + RESET


def _badge(word, name, color):
    """A state or a risk as a word, and with colour as a filled block: never colour alone."""
    if not color:
        return "[%s]" % word
    return "\x1b[1m" + bg(name) + fg("ink") + " %s " % word + RESET


SHOW_LINES = 6      # rows of the pending action's text; a longer one shows how many characters are left out, and cannot be approved


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
    if not model.up:
        return "SERVICE DOWN", "red"
    if model.pending:
        return ("APPROVAL", "red") if model.pmode() == "approve" else ("COUNTDOWN", "amber")
    return STATE_WORD.get(model.goal.get("state") if model.goal else None, ("IDLE", "dim"))


def args_text(call):
    a = call.get("args") if isinstance(call.get("args"), dict) else {}
    parts = [str(a["tab"])] if "tab" in a else []
    parts += [str(a[k]) for k in ("command", "text", "summary") if k in a]
    parts += ["%s=%s" % (k, v) for k, v in a.items() if k not in ("tab", "command", "text", "summary") and isinstance(v, (str, int, float, bool))]
    return one_line(" ".join(parts), 300)


def result_text(call):
    s = call.get("summary")
    lines = [ln.strip() for ln in clean(s if isinstance(s, str) else "").split("\n") if ln.strip()]
    return " | ".join(lines)[:300]


def verdict_text(v):
    v = v.get("level") if isinstance(v, dict) else v
    return v if isinstance(v, str) and v not in ("", "allowed", "low") else ""


def _log(model, W, color):
    """The live log, oldest first: calls and says in time order, then how the goal ended."""
    rows = []

    def para(name, text, indent, lead=None, bold=False):
        for n, line in enumerate(wrap(text, max(1, W - indent))):
            rows.append((lead if (n == 0 and lead is not None) else " " * indent) + _paint(color, name, line, bold))

    g = model.goal
    if g:
        items = [("call", c) for c in g.get("calls") or [] if isinstance(c, dict)] + [("say", s) for s in g.get("say") or [] if isinstance(s, dict)]

        def when(it):
            t = it[1].get("t")
            return t if isinstance(t, (int, float)) else 0
        for kind, it in sorted(items, key=when):
            if kind == "say":
                para("lavender", "say: " + one_line(it.get("text"), 600), 2)
                continue
            v = verdict_text(it.get("verdict"))
            head = "%s %s" % (one_line(it.get("tool"), 30), args_text(it))
            para("text", head + ((" [%s]" % one_line(v, 20)) if v else ""), 4, lead=" " + _paint(color, "violet", ">", True) + " ")
            res = result_text(it)
            if res:
                para("red" if it.get("is_error") else "dim", ("! " if it.get("is_error") else "= ") + res, 4, lead="   ")
        st = g.get("state")
        if st in TERMINAL:
            why = one_line(g.get("summary") or g.get("error"), 500)
            name = {"done": "green", "failed": "red", "stopped": "amber"}[st]
            para(name, st + (": " + why if why else ""), 1, bold=True)
            if g.get("note"):
                para("dim", one_line(g.get("note"), 300), 1)
        elif st == "queued":
            para("dim", "waiting in the queue", 1)
    if not model.up:
        para("red", "The sysop service is not running, so no goal can be run. It starts with the box; by hand: swarmbox-sysop serve --log", 1)
        return rows
    if not g or g.get("state") in TERMINAL:
        if not model.queue:
            para("dim", IDLE_TEXT, 1)
    return rows


def _key_line(keys, cols, color):
    """The key line(s), wrapped so that they stay clear of the microphone button: ([ANSI lines], [(line index, c0, c1, key)])."""
    limit = max(10, cols - MIC_RESERVE)
    lines, spans, cur, w, idx = [], [], "", 1, 0
    for key, label in keys:
        piece = "[%s] %s" % (key, cut(label, max(1, cols - 2 - len(key) - 3)))
        pw = text_width(piece)
        if w + pw > limit and cur:
            lines.append(cur)
            cur, w, idx = "", 1, idx + 1
        cur += " " * (w - text_width(strip_ansi(cur)) if cur else 1)
        cur += _paint(color, "violet", "[%s]" % key, True) + _paint(color, "text", piece[len(key) + 2:])
        spans.append((idx, w + 1, w + pw, key))
        w += pw + 2
    if cur:
        lines.append(cur)
    return lines, spans


def _pending_lines(model, W, wall, color):
    p = model.pending
    lv, name = model.risk(), RISK_COLOR[model.risk()]
    left = model.remaining(wall)
    badge = _badge(lv.upper() + " RISK", name, color)
    where = "tab %s: %s" % (one_line(p.get("label") or p.get("tab"), 40), one_line(p.get("kind"), 10))
    room = W - text_width(strip_ansi(badge)) - 2
    rows = [" " + _paint(color, "dim", cut(where, room)) + "  " + badge] if room >= 8 else [" " + _paint(color, "dim", cut(where, W)), " " + badge]
    full = one_line(p.get("text"), 4100)
    text = wrap(full, W - 3)
    model.hidden = 0
    if len(text) <= SHOW_LINES:
        shown = text
    else:
        shown = text[:SHOW_LINES - 1]
        model.hidden = max(1, len(full) - sum(len(x) for x in shown))
    for ln in shown:
        rows.append("  > " + _paint(color, "text", ln))
    if model.hidden:
        note = "(+%d more characters NOT shown)" % model.hidden
        if model.pmode() == "approve":
            note += ": it cannot be allowed here, only refused"
        rows += ["    " + _paint(color, "red", ln, True) for ln in wrap(note, W - 4)]
    reasons = [one_line(r, 200) for r in (p.get("reasons") if isinstance(p.get("reasons"), list) else [])[:6]]
    if lv != "low" and reasons:
        rows += [" " + _paint(color, name, ln) for ln in wrap("why: " + "; ".join(reasons), W)]
    if model.pmode() == "veto":
        msg = "sent in %d s unless you veto it: c" % int(left + 0.999) if left > 0 else "sending now"
        rows += [" " + _paint(color, "amber", ln, True) for ln in wrap(msg, W)]
    else:
        msg = ("NOT sent unless you allow it: r, then type run, Enter. Refused in %s" % clock(int(left + 0.999))) if left > 0 else "time is up: refused"
        rows += [" " + _paint(color, "red", ln, True) for ln in wrap(msg, W)]
    return rows


def render(model, cols, rows, wall, color=True):
    """The screen as a Frame of exactly `rows` lines. The key line is at the bottom and always visible; the log shows its end (Up scrolls back)."""
    cols, rows = max(16, cols), max(4, rows)
    W = cols - 2
    word, name = state_of(model)
    title = _paint(color, "violet", "SYSOP", True)
    extra = ""
    if model.up and model.queue:
        extra = _paint(color, "dim", "%d queued" % len(model.queue))
    if model.up and model.bus and model.bus != "connected":
        extra = _paint(color, "red", "bus %s" % one_line(model.bus, 12))
    badge = _badge(word, name, color)
    options = [" %s  %s%s" % (title, badge, ("  " + extra) if extra else ""), " %s  %s" % (title, badge), " " + badge]
    head = next((o for o in options if text_width(strip_ansi(o)) <= cols), options[-1])

    top = []
    g = model.goal
    if g and model.up:
        lines = wrap("goal (%s): %s" % (one_line(g.get("source"), 12), one_line(g.get("text"), 1000)), W)
        if len(lines) > GOAL_LINES:
            lines = lines[:GOAL_LINES]
            lines[-1] = cut(lines[-1] + " …", W)
        top = [" " + _paint(color, "lavender", ln) for ln in lines]

    queue_l = []
    if model.up and model.queue:
        for n, q in enumerate(model.queue[:3]):
            queue_l.append(" " + _paint(color, "dim", cut("queue %d (%s): %s" % (n + 1, one_line(q.get("source"), 12), one_line(q.get("text"), 200)), W)))
        if len(model.queue) > 3:
            queue_l.append(" " + _paint(color, "dim", "+%d more" % (len(model.queue) - 3)))
    pend_l = _pending_lines(model, W, wall, color) if (model.pending and model.up) else []
    notice_l = [" " + _paint(color, "red", ln) for ln in wrap(model.notice, W)] if model.notice else []
    prompt_l, key_lines, spans, cursor_at = [], [], [], None
    if model.mode == "word":
        prompt_l = [" " + _paint(color, "red", ln) for ln in wrap("HIGH RISK. To allow it type the word run, then Enter. Esc goes back.", W)]
        prompt_l.append(" > " + model.word)
        cursor_at = (len(prompt_l), 4 + text_width(model.word))
    elif model.mode == "edit":
        prompt_l = [" " + _paint(color, "violet", ln) for ln in wrap("New goal. Enter sends it, Esc aborts.", W)]
        shown, curw, left, right = model.editor.view(W - 1)
        prompt_l.append(("<" if left else " ") + _paint(color, "lavender", shown) + (">" if right else ""))
        cursor_at = (len(prompt_l), curw + 2)
    else:
        keys = []
        if model.up and model.live(wall):
            keys = [("c", "Veto")] if model.pmode() == "veto" else ([] if model.hidden else [("r", "Allow (type run)")]) + [("c", "Refuse")]
        if model.up and (model.running() or model.queue):
            keys.append(("x", "Stop"))
        if model.up and not model.live(wall):
            keys.append(("g", "Goal"))
        keys.append(("q", "Close"))
        key_lines, spans = _key_line(keys, cols, color)

    def total():
        return len(top) + len(queue_l) + len(pend_l) + len(notice_l) + len(prompt_l) + len(key_lines)
    while rows - 1 - total() < 1 and queue_l:
        queue_l.pop()
    while rows - 1 - total() < 1 and len(top) > 1:
        top.pop()
    avail = max(1, rows - 1 - total())
    body = _log(model, W, color)
    s = max(0, min(model.scroll, max(0, len(body) - 1)))
    model.scroll = s
    if len(body) <= avail:
        visible = body
    else:
        end = len(body) - s
        room = avail - (1 if s else 0)
        start = max(0, end - room)
        older = start > 0
        if older:
            room -= 1
            start = max(0, end - room)
        visible = body[start:end]
        if older:
            visible = [" " + _paint(color, "dim", cut("%d earlier (Up)" % start, W))] + visible
        if s:
            visible = visible + [" " + _paint(color, "dim", cut("%d later (Down)" % s, W))]
    out = [head] + top + visible
    while len(out) < rows - (total() - len(top)):
        out.append("")
    base = len(out)
    out += queue_l + pend_l + notice_l + prompt_l
    hits = []
    if key_lines:
        first = len(out)
        hits = [(first + 1 + i, c0, c1, key) for i, c0, c1, key in spans]
        out += key_lines
    cursor = (base + len(queue_l) + len(pend_l) + len(notice_l) + cursor_at[0], cursor_at[1]) if cursor_at else None
    if len(out) > rows:                       # too small for everything: the head and the end (prompt, keys) win
        drop = len(out) - rows
        out = [out[0]] + out[1 + drop:]
        hits = [(r - drop, a, b, k) for r, a, b, k in hits if r - drop > 1]
        cursor = (cursor[0] - drop, cursor[1]) if cursor and cursor[0] - drop > 1 else None
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
        self.keys = KeyParser()
        self.hits = []
        self.focus_at = None          # when the pane got the focus (a click that gave it the focus is not a click on a button)
        self.last_gid = None
        self.drawn = None
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
        frame = render(self.model, cols, rows, self.wall(), self.color)
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
            m.finished = True
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
                self.bus.pub("goal", {"text": text}, "panel")
                m.notice = "Goal sent."
            except busclient.BusError as e:
                m.draft = text
                m.notice = ("The sysop is not running: nobody takes the goal (your text is kept: g)." if e.code == "no_subscriber"
                            else "The goal was not sent (%s). Your text is kept: g." % clean(str(e), 120))

    def handle_key(self, k):
        now = self.now()
        if k == "focus-in":
            self.focus_at = now
            return
        if k == "focus-out":
            self.focus_at = None
            return
        if isinstance(k, tuple):
            if k[0] == "wheel":
                self.model.scroll = max(0, self.model.scroll + (1 if k[1] == "up" else -1))
            elif k[0] == "click" and self.model.mode == "view" and now >= self.model.ready_at:
                if self.focus_at is not None and now - self.focus_at < 0.4:
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
            if os.environ.get("SWARMBOX_SYSOP_PANEL"):          # a panel opened by the dock: its window may have a frozen name
                dock.thaw_own_window()
        return self.exit_code

    def loop(self):
        while not self.model.finished:
            self.look()
            self.draw()
            timeout = ESC_WAIT if self.keys.pending() else POLL
            try:
                ready, _, _ = select.select([self.in_fd, self.wake_r], [], [], timeout)
            except InterruptedError:
                continue
            if self.wake_r in ready:
                try:
                    os.read(self.wake_r, 4096)
                except BlockingIOError:
                    pass
            if self.in_fd in ready:
                try:
                    data = os.read(self.in_fd, 4096)
                except OSError:
                    break
                if not data:
                    break          # the pane's terminal is gone
                for k in self.keys.feed(data):
                    self.handle_key(k)
            elif not ready and self.keys.pending():
                for k in self.keys.flush():
                    self.handle_key(k)


def run(argv=None):
    return Panel().run()
