"""The panel: `swarmbox-voice panel`, a text program for a tmux pane. Stdlib only (raw ANSI, termios, select).

It shows the PENDING plan of the voice service and is the only place where a plan is run, edited or cancelled:
what was heard, the planner's sentence, the risk the HOST computed (colour AND words), every action and the time left.
Keys: r run, e edit the text of an action, c or Esc cancel, q close (the plan stays pending), Up/Down scroll.
A plan of HIGH risk needs more: after `r` type the word `run` and Enter. Nothing runs without a key pressed in this pane.

It talks to the service on the loopback address (GET /voice/pending as a long poll, POST /voice/run|edit|cancel); none of those is
reachable through the web front. It exits by itself when the plan is run, cancelled or expires (so tmux closes the pane). If the
service is down it says so and keeps trying; `q` closes it.

Parts, each testable alone: Model (state and keys, no I/O), render (state and size -> text), KeyParser (bytes -> keys), LineEditor,
Client (the HTTP calls) and Panel (the terminal loop).
"""
import errno
import http.client
import json
import os
import select
import signal
import sys
import termios
import threading
import time
import tty
import unicodedata
from collections import namedtuple

DEFAULT_SERVICE = "127.0.0.1:17682"
POLL_WAIT = 20          # seconds of one long poll
GUARD = 0.5             # seconds after a plan appears in which keys are ignored: typing that was meant for another pane must not answer it
ESC_WAIT = 0.05         # a lone ESC is a key when nothing follows within this long
MIC_RESERVE = 7         # the browser's microphone button covers the last columns of the bottom row: the key line stays clear of them
MAX_EDIT = 2000
ACTIONS = ("send_text", "new_window", "select_pane")

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


# ---------------------------------------------------------------------------------------------------------------------- model

