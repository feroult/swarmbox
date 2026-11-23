"""UI host of the resident sysop service.

herdr is the only multiplexer of the box (`SWARMBOX_MUX`, default `herdr`): its UI is the Herdr Web Studio panel and the terminal cockpit, which read
state.py / actions.py themselves; `start_ui` only starts the OSC 7501 agent bridge (agent.HerdrBridge). `SWARMBOX_MUX=none` (or any other name)
runs headless.
"""
import os
import sys


def mux_name(env=None):
    e = os.environ if env is None else env
    return (e.get("SWARMBOX_MUX") or "herdr").strip() or "herdr"


class UiSession:
    """Lifecycle handle returned by start_ui()."""

    def __init__(self, on_shutdown=None):
        self._on_shutdown = on_shutdown

    def shutdown(self, unset=True):
        if self._on_shutdown is not None:
            self._on_shutdown(unset)


def start_ui(pth, cfg, log=None, enabled=True, mux=None):
    """Start the UI helpers for `serve`. Returns a UiSession whose shutdown() stops them cleanly."""
    if not enabled:
        return UiSession()
    name = mux if mux is not None else mux_name()
    if name == "herdr":
        from . import agent
        if log:
            log("sysop ui: starting herdr agent bridge")
        bridge = agent.HerdrBridge(pth, log=log).start()
        return UiSession(lambda unset=True: bridge.shutdown())
    if log and name != "none":
        log("sysop ui: no built-in UI for multiplexer %r; running headless" % (name,))
    return UiSession()


def notify(msg):
    """Feedback of a key command (veto, approve, stop) on stderr."""
    print("swarmbox-sysop: %s" % msg, file=sys.stderr)
