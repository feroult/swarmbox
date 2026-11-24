#!/usr/bin/python3 -S
"""swarmbox-tabs: the tabs of the box (the terminals of herdr-core, `hc`), a capability of the host. One file, standard library only: it is
a command line and, at the same time, the library the addons can import by path. No daemon: a call reads or acts on herdr-core and ends.

  swarmbox-tabs list                                     the tabs, a JSON list
  swarmbox-tabs active                                   the active tab, a JSON object
  swarmbox-tabs screen TAB [--lines N]                   the text on the tab now (JSON object, see below)
  swarmbox-tabs send TAB (--run TEXT | --input TEXT) [--queue] [--slash]
                                                         type into the tab. --run types TEXT and presses Enter; --input types TEXT as it is
                                                         ({Esc} {C-c} {Enter} {Up} ... are keys, see KEYS). TEXT "-" reads stdin (long or
                                                         multi-line text: one trailing newline is dropped). --queue types although the agent in
                                                         the tab is busy; --slash allows a first character "/" or "!" for an agent.
  swarmbox-tabs open [--name NAME] [--cwd DIR] [--agent AGENT]
                                                         open a tab: a login shell, or an agent of ALLOWED_OPEN_AGENTS; it becomes the active tab
  swarmbox-tabs focus TAB                                make TAB the active tab
  swarmbox-tabs close TAB                                end the program of TAB and remove the tab

Output: JSON on stdout, always. Success: the object or list above; send answers {"ok":true,"tab":"t3","pane":"t3","submitted":BOOL}. A
failure is {"err":CODE,"msg":TEXT} (also on stdout, so a program has one place to read) and a non-zero exit.
Exit codes: 0 ok; 1 the call was understood and refused or failed: no_such_tab ambiguous_tab dialog_open busy_tab slash_refused
not_submitted backend_error lock_error unsupported; 2 usage or a text that cannot be typed (usage, bad_body); 4 herdr-core is not there:
no_backend (no `hc` program, or an unknown SB_TABS_BACKEND), or no_session (the herdr-core server does not answer); 5 timeout (an `hc`
call, or an earlier send to the same tab still running).

Tabs.  A tab is a live terminal of herdr-core. The address is its terminal address "t3" (stable, never reused), and the label
"index:name" is accepted too, as is a bare index (1, 2 ... in the order the terminals were created) or a bare name; a name used by two
tabs is the error ambiguous_tab that lists the candidates. Terminals labelled swarmbox.role=sysop (HIDDEN_HERDR_ROLES) are never listed and
never a target. The active tab is the one named in <run folder>/herdr-active-tab (written by whoever opens or focuses a tab: the web
studio, the cockpit, `open` and `focus` here), or the first tab when that file names none of them.
  list:    one object per tab: tab "t3" (the address), label "1:name", index, name, dir, cmd, pane (the address again), panes, active (true
           for exactly one), and status when the program reported one (OSC 7501: state, progress, msg, app)
  screen:  {"tab", "pane", "text", "cursor", "alternate", "in_mode", "mode", "size", "lines"}; text is made from the text of the terminal:
           the last `lines` lines, the secrets removed (on whole lines, whatever the colours), then the markers written and a line longer
           than 1000 characters cut. Text of the terminal that looks like a marker has one more `[` (see to_marked)

Environment.  SB_TABS_HC_BIN or SB_TABS_BIN (the hc program, default hc), SB_RUN_DIR (the run folder: the locks are in its subfolder tabs/
and the active tab in herdr-active-tab, default /tmp/swarmbox), SB_TABS_BACKEND (herdr, the only backend; a test seam). Every hc call has a
timeout.

Typing.  The text goes as literal UTF-8 over `hc connect` (a framed terminal.attach, in pieces of CHUNK bytes, no Enter), then, after
PAUSE seconds, each key (the Enter of --run too) as its own `hc keys` call: never one burst, because a terminal program that sees text and
Enter in one burst treats it as a paste and the Enter becomes a line break (docs/spikes/enter.md: 0 of 4 at 600 characters).
When the tab runs an agent (the state it reports with OSC 7501; else Claude Code's screen: the input box between two rules, a dialog, "esc
to interrupt"; or the command is a known agent) and the message submits text (text followed by Enter): a dialog is refused (dialog_open), a
busy agent is refused unless --queue, a text that starts with "/" or "!" is refused unless --slash (it would open a menu or run a shell
command; every text that is submitted is checked, not only the first, and a body that submits more than one text to an agent needs
--queue, because the agent is busy after the first), and after the Enter the call checks that the end of the text left the input box,
pressing Enter once more only when it did not (not_submitted when it still did not).
Plain --input (keys, or text without Enter) is not judged: it is how a dialog is answered and a busy agent interrupted.

The lock.  A send holds an flock on <run folder>/tabs/tab-<address>.lock for as long as it types (the kernel drops it however the process
dies), so two sends to one tab, from any processes, never interleave; the second waits up to LOCK_TIMEOUT seconds and then fails with timeout,
nothing typed. Reads (list, active, screen) take no lock. The lock files of tabs that are gone are deleted when there are more than LOCK_KEEP (64) of them.
No other state is kept.

The library.  Importing this file by path (importlib.util.spec_from_file_location) gives the class Tabs, the same calls without
a process: list_tabs(), active(), screen(tab, lines=None), send(tab, run=None, input=None, queue=False, slash=False), open_tab(name, cwd,
agent), focus_tab(tab), close_tab(tab); failures are raised as TabsError(code, message). Tabs(backend=...) takes any TabsBackend (the
contract between the facade and the multiplexer; HerdrBackend is the one of the box). The pure functions (redact, to_marked, parse_keys,
agent_state, input_box) are importable too. Recommended for an addon: run the command, not the library. The command is the contract (JSON,
exit codes, the lock, the timeouts, the same code path as every other caller, nothing to import from the host's files, a failure that cannot
take the addon's process down); the library is for tests and for this file's own main(). The cost is one Python start-up (about 15 ms) per call.
"""
import contextlib
import fcntl
import json
import os
import re
import struct
import subprocess
import sys
import time
from collections import namedtuple

