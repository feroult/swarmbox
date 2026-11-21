"""The one line of the sysop: what it is doing, in a sentence, for a screen that has no room for the panel (a phone).

Pure status computation lives in state.py (`line_of`, `value_of`). This module keeps the `Toaster` thread, which polls
cheaply and delivers each change to a sink — by default the global tmux option `@sysop_line` (`TmuxOptionSink`), or any
custom callable `sink(value)` for non-tmux front-ends.
"""
import threading
import time

from .dock import Tmux
from .state import IDLE, MAX_TEXT, PREFIX, SHOW_END, TERMINAL, _cut, _last_thing, line_of, snapshot, value_of  # noqa: F401

OPTION = "@sysop_line"
BUSY_POLL = 0.5          # while a goal runs or waits
IDLE_POLL = 2.0          # nothing going on: a stat and a lock probe


class Toaster:
    """A thread: looks at the files of the service and pushes the status line to a sink (default: tmux @sysop_line) whenever
    it changes. Never raises and never takes the service down."""

    def __init__(self, pth, tmux=None, log=None, clock=time.monotonic, wall=time.time, sink=None):
        self.paths = pth
        self.tmux = tmux
        self.sink = sink
        self.log = log or (lambda msg: None)
        self.clock, self.wall = clock, wall
        self.stop = threading.Event()
        self.thread = None
        self.sent = False                # the value last set (None: unset); False: nothing sent yet
        self.last_gid = None
        self.ended = None                # (goal id, state) and when it was first seen
        self.busy = False
        self._said = None

    def current(self):
        """The line to show now: line_of, but an ended goal only for SHOW_END seconds from when it was first seen (a clock of our own too)."""
        snap = snapshot(self.paths, self.last_gid)
        if snap.gid:
            self.last_gid = snap.gid
        line = line_of(snap, self.wall())
        self.busy = bool(snap.up and (snap.pending or snap.queue or (snap.goal and snap.goal.get("state") not in TERMINAL)))
        if line and line[0] in TERMINAL:
            key = (snap.gid, line[0])
            now = self.clock()
            if not self.ended or self.ended[0] != key:
                self.ended = (key, now)
            if now - self.ended[1] >= SHOW_END:
                return IDLE
        else:
            self.ended = None
        return line

    def apply(self, value):
        """Deliver `value` (or None to unset) when it differs from what was sent last. True when accepted."""
        if value == self.sent:
            return True
        if self.sink is not None:
            ok = self.sink(value)
            if ok is False:
                return False
            self._said = None
            self.sent = value
            return True
        if self.tmux is None:
            self.tmux = Tmux()
        res = self.tmux.run("set-option", "-g", OPTION, value) if value else self.tmux.run("set-option", "-gu", OPTION)
        if res.rc != 0:
            msg = "the line of the sysop: tmux said %s" % (res.err.strip()[:120] or "rc %d" % res.rc)
            if msg != self._said:
                self._said = msg
                self.log(msg)
            return False
        self._said = None
        self.sent = value
        return True

    def look(self):
        try:
            self.apply(value_of(self.current()))
        except Exception as e:              # nothing here may take the service down
            msg = "the line of the sysop: %r" % (e,)
            if msg != self._said:
                self._said = msg
                self.log(msg)

    def loop(self):
        while True:
            self.look()
            if self.stop.wait(BUSY_POLL if self.busy or self.sent is False or self.ended else IDLE_POLL):
                return

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="sysop-line", daemon=True)
        self.thread.start()
        return self

    def shutdown(self, unset=True):
        self.stop.set()
        try:
            if unset and self.sent:
                if self.sink is not None:
                    self.sink(None)
                else:
                    (self.tmux or Tmux()).run("set-option", "-gu", OPTION)     # the service ends: the line goes with it
        except Exception:
            pass
