"""Mux-selectable UI host for the resident sysop service and key feedback.

When SWARMBOX_MUX is `tmux` (the default) and docking is enabled, `start_ui` starts dock.Follower and line.Toaster.
When SWARMBOX_MUX is `none` (or another headless backend that drives its own UI from state.py / actions.py), `start_ui`
never imports or invokes tmux.
"""
import os
import sys


def mux_name(env=None):
    e = os.environ if env is None else env
    return (e.get("SWARMBOX_MUX") or "tmux").strip() or "tmux"


class UiSession:
    """Lifecycle handle returned by start_ui()."""

    def __init__(self, on_shutdown=None):
        self._on_shutdown = on_shutdown

    def shutdown(self, unset=True):
        if self._on_shutdown is not None:
            self._on_shutdown(unset)


def start_ui(pth, cfg, log=None, enabled=True, mux=None):
    """Start the multiplexer-specific UI helpers for `serve`. Returns a UiSession whose shutdown() stops them cleanly."""
    if not enabled:
        return UiSession()
    name = mux if mux is not None else mux_name()
    if name == "none":
        return UiSession()
    if name == "tmux":
        from . import dock, line
        follower = dock.Follower(pth, log=log, mode=cfg.panel_mode).start()
        toaster = line.Toaster(pth, log=log).start()

        def _stop(unset=True):
            follower.shutdown()
            toaster.shutdown(unset=unset)

        return UiSession(_stop)
    if log:
        log("sysop ui: no built-in dock for multiplexer %r; running headless" % (name,))
    return UiSession()


def notify(msg, socket="", client="", mux=None):
    """Print feedback to stderr and, when running under tmux with a client name, show it in that client's status line."""
    print("swarmbox-sysop: %s" % msg, file=sys.stderr)
    name = mux if mux is not None else mux_name()
    if name == "tmux" and client:
        from . import dock
        tm = dock.Tmux(argv=["tmux", "-S", socket]) if socket else dock.Tmux()
        tm.run("display-message", "-c", client, "sysop: " + msg)


def run_panel():
    """Run the terminal panel UI."""
    from . import panel
    return panel.run()


def run_dock(action, socket="", window=None):
    """Run a tmux dock subcommand (`open`, `close`, `toggle`, `redock`, `sync`)."""
    from . import dock
    return dock.run(action, socket, window)
