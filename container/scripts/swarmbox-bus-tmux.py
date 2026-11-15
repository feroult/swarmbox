"""swarmbox-bus-tmux: the tmux driver of swarmbox-bus (the tabs of the box), standard library only. Loaded by path by swarmbox-bus.py
(`make_driver`), never run on its own; it belongs to the host image next to the bus and imports nothing from any plugin.

The class TmuxDriver implements the three blocking methods of the bus driver interface (see the docstring of swarmbox-bus.py):

  list_tabs()        one dict per tab (a window of the session): tab "@3" (the address), label "1:name", index, name, dir, cmd, pane, panes,
                     active (true for exactly one)
  screen(tab, lines) {"tab", "pane", "text", "cursor", "alternate", "in_mode", "mode", "size", "lines"}; text is made from the plain text of the pane:
                     the last `lines` lines, the secrets removed (on whole lines, whatever the colours), then the markers written and a
                     line longer than 1000 characters cut. Text of the pane that looks like a marker has one more `[` (see to_marked)
  send(tab, body)    body is {"run": text} (typed literally, then Enter) or {"input": text} (braces keys, see parse_keys); both accept
                     "queue": true (type although the agent in the tab is busy) and "slash": true (allow a first character "/" or "!")

Errors are raised as the error class the bus gives to the constructor (swarmbox-bus's DriverError(code, message)): no_such_tab,
ambiguous_tab, bad_body, no_session, no_tmux, timeout, dialog_open, busy_tab, slash_refused, not_submitted, tmux_error.

Tabs.  A tab is a tmux window of the session "main" (SB_BUS_TMUX_SESSION). The address is the window id "@3" (stable, never reused), and the
label "index:name" is accepted too, as is a bare index or a bare name; a name used by two windows is the error ambiguous_tab that lists the
candidates. The tmux target of every call is the pane id "%7", never the window. Panes that carry one of the pane options in HIDDEN_OPTIONS
(the panels of the sysop and of voice) are never listed, never a target, and a window with only such panes is not a tab. The pane of a tab is
its active pane, or, when the focus is in a panel, the pane that had it before (pane_last), or the first one.
The active tab is the window shown by the non-control client with the latest client_activity (1 s resolution, a tie is arbitrary); the
current window of the session when no client shows a tab.

The tmux used: `tmux` (or SB_BUS_TMUX_BIN), with `-L SB_BUS_TMUX_SOCKET` when that is set (tests); TMUX_TMPDIR is passed on as it is. TMUX is removed
from the environment of every call so a nested shell never changes the server. Every tmux call has a timeout.

Typing.  The text goes as `send-keys -l -- piece` calls of CHUNK characters (a `;` at the end of a piece as the key 0x3b: tmux would take
it for the end of the command), then, after PAUSE seconds, each key (the Enter of `run` too) as its own tmux call:
two processes, never one burst, because a terminal program that sees text and Enter in one burst treats it as a paste and the Enter
becomes a line break (docs/spikes/enter.md: 0 of 4 at 600 characters). A pane in copy mode gets `-X cancel` first.
When the pane runs an agent (Claude Code: the input box between two rules, a dialog, "esc to interrupt"; or the command is a known agent) and
the message submits text (text followed by Enter): a dialog is refused (dialog_open), a busy agent is refused unless "queue", a text that
starts with "/" or "!" is refused unless "slash" (it would open a menu or run a shell command; every text that is submitted is checked, not
only the first, and a body that submits more than one text to an agent needs "queue", because the agent is busy after the first), and after the Enter the driver checks that the end
of the text left the input box, pressing Enter once more only when it did not (not_submitted when it still did not). Plain `input` (keys,
or text without Enter) is not judged: it is how a dialog is answered and a busy agent interrupted.
"""
import os
import re
import subprocess
import threading
import time
from collections import namedtuple

SEP = "@@sb@@"     # never a tab: tmux 3.6+ prints control characters of a list as `_` when it has no terminal
HIDDEN_OPTIONS = ("@swarmbox_sysop_panel", "@swarmbox_voice_panel")
HIDDEN_MARKERS = ("SWARMBOX_SYSOP_PANEL=1",)      # in the start command of a panel pane (container/tools/sysop/lib/swarmbox_sysop/dock.py PANEL_COMMAND)
PAUSE = 0.15
MAX_STEPS = 100          # steps (texts and keys) of one body: each key costs PAUSE plus a tmux process (about 0.15 s), the bus gives a call 30 s
CHUNK = 1024             # characters of one send-keys word (4 KiB at most in UTF-8, far below the 16 KB that tmux accepts in a command)
TMUX_TIMEOUT = 5.0
MAX_LINE = 1000          # characters of one line of a screen, cut after the secrets filter (see _render)
VERIFY_TIMEOUT = 5.0     # seconds to see the text leave the input box after an Enter
AGENT_COMMANDS = ("claude", "gemini", "opencode", "codex")
REDACTED = "[REDACTED]"

