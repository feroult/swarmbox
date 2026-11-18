"""The one line of the sysop: what it is doing, in a sentence, for a screen that has no room for the panel (a phone).

The service (`swarmbox-sysop serve --dock`, in every panel mode) keeps the global tmux option @sysop_line:
    sysop:<state>:<sentence>        state: working | sending | allow? | queued | done | failed | stopped
and unsets it when there is nothing to say (idle, the service is down, a finished goal after SHOW_END seconds). tmux.conf has `set-titles on` with the
title `#{?@sysop_line,#{@sysop_line},#S:#I:#W}`, so tmux sends the line to every client as the title of the terminal and the web page (ttyd-clipboard.js)
shows it next to the microphone. No file, no port and no process in the pane: a change of the option is the whole channel.

The sentence is one plain line of at most MAX_TEXT characters (no control characters: panel.clean), and it is not the whole result of anything: what
the sysop said last, or else the last step in plain words (`read tab 1`, `run: pytest -q`); for `sending` and `allow?` the action that waits; for the end of
a goal its summary or error.

line_of is a pure function of the files' snapshot (panel.snapshot); Toaster is the thread that looks, cheaply, and sets the option when the line changes.
"""
import threading
import time

from .dock import Tmux
from .panel import TERMINAL, Model, one_line, snapshot, step_text

OPTION = "@sysop_line"
PREFIX = "sysop"
MAX_TEXT = 140
SHOW_END = 10.0          # seconds the end of a goal (done, failed, stopped) stays on the line
BUSY_POLL = 0.5          # while a goal runs or waits
IDLE_POLL = 2.0          # nothing going on: a stat and a lock probe


def _cut(text, limit=MAX_TEXT):
    text = one_line(text, 4000)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _last_thing(goal):
    """The latest of what the sysop said and of its steps (the tool done is not a step), in plain words."""
    best = None
    items = [("say", s) for s in goal.get("say") or [] if isinstance(s, dict)]
    items += [("call", c) for c in goal.get("calls") or [] if isinstance(c, dict) and c.get("tool") != "done"]
    for kind, it in items:
        t = it.get("t") if isinstance(it.get("t"), (int, float)) else 0
        if best is None or t >= best[0]:
            best = (t, kind, it)
    if best is None:
        return ""
    return one_line(best[2].get("text"), 4000) if best[1] == "say" else step_text(best[2])


def line_of(snap, wall=0.0):
    """(state, sentence) of what the files say, or None when there is nothing to show. `wall`: the time now, for how long an ended goal stays."""
    m = Model()
    m.update(snap, 0.0)
    if not m.up:
        return None
    if m.pending:
        what = _cut(m.pending.get("text"))
        return ("allow?" if m.pmode() == "approve" else "sending", what or "an action")
    g = m.goal
    if g:
        st = g.get("state")
        if st in TERMINAL:
            ended = g.get("ended")
            if isinstance(ended, (int, float)) and wall and wall - ended > SHOW_END:
                return None
            return (st, _cut(g.get("summary") or g.get("error") or st))
        if st == "queued":
            return ("queued", _cut(g.get("text")))
        if st == "waiting_approval":
            return ("allow?", _cut(g.get("text")))
        return ("working", _cut(_last_thing(g) or g.get("text")))
    if m.queue:
        return ("queued", "%d queued" % len(m.queue))
    return None


def value_of(line):
    return None if line is None else "%s:%s:%s" % (PREFIX, line[0], line[1])


class Toaster:
    """A thread: looks at the files of the service and keeps the option @sysop_line as line_of says. Never raises and never takes the service down: a tmux that
    is missing, or a server that is not up yet, is tried again at the next look and said once in the log. At its start it sets or unsets the option once,
    so a line left by an earlier service does not stay."""

    def __init__(self, pth, tmux=None, log=None, clock=time.monotonic, wall=time.time):
        self.paths = pth
        self.tmux = tmux
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
                return None
        else:
            self.ended = None
        return line

    def apply(self, value):
        """Set or unset the option when `value` is not what was set last. True when tmux took it."""
        if value == self.sent:
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
                (self.tmux or Tmux()).run("set-option", "-gu", OPTION)     # the service ends: the line goes with it
        except Exception:
            pass
