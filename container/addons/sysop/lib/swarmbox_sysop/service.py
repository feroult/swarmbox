"""The resident subscriber of the sysop: it reads goals from the bus, keeps a queue and runs ONE goal at a time.

  reader thread   subscribes to the topic of `sysop.topic` (default `goal`) as a member of the group `sysop.group` (default `sysop`: sysops of one group share
                  the goals, one gets each), with reconnect and backoff (1, 2, 4, 5, 5 ... s; the bus is restarted by its supervisor within
                  a few seconds), puts each goal in the queue, writes its state `queued`
  main thread     takes the oldest goal, writes the files of the goal (context.json, the MCP config), runs the brain (brain.py), keeps state.json
                  up to date while it runs, and writes the end: done, stopped or failed (with the reason). It also takes the stop requests

Limits: at most max_goals goals wait; the next is dropped, with its own state `failed` ("queue is full") and an audit line (the bus has no ack in
v1, so the sender cannot be told). A goal is at most MAX_GOAL_TEXT characters.
Survival: a brain that crashes, hangs or is not logged in ends ITS goal as failed with the reason, and the service takes the next goal; a bus that
goes away makes the reader reconnect, and a run in progress goes on (its tools act on the tabs, not through the bus);
when the service itself dies, the next start (the single-instance lock is a flock, so a dead one never blocks it) marks every goal that was
queued, running or waiting as `failed` with the note that goals in flight are LOST (they are not kept, and no one is told). The brain of a dead
service gets SIGTERM from the kernel (brain.pdeathsig).
Files: ipc.py has the contract; status.json (run folder) is the state of the whole service, state.json (goal folder) the state of one goal.
"""
import collections
import errno
import fcntl
import json
import os
import re
import shutil
import sys
import threading
import time

from . import __version__, brain, busclient, history, ipc
from . import paths as pathsmod
from . import audit as auditmod

MAX_GOAL_TEXT = 4000
KEEP_GOALS = 50
RECENT_CALLS = 12
HOUSEKEEPING = 60.0
RETRY_WRITES = 2.0       # seconds between two tries to write the end of a goal that the disk refused
BACKOFF = (1.0, 5.0)       # the bus is on a unix socket of the same box (a try costs nothing), and its supervisor can give up and be restarted by hand: the wait is short
FREE_TOOLS = ("say", "done")
LOST = "lost: the sysop restarted while this goal was in flight (goals in flight are not kept)"


LOW_DISK = 2 << 20      # bytes free below which a failed goal says that the disk is almost full


def disk_low(path):
    try:
        return shutil.disk_usage(path).free < LOW_DISK
    except OSError:
        return False


def explain(e):
    """The reason a goal failed for an exception of the service itself: a full disk is said as one, the rest as an internal error"""
    if isinstance(e, OSError) and getattr(e, "errno", None) in (errno.ENOSPC, errno.EDQUOT):
        return "the disk of the box is full (%s): free some space and send the goal again" % (e.strerror or "no space left")
    return "internal error: %s: %s" % (type(e).__name__, e)


def sanitize(s, default):
    s = re.sub(r"[^A-Za-z0-9._-]", "_", str(s or ""))[:64].strip(".")
    return s or default


class Goal:
    def __init__(self, gid, source, text, clock=time.time):
        self.id, self.source, self.text = gid, source, text
        self.state, self.created, self.started, self.ended = "queued", clock(), None, None
        self.say, self.calls, self.pending = [], [], None
        self.summary, self.error, self.note, self.steps = "", "", "", 0
        self.brain = {}
        self._written = None

    def as_dict(self):
        return {"id": self.id, "source": self.source, "text": self.text, "state": self.state, "created": self.created, "started": self.started,
                "ended": self.ended, "say": self.say, "calls": self.calls, "pending": self.pending, "summary": self.summary, "error": self.error,
                "note": self.note, "steps": self.steps, "brain": self.brain}


