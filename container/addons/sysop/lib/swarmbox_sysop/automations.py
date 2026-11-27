"""The sysop's automations (docs/sysop-automations-design.md 2): goals at a time (schedule) and goals when a tab changes (trigger).

THE RECORD is <state>/sysop/automations.json, changed under an flock (automations.lock) by the MCP server (the brain creates one), the CLI
and the Web Studio (pause, resume, cancel) and the service (it fires them). One writer at a time, whole file replaced (ipc.write_json).

THE TIMES. A schedule has `cron` (five fields in the local time zone: minute hour day month weekday; `*`, lists, ranges, steps; weekday 0 or 7 is
Sunday; when both day and weekday are restricted either one matches, as in cron), `every` (seconds, at least MIN_EVERY) or `at` (once).
`next` is the next time it is due. A trigger has a tab and `when`: blocked | idle | working | done (the state the tab reports, OSC 7501),
text (a regular expression on its screen) or gone (the tab closes); it fires on a change, at most once per `cooldown` seconds.

Every automation ends by itself: at `expires`, after `max_runs` runs, after its one run (`at`), or (a trigger) when its tab is gone.
"""
import datetime
import fcntl
import os
import re
import time

from . import ipc

MIN_EVERY = 60
MIN_COOLDOWN = 30
DEFAULT_COOLDOWN = 300
MAX_ACTIVE = 20
MAX_PROMPT = 2000
DAY = 86400
DEFAULT_EXPIRES = {"schedule": 7 * DAY, "trigger": DAY}
MAX_EXPIRES = 30 * DAY
WHEN = ("blocked", "idle", "working", "done", "text", "gone")
STATES = ("active", "paused", "ended")


class AutomationError(ValueError):
    """A request that cannot become an automation: the text goes back to the brain or the user."""


# ---- the record
def path(paths):
    return os.path.join(paths.state, "automations.json")


def load(paths):
    d = ipc.read_json(path(paths))
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return {"seq": 0, "items": []}
    d.setdefault("seq", 0)
    d["items"] = [x for x in d["items"] if isinstance(x, dict) and x.get("id")]
    return d


def update(paths, fn):
    """Run fn(record) under the lock and write the record when fn returns without raising; fn's value is returned."""
    os.makedirs(paths.state, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(paths.state, "automations.lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        d = load(paths)
        out = fn(d)
        for x in d["items"]:
            x["desc"] = describe(x)          # the panel shows this line as it is: one wording, written here
        ipc.write_json(path(paths), d)
        return out
    finally:
        os.close(fd)


def active(d):
    return [x for x in d["items"] if x.get("state") == "active"]


def find(d, aid):
    for x in d["items"]:
        if x.get("id") == aid:
            return x
    raise AutomationError("no automation %r (the automations are: %s)" % (aid, ", ".join(x["id"] for x in d["items"] if x.get("state") != "ended") or "none"))


def prune(d, now, keep=40):
    """Ended automations are kept for the panel for a while: the newest `keep`, none older than a week."""
    ended = [x for x in d["items"] if x.get("state") == "ended"]
    drop = {x["id"] for x in ended if now - (x.get("ended") or 0) > 7 * DAY}
    drop |= {x["id"] for x in sorted(ended, key=lambda x: x.get("ended") or 0)[:-keep]} if len(ended) > keep else set()
    d["items"] = [x for x in d["items"] if x["id"] not in drop]


# ---- durations and times
_DUR = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?|d|days?)?\s*$", re.I)


def duration(v, name="duration"):
    """Seconds of 90, "90s", "10m", "2h", "1d"."""
    if isinstance(v, bool):
        raise AutomationError("%s must be a duration like 90s, 10m, 2h or 1d" % name)
    if isinstance(v, (int, float)):
        return float(v)
    m = _DUR.match(str(v or ""))
    if not m:
        raise AutomationError("%s must be a duration like 90s, 10m, 2h or 1d, not %r" % (name, v))
    n, unit = float(m.group(1)), (m.group(2) or "s").lower()
    return n * {"s": 1, "m": 60, "h": 3600, "d": DAY}[unit[0]]


def when_at(v, now):
    """The epoch of "in 20m", "14:10" (today, else tomorrow), "2026-11-27 14:10" or an ISO time, in the local time zone."""
    s = str(v or "").strip()
    if not s:
        raise AutomationError("at must be a time like 14:10, 2026-11-27 14:10 or in 20m")
    if s.lower().startswith("in "):
        return now + duration(s[3:], "at")
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    base = datetime.datetime.fromtimestamp(now)
    if m:
        t = base.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if t.timestamp() <= now:
            t += datetime.timedelta(days=1)
        return t.timestamp()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            pass
    raise AutomationError("at must be a time like 14:10, 2026-11-27 14:10 or in 20m, not %r" % s)


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


# ---- cron
_FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31), ("month", 1, 12), ("weekday", 0, 7))