class Model:
    """What the panel knows and what its keys do. No I/O: key() returns a command for the caller to carry out:
    ("run", id), ("edit", id, {"<index>": text}), ("cancel", id), ("quit",) or None."""

    def __init__(self, now=0.0):
        self.plan = None
        self.measured = now         # when plan["expires_in"] was true
        self.mode = "view"          # view | word | pick | edit | dead
        self.word = ""
        self.notice = ""
        self.dead = ""              # why this plan can not be run any more (shown until a key)
        self.down = ""              # the service does not answer: what to say
        self.editor = None
        self.edit_index = None
        self.scroll = 0
        self.seen_end = True
        self.ready_at = 0.0
        self.finished = False
        self.had_plan = False

    # -------- plans
    def set_plan(self, plan, now, guard=True):
        new = self.plan is None or plan.get("id") != self.plan.get("id")
        self.plan, self.measured, self.had_plan = plan, now, True
        if new:
            self.mode, self.word, self.notice, self.dead, self.editor, self.scroll = "view", "", "", "", None, 0
            self.seen_end = True
            if guard:
                self.ready_at = now + GUARD

    def apply_poll(self, pending, now):
        """The answer of the service to GET /voice/pending: a plan dict or None."""
        self.down = ""
        if pending:
            self.set_plan(pending, now)
        elif self.had_plan and not self.dead:
            self.finished = True     # run, cancelled or expired: close the pane
        elif self.had_plan and self.dead and self.plan is not None and self.mode != "dead":
            self.mode = "dead"

    def die(self, message):
        """The plan can not run (it was used, replaced, expired, or tmux refused): say why, close on the next key."""
        self.dead, self.mode, self.editor, self.word = message, "dead", None, ""

    def remaining(self, now):
        if not self.plan:
            return 0
        return max(0, int(self.plan.get("expires_in", 0)) - int(now - self.measured))

    # -------- the plan's parts
    def actions(self):
        acts = self.plan.get("actions") if self.plan else None
        return [a if isinstance(a, dict) else {} for a in acts] if isinstance(acts, list) else []

    def level(self):
        risk = self.plan.get("risk") if self.plan else None
        lv = risk.get("level") if isinstance(risk, dict) else None
        return lv if lv in ("low", "medium", "high") else "high"     # an unknown level gets the strongest treatment

    def runnable(self):
        acts = self.actions()
        return bool(acts) and all(a.get("type") in ACTIONS for a in acts)

    def editable(self):
        return [i for i, a in enumerate(self.actions()) if a.get("type") == "send_text"]

    # -------- keys
    def key(self, k, now):
        if self.finished:
            return None
        if now < self.ready_at and self.plan is not None:
            return None
        if isinstance(k, tuple):
            return None
        if k == "ctrl-c" and self.mode in ("view", "dead"):
            return ("quit",)
        if self.mode == "dead":
            return ("quit",)
        if self.mode == "edit":
            return self._key_edit(k)
        if self.mode == "word":
            return self._key_word(k)
        if self.mode == "pick":
            return self._key_pick(k)
        return self._key_view(k, now)

    def _key_view(self, k, now):
        low = k.lower() if isinstance(k, str) and len(k) == 1 else k
        if low in ("q", "ctrl-c"):
            return ("quit",)
        if self.plan is None:
            return ("quit",) if low == "esc" else None
        pid = str(self.plan.get("id", ""))
        if low in ("up", "k"):
            self.scroll = max(0, self.scroll - 1)
        elif low in ("down", "j"):
            self.scroll += 1
        elif low == "pgup":
            self.scroll = max(0, self.scroll - 5)
        elif low in ("pgdn", " "):
            self.scroll += 5
        elif low in ("c", "esc"):
            return ("cancel", pid)
        elif low == "r":
            self.notice = ""
            if not self.runnable():
                self.notice = "This plan has an action that cannot be run."
            elif not self.seen_end:
                self.notice = "Scroll down (Down) to read the whole plan before you run it."
            elif self.level() == "high":
                self.mode, self.word = "word", ""
            else:
                return ("run", pid)
        elif low == "e":
            self.notice = ""
            idx = self.editable()
            if not idx:
                self.notice = "There is no text to edit in this plan."
            elif len(idx) == 1:
                self._start_edit(idx[0])
            else:
                self.mode = "pick"
        return None

    def _start_edit(self, i):
        self.mode, self.edit_index = "edit", i
        self.editor = LineEditor(clean(self.actions()[i].get("text", ""), MAX_EDIT).replace("\n", " "))
        self.original = self.editor.text

    def _key_pick(self, k):
        if k == "esc":
            self.mode = "view"
        elif isinstance(k, str) and k.isdigit() and int(k) - 1 in self.editable():
            self._start_edit(int(k) - 1)
        return None

    def _key_word(self, k):
        if k == "esc":
            self.mode, self.word = "view", ""
        elif k == "enter":
            if self.word.strip().lower() == "run":
                self.mode, self.word = "view", ""
                return ("run", str(self.plan.get("id", "")))
            self.word = ""
            self.notice = "Not run. To run a high-risk plan type the word run and press Enter."
        elif k == "backspace":
            self.word = self.word[:-1]
        elif isinstance(k, str) and len(k) == 1 and k >= " " and len(self.word) < 12:
            self.word += k
        return None

    def _key_edit(self, k):
        if k == "esc" or k == "ctrl-c":
            self.mode, self.editor = "view", None
        elif k == "enter":
            text, self.mode, self.editor = self.editor.text, "view", None
            if text != self.original:
                return ("edit", str(self.plan.get("id", "")), {str(self.edit_index): text})
        elif isinstance(k, str):
            self.editor.key(k)
        return None


# ---------------------------------------------------------------------------------------------------------------------- render

Frame = namedtuple("Frame", "lines cursor hits complete")   # lines: `rows` ANSI strings; cursor: (row, col) 1-based or None; hits: [(row, c0, c1, key)]

RISK_WORD = {"low": "LOW RISK", "medium": "MEDIUM RISK", "high": "HIGH RISK"}
RISK_COLOR = {"low": "green", "medium": "amber", "high": "red"}


def _paint(color, name, text, bold=False):
    if not color or not (name or bold):
        return text
    return ("\x1b[1m" if bold else "") + (fg(name) if name else "") + text + RESET


def _badge(level, color):
    """The risk as a word, and with colour as a filled block: never colour alone."""
    if not color:
        return "[%s]" % RISK_WORD[level]
    return "\x1b[1m" + bg(RISK_COLOR[level]) + fg("ink") + " %s " % RISK_WORD[level] + RESET


def describe(action):
    """(heading, detail lines, note) of one action, from service data that is shown as text only."""
    t = action.get("type")
    if t == "send_text":
        note = "Enter is pressed: it runs." if action.get("enter") is True else "Enter is not pressed."
        return "type into pane %s:" % clean(action.get("pane"), 20), [clean(action.get("text", ""), 2000)], note
    if t == "new_window":
        lines = []
        if action.get("name"):
            lines.append("name: " + clean(action["name"], 100))
        if action.get("cwd"):
            lines.append("folder: " + clean(action["cwd"], 500))
        return "open a new window", lines or ["(default name and folder)"], ""
    if t == "select_pane":
        return "switch to pane %s" % clean(action.get("pane"), 20), [], ""
    return "unknown action, it cannot be run", [clean(t, 40)], ""


