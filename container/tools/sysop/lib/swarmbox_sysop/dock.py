"""Docking of the panel of the sysop: where it goes in tmux, and opening, closing, moving and toggling it.

The panel (panel.py, `swarmbox-sysop panel`) is a pane of the shared tmux session, so every client sees the same thing. It opens by itself when a
goal arrives and closes a few seconds after the goal ends (Follower, started by `swarmbox-sysop serve`), and by hand with the tmux key
(`bind S` in container/config/tmux.conf, `swarmbox-sysop dock toggle`).

layout(cols, rows) is the one rule for where it docks (a pure function, tested alone):
  * portrait, `cols < CELL_FACTOR * rows` (cells are about twice as tall as wide, so a window that is taller than wide in pixels still has
    more columns than rows): a full-width pane at the bottom, 40 % of the height          -> split-window -f -v -l 40%
  * otherwise a pane at the right edge, 20 % of the width, at least 40 columns             -> split-window -f -h -l 20% (or -l 40)
  * but when that leaves the terminal fewer than 60 columns (the border counts one) the bottom layout is used.
The size is the size of the WINDOW (tmux's `window-size latest`, the default). When a window changes shape (a phone rotates, a browser is resized)
the tmux hook `window-resized` runs `swarmbox-sysop dock redock --window #{hook_window}`, which fits ONLY that window: the same pane moves (the
program in it keeps running) when the layout kind changed. A redock never takes the focus: the pane that had it in that window has it after.
The hook is set while a panel exists and removes itself when the next resize finds no panel in any window.

One panel PER WINDOW: a pane with the pane option @swarmbox_sysop_panel (and the marker argument SWARMBOX_SYSOP_PANEL=1 in its start command, for the
instant before the option is set), found by those, never by position. The bus driver hides these panes from the tabs. Never two in one window (an
extra one found is killed); panels of other windows are never touched by an operation on this one. Every operation holds a file lock.
A panel opened by the Follower also carries @swarmbox_sysop_auto=1: only those are closed when the goal ends; one opened by hand stays.
The name of the tab. tmux names a window after the command of its ACTIVE pane, and the panel takes the focus: without care the tab would be called
"python3" while the panel is open (in the status line, in `list_tabs` labels, in the panel's own header). So the panel's window gets `automatic-rename off`
before the panel is created, and gets back what it had (on, off, or "inherited") when no panel is left in it: `close`, the quit key of the panel
(thaw_own_window) and, for a panel that was killed some other way, the next open or close of any window (_heal). The value to go back to is kept in the
window option @swarmbox_sysop_ar.
Nothing here can fail a request: callers get DockError and log it.
"""
import fcntl
import os
import re
import shlex
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
REDOCK_OPTION = "@swarmbox_sysop_redock"
AR_OPTION = "@swarmbox_sysop_ar"       # window option: what `automatic-rename` was on the window before the panel froze the tab's name (see Dock._freeze_name)
SEP = "@@sb@@"                         # not a tab: tmux 3.6 and later prints control characters of a list as `_` when it has no terminal

CELL_FACTOR = 2
BOTTOM_PERCENT = 40
RIGHT_PERCENT = 20
MIN_PANEL_COLS = 40
MIN_TERMINAL_COLS = 60
ACTIONS = ("open", "close", "toggle", "redock")
PASS_ENV = ("SB_RUN_DIR", "SB_STATE_DIR", "SB_BUS_SOCKET", "XDG_STATE_HOME", "HOME", "NO_COLOR", "LANG", "LC_ALL", "TERM")

Layout = namedtuple("Layout", "kind size")   # kind: "bottom" | "right"; size: the value of -l ("40%", "20%" or a column count)
Result = namedtuple("Result", "rc out err")


def layout(cols, rows):
    """Where the panel docks in a window of cols x rows cells. See the module docstring for the rule."""
    bottom = Layout("bottom", "%d%%" % BOTTOM_PERCENT)
    try:
        cols, rows = int(cols), int(rows)
    except (TypeError, ValueError):
        return bottom
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