def _field(text, name, lo, hi):
    out = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) < 1:
                raise AutomationError("cron: the step of the %s field must be a whole number above 0" % name)
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif re.fullmatch(r"\d+-\d+", part):
            a, b = (int(x) for x in part.split("-"))
        elif part.isdigit():
            a = b = int(part)
            if step > 1:
                b = hi
        else:
            raise AutomationError("cron: %r is not a value of the %s field" % (part, name))
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise AutomationError("cron: the %s field takes %d to %d" % (name, lo, hi))
        out.update(range(a, b + 1, step))
    return out


def parse_cron(text):
    words = str(text or "").split()
    if len(words) != 5:
        raise AutomationError("cron takes five fields: minute hour day month weekday (for example */10 * * * *)")
    sets = [_field(w, n, lo, hi) for w, (n, lo, hi) in zip(words, _FIELDS)]
    if 7 in sets[4]:
        sets[4] = (sets[4] - {7}) | {0}
    return {"min": sets[0], "hour": sets[1], "day": sets[2], "month": sets[3], "wday": sets[4],
            "day_any": words[2] == "*", "wday_any": words[4] == "*"}


def cron_next(text, after):
    """The first time after `after` (an epoch) that the cron line matches, in the local time zone; None within 400 days."""
    c = parse_cron(text)
    start = datetime.datetime.fromtimestamp(after).replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    day = start.replace(hour=0, minute=0)
    for _ in range(400):
        if day.month in c["month"]:
            dom = day.day in c["day"]
            dow = ((day.weekday() + 1) % 7) in c["wday"]          # cron: 0 is Sunday; Python: 0 is Monday
            if c["day_any"] and c["wday_any"]:
                ok = True
            elif c["day_any"]:
                ok = dow
            elif c["wday_any"]:
                ok = dom
            else:
                ok = dom or dow
            if ok:
                for h in sorted(c["hour"]):
                    for mi in sorted(c["min"]):
                        t = day.replace(hour=h, minute=mi)
                        if t >= start:
                            return t.timestamp()
        day += datetime.timedelta(days=1)
    return None


def cron_period(text):
    """The shortest gap between two times of a cron line over the next two days (to keep the MIN_EVERY floor)."""
    t = time.time()
    times = []
    for _ in range(4):
        n = cron_next(text, t)
        if n is None:
            break
        times.append(n)
        t = n
    return min((b - a for a, b in zip(times, times[1:])), default=DAY)


# ---- create, change
def describe(x):
    """One line for a person and for the brain."""
    if x.get("kind") == "schedule":
        if x.get("cron"):
            how = "cron %s" % x["cron"]
        elif x.get("every"):
            how = "every %s" % human(x["every"])
        else:
            how = "once at %s" % stamp(x.get("at"))
    else:
        how = "when %s %s" % (x.get("label") or x.get("tab"), "shows /%s/" % x.get("text") if x.get("when") == "text" else
                              "goes away" if x.get("when") == "gone" else "becomes %s" % x.get("when"))
    runs = "%d run%s" % (x.get("runs", 0), "" if x.get("runs", 0) == 1 else "s") + (" of %d" % x["max_runs"] if x.get("max_runs") else "")
    nxt = (", next %s" % stamp(x["next"])) if x.get("kind") == "schedule" and x.get("next") and x.get("state") == "active" else ""
    end = x.get("why") if x.get("state") == "ended" else "until %s" % stamp(x.get("expires"))
    return "%s [%s] %s, %s%s, %s: %s" % (x["id"], x.get("state"), how, runs, nxt, end, x.get("prompt", "")[:200])