def running(paths):
    """True when a service holds the lock (the pid is in the pid file)."""
    try:
        fd = os.open(paths.lock, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)           # closing drops the lock we may just have taken
    return False


def recent_goals(paths, n=5):
    out = []
    try:
        names = sorted(os.listdir(paths.goals), key=lambda x: os.path.getmtime(os.path.join(paths.goals, x)), reverse=True)
    except OSError:
        return out
    for name in names:
        st = ipc.read_json(os.path.join(paths.goals, name, "state.json"))
        if isinstance(st, dict):
            out.append(st)
        if len(out) >= n:
            break
    return out


class Service:
    def __init__(self, cfg, paths, bus=None, clock=time.time, log=None, backoff=BACKOFF, popen=None):
        self.cfg, self.paths, self.clock = cfg, paths, clock
        self.bus = bus or busclient.Bus(paths.socket)
        self.log = log or self.stderr_log
        self.backoff = backoff
        self.audit = auditmod.Audit(paths.audit, clock=clock)
        self.cond = threading.Condition()
        self.status_lock = threading.Lock()       # status.json: the reader thread (a goal arrived) and the main thread (a goal starts) both write it
        self.queue = collections.deque()
        self.current = None
        self.stopping = False
        self.stop_current = False
        self.sub = None
        self.bus_state = "down"
        self.rejected = 0
        self.started = clock()
        self.lock_fd = None
        self.reader = None
        self.popen = popen
        self.housekeeping = None       # a callable the main loop runs every HOUSEKEEPING seconds (the daemon's log rotation: cli.py)
        self._retried = 0.0
        self.unwritten = {}            # goals whose end could not be written to their state.json (a full disk): tried again by retry_writes
        self._last_status = None
        self._ready = threading.Event()
        self.libdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @staticmethod
    def stderr_log(m):
        """the log of the daemon (standard error is serve.log). A log that cannot be written (the disk is full) must not take the service down with it:
        the line is lost, which is all a full disk can mean for a log."""
        try:
            print("%s sysop[%d]: %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid(), m), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass

    # ---- life
    LOCK_WAIT = 1.0

    def acquire(self, wait=None):
        """Take the single-instance lock. `running()` (the panel every 0.2 s, `swarmbox-sysop status`, prepare.sh) probes the same lock with a
        non-blocking flock that holds it for an instant when it is free: a start that lands on such an instant used to find the lock taken, say
        "already running" and exit 0, leaving NO service until the next start of the box (seen once by the end-to-end test of version 1). So a taken lock is tried
        again for LOCK_WAIT seconds: a probe is gone by then, a live service is not."""
        self.paths.make()
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        end = time.monotonic() + (self.LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    os.close(fd)
                    return False
                time.sleep(0.02)
        self.lock_fd = fd
        os.ftruncate(fd, 0)
        os.write(fd, ("%d\n" % os.getpid()).encode())
        with open(self.paths.pidfile, "w") as f:
            f.write("%d\n" % os.getpid())
        os.chmod(self.paths.pidfile, 0o600)
        return True

    def run(self, handle_signals=False):
        """Returns 0 at a clean end, 9 when another service holds the lock."""
        if not self.acquire():
            return 9
        try:
            ipc.remove(self.paths.stop_request)
            self.recover()
            self.prune()
            self.reader = threading.Thread(target=self.read_goals, name="sysop-reader", daemon=True)
            self.reader.start()
            self.status()
            self._ready.set()
            self.log("serving: autonomy %s, brain %s, topic %s, group %s, bus %s" % (self.cfg.autonomy, self.cfg.brain.split()[0], self.cfg.topic, self.cfg.group, self.paths.socket))
            fails, tidied = 0, self.clock()
            while not self.stopping:
                try:
                    if self.housekeeping is not None and self.clock() - tidied >= HOUSEKEEPING:
                        tidied = self.clock()
                        self.housekeeping()
                    self.retry_writes()
                    self.poll_stop()
                    goal = self.next_goal(0.2)
                    if goal is not None:
                        self.execute(goal)
                        self.prune()
                        self.status()
                    fails = 0
                except Exception as e:      # a disk that is full, a folder that went away: one turn of the loop fails, the service does not end (and does not spin)
                    fails += 1
                    if fails <= 3 or fails % 100 == 0:
                        self.log("internal error in the main loop (%d in a row): %s: %s" % (fails, type(e).__name__, e))
                    with self.cond:
                        self.cond.wait(min(5.0, 0.5 * fails))
        finally:
            self.shutdown()
            self.status(final=True)
            for p in (self.paths.pidfile,):
                ipc.remove(p)
            if self.lock_fd is not None:
                os.close(self.lock_fd)
                self.lock_fd = None
        return 0

    def retry_writes(self):
        """The end of a goal that could not be written (the disk was full) is written when there is room again: without this its state.json says `running`
        for ever (the panel shows a goal that is long over) until the next start of the service marks it lost."""
        if not self.unwritten or time.monotonic() - self._retried < RETRY_WRITES:
            return
        self._retried = time.monotonic()
        for gid, goal in list(self.unwritten.items()):
            try:
                self.write_goal(goal)
            except OSError:
                return
            del self.unwritten[gid]
            self.log("goal %s: its end is written now (the disk has room again)" % gid)

    def wait_ready(self, timeout=10):
        return self._ready.wait(timeout)

    def shutdown(self):
        """Thread-safe: end the loop, the run in progress and the reader."""
        self.stopping = True
        with self.cond:
            self.cond.notify_all()
        sub = self.sub
        if sub is not None:
            sub.close()

    def recover(self):
        """Goals of an earlier service that never ended are lost: say so in their state."""
        try:
            names = os.listdir(self.paths.goals)
        except OSError:
            return
        for name in names:
            p = os.path.join(self.paths.goals, name, "state.json")
            st = ipc.read_json(p)
            if isinstance(st, dict) and st.get("state") in ("queued", "running", "waiting_approval"):
                st.update(state="failed", error=LOST, ended=self.clock(), pending=None)
                try:
                    ipc.write_json(p, st)
                except OSError as e:           # a full disk: the service still starts; the goal is marked at the next start
                    self.log("goal %s was %s when the sysop stopped, but its state cannot be written: %s" % (name, st.get("state"), e.strerror or e))
                    continue
                self.audit.bind(st.get("id"), st.get("source")).append("lost", was=st.get("state"), error=LOST)
                self.log("goal %s was %s when the sysop stopped: marked failed (lost)" % (name, st.get("state")))
        ipc.remove(self.paths.status)

    def prune(self):
        """Keep the newest KEEP_GOALS goal folders; never one that is queued or running (the service calls this at start, after every goal and
        after every rejected goal, so a flood of goals cannot fill the disk while it runs)."""
        with self.cond:
            live = {g.id for g in self.queue}
        if self.current is not None:
            live.add(self.current.id)
        try:
            names = sorted(os.listdir(self.paths.goals), key=lambda x: os.path.getmtime(os.path.join(self.paths.goals, x)))
        except OSError:
            return
        for name in [n for n in names if n not in live][:-KEEP_GOALS]:
            shutil.rmtree(os.path.join(self.paths.goals, name), ignore_errors=True)

    # ---- the reader
    def read_goals(self):
        wait, hi = self.backoff[0], self.backoff[1]
        while not self.stopping:
            began = None
            try:
                sub = self.bus.subscribe(self.cfg.topic, self.cfg.group)
            except busclient.BusError as e:
                self.set_bus("down")
                self.log("the bus is not reachable (%s): retrying in %g s" % (e, wait))
            else:
                self.sub = sub
                if self.stopping:
                    # shutdown() ran between the broker's ack and this line, when self.sub was not yet there to close: the stream would stay
                    # open (and the broker would go on delivering goals to a service that is gone)
                    sub.close()
                    self.sub = None
                    return
                began = self.clock()
                self.set_bus("connected")
                try:
                    for env in sub:
                        try:
                            self.accept(env)
                        except Exception as e:      # one bad goal must not end the reader: the service would go on deaf
                            self.log("a goal could not be accepted: %r" % (e,))
                except busclient.BusError as e:
                    self.log("the goal stream broke: %s" % e)
                finally:
                    sub.close()
                    self.sub = None
                self.set_bus("down")
                if not self.stopping:
                    self.log("the goal stream ended: reconnecting")
            if self.stopping:
                return
            if began is not None and self.clock() - began > 10:
                wait = self.backoff[0]
            with self.cond:
                self.cond.wait(wait)
            wait = min(hi, wait * 2)

    def set_bus(self, st):
        if st != self.bus_state:
            self.bus_state = st
            self.status()

    def accept(self, env):
        if not isinstance(env, dict) or env.get("_bad"):
            self.audit.append("rejected", reason="not a bus envelope")
            return
        if not isinstance(env.get("v", 1), int) or env.get("v", 1) > 1:
            self.audit.append("rejected", reason="envelope of a newer protocol version")
            return
        source = sanitize(str(env.get("source") or "unknown").lower(), "unknown")[:32]
        body = env.get("body")
        text = body.get("text") if isinstance(body, dict) else body
        gid = self.new_id(env.get("id"))
        goal = Goal(gid, source, text if isinstance(text, str) else "", self.clock)
        aud = self.audit.bind(gid, source)
        gdir = self.paths.goal_dir(gid)
        pathsmod.private_dir(gdir)
        reason = None
        if not isinstance(text, str) or not text.strip():
            reason = 'the goal has no text (the body is {"text": "..."} or plain text)'
        elif len(text) > MAX_GOAL_TEXT:
            reason = "the goal has %d characters, at most %d" % (len(text), MAX_GOAL_TEXT)
        else:
            with self.cond:
                if len(self.queue) >= self.cfg.max_goals:
                    reason = "the queue is full (%d goals wait): this goal was dropped" % self.cfg.max_goals
                else:
                    goal.text = text.strip()
                    self.queue.append(goal)
        if reason:
            self.rejected += 1
            goal.text = goal.text[:200]           # a rejected goal does not keep its text (a goal of 1 MiB, a hundred times, would fill the disk)
            aud.append("goal", text=goal.text, peer=env.get("peer"), bus_id=env.get("id"))
            goal.state, goal.error, goal.ended = "failed", reason, self.clock()
            self.write_goal(goal)
            aud.append("rejected", reason=reason)
            self.log("goal %s rejected: %s" % (gid, reason))
            self.prune()
        else:
            aud.append("goal", text=goal.text, peer=env.get("peer"), bus_id=env.get("id"))
            self.write_goal(goal)
            aud.append("state", state="queued", queue=len(self.queue))
            with self.cond:
                self.cond.notify_all()
        self.status()

    def new_id(self, bus_id):
        base = sanitize(bus_id, "g%d" % int(self.clock() * 1000))
        gid, n = base, 1
        while os.path.exists(self.paths.goal_dir(gid)):
            n += 1
            gid = "%s-%d" % (base, n)
        return gid

    def next_goal(self, timeout):
        with self.cond:
            if not self.queue and not self.stopping:
                self.cond.wait(timeout)
            return self.queue.popleft() if self.queue and not self.stopping else None

    # ---- files
    def write_goal(self, goal):
        ipc.write_json(os.path.join(self.paths.goal_dir(goal.id), "state.json"), goal.as_dict())

    def status(self, final=False):
        """Write status.json. The state is read AND written under one lock: two threads call this (the reader when a goal arrives, the main thread when
        it starts it), and a state read first but written last would leave an old file (found by the end-to-end test of version 1: the panel showed `1 queued, idle`
        for the whole goal, so the countdown and the approval were never shown and the veto key had nothing to act on)."""
        with self.status_lock:
            with self.cond:
                queue = [{"id": g.id, "source": g.source, "text": g.text[:200], "queued": g.created} for g in self.queue]
            st = {"pid": os.getpid(), "version": __version__, "started": self.started, "updated": self.clock(),
                  "bus": "stopped" if final else self.bus_state, "current": self.current.id if self.current else None, "queue": queue,
                  "rejected": self.rejected,
                  "settings": {"topic": self.cfg.topic, "group": self.cfg.group, "autonomy": self.cfg.autonomy, "countdown": self.cfg.countdown, "brain": self.cfg.brain.split()[0], "model": self.cfg.model,
                               "max_steps": self.cfg.max_steps, "max_seconds": self.cfg.max_seconds, "max_goals": self.cfg.max_goals}}
            key = json.dumps({k: v for k, v in st.items() if k != "updated"}, sort_keys=True)
            if key == self._last_status and not final:
                return
            self._last_status = key
            try:
                ipc.write_json(self.paths.status, st)
            except OSError as e:
                self.log("cannot write status.json: %s" % e)

    # ---- stop
    def poll_stop(self):
        """Take a stop request. Returns True when it ends the goal that runs now."""
        req = ipc.take_stop(self.paths)
        if req is None:
            return self.stop_current
        target = req.get("goal")
        dropped = []
        with self.cond:
            if target is None:
                dropped, self.queue = list(self.queue), collections.deque()
            else:
                dropped = [g for g in self.queue if g.id == target]
                self.queue = collections.deque(g for g in self.queue if g.id != target)
        for g in dropped:
            g.state, g.error, g.ended = "stopped", "stopped before it started", self.clock()
            try:
                self.write_goal(g)
            except OSError as e:
                self.log("goal %s: cannot write its state: %s" % (g.id, e.strerror or e))
            self.audit.bind(g.id, g.source).append("state", state="stopped", why="stop request, queued")
        if self.current is not None and (target is None or target == self.current.id):
            self.stop_current = True
            self.audit.bind(self.current.id, self.current.source).append("decision", decision="stop", why="stop request")
        self.status()
        return self.stop_current

    # ---- one goal
    def refresh(self, goal):
        """Rebuild the live parts of the state of a running goal from the files of the MCP server; write it when it changed."""
        gdir = self.paths.goal_dir(goal.id)
        goal.say = [{"t": x.get("t"), "text": x.get("text")} for x in ipc.read_jsonl(os.path.join(gdir, "say.jsonl"))][-20:]
        calls = ipc.read_jsonl(os.path.join(gdir, "calls.jsonl"))
        goal.steps = sum(1 for c in calls if c.get("tool") not in FREE_TOOLS)
        goal.calls = calls[-RECENT_CALLS:]
        pend = ipc.read_json(os.path.join(gdir, "pending_action.json"))
        goal.pending = pend if isinstance(pend, dict) else None
        if goal.state in ("running", "waiting_approval"):
            goal.state = "waiting_approval" if goal.pending else "running"
        done = ipc.read_json(os.path.join(gdir, "done.json"))
        if isinstance(done, dict):
            goal.summary = str(done.get("summary", ""))
        before = goal._written
        now = json.dumps(goal.as_dict(), sort_keys=True)
        if now != before:
            goal._written = now
            self.write_goal(goal)
            if before is not None and json.loads(before)["state"] != goal.state:
                self.audit.bind(goal.id, goal.source).append("state", state=goal.state)

    def execute(self, goal):
        aud = self.audit.bind(goal.id, goal.source)
        self.current, self.stop_current = goal, False
        goal.state, goal.started = "running", self.clock()
        gdir = self.paths.goal_dir(goal.id)
        try:
            self.write_goal(goal)
            aud.append("state", state="running")
            self.status()
            deadline = goal.started + self.cfg.max_seconds
            ctx = os.path.join(gdir, "context.json")
            ipc.write_json(ctx, {"goal": goal.id, "source": goal.source, "goal_dir": gdir, "audit": self.paths.audit,
                                 "autonomy": self.cfg.autonomy, "countdown": self.cfg.countdown, "approval_timeout": self.cfg.approval_timeout,
                                 "max_steps": self.cfg.max_steps, "deadline": deadline})
            mcp = os.path.join(gdir, "mcp.json")
            brain.write_mcp_config(mcp, ctx, self.paths, self.libdir)
            pfile = os.path.join(gdir, "system-prompt.txt")
            with open(pfile, "w", encoding="utf-8") as f:
                f.write(brain.system_prompt(goal.source, self.cfg.max_steps, self.cfg.max_seconds, self.cfg.autonomy))
            os.chmod(pfile, 0o600)
            argv, env = brain.build(self.cfg, gdir, mcp, goal.source, pfile)
            kw = {"popen": self.popen} if self.popen else {}

            def stop_check():
                if self.stopping:
                    self.stop_current = True
                if self.poll_stop() or self.stop_current:
                    if not os.path.exists(os.path.join(gdir, "stopped")):
                        open(os.path.join(gdir, "stopped"), "w").close()
                    return True
                return False

            def on_start(pid):
                goal.brain["pid"] = pid
                self.refresh(goal)
            # the brain starts with no memory: the goals before this one go in front of it (history.py), so a follow-up is understood
            heard = goal.text
            try:
                before = history.conversation(history.load(self.paths), goal.id, self.clock(), since=history.since(self.paths))
            except Exception as e:      # a damaged folder of an old goal must not stop this one
                self.log("goal %s: no conversation so far (%r)" % (goal.id, e))
                before = ""
            if before:
                heard = before + "\n\nThe goal now (" + goal.source + "):\n" + goal.text
            res = brain.run(self.cfg, heard, goal.source, gdir, argv, env, stop_check, lambda: self.refresh(goal), deadline,
                            clock=self.clock, on_start=on_start, **kw)
        except Exception as e:             # a bug here must not kill the service: this goal fails, the next one runs
            self.log("goal %s: internal error: %r" % (goal.id, e))
            res = brain.Result("failed", explain(e))
        goal.state, goal.ended, goal.error, goal.note = res.outcome, self.clock(), res.error, res.note
        if self.stopping and res.outcome == "stopped":
            goal.error = "the sysop service was stopped"
        if res.summary:
            goal.summary = res.summary
        goal.brain.update({"exit": res.exit_code, "turns": res.turns, "cost": res.cost})
        goal.pending = None
        for name in ("pending_action.json", "decision.json"):
            ipc.remove(os.path.join(gdir, name))
        if res.outcome == "failed" and disk_low(gdir):
            goal.error = (goal.error + " " if goal.error else "") + "(the disk of the box is almost full: free some space)"
        try:
            self.refresh_final(goal)
        except Exception as e:       # not only OSError: the end of one goal must never end the service
            self.log("cannot write the end of goal %s: %r" % (goal.id, e))
            self.unwritten[goal.id] = goal
        aud.append("brain", **res.as_dict(), note=res.note)
        aud.append("state", state=goal.state, summary=goal.summary, error=goal.error)
        self.log("goal %s: %s%s" % (goal.id, goal.state, (" (%s)" % goal.error) if goal.error else ""))
        self.current, self.stop_current = None, False

    def refresh_final(self, goal):
        gdir = self.paths.goal_dir(goal.id)
        goal.say = [{"t": x.get("t"), "text": x.get("text")} for x in ipc.read_jsonl(os.path.join(gdir, "say.jsonl"))][-20:]
        calls = ipc.read_jsonl(os.path.join(gdir, "calls.jsonl"))
        goal.steps = sum(1 for c in calls if c.get("tool") not in FREE_TOOLS)
        goal.calls = calls[-RECENT_CALLS:]
        self.write_goal(goal)
