"""The audit file: events.jsonl, append-only, one JSON object per line, mode 0600, in the private state folder.

Every goal, tool call, decision and result of the sysop is a line: {"t": epoch, "time": ISO, "goal": id, "source": label, "event": name, ...}.
Events: goal (received), rejected, state (queued running waiting_approval done stopped failed), call (a tool call of the brain, with the
policy verdict), decision (what happened to a run or input: allowed, vetoed, approved, denied, timed_out, blocked), result (what the tool
answered), say, brain (the end of the brain: exit code, turns, cost), lost (a goal that a restart dropped).
The file is opened with O_APPEND and each line is ONE write, so the service and the MCP server of a goal (two processes) never mix lines.
Long strings are cut (MAX_STRING) so a screen cannot make the file grow without bound; the cut says how long the text was.

THE LIMIT. Nothing here ever rewrites or truncates a file. Past MAX_FILE (8 MiB) the file is renamed to events.jsonl.1, the older ones move up
(.1 to .2 and so on) and a new one starts; only KEEP (3) old files are kept, the oldest is deleted. So the audit never takes more than
(KEEP + 1) * MAX_FILE = 32 MiB of the workspace, the last 24 to 32 MiB of events (some 20 000 goals). Two processes write (the service and the MCP
server of a goal), so the rotation holds a lock (events.jsonl.lock, an flock: the kernel drops it however the process dies) and looks at the size again
under it: two writers that see the file too big rotate it once, never twice (which would have thrown a whole generation away).
A line that cannot be written (the disk is full) does not stop the service: append() returns False, says so once a minute on standard error (the log of
the service) and goes on. A tool call that TYPES (run, input) is refused by the MCP server when its own audit line cannot be written (require()): nothing
is typed that the audit cannot show.
"""
import errno
import fcntl
import json
import os
import sys
import time

MAX_STRING = 2000
MAX_FILE = 8 << 20        # events.jsonl is renamed to events.jsonl.1 past this
KEEP = 3                  # old files kept (.1 newest to .3 oldest): at most (KEEP + 1) * MAX_FILE on disk
WARN_EVERY = 60.0         # seconds between two messages about a line that could not be written
_last_warning = [0.0]


class AuditError(OSError):
    """a line the audit file could not take (require() raises it; append() only says False)"""


def _cut(v, depth=0):
    if isinstance(v, str):
        return v if len(v) <= MAX_STRING else v[:MAX_STRING] + "...[%d characters in all]" % len(v)
    if depth < 4 and isinstance(v, dict):
        return {str(k): _cut(x, depth + 1) for k, x in v.items()}
    if depth < 4 and isinstance(v, (list, tuple)):
        return [_cut(x, depth + 1) for x in v[:50]]
    return v


def _size(path):
    try:
        return os.stat(path).st_size
    except OSError:
        return 0


def generations(path):
    """the old files of an audit file, newest first: [(n, path)] for path.1, path.2 ..., whatever n"""
    d, base = os.path.split(path)
    out = []
    try:
        names = os.listdir(d or ".")
    except OSError:
        return out
    for name in names:
        head, _, tail = name.rpartition(".")
        if head == base and tail.isdigit() and int(tail) >= 1:
            out.append((int(tail), os.path.join(d, name)))
    return sorted(out)


def rotate(path, max_file=None, keep=None):
    """Move path to path.1 when it is bigger than max_file, the old ones up by one, and delete the ones past `keep`. Safe with several writers: an flock on
    path.lock, and the size is looked at again under it. True when it rotated."""
    max_file = MAX_FILE if max_file is None else max_file
    keep = KEEP if keep is None else keep
    lock = os.open(path + ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        did = False
        if _size(path) > max_file:
            for n, old in reversed(generations(path)):
                if n >= keep:
                    _unlink(old)
                else:
                    os.replace(old, "%s.%d" % (path, n + 1))
            os.replace(path, path + ".1")
            did = True
        for n, old in generations(path):            # whatever is past the limit (a smaller KEEP than before, a crash between two renames)
            if n > keep:
                _unlink(old)
        return did
    finally:
        os.close(lock)


def _unlink(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def _warn(path, err):
    now = time.time()
    if now - _last_warning[0] >= WARN_EVERY:
        _last_warning[0] = now
        try:
            print("sysop audit: cannot write %s: %s (the line is lost; the disk may be full)" % (path, err.strerror or err), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass


class Audit:
    def __init__(self, path, goal=None, source=None, clock=time.time):
        self.path, self.goal, self.source, self.clock = path, goal, source, clock

    def bind(self, goal, source):
        return Audit(self.path, goal, source, self.clock)

    def _line(self, event, fields):
        t = self.clock()
        rec = {"t": round(t, 3), "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int(t % 1 * 1000),
               "goal": self.goal, "source": self.source, "event": event}
        rec.update(_cut(fields))
        return (json.dumps(rec, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")

    def _write(self, line):
        if _size(self.path) > MAX_FILE:
            try:
                rotate(self.path)
            except OSError:
                pass                                  # a rotation that fails is tried at the next line; the line itself still goes in
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o600)
            n = os.write(fd, line)
            if n != len(line):
                raise OSError(errno.ENOSPC, "short write (%d of %d bytes)" % (n, len(line)))
        finally:
            os.close(fd)

    def append(self, event, **fields):
        """One line. Never raises: True when it was written, False when it was not (the disk is full, the folder is gone)."""
        try:
            self._write(self._line(event, fields))
            return True
        except (OSError, ValueError) as e:
            _warn(self.path, e if isinstance(e, OSError) else OSError(str(e)))
            return False

    def require(self, event, **fields):
        """append(), but raises AuditError when the line was not written: for what must not happen without a record (typing into a tab)."""
        try:
            self._write(self._line(event, fields))
        except (OSError, ValueError) as e:
            _warn(self.path, e if isinstance(e, OSError) else OSError(str(e)))
            raise AuditError(getattr(e, "errno", None) or errno.EIO, "the audit file cannot be written: %s" % (getattr(e, "strerror", None) or e)) from None


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