Tab = namedtuple("Tab", "id index name cwd command pane panes active label")


# ---------------------------------------------------------------------------------------------------------------- the secrets filter
# A copy of the redaction of the voice plugin (container/tools/voice/lib/swarmbox_voice/context.py, the version with linear-time
# patterns): the bus is part of the host image and voice is an optional plugin, so the bus does not import it. tests/test_bus_tmux.py
# checks that the two stay the same.

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    # A JWT may follow a dash or letters of a name (`id-eyJ...`). Linear: it is tried only from the start of its maximal run of token characters
    # (lookbehind); the atomic group runs on to the FIRST eyJ of the run, because a later eyJ of the same run fails exactly where the first did
    # (the rest of the run and what follows it are the same), so every run is scanned once. `(?<![A-Za-z0-9_])eyJ...` alone is quadratic on
    # "eyJ-eyJ-..." (13 s for 400000 characters). The part before eyJ is kept (group `keep`). It runs before `sk-`, which would take the first segment of `sk-eyJ...` and leave the rest.
    re.compile(r"(?<![A-Za-z0-9_-])(?P<keep>(?>(?:(?!eyJ)[A-Za-z0-9_-])*))eyJ[A-Za-z0-9_-]{8,}+\.[A-Za-z0-9_-]{8,}+\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    # the body of a key whose BEGIN line fell outside the captured window: two or more long base64 lines in a row
    re.compile(r"(?m)^[ \t]*[A-Za-z0-9+/=]{32,}[ \t]*(?:\n[ \t]*[A-Za-z0-9+/=]{32,}[ \t]*)+"),
    # one long base64 run on a single line (`base64 -w0 ~/.ssh/id_rsa`): 120 characters or more. Linear: tried only from the start of the run.
    re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{120,}={0,2}"),
]
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_AUTH = re.compile(r"(?i)\b(authorization|x-api-key|api-key|proxy-authorization)\s*[:=]\s*[^\r\n]+")
# Linear-time matching: a name (variable or flag) is matched only from the start of its maximal run of name characters (lookbehind) and the part
# before the first keyword is atomic, so every run is scanned once (an unbounded [..]* behind a bare \b rescans the rest of the run from every
# dash or dot inside it: quadratic, 100000 dashes took 110 s).
_KW = r"(?:key|token|secret|passw(?:or)?d|passwd|credential)"
_ASSIGN = re.compile(r"(?i)(?<![A-Za-z0-9_.-])((?>(?:(?!" + _KW + r")[A-Za-z0-9_.-])*)" + _KW + r"[A-Za-z0-9_.-]*+)([\"']?\s*[=:]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s\"']+)")
_FLAG = re.compile(r"(?i)(?<![a-z0-9-])((?>(?:(?!--)[a-z0-9-])*)--(?>(?:(?!" + _KW + r")[a-z0-9-])*)" + _KW + r"[a-z0-9-]*+)(\s+)(?!-)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
_USERFLAG = re.compile(r"(?<!\S)(-u|--user|--proxy-user)(\s+)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
_URLCRED = re.compile(r"(?i)(?<![a-z0-9+.-])([a-z0-9+.-]++://[^/\s:@]+):[^/\s@]+@")


def _secret(m):
    return (m.groupdict().get("keep") or "") + REDACTED


def _sub(pat, fn, text, org):
    """pat.sub(fn, text). With org (a list with one entry per character of text) it also returns the org of the new text: the characters
    that a match keeps (its common prefix with the replacement) keep their entry, the rest of the replacement takes the entry of the first
    character that was replaced. That is how the style of the screen follows the secrets filter."""
    if org is None:
        return pat.sub(fn, text), None
    out, o2, pos = [], [], 0
    for m in pat.finditer(text):
        old, new = m.group(0), fn(m)
        if new == old:
            continue
        k, lim = 0, min(len(old), len(new))
        while k < lim and old[k] == new[k]:
            k += 1
        cut = m.start() + k
        out.append(text[pos:cut])
        o2.extend(org[pos:cut])
        rest = new[k:]
        if rest:
            out.append(rest)
            o2.extend([org[min(cut, m.end() - 1)]] * len(rest))
        pos = m.end()
    out.append(text[pos:])
    o2.extend(org[pos:])
    return "".join(out), o2


def redact_tracked(text, org=None):
    """(text, org) with the secrets removed; org is None when it was None (see _sub)."""
    for pat in _PATTERNS:
        text, org = _sub(pat, _secret, text, org)
    text, org = _sub(_AUTH, lambda m: m.group(1) + ": " + REDACTED, text, org)
    text, org = _sub(_BEARER, lambda m: m.group(1) + " " + REDACTED, text, org)
    text, org = _sub(_URLCRED, lambda m: m.group(1) + ":" + REDACTED + "@", text, org)
    text, org = _sub(_FLAG, lambda m: m.group(1) + m.group(2) + REDACTED, text, org)
    text, org = _sub(_USERFLAG, lambda m: m.group(1) + m.group(2) + REDACTED if ":" in m.group(3) else m.group(0), text, org)
    text, org = _sub(_ASSIGN, lambda m: m.group(1) + m.group(2) + REDACTED if m.group(3) != REDACTED else m.group(0), text, org)
    return text, org


def redact(text):
    return redact_tracked(text)[0]


# ---------------------------------------------------------------------------------------------------------------- the markers
_ESC = re.compile(r"\x1b(?:\[([0-9;:?]*)([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B]|[@-Z\\-_=>])")
_RED = {1, 9, 124, 160, 196, 197, 203, 167, 131, 88, 52}   # 256-colour reds that terminals use for errors


def _sgr(params, st, colon=False):
    """Apply one SGR sequence (a list of ints) to st = dict(rev, bold, dim, fg, bg). colon: the parameters were separated by colons."""
    i = 0
    if not params:
        params = [0]
    while i < len(params):
        n = params[i]
        if n == 0:
            st.update(rev=False, bold=False, dim=False, fg=None, bg=None)
        elif n == 1:
            st["bold"] = True
        elif n == 2:
            st["dim"] = True
        elif n == 22:
            st["bold"] = st["dim"] = False
        elif n == 7:
            st["rev"] = True
        elif n == 27:
            st["rev"] = False
        elif 30 <= n <= 37:
            st["fg"] = n - 30
        elif 90 <= n <= 97:
            st["fg"] = n - 90 + 8
        elif n == 39:
            st["fg"] = None
        elif 40 <= n <= 47:
            st["bg"] = n - 40
        elif 100 <= n <= 107:
            st["bg"] = n - 100 + 8
        elif n == 49:
            st["bg"] = None
        elif n in (38, 48, 58):
            # 58 is the underline colour: its parameters are skipped, never read as SGR codes (58;5;7 would be reverse video)
            key = "fg" if n == 38 else "bg" if n == 48 else None
            if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                if key:
                    st[key] = params[i + 2]
                i += 2
            elif i + 1 < len(params) and params[i + 1] == 2:
                # 2;r;g;b, or with a colour-space id between (38:2::r:g:b, 38:2:ID:r:g:b: the colon form has an empty or a numeric id)
                rgb = params[i + 2:i + 5]
                if len(params) - i - 2 >= 4 and colon:
                    rgb = params[i + 3:i + 6]
                    i += 1
                if len(rgb) == 3:
                    if key:
                        st[key] = ("rgb",) + tuple(rgb)
                    i += 4
                else:
                    i = len(params)
        i += 1


def _is_red(fg):
    if isinstance(fg, tuple):
        r, g, b = fg[1:]
        return r > 150 and g < 90 and b < 90
    return fg in _RED if isinstance(fg, int) else False


def _tags(st):
    """[sel] reverse video, [bg] a background colour (fzf and many menus mark the current line so), [err] red text. [bg] is dropped at render
    time when the span has no letter or digit (the logo of Claude Code is made of coloured blocks)."""
    t = []
    if st["rev"]:
        t.append("sel")
    elif st["bg"] is not None:
        t.append("bg")
    if _is_red(st["fg"]):
        t.append("err")
    return t


_LOOKALIKE = re.compile(r"(?<!\[)\[+(?=/?(?:sel|bg|err|REDACTED)\])")


def _parse(raw):
    """`capture-pane -e` output -> (text, styles): the plain text (every escape sequence removed, trailing blank lines and the spaces
    at the ends of the lines dropped later by _render) and one tuple of tags per character, ("sel",), ("bg", "err") and so on, () for none.
    Text that looks like a marker (`[sel]`, `[/err]`, `[REDACTED]`...) gets one more `[` in front of it, so that program output cannot forge
    a marker (see to_marked)."""
    parts, styles = [], []
    st = dict(rev=False, bold=False, dim=False, fg=None, bg=None)
    for li, line in enumerate(raw.split("\n")):
        if li:
            parts.append("\n")
            styles.append(())
        pos = 0

        def add(text):
            parts.append(text)
            styles.extend([tuple(_tags(st))] * len(text))
        for m in _ESC.finditer(line):
            if m.start() > pos:
                add(line[pos:m.start()])
            pos = m.end()
            if m.group(2) == "m":
                try:
                    p = m.group(1) or ""
                    _sgr([int(x) if x else 0 for x in re.split(r"[;:]", p)], st, ":" in p)
                except ValueError:
                    pass
        if pos < len(line):
            add(line[pos:])
    text = "".join(parts)
    keep = len(text.rstrip())
    text, styles = text[:keep], styles[:keep]
    return _sub(_LOOKALIKE, lambda m: m.group(0) + "[", text, styles)


def _render(text, styles, max_line=0):
    """(text, styles) -> text with spans written [sel]text[/sel], [bg]text[/bg], [err]text[/err]. A span never crosses a line; the spaces at
    the ends of a span and spans of only spaces are dropped (a cursor is a reverse space), trailing spaces of a line are cut. A line longer
    than max_line (when it is not 0) is cut there, after the secrets filter, and says how much is missing."""
    out_lines, pos = [], 0
    for line in text.split("\n"):
        st = styles[pos:pos + len(line)]
        pos += len(line) + 1
        more = ""
        if max_line and len(line) > max_line:
            more = " [... %d more characters]" % (len(line) - max_line)
            line, st = line[:max_line], st[:max_line]
        res, i = [], 0
        while i < len(line):
            j = i + 1
            while j < len(line) and st[j] == st[i]:
                j += 1
            tags, piece = st[i], line[i:j]
            i = j
            if "bg" in tags and not any(c.isalnum() for c in piece):
                tags = tuple(t for t in tags if t != "bg")
            if tags and piece.strip():
                lead = piece[:len(piece) - len(piece.lstrip())]
                tail = piece[len(piece.rstrip()):]
                res.append(lead + "".join("[%s]" % t for t in tags) + piece.strip() + "".join("[/%s]" % t for t in reversed(tags)) + tail)
            else:
                res.append(piece)
        out_lines.append(("".join(res) + more).rstrip())
    return "\n".join(out_lines).rstrip("\n")


def to_marked(raw):
    """`capture-pane -e` output -> text with spans written [sel]text[/sel], [bg]text[/bg], [err]text[/err] (see _render). Literal text of the
    pane that looks like a marker is escaped by one more `[`: `[sel]` in the pane reads `[[sel]`, `[[sel]` reads `[[[sel]`; a marker is a tag
    with a single `[`. The secrets filter is NOT applied here: the screen runs it on the plain text between _parse and _render, so that a
    marker in the middle of a secret cannot hide it."""
    return _render(*_parse(raw))


# ---------------------------------------------------------------------------------------------------------------- keys in braces
KEYS = {"Esc": "Escape", "Enter": "Enter", "Tab": "Tab", "BTab": "BTab", "Space": "Space", "BSpace": "BSpace", "Up": "Up", "Down": "Down",
        "Left": "Left", "Right": "Right", "Home": "Home", "End": "End", "PgUp": "PageUp", "PgDn": "PageDown", "Delete": "DC", "Insert": "IC"}
_TOKEN = re.compile(r"\{\{|\}\}|(?<!\$)\{([A-Za-z][A-Za-z0-9-]*)\}")


def parse_keys(text):
    """text with {Key} tokens -> [("text", str) | ("key", tmuxname)]. {{ and }} are a literal brace. A {word} that is not a known key stays
    the literal text it is ({"a": 1} is typed as it is). Names are CASE SENSITIVE and a `{` right after `$` is never a key, so `${Home}` and
    `${HOME}` stay shell variables. Known: the names in KEYS, C-a..C-z, M-<char>, F1..F12."""
    steps, pos, buf = [], 0, []

    def flush():
        if "".join(buf):
            steps.append(("text", "".join(buf)))
            del buf[:]
    for m in _TOKEN.finditer(text):
        buf.append(text[pos:m.start()])
        pos = m.end()
        tok = m.group(0)
        if tok in ("{{", "}}"):
            buf.append(tok[0])
            continue
        name = m.group(1)
        key = KEYS.get(name)
        if key is None and re.fullmatch(r"C-[a-z]", name):
            key = name
        elif key is None and re.fullmatch(r"M-[a-zA-Z0-9]", name):
            key = name
        elif key is None and re.fullmatch(r"F([1-9]|1[0-2])", name):
            key = name
        if key is None:
            buf.append(tok)
        else:
            flush()
            steps.append(("key", key))
    buf.append(text[pos:])
    flush()
    return steps


# ---------------------------------------------------------------------------------------------------------------- the state of an agent
_RULE = "─" * 6          # a line that starts so is a rule of the input box of Claude Code
_DASHED = "\u254c" * 6
_DIALOG_FOOTER = re.compile(r"Enter to confirm|Esc to cancel|Esc to exit")
_DIALOG_BODY = re.compile(r"Do you want to")


def _rule_rows(rows):
    return [i for i, r in enumerate(rows) if r.startswith(_RULE)]


def _has_rule(rows):
    """a rule of any kind: the solid one of the input box, the dashed ones that frame the command of a permission dialog"""
    return any(r.startswith(_RULE) or r.startswith(_DASHED) for r in rows)


def input_box(rows, lenient=False):
    """The text of the input box of Claude Code: what is between the last two rules, without the pointer (a pointer is followed by a no-break
    space). None when there is no box. lenient: a box whose top scrolled off the screen (a long text in it) has only its bottom rule; its
    text is then what is above that rule, from the last pointer line."""
    r = _rule_rows(rows)
    if len(r) >= 2:
        body = rows[r[-2] + 1:r[-1]]
    elif lenient and len(r) == 1 and len([x for x in rows[r[0] + 1:] if x.strip()]) <= 3:
        top = max([i for i, x in enumerate(rows[:r[0]]) if x.startswith("\u276f")] or [0])
        body = rows[top:r[0]]
    else:
        return None
    box = []
    for x in body:
        if x.startswith("\u276f"):
            x = x[1:]
        box.append(x[1:] if x[:1] in (" ", "\xa0") else x)
    return "\n".join(box).strip("\n")


def agent_state(rows, command=""):
    """(is_agent, state) for the rows of a plain screen: state is dialog, busy, idle or unknown. A screen is an agent's when it has the
    input box, or a dialog footer next to a rule, or the command is a known agent. Only the bottom of the screen is read: an old answer
    that says "Do you want to" is no dialog."""
    used = [r for r in rows if r.strip()]
    bottom = used[-14:]
    box = input_box(rows) is not None
    footer = used[-4:]
    dialog = _has_rule(rows) and (any(_DIALOG_FOOTER.search(x) for x in footer) or (not box and any(_DIALOG_BODY.search(x) for x in used[-12:])))
    agent = box or dialog or os.path.basename(command) in AGENT_COMMANDS
    if not agent:
        return False, "unknown"
    if dialog:
        return True, "dialog"
    if any("esc to interrupt" in x for x in bottom[-3:]):
        return True, "busy"
    return True, "idle" if box else "unknown"


class TmuxDriver:
    def __init__(self, error, session=None, socket=None, pause=PAUSE, timeout=TMUX_TIMEOUT, verify_timeout=VERIFY_TIMEOUT, binary=None):
        self.error = error
        self.session = session or os.environ.get("SB_BUS_TMUX_SESSION") or "main"
        self.socket = socket if socket is not None else os.environ.get("SB_BUS_TMUX_SOCKET")
        self.binary = binary or os.environ.get("SB_BUS_TMUX_BIN") or "tmux"
        self.pause, self.timeout, self.verify_timeout = pause, timeout, verify_timeout
        self._locks = {}
        self._locks_guard = threading.Lock()

    # ---- tmux
    def tmux(self, *args, check=True):
        argv = [self.binary] + (["-L", self.socket] if self.socket else []) + [str(a) for a in args]
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        try:
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise self.error("timeout", "tmux %s did not answer in %g s" % (args[0], self.timeout))
        except FileNotFoundError:
            raise self.error("no_tmux", "tmux is not installed")
        except OSError as e:
            raise self.error("no_tmux", "cannot run tmux: %s" % (e.strerror or e))
        out = p.stdout.decode("utf-8", "replace")
        if check and p.returncode != 0:
            msg = p.stderr.decode("utf-8", "replace").strip() or "tmux %s failed" % args[0]
            if "no server running" in msg or "can't find session" in msg or "error connecting" in msg:
                raise self.error("no_session", "no tmux session %s (%s)" % (self.session, msg))
            if "can't find pane" in msg or "can't find window" in msg:
                raise self.error("no_such_tab", "the tab closed (%s)" % msg)
            raise self.error("tmux_error", msg)
        return out

    # ---- tabs
    def _windows(self):
        """[Tab] of the session, panels hidden, in window order (the `active` flag is not set)."""
        # Names, paths and commands are text that a program can choose (a window name, a directory, the name of a process), so each of them
        # is asked in a call of its own, as the LAST field of its lines and cut with a limit: whatever it holds, even SEP, it cannot move the
        # other fields. The fields before it are ids, numbers and flags.
        def ask(*fields):
            fmt = SEP.join(fields)
            try:
                listing = self.tmux("list-panes", "-s", "-t", "=" + self.session, "-F", fmt)
            except self.error as e:
                if e.code == "no_such_tab":         # the target of this call is the session: "can't find window" means it is not there
                    raise self.error("no_session", "no tmux session %s (%s)" % (self.session, e.message))
                raise
            return [line.split(SEP, len(fields) - 1) for line in listing.splitlines()]
        flags = ["#{?#{%s},1,0}" % o for o in HIDDEN_OPTIONS]
        wins, order, panes = {}, [], {}
        first = ask("#{window_id}", "#{window_index}", "#{pane_id}", "#{pane_active}", "#{pane_last}", *flags, "#{pane_start_command}", "#{window_name}")
        for p in first:
            n = len(HIDDEN_OPTIONS)
            if len(p) != 7 + n or any(f == "1" for f in p[5:5 + n]):
                continue
            # a panel pane is also known by the marker in its start command: split-window makes the pane before the option can be set on it
            if any(m in p[5 + n] for m in HIDDEN_MARKERS):
                continue
            if p[0] not in wins:
                try:
                    idx = int(p[1])
                except ValueError:
                    continue
                wins[p[0]] = {"index": idx, "name": p[-1], "rows": []}
                order.append(p[0])
            wins[p[0]]["rows"].append(p)
            panes[p[2]] = p

        def column(field):
            # a value with a newline in it (a directory can be named so) would add lines, even lines that look like another pane's: when the
            # pane ids of the answer are not exactly those of the first call, the values are not trusted at all
            rows = ask("#{pane_id}", field)
            ok = [p[0] for p in rows] == [p[2] for p in first if len(p) > 2] and all(len(p) == 2 for p in rows)
            return {p[0]: p[1] for p in rows} if ok else {}
        cwds, cmds = column("#{pane_current_path}"), column("#{pane_current_command}")
        home = os.path.expanduser("~")
        tabs = []
        for wid in order:
            w = wins[wid]
            rows = w["rows"]
            # the active pane; when the focus is in a panel (not in `rows`) the pane that had it before it, else the first
            row = next((r for r in rows if r[3] == "1"), None) or next((r for r in rows if r[4] == "1"), rows[0])
            cwd = cwds.get(row[2], "")
            if home != "/" and (cwd == home or cwd.startswith(home + "/")):
                cwd = "~" + cwd[len(home):]
            tabs.append(Tab(wid, w["index"], w["name"], cwd, cmds.get(row[2], ""), row[2], [r[2] for r in rows], False, "%d:%s" % (w["index"], w["name"])))
        return tabs

    def _shown(self, ids):
        """The window id of the active tab: the window of the non-control client with the latest activity among those that show a tab,
        else the current window of the session, else the first tab."""
        fmt = SEP.join(["#{client_activity}", "#{window_id}", "#{client_control_mode}"])
        rows = []
        for line in self.tmux("list-clients", "-F", fmt, check=False).splitlines():
            p = line.split(SEP)
            if len(p) == 3 and p[2] != "1" and p[1] in ids:
                try:
                    rows.append((int(p[0] or 0), p[1]))
                except ValueError:
                    pass
        if rows:
            return max(rows, key=lambda r: r[0])[1]
        cur = self.tmux("display-message", "-p", "-t", "=%s:" % self.session, "#{window_id}", check=False).strip()
        return cur if cur in ids else (next(iter(ids)) if ids else None)

    def tabs(self):
        tabs = self._windows()
        shown = self._shown([t.id for t in tabs]) if tabs else None
        return [t._replace(active=t.id == shown) for t in tabs]

    def list_tabs(self):
        return [{"tab": t.id, "label": t.label, "index": t.index, "name": t.name, "dir": t.cwd, "cmd": t.command, "pane": t.pane,
                 "panes": t.panes, "active": t.active} for t in self.tabs()]

    def resolve(self, tab):
        """Tab for "@3", "1:name" (the label), "1" (the index) or "name". no_such_tab, or ambiguous_tab with the candidates."""
        tabs = self._windows()
        s = str(tab)
        hit = [t for t in tabs if t.id == s] or [t for t in tabs if t.label == s] or [t for t in tabs if s.isdigit() and t.index == int(s)] \
            or [t for t in tabs if t.name == s]
        if not hit:
            raise self.error("no_such_tab", "no tab %s; the tabs are: %s" % (s, ", ".join("%s (%s)" % (t.label, t.id) for t in tabs) or "none"))
        if len(hit) > 1:
            raise self.error("ambiguous_tab", "the name %s is used by %s: use the id" % (s, ", ".join("%s (%s)" % (t.label, t.id) for t in hit)))
        return hit[0]

    # ---- the screen
    def _plain_rows(self, pane):
        raw = self.tmux("capture-pane", "-p", "-J", "-t", pane)
        return [x.rstrip() for x in raw.split("\n")]

    def screen(self, tab, lines):
        t = self.resolve(tab)
        fmt = SEP.join(["#{cursor_x}", "#{cursor_y}", "#{pane_in_mode}", "#{alternate_on}", "#{pane_width}", "#{pane_height}", "#{pane_mode}"])
        meta = self.tmux("display-message", "-p", "-t", t.pane, fmt).rstrip("\n").split(SEP)
        if len(meta) != 7:
            raise self.error("tmux_error", "unexpected answer of display-message")
        alternate = meta[3] == "1"
        n = None if alternate else lines     # a full-screen program has no scrollback: only the visible screen exists
        args = ["capture-pane", "-p", "-J", "-e", "-t", t.pane]
        if n:
            args += ["-S", "-%d" % int(n)]
        text, styles = _parse(self.tmux(*args))
        if n:       # -S -N counts N lines above the top of the screen, so the capture has N + height lines: keep the last N
            rows = text.split("\n")
            if len(rows) > int(n):
                cut = len("\n".join(rows[:-int(n)])) + 1
                text, styles = text[cut:], styles[cut:]
        # the secrets are found in the plain text, whole lines, whatever the colours: the markers are written afterwards, and the cut of a long
        # line comes last, so no secret is cut in half
        text, styles = redact_tracked(text, styles)
        text = _render(text, styles, MAX_LINE)
        return {"tab": t.id, "pane": t.pane, "text": text, "cursor": [int(meta[0]), int(meta[1])], "alternate": alternate,
                "in_mode": meta[2] == "1", "mode": meta[6], "size": [int(meta[4]), int(meta[5])], "lines": n}

    # ---- typing
    def _lock(self, pane):
        with self._locks_guard:
            return self._locks.setdefault(pane, threading.Lock())

    def _body(self, body):
        """(steps, submit, queue, slash) of a body, or bad_body."""
        ok = isinstance(body, dict) and 1 <= len(body) <= 3 and ("run" in body) != ("input" in body)
        if ok:
            ok = all(k in ("run", "input", "queue", "slash") for k in body) and all(isinstance(body[k], bool) for k in ("queue", "slash") if k in body)
        key = "run" if isinstance(body, dict) and "run" in body else "input"
        if not ok or not isinstance(body.get(key), str) or not body[key]:
            raise self.error("bad_body", 'the body of a tab message is {"run": text} or {"input": text}, with the optional booleans "queue" and "slash"')
        text = body[key]
        if "\x00" in text:
            raise self.error("bad_body", "the text holds a NUL character")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise self.error("bad_body", "the text is not valid Unicode (a lone surrogate)")
        steps = [("text", text), ("key", "Enter")] if key == "run" else parse_keys(text)
        if not steps:
            raise self.error("bad_body", "nothing to type")
        if len(steps) > MAX_STEPS:
            raise self.error("bad_body", "%d steps (texts and keys) in one message, at most %d: send it in several messages" % (len(steps), MAX_STEPS))
        has_text = any(k == "text" for k, _ in steps)
        return steps, has_text and any(k == "key" and v == "Enter" for k, v in steps), bool(body.get("queue")), bool(body.get("slash"))

    def send(self, tab, body):
        steps, submit, queue, slash = self._body(body)
        t = self.resolve(tab)
        with self._lock(t.pane):
            if self.tmux("display-message", "-p", "-t", t.pane, "#{pane_in_mode}").strip() == "1":
                self.tmux("send-keys", "-t", t.pane, "-X", "cancel")
            agent = False
            submitted = self._submitted(steps)
            if submit:
                agent, state = agent_state(self._plain_rows(t.pane), t.command)
                if agent:
                    if state == "dialog":
                        raise self.error("dialog_open", "a dialog is open in the tab; answer it with input (a key), nothing was typed")
                    if state == "busy" and not queue:
                        raise self.error("busy_tab", 'the agent in the tab is busy; nothing was typed (use "queue": true to queue the message, or interrupt it with {Esc})')
                    if len(submitted) > 1 and not queue:
                        # the state above is read once: after the first Enter the agent works, so the later texts would be typed into a busy agent
                        raise self.error("busy_tab", 'the message submits %d texts to an agent, and the agent is busy after the first; nothing was typed (use "queue": true, or send one message per text)' % len(submitted))
                    if not slash and any(steps[i][1][:1] in ("/", "!") for i in submitted):
                        raise self.error("slash_refused", 'text that starts with "/" or "!" is a command for the agent, not a prompt; nothing was typed ("slash": true allows it)')
            last_enter = max(i for i, (k, v) in enumerate(steps) if k == "key" and v == "Enter") if submit else -1
            for i, (kind, val) in enumerate(steps):
                if i and self.pause:
                    time.sleep(self.pause)
                if kind == "text":
                    self._type(t.pane, val)
                else:
                    self.tmux("send-keys", "-t", t.pane, val)
                if agent and i == last_enter:
                    self._verify(t, steps, i)

    @staticmethod
    def _submitted(steps):
        """indexes of the text steps that are followed by an Enter before the next text step: the texts that are submitted"""
        out, pending = [], None
        for i, (k, v) in enumerate(steps):
            if k == "text":
                pending = i
            elif v == "Enter" and pending is not None:
                out.append(pending)
                pending = None
        return out

    def _type(self, pane, text):
        """Type a text literally, in pieces of CHUNK characters (one word of send-keys must stay small: tmux refuses a command over 16 KB and
        the kernel an argument over 128 KB). tmux reads a word that ends in `;` as the end of the command and drops the `;` (and turns a
        final `\\;` into `;`), so the semicolons at the end of a piece are sent as the key 0x3b (send-keys -H) instead."""
        for i in range(0, len(text), CHUNK):
            piece = text[i:i + CHUNK]
            body = piece.rstrip(";")
            if body:
                self.tmux("send-keys", "-t", pane, "-l", "--", body)
            if len(body) != len(piece):
                self.tmux("send-keys", "-t", pane, "-H", *["3b"] * (len(piece) - len(body)))

    @staticmethod
    def _tail(steps, upto):
        """the last characters of the last non-empty line of the last text step before upto"""
        for k, v in reversed(steps[:upto]):
            if k == "text":
                for ln in reversed(v.split("\n")):
                    if ln.strip():
                        return ln.strip()[-12:]
                return ""
        return ""

    def _verify(self, t, steps, enter_index):
        """After the Enter: wait until the text left the input box (or the agent is busy or showing a dialog). If it did not within
        VERIFY_TIMEOUT, press Enter once more, only when the text is still in the box (an Enter on an empty box could accept a suggestion)."""
        tail = self._tail(steps, enter_index)
        if not tail:
            return

        def left_in_box():
            rows = self._plain_rows(t.pane)
            _, state = agent_state(rows, t.command)
            box = input_box(rows, lenient=True)
            return state in ("idle", "unknown") and box is not None and (tail in box or "[Pasted text" in box)
        for attempt in (1, 2):
            end = time.time() + self.verify_timeout
            while True:
                if not left_in_box():
                    return
                if time.time() >= end:
                    break
                time.sleep(0.1)
            if attempt == 1:
                self.tmux("send-keys", "-t", t.pane, "Enter")
        raise self.error("not_submitted", "the text was typed but did not leave the input box")
