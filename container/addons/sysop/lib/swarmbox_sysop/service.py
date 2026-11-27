"""The resident subscriber of the sysop: it reads goals from the bus, keeps a queue and runs ONE goal at a time.

  reader thread   subscribes to the topic of `sysop.topic` (default `goal`) as a member of the group `sysop.group` (default `sysop`: sysops of one group share
                  the goals, one gets each), with reconnect and backoff (1, 2, 4, 5, 5 ... s; the bus is restarted by its supervisor within
                  a few seconds), puts each goal in the queue, writes its state `queued`
  main thread     takes the oldest goal, writes the files of the goal (context.json, the MCP config), runs the brain (brain.py), keeps state.json
                  up to date while it runs, and writes the end: done, stopped or failed (with the reason). It also takes the stop requests.
                  A resident brain (docs/sysop-resident-brain-design.md) is one process kept across goals (brain.Runtime): the goal is one
                  message to it, Stop an interrupt of its turn; it is started at the first goal, again when it died, and ends with the service

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
import subprocess
import sys
import threading
import time

from . import __version__, brain, busclient, history, ipc, landlock, mcpserver, notes, tabsclient
from . import automations as automod
from . import events as eventsmod
from . import paths as pathsmod
from . import audit as auditmod

MAX_GOAL_TEXT = 4000
KEEP_GOALS = 50
RECENT_CALLS = 12
HOUSEKEEPING = 60.0
RETRY_WRITES = 2.0       # seconds between two tries to write the end of a goal that the disk refused
BACKOFF = (1.0, 5.0)       # the bus is on a unix socket of the same box (a try costs nothing), and its supervisor can give up and be restarted by hand: the wait is short
FREE_TOOLS = ("say", "done")
# the sources a person types or speaks in: a goal of one of them that arrives while another such goal runs is given to that goal (steering).
# Not cli or agent: a script that sends goals expects a queue
INTERACTIVE = ("web", "panel", "cockpit", "voice")
AUTOMATED = ("schedule", "trigger")
TRIGGER_EVERY = 3.0       # seconds between two turns of the automations' thread: the schedules that are due, a look at the tabs for the triggers
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
        self.steer_into = None       # the running goal this one was given to (steering), while it waits for the brain to take it
        self.automation = None       # the automation that started it
        self._written = None

    def as_dict(self):
        return {"id": self.id, "source": self.source, "text": self.text, "state": self.state, "created": self.created, "started": self.started,
                "ended": self.ended, "say": self.say, "calls": self.calls, "pending": self.pending, "summary": self.summary, "error": self.error,
                "note": self.note, "steps": self.steps, "brain": self.brain, "automation": self.automation}


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
        if backoff is BACKOFF and os.environ.get("SWARMBOX_TEST_BUS_BACKOFF"):
            parts = [float(x) for x in os.environ["SWARMBOX_TEST_BUS_BACKOFF"].split(",") if x.strip()]
            if parts:
                backoff = (max(0.005, parts[0]), max(0.005, parts[-1]))
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
        self.runtime = brain.Runtime(log=self.log, popen=popen or subprocess.Popen, clock=clock)
        self.steering = []             # goals given to the running goal (steer.jsonl of its folder), until it takes them or ends
        self.auto_goal = {}            # automation id -> the id of its last goal (one goal of an automation at a time)
        self.watch = automod.TriggerWatch()
        self.watcher = None
        self.sandbox_state = self.sandbox()
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
            self.watcher = threading.Thread(target=self.watch_automations, name="sysop-automations", daemon=True)
            self.watcher.start()
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
            try:
                self.runtime.close()
            except Exception as e:
                self.log("cannot end the brain: %r" % e)
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
                cur = self.current
                if (cur is not None and cur.state in ("running", "waiting_approval") and source in INTERACTIVE and cur.source in INTERACTIVE
                        and not self.queue):
                    goal.text = text.strip()
                    goal.steer_into = cur.id
                    self.steering.append(goal)
                elif len(self.queue) >= self.cfg.max_goals:
                    reason = "the queue is full (%d goals wait): this goal was dropped" % self.cfg.max_goals
                else:
                    goal.text = text.strip()
                    self.queue.append(goal)
            if goal.steer_into:
                try:
                    ipc.append_jsonl(os.path.join(self.paths.goal_dir(goal.steer_into), "steer.jsonl"),
                                     {"id": goal.id, "t": self.clock(), "source": source, "text": goal.text})
                except OSError as e:
                    self.log("goal %s: cannot pass it to the running goal (%s): it waits for its turn" % (gid, e))
                    with self.cond:
                        self.steering.remove(goal)
                        self.queue.append(goal)
                        goal.steer_into = None
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
                               "max_steps": self.cfg.max_steps, "max_seconds": self.cfg.max_seconds, "max_goals": self.cfg.max_goals,
                               "autocontext": bool(getattr(self.cfg, "autocontext", True)), "sandbox": self.sandbox_state}}
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
                dropped += self.steering
                self.steering = []
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
        if self.steering:
            self.settle_steering(goal, final=False)
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

    def sandbox(self):
        """landlock | off (SWARMBOX_SYSOP_SANDBOX=0) | unavailable (no Landlock in this kernel or container)"""
        if os.environ.get("SWARMBOX_SYSOP_SANDBOX", "1") == "0":
            return "off"
        return "landlock" if landlock.abi() else "unavailable"

    def execute(self, goal):
        aud = self.audit.bind(goal.id, goal.source)
        self.current, self.stop_current = goal, False
        goal.state, goal.started = "running", self.clock()
        gdir = self.paths.goal_dir(goal.id)
        events = eventsmod.EventLog(os.path.join(gdir, "events.jsonl"), self.clock, self.log)
        events.emit("state", state="running", source=goal.source, text=goal.text[:4000])
        host = None
        try:
            self.status()             # first: whoever sees the goal running (state.json) finds it current in status.json too
            self.write_goal(goal)
            aud.append("state", state="running")
            deadline = (goal.started + self.cfg.max_seconds) if (self.cfg.max_seconds and self.cfg.max_seconds > 0) else None
            ctx = os.path.join(gdir, "context.json")
            ipc.write_json(ctx, {"goal": goal.id, "source": goal.source, "goal_dir": gdir, "audit": self.paths.audit,
                                 "autonomy": self.cfg.autonomy, "countdown": self.cfg.countdown, "approval_timeout": self.cfg.approval_timeout,
                                 "max_steps": self.cfg.max_steps, "deadline": deadline})
            resident = brain.is_resident(self.cfg.brain)
            # the MCP server runs here, outside the brain's sandbox; the brain starts only the proxy that reaches its socket. One server
            # per goal, also for a resident brain: its proxy reconnects to the stable socket of the brain at each goal
            sock = self.paths.mcp_socket("brain" if resident else goal.id)
            host = brain.McpHost(sock, brain.server_env(ctx, self.paths, self.libdir), events, self.log)
            host.start()
            prev_sid = history.session_id(self.paths)
            opts = brain.options(self.cfg.brain)
            resuming = bool(prev_sid and opts["resume"])
            home = brain.prepare_home(self.paths.brain_home)
            if resident:
                start_error = self.ensure_runtime(prev_sid, opts, home, sock)
            else:
                start_error = None
                mcp = os.path.join(gdir, "mcp.json")
                brain.write_mcp_config(mcp, ctx, self.paths, self.libdir, socket_path=sock)
                pfile = os.path.join(gdir, "system-prompt.txt")
                with open(pfile, "w", encoding="utf-8") as f:
                    f.write(brain.system_prompt(goal.source, self.cfg.max_steps, self.cfg.max_seconds, self.cfg.autonomy))
                os.chmod(pfile, 0o600)
                argv, env = brain.build(self.cfg, gdir, mcp, goal.source, pfile, session_id=prev_sid)
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
            # Pre-seed a fresh, nonce-framed workspace snapshot + conversation history so the brain has immediate awareness
            # without spending Turn 1 calling box_state. When resuming a persistent Claude Code session, skip the lossy
            # text history block since the session already holds the full conversation and prompt cache.
            parts = []
            if os.environ.get("SWARMBOX_SYSOP_PRESEED", "1") != "0":
                try:
                    ws = tabsclient.Tabs(read_timeout=5.0).box_state("workspace")
                    if isinstance(ws, dict) and ("folders" in ws or "shells" in ws):
                        parts.append(mcpserver.format_box_state(ws, "workspace"))
                except Exception:
                    pass
            if not resuming:
                try:
                    before = history.conversation(history.load(self.paths), goal.id, self.clock(), since=history.since(self.paths))
                except Exception as e:      # a damaged folder of an old goal must not stop this one
                    self.log("goal %s: no conversation so far (%r)" % (goal.id, e))
                    before = ""
                if before:
                    parts.append(before)
            extra = self.memory_block()
            if extra:
                parts.append(extra)
            note = history.stop_note(self.paths) if resuming else ""
            if note:
                # the session of a stopped goal may hold a call that ran as refused (docs/sysop-brain-design.md 7): the host's record wins
                parts.append("[note from the host: the previous goal was stopped by the user. These actions DID run (or failed) whatever your "
                             "own record of that goal says; do not run them again unless the user asks:\n" + note + "\n]")
            history.save_stop_note(self.paths, "")
            if resident:
                # the system prompt of a resident brain is fixed for the life of its process: the source of each goal comes with it,
                # first, so a message never starts with a slash command either
                heard = "[" + brain.source_note(goal.source) + "]\n\n" + "\n\n".join(parts + ["The goal now (" + goal.source + "):\n" + goal.text])
            elif parts:
                heard = "\n\n".join(parts) + "\n\nThe goal now (" + goal.source + "):\n" + goal.text
            else:
                heard = goal.text
            if resident and start_error:
                res = brain.Result("failed", start_error)
            elif resident:
                on_start(self.runtime.proc.pid)
                res = self.runtime.run_goal(self.cfg, heard, gdir, stop_check, lambda: self.refresh(goal), deadline, events, opts,
                                            clock=self.clock, log=self.log)
            else:
                res = brain.run(self.cfg, heard, goal.source, gdir, argv, env, stop_check, lambda: self.refresh(goal), deadline,
                                clock=self.clock, on_start=on_start, opts=opts, home=home, events=events, sandbox=self.sandbox() != "off",
                                log=self.log, **kw)
            if res.session_id:
                history.save_session_id(self.paths, res.session_id)
            elif resuming and res.outcome == "failed" and re.search(r"session|resume|conversation", res.error or "", re.I):
                # Stale/missing persistent session: clear it so the next turn starts cleanly.
                history.save_session_id(self.paths, "")
        except brain.McpHostError as e:
            self.log("goal %s: %s" % (goal.id, e))
            res = brain.Result("failed", "the MCP server of the goal could not start: %s" % e)
        except Exception as e:             # a bug here must not kill the service: this goal fails, the next one runs
            self.log("goal %s: internal error: %r" % (goal.id, e))
            res = brain.Result("failed", explain(e))
        finally:
            if host is not None:
                host.stop()
        goal.state, goal.ended, goal.error, goal.note = res.outcome, self.clock(), res.error, res.note
        self.settle_steering(goal, final=True)
        if self.stopping and res.outcome == "stopped":
            goal.error = "the sysop service was stopped"
        if res.summary:
            goal.summary = res.summary
        goal.brain.update({"exit": res.exit_code, "turns": res.turns, "cost": res.cost})
        if res.session_id:
            goal.brain["session_id"] = res.session_id
        goal.pending = None
        for name in ("pending_action.json", "decision.json"):
            ipc.remove(os.path.join(gdir, name))
        if res.outcome == "failed" and disk_low(gdir):
            goal.error = (goal.error + " " if goal.error else "") + "(the disk of the box is almost full: free some space)"
        # the last event of the stream before the state.json that ends the goal: whoever sees the goal over (the panel, a test) reads its
        # stream whole, the final state included (written the other way round, a reader under load saw "stopped" and a stream without it)
        events.emit("state", state=goal.state, error=goal.error or "", summary=(goal.summary or "")[:8000])
        events.close()
        try:
            self.refresh_final(goal)
        except Exception as e:       # not only OSError: the end of one goal must never end the service
            self.log("cannot write the end of goal %s: %r" % (goal.id, e))
            self.unwritten[goal.id] = goal
        if goal.state == "stopped":
            try:
                history.save_stop_note(self.paths, history.describe_calls(ipc.read_jsonl(os.path.join(gdir, "calls.jsonl"))))
            except Exception as e:
                self.log("goal %s: cannot keep the stop note: %r" % (goal.id, e))
        aud.append("brain", **res.as_dict(), note=res.note)
        aud.append("state", state=goal.state, summary=goal.summary, error=goal.error)
        self.log("goal %s: %s%s" % (goal.id, goal.state, (" (%s)" % goal.error) if goal.error else ""))
        self.current, self.stop_current = None, False

    # ---- steering (docs/sysop-automations-design.md 6)
    def settle_steering(self, goal, final):
        """The goals given to `goal` while it ran: one the brain took (steer.delivered.json) ends done; at the end of `goal`, one it never
        took runs as a goal of its own, first in the queue."""
        got = ipc.read_json(os.path.join(self.paths.goal_dir(goal.id), "steer.delivered.json"))
        taken = set(got.get("ids") or []) if isinstance(got, dict) else set()
        with self.cond:
            mine = [g for g in self.steering if g.steer_into == goal.id]
            done = [g for g in mine if g.id in taken]
            back = [g for g in mine if g.id not in taken] if final else []
            self.steering = [g for g in self.steering if g not in done and g not in back]
            for g in reversed(back):
                g.steer_into = None
                self.queue.appendleft(g)
            if back:
                self.cond.notify_all()
        for g in done:
            g.state, g.ended, g.started = "done", self.clock(), g.created
            g.summary = "Passed to the goal that was running."
            g.note = "steered into %s" % goal.id
            self.write_goal(g)
            self.audit.bind(g.id, g.source).append("state", state="done", why="given to the running goal %s" % goal.id)
        for g in back:
            self.audit.bind(g.id, g.source).append("state", state="queued", why="the running goal ended before it took it")
        if done or back:
            self.status()

    def memory_block(self):
        """What the brain keeps outside its session, at the start of each goal: its notes (names and first lines) and the automations."""
        out = []
        try:
            idx = notes.index(self.paths)
        except OSError:
            idx = ""
        if idx:
            out.append("[your notes (the `note` tool reads one in full):\n" + idx + "\n]")
        try:
            live = [automod.describe(x) for x in automod.load(self.paths)["items"] if x.get("state") in ("active", "paused")]
        except (OSError, ValueError):
            live = []
        if live:
            out.append("[your automations (schedule / trigger list, cancel, pause, resume):\n" + "\n".join("- " + x for x in live[:20]) + "\n]")
        return "\n\n".join(out)

    # ---- automations (docs/sysop-automations-design.md 2)
    def auto_busy(self, aid):
        """True when the last goal of an automation still waits or runs."""
        gid = self.auto_goal.get(aid)
        if not gid:
            return False
        with self.cond:
            if any(g.id == gid for g in self.queue):
                return True
        return self.current is not None and self.current.id == gid

    def auto_event(self, x, phase, **fields):
        from .autoname import append_system_event
        append_system_event(os.path.join(self.paths.state, "system_events.jsonl"), "automation", clock=self.clock, phase=phase, auto=x["id"],
                            text=automod.describe(x), **fields)
        self.audit.append("automation", action=phase, id=x["id"], **fields)

    def enqueue_auto(self, x, reason):
        """A goal of the automation x, in the queue. False when the queue is full (the run is skipped)."""
        source = "schedule" if x.get("kind") == "schedule" else "trigger"
        gid = self.new_id("%s-%s-%d" % (x["id"], source[0], int(self.clock())))
        goal = Goal(gid, source, automod.frame(x, reason, self.clock()), self.clock)
        goal.automation = x["id"]
        pathsmod.private_dir(self.paths.goal_dir(gid))
        with self.cond:
            if len(self.queue) >= self.cfg.max_goals:
                return False
            self.queue.append(goal)
            self.auto_goal[x["id"]] = gid
            self.cond.notify_all()
        aud = self.audit.bind(gid, source)
        aud.append("goal", text=goal.text, automation=x["id"])
        self.write_goal(goal)
        aud.append("state", state="queued", queue=len(self.queue))
        self.status()
        return True

    def run_schedules(self):
        """Fire the schedules that are due and end what is over. The record is read without the lock; it is taken (and the file written)
        only when something is due or over, so a quiet box writes nothing."""
        now = self.clock()
        try:
            look = automod.load(self.paths)
        except (OSError, ValueError):
            return
        if not automod.due(look, now) and not automod.over(look, now):
            return
        fired, ended, skipped = [], [], []

        def fn(d):
            ended.extend(automod.expire(d, now))
            for x in automod.due(d, now):
                if self.auto_busy(x["id"]):
                    automod.skip_schedule(x, now)
                    skipped.append(dict(x))
                    continue
                ok = self.enqueue_auto(x, "")
                if ok:
                    automod.ran(x, now)
                    fired.append(dict(x))
                else:
                    automod.skip_schedule(x, now)
                    skipped.append(dict(x, why_skipped="the queue is full"))
                if x.get("state") == "ended":
                    ended.append(x)
            automod.prune(d, now)
        try:
            automod.update(self.paths, fn)
        except (OSError, ValueError) as e:
            self.log("automations: %s" % e)
            return
        for x in fired:
            self.auto_event(x, "fired")
        for x in skipped:
            self.auto_event(x, "skipped", why=x.get("why_skipped") or "its last goal still runs")
        for x in ended:
            self.auto_event(x, "ended", why=x.get("why", ""))
            self.watch.forget(x["id"])

    def watch_automations(self):
        """The thread of the automations, apart from the goals (a schedule is due, and a tab changes, while a goal runs too): every
        TRIGGER_EVERY seconds the schedules that are due, and, while a trigger is active, a look at the tabs (and at the screen of a tab a
        text trigger watches). What fires becomes a goal of the queue."""
        tabs = tabsclient.Tabs(read_timeout=5.0)
        while not self.stopping:
            try:
                self.run_schedules()
            except Exception as e:
                self.log("schedules: %r" % e)
            try:
                self.look_triggers(tabs)
            except Exception as e:      # a look that fails (herdr-core away) is tried again at the next turn
                self.log("triggers: %r" % e)
            with self.cond:
                if not self.stopping:
                    self.cond.wait(TRIGGER_EVERY)

    def look_triggers(self, tabs):
        try:
            d = automod.load(self.paths)
        except (OSError, ValueError):
            return
        live = [x for x in d["items"] if x.get("kind") == "trigger" and x.get("state") == "active"]
        if not live:
            return
        rows = {t["tab"]: t for t in tabs.list_tabs() if isinstance(t, dict) and t.get("tab")}
        now = self.clock()
        hits = []
        for x in live:
            row = rows.get(x.get("tab"))
            screen = None
            if x.get("when") == "text" and row is not None:
                try:
                    screen = (tabs.screen(x["tab"]) or {}).get("text", "")
                except tabsclient.TabsError:
                    screen = None
            reason = self.watch.look(x, row, screen, now)
            if reason:
                hits.append((x["id"], reason))
            elif row is None and x.get("when") != "gone":
                hits.append((x["id"], None))       # its tab is gone: the trigger ends
        if not hits:
            return
        fired, ended, skipped = [], [], []

        def fn(d2):
            for aid, reason in hits:
                try:
                    x = automod.find(d2, aid)
                except automod.AutomationError:
                    continue
                if x.get("state") != "active":
                    continue
                if reason is None:
                    automod.end(x, now, "its tab is gone")
                    ended.append(dict(x))
                    continue
                if self.auto_busy(aid) or not self.enqueue_auto(x, reason):
                    x["last"] = now          # the cooldown starts again: a busy automation does not pile up goals
                    skipped.append(dict(x))
                    continue
                automod.ran(x, now)
                fired.append(dict(x, reason=reason))
                if x.get("state") == "ended":
                    ended.append(dict(x))
        automod.update(self.paths, fn)
        for x in fired:
            self.auto_event(x, "fired", reason=x["reason"])
        for x in skipped:
            self.auto_event(x, "skipped", why="its last goal still runs")
        for x in ended:
            self.auto_event(x, "ended", why=x.get("why", ""))
            self.watch.forget(x["id"])

    def ensure_runtime(self, sid, opts, home, sock):
        """The resident brain on the conversation's session (brain.Runtime.ensure). None, or why it cannot start."""
        return self.runtime.ensure(self.cfg, opts, home, sock, self.paths, self.libdir, sid, sandbox=self.sandbox() != "off")

    def refresh_final(self, goal):
        gdir = self.paths.goal_dir(goal.id)
        goal.say = [{"t": x.get("t"), "text": x.get("text")} for x in ipc.read_jsonl(os.path.join(gdir, "say.jsonl"))][-20:]
        calls = ipc.read_jsonl(os.path.join(gdir, "calls.jsonl"))
        goal.steps = sum(1 for c in calls if c.get("tool") not in FREE_TOOLS)
        goal.calls = calls[-RECENT_CALLS:]
        self.write_goal(goal)
