"""Docking of the panel of the sysop: where it goes in tmux, and when it is there.

The panel (panel.py, `swarmbox-sysop panel`) is a pane of the shared tmux session, so every client sees the same thing. WHEN it is there is the
setting `sysop.panel` (SWARMBOX_SYSOP_PANEL_MODE, config.py), which `swarmbox-sysop serve --dock` carries out (Follower):
  always (default)  the panel is up in EVERY window from the start of the box, in the idle state when there is no goal. It follows new windows
                    (the tmux hook after-new-window) and the windows that change shape (window-resized), and a slow tick (SYNC_TICK) catches whatever a
                    hook missed (a session that did not exist yet when the service started, a panel that crashed). The tmux key (`bind S`,
                    `swarmbox-sysop dock toggle`) and the key q of the panel HIDE it in all windows or show it again; the choice is a global option of
                    the tmux server (@swarmbox_sysop_hidden), so it is remembered until the next start of the box, and while hidden no hook makes one.
  auto              the panel opens (in the window you look at) when a goal arrives and closes a few seconds after the last goal; by hand with the key.
  off               the service never opens it. The key still opens one by hand, in the window you press it in.
A window never stays with only the panel in it (that is not a tab): when the last pane of the user in a window is gone (kill-pane, `exit`), the
hooks pane-exited and after-kill-pane run `dock sync`, which closes the window; this ends the session only when it was the last window, as it
does when the last shell of a box without panels exits.

layout(cols, rows) is the one rule for where it docks (a pure function, tested alone):
  * portrait, `cols < CELL_FACTOR * rows` (cells are about twice as tall as wide, so a window that is taller than wide in pixels still has
    more columns than rows): a full-width pane at the bottom, 30 % of the height, at least 8 lines (never more than half of the window)
                                                                                              -> split-window -f -v -l 30% (or -l 8)
  * otherwise a pane at the right edge, 20 % of the width, at least 40 columns             -> split-window -f -h -l 20% (or -l 40)
  * but when that leaves the terminal fewer than 60 columns (the border counts one) the bottom layout is used.
The size is the size of the WINDOW (tmux's `window-size latest`, the default). When a window changes shape (a phone rotates, a browser is resized)
the tmux hook `window-resized` runs `swarmbox-sysop dock redock --window #{hook_window}`, which fits ONLY that window: the same pane moves (the
program in it keeps running) when the layout kind changed. A redock never takes the focus: the pane that had it in that window has it after.
In the modes auto and off the hook is set while a panel exists and removes itself when the next resize finds no panel in any window.

One panel PER WINDOW: a pane with the pane option @swarmbox_sysop_panel (and the marker argument SWARMBOX_SYSOP_PANEL=1 in its start command, for the
instant before the option is set), found by those, never by position. swarmbox-tabs hides these panes from the tabs. Never two in one window (an
extra one found is killed); panels of other windows are never touched by an operation on this one. Every operation holds a file lock.
A panel opened by the Follower in the mode auto also carries @swarmbox_sysop_auto=1: only those are closed when the goal ends; one opened by hand stays.
The name of the tab. tmux names a window after the command of its ACTIVE pane. The panel never takes the focus by itself, so in the mode always the
names follow the program of your pane as they always did (a click on the panel makes the name `python3` until the focus is back). In the other modes the
panel's window gets `automatic-rename off` before the panel is created and gets back what it had (on, off, or "inherited") when no panel is left in it:
`close`, the quit key of the panel (thaw_own_window) and, for a panel that was killed some other way, the next open or close of any window (_heal).
The value to go back to is kept in the window option @swarmbox_sysop_ar.
Nothing here can fail a request: callers get DockError and log it.
"""
import fcntl
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import namedtuple

from . import ipc