def _body(model, W, color):
    """The scrolling part: heard, plan sentence, why, actions. A list of ANSI lines."""
    rows = []

    def para(name, text, indent=1, bold=False, lead=None):
        for n, line in enumerate(wrap(text, max(1, W - indent))):
            rows.append((lead if (n == 0 and lead is not None) else " " * indent) + _paint(color, name, line, bold))

    if model.down:
        para("red", model.down)
    plan = model.plan
    if not plan:
        para("dim", "Hold the microphone button in the browser and speak: the plan shows here.")
        return rows
    lv = model.level()
    heard = clean(plan.get("text", "")).strip()
    if heard:
        para("lavender", 'heard: "%s"' % heard)
    say = clean(plan.get("say", "")).strip()
    if say:
        para("text", "plan: " + say)
    risk = plan.get("risk") if isinstance(plan.get("risk"), dict) else {}
    reasons = [clean(r, 200) for r in (risk.get("reasons") if isinstance(risk.get("reasons"), list) else [])[:6]]
    if lv != "low" and reasons:
        para(RISK_COLOR[lv], "why: " + "; ".join(reasons))
    acts = model.actions()
    for n, a in enumerate(acts):
        heading, details, note = describe(a)
        para("dim", heading, 3, lead=" " + _paint(color, "violet", "%d" % (n + 1), True) + " ")
        for d in details:
            para("text", d, 4)
        if note:
            para("amber" if a.get("enter") is True else "dim", note, 4)
    if not acts:
        para("red", "This plan has no actions.")
    return rows


def _key_line(keys, cols, color):
    """The key line(s), wrapped so that they stay clear of the microphone button: ([ANSI lines], [(line index, c0, c1, key)])."""
    limit = max(10, cols - MIC_RESERVE)
    lines, spans, cur, w, idx = [], [], "", 1, 0
    for key, label in keys:
        piece = "[%s] %s" % (key, label)
        pw = text_width(piece)
        if w + pw > limit and cur:
            lines.append(cur)
            cur, w, idx = "", 1, idx + 1
        cur += " " * (w - text_width(strip_ansi(cur)) if cur else 1)
        cur += _paint(color, "violet", "[%s]" % key, True) + _paint(color, "text", piece[3:])
        spans.append((idx, w + 1, w + pw, key))
        w += pw + 2
    if cur:
        lines.append(cur)
    return lines, spans


def render(model, cols, rows, now, color=True):
    """The screen as a Frame of exactly `rows` lines. The key line is at the bottom and always visible; the plan scrolls above it
    (Frame.complete says the whole plan is on screen: the panel refuses to run a plan whose end was never shown)."""
    cols, rows = max(16, cols), max(4, rows)
    W = cols - 2
    plan = model.plan
    lv = model.level() if plan else None
    voice = _paint(color, "violet", "VOICE", True)
    if plan:
        left = _paint(color, "dim", "time left " + clock(model.remaining(now)))
        short = _paint(color, "dim", clock(model.remaining(now)))
        # the longest header that fits the width: everything, then without the words "time left", then the risk alone
        options = [" %s  %s  %s" % (voice, _badge(lv, color), left), " %s  %s  %s" % (voice, _badge(lv, color), short),
                   " %s %s" % (_badge(lv, color), short), " " + _badge(lv, color)]
        head = next((o for o in options if text_width(strip_ansi(o)) <= cols), options[-1])
    else:
        head = " %s  %s" % (voice, _paint(color, "dim", "nothing is waiting for you"[:max(4, cols - 9)]))

    bottom, cursor_at, key_lines = [], None, []
    for name, text in (("red", model.notice), ("red", model.dead)):
        for ln in wrap(text, W) if text else []:
            bottom.append(" " + _paint(color, name, ln))
    mode = model.mode
    if mode == "word":
        for ln in wrap("HIGH RISK. To run it type the word run, then Enter. Esc goes back.", W):
            bottom.append(" " + _paint(color, "red", ln))
        bottom.append(" > " + model.word)
        cursor_at = (len(bottom), 4 + text_width(model.word))
    elif mode == "pick":
        for ln in wrap("Edit which action? Press its number. Esc goes back.", W):
            bottom.append(" " + _paint(color, "amber", ln))
    elif mode == "edit":
        for ln in wrap("Editing action %d. Enter accepts, Esc aborts." % (model.edit_index + 1), W):
            bottom.append(" " + _paint(color, "violet", ln))
        shown, curw, left, right = model.editor.view(W - 1)
        bottom.append(("<" if left else " ") + _paint(color, "lavender", shown) + (">" if right else ""))
        cursor_at = (len(bottom), curw + 2)
    elif mode == "dead":
        bottom.append(" " + _paint(color, "dim", "Press any key to close."))
    elif plan:
        key_lines, spans = _key_line([("r", "Run (type run)" if lv == "high" else "Run"), ("e", "Edit"), ("c", "Cancel"), ("q", "Close")], cols, color)
    else:
        key_lines, spans = _key_line([("q", "Close")], cols, color)
    n_bottom = len(bottom) + len(key_lines)

    avail = max(1, rows - 1 - n_bottom)
    body = _body(model, W, color)
    if len(body) <= avail:
        visible, complete, marker = body, True, None
    else:
        room = max(1, avail - 1)
        model.scroll = max(0, min(model.scroll, len(body) - room))
        visible = body[model.scroll:model.scroll + room]
        complete = model.scroll + room >= len(body)
        marker = " " + _paint(color, "dim", "end (Up: back)" if complete else "more (Down)")
    out = [head] + visible + ([marker] if marker else [])
    while len(out) < rows - n_bottom:
        out.append("")
    base = len(out)
    out += bottom
    hits = []
    if key_lines:
        for idx, c0, c1, key in spans:
            hits.append((base + len(bottom) + 1 + idx, c0, c1, key))
        out += key_lines
    cursor = (base + cursor_at[0], cursor_at[1]) if cursor_at else None
    return Frame(out[:rows] + [""] * max(0, rows - len(out)), cursor, hits, complete)


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