HIDDEN_HERDR_ROLES = ("sysop",)                   # herdr-core labels["swarmbox.role"] values hidden from normal tab lists
PAUSE = 0.15
MAX_STEPS = 100          # steps (texts and keys) of one send: each key costs PAUSE plus an hc process (about 0.15 s)
LOCK_TIMEOUT = 30.0      # seconds a send waits for an earlier send to the same tab
LOCK_KEEP = 64           # lock files of tabs that are gone are deleted past this many (see Tabs._sweep_locks)
MAX_STDIN = 1 << 20      # bytes of a text read from stdin
CHUNK = 1024             # bytes of one DATA frame of `hc connect` when text is typed
TIMEOUT = 5.0            # seconds of one hc call
MAX_LINE = 1000          # characters of one line of a screen, cut after the secrets filter (see _render)
VERIFY_TIMEOUT = 5.0     # seconds to see the text leave the input box after an Enter
AGENT_COMMANDS = ("claude", "gemini", "opencode", "codex", "agy")
REDACTED = "[REDACTED]"

Tab = namedtuple("Tab", "id index name cwd command pane panes active label")
ScreenCapture = namedtuple("ScreenCapture", "raw cursor alternate in_mode mode size lines")

# exit code of the command for each error code (the others are 1); see the docstring
EXIT = {"usage": 2, "bad_body": 2, "no_session": 4, "no_backend": 4, "timeout": 5}


class TabsError(Exception):
    """A failure of the tabs: `code` is a short word (no_such_tab, dialog_open, ...), `message` the text for a person."""

    def __init__(self, code, message=""):
        Exception.__init__(self, "%s: %s" % (code, message) if message else code)
        self.code, self.message = code, message


# ---------------------------------------------------------------------------------------------------------------- the secrets filter
# The one secrets filter of the box: every screen swarmbox-tabs reads passes through it. Its patterns run in linear time (no pattern
# rescans a long run from every position inside it); tests/fast/test_tabs_redact_dos.py measures that on adversarial text.

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


_TOKEN_END = re.compile(r"[A-Za-z0-9_-]{16,}$")
_TOKEN_ROW = re.compile(r"[A-Za-z0-9_-]+$")


def _wrapped_spans(text):
    """Spans (start, end) of the secrets that a program wrapped with hard line breaks (a TUI at a narrow width): the rows are joined, the token
    patterns run on the joined text and each match is mapped back to the rows. A group is a row that ends with 16 or more token characters
    followed by rows made only of token characters, as long as each row but the last ends with 16 or more of them. The line-wise pass cannot
    see these: the continuation rows have no keyword or prefix."""
    spans, lines, pos, i = [], text.split("\n"), 0, 0
    starts = []
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and _TOKEN_END.search(lines[j]) and _TOKEN_ROW.match(lines[j + 1]):
            j += 1
        if j == i:
            i += 1
            continue
        joined, idx = [], []
        for k in range(i, j + 1):
            joined.append(lines[k])
            idx.extend(range(starts[k], starts[k] + len(lines[k])))
        joined = "".join(joined)
        for pat in _PATTERNS:
            for m in pat.finditer(joined):
                a = m.end("keep") if "keep" in pat.groupindex and m.group("keep") is not None else m.start()
                b = m.end()
                run = None
                for q in range(a, b):
                    if run is not None and idx[q] == run[1]:
                        run[1] += 1
                    else:
                        if run is not None:
                            spans.append(tuple(run))
                        run = [idx[q], idx[q] + 1]
                if run is not None:
                    spans.append(tuple(run))
        i = j + 1
    return spans


def _replace_spans(text, org, spans):
    """text with each span replaced by REDACTED; a replacement takes the org entry of the first character it replaces."""
    out, o2, pos = [], [], 0
    for a, b in sorted(set(spans)):
        if a < pos:
            a = pos
        if b <= a:
            continue
        out.append(text[pos:a] + REDACTED)
        if org is not None:
            o2.extend(org[pos:a])
            o2.extend([org[a]] * len(REDACTED))
        pos = b
    out.append(text[pos:])
    if org is not None:
        o2.extend(org[pos:])
    return "".join(out), (o2 if org is not None else None)


def redact_tracked(text, org=None):
    """(text, org) with the secrets removed; org is None when it was None (see _sub)."""
    spans = _wrapped_spans(text)
    if spans:
        text, org = _replace_spans(text, org, spans)
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
    """the text of a terminal, with its escape sequences -> (text, styles): the plain text (every escape sequence removed, trailing blank lines and the spaces
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
    """the text of a terminal, with its escape sequences -> text with spans written [sel]text[/sel], [bg]text[/bg], [err]text[/err] (see _render). Literal text of the
    pane that looks like a marker is escaped by one more `[`: `[sel]` in the pane reads `[[sel]`, `[[sel]` reads `[[[sel]`; a marker is a tag
    with a single `[`. The secrets filter is NOT applied here: the screen runs it on the plain text between _parse and _render, so that a
    marker in the middle of a secret cannot hide it."""
    return _render(*_parse(raw))


# ---------------------------------------------------------------------------------------------------------------- keys in braces
KEYS = {"Esc": "Escape", "Enter": "Enter", "Tab": "Tab", "BTab": "BTab", "Space": "Space", "BSpace": "BSpace", "Up": "Up", "Down": "Down",
        "Left": "Left", "Right": "Right", "Home": "Home", "End": "End", "PgUp": "PageUp", "PgDn": "PageDown", "Delete": "DC", "Insert": "IC"}
_TOKEN = re.compile(r"\{\{|\}\}|(?<!\$)\{([A-Za-z][A-Za-z0-9-]*)\}")


def parse_keys(text):
    """text with {Key} tokens -> [("text", str) | ("key", name)] (name: a value of KEYS, C-x, M-x or F1..F12, mapped to the spelling of `hc keys` by _hc_key_name). {{ and }} are a literal brace. A {word} that is not a known key stays
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


_INTERRUPT = "esc to interrupt"


def _footer_busy(row):
    """The footer of Claude Code while it works ends with `· esc to interrupt`. In a narrow pane the end is cut (`· esc to in…`, `· esc …`, a lone `·`) and
    the words are not whole on the screen, which a phone held sideways (about 60 columns) does. So: after the last `·` of the row, nothing, or a start of
    those words (with an ellipsis or not). A pane of about 30 columns shows no `·` at all: nothing on that screen tells busy from idle."""
    if "\u00b7" not in row:
        return False
    tail = row.rsplit("\u00b7", 1)[1].strip().rstrip("\u2026").strip().lower()
    return _INTERRUPT.startswith(tail)


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
    if any("esc to interrupt" in x for x in bottom[-3:]) or (box and _footer_busy(used[-1])):
        return True, "busy"
    return True, "idle" if box else "unknown"


# ---------------------------------------------------------------------------------------------------------------- multiplexer backends


