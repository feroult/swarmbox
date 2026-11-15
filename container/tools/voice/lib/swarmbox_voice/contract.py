"""The planner contract: what goes in, what may come out, and the validator of the output.

Input (JSON on the planner's stdin), see build_input:
    {"utterance": str, "active_pane": "%N", "panes": [{"id", "window", "cwd", "command", "tail"}]}
    There is no language field.
Output (JSON on stdout), validated by parse_output / validate_plan:
    {"say": str, "actions": [action, ...]}
    action = {"type": "send_text", "pane": "%N", "text": str, "enter": bool (default false)}
           | {"type": "new_window", "name": str (optional), "cwd": str (optional)}
           | {"type": "select_pane", "pane": "%N"}
A planner must not declare risk: a "risk" key (top level or in an action) is ignored and stripped. Any other unknown key,
an unknown action type or an unknown pane is rejected. Validation never raises anything but ContractError.
Errors carry a stable `code`: output_too_large not_json not_object bad_shape unknown_key bad_type unknown_action
unknown_pane too_long too_many_actions bad_text.
"""
import json
import re
import unicodedata

ACTION_TYPES = ("send_text", "new_window", "select_pane")
MAX_OUTPUT_BYTES = 64 * 1024
MAX_ACTIONS = 8
MAX_TEXT = 2000
MAX_SAY = 500
MAX_NAME = 50
MAX_CWD = 500
PANE_ID = re.compile(r"%[0-9]{1,9}")
STRIPPED_KEYS = ("risk",)


class ContractError(ValueError):
    def __init__(self, code, message):
        ValueError.__init__(self, "%s: %s" % (code, message))
        self.code = code
        self.message = message


def build_input(utterance, active_pane, panes):
    """The planner input, with exactly the contract keys. Use context.build_input to also apply the host limits."""
    return {"utterance": utterance, "active_pane": active_pane, "panes": panes}


def _str(value, what, limit, allow_newline=False):
    if not isinstance(value, str):
        raise ContractError("bad_type", "%s must be a string" % what)
    if len(value) > limit:
        raise ContractError("too_long", "%s is longer than %d characters" % (what, limit))
    for ch in value:
        cat = unicodedata.category(ch)
        if cat in ("Cf", "Cs", "Co", "Cn"):
            raise ContractError("bad_text", "%s has an invisible or invalid character (U+%04X)" % (what, ord(ch)))
        if cat == "Cc" and ch != "\t" and not (allow_newline and ch == "\n"):
            raise ContractError("bad_text", "%s has a control character (U+%04X)" % (what, ord(ch)))
    return value


def _no_format(value, what):
    if "#" in value:
        raise ContractError("bad_text", "%s must not contain '#' (tmux would expand it as a format)" % what)
    return value


def _keys(obj, allowed, what):
    for key in obj:
        if key in STRIPPED_KEYS:
            continue
        if key not in allowed:
            raise ContractError("unknown_key", "%s has an unknown key %r" % (what, str(key)[:40]))


def _pane(obj, pane_ids, what):
    pane = obj.get("pane")
    if not isinstance(pane, str):
        raise ContractError("bad_type", "%s needs a pane id string" % what)
    if not PANE_ID.fullmatch(pane) or pane not in pane_ids:
        raise ContractError("unknown_pane", "%s targets a pane that does not exist: %r" % (what, pane[:20]))
    return pane


def validate_action(action, pane_ids, index=0):
    """Return the normalized copy of one action, or raise ContractError."""
    what = "action %d" % index
    if not isinstance(action, dict):
        raise ContractError("bad_shape", "%s must be an object" % what)
    kind = action.get("type")
    if not isinstance(kind, str):
        raise ContractError("bad_type", "%s needs a type string" % what)
    if kind not in ACTION_TYPES:
        raise ContractError("unknown_action", "%s has an unknown type %r" % (what, kind[:40]))
    pane_ids = set(pane_ids)
    if kind == "send_text":
        _keys(action, ("type", "pane", "text", "enter"), what)
        pane = _pane(action, pane_ids, what)
        if "text" not in action:
            raise ContractError("bad_shape", "%s needs text" % what)
        text = _str(action["text"], what + " text", MAX_TEXT)
        if text.strip() == "":
            # a blank text with Enter would submit whatever an earlier action left in the line buffer
            raise ContractError("bad_shape", "%s has empty text" % what)
        enter = action.get("enter", False)
        if not isinstance(enter, bool):
            raise ContractError("bad_type", "%s enter must be true or false" % what)
        return {"type": kind, "pane": pane, "text": text, "enter": enter}
    if kind == "select_pane":
        _keys(action, ("type", "pane"), what)
        return {"type": kind, "pane": _pane(action, pane_ids, what)}
    _keys(action, ("type", "name", "cwd"), what)
    out = {"type": kind}
    # tmux expands formats in -n and -c, and #(command) runs a shell command: no '#' is allowed in either
    if "name" in action:
        out["name"] = _no_format(_str(action["name"], what + " name", MAX_NAME), what + " name")
    if "cwd" in action:
        out["cwd"] = _no_format(_str(action["cwd"], what + " cwd", MAX_CWD), what + " cwd")
    return out


def validate_plan(obj, pane_ids):
    """Return the normalized plan {"say", "actions"} for an already parsed object, or raise ContractError."""
    if not isinstance(obj, dict):
        raise ContractError("not_object", "the plan must be a JSON object")
    _keys(obj, ("say", "actions"), "plan")
    actions = obj.get("actions")
    if not isinstance(actions, list):
        raise ContractError("bad_shape", "plan needs an actions list")
    if len(actions) > MAX_ACTIONS:
        raise ContractError("too_many_actions", "more than %d actions" % MAX_ACTIONS)
    say = _str(obj.get("say", ""), "say", MAX_SAY, allow_newline=True)
    pane_ids = set(pane_ids)
    return {"say": say, "actions": [validate_action(a, pane_ids, i) for i, a in enumerate(actions)]}


def _no_constant(name):
    raise ValueError("not allowed: " + name)


def parse_output(raw, pane_ids):
    """Parse planner stdout (bytes or str) and validate it. Raises only ContractError."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "surrogatepass")
    if not isinstance(raw, (bytes, bytearray)):
        raise ContractError("not_json", "the planner output is not text")
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ContractError("output_too_large", "the planner output is larger than %d bytes" % MAX_OUTPUT_BYTES)
    try:
        obj = json.loads(bytes(raw).decode("utf-8"), parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise ContractError("not_json", "the planner output is not valid JSON") from None
    return validate_plan(obj, pane_ids)
