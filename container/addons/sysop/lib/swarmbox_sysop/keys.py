"""The keys of the sysop that work from ANY tab: `swarmbox-sysop veto | approve | stop | goal` called by the tmux keys of
container/config/tmux.conf: Ctrl+A then V / X / a / g.

Why they exist: the panel never takes the focus by itself (dock.Follower opens it with -d), so what you type in your own tab never reaches it.
Its own keys only work once you focus it with a click. These commands are the way to act on
the goal without that:

  veto       V   Cancel: refuse what waits (a countdown is vetoed, it is NOT sent; an approval is refused); with nothing waiting it stops the goal.
                 Writes decision.json like the panel's Cancel.
  stop       X   `swarmbox-sysop stop`: ends the goal and drops the queue (cmd_stop in cli.py).
  approve    a   allow what waits (a high-risk action, or a countdown now). One press, no typed word: it is a tmux prefix key or a tap on the Allow
                 button of the web strip, which a program in a tab cannot press. Writes decision.json like the panel's Allow.
  goal       g   `swarmbox-sysop goal` with no text on a terminal asks for the goal on one line (tmux runs it in a popup: a popup takes the keys
                 of the client, never of the panel).
"""
import os
import sys
import time

from . import dock, ipc, service

ACK_SECONDS = 3.0


def _say(msg, tmux=None, client=""):
    """To stderr (tmux shows nothing of a background run-shell) and, when the key gave a client, in that client's status line."""
    print("swarmbox-sysop: %s" % msg, file=sys.stderr)
    if tmux is not None and client:
        tmux.run("display-message", "-c", client, "sysop: " + msg)


def pending_of(pth):
    """(goal id, pending action) of the running goal, or (id or "", None)."""
    st = ipc.read_json(pth.status) if service.running(pth) else None
    gid = service.sanitize((st or {}).get("current"), "") if isinstance(st, dict) and st.get("current") else ""
    if not gid:
        return "", None
    p = ipc.read_json(os.path.join(pth.goal_dir(gid), "pending_action.json"))
    return gid, (p if isinstance(p, dict) and p.get("id") else None)


def _live(p, wall=None):
    try:
        return float(p.get("deadline")) > (time.time() if wall is None else wall)
    except (AttributeError, TypeError, ValueError):
        return False


def veto(pth, tmux=None, client=""):
    """The key c. Exit code 0 when a decision was written, 1 when nothing waits."""
    gid, p = pending_of(pth)
    if not p or not _live(p):
        _say("nothing is waiting for a veto", tmux, client)
        return 1
    mode = "veto" if p.get("mode") == "veto" else "deny"
    try:
        ipc.write_json(os.path.join(pth.goal_dir(gid), "decision.json"), {"id": str(p["id"]), "decision": mode, "by": "key"})
    except OSError as e:
        _say("could not write the decision: %s" % (e.strerror or e), tmux, client)
        return 1
    _say("vetoed: it will not be sent" if mode == "veto" else "refused", tmux, client)
    return 0


def approve(pth, dk=None, window=None, tmux=None, client="", wait=0):
    """The key a (and the Allow button of the web strip): allow what waits. A countdown is sent now; a high-risk action is allowed. It is a
    deliberate gesture of a client of tmux (a prefix key or a tap on a button), which is why it needs no typed word. Writes decision.json with
    the word the service requires. Exit code 0 when a decision was written, 1 when nothing waits."""
    gid, p = pending_of(pth)
    if not p or not _live(p):
        _say("nothing is waiting for you", tmux, client)
        return 1
    try:
        ipc.write_json(os.path.join(pth.goal_dir(gid), "decision.json"), {"id": str(p["id"]), "decision": "approve", "by": "key", "word": "run"})
    except OSError as e:
        _say("could not write the decision: %s" % (e.strerror or e), tmux, client)
        return 1
    _say("allowed", tmux, client)
    return 0


def prompt(bus, source="panel", inp=None, out=None, topic=None):
    """The key g, run by tmux in a popup: ask for a goal on one line and publish it. Exit codes as `swarmbox-sysop goal`."""
    from . import busclient, config
    inp, out = inp or sys.stdin, out or sys.stderr
    out.write("Goal for the sysop (Enter sends it, empty cancels): ")
    out.flush()
    text = inp.readline().strip()
    if not text:
        return 1
    if len(text) > service.MAX_GOAL_TEXT:
        out.write("too long: %d characters, at most %d. Press Enter." % (len(text), service.MAX_GOAL_TEXT))
        inp.readline()
        return 2
    try:
        bus.pub(topic or config.goal_topic(), {"text": text}, source)
    except (busclient.BusError, config.ConfigError) as e:
        out.write("the goal was not sent: %s. Press Enter." % busclient.words(e))
        out.flush()
        inp.readline()
        return 3
    return 0
