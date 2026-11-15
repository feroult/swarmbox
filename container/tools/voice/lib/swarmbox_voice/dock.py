"""Docking of the panel: where it goes in tmux, and opening, closing, moving and toggling it.

The panel (panel.py, `swarmbox-voice panel`) is a pane of the shared tmux session, so every client sees the same thing. It is opened
when a plan becomes pending (the service calls Dock.open) or by hand (the tmux key, `swarmbox-voice dock toggle`), and it closes
itself when the plan ends (the program exits and tmux removes the pane).

layout(cols, rows) is the one rule for where it docks (a pure function, tested alone):
  * portrait, `cols < CELL_FACTOR * rows` (cells are about twice as tall as wide, so a window that is taller than wide in pixels still has
    more columns than rows): a full-width pane at the bottom, 40 % of the height          -> split-window -f -v -l 40%
  * otherwise a pane at the right edge, 20 % of the width, at least 40 columns             -> split-window -f -h -l 20% (or -l 40)
  * but when that leaves the terminal fewer than 60 columns (the border counts one) the bottom layout is used.
The size is the size of the WINDOW, which follows the client that was active last (tmux's `window-size latest`, the default; the box's
tmux.conf does not change it). When the window changes shape (a phone rotates, a browser is resized, another client becomes the latest)
the tmux hook `window-resized` runs `swarmbox-voice dock redock`, which moves the same pane (the program in it keeps running) when the
layout kind changed. The hook is set while a panel exists and removes itself when the next resize finds none.

One panel at most: it is a pane with the pane option @swarmbox_voice_panel (and the marker argument in its start command), found by
those, never by position; every operation holds a file lock, and an extra panel found is killed. With several windows it opens in the
window the session shows (or the window the tmux key was pressed in); if the panel is in another window, opening MOVES it to this one.
Nothing here can fail a request: callers get DockError and log it.
"""
import fcntl
import os
import shlex
import sys
import tempfile
from collections import namedtuple

from .tmuxrun import PANEL_COMMAND, PANEL_MARK, PANEL_OPTION
from .tmuxrun import SEP as _SEP

CELL_FACTOR = 2
BOTTOM_PERCENT = 40
RIGHT_PERCENT = 20
MIN_PANEL_COLS = 40
MIN_TERMINAL_COLS = 60
HOOK = "window-resized[417]"
REDOCK_OPTION = "@swarmbox_voice_redock"

Layout = namedtuple("Layout", "kind size")   # kind: "bottom" | "right"; size: the value of -l ("40%", "20%" or a column count)


def layout(cols, rows):
    """Where the panel docks in a window of cols x rows cells. See the module docstring for the rule."""
    try:
        cols, rows = int(cols), int(rows)
    except (TypeError, ValueError):
        return Layout("bottom", "%d%%" % BOTTOM_PERCENT)
    bottom = Layout("bottom", "%d%%" % BOTTOM_PERCENT)
    if cols <= 0 or rows <= 0 or cols < CELL_FACTOR * rows:
        return bottom
    width = cols * RIGHT_PERCENT // 100          # what tmux makes of -l 20%
    size = "%d%%" % RIGHT_PERCENT
    if width < MIN_PANEL_COLS:
        width, size = MIN_PANEL_COLS, str(MIN_PANEL_COLS)
    if cols - width - 1 < MIN_TERMINAL_COLS:
        return bottom
    return Layout("right", size)


def split_args(lay):
    """The tmux flags of a layout: a full-size split, vertical for the bottom pane and horizontal for the right one."""
    return ["-f", "-v" if lay.kind == "bottom" else "-h", "-l", lay.size]


class DockError(RuntimeError):
    pass


Row = namedtuple("Row", "pane window win_active pane_active left top width height win_w win_h panel")


def _is_panel(mark, start):
    return mark == PANEL_MARK or PANEL_COMMAND in start


def shape_of(row):
    """The layout kind a panel pane has now, from its geometry: bottom (full width) or right (full height)."""
    if row.width >= row.win_w and row.height < row.win_h:
        return "bottom"
    if row.height >= row.win_h and row.width < row.win_w:
        return "right"
    return None   # alone in the window (or something else): nothing to fit


