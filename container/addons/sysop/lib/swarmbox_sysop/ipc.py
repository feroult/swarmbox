"""The files the sysop service, the MCP server of a goal and the panel share. Every write is atomic (a temporary file in the same folder,
then rename), mode 0600, so a reader sees the old file or the new one, never half of it. A reader that finds nothing, or a damaged file,
treats it as "not there".

In the run folder (paths.Paths.run):
  status.json        written by the service: {"pid", "started", "updated", "bus": "connected"|"down", "current": goal id or null,
                     "queue": [{"id", "source", "text", "queued"}], "settings": {...}, "rejected": N, "version"}
  stop.request       written by `swarmbox-sysop stop` and by the panel's stop key: {"goal": id or null (the running one and the queue), "time"}.
                     The service takes it (reads and deletes it) within 0.2 s, kills the process group of the brain and ends the goal as `stopped`.
In the goal folder (state/goals/<id>/):
  state.json         written by the service only: {"id", "source", "text", "state", "created", "started", "ended", "say": [{"t", "text"}],
                     "calls": the last 12 [{"t", "tool", "args", "verdict", "is_error", "summary"}], "pending": the pending action or null,
                     "summary", "error", "note", "steps", "brain": {"pid", "exit", "turns", "cost"}}.
                     state is queued | running | waiting_approval | done | stopped | failed
  context.json       what the MCP server needs (settings of the policy, the budgets, the deadline); written before the brain starts
  calls.jsonl, say.jsonl, done.json   appended by the MCP server (calls and says as they happen; done once)
  pending_action.json  written by the MCP server when a run or input must wait for the user:
                     {"id": "p1", "goal", "tab": "@3", "label": "1:api", "kind": "run"|"input", "text", "risk": "low"|"medium"|"high",
                      "reasons": [...], "mode": "veto" (a countdown: it is sent at the deadline unless vetoed) |
                      "approve" (it is NOT sent unless approved before the deadline), "created", "deadline"}   (epochs, seconds)
  decision.json      written by the PANEL: {"id": the id of the pending action, "decision": "approve" | "deny" | "veto", "by": "panel", "word": "run"}.
                     approve is the word `run` typed in the panel: for mode approve the file MUST carry "word": "run" (the MCP server checks it and
                     ignores an approval without it); in mode veto an approve sends the action now. veto is the key `c` in a countdown, deny
                     refuses an approval. A decision with another id, or another word in "decision", is ignored. The MCP server deletes both
                     files when it is done.
  stopped            created by the service when the goal is stopped; the MCP server refuses every call once it exists
  events.jsonl       the live log of the goal (events.py): one event per line with a growing `seq`, written by the service only (the brain's
                     output through its adapter, the MCP server's events, the states). The Web Studio tails it.
  stream.jsonl, brain.err   the brain's raw standard output (the audit stream, read by the service through a pipe) and its error output
In the run folder, per goal: mcp-<hash>.sock, the socket of the goal's MCP server (run by the service, outside the brain's sandbox), for the
one connection of the brain's proxy; removed once it connected.
In the state folder: brain/, the brain's own home (HOME, its configuration folder, TMPDIR, its working directory), kept across goals.
"""
import json
import os
import tempfile
import time


def write_json(path, obj):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=True, separators=(",", ":"))      # ASCII: a lone surrogate (a goal with a byte that is not UTF-8) cannot raise
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_text(path, limit=2000):
    """The text of a small file, or "" when there is none"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def remove(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def append_jsonl(path, obj):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, (json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii"))
    finally:
        os.close(fd)


def read_jsonl(path, last=None):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out[-last:] if last else out


def request_stop(paths, goal=None):
    """The stop key: ask the service to end the running goal (goal=None: it and the whole queue)."""
    write_json(paths.stop_request, {"goal": goal, "time": time.time()})


def take_stop(paths):
    """The stop request, once (it is deleted), or None. A damaged file still means "stop everything": the stop key never fails silently."""
    exists = os.path.exists(paths.stop_request)
    req = read_json(paths.stop_request) if exists else None
    if exists:
        remove(paths.stop_request)
    if isinstance(req, dict):
        return req
    return {"goal": None} if exists else None
