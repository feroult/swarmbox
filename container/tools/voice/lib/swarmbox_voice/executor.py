"""Apply a validated, CONFIRMED plan with tmux.

execute(actions, confirmed, tmux=None, session="main") -> [{"type", "ok", "error"?, "pane"?}]

- confirmed must be exactly True, otherwise ExecutorError is raised and nothing is sent.
- Every action is validated again here (contract.validate_action) against the panes that exist NOW in the session.
- send_text uses `send-keys -l -- TEXT` (literal: no key names, no escapes). Enter is sent only when enter is true.
- Targets are only panes of the session, never the voice panel; execution stops at the first failing action.
The tmux binary is a Tmux object (tmuxrun), so a test can substitute argv or pass a spy with a `run(*args)` method.
"""
import os

from . import contract
from .tmuxrun import PANEL_COMMAND, PANEL_MARK, PANEL_OPTION, SEP, Tmux


class ExecutorError(RuntimeError):
    pass


def session_panes(tmux, session):
    """The ids of the panes a plan may target: every pane of the session except the voice panel."""
    res = tmux.run("list-panes", "-s", "-t", "=" + session, "-F", SEP.join(["#{pane_id}", "#{%s}" % PANEL_OPTION, "#{pane_start_command}"]))
    if res.rc != 0:
        raise ExecutorError("tmux session %r is not available: %s" % (session, res.err.strip()[:200]))
    out = set()
    for line in res.out.splitlines():
        pane_id, _, rest = line.strip().partition(SEP)
        mark, _, start = rest.partition(SEP)
        if pane_id and mark != PANEL_MARK and PANEL_COMMAND not in start:
            out.add(pane_id)
    return out


def execute(actions, confirmed, tmux=None, session="main"):
    if confirmed is not True:
        raise ExecutorError("the plan was not confirmed")
    tmux = tmux or Tmux()
    panes = session_panes(tmux, session)
    results = []
    try:
        checked = [contract.validate_action(a, panes, i) for i, a in enumerate(actions)]
    except contract.ContractError as e:
        raise ExecutorError("invalid action: %s" % e) from None
    for action in checked:
        res = _one(action, tmux, session)
        results.append(res)
        if not res["ok"]:
            break
    return results


def _one(action, tmux, session):
    kind = action["type"]
    out = {"type": kind, "ok": False}
    if kind == "send_text":
        out["pane"] = action["pane"]
        r = tmux.run("send-keys", "-t", action["pane"], "-l", "--", action["text"])
        if r.rc == 0 and action["enter"]:
            r = tmux.run("send-keys", "-t", action["pane"], "Enter")
    elif kind == "select_pane":
        out["pane"] = action["pane"]
        r = tmux.run("select-window", "-t", action["pane"])
        if r.rc == 0:
            r = tmux.run("select-pane", "-t", action["pane"])
    else:
        args = ["new-window", "-t", "=%s:" % session, "-P", "-F", "#{pane_id}"]
        if "cwd" in action:
            cwd = os.path.expanduser(action["cwd"])
            if not os.path.isdir(cwd):
                out["error"] = "cwd is not a directory"
                return out
            args += ["-c", cwd.replace("#", "##")]
        if "name" in action:
            args += ["-n", action["name"].replace("#", "##")]
        r = tmux.run(*args)
        if r.rc == 0:
            out["pane"] = r.out.strip()
    if r.rc == 0:
        out["ok"] = True
    else:
        out["error"] = (r.err.strip() or "tmux failed (rc %d)" % r.rc)[:200]
    return out