def human(seconds):
    s = int(seconds)
    for unit, n in (("d", DAY), ("h", 3600), ("min", 60)):
        if s >= n and s % n == 0:
            return "%d %s" % (s // n, unit)
    return "%d s" % s


def new_schedule(d, now, prompt, cron=None, every=None, at=None, expires=None, max_runs=0, goal="", source=""):
    prompt = _prompt(prompt)
    given = [k for k, v in (("cron", cron), ("every", every), ("at", at)) if v not in (None, "")]
    if len(given) != 1:
        raise AutomationError("a schedule takes exactly one of cron, every or at")
    x = {"kind": "schedule", "prompt": prompt}
    if cron:
        if cron_next(cron, now) is None:
            raise AutomationError("cron %r never matches" % cron)
        if cron_period(cron) < MIN_EVERY:
            raise AutomationError("cron %r runs more often than once a minute" % cron)
        x["cron"], x["next"] = " ".join(str(cron).split()), cron_next(cron, now)
    elif every not in (None, ""):
        sec = duration(every, "every")
        if sec < MIN_EVERY:
            raise AutomationError("every must be at least %d seconds" % MIN_EVERY)
        x["every"], x["next"] = sec, now + sec
    else:
        t = when_at(at, now)
        if t <= now:
            raise AutomationError("at %s is in the past" % stamp(t))
        x["at"], x["next"], max_runs = t, t, 1
    return _add(d, now, x, expires, max_runs, goal, source)


def new_trigger(d, now, prompt, tab, label, when, text=None, cooldown=None, expires=None, max_runs=0, goal="", source=""):
    prompt = _prompt(prompt)
    if when not in WHEN:
        raise AutomationError("when must be one of %s" % ", ".join(WHEN))
    x = {"kind": "trigger", "prompt": prompt, "tab": tab, "label": label or tab, "when": when}
    if when == "text":
        if not text:
            raise AutomationError("when=text needs text: a regular expression to look for on the screen")
        try:
            re.compile(text)
        except re.error as e:
            raise AutomationError("text is not a regular expression: %s" % e)
        x["text"] = str(text)[:200]
    cd = DEFAULT_COOLDOWN if cooldown in (None, "") else duration(cooldown, "cooldown")
    if cd < MIN_COOLDOWN:
        raise AutomationError("cooldown must be at least %d seconds" % MIN_COOLDOWN)
    x["cooldown"] = cd
    return _add(d, now, x, expires, max_runs, goal, source)


def _prompt(p):
    p = str(p or "").strip()
    if not p:
        raise AutomationError("prompt is required: what the sysop does when it runs")
    if len(p) > MAX_PROMPT:
        raise AutomationError("prompt has %d characters, at most %d" % (len(p), MAX_PROMPT))
    return p


def _add(d, now, x, expires, max_runs, goal, source):
    if len(active(d)) >= MAX_ACTIVE:
        raise AutomationError("there are already %d active automations: cancel one first" % MAX_ACTIVE)
    life = DEFAULT_EXPIRES[x["kind"]] if expires in (None, "") else duration(expires, "expires")
    if life <= 0 or life > MAX_EXPIRES:
        raise AutomationError("expires must be above 0 and at most 30d")
    if max_runs is None or isinstance(max_runs, bool) or not isinstance(max_runs, (int, float)) or max_runs < 0 or int(max_runs) != max_runs:
        raise AutomationError("max_runs must be a whole number, 0 for no limit")
    if x.get("next") and x["next"] > now + life:
        raise AutomationError("it would first run at %s, after it expires (%s): give a longer expires" % (stamp(x["next"]), stamp(now + life)))
    d["seq"] = int(d.get("seq") or 0) + 1
    x.update({"id": "a%d" % d["seq"], "state": "active", "created": now, "goal": goal, "source": source, "expires": now + life,
              "max_runs": int(max_runs), "runs": 0, "last": None})
    d["items"].append(x)
    return x


def set_state(d, aid, action, now, who="the user"):
    x = find(d, aid)
    if x.get("state") == "ended":
        raise AutomationError("%s has ended (%s)" % (aid, x.get("why", "")))
    if action == "cancel":
        end(x, now, "cancelled by %s" % who)
    elif action == "pause":
        x["state"] = "paused"
    elif action == "resume":
        x["state"] = "active"
        if x.get("kind") == "schedule" and x.get("next") and x["next"] < now:
            x["next"] = following(x, now)
            if x["next"] is None:
                end(x, now, "its time has passed")
    else:
        raise AutomationError("action must be create, list, cancel, pause or resume")
    return x


def end(x, now, why):
    x["state"], x["why"], x["ended"] = "ended", why, now


# ---- firing
def following(x, now):
    """The next time a schedule is due after `now`, or None (it has no next run)."""
    if x.get("cron"):
        return cron_next(x["cron"], now)
    if x.get("every"):
        n = (x.get("next") or now) + x["every"]
        while n <= now:                              # missed runs (the service was down) are not caught up: the next one is in the future
            n += x["every"]
        return n
    return None


def expire(d, now):
    """End what is over; returns the items that ended now."""
    out = []
    for x in d["items"]:
        if x.get("state") == "ended":
            continue
        if now >= (x.get("expires") or 0):
            end(x, now, "expired")
            out.append(x)
        elif x.get("max_runs") and x.get("runs", 0) >= x["max_runs"]:
            end(x, now, "done: %d run%s" % (x["runs"], "" if x["runs"] == 1 else "s"))
            out.append(x)
    return out


def over(d, now):
    """The automations that expire() would end now."""
    return [x for x in d["items"] if x.get("state") != "ended" and (now >= (x.get("expires") or 0)
                                                                     or (x.get("max_runs") and x.get("runs", 0) >= x["max_runs"]))]


def due(d, now):
    return [x for x in d["items"] if x.get("kind") == "schedule" and x.get("state") == "active" and x.get("next") and x["next"] <= now]


def ran(x, now):
    """Count a run: the schedule's next time, and the end of what is over."""
    x["runs"] = x.get("runs", 0) + 1
    x["last"] = now
    if x.get("kind") == "schedule":
        nxt = following(x, now)
        x["next"] = nxt
        if nxt is None:
            end(x, now, "done: it ran once" if x.get("at") else "no next time")
        elif nxt > x.get("expires", 0):
            end(x, now, "expired")
    if x.get("state") != "ended" and x.get("max_runs") and x["runs"] >= x["max_runs"]:
        end(x, now, "done: %d run%s" % (x["runs"], "" if x["runs"] == 1 else "s"))


def skip_schedule(x, now):
    """A schedule whose last goal still waits or runs: this time is skipped, the next one is set."""
    nxt = following(x, now)
    x["next"] = nxt
    if nxt is None or nxt > x.get("expires", 0):
        end(x, now, "expired")


class TriggerWatch:
    """What a trigger saw at its last look (in the service's memory; a restart starts again without firing: a change is only seen after a
    first look). look() returns the reason to fire, or None."""

    def __init__(self):
        self.seen = {}

    def look(self, x, row, screen, now):
        key = x["id"]
        was = self.seen.get(key)
        state = ((row or {}).get("status") or {}).get("state") if row else None
        present = None
        if x.get("when") == "text" and screen is not None:
            try:
                present = bool(re.search(x["text"], screen))
            except re.error:
                present = False
        self.seen[key] = {"gone": row is None, "state": state, "present": present}
        if was is None:
            return None
        if x.get("last") and now - x["last"] < x.get("cooldown", DEFAULT_COOLDOWN):
            return None
        w = x.get("when")
        if w == "gone":
            return "the tab went away" if row is None and not was["gone"] else None
        if row is None:
            return None
        if w == "text":
            return ("the text /%s/ appeared on the screen" % x["text"]) if present and was["present"] is False else None
        return ("the tab became %s (it was %s)" % (w, was["state"] or "unknown")) if state == w and was["state"] != w and not was["gone"] else None

    def forget(self, aid):
        self.seen.pop(aid, None)


def frame(x, reason, now):
    """The text of the goal an automation starts."""
    head = "[automation %s (%s, run %d%s, until %s)%s]" % (
        x["id"], describe(x).split("] ", 1)[1].split(", ")[0], x.get("runs", 0) + 1, " of %d" % x["max_runs"] if x.get("max_runs") else "",
        stamp(x.get("expires")), (": " + reason) if reason else "")
    return head + "\n" + x["prompt"]

