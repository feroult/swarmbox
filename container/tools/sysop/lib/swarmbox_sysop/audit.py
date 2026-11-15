"""The audit file: events.jsonl, append-only, one JSON object per line, mode 0600, in the private state folder.

Every goal, tool call, decision and result of the sysop is a line: {"t": epoch, "time": ISO, "goal": id, "source": label, "event": name, ...}.
Events: goal (received), rejected, state (queued running waiting_approval done stopped failed), call (a tool call of the brain, with the
policy verdict), decision (what happened to a run or input: allowed, vetoed, approved, denied, timed_out, blocked), result (what the tool
answered), say, brain (the end of the brain: exit code, turns, cost), lost (a goal that a restart dropped).
The file is opened with O_APPEND and each line is ONE write, so the service and the MCP server of a goal (two processes) never mix lines.
Long strings are cut (MAX_STRING) so a screen cannot make the file grow without bound; the cut says how long the text was.
Nothing here ever rewrites or truncates the file; past MAX_FILE it is renamed to <file>.1 (the older .1 is replaced) and a new one starts.
"""
import json
import os
import time

MAX_STRING = 2000
MAX_FILE = 16 << 20       # events.jsonl is renamed to events.jsonl.1 past this (one generation), so a flood of goals cannot fill the disk


def _cut(v, depth=0):
    if isinstance(v, str):
        return v if len(v) <= MAX_STRING else v[:MAX_STRING] + "...[%d characters in all]" % len(v)
    if depth < 4 and isinstance(v, dict):
        return {str(k): _cut(x, depth + 1) for k, x in v.items()}
    if depth < 4 and isinstance(v, (list, tuple)):
        return [_cut(x, depth + 1) for x in v[:50]]
    return v


class Audit:
    def __init__(self, path, goal=None, source=None, clock=time.time):
        self.path, self.goal, self.source, self.clock = path, goal, source, clock

    def bind(self, goal, source):
        return Audit(self.path, goal, source, self.clock)

    def append(self, event, **fields):
        t = self.clock()
        rec = {"t": round(t, 3), "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int(t % 1 * 1000),
               "goal": self.goal, "source": self.source, "event": event}
        rec.update(_cut(fields))
        line = (json.dumps(rec, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        try:
            if os.stat(self.path).st_size > MAX_FILE:
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o600)
            os.write(fd, line)
        finally:
            os.close(fd)


def read(path):
    """The events of an audit file as a list of dicts (a damaged line is skipped); [] when there is no file."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return out