# ---------------------------------------------------------------------------------------------------------------------- the service

class ServiceError(Exception):
    def __init__(self, status, code, message):
        Exception.__init__(self, message)
        self.status, self.code, self.message = status, code, message


class ServiceDown(Exception):
    pass


class Client:
    def __init__(self, addr=DEFAULT_SERVICE):
        host, _, port = addr.rpartition(":")
        self.host, self.port, self.addr = host or "127.0.0.1", int(port), addr

    def call(self, method, path, obj=None, timeout=10.0):
        body = json.dumps(obj).encode() if obj is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            c = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            try:
                c.request(method, path, body=body, headers=headers)
                r = c.getresponse()
                raw = r.read(1 << 20)
            finally:
                c.close()
        except (OSError, http.client.HTTPException) as e:
            raise ServiceDown(str(e) or e.__class__.__name__) from None
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            raise ServiceDown("the service sent an answer that is not JSON") from None
        if not isinstance(data, dict):
            raise ServiceDown("the service sent an unexpected answer")
        if r.status >= 400:
            raise ServiceError(r.status, str(data.get("error", "")), str(data.get("message") or data.get("error") or "the service refused")[:300])
        return data

    def pending(self, wait=0, since=""):
        path = "/voice/pending"
        if wait:
            path += "?wait=%d&since=%s" % (wait, since)
        return self.call("GET", path, timeout=wait + 10.0).get("pending")

    def post(self, path, obj):
        return self.call("POST", path, obj)


# ---------------------------------------------------------------------------------------------------------------------- the terminal loop