class Dock:
    """panel_argv: the command the panel pane runs. redock_argv: the command the hook runs (`... dock redock`, the socket is added)."""

    def __init__(self, tmux, session="main", panel_argv=None, redock_argv=None, lock_path=None):
        self.tmux, self.session = tmux, session
        self.panel_argv = list(panel_argv or [])
        self.redock_argv = list(redock_argv or [])
        # one lock per user, not per tmux argv: the service, the tmux key and the hook reach the same server in different ways (-L, -S, the default)
        self.lock_path = lock_path or os.path.join(tempfile.gettempdir(), "swarmbox-voice-dock-%d.lock" % os.getuid())

    # ---------------------------------------------------------------------------------------------------------------- tmux
    def _tm(self, *args, check=True):
        res = self.tmux.run(*args)
        if check and res.rc != 0:
            raise DockError((res.err.strip() or "tmux %s failed (rc %d)" % (args[0], res.rc))[:200])
        return res

    def _rows(self):
        fmt = _SEP.join(["#{pane_id}", "#{window_id}", "#{window_active}", "#{pane_active}", "#{pane_left}", "#{pane_top}", "#{pane_width}",
                         "#{pane_height}", "#{window_width}", "#{window_height}", "#{%s}" % PANEL_OPTION, "#{pane_start_command}"])
        res = self.tmux.run("list-panes", "-s", "-t", "=" + self.session, "-F", fmt)
        if res.rc != 0:
            raise DockError("the tmux session %r is not available" % self.session)
        rows = []
        for line in res.out.splitlines():
            p = line.split(_SEP)
            if len(p) != 12:
                continue
            try:
                nums = [int(x) for x in p[4:10]]
            except ValueError:
                continue
            rows.append(Row(p[0], p[1], p[2] == "1", p[3] == "1", *nums, _is_panel(p[10], p[11])))
        return rows

    def _lock(self):
        class _L:
            def __enter__(s):
                s.f = open(self.lock_path, "a")
                fcntl.flock(s.f, fcntl.LOCK_EX)

            def __exit__(s, *a):
                s.f.close()
        return _L()

    @staticmethod
    def _shown_window(rows):
        return next((r.window for r in rows if r.win_active), rows[0].window if rows else None)

    # ------------------------------------------------------------------------------------------------------------ operations
    def panels(self):
        return [r for r in self._rows() if r.panel]

    def open(self, window=None, focus=True):
        """Make the panel exist in `window` (default: the window the session shows), once, with the focus. Returns a word:
        created, moved, shown (already there)."""
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            if target is None or not any(r.window == target for r in rows):
                raise DockError("there is no window to dock in")
            panels = [r for r in rows if r.panel]
            keep = next((p for p in panels if p.window == target), panels[0] if panels else None)
            for p in panels:
                if p is not keep:
                    self._tm("kill-pane", "-t", p.pane, check=False)
            self._hook(True)
            if keep is None:
                self._create(target, rows)
                return "created"
            if keep.window != target:
                self._move(keep, target, rows, focus=True)
                return "moved"
            self._fit(keep, rows, focus=focus)
            if focus:
                self._tm("select-pane", "-t", keep.pane, check=False)
            return "shown"

    def close(self):
        """Kill every panel pane. The plan stays pending in the service (it expires, or the panel is opened again)."""
        with self._lock():
            n = 0
            for p in self.panels():
                self._tm("kill-pane", "-t", p.pane, check=False)
                n += 1
            self._hook(False)
            return n

    def toggle(self, window=None):
        """Closes the panel when it is in the window (the one given, else the one shown), else opens it there. Returns "closed" or what open returns."""
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            here = [r for r in rows if r.panel and r.window == target]
        if here:
            self.close()
            return "closed"
        return self.open(window=target)

    def redock(self):
        """The hook: when the panel's window changed shape so that another layout applies, move the panel there. Never takes the focus
        from a pane that has it. With no panel left the hook removes itself."""
        with self._lock():
            rows = self._rows()
            panels = [r for r in rows if r.panel]
            if not panels:
                self._hook(False)
                return "none"
            keep = panels[0]
            for p in panels[1:]:
                self._tm("kill-pane", "-t", p.pane, check=False)
            return "moved" if self._fit(keep, rows, focus=False) else "unchanged"

    # ---------------------------------------------------------------------------------------------------------------- pieces
    def _window_size(self, window, rows):
        r = next(r for r in rows if r.window == window)
        return r.win_w, r.win_h

    def _create(self, window, rows):
        if not self.panel_argv:
            raise DockError("no panel command is set")
        cols, lines = self._window_size(window, rows)
        res = self._tm("split-window", "-t", window, *split_args(layout(cols, lines)), "-P", "-F", "#{pane_id}", "--", *self.panel_argv)
        pane = res.out.strip()
        self._tm("set-option", "-p", "-t", pane, PANEL_OPTION, PANEL_MARK, check=False)
        self._tm("set-option", "-p", "-t", pane, "remain-on-exit", "off", check=False)

    def _anchor(self, window, rows):
        mine = [r for r in rows if r.window == window and not r.panel]
        return next((r for r in mine if r.pane_active), mine[0] if mine else None)

    def _move(self, panel, window, rows, focus):
        anchor = self._anchor(window, rows)
        if anchor is None:
            raise DockError("the window has no pane of its own to dock beside")
        cols, lines = self._window_size(window, rows)
        was_active = next((r.pane for r in rows if r.window == window and r.pane_active and not r.panel), None)
        self._tm("join-pane", *split_args(layout(cols, lines)), "-s", panel.pane, "-t", anchor.pane)
        if not focus and was_active:
            self._tm("select-pane", "-t", was_active, check=False)

    def _fit(self, panel, rows, focus):
        """Move the panel to the layout that applies now when its shape is the other one. True when it moved."""
        cols, lines = self._window_size(panel.window, rows)
        want = layout(cols, lines).kind
        have = shape_of(panel)
        if have is None or have == want:
            return False
        had_focus = panel.pane_active and panel.win_active
        self._move(panel, panel.window, rows, focus=focus or had_focus)
        if focus or had_focus:
            self._tm("select-pane", "-t", panel.pane, check=False)
        return True

    def _hook(self, on):
        if not on:
            self._tm("set-hook", "-gu", HOOK, check=False)
            self._tm("set-option", "-gu", REDOCK_OPTION, check=False)
            return
        if not self.redock_argv:
            return
        sock = self._tm("display-message", "-p", "#{socket_path}", check=False).out.strip()
        cmd = shlex.join(self.redock_argv + (["--socket", sock] if sock else []))
        self._tm("set-option", "-g", REDOCK_OPTION, cmd, check=False)
        self._tm("set-hook", "-g", HOOK, 'run-shell -b "#{%s}"' % REDOCK_OPTION, check=False)


def lib_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_dock(tmux, service_addr, session="main"):
    """A Dock whose panel and hook run this very library with the python that runs this process (no dependency on PATH)."""
    base = ["env", "PYTHONPATH=" + lib_dir() + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
            sys.executable, "-B", "-m", "swarmbox_voice"]
    return Dock(tmux, session, panel_argv=["env", PANEL_COMMAND] + base[1:] + ["panel", "--service", service_addr],
                redock_argv=base + ["dock", "redock", "--service", service_addr])