class TabsBackend:
    """Contract between the mux-agnostic Tabs facade (redaction, markers, key parsing, locking, agent rules) and a concrete multiplexer."""

    name = "abstract"

    def list_tabs_raw(self):
        """Return [Tab] in display order (the `active` flag is filled by Tabs.tabs())."""
        raise NotImplementedError

    def active_tab_id(self, tab_ids):
        """Return the id of the active tab among `tab_ids`, or None."""
        raise NotImplementedError

    def capture_screen(self, tab, lines):
        """Return ScreenCapture(raw, cursor, alternate, in_mode, mode, size, lines) for `tab`."""
        raise NotImplementedError

    def capture_plain_rows(self, tab):
        """Return plain (non-ANSI) screen rows for `tab`."""
        raise NotImplementedError

    def prepare_send(self, tab):
        """Run any backend-specific preparation before typing (nothing for herdr-core)."""

    def send_text(self, tab, text):
        """Type literal `text` into `tab`."""
        raise NotImplementedError

    def send_key(self, tab, key):
        """Press a single normalized key name (from KEYS / C-x / M-x / F1..F12) in `tab`."""
        raise NotImplementedError

    def live_tab_ids(self):
        """Return a set of live tab ids (used by lock sweeping)."""
        return {t.id for t in self.list_tabs_raw()}

    def tab_state(self, tab):
        """Optional native agent state `(is_agent, state)` where state is dialog|busy|idle|unknown.
        Return None to fall back to screen-based agent_state() heuristics."""
        return None

    def tab_status(self, tab):
        """Optional native status dict (e.g. OSC 7501 state/progress/msg/app) for list_tabs()."""
        return None

    def tab_labels(self, tab):
        """Optional labels dict for `tab` (e.g. swarmbox.title, swarmbox.pin_id, swarmbox.worktree)."""
        return {}

    def rename_tab(self, tab, title, source="user"):
        """Set display title metadata on `tab`."""
        raise TabsError("unsupported", "backend %s cannot rename tabs" % self.name)

    def set_labels(self, tab, labels):
        """Set arbitrary key=value labels on `tab`."""
        raise TabsError("unsupported", "backend %s cannot label tabs" % self.name)

    def open_tab(self, name=None, cwd=None, agent=None, labels=None):
        """Open a new terminal tab (allowlisted agent or shell) and return its id."""
        raise TabsError("unsupported", "backend %s cannot open tabs" % self.name)

    def focus_tab(self, tab):
        """Switch the active tab to `tab`."""
        raise TabsError("unsupported", "backend %s cannot focus tabs" % self.name)

    def close_tab(self, tab):
        """Close `tab` and end its program."""
        raise TabsError("unsupported", "backend %s cannot close tabs" % self.name)


ALLOWED_OPEN_AGENTS = {
    "shell": None,
    "claude": ["claude"],
    "agy": ["agy"],
    "opencode": ["opencode"],
    "codex": ["codex"],
    "gemini": ["gemini"],
}


_HC_KEYS = {
    "Escape": "esc", "Enter": "enter", "Tab": "tab", "BTab": "shift+tab", "Space": "space", "BSpace": "backspace",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right", "Home": "home", "End": "end",
    "PageUp": "pageup", "PageDown": "pagedown", "DC": "delete", "IC": "insert",
}


def _hc_key_name(key):
    """Map a normalized swarmbox-tabs key name (KEYS / C-x / M-x / F1..F12) to herdr-core's key spelling."""
    if key in _HC_KEYS:
        return _HC_KEYS[key]
    if key.startswith("C-") and len(key) == 3:
        return "ctrl+" + key[2].lower()
    if key.startswith("M-") and len(key) == 3:
        return "alt+" + key[2].lower()
    if re.fullmatch(r"F([1-9]|1[0-2])", key):
        return key.lower()
    return key.lower()