class Panel:
    def __init__(self, client, in_fd=0, out_fd=1, now=time.monotonic, color=None, mouse=True):
        self.client, self.in_fd, self.out_fd, self.now = client, in_fd, out_fd, now
        self.color = (not os.environ.get("NO_COLOR")) if color is None else color
        self.mouse = mouse
        self.model = Model(now())
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.keys = KeyParser()
        self.dirty = True
        self.hits = []
        self.focus_at = None          # when the pane got the focus (a click that gave it the focus is not a click on a button)
        self.wake_r, self.wake_w = os.pipe()
        for fd in (self.wake_r, self.wake_w):
            os.set_blocking(fd, False)
        self.last_clock = None
        self.checked_id = None
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

    def draw(self):
        cols, rows = self.size()
        with self.lock:
            frame = render(self.model, cols, rows, self.now(), self.color)
            pid = self.model.plan.get("id") if self.model.plan else None
            if pid != self.checked_id:
                self.checked_id, self.model.seen_end = pid, frame.complete
            elif frame.complete:
                self.model.seen_end = True
            self.last_clock = self.model.remaining(self.now())
        out = ["\x1b[?25l"]
        for i, line in enumerate(frame.lines):
            out.append("\x1b[%d;1H%s\x1b[0m\x1b[K" % (i + 1, line))
        if frame.cursor:
            out.append("\x1b[%d;%dH\x1b[?25h" % frame.cursor)
        self.write("".join(out))
        self.hits = frame.hits
        self.dirty = False

    # -------- the poller
    def poller(self):
        since = ""
        while not self.stop.is_set():
            try:
                pending = self.client.pending(POLL_WAIT, since)
            except ServiceDown as e:
                with self.lock:
                    self.model.down = "The voice service is not answering (%s: %s). Trying again..." % (self.client.addr, clean(str(e), 120))
                self.dirty = True
                self.wake()
                self.stop.wait(1.5)
                continue
            except ServiceError as e:
                with self.lock:
                    self.model.down = "The voice service refused the request: %s" % clean(e.message, 150)
                self.dirty = True
                self.wake()
                self.stop.wait(1.5)
                continue
            with self.lock:
                self.model.apply_poll(pending, self.now())
                since = str(pending.get("id", "")) if pending else ""
            self.dirty = True
            self.wake()

    # -------- commands
    def carry_out(self, cmd):
        kind = cmd[0]
        if kind == "quit":
            self.model.finished = True
            return
        try:
            if kind == "run":
                out = self.client.post("/voice/run", {"id": cmd[1]})
                if out.get("ok") is False:
                    bad = next((r for r in out.get("results", []) if isinstance(r, dict) and r.get("ok") is False), {})
                    with self.lock:
                        self.model.die("It did not run: %s" % clean(bad.get("error") or "tmux refused the action", 200))
                else:
                    self.model.finished = True
            elif kind == "cancel":
                try:
                    self.client.post("/voice/cancel", {"id": cmd[1]})
                except ServiceError:
                    pass          # already gone: it is what was asked
                self.model.finished = True
            elif kind == "edit":
                plan = self.client.post("/voice/edit", {"id": cmd[1], "edits": cmd[2]})
                with self.lock:
                    self.model.set_plan(plan, self.now(), guard=False)
                    self.model.notice = ""
        except ServiceError as e:
            with self.lock:
                if kind == "edit" and e.status in (400, 422):
                    self.model.notice = "The edit was refused: %s" % clean(e.message, 200)
                else:
                    self.model.die("%s (%s)" % (clean(e.message, 200), "the plan is gone" if e.status in (404, 409, 410) else "error %d" % e.status))
        except ServiceDown as e:
            with self.lock:
                self.model.notice = "The voice service is not answering: %s" % clean(str(e), 120)

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
                self.model.scroll = max(0, self.model.scroll + (-1 if k[1] == "up" else 1))
            elif k[0] == "click" and self.model.mode == "view":
                if self.focus_at is not None and now - self.focus_at < 0.4:
                    return
                for row, c0, c1, key in self.hits:
                    if k[2] == row and c0 <= k[1] <= c1:
                        self.handle_key(key)
                        return
            return
        with self.lock:
            cmd = self.model.key(k, now)
        if cmd:
            self.carry_out(cmd)
        self.dirty = True

    # -------- run
    def run(self):
        if not os.isatty(self.in_fd):
            print("swarmbox-voice panel: it needs a terminal (run it in a tmux pane)", file=sys.stderr)
            return 2
        saved = termios.tcgetattr(self.in_fd)
        old_winch = signal.signal(signal.SIGWINCH, lambda *_: (setattr(self, "dirty", True), self.wake()))
        old_term = [signal.signal(s, lambda *_: (self.stop.set(), self.wake())) for s in (signal.SIGTERM, signal.SIGHUP)]
        try:
            tty.setraw(self.in_fd)
            self.write("\x1b[?1049h\x1b[?25l" + ("\x1b[?1000h\x1b[?1006h" if self.mouse else "") + "\x1b[?1004h\x1b[2J")
            threading.Thread(target=self.poller, daemon=True).start()
            self.loop()
        finally:
            self.stop.set()
            try:
                self.write("\x1b[?1004l" + ("\x1b[?1006l\x1b[?1000l" if self.mouse else "") + "\x1b[?25h\x1b[?1049l")
            except OSError:
                pass
            termios.tcsetattr(self.in_fd, termios.TCSADRAIN, saved)
            signal.signal(signal.SIGWINCH, old_winch)
            for s, h in zip((signal.SIGTERM, signal.SIGHUP), old_term):
                signal.signal(s, h)
        return self.exit_code

    def loop(self):
        while not self.model.finished and not self.stop.is_set():
            timeout = ESC_WAIT if self.keys.pending() else 0.5
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
            with self.lock:
                tick = self.model.plan is not None and self.model.remaining(self.now()) != self.last_clock
            if self.dirty or tick:
                self.draw()


def run(addr=DEFAULT_SERVICE):
    return Panel(Client(addr)).run()