PANEL_OPTION = "@swarmbox_sysop_panel"
AUTO_OPTION = "@swarmbox_sysop_auto"
PANEL_MARK = "1"
PANEL_COMMAND = "SWARMBOX_SYSOP_PANEL=1"
HOOK = "window-resized[418]"           # voice has [417]: both can be set
SYNC_HOOKS = ("after-new-window[418]", "pane-exited[418]", "after-kill-pane[418]")   # mode always: `dock sync`
REDOCK_OPTION = "@swarmbox_sysop_redock"
SYNC_OPTION = "@swarmbox_sysop_sync"   # global option: the command the sync hooks run
HIDDEN_OPTION = "@swarmbox_sysop_hidden"   # global option of the tmux server: "1" while the panels are hidden by hand (mode always)
BORN_OPTION = "@swarmbox_sysop_born"   # window option: when (epoch seconds) a panel was last made in the window; see REMAKE_AFTER
REMAKE_AFTER = 2.0                     # a panel that is missing is not made again within this time of the last one: a panel that crashes at its start would else be made
                                       # again by the hook of its own exit, at the speed of a process start. The slow tick of the Follower makes it later.
AR_OPTION = "@swarmbox_sysop_ar"       # window option: what `automatic-rename` was on the window before the panel froze the tab's name (see Dock._freeze_name)
SEP = "@@sb@@"                         # not a tab: tmux 3.6 and later prints control characters of a list as `_` when it has no terminal

CELL_FACTOR = 2
BOTTOM_PERCENT = 30
MIN_BOTTOM_ROWS = 8
RIGHT_PERCENT = 20
MIN_PANEL_COLS = 40
MIN_TERMINAL_COLS = 60
SYNC_TICK = 4.0                         # seconds between two looks of the Follower in the mode always (a hook does the quick part)
ACTIONS = ("open", "close", "toggle", "redock", "sync")
PASS_ENV = ("SWARMBOX_SYSOP_PANEL_MODE", "SB_TABS_SESSION", "SB_TABS_SOCKET", "SB_TABS_BIN", "SB_RUN_DIR", "SB_STATE_DIR", "SB_BUS_SOCKET", "XDG_STATE_HOME", "HOME", "NO_COLOR", "LANG", "LC_ALL", "TERM")

Layout = namedtuple("Layout", "kind size")   # kind: "bottom" | "right"; size: the value of -l ("40%", "20%" or a column count)
Result = namedtuple("Result", "rc out err")


