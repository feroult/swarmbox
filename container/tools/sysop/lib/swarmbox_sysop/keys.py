"""The keys of the sysop that work from ANY tab: `swarmbox-sysop veto | approve | stop | goal` called by the tmux keys of
container/config/tmux.conf: Ctrl+A then V / X / a / g.

Why they exist: the panel never takes the focus by itself (dock.Follower opens it with -d), so what you type in your own tab never reaches it.
Its own keys (c, x, r, g) only work once you focus it with a click or with the approval gesture below. These commands are the way to act on
the goal without that:

  veto       V   refuse what waits: a countdown is vetoed (it is NOT sent), an approval is refused. Writes decision.json like the panel's c.
  stop       X   `swarmbox-sysop stop`: ends the goal and drops the queue (cmd_stop in cli.py).
  approve    a   the stronger gesture for a HIGH-RISK action: it does NOT allow anything. It makes the panel of this window exist, tells it to open
                 its approval prompt, waits until it did, and only THEN gives it the focus. So keys typed before the gesture went to your tab, and
                 keys typed after it are the word `run` you mean to type (nothing is allowed until the panel gets `run` and Enter).
  goal       g   `swarmbox-sysop goal` with no text on a terminal asks for the goal on one line (tmux runs it in a popup: a popup takes the keys
                 of the client, never of the panel).

The approve request is a file in the run folder (ipc.py: panel.request, {"action": "approve", "id": the pending action, "time", "pane": the tmux
pane of the panel that is to take it}); the panel deletes it when it has taken it (panel.py, Panel.take_request). Every window has a panel, so the
pane says which one: the others leave the request alone.
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


def approve(pth, dk, window, tmux=None, client="", wait=ACK_SECONDS):
    """The key a. Exit code 0 when the panel has its approval prompt open and the focus, 1 otherwise (and nothing was focused)."""
    gid, p = pending_of(pth)
    if not p or not _live(p) or p.get("mode") == "veto":
        _say("no high-risk action is waiting for approval", tmux, client)
        return 1
    try:
        dk.open(window=window, focus=False, auto=True)
    except dock.DockError as e:
        _say("the panel could not be opened: %s" % e, tmux, client)
        return 1
    try:
        # the request names the pane: with a panel in every window, only the panel that is about to get the focus may take it
        ipc.write_json(pth.panel_request, {"action": "approve", "id": str(p["id"]), "time": time.time(), "pane": dk.panel_pane(window)})
    except OSError as e:
        _say("could not ask the panel: %s" % (e.strerror or e), tmux, client)
        return 1
    end = time.time() + wait
    while time.time() < end and os.path.exists(pth.panel_request):
        time.sleep(0.05)
    if os.path.exists(pth.panel_request):
        ipc.remove(pth.panel_request)
        _say("the panel did not answer: focus it with a click", tmux, client)
        return 1
    try:
        dk.focus(window=window)
    except dock.DockError as e:
        _say("the panel could not be focused: %s" % e, tmux, client)
        return 1
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
