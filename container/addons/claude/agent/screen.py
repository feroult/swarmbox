"""The screen adapter of Claude Code (docs/agents-design.md 3.2): what its screen says when the state it reports (OSC 7501) is not there.

Loaded by the agent registry (swarmbox_agents.hook) for `swarmbox-tabs` and the sysop. The interface, every function optional but state:
  state(rows)              -> "dialog" | "busy" | "idle" | "unknown"
  detect(rows)             -> True when these rows are this agent's screen (an agent started under another process name)
  input_box(rows, lenient) -> the text in the agent's input box, or None when there is no box on the screen
  submitted(rows, tail)    -> after an Enter: True (the text left the box), False (it is still there), None (cannot tell)
`rows` are the plain lines of the screen, top to bottom. The rules below were measured on Claude Code 2.1 (dev/spikes/enter/screens).
Standard library only.
"""
import re

_RULE = "─" * 6          # a line that starts so is a rule of the input box of Claude Code
_DASHED = "╌" * 6
_DIALOG_FOOTER = re.compile(r"Enter to confirm|Esc to cancel|Esc to exit")
_DIALOG_BODY = re.compile(r"Do you want to")
_INTERRUPT = "esc to interrupt"
_PASTED = "[Pasted text"   # what the box shows for a long text pasted into it


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
        top = max([i for i, x in enumerate(rows[:r[0]]) if x.startswith("❯")] or [0])
        body = rows[top:r[0]]
    else:
        return None
    box = []
    for x in body:
        if x.startswith("❯"):
            x = x[1:]
        box.append(x[1:] if x[:1] in (" ", "\xa0") else x)
    return "\n".join(box).strip("\n")


def _footer_busy(row):
    """The footer of Claude Code while it works ends with `· esc to interrupt`. In a narrow pane the end is cut (`· esc to in…`, `· esc …`, a lone `·`) and
    the words are not whole on the screen, which a phone held sideways (about 60 columns) does. So: after the last `·` of the row, nothing, or a start of
    those words (with an ellipsis or not). A pane of about 30 columns shows no `·` at all: nothing on that screen tells busy from idle."""
    if "·" not in row:
        return False
    tail = row.rsplit("·", 1)[1].strip().rstrip("…").strip().lower()
    return _INTERRUPT.startswith(tail)


def _dialog(rows, box):
    used = [r for r in rows if r.strip()]
    footer = used[-4:]
    return _has_rule(rows) and (any(_DIALOG_FOOTER.search(x) for x in footer) or (not box and any(_DIALOG_BODY.search(x) for x in used[-12:])))


def detect(rows):
    """A screen of Claude Code: its input box, or a dialog footer next to a rule."""
    box = input_box(rows) is not None
    return box or _dialog(rows, box)


def state(rows):
    """dialog, busy, idle or unknown. Only the bottom of the screen is read: an old answer that says "Do you want to" is no dialog."""
    used = [r for r in rows if r.strip()]
    bottom = used[-14:]
    box = input_box(rows) is not None
    if _dialog(rows, box):
        return "dialog"
    if any(_INTERRUPT in x for x in bottom[-3:]) or (box and used and _footer_busy(used[-1])):
        return "busy"
    return "idle" if box else "unknown"


def submitted(rows, tail):
    """After an Enter: did the text whose last characters are `tail` leave the input box? None when no box is on the screen."""
    box = input_box(rows, lenient=True)
    if box is None:
        return None
    return not (tail in box or _PASTED in box)