def layout(cols, rows):
    """Where the panel docks in a window of cols x rows cells. See the module docstring for the rule."""
    bottom = Layout("bottom", "%d%%" % BOTTOM_PERCENT)
    try:
        cols, rows = int(cols), int(rows)
    except (TypeError, ValueError):
        return bottom
    if cols <= 0 or rows <= 0:
        return bottom
    if rows * BOTTOM_PERCENT // 100 < MIN_BOTTOM_ROWS:      # a short window: 8 lines are the least that is useful, but never more than half of it
        bottom = Layout("bottom", str(max(1, min(MIN_BOTTOM_ROWS, rows // 2))))
    if cols < CELL_FACTOR * rows:
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


class Tmux:
    """argv is the command prefix. Default: the words of SWARMBOX_TEST_TMUX, else `tmux` with `-L SB_TABS_SOCKET` when that is set (the same
    server as swarmbox-tabs). `run` never raises: a missing binary is rc 127, a timeout rc 124. TMUX is removed from the environment."""

    def __init__(self, argv=None, env=None, timeout=5.0):
        if argv is None:
            argv = shlex.split(os.environ.get("SWARMBOX_TEST_TMUX", ""))
        if not argv:
            argv = [os.environ.get("SB_TABS_BIN") or "tmux"]
            if os.environ.get("SB_TABS_SOCKET"):
                argv += ["-L", os.environ["SB_TABS_SOCKET"]]
        self.argv = list(argv)
        base = dict(os.environ if env is None else env)
        base.pop("TMUX", None)
        self.env, self.timeout = base, timeout

    def run(self, *args):
        try:
            p = subprocess.run(self.argv + [str(a) for a in args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=self.env, timeout=self.timeout)
        except FileNotFoundError:
            return Result(127, "", "tmux not found")
        except subprocess.TimeoutExpired:
            return Result(124, "", "tmux timed out")
        except OSError as e:
            return Result(126, "", str(e))
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


Row = namedtuple("Row", "pane window win_active pane_active left top width height win_w win_h panel auto")


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
    """panel_argv: the command the panel pane runs. redock_argv: the command the hook runs (`... dock redock`; `--socket` and `--window` are added)."""

    def __init__(self, tmux, session="main", panel_argv=None, redock_argv=None, lock_path=None, mode="auto", sync_argv=None):
        self.tmux, self.session = tmux, session
        self.mode = mode                      # always | auto | off, see the module docstring (the default keeps the old behaviour)
        self.sync_argv = list(sync_argv or [])
        self.panel_argv = list(panel_argv or [])
        self.redock_argv = list(redock_argv or [])
        # one lock per user: the service, the tmux key and the hook reach the same server in different ways (-L, -S, the default)
        self.lock_path = lock_path or os.path.join(tempfile.gettempdir(), "swarmbox-sysop-dock-%d.lock" % os.getuid())

    # ---------------------------------------------------------------------------------------------------------------- tmux
    def _tm(self, *args, check=True):
        res = self.tmux.run(*args)
        if check and res.rc != 0:
            raise DockError((res.err.strip() or "tmux %s failed (rc %d)" % (args[0], res.rc))[:200])
        return res

    def _rows(self):
        fmt = SEP.join(["#{pane_id}", "#{window_id}", "#{window_active}", "#{pane_active}", "#{pane_left}", "#{pane_top}", "#{pane_width}",
                        "#{pane_height}", "#{window_width}", "#{window_height}", "#{%s}" % PANEL_OPTION, "#{pane_start_command}", "#{%s}" % AUTO_OPTION])
        res = self.tmux.run("list-panes", "-s", "-t", "=" + self.session, "-F", fmt)
        if res.rc != 0:
            raise DockError("the tmux session %r is not available" % self.session)
        rows = []
        for line in res.out.splitlines():
            p = line.split(SEP)
            if len(p) != 13:
                continue
            try:
                nums = [int(x) for x in p[4:10]]
            except ValueError:
                continue
            rows.append(Row(p[0], p[1], p[2] == "1", p[3] == "1", *nums, _is_panel(p[10], p[11]), p[12] == "1"))
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

    def open(self, window=None, focus=True, auto=False):
        """Make the panel exist in `window` (default: the window the session shows), once. Panels of other windows are left alone.
        `focus`: the panel gets the focus when it is created (keys are for it); an existing panel gets it only when `focus` and not `auto`.
        The Follower and `swarmbox-sysop approve` open with focus=False: the panel never takes the focus on its own (see focus() and keys.py).
        Returns a word: created, shown (already there)."""
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            if target is None or not any(r.window == target for r in rows):
                raise DockError("there is no window to dock in")
            here = [r for r in rows if r.panel and r.window == target]
            for p in here[1:]:
                self._tm("kill-pane", "-t", p.pane, check=False)
            self._heal(rows)
            self._hook(True)
            if not here:
                self._create(target, rows, focus, auto)
                return "created"
            if focus and not auto:
                self._fit(here[0], rows, focus=True)
                self._tm("select-pane", "-t", here[0].pane, check=False)
            return "shown"

    def close(self, window=None, only_auto=False):
        """Kill the panels of `window` (default: all windows; only_auto: only the ones the Follower opened). The goal goes on in the service.
        Returns how many. The hook is removed when no panel is left anywhere."""
        with self._lock():
            n = 0
            own = os.environ.get("TMUX_PANE")       # called from a panel: its own pane goes last, killing it ends this process
            for p in sorted(self.panels(), key=lambda r: r.pane == own):
                if (window is None or p.window == window) and (p.auto or not only_auto):
                    self._tm("kill-pane", "-t", p.pane, check=False)
                    n += 1
            rows = self._rows()
            self._heal(rows)
            if not any(r.panel for r in rows):
                self._hook(False)
            return n

    def focus(self, window=None):
        """Give the focus to the panel of `window` (default: the window the session shows). Only the keys `swarmbox-sysop approve` and a click do
        this: nothing else in the sysop selects the panel. Returns its pane id."""
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            here = [r for r in rows if r.panel and r.window == target]
            if not here:
                raise DockError("there is no panel in this window")
            self._tm("select-pane", "-t", here[0].pane)
            return here[0].pane

    def panel_pane(self, window=None):
        """The pane id of the panel of `window` (default: the window the session shows), or None."""
        rows = self._rows()
        target = window or self._shown_window(rows)
        return next((r.pane for r in rows if r.panel and r.window == target), None)

    def toggle(self, window=None):
        """Mode always: hide the panels of ALL windows, or show them again (the choice is remembered by the tmux server): "closed" or "shown". Other
        modes: closes the panel of the window (the one given, else the one shown) when there is one, else opens it there: "closed" or what open returns."""
        if self.mode == "always":
            if self.hidden():
                self.set_hidden(False)
                self.sync(force=True)
                return "shown"
            self.hide()
            return "closed"
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            here = [r for r in rows if r.panel and r.window == target]
        if here:
            self.close(window=target)
            return "closed"
        return self.open(window=target)

    def hidden(self):
        return self.tmux.run("show-options", "-gqv", HIDDEN_OPTION).out.strip() == "1"

    def set_hidden(self, on):
        self._tm("set-option", "-g", HIDDEN_OPTION, "1") if on else self._tm("set-option", "-gu", HIDDEN_OPTION, check=False)

    def hide(self):
        """Mode always: the panels go away in every window and no hook brings them back until `toggle` (or the next start of the box). Returns how many closed."""
        self.set_hidden(True)
        return self.close()

    def sync(self, window=None, force=False):
        """The one operation of the mode always (the hooks, the slow tick and `dock sync` run it): (1) close the windows that hold only a panel,
        (2) unless the panels are hidden, make a panel exist in every window (in `window` only, when one is given) and fit every panel to its window.
        Never takes the focus. `force`: also make a panel that was made a moment ago (the key that shows them again). In the other modes only (1) is done. Returns a word: "closed N windows", "created N", "unchanged" or "hidden"."""
        with self._lock():
            rows = self._rows()
            if not rows:
                return "unchanged"
            note = []
            only = self._panel_only_windows(rows)
            if only:
                time.sleep(0.15)                  # the pane of the user may be in the middle of a join or a respawn: look again before closing anything
                rows = self._rows()
                only = [w for w in self._panel_only_windows(rows) if w in only]
                for w in only:
                    self._tm("kill-window", "-t", w, check=False)
                if only:
                    note.append("closed %d windows" % len(only))
                    rows = [r for r in self._rows()]
            if self.mode != "always":
                return ", ".join(note) or "unchanged"
            self._hook(True)
            if self.hidden():
                return ", ".join(note + ["hidden"])
            made = 0
            for win in dict.fromkeys(r.window for r in rows):
                if window is not None and win != window:
                    continue
                here = [r for r in rows if r.panel and r.window == win]
                for extra in here[1:]:
                    self._tm("kill-pane", "-t", extra.pane, check=False)
                if not here:
                    if not any(not r.panel for r in rows if r.window == win):
                        continue
                    if not force and self._born_lately(win):
                        continue
                    try:
                        self._create(win, rows, False, False)
                        made += 1
                    except DockError:
                        pass
                else:
                    try:
                        self._fit(here[0], rows, focus=False)
                    except DockError:
                        pass
            if made:
                note.append("created %d" % made)
            return ", ".join(note) or "unchanged"

    def _born_lately(self, window):
        try:
            born = float(self.tmux.run("show-options", "-wqv", "-t", window, BORN_OPTION).out.strip() or 0)
        except ValueError:
            return False
        return 0 <= time.time() - born < REMAKE_AFTER

    @staticmethod
    def _panel_only_windows(rows):
        wins = list(dict.fromkeys(r.window for r in rows))
        return [w for w in wins if all(r.panel for r in rows if r.window == w)]

    def redock(self, window=None):
        """The hook: when the window's shape changed so that another layout applies, move ITS panel there (all windows when none is given). Never
        takes the focus from the pane that has it. With no panel left anywhere the hook removes itself.

        COALESCED. The hook runs once per resize event and a browser that is being dragged makes dozens a second: each run is a Python start (about 30 ms and
        20 MiB), and they used to queue up on the lock (105 at once in the soak test). Now a run leaves a mark for its window, and the one run that gets the
        redock lock does the work for every mark, again until there is none; a run that finds the lock taken ends at once, because the one that holds it will
        see its mark. The lock is let go BEFORE the last look for marks, so a mark that came in between is not left alone."""
        mark = "%s.redock.%s" % (self.lock_path, window or "all")
        try:
            os.close(os.open(mark, os.O_WRONLY | os.O_CREAT, 0o600))
        except OSError:
            return self._redock_now(window)                       # no room for a mark: the old way, one after the other
        gate = os.open(self.lock_path + ".redock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        out = "queued"
        try:
            while True:
                try:
                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return out                                     # someone is redocking: it will take our mark
                marks = self._redock_marks()
                while marks:
                    for m in marks:
                        try:
                            os.unlink("%s.redock.%s" % (self.lock_path, m))
                        except OSError:
                            pass
                    out = self._redock_now(None) if "all" in marks else self._redock_many(sorted(marks))
                    marks = self._redock_marks()
                fcntl.flock(gate, fcntl.LOCK_UN)
                if not self._redock_marks():
                    return out
        finally:
            os.close(gate)

    def _redock_marks(self):
        """the windows that asked for a redock and were not served yet ("all" for every window)"""
        d, base = os.path.split(self.lock_path + ".redock.")
        try:
            return [n[len(base):] for n in os.listdir(d or ".") if n.startswith(base)]
        except OSError:
            return []

    def _redock_many(self, windows):
        out = "unchanged"
        for w in windows:
            if self._redock_now(w) == "moved":
                out = "moved"
        return out

    def _redock_now(self, window=None):
        with self._lock():
            rows = self._rows()
            panels = [r for r in rows if r.panel]
            if not panels:
                self._hook(False)
                return "none"
            moved = False
            for win in sorted({p.window for p in panels}):
                if window is not None and win != window:
                    continue
                here = [p for p in panels if p.window == win]
                for p in here[1:]:
                    self._tm("kill-pane", "-t", p.pane, check=False)
                moved = self._fit(here[0], rows, focus=False) or moved
            return "moved" if moved else "unchanged"

    # ---------------------------------------------------------------------------------------------------------------- pieces
    @staticmethod
    def _window_size(window, rows):
        r = next(r for r in rows if r.window == window)
        return r.win_w, r.win_h

    def _create(self, window, rows, focus, auto):
        if not self.panel_argv:
            raise DockError("no panel command is set")
        cols, lines = self._window_size(window, rows)
        flags = [] if focus else ["-d"]
        if self.mode != "always":
            self._freeze_name(window)
        try:
            res = self._tm("split-window", "-t", window, *flags, *split_args(layout(cols, lines)), "-P", "-F", "#{pane_id}", "--", *self.panel_argv)
        except DockError:
            if self.mode != "always":
                self._thaw_name(window)
            raise
        pane = res.out.strip()
        if self.mode == "always":
            self._tm("set-option", "-w", "-t", window, BORN_OPTION, "%.3f" % time.time(), check=False)
        self._tm("set-option", "-p", "-t", pane, PANEL_OPTION, PANEL_MARK, check=False)
        if auto:
            self._tm("set-option", "-p", "-t", pane, AUTO_OPTION, "1", check=False)
        self._tm("set-option", "-p", "-t", pane, "remain-on-exit", "off", check=False)

    def _fit(self, panel, rows, focus):
        """Move the panel to the layout that applies now when its shape is the other one. True when it moved. The pane that was active in the
        window (the panel included) is active after, unless `focus` gives the focus to the panel."""
        cols, lines = self._window_size(panel.window, rows)
        want = layout(cols, lines).kind
        have = shape_of(panel)
        if have is None:
            return False
        if have == want:
            return self._resize(panel, layout(cols, lines), cols, lines)
        anchor = next((r for r in rows if r.window == panel.window and not r.panel and r.pane_active), None) or \
            next((r for r in rows if r.window == panel.window and not r.panel), None)
        if anchor is None:
            raise DockError("the window has no pane of its own to dock beside")
        active = next((r.pane for r in rows if r.window == panel.window and r.pane_active), None)
        self._tm("join-pane", "-d", *split_args(layout(cols, lines)), "-s", panel.pane, "-t", anchor.pane)
        keep = panel.pane if focus else active
        if keep:
            self._tm("select-pane", "-t", keep, check=False)
        return True

    def _resize(self, panel, lay, cols, lines):
        """The window changed size but not layout kind: tmux shrinks or stretches the panes in proportion, and a window that gets much shorter can leave the
        panel one line high. Put it back to the size the layout says (a difference of one cell is rounding). True when it was resized."""
        whole = lines if lay.kind == "bottom" else cols
        cells = whole * int(lay.size[:-1]) // 100 if lay.size.endswith("%") else int(lay.size)
        have = panel.height if lay.kind == "bottom" else panel.width
        if abs(have - cells) <= 1:
            return False
        self._tm("resize-pane", "-t", panel.pane, "-y" if lay.kind == "bottom" else "-x", str(cells), check=False)
        return True

    def _freeze_name(self, window):
        """Stop tmux from renaming the window after the panel (see the module docstring). Idempotent: a window already frozen keeps the first value."""
        if self._tm("show-options", "-wqv", "-t", window, AR_OPTION, check=False).out.strip():
            return
        cur = self._tm("show-options", "-w", "-t", window, "automatic-rename", check=False).out.split()     # empty when the window inherits it
        self._tm("set-option", "-w", "-t", window, AR_OPTION, cur[-1] if len(cur) == 2 else "unset", check=False)
        self._tm("set-option", "-w", "-t", window, "automatic-rename", "off", check=False)

    def _thaw_name(self, window):
        prev = self._tm("show-options", "-wqv", "-t", window, AR_OPTION, check=False).out.strip()
        if not prev:
            return
        if prev == "unset":
            self._tm("set-option", "-wu", "-t", window, "automatic-rename", check=False)
        else:
            self._tm("set-option", "-w", "-t", window, "automatic-rename", prev, check=False)
        self._tm("set-option", "-wu", "-t", window, AR_OPTION, check=False)

    def _heal(self, rows):
        """Windows that were frozen and have no panel any more (it was killed by hand, or crashed): give them their automatic names back."""
        res = self.tmux.run("list-windows", "-t", "=" + self.session, "-F", "#{window_id}" + SEP + "#{%s}" % AR_OPTION)
        if res.rc != 0:
            return
        with_panel = {r.window for r in rows if r.panel}
        for line in res.out.splitlines():
            wid, _, mark = line.partition(SEP)
            if mark and wid not in with_panel:
                self._thaw_name(wid)

    def forget_sync(self):
        """Take away the hooks of the mode always. The service calls it when it starts in auto or off in a tmux server that an earlier always had
        set them in (the service restarted with another SWARMBOX_SYSOP_PANEL_MODE while the box stayed up): the hooks run `dock sync` with the
        mode they were made with, so without this a new window would still get a panel in a box that said auto or off. Never in the mode always."""
        if self.mode == "always":
            return
        for h in SYNC_HOOKS:
            self._tm("set-hook", "-gu", h, check=False)
        self._tm("set-option", "-gu", SYNC_OPTION, check=False)

    def _hook(self, on):
        if not on:
            if self.mode == "always":
                return                   # the hooks stay: the panels come back with `toggle`, and new windows need them
            self._tm("set-hook", "-gu", HOOK, check=False)
            self._tm("set-option", "-gu", REDOCK_OPTION, check=False)
            return
        if not self.redock_argv:
            return
        res = self.tmux.run("display-message", "-p", SEP.join(["#{socket_path}", "#{%s}" % SYNC_OPTION, "#{%s}" % REDOCK_OPTION]))
        sock, have_sync, have_redock = (res.out.rstrip("\n").split(SEP) + ["", "", ""])[:3]
        cmd = shlex.join(self.redock_argv + (["--socket", sock] if sock else []))
        sync_on = self.mode == "always" and bool(self.sync_argv)
        sync = shlex.join(self.sync_argv + (["--socket", sock] if sock else [])) if sync_on else ""
        if have_redock == cmd and have_sync == sync:
            return                       # already set: the Follower asks at every look
        if sync_on:
            self._tm("set-option", "-g", SYNC_OPTION, sync, check=False)
            for h in SYNC_HOOKS:
                self._tm("set-hook", "-g", h, 'run-shell -b "#{%s} >/dev/null 2>&1 || true"' % SYNC_OPTION, check=False)
        self._tm("set-option", "-g", REDOCK_OPTION, cmd, check=False)
        self._tm("set-hook", "-g", HOOK, 'run-shell -b "#{%s} --window #{hook_window} >/dev/null 2>&1 || true"' % REDOCK_OPTION, check=False)


def thaw_own_window():
    """Called by the panel when it quits by itself (the `q` key): the window it was in gets its automatic name back. Never raises, does nothing
    outside tmux. The server is the one the pane runs in ($TMUX), so it needs no other setting."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return
    try:
        sock = os.environ.get("TMUX", "").split(",")[0]
        t = Tmux(argv=["tmux", "-S", sock]) if sock else Tmux()
        win = t.run("display-message", "-p", "-t", pane, "#{window_id}").out.strip()
        if re.fullmatch(r"@[0-9]{1,9}", win):
            Dock(t)._thaw_name(win)
    except Exception:
        pass


def lib_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_dock(tmux=None, session=None, mode=None):
    """A Dock whose panel and hooks run this very library with the python that runs this process (no dependency on PATH). The folders of the
    service (SB_RUN_DIR and the others of PASS_ENV that are set) are handed on, so the panel reads the same files as the service. `mode`: the
    setting sysop.panel (default: SWARMBOX_SYSOP_PANEL_MODE of the environment; a wrong value counts as always, the service refuses it at start)."""
    from . import config
    if mode is None:
        try:
            mode = config.panel_mode()
        except config.ConfigError:
            mode = "always"
    have = [x for x in os.environ.get("PYTHONPATH", "").split(os.pathsep) if x]
    env = ["PYTHONPATH=" + os.pathsep.join(([] if lib_dir() in have else [lib_dir()]) + have)]      # not once more at each generation of hook and panel
    env += ["%s=%s" % (k, os.environ[k]) for k in PASS_ENV if os.environ.get(k)]
    base = ["env"] + env + [sys.executable, "-B", "-m", "swarmbox_sysop"]
    return Dock(tmux or Tmux(), session or os.environ.get("SB_TABS_SESSION") or "main",
                panel_argv=["env", PANEL_COMMAND] + base[1:] + ["panel"], redock_argv=base + ["dock", "redock"], mode=mode,
                sync_argv=base + ["dock", "sync"])


def run(action, socket=None, window=None):
    """`swarmbox-sysop dock ACTION`: the tmux key and the hooks call this. Exit code 0, 1 (a DockError, said on stderr), 2 (bad window id)."""
    if action not in ACTIONS:
        print("swarmbox-sysop: dock: unknown action %r" % action, file=sys.stderr)
        return 2
    if window is not None and not re.fullmatch(r"@[0-9]{1,9}", window):
        print("swarmbox-sysop: dock: --window must be a tmux window id such as @3", file=sys.stderr)
        return 2
    d = default_dock(Tmux(argv=["tmux", "-S", socket]) if socket else Tmux())
    try:
        if action == "open":
            out = d.open(window=window)
        elif action == "close":
            out = "closed %d" % d.close(window=window)
        elif action == "toggle":
            out = d.toggle(window=window)
        elif action == "sync":
            out = d.sync(window=window)
        else:
            out = d.redock(window=window)
    except DockError as e:
        print("swarmbox-sysop: dock: %s" % e, file=sys.stderr)
        return 1
    if action not in ("redock", "sync"):
        print("swarmbox-sysop: panel %s" % out, file=sys.stderr)
    return 0


def panel_quit():
    """Called by the panel when its quit key `q` was pressed (not when it is killed). Mode always: the panels of ALL windows are hidden, and stay
    hidden until the key shows them or the box starts again. Other modes: the window gets its automatic name back. Never raises."""
    from . import config
    try:
        mode = config.panel_mode()
    except config.ConfigError:
        mode = "always"
    if mode != "always":
        thaw_own_window()
        return
    for sg in (signal.SIGHUP, signal.SIGTERM):       # closing the panels kills this pane too: finish the job of the other windows first
        signal.signal(sg, signal.SIG_IGN)
    try:
        sock = os.environ.get("TMUX", "").split(",")[0]
        t = Tmux(argv=["tmux", "-S", sock]) if sock else Tmux()
        default_dock(t, mode=mode).hide()
    except Exception:
        pass


class Follower:
    """What `swarmbox-sysop serve --dock` does for the setting sysop.panel (`mode`). Everything it does is a Dock operation; it never takes the focus.
      always  every SYNC_TICK seconds `dock.sync()`: the panel exists in every window (the hooks do the quick part), unless it is hidden by hand.
      auto    opens the panel (WITHOUT the focus) when a goal arrives and closes it (the ones it opened) `grace` seconds after the last goal and the
              queue ended. It reads status.json of the service (the files of ipc.py), nothing else, and only when the file changed (a stat per look).
              Once per goal: a panel the user closed with `q` is not opened again for the same run of goals.
      off     does nothing (but, once at its start, takes away the hooks of an earlier always, like auto).
    A tmux that is missing or has no session is not an error here: it is tried again at the next look (and said once in the log, not at every look)."""

    def __init__(self, pth, dock=None, interval=0.5, grace=3.0, clock=time.monotonic, log=None, mode="auto", tick=SYNC_TICK):
        self.paths, self.dock, self.mode = pth, dock, mode
        self.interval, self.grace, self.clock, self.tick = interval, grace, clock, tick
        self.log = log or (lambda msg: None)
        self.busy, self.idle_since = False, None
        self.stop = threading.Event()
        self.thread = None
        self._status = None             # the stat signature and the content of status.json at the last look
        self._said = None               # the last message sent to the log

    def _read_status(self):
        try:
            stt = os.stat(self.paths.status)
            sig = (stt.st_ino, stt.st_mtime_ns, stt.st_size)
        except OSError:
            sig = None
        if self._status is None or self._status[0] != sig:
            st = ipc.read_json(self.paths.status) if sig else None
            self._status = (sig, st if isinstance(st, dict) else {})
        return self._status[1]

    def step(self):
        if self.mode == "off":
            return
        if self.mode == "always":
            self._do(lambda d: d.sync(), "sync")
            return
        now = self.clock()
        st = self._read_status()
        busy = bool(st.get("current")) or bool(st.get("queue"))
        if busy:
            self.idle_since = None
            if not self.busy:
                self.busy = True
                self._do(lambda d: d.open(auto=True, focus=False), "open")      # never the focus: what you type in your tab must not reach the panel
        elif self.busy:
            if self.idle_since is None:
                self.idle_since = now
            if now - self.idle_since >= self.grace:
                self.busy, self.idle_since = False, None
                self._do(lambda d: d.close(only_auto=True), "close")

    def _do(self, fn, what):
        try:
            if self.dock is None:
                self.dock = default_dock(mode=self.mode)
            fn(self.dock)
            self._said = None
        except DockError as e:
            self._say("panel %s: %s" % (what, e))
        except Exception as e:               # nothing here may take the service down
            self._say("panel %s: %r" % (what, e))

    def _say(self, msg):
        if msg != self._said:                # the same trouble at every look would fill the log
            self._said = msg
            self.log(msg)

    def loop(self):
        if self.mode == "always":
            self.step()                      # at once: the box may already have its windows
        else:
            self._do(lambda d: d.forget_sync(), "unhook")       # the hooks of an earlier always are not wanted in auto or off
        if self.mode == "off":
            return                           # nothing else to do in off: the thread ends
        while not self.stop.wait(self.tick if self.mode == "always" else self.interval):
            self.step()

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="sysop-dock", daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        self.stop.set()