class Tmux:
    """argv is the command prefix. Default: the words of SWARMBOX_TEST_TMUX, else `tmux` with `-L SB_BUS_TMUX_SOCKET` when that is set (the same
    server as the bus driver). `run` never raises: a missing binary is rc 127, a timeout rc 124. TMUX is removed from the environment."""

    def __init__(self, argv=None, env=None, timeout=5.0):
        if argv is None:
            argv = shlex.split(os.environ.get("SWARMBOX_TEST_TMUX", ""))
        if not argv:
            argv = [os.environ.get("SB_BUS_TMUX_BIN") or "tmux"]
            if os.environ.get("SB_BUS_TMUX_SOCKET"):
                argv += ["-L", os.environ["SB_BUS_TMUX_SOCKET"]]
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

    def __init__(self, tmux, session="main", panel_argv=None, redock_argv=None, lock_path=None):
        self.tmux, self.session = tmux, session
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
            for p in self.panels():
                if (window is None or p.window == window) and (p.auto or not only_auto):
                    self._tm("kill-pane", "-t", p.pane, check=False)
                    n += 1
            rows = self._rows()
            self._heal(rows)
            if not any(r.panel for r in rows):
                self._hook(False)
            return n

    def toggle(self, window=None):
        """Closes the panel of the window (the one given, else the one shown) when there is one, else opens it there. "closed" or what open returns."""
        with self._lock():
            rows = self._rows()
            target = window or self._shown_window(rows)
            here = [r for r in rows if r.panel and r.window == target]
        if here:
            self.close(window=target)
            return "closed"
        return self.open(window=target)

    def redock(self, window=None):
        """The hook: when the window's shape changed so that another layout applies, move ITS panel there (all windows when none is given). Never
        takes the focus from the pane that has it. With no panel left anywhere the hook removes itself."""
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
        self._freeze_name(window)
        try:
            res = self._tm("split-window", "-t", window, *flags, *split_args(layout(cols, lines)), "-P", "-F", "#{pane_id}", "--", *self.panel_argv)
        except DockError:
            self._thaw_name(window)
            raise
        pane = res.out.strip()
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
        if have is None or have == want:
            return False
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
        self._tm("set-hook", "-g", HOOK, 'run-shell -b "#{%s} --window #{hook_window}"' % REDOCK_OPTION, check=False)


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


def default_dock(tmux=None, session=None):
    """A Dock whose panel and hook run this very library with the python that runs this process (no dependency on PATH). The folders of the
    service (SB_RUN_DIR and the others of PASS_ENV that are set) are handed on, so the panel reads the same files as the service."""
    env = ["PYTHONPATH=" + lib_dir() + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")]
    env += ["%s=%s" % (k, os.environ[k]) for k in PASS_ENV if os.environ.get(k)]
    base = ["env"] + env + [sys.executable, "-B", "-m", "swarmbox_sysop"]
    return Dock(tmux or Tmux(), session or os.environ.get("SB_BUS_TMUX_SESSION") or "main",
                panel_argv=["env", PANEL_COMMAND] + base[1:] + ["panel"], redock_argv=base + ["dock", "redock"])


def run(action, socket=None, window=None):
    """`swarmbox-sysop dock ACTION`: the tmux key and the hook call this. Exit code 0, 1 (a DockError, said on stderr), 2 (bad window id)."""
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
        else:
            out = d.redock(window=window)
    except DockError as e:
        print("swarmbox-sysop: dock: %s" % e, file=sys.stderr)
        return 1
    if action != "redock":
        print("swarmbox-sysop: panel %s" % out, file=sys.stderr)
    return 0


class Follower:
    """Opens the panel when a goal arrives and closes it (the ones it opened) `grace` seconds after the last goal and the queue ended.
    It reads status.json of the service (the files of ipc.py), nothing else. Once per goal: a panel the user closed with `q` is not opened
    again for the same run of goals. A tmux that is missing or has no session is not an error here: it is tried again at the next goal."""

    def __init__(self, pth, dock=None, interval=0.3, grace=3.0, clock=time.monotonic, log=None):
        self.paths, self.dock = pth, dock
        self.interval, self.grace, self.clock = interval, grace, clock
        self.log = log or (lambda msg: None)
        self.busy, self.idle_since = False, None
        self.stop = threading.Event()
        self.thread = None

    def step(self):
        st = ipc.read_json(self.paths.status)
        st = st if isinstance(st, dict) else {}
        busy = bool(st.get("current")) or bool(st.get("queue"))
        now = self.clock()
        if busy:
            self.idle_since = None
            if not self.busy:
                self.busy = True
                self._do(lambda d: d.open(auto=True, focus=True), "open")
        elif self.busy:
            if self.idle_since is None:
                self.idle_since = now
            if now - self.idle_since >= self.grace:
                self.busy, self.idle_since = False, None
                self._do(lambda d: d.close(only_auto=True), "close")

    def _do(self, fn, what):
        try:
            if self.dock is None:
                self.dock = default_dock()
            fn(self.dock)
        except DockError as e:
            self.log("panel %s: %s" % (what, e))
        except Exception as e:               # nothing here may take the service down
            self.log("panel %s: %r" % (what, e))

    def loop(self):
        while not self.stop.wait(self.interval):
            self.step()

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="sysop-dock", daemon=True)
        self.thread.start()
        return self

    def shutdown(self):
        self.stop.set()
