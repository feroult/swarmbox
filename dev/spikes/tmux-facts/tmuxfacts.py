"""tmuxfacts: what the bus can rely on from tmux. Standard library only. See docs/spikes/tmux-facts.md.

list_tabs(session)          -> [Tab]   one per window of the session, hidden (panel) panes left out, `active` = the window of the client
                                       that was active last
active_tab(session)         -> Tab | None
resolve(tab, session)       -> Tab     "@3", "3" (index), "name", "%7" (a pane id) or "@3.%7"
screen(tab, lines, markers) -> dict    text (secrets removed by the caller's filter), cursor, mode flags
send(tab, text=None, keys=None)        typed text with {Esc}-style keys; returns the steps it ran
to_marked(raw)              -> str     the converter from `capture-pane -e` to the text-with-markers format

The tmux to talk to comes from TMUXFACTS_TMUX (a command prefix, e.g. "tmux -L spike"); default "tmux". TMUX is removed from the
environment of every call, so the default socket is never reached by accident through a nested shell.
"""
import os
import re
import shlex
import subprocess
import time
from collections import namedtuple

SEP = "@@sb@@"   # not a tab: tmux 3.6+ prints control characters of a list as `_` without a terminal (see voice tmuxrun.py)
HIDDEN_OPTIONS = ("@swarmbox_sysop_panel", "@swarmbox_voice_panel")   # a pane with any of these set is never listed or targeted
PAUSE = 0.15

Tab = namedtuple("Tab", "id index name cwd command pane panes active label")


class TmuxError(RuntimeError):
    pass


class AmbiguousTab(TmuxError):
    pass