class HerdrBackend(TabsBackend):
    """Concrete TabsBackend talking to a herdr-core (hc) daemon.

    Uses `hc ls/get/read/keys --json` for queries and key presses, framed `hc connect` (`terminal.attach` DATA)
    for arbitrary literal UTF-8 text without Enter, and native OSC 7501 status via `tab_state()` when reported.
    """

    name = "herdr"

    def __init__(self, binary=None, timeout=TIMEOUT, run_dir=None):
        self.binary = binary or os.environ.get("SB_TABS_HC_BIN") or os.environ.get("SB_TABS_BIN") or "hc"
        self.timeout = timeout
        self.run_dir = run_dir or os.environ.get("SB_RUN_DIR") or "/tmp/swarmbox"
        self._meta = {}

    def _raise_hc_error(self, kind, msg):
        low = (msg or "").lower()
        if kind in ("not_found", "finished") or "no terminal" in low or "has finished" in low:
            raise TabsError("no_such_tab", msg or "no such terminal")
        if kind == "blocked":
            raise TabsError("dialog_open", msg or "terminal is blocked on a dialog")
        if kind in ("not_running", "connection", "unavailable") or any(
            w in low for w in ("not running", "connection refused", "connect", "no such file", "server is not")
        ):
            raise TabsError("no_session", "herdr-core is not running (%s); start it with `hc server start`" % (msg or kind))
        raise TabsError("backend_error", msg or kind or "hc failed")

    def hc(self, *args, check=True):
        argv = [self.binary] + [str(a) for a in args]
        try:
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise TabsError("timeout", "hc %s did not answer in %g s" % (args[0] if args else "", self.timeout))
        except FileNotFoundError:
            raise TabsError("no_backend", "hc (herdr-core) is not installed")
        except OSError as e:
            raise TabsError("no_backend", "cannot run hc: %s" % (e.strerror or e))
        raw = p.stdout.decode("utf-8", "replace").strip()
        err_txt = p.stderr.decode("utf-8", "replace").strip()
        data = None
        if raw:
            try:
                data = json.loads(raw)
            except ValueError:
                data = None
        if isinstance(data, dict) and isinstance(data.get("error"), dict):
            if check:
                err = data["error"]
                self._raise_hc_error(str(err.get("kind", "")), str(err.get("message", "") or err_txt))
            return None
        if check and p.returncode != 0:
            self._raise_hc_error("", err_txt or raw or ("hc %s failed (exit %d)" % (args[0] if args else "", p.returncode)))
        return data

    @staticmethod
    def _cmd_of(entry):
        fg = entry.get("foreground")
        if isinstance(fg, dict) and fg.get("name"):
            return os.path.basename(str(fg["name"]))
        if entry.get("agent"):
            return os.path.basename(str(entry["agent"]))
        argv = entry.get("argv")
        if isinstance(argv, list) and argv:
            return os.path.basename(str(argv[0]))
        return ""

    def _hidden_addresses(self):
        """Return addresses of live terminals carrying a hidden swarmbox.role label.

        `hc ls --json` returns compact summaries without `labels`, so we query server-side with
        `--label swarmbox.role=<role>`.
        """
        hidden = set()
        for role in HIDDEN_HERDR_ROLES:
            res = self.hc("ls", "--json", "--label", "swarmbox.role=%s" % role, check=False)
            if isinstance(res, dict):
                for e in res.get("terminals") or []:
                    if isinstance(e, dict) and e.get("address"):
                        hidden.add(str(e["address"]))
        return hidden

    def list_tabs_raw(self):
        res = self.hc("ls", "--json")
        if not isinstance(res, dict):
            raise TabsError("backend_error", "unexpected answer from hc ls --json")
        hidden = self._hidden_addresses()
        entries = [
            e for e in (res.get("terminals") or [])
            if isinstance(e, dict)
            and e.get("state", "live") == "live"
            and str(e.get("address") or "") not in hidden
            and not (isinstance(e.get("labels"), dict) and e["labels"].get("swarmbox.role") in HIDDEN_HERDR_ROLES)
        ]
        entries.sort(key=lambda e: (e.get("created_ms", 0), str(e.get("address", ""))))
        home = os.path.expanduser("~")
        tabs = []
        self._meta = {}
        for idx, e in enumerate(entries, 1):
            addr = str(e.get("address") or "")
            if not addr:
                continue
            self._meta[addr] = e
            name = str(e.get("name") or addr)
            cwd = str(e.get("cwd") or "")
            if home != "/" and (cwd == home or cwd.startswith(home + "/")):
                cwd = "~" + cwd[len(home):]
            cmd = self._cmd_of(e)
            tabs.append(Tab(addr, idx, name, cwd, cmd, addr, [addr], False, "%d:%s" % (idx, name)))
        return tabs

    def active_tab_id(self, tab_ids):
        if not tab_ids:
            return None
        marker = os.path.join(self.run_dir, "herdr-active-tab")
        try:
            with open(marker, encoding="utf-8") as f:
                cur = f.read().strip()
            if cur in tab_ids:
                return cur
        except OSError:
            pass
        return tab_ids[0]

    def _get_meta(self, tab_id, fresh=False):
        if not fresh:
            cached = self._meta.get(tab_id)
            if isinstance(cached, dict) and "cols" in cached and "rows" in cached:
                return cached
        res = self.hc("get", "--json", tab_id, check=False)
        if isinstance(res, dict) and res.get("address"):
            self._meta[tab_id] = res
            return res
        return self._meta.get(tab_id) or {}

    def capture_plain_rows(self, tab):
        res = self.hc("read", "--json", tab.id)
        if not isinstance(res, dict):
            raise TabsError("backend_error", "unexpected answer from hc read --json")
        raw = str(res.get("text") or "")
        return [x.rstrip() for x in raw.split("\n")]

    def capture_screen(self, tab, lines):
        args = ["read", "--json"]
        if lines:
            args += ["--lines", str(int(lines))]
        args.append(tab.id)
        res = self.hc(*args)
        if not isinstance(res, dict):
            raise TabsError("backend_error", "unexpected answer from hc read --json")
        meta = self._get_meta(tab.id)
        cols = int(meta.get("cols") or 80)
        rows = int(meta.get("rows") or 24)
        alternate = res.get("how") == "stitched"
        return ScreenCapture(str(res.get("text") or ""), [0, 0], alternate, False, "", [cols, rows], None if alternate else lines)

    def prepare_send(self, tab):
        pass

    def _framed_write(self, tab_id, payload_bytes):
        """Deliver raw UTF-8 bytes into `tab_id` via `hc connect` framed `terminal.attach` DATA without pressing Enter."""
        meta = self._get_meta(tab_id)
        cols = int(meta.get("cols") or 100)
        rows = int(meta.get("rows") or 30)
        try:
            proc = subprocess.Popen([self.binary, "connect"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise TabsError("no_backend", "hc (herdr-core) is not installed")
        except OSError as e:
            raise TabsError("no_backend", "cannot run hc: %s" % (e.strerror or e))

        def write_frame(ch, kind, data=b""):
            proc.stdin.write(struct.pack("<IBI", ch, kind, len(data)) + data)
            proc.stdin.flush()

        def read_exact(n):
            buf = bytearray()
            while len(buf) < n:
                chunk = proc.stdout.read(n - len(buf))
                if not chunk:
                    raise EOFError("hc connect closed stream early")
                buf.extend(chunk)
            return bytes(buf)

        deadline = time.monotonic() + self.timeout
        try:
            hello = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "hello", "params": {"framed": True, "generation": 1}}) + "\n"
            proc.stdin.write(hello.encode("utf-8"))
            proc.stdin.flush()
            hello_line = proc.stdout.readline()
            if not hello_line:
                err = proc.stderr.read().decode("utf-8", "replace").strip()
                self._raise_hc_error("not_running", err or "hc connect exited during handshake")
            hello_msg = json.loads(hello_line.decode("utf-8", "replace"))
            if hello_msg.get("error"):
                e = hello_msg["error"]
                self._raise_hc_error(str(e.get("data", {}).get("kind", "")), str(e.get("message", "")))

            attach = json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "terminal.attach",
                "params": {"terminal": tab_id, "cols": cols, "rows": rows, "history": 0, "resumed": True},
            }).encode("utf-8")
            write_frame(0, 0, attach)

            channel = None
            while channel is None:
                if time.monotonic() > deadline:
                    raise TabsError("timeout", "hc connect timed out attaching to %s" % tab_id)
                hdr = read_exact(9)
                fch, fkind, flen = struct.unpack("<IBI", hdr)
                fpay = read_exact(flen)
                if fch == 0 and fkind == 0:
                    msg = json.loads(fpay.decode("utf-8", "replace"))
                    if msg.get("id") == 2:
                        if msg.get("error"):
                            e = msg["error"]
                            kind = str((e.get("data") or {}).get("kind", "")) if isinstance(e.get("data"), dict) else ""
                            self._raise_hc_error(kind, str(e.get("message", "")))
                        channel = int(msg["result"]["channel"])

            for i in range(0, len(payload_bytes), CHUNK):
                write_frame(channel, 0, payload_bytes[i:i + CHUNK])
            time.sleep(0.02)
            write_frame(channel, 2, b"")
            proc.stdin.close()
            proc.wait(timeout=max(0.5, deadline - time.monotonic()))
        except TabsError:
            proc.kill()
            proc.wait()
            raise
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise TabsError("timeout", "hc connect did not finish in %g s" % self.timeout)
        except (EOFError, OSError, ValueError, KeyError) as e:
            proc.kill()
            err = proc.stderr.read().decode("utf-8", "replace").strip() if proc.stderr else ""
            proc.wait()
            self._raise_hc_error("", err or str(e))
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def send_text(self, tab, text):
        if not text:
            return
        self._framed_write(tab.id, text.encode("utf-8"))

    def send_key(self, tab, key):
        self.hc("keys", "--json", tab.id, _hc_key_name(key))

    def live_tab_ids(self):
        return {t.id for t in self.list_tabs_raw()}

    def tab_status(self, tab):
        meta = self._meta.get(tab.id)
        if not isinstance(meta, dict):
            return None
        st = meta.get("status")
        if not isinstance(st, dict) or not st.get("state"):
            return None
        out = {"state": str(st["state"])}
        if isinstance(st.get("progress"), (int, float)):
            out["progress"] = int(st["progress"])
        if st.get("msg"):
            out["msg"] = str(st["msg"])[:160]
        if st.get("app"):
            out["app"] = str(st["app"])[:32]
        return out

    def tab_labels(self, tab):
        meta = self._meta.get(tab.id)
        if isinstance(meta, dict) and isinstance(meta.get("labels"), dict):
            return meta["labels"]
        full = self._get_meta(tab.id, fresh=True)
        lbls = full.get("labels") if isinstance(full, dict) else None
        return lbls if isinstance(lbls, dict) else {}

    def rename_tab(self, tab, title, source="user"):
        self.set_labels(tab, {"swarmbox.title": title, "swarmbox.title_source": source})

    def set_labels(self, tab, labels):
        pairs = ["%s=%s" % (k, "" if v is None else v) for k, v in sorted((labels or {}).items()) if k]
        if not pairs:
            return
        self.hc("label", tab.id, *pairs)
        meta = self._meta.get(tab.id)
        if isinstance(meta, dict):
            lbls = dict(meta.get("labels") or {})
            for k, v in (labels or {}).items():
                if not k:
                    continue
                if v is None or v == "":
                    lbls.pop(k, None)
                else:
                    lbls[k] = str(v)
            meta["labels"] = lbls

    def _write_active(self, tab_id):
        try:
            os.makedirs(self.run_dir, mode=0o700, exist_ok=True)
            marker = os.path.join(self.run_dir, "herdr-active-tab")
            tmp = marker + ".tmp.%d" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(str(tab_id))
            os.replace(tmp, marker)
        except OSError:
            pass

    def open_tab(self, name=None, cwd=None, agent=None, labels=None):
        # --keep like every other terminal the box opens (mux/herdr.sh): an agent that exits leaves a shell in its place
        args = ["run", "--bg", "--keep", "--no-parent", "--json"]
        if name:
            args += ["--name", name]
        if cwd:
            args += ["--cwd", cwd]
        if isinstance(labels, dict):
            for k, v in sorted(labels.items()):
                if k and v is not None and str(v) != "":
                    args += ["--label", "%s=%s" % (k, v)]
        cmd = ALLOWED_OPEN_AGENTS.get(agent or "shell")
        if cmd:
            args += ["--", "bash", "-lc", "exec " + " ".join(cmd)]
        else:
            args += ["--", "bash", "-l"]
        res = self.hc(*args)
        addr = ""
        if isinstance(res, dict):
            addr = str(res.get("address") or (res.get("terminal") or {}).get("address") or "")
        if addr:
            self._write_active(addr)
        return addr

    def focus_tab(self, tab):
        self._write_active(tab.id)

    def close_tab(self, tab):
        # as the web studio closes a tab (DELETE /api/tabs/:id): end the program, then remove the finished terminal so it leaves no row behind
        self.hc("kill", tab.id)
        self.hc("rm", tab.id, check=False)

    def tab_state(self, tab):
        """Return native OSC 7501 `(True, dialog|busy|idle)` when the program reported status, else None for heuristic fallback."""
        meta = self._get_meta(tab.id, fresh=True)
        if not meta or not meta.get("reported"):
            return None
        st = meta.get("status")
        if not isinstance(st, dict):
            return None
        state = st.get("state")
        if state == "blocked":
            return True, "dialog"
        if state == "working":
            return True, "busy"
        if state in ("idle", "done", "error"):
            return True, "idle"
        return None


