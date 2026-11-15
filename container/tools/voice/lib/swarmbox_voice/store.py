"""Pending plans: what the service produced and the user has not yet confirmed.

PlanStore.add(plan, ...) -> id; PlanStore.take(id) -> the stored entry, once. Nothing reaches tmux without a take().
PlanStore.replace(plan, ...) is add() for the voice flow: it cancels every older pending plan first, in one step, so there is only ever
ONE pending plan (the panel shows exactly one). PlanStore.swap(id, plan, ...) replaces plan `id` by an edited one in one step (no moment
without a pending plan, so a panel never sees the plan "end" in the middle of an edit). PlanStore.current() is the pending plan and
PlanStore.wait_change(known, timeout) blocks until the pending plan is not `known` (a long poll).
- The id is random (128 bits) and the entry never leaves the service: confirm executes what is stored here, not what a client sends.
- One shot: take() removes the entry, so a second confirm of the same id fails (state "used"), as does a cancel after it.
- A TTL: after it the entry is gone (state "expired"). At most `limit` entries are pending; the oldest is dropped (state "expired").
take raises PlanError with code unknown (never issued or forgotten), used, cancelled or expired.
"""
import math
import secrets
import threading
import time

TTL = 120.0
LIMIT = 32
REMEMBER = 256


class PlanError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class PlanStore:
    def __init__(self, ttl=TTL, limit=LIMIT, clock=time.monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self._lock = threading.Lock()
        self._pending = {}   # id -> entry, in insertion order
        self._gone = {}      # id -> "used" | "cancelled" | "expired"

    def _forget(self, pid, state):
        self._gone[pid] = state
        while len(self._gone) > REMEMBER:
            self._gone.pop(next(iter(self._gone)))

    def _sweep(self):
        now = self.clock()
        for pid in [k for k, e in self._pending.items() if e["expires"] <= now]:
            del self._pending[pid]
            self._forget(pid, "expired")

    def _add(self, plan, extra):
        while len(self._pending) >= self.limit:
            old = next(iter(self._pending))
            del self._pending[old]
            self._forget(old, "expired")
        pid = secrets.token_urlsafe(16)
        self._pending[pid] = dict(extra, plan=plan, created=self.clock(), expires=self.clock() + self.ttl)
        return pid

    def add(self, plan, **extra):
        """Store a validated plan ({say, actions}); returns the id. extra (text, risk, ...) is kept with it."""
        with self._lock:
            self._sweep()
            return self._add(plan, extra)

    def replace(self, plan, **extra):
        """Cancel every pending plan and store this one, in one step; returns the id."""
        with self._lock:
            self._sweep()
            for old in list(self._pending):
                del self._pending[old]
                self._forget(old, "cancelled")
            return self._add(plan, extra)

    def swap(self, pid, plan, **extra):
        """Replace the pending plan `pid` by `plan` in one step (an edit). PlanError when `pid` is not pending."""
        with self._lock:
            self._sweep()
            entry = self._pending.pop(pid, None) if isinstance(pid, str) else None
            if entry is None:
                why = self._gone.get(pid) if isinstance(pid, str) else None
            else:
                self._forget(pid, "cancelled")
                return self._add(plan, extra)
        if why == "expired":
            raise PlanError("expired", "the plan expired; ask again")
        if why in ("used", "cancelled"):
            raise PlanError(why, "the plan was already %s" % why)
        raise PlanError("unknown", "unknown plan")

    def take(self, pid, state="used"):
        """Remove and return the entry. state is what a later take of the same id reports (used or cancelled)."""
        with self._lock:
            self._sweep()
            entry = self._pending.pop(pid, None) if isinstance(pid, str) else None
            if entry is not None:
                self._forget(pid, state)
                return entry
            why = self._gone.get(pid) if isinstance(pid, str) else None
        if why == "expired":
            raise PlanError("expired", "the plan expired; ask again")
        if why in ("used", "cancelled"):
            raise PlanError(why, "the plan was already %s" % why)
        raise PlanError("unknown", "unknown plan")

    def peek(self, pid):
        """The pending entry without removing it, or None."""
        with self._lock:
            self._sweep()
            return self._pending.get(pid) if isinstance(pid, str) else None

    def pending(self):
        with self._lock:
            self._sweep()
            return len(self._pending)

    def current(self):
        """(id, entry) of the newest pending plan, or None."""
        with self._lock:
            self._sweep()
            if not self._pending:
                return None
            pid = next(reversed(self._pending))
            return pid, self._pending[pid]

    def remaining(self, entry):
        """Whole seconds left before the entry expires (at least 0)."""
        return max(0, int(math.ceil(entry["expires"] - self.clock())))

    def wait_change(self, known, timeout, step=0.1):
        """The current (id, entry) once its id differs from `known` ("" for none), or after `timeout` seconds whatever it is.
        It polls the store (an expiry is a change of the clock, not an event), so a test clock works too."""
        end = _real_time() + max(0.0, timeout)
        while True:
            cur = self.current()
            if (cur[0] if cur else "") != known or _real_time() >= end:
                return cur
            _sleep(min(step, max(0.0, end - _real_time())))


_real_time = time.monotonic
_sleep = time.sleep