def tmux(*args, check=True):
    argv = shlex.split(os.environ.get("TMUXFACTS_TMUX", "")) or ["tmux"]
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    p = subprocess.run(argv + [str(a) for a in args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=10)
    out = p.stdout.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise TmuxError(p.stderr.decode("utf-8", "replace").strip() or "tmux %s failed" % args[0])
    return out


# ------------------------------------------------------------------------------------------------------------------ the tabs
def _clients():
    """Real clients (not control mode): (activity, session, window_id). In a client's own session window_id is the window THAT CLIENT shows."""
    fmt = SEP.join(["#{client_activity}", "#{client_session}", "#{window_id}", "#{client_control_mode}", "#{client_flags}"])
    rows = []
    for line in tmux("list-clients", "-F", fmt, check=False).splitlines():
        p = line.split(SEP)
        if len(p) == 5 and p[3] != "1":
            rows.append((int(p[0] or 0), p[1], p[2]))
    return rows


def shown_window(session="main"):
    """The window of the client that was active last (any session), else the current window of `session`. Rule: highest client_activity."""
    cl = _clients()
    if cl:
        return max(cl, key=lambda c: c[0])[2]
    return tmux("display-message", "-p", "-t", "=%s:" % session, "#{window_id}", check=False).strip() or None


def list_tabs(session="main"):
    fmt = SEP.join(["#{window_id}", "#{window_index}", "#{window_name}", "#{pane_id}", "#{pane_active}", "#{pane_current_path}",
                    "#{pane_current_command}", "#{pane_last}"] + ["#{%s}" % o for o in HIDDEN_OPTIONS])
    wins, order = {}, []
    for line in tmux("list-panes", "-s", "-t", "=" + session, "-F", fmt).splitlines():
        p = line.split(SEP)
        if len(p) != 8 + len(HIDDEN_OPTIONS) or any(p[8:]):
            continue
        wid = p[0]
        if wid not in wins:
            wins[wid] = {"id": wid, "index": int(p[1]), "name": p[2], "rows": []}
            order.append(wid)
        wins[wid]["rows"].append(p)
    active = shown_window(session)
    home = os.path.expanduser("~")
    tabs = []
    for wid in order:
        w = wins[wid]
        rows = w["rows"]
        # the active pane; when the focus is in a panel (already out of `rows`) the pane that had it before (pane_last), else the first
        row = next((r for r in rows if r[4] == "1"), None) or next((r for r in rows if r[7] == "1"), rows[0])
        cwd = row[5]
        if home != "/" and (cwd == home or cwd.startswith(home + "/")):
            cwd = "~" + cwd[len(home):]
        tabs.append(Tab(wid, w["index"], w["name"], cwd, row[6], row[3], [r[3] for r in rows], wid == active, "%d:%s" % (w["index"], w["name"])))
    return tabs


def active_tab(session="main"):
    return next((t for t in list_tabs(session) if t.active), None)


def resolve(tab, session="main"):
    """tab: Tab, "@3", "@3.%7", "%7", "3" (index in the session) or a name; a name used twice raises AmbiguousTab (use the index or the @id)."""
    if isinstance(tab, Tab):
        return tab
    tabs = list_tabs(session)
    s = str(tab).strip()
    pane = None
    if "." in s and s.startswith("@"):
        s, pane = s.split(".", 1)
    elif s.startswith("%"):
        for t in tabs:
            if s in t.panes:
                return t._replace(pane=s)
        raise TmuxError("no tab has the pane %s" % s)
    hit = [t for t in tabs if t.id == s] or [t for t in tabs if s.isdigit() and t.index == int(s)] or [t for t in tabs if t.name == s]
    if not hit:
        raise TmuxError("no tab %r" % tab)
    if len(hit) > 1:
        raise AmbiguousTab("the name %r is used by %s: use the index or the id" % (tab, ", ".join("%s (%s)" % (t.label, t.id) for t in hit)))
    t = hit[0]
    if pane:
        if pane not in t.panes:
            raise TmuxError("%s is not a pane of %s" % (pane, t.id))
        t = t._replace(pane=pane)
    return t


# ----------------------------------------------------------------------------------------------------------------- the screen
_ESC = re.compile(r"\x1b(?:\[([0-9;:?]*)([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B]|[@-Z\\-_=>])")
_RED = {1, 9, 124, 160, 196, 197, 203, 167, 131, 124, 88, 52, 160}   # 256-colour reds that terminals use for errors


def _sgr(params, st):
    """Apply one SGR sequence (list of ints) to st = dict(rev, bold, dim, fg, bg)."""
    i = 0
    if not params:
        params = [0]
    while i < len(params):
        n = params[i]
        if n == 0:
            st.update(rev=False, bold=False, dim=False, fg=None, bg=None)
        elif n == 1: st["bold"] = True
        elif n == 2: st["dim"] = True
        elif n == 22: st["bold"] = st["dim"] = False
        elif n == 7: st["rev"] = True
        elif n == 27: st["rev"] = False
        elif 30 <= n <= 37: st["fg"] = n - 30
        elif 90 <= n <= 97: st["fg"] = n - 90 + 8
        elif n == 39: st["fg"] = None
        elif 40 <= n <= 47: st["bg"] = n - 40
        elif 100 <= n <= 107: st["bg"] = n - 100 + 8
        elif n == 49: st["bg"] = None
        elif n in (38, 48):
            key = "fg" if n == 38 else "bg"
            if i + 1 < len(params) and params[i + 1] == 5 and i + 2 < len(params):
                st[key] = params[i + 2]; i += 2
            elif i + 1 < len(params) and params[i + 1] == 2 and i + 4 < len(params):
                st[key] = ("rgb",) + tuple(params[i + 2:i + 5]); i += 4
        i += 1


def _is_red(fg):
    if fg in (1, 9):
        return True
    if isinstance(fg, tuple):
        r, g, b = fg[1:]
        return r > 150 and g < 90 and b < 90
    return fg in _RED if isinstance(fg, int) else False


def _tags(st, bold, red, bg):
    """The marker names of a style: [sel] reverse video (SGR 7), [bg] a background colour (fzf and many menus mark the current line so), [err]
    red text, [b] bold. [bg] is dropped at render time when the span has no letter or digit (Claude Code's logo is made of coloured blocks)."""
    t = []
    if st["rev"]:
        t.append("sel")
    elif bg and st["bg"] is not None:
        t.append("bg")
    if red and _is_red(st["fg"]):
        t.append("err")
    if bold and st["bold"] and not t:
        t.append("b")
    return t


def to_marked(raw, bold=False, red=True, bg=True):
    """capture-pane -e output -> text. Spans are written [sel]text[/sel] (reverse video), [bg]..[/bg] (background colour, with letters or
    digits in it), [err]..[/err] (red text) and [b]..[/b] (bold, off by default: full-screen programs use bold everywhere). A span never
    crosses a line; trailing spaces of a span, and spans of only spaces, are dropped; trailing spaces of a line are cut. Other escape
    sequences are removed."""
    out_lines = []
    st = dict(rev=False, bold=False, dim=False, fg=None, bg=None)
    for line in raw.split("\n"):
        pieces, pos = [], 0   # pieces: [tags, text]; neighbours with the same tags are merged
        def add(text):
            tags = tuple(_tags(st, bold, red, bg))
            if pieces and pieces[-1][0] == tags:
                pieces[-1][1] += text
            else:
                pieces.append([tags, text])
        for m in _ESC.finditer(line):
            if m.start() > pos:
                add(line[pos:m.start()])
            pos = m.end()
            if m.group(2) == "m":
                try:
                    _sgr([int(x) if x else 0 for x in re.split(r"[;:]", m.group(1) or "")], st)
                except ValueError:
                    pass
        if pos < len(line):
            add(line[pos:])
        res = []
        for tags, text in pieces:
            if "bg" in tags and not any(c.isalnum() for c in text):
                tags = tuple(t for t in tags if t != "bg")
            if tags and text.strip():
                lead = text[:len(text) - len(text.lstrip())]
                tail = text[len(text.rstrip()):]
                res.append(lead + "".join("[%s]" % t for t in tags) + text.strip() + "".join("[/%s]" % t for t in reversed(tags)) + tail)
            else:
                res.append(text)
        out_lines.append("".join(res).rstrip())
    return "\n".join(out_lines).rstrip("\n")


def clip_lines(text, max_line=1000):
    """Cut every line to max_line characters. The secrets filter (voice context.redact) is quadratic on a long run of one character such as '-'
    (100000 dashes took 110 s), and a joined (-J) minified file is such a line, so the cut comes BEFORE the filter."""
    if max_line and any(len(l) > max_line for l in text.split("\n")):
        text = "\n".join(l if len(l) <= max_line else l[:max_line] + " [... %d more characters]" % (len(l) - max_line) for l in text.split("\n"))
    return text


def screen(tab, lines=None, markers=True, session="main", redact=None, max_line=1000):
    """The text of a tab's pane. lines=None: the visible screen; lines=N: the last N lines including scrollback (-S -N, from the bottom of
    the screen up). markers=False: plain `-p -J`. redact: a function applied to the text (the secrets filter), before the markers matter."""
    t = resolve(tab, session)
    fmt = SEP.join(["#{cursor_x}", "#{cursor_y}", "#{pane_in_mode}", "#{alternate_on}", "#{pane_width}", "#{pane_height}", "#{history_size}",
                    "#{cursor_flag}", "#{pane_mode}"])
    meta = tmux("display-message", "-p", "-t", t.pane, fmt).rstrip("\n").split(SEP)
    args = ["capture-pane", "-p", "-J", "-t", t.pane]
    if markers:
        args.insert(2, "-e")
    if lines:
        args += ["-S", "-%d" % int(lines)]
    raw = tmux(*args)
    text = to_marked(raw) if markers else "\n".join(l.rstrip() for l in raw.split("\n")).rstrip("\n")
    h = int(meta[5])
    if lines:   # -S -N counts N lines ABOVE the top of the screen, so the capture has N + height lines: keep the last N
        text = "\n".join(text.split("\n")[-int(lines):])
    text = clip_lines(text, max_line)
    if redact:
        text = redact(text)
    return {"tab": t.id, "pane": t.pane, "text": text, "cursor": [int(meta[0]), int(meta[1])], "in_mode": meta[2] == "1", "mode": meta[8],
            "alternate": meta[3] == "1", "size": [int(meta[4]), h]}


# ------------------------------------------------------------------------------------------------------------------- send-keys
KEYS = {"Esc": "Escape", "Enter": "Enter", "Tab": "Tab", "BTab": "BTab", "Space": "Space", "BSpace": "BSpace", "Up": "Up", "Down": "Down",
        "Left": "Left", "Right": "Right", "Home": "Home", "End": "End", "PgUp": "PageUp", "PgDn": "PageDown", "Delete": "DC", "Insert": "IC"}
_TOKEN = re.compile(r"\{\{|\}\}|(?<!\$)\{([A-Za-z][A-Za-z0-9-]*)\}")


def parse_keys(text):
    """text with {Key} tokens -> [("text", str) | ("key", tmuxname)]. {{ and }} are a literal brace. A {word} that is NOT a known key stays as the
    literal text it is ({"a": 1} is typed as it is). Names are CASE SENSITIVE and a `{` right after `$` is never a key, so `${Home}` and
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


def send(tab, text=None, keys=None, session="main", pause=PAUSE, cancel_mode=True):
    """Type `text` (with {Key} tokens, see parse_keys) and/or press `keys` (a list of tmux key names). Text and each key are separate
    send-keys calls with `pause` seconds between them. A pane in a mode (copy-mode, view-mode) gets the mode cancelled first (-X cancel), or
    TmuxError when cancel_mode=False: without that the keys would drive the mode, not the program. Returns the steps run."""
    t = resolve(tab, session)
    steps = parse_keys(text) if text else []
    steps += [("key", k) for k in (keys or [])]
    if tmux("display-message", "-p", "-t", t.pane, "#{pane_in_mode}").strip() == "1":
        if not cancel_mode:
            raise TmuxError("the pane %s is in a mode (copy-mode): keys would not reach the program" % t.pane)
        tmux("send-keys", "-t", t.pane, "-X", "cancel")
    for i, (kind, val) in enumerate(steps):
        if i and pause:
            time.sleep(pause)
        if kind == "text":
            tmux("send-keys", "-t", t.pane, "-l", "--", val)
        else:
            tmux("send-keys", "-t", t.pane, val)
    return steps
