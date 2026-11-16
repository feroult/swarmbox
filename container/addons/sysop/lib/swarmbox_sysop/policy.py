"""The policy of the sysop: what each `run` and `input` of the brain is worth, and what has to happen before it is sent.

Everything here is computed by the host from the text and from what the tab runs, never from what the brain claims. The brain cannot lower a
risk, pick the autonomy or skip the countdown.

THE RISK of an action (assess_run / assess_input), low, medium or high, plus `block`:
  * the target tab runs an AGENT (claude, gemini, opencode, codex, aider), a SHELL (bash, zsh, ...) or something ELSE (python, vim, ssh,
    a program that is running a command, node...). A tab that is not a shell or an agent is rated at least medium: what is typed there is
    code of a program the policy cannot read.
  * agent: the text is a prompt, low. A text whose first character is `/` or `!` (a slash command, a shell escape) is BLOCKED (no approval path:
    the sysop never passes --slash to swarmbox-tabs, which refuses it anyway). A later line that starts so is medium. Any key
    while a dialog of the agent is on the screen (Esc included: it rejects the request) is high, so it always needs the user's approval, never a
    countdown: a dialog is the USER's decision.
  * shell: classify_command(the whole line; for `run` the text already on the command line of the screen is part of it) from risk.py. The line is what is already typed plus the new text, because a command can be typed in
    several parts (input "r", input "m -rf ~", input "{Enter}"): the policy keeps what it typed in each tab since the last Enter or {C-c}. Keys
    that edit the line ({Up}, {Left}, {Tab}...) make that text unreliable: an Enter then is at least medium. An Enter with nothing known on the
    line runs whatever is there (medium). {C-j}, {C-m} and {C-o} end a line like {Enter}. A command that mentions tmux, the bus, the sysop commands or the
    sysop's own files is high (risk.py): an approval is a file, and those commands type into any tab.
  * control characters in a text (ESC, C-c, a carriage return...) are blocked: keys are written {Key}. Text longer than MAX_TEXT is blocked.
  * `{Key}` words follow swarmbox-tabs (parse_keys): only the known names are keys; an unknown {word} is an error for the brain, {{ and }}
    are literal braces.
  * it is not a sandbox: an alias, a script, a Makefile can do anything. The point is that the dangerous shapes cost a deliberate approval.

WHAT HAPPENS (route) depends on the autonomy level and on the risk:
                    low          medium       high
  confirm-all       approve      approve      approve
  confirm-risky     countdown    approve      approve
  auto              at once      countdown    approve        (the default)
  `countdown` = the action is shown in the panel and sent after SWARMBOX_SYSOP_COUNTDOWN seconds unless the user vetoes it (0 = sent at once);
  `approve` = it is NOT sent unless the user allows it (a tap on Allow in the panel or on the strip, or Ctrl+A a), and after SWARMBOX_SYSOP_APPROVAL_TIMEOUT seconds it is
  refused. No autonomy level sends a high-risk action without that approval. A blocked action is refused outright.

THE BUDGETS (Budget): at most max_steps tool calls (say and done do not count) and until a deadline; past either, every tool but say and
done answers with an error. (The service also kills the brain at the deadline.)
"""
import os
import re
import time
import unicodedata

from . import risk

AGENT_COMMANDS = ("claude", "gemini", "opencode", "codex", "aider")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "ash")
MAX_TEXT = 4000
LEVELS = risk.LEVELS