BACKENDS = {"herdr": HerdrBackend}


def make_backend(name=None, binary=None, timeout=TIMEOUT, run_dir=None):
    """the backend: a TabsBackend given as it is, else the class of BACKENDS named by `name` or SB_TABS_BACKEND (default herdr)"""
    if isinstance(name, TabsBackend):
        return name
    chosen = name or os.environ.get("SB_TABS_BACKEND") or "herdr"
    cls = BACKENDS.get(chosen)
    if cls is None:
        raise TabsError("no_backend", "unknown tabs backend %r (known: %s)" % (chosen, ", ".join(sorted(BACKENDS))))
    return cls(binary=binary, timeout=timeout, run_dir=run_dir)


class Tabs:
    """Mux-agnostic tab facade (redaction, markers, key parsing, locking, agent rules) over a TabsBackend (default: HerdrBackend)."""

    def __init__(self, binary=None, run_dir=None, pause=PAUSE, timeout=TIMEOUT, verify_timeout=VERIFY_TIMEOUT, lock_timeout=LOCK_TIMEOUT,
                 backend=None):
        self.run_dir = run_dir or os.environ.get("SB_RUN_DIR") or "/tmp/swarmbox"
        self.backend = make_backend(backend, binary=binary, timeout=timeout, run_dir=self.run_dir)
        self.binary = getattr(self.backend, "binary", binary)
        self.pause, self.timeout, self.verify_timeout, self.lock_timeout = pause, timeout, verify_timeout, lock_timeout

    # ---- tabs
    def _windows(self):
        return self.backend.list_tabs_raw()

    def _shown(self, ids):
        return self.backend.active_tab_id(ids)

    def tabs(self):
        tabs = self._windows()
        shown = self._shown([t.id for t in tabs]) if tabs else None
        return [t._replace(active=t.id == shown) for t in tabs]

    def list_tabs(self):
        out = []
        for t in self.tabs():
            row = {"tab": t.id, "label": t.label, "index": t.index, "name": t.name, "dir": t.cwd, "cmd": t.command, "pane": t.pane,
                   "panes": t.panes, "active": t.active}
            st = self.backend.tab_status(t)
            if st:
                row["status"] = st
            lbls = self.backend.tab_labels(t) or {}
            if lbls.get("swarmbox.title"):
                row["title"] = str(lbls["swarmbox.title"])[:60]
            if lbls.get("swarmbox.title_source") in ("user", "auto"):
                row["title_source"] = lbls["swarmbox.title_source"]
            if lbls.get("swarmbox.pin_id"):
                row["pin_id"] = str(lbls["swarmbox.pin_id"])
                row["pinned"] = True
            if lbls.get("swarmbox.worktree"):
                row["worktree"] = {
                    "path": str(lbls["swarmbox.worktree"]),
                    "branch": str(lbls.get("swarmbox.branch") or ""),
                    "base": str(lbls.get("swarmbox.base") or ""),
                    "repo": str(lbls.get("swarmbox.repo") or ""),
                }
            out.append(row)
        return out

    @staticmethod
    def _sibling_bin(name, script_name):
        here = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(here, script_name)
        if os.path.isfile(cand):
            return [sys.executable, cand]
        return [name]

    def rename_tab(self, tab, title, source="user"):
        src = str(source or "user").strip().lower()
        if src not in ("user", "auto"):
            raise usage_error("--source must be user or auto")
        clean = re.sub(r"\s+", " ", "".join(c if c.isprintable() else " " for c in str(title or ""))).strip()[:60]
        if not clean:
            raise TabsError("bad_body", "title cannot be empty")
        t = self.resolve(tab)
        lbls = self.backend.tab_labels(t) or {}
        old_title = str(lbls.get("swarmbox.title") or t.name)
        self.backend.rename_tab(t, clean, source=src)
        pin_id = lbls.get("swarmbox.pin_id")
        if pin_id:
            try:
                cmd = self._sibling_bin("swarmbox-pins", "swarmbox-pins.py") + [
                    "update", str(pin_id), "--title", clean, "--title-source", src,
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return {"ok": True, "tab": t.id, "title": clean, "old_title": old_title, "source": src}

    def label_tab(self, tab, labels):
        if not isinstance(labels, dict) or not labels:
            raise usage_error("at least one KEY=VALUE label is required")
        clean = {}
        for k, v in labels.items():
            key = str(k or "").strip()
            if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", key):
                raise usage_error("invalid label key %r" % key)
            clean[key] = "" if v is None else str(v)[:512]
        t = self.resolve(tab)
        self.backend.set_labels(t, clean)
        return {"ok": True, "tab": t.id, "labels": clean}

    def open_tab(self, name=None, cwd=None, agent=None, worktree=False, title=None):
        ag = (agent or "shell").strip().lower()
        if ag not in ALLOWED_OPEN_AGENTS:
            raise usage_error("unknown agent %r (known: %s)" % (ag, ", ".join(sorted(ALLOWED_OPEN_AGENTS))))
        clean_name = None
        if name:
            # the rule of `hc run --name` (1-32 of a-z 0-9 - _)
            clean_name = re.sub(r"[^a-z0-9_-]", "-", str(name).strip().lower())[:32].strip("-") or None
        clean_cwd = None
        if cwd:
            expanded = os.path.expanduser(str(cwd).strip())
            if not os.path.isdir(expanded):
                raise TabsError("bad_body", "directory does not exist: %s" % cwd)
            clean_cwd = expanded
        labels = {}
        wt_info = None
        if worktree:
            src_dir = clean_cwd or os.getcwd()
            cmd = self._sibling_bin("swarmbox-worktree", "swarmbox-worktree.py") + ["create", src_dir]
            try:
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20.0)
                data = json.loads(p.stdout) if p.stdout.strip() else {}
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                raise TabsError("backend_error", "worktree creation failed: %s" % exc)
            if p.returncode != 0 or not data.get("ok"):
                raise TabsError(str(data.get("err") or "backend_error"), str(data.get("msg") or "worktree creation failed"))
            clean_cwd = data["path"]
            wt_info = {
                "path": data["path"],
                "branch": data["branch"],
                "base": data["base"],
                "repo": data["repo_root"],
            }
            labels.update({
                "swarmbox.worktree": data["path"],
                "swarmbox.branch": data["branch"],
                "swarmbox.base": data["base"],
                "swarmbox.repo": data["repo_root"],
            })
        if title:
            clean_t = re.sub(r"\s+", " ", "".join(c if c.isprintable() else " " for c in str(title))).strip()[:60]
            if clean_t:
                labels["swarmbox.title"] = clean_t
                labels["swarmbox.title_source"] = "user"
        if labels:
            labels["swarmbox.agent"] = ag
            tid = self.backend.open_tab(name=clean_name, cwd=clean_cwd, agent=ag, labels=labels)
        else:
            tid = self.backend.open_tab(name=clean_name, cwd=clean_cwd, agent=ag)
        res = {"ok": True, "tab": tid, "name": clean_name or ag, "agent": ag}
        if wt_info:
            res["worktree"] = wt_info
        if labels.get("swarmbox.title"):
            res["title"] = labels["swarmbox.title"]
        return res

    def focus_tab(self, tab):
        t = self.resolve(tab)
        self.backend.focus_tab(t)
        return {"ok": True, "tab": t.id, "label": t.label}

    def close_tab(self, tab):
        t = self.resolve(tab)
        self.backend.close_tab(t)
        return {"ok": True, "tab": t.id, "label": t.label}

    def active(self):
        """the dict of list_tabs() of the active tab; no_such_tab when the box has no tab"""
        for t in self.list_tabs():
            if t["active"]:
                return t
        raise TabsError("no_such_tab", "the box has no tab")

    def resolve(self, tab):
        """Tab for "t3" (the address), "1:name" (the label), "1" (the index) or "name". no_such_tab, or ambiguous_tab with the candidates."""
        tabs = self._windows()
        s = str(tab)
        hit = [t for t in tabs if t.id == s] or [t for t in tabs if t.label == s] or [t for t in tabs if s.isdigit() and t.index == int(s)] \
            or [t for t in tabs if t.name == s]
        if not hit:
            low = s.strip().lower()
            hit = [t for t in tabs if str((self.backend.tab_labels(t) or {}).get("swarmbox.title") or "").strip().lower() == low]
        if not hit:
            raise TabsError("no_such_tab", "no tab %s; the tabs are: %s" % (s, ", ".join("%s (%s)" % (t.label, t.id) for t in tabs) or "none"))
        if len(hit) > 1:
            raise TabsError("ambiguous_tab", "the name %s is used by %s: use the id" % (s, ", ".join("%s (%s)" % (t.label, t.id) for t in hit)))
        return hit[0]

    # ---- the screen
    def _plain_rows(self, tab):
        return self.backend.capture_plain_rows(tab)

    def screen(self, tab, lines):
        t = self.resolve(tab)
        cap = self.backend.capture_screen(t, lines)
        text, styles = _parse(cap.raw)
        n = cap.lines
        if n:       # the capture may hold more than N lines (history and the screen): keep the last N
            rows = text.split("\n")
            if len(rows) > int(n):
                cut = len("\n".join(rows[:-int(n)])) + 1
                text, styles = text[cut:], styles[cut:]
        # the secrets are found in the plain text, whole lines, whatever the colours: the markers are written afterwards, and the cut of a long
        # line comes last, so no secret is cut in half
        text, styles = redact_tracked(text, styles)
        text = _render(text, styles, MAX_LINE)
        return {"tab": t.id, "pane": t.pane, "text": text, "cursor": list(cap.cursor), "alternate": bool(cap.alternate),
                "in_mode": bool(cap.in_mode), "mode": cap.mode, "size": list(cap.size), "lines": n}

    # ---- typing
    @contextlib.contextmanager
    def _lock(self, wid):
        """flock on <run folder>/tabs/tab-<address>.lock: one send at a time per tab, across processes; waits up to lock_timeout"""
        d = os.path.join(self.run_dir, "tabs")
        path = os.path.join(d, "tab-%s.lock" % re.sub(r"[^0-9A-Za-z]", "", wid))
        end = time.monotonic() + self.lock_timeout
        fd = None
        try:
            while fd is None:
                try:
                    os.makedirs(d, mode=0o700, exist_ok=True)
                    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
                except OSError as e:
                    raise TabsError("lock_error", "cannot create the lock %s: %s" % (path, e.strerror or e))
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= end:
                            raise TabsError("timeout", "an earlier send to the tab %s is still typing (waited %g s); nothing was typed" % (wid, self.lock_timeout))
                        time.sleep(0.02)
                try:
                    same = os.fstat(fd).st_ino == os.stat(path).st_ino
                except OSError:
                    same = False
                if not same:        # the sweep (_sweep_locks) deleted the file while we waited: what we hold is a lock nobody else sees; take the new file
                    os.close(fd)
                    fd = None
            yield
        finally:
            if fd is not None:
                os.close(fd)        # closing drops the lock

    def _sweep_locks(self):
        """Delete the lock files of tabs that are gone. An address is never reused, so the files of a box that opens and closes tabs for weeks would only
        pile up (empty files, in the run folder, which is gone at every start): past LOCK_KEEP files, those of tabs that no longer exist and that nobody
        holds are removed. Never fails."""
        d = os.path.join(self.run_dir, "tabs")
        try:
            names = [n for n in os.listdir(d) if re.fullmatch(r"tab-[0-9A-Za-z]+\.lock", n)]
            if len(names) <= LOCK_KEEP:
                return
            live = {"tab-%s.lock" % re.sub(r"[^0-9A-Za-z]", "", w) for w in self.backend.live_tab_ids()}
        except (OSError, TabsError):
            return
        for n in names:
            if n in live:
                continue
            try:
                fd = os.open(os.path.join(d, n), os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)      # held by a send that is still typing: leave it
                os.unlink(os.path.join(d, n))                        # unlinked while we hold it: a waiter sees that in _lock and opens the new file
            except OSError:
                pass
            finally:
                os.close(fd)

    def _body(self, body):
        """(steps, submit, queue, slash) of a body, or bad_body."""
        ok = isinstance(body, dict) and 1 <= len(body) <= 3 and ("run" in body) != ("input" in body)
        if ok:
            ok = all(k in ("run", "input", "queue", "slash") for k in body) and all(isinstance(body[k], bool) for k in ("queue", "slash") if k in body)
        key = "run" if isinstance(body, dict) and "run" in body else "input"
        if not ok or not isinstance(body.get(key), str) or not body[key]:
            raise TabsError("bad_body", 'a send is --run TEXT or --input TEXT (a non-empty text), with the optional --queue and --slash')
        text = body[key]
        if "\x00" in text:
            raise TabsError("bad_body", "the text holds a NUL character")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise TabsError("bad_body", "the text is not valid Unicode (a lone surrogate)")
        steps = [("text", text), ("key", "Enter")] if key == "run" else parse_keys(text)
        if not steps:
            raise TabsError("bad_body", "nothing to type")
        if len(steps) > MAX_STEPS:
            raise TabsError("bad_body", "%d steps (texts and keys) in one message, at most %d: send it in several messages" % (len(steps), MAX_STEPS))
        has_text = any(k == "text" for k, _ in steps)
        return steps, has_text and any(k == "key" and v == "Enter" for k, v in steps), bool(body.get("queue")), bool(body.get("slash"))

    def send(self, tab, run=None, input=None, queue=False, slash=False):
        """type into a tab: run=TEXT (TEXT and Enter) or input=TEXT (braces keys); returns {"ok", "tab", "pane", "submitted"}"""
        body = {k: v for k, v in (("run", run), ("input", input)) if v is not None}
        if queue:
            body["queue"] = True
        if slash:
            body["slash"] = True
        return self.send_body(tab, body)

    def _agent_state_for(self, tab):
        native = self.backend.tab_state(tab)
        if native is not None:
            return native
        return agent_state(self._plain_rows(tab), tab.command)

    def send_body(self, tab, body):
        """send() with its arguments as a dict: {"run": text} or {"input": text}, with the optional booleans "queue" and "slash"; bad_body
        for anything else"""
        steps, submit, queue, slash = self._body(body)
        t = self.resolve(tab)
        self._sweep_locks()
        with self._lock(t.id):
            self.backend.prepare_send(t)
            agent = False
            submitted = self._submitted(steps)
            if submit:
                agent, state = self._agent_state_for(t)
                if agent:
                    if state == "dialog":
                        raise TabsError("dialog_open", "a dialog is open in the tab; answer it with input (a key), nothing was typed")
                    if state == "busy" and not queue:
                        raise TabsError("busy_tab", 'the agent in the tab is busy; nothing was typed (use --queue to queue the message, or interrupt it with --input {Esc})')
                    if len(submitted) > 1 and not queue:
                        # the state above is read once: after the first Enter the agent works, so the later texts would be typed into a busy agent
                        raise TabsError("busy_tab", 'the message submits %d texts to an agent, and the agent is busy after the first; nothing was typed (use --queue, or send one message per text)' % len(submitted))
                    if not slash and any(steps[i][1][:1] in ("/", "!") for i in submitted):
                        raise TabsError("slash_refused", 'text that starts with "/" or "!" is a command for the agent, not a prompt; nothing was typed (--slash allows it)')
            last_enter = max(i for i, (k, v) in enumerate(steps) if k == "key" and v == "Enter") if submit else -1
            for i, (kind, val) in enumerate(steps):
                if i and self.pause:
                    time.sleep(self.pause)
                if kind == "text":
                    self.backend.send_text(t, val)
                else:
                    self.backend.send_key(t, val)
                if agent and i == last_enter:
                    self._verify(t, steps, i)
        return {"ok": True, "tab": t.id, "pane": t.pane, "submitted": submit}

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
            native = self.backend.tab_state(t)
            if native is not None and native[1] not in ("idle", "unknown"):
                return False
            rows = self._plain_rows(t)
            _, state = native if native is not None else agent_state(rows, t.command)
            box = input_box(rows, lenient=True)
            return state in ("idle", "unknown") and box is not None and (tail in box or "[Pasted text" in box)
        for attempt in (1, 2):
            end = time.monotonic() + self.verify_timeout
            while True:
                if not left_in_box():
                    return
                if time.monotonic() >= end:
                    break
                time.sleep(0.1)
            if attempt == 1:
                self.backend.send_key(t, "Enter")
        raise TabsError("not_submitted", "the text was typed but did not leave the input box")


