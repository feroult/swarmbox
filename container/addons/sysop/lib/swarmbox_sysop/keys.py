"""The keys of the sysop that work from ANY tab: `swarmbox-sysop veto | approve | stop | goal` called by the tmux keys of
container/config/tmux.conf: Ctrl+A then V / X / a / g.

Pure decision logic lives in actions.py; this module adds terminal prompt input and optional tmux client status messages.
"""
import sys

from . import actions, busclient, config, service

ACK_SECONDS = 3.0

pending_of = actions.pending_of
_live = actions.is_live


def _say(msg, tmux=None, client=""):
    """To stderr (tmux shows nothing of a background run-shell) and, when the key gave a client, in that client's status line."""
    print("swarmbox-sysop: %s" % msg, file=sys.stderr)
    if tmux is not None and client:
        tmux.run("display-message", "-c", client, "sysop: " + msg)


def veto(pth, tmux=None, client=""):
    """The key c. Exit code 0 when a decision was written, 1 when nothing waits."""
    res = actions.veto(pth, by="key")
    _say(res.message, tmux, client)
    return res.rc


def approve(pth, dk=None, window=None, tmux=None, client="", wait=0):
    """The key a (and the Allow button of the web strip): allow what waits. Exit code 0 when a decision was written, 1 when nothing waits."""
    res = actions.approve(pth, by="key")
    _say(res.message, tmux, client)
    return res.rc


def prompt(bus, source="panel", inp=None, out=None, topic=None):
    """The key g, run by tmux in a popup: ask for a goal on one line and publish it. Exit codes as `swarmbox-sysop goal`."""
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
        actions.publish_goal(bus, text, source=source, topic=topic)
    except (busclient.BusError, config.ConfigError) as e:
        out.write("the goal was not sent: %s. Press Enter." % busclient.words(e))
        out.flush()
        inp.readline()
        return 3
    return 0