# the keys of swarmbox-tabs (container/scripts/swarmbox-tabs.py KEYS and parse_keys): the same names, so a key that this accepts is one
# swarmbox-tabs turns into a key. tests/fast/test_sysop_policy.py compares this table with that of swarmbox-tabs.
KEYS = ("Esc", "Enter", "Tab", "BTab", "Space", "BSpace", "Up", "Down", "Left", "Right", "Home", "End", "PgUp", "PgDn", "Delete", "Insert")
# keys that end a line like Enter does: C-j and C-m are a line feed and a carriage return, C-o runs the line and fetches the next one (bash)
ENTERS = ("Enter", "C-j", "C-m", "C-o")
_TOKEN = re.compile(r"\{\{|\}\}|(?<!\$)\{([A-Za-z][A-Za-z0-9-]*)\}")
_DIALOG = re.compile(r"Enter to confirm|Esc to cancel|Esc to exit|Do you want to|\(y/n\)|\[Y/n\]|\[y/N\]")
DIALOG_REASON = "{%s} answers a dialog of the agent: that is the user's decision (it may grant or reject a permission)"
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x80-\x9f]")      # everything but \t and \n; includes C1 (CSI as one byte)


def history_reference(line):
    """A reason when `line` (typed into a shell) holds a history expansion that bash would replace with an earlier command of the tab: `!!`,
    `!rm`, `!-3`, `^a^b` at the start. A `!` inside single quotes, behind a backslash or behind `$`, or followed by a blank, `=` or `(` is not one.
    Anything else is refused, which is the safe side: the brain can write the command without it."""
    if line[:1] == "^":
        return "a line that starts with ^ is a history substitution (it re-runs an earlier command with a change)"
    quote, i = "", 0
    while i < len(line):
        c = line[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote == "'":
            if c == "'":
                quote = ""
        elif c == "'" and quote == "":
            quote = "'"
        elif c == '"':
            quote = "" if quote == '"' else '"'
        elif c == "!" and quote != "'" and not (i > 0 and line[i - 1] == "$"):
            nxt = line[i + 1:i + 2]
            if nxt and nxt not in " \t\n=(":
                return "an exclamation mark followed by text is a history reference (it re-runs an earlier command): write the command out"
        i += 1
    return ""


class PolicyError(Exception):
    """An action the brain asked for that is wrong in itself (an unknown key, a bad text): the message goes back to the brain."""


def key_name(name):
    """The name swarmbox-tabs gives to {name}, or None when {name} is not a key."""
    if name in KEYS or re.fullmatch(r"C-[a-z]", name) or re.fullmatch(r"M-[a-zA-Z0-9]", name) or re.fullmatch(r"F([1-9]|1[0-2])", name):
        return name
    return None


def parse_input(text):
    """text with {Key} tokens -> [("text", str) | ("key", name)], like swarmbox-tabs; an unknown {word} raises PolicyError."""
    steps, pos, buf = [], 0, []

    def flush():
        if buf and "".join(buf):
            steps.append(("text", "".join(buf)))
        del buf[:]
    for m in _TOKEN.finditer(text):
        buf.append(text[pos:m.start()])
        pos = m.end()
        tok = m.group(0)
        if tok in ("{{", "}}"):
            buf.append(tok[0])
            continue
        if key_name(m.group(1)) is None:
            raise PolicyError("unknown key {%s}: the keys are %s, C-a..C-z, M-x, F1..F12; write {{ and }} for a literal brace"
                              % (m.group(1), " ".join("{%s}" % k for k in KEYS)))
        flush()
        steps.append(("key", m.group(1)))
    buf.append(text[pos:])
    flush()
    return steps


def tab_kind(cmd):
    base = os.path.basename(str(cmd or "").strip()).lstrip("-").lower()
    if base in AGENT_COMMANDS:
        return "agent"
    if base in SHELLS:
        return "shell"
    return "other"


class Verdict:
    def __init__(self, level="low", reasons=None, block=False):
        self.level, self.reasons, self.block = level, list(reasons or []), block

    def add(self, level, reason):
        if LEVELS.index(level) > LEVELS.index(self.level):
            self.level = level
        if reason not in self.reasons:
            self.reasons.append(reason)

    def as_dict(self):
        return {"level": self.level, "reasons": self.reasons[:8], "block": self.block}


class Route:
    """What to do with an action: action is block, approve, veto or allow; seconds is the countdown or the approval window."""

    def __init__(self, action, seconds=0.0):
        self.action, self.seconds = action, seconds


class Budget:
    def __init__(self, max_steps, deadline, clock=time.time):
        self.max_steps, self.deadline, self.clock, self.steps = max_steps, deadline, clock, 0

    def charge(self):
        """Count one tool call; PolicyError when the budget is spent."""
        if self.deadline is not None and self.clock() >= self.deadline:
            raise PolicyError("the time budget of this goal is spent: do not call more tools, say what is done and call done")
        if self.steps >= self.max_steps:
            raise PolicyError("the budget of %d tool calls is spent: do not call more tools, say what is done and call done" % self.max_steps)
        self.steps += 1


class Buffer:
    """What was typed in a tab since the last Enter or C-c: the text, and whether keys edited it since (so the text is not what is there)."""

    def __init__(self):
        self.text, self.dirty = "", False


class Policy:
    def __init__(self, autonomy="auto", countdown=4.0, approval_timeout=60.0, max_steps=20, deadline=None, clock=time.time):
        self.autonomy, self.countdown, self.approval_timeout = autonomy, float(countdown), float(approval_timeout)
        self.budget = Budget(max_steps, deadline, clock)
        self.buffers = {}

    def buf(self, tab_id):
        return self.buffers.setdefault(tab_id, Buffer())

    # ---- the risk
    @staticmethod
    def _check_text(text):
        if not isinstance(text, str) or text == "":
            raise PolicyError("the text is empty")
        if len(text) > MAX_TEXT:
            raise PolicyError("the text has %d characters, at most %d: split the work" % (len(text), MAX_TEXT))

    @staticmethod
    def _control(text, v, kind="agent", before=""):
        if _CONTROL.search(text):
            v.block = True
            v.add("high", "the text holds control characters (use a {Key} for keys)")
        if kind != "agent":
            # readline and history expand text before the shell parses it, so the text that risk.py rates is not what runs
            if "\t" in text:
                v.block = True
                v.add("high", "a Tab character completes a name in the shell: what runs is not the text typed (use plain spaces)")
            reason = history_reference(before + text)
            if reason:
                v.block = True
                v.add("high", reason)

    def _line_risk(self, kind, line, v, dirty):
        """The text of a command line in a shell (or a program that is not an agent)."""
        lv, rs = risk.classify_command(line)
        for r in rs:
            if r != "no risky pattern found":
                v.add(lv, r)
        if lv == "low" and not v.reasons:
            v.reasons.append("no risky pattern found")
        if kind == "other":
            v.add("medium", "typed into a program that is not a shell or an agent: it may run anything")
            if risk._CODE_DANGER.search(line):
                v.add("high", "code that deletes files or runs programs, typed into a program that is not a shell")
        if dirty:
            v.add("medium", "keys edited the line, so what runs is not exactly the text typed")

    @staticmethod
    def _agent_start(text, v):
        body = risk._normalize(text).lstrip()
        if body[:1] in ("/", "!"):
            v.block = True
            v.add("high", 'text that starts with "%s" is a command for the agent (a menu or a shell escape), not a prompt' % body[:1])
        for ln in body.split("\n")[1:]:
            if ln.lstrip()[:1] in ("/", "!"):
                v.add("medium", 'a later line starts with "/" or "!"')

    def assess_run(self, tab, text, prefill=""):
        """Verdict for `run`: text typed and Enter. tab is a dict with at least "tab" and "cmd". prefill is what the screen shows on the command line
        of a shell tab before the text goes in (typed by the user or left by something else, not by this goal); it is part of the line that runs."""
        self._check_text(text)
        kind = tab_kind(tab.get("cmd"))
        v = Verdict()
        b = self.buf(tab["tab"])
        self._control(text, v, kind, b.text)
        if kind == "agent":
            if not b.text or b.dirty:
                self._agent_start(text, v)
            elif "\n" in text:
                self._agent_start("x\n" + text, v)
            if not v.reasons:
                v.reasons.append("a prompt for %s" % os.path.basename(str(tab.get("cmd"))))
        else:
            self._line_risk(kind, (b.text or prefill) + text, v, b.dirty)
        return v

    def assess_input(self, tab, text, screen=""):
        """Verdict for `input`: the text and keys in order. screen is the plain screen of the tab (used for dialogs of an agent)."""
        self._check_text(text)
        steps = parse_input(text)
        kind = tab_kind(tab.get("cmd"))
        v = Verdict()
        buf, dirty = self.buf(tab["tab"]).text, self.buf(tab["tab"]).dirty
        # the screen decides, not the name of the process: Claude Code started through `tmux new-window CMD`, `env`, `ssh` or `bash -c` shows as sh,
        # ssh or node. A screen with a dialog is a dialog whatever runs: it is rated as an agent's (the safe side)
        dialog = bool(_DIALOG.search("\n".join([x for x in screen.split("\n") if x.strip()][-14:])))
        if dialog:
            kind = "agent"
        self._control(text, v, kind, buf)
        for what, val in steps:
            if what == "text":
                if kind == "agent" and (not buf or dirty):
                    # after {Home}, {Left}... the text may land at the start of what is in the box: look at its first character anyway
                    self._agent_start(val, v)
                buf += val
                if kind != "agent":
                    self._line_risk(kind, buf, v, dirty)
                elif dialog:
                    v.add("high", "answers a dialog of the agent (it may grant permissions)")
                continue
            if val in ENTERS:
                if kind == "agent":
                    if dialog:
                        v.add("high", "Enter answers a dialog of the agent (it may grant permissions)")
                    elif not buf:
                        v.add("medium", "Enter with nothing typed submits or accepts whatever the agent shows")
                else:
                    if buf == "" and not dirty:
                        v.add("medium", "Enter with nothing typed runs whatever is on the command line")
                    else:
                        self._line_risk(kind, buf, v, dirty)
                buf, dirty = "", False
            elif val == "C-c":
                if dialog:
                    v.add("high", DIALOG_REASON % "C-c")
                elif kind == "agent":
                    v.add("medium", "C-c can exit the agent")
                buf, dirty = "", False
            elif val == "C-d":
                v.add("medium", "C-d ends the input: it exits a shell or an agent")
                if dialog:
                    v.add("high", DIALOG_REASON % "C-d")
                buf, dirty = "", False
            elif val == "Esc":
                if dialog:
                    v.add("high", DIALOG_REASON % "Esc")      # Esc rejects the request the dialog asks about
                else:
                    dirty = dirty or bool(buf)
            else:
                dirty = True
                if dialog:
                    v.add("high", DIALOG_REASON % val)
        if not v.reasons:
            v.reasons.append("keys only" if all(w == "key" for w, _ in steps) else "text typed, nothing runs")
        return v

    def commit(self, tab, kind, text, typed=True):
        """Remember what was typed (after the bus accepted it); typed=False after an error that may have typed part of it."""
        b = self.buf(tab["tab"])
        if not typed:
            b.dirty = True
            return
        if kind == "run":
            b.text, b.dirty = "", False
            return
        for what, val in parse_input(text):
            if what == "text":
                b.text += val
            elif val in ENTERS or val in ("C-c", "C-d"):
                b.text, b.dirty = "", False
            elif val == "Esc":
                b.dirty = b.dirty or bool(b.text)
            else:
                b.dirty = True
        if len(b.text) > 4 * MAX_TEXT:
            b.text = b.text[-4 * MAX_TEXT:]

    # ---- what to do
    def route(self, verdict):
        if verdict.block:
            return Route("block")
        level = verdict.level
        if self.autonomy == "confirm-all" or level == "high" or (level == "medium" and self.autonomy == "confirm-risky"):
            return Route("approve", self.approval_timeout)
        if self.countdown <= 0 or (self.autonomy == "auto" and level == "low"):
            return Route("allow")
        return Route("veto", self.countdown)