# ---------------------------------------------------------------------------------------------------------------- the command line

def usage_error(msg):
    return TabsError("usage", msg + " (swarmbox-tabs --help)")


def read_stdin():
    data = sys.stdin.buffer.read(MAX_STDIN + 1)
    if len(data) > MAX_STDIN:
        raise TabsError("bad_body", "more than %d bytes on stdin" % MAX_STDIN)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise TabsError("bad_body", "the text on stdin is not valid UTF-8")
    return text[:-1] if text.endswith("\n") else text


def parse_args(a, takes, flags):
    """(opts, positional) of a: takes are the options with a value, flags the ones without; usage error for anything else"""
    opts, rest, i = {}, [], 0
    while i < len(a):
        x = a[i]
        if x in takes:
            if i + 1 >= len(a):
                raise usage_error("%s takes a value" % x)
            if x in opts:
                raise usage_error("%s given twice" % x)
            opts[x] = a[i + 1]
            i += 1
        elif x in flags:
            opts[x] = True
        elif x.startswith("-") and x != "-":
            raise usage_error("unknown option %s" % x)
        else:
            rest.append(x)
        i += 1
    return opts, rest


def run(argv, tabs=None):
    """the command: a JSON-able result, or TabsError"""
    if not argv:
        raise usage_error("a command is needed: list, active, screen, send, open, focus, close")
    cmd, a = argv[0], argv[1:]
    tabs = tabs or Tabs()
    if cmd in ("list", "active"):
        opts, rest = parse_args(a, (), ())
        if rest:
            raise usage_error("%s takes no argument" % cmd)
        return tabs.list_tabs() if cmd == "list" else tabs.active()
    if cmd == "screen":
        opts, rest = parse_args(a, ("--lines",), ())
        if len(rest) != 1:
            raise usage_error("usage: screen TAB [--lines N]")
        lines = None
        if "--lines" in opts:
            try:
                lines = int(opts["--lines"])
            except ValueError:
                lines = 0
            if not 0 < lines <= 100000:
                raise usage_error("--lines takes a number from 1 to 100000")
        return tabs.screen(rest[0], lines)
    if cmd == "send":
        opts, rest = parse_args(a, ("--run", "--input"), ("--queue", "--slash"))
        if len(rest) != 1 or ("--run" in opts) == ("--input" in opts):
            raise usage_error("usage: send TAB (--run TEXT | --input TEXT) [--queue] [--slash]")
        key = "--run" if "--run" in opts else "--input"
        text = read_stdin() if opts[key] == "-" else opts[key]
        return tabs.send(rest[0], run=text if key == "--run" else None, input=text if key == "--input" else None,
                         queue="--queue" in opts, slash="--slash" in opts)
    if cmd == "open":
        opts, rest = parse_args(a, ("--name", "--cwd", "--agent", "--title"), ("--worktree",))
        if rest:
            raise usage_error("usage: open [--name NAME] [--cwd DIR] [--agent AGENT] [--title TITLE] [--worktree]")
        return tabs.open_tab(name=opts.get("--name"), cwd=opts.get("--cwd"), agent=opts.get("--agent"),
                             worktree="--worktree" in opts, title=opts.get("--title"))
    if cmd == "rename":
        opts, rest = parse_args(a, ("--source",), ())
        if len(rest) != 2:
            raise usage_error("usage: rename TAB TITLE [--source user|auto]")
        return tabs.rename_tab(rest[0], rest[1], source=opts.get("--source", "user"))
    if cmd == "label":
        _, rest = parse_args(a, (), ())
        if len(rest) < 2:
            raise usage_error("usage: label TAB KEY=VALUE [KEY=VALUE ...]")
        pairs = {}
        for item in rest[1:]:
            if "=" not in item:
                raise usage_error("label must be KEY=VALUE, got %r" % item)
            k, v = item.split("=", 1)
            pairs[k] = v
        return tabs.label_tab(rest[0], pairs)
    if cmd == "focus":
        opts, rest = parse_args(a, (), ())
        if len(rest) != 1:
            raise usage_error("usage: focus TAB")
        return tabs.focus_tab(rest[0])
    if cmd == "close":
        opts, rest = parse_args(a, (), ())
        if len(rest) != 1:
            raise usage_error("usage: close TAB")
        return tabs.close_tab(rest[0])
    raise usage_error("unknown command %s" % cmd)


def main(argv):
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(__doc__)
        return 0
    try:
        out, rc = run(argv), 0
    except TabsError as e:
        out, rc = {"err": e.code, "msg": e.message}, EXIT.get(e.code, 1)
    try:
        print(json.dumps(out, ensure_ascii=False))
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
