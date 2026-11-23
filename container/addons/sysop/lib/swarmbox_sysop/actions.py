"""Mux-agnostic control actions of the sysop: reading a pending action, writing veto/approve decisions, requesting stop, and publishing goals.

Any front-end (terminal keybindings, panel, web gateway, mobile client, CLI) calls these directly without depending on the multiplexer.
"""
import os
import time
from collections import namedtuple

from . import busclient, config, ipc, service

ActionResult = namedtuple("ActionResult", "ok rc message")


def pending_of(pth):
    """(goal id, pending action) of the running goal, or (id or "", None)."""
    st = ipc.read_json(pth.status) if service.running(pth) else None
    gid = service.sanitize((st or {}).get("current"), "") if isinstance(st, dict) and st.get("current") else ""
    if not gid:
        return "", None
    p = ipc.read_json(os.path.join(pth.goal_dir(gid), "pending_action.json"))
    return gid, (p if isinstance(p, dict) and p.get("id") else None)


def is_live(p, wall=None):
    try:
        return float(p.get("deadline")) > (time.time() if wall is None else wall)
    except (AttributeError, TypeError, ValueError):
        return False


def veto(pth, by="key", wall=None):
    """Refuse what waits (a countdown is vetoed, an approval is denied). Returns ActionResult."""
    gid, p = pending_of(pth)
    if not p or not is_live(p, wall):
        return ActionResult(False, 1, "nothing is waiting for a veto")
    mode = "veto" if p.get("mode") == "veto" else "deny"
    try:
        ipc.write_json(os.path.join(pth.goal_dir(gid), "decision.json"), {"id": str(p["id"]), "decision": mode, "by": by})
    except OSError as e:
        return ActionResult(False, 1, "could not write the decision: %s" % (e.strerror or e))
    return ActionResult(True, 0, "vetoed: it will not be sent" if mode == "veto" else "refused")


def approve(pth, by="key", wall=None):
    """Allow what waits (a countdown is sent now; a high-risk action is approved). Returns ActionResult."""
    gid, p = pending_of(pth)
    if not p or not is_live(p, wall):
        return ActionResult(False, 1, "nothing is waiting for you")
    try:
        ipc.write_json(os.path.join(pth.goal_dir(gid), "decision.json"), {"id": str(p["id"]), "decision": "approve", "by": by, "word": "run"})
    except OSError as e:
        return ActionResult(False, 1, "could not write the decision: %s" % (e.strerror or e))
    return ActionResult(True, 0, "allowed")


def stop(pth, goal_id=None, wait=5.0):
    """Request stopping the running goal (and queue) or a single goal id. Returns ActionResult."""
    if not service.running(pth):
        return ActionResult(False, 1, "the sysop is not running: nothing to stop")
    ipc.request_stop(pth, goal_id)
    end = time.time() + wait
    while time.time() < end:
        if not os.path.exists(pth.stop_request):
            return ActionResult(True, 0, "stop taken (%s)" % (goal_id or "the running goal and the queue"))
        time.sleep(0.05)
    return ActionResult(False, 1, "stop requested, the service has not taken it yet")


def publish_goal(bus, text, source="cli", topic=None):
    """Publish a goal on the bus. Returns (goal_id, None) or raises BusError / ConfigError / ValueError."""
    text = text.strip()
    if not text:
        raise ValueError("no text")
    if len(text) > service.MAX_GOAL_TEXT:
        raise ValueError("%d characters, at most %d" % (len(text), service.MAX_GOAL_TEXT))
    rep = bus.pub(topic or config.goal_topic(), {"text": text}, source)
    return service.sanitize(rep.get("id"), ""), rep
