"""The live log of a goal (docs/sysop-brain-design.md 4): one JSON line per event in goals/<id>/events.jsonl, written by the service only,
with a `seq` that only grows and the time `t`. What the brain is doing reaches every reader from here, in one order: the gateway tails it and
relays it to the pages, a page that reconnects asks for the events after the last `seq` it has.

Two sources feed it:
  * an ADAPTER turns the brain's standard output into neutral events, so nothing past this file knows one CLI's format. `claude-stream-json`
    reads Claude Code's stream-json with partial messages; `text` takes every line of a CLI that prints only its reply.
  * the MCP server of the goal sends its own events (what it was asked, what it decided, what it answered) as JSON lines on its standard
    output; `mcp_event` keeps only the known types and fields.

Events (every one also has seq, t, type):
  session        id                         the brain's session, to resume it
  thinking       block, state               started | ended: the model is thinking (its text is not given)
  text.delta     block, text                free text being written (text is the new part)
  text           block, text                the whole block
  action.start   block, fn                  the model chose a tool (block is the tool-use id), before it runs
  action.args    block, fn, args            the arguments, once complete
  say.delta      block, text                the text of a `say` being written
  reply.delta    block, text                the summary of a `done` being written
  call           id, fn, args               the MCP server received the call (id = the tool-use id when the CLI passes it)
  approval       id, state, ...             waiting (mode, risk, text, tab, deadline) | approved | allowed | vetoed | denied | timed_out | stopped
  call.end       id, fn, ok, summary        the MCP server answered
  say            text                       the authoritative text of a say
  done           summary                    the authoritative summary of done
  notify         text, level                a notification for the user (info | warn | urgent)
  question       id, state, ...             waiting (text, options, deadline) | answered (answer) | timeout | stopped: an `ask` of the brain
  steer          text                       a message the user wrote while the goal ran, given to the brain with a tool result
  usage          turns, cost                the brain's own account at its end
  denied         fn                         the CLI refused a tool the model asked for (a security event)
  state          state, error?              running | done | failed | stopped (written by the service)
"""
import json
import os
import re
import threading
import time

MAX_TEXT = 20000       # an event's text field is cut there (a `done` is at most 8000 characters, a screen 20000)


class EventLog:
    """The single writer of a goal's events.jsonl. Thread-safe: the brain's reader thread, the MCP server's reader thread and the service's
    main thread all write here, and the lock gives the file one order. A full disk loses the line, never the goal."""

    MAX_BYTES = 32 << 20     # past this the deltas are dropped (the whole blocks, actions and states are still written)

    def __init__(self, path, clock=time.time, log=None):
        self.path, self.clock, self.log = path, clock, log or (lambda m: None)
        self.lock = threading.Lock()
        self.seq = 0
        self.bytes = 0
        self.f = None
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            self.f = os.fdopen(fd, "a", encoding="utf-8")
        except OSError as e:
            self.log("cannot open %s: %s" % (path, e))
        self.listeners = []

    def emit(self, type_, **fields):
        with self.lock:
            if self.bytes >= self.MAX_BYTES and type_.endswith(".delta"):
                return None
            self.seq += 1
            ev = {"seq": self.seq, "t": round(self.clock(), 3), "type": type_}
            ev.update(fields)
            if self.f is not None:
                try:
                    line = json.dumps(ev, ensure_ascii=True, separators=(",", ":")) + "\n"
                    self.f.write(line)
                    self.f.flush()
                    self.bytes += len(line)
                except (OSError, ValueError) as e:
                    self.log("cannot write an event: %s" % e)
            for fn in self.listeners:
                try:
                    fn(ev)
                except Exception as e:       # a listener's bug must not stop the log
                    self.log("event listener: %r" % (e,))
            return ev

    def close(self):
        with self.lock:
            if self.f is not None:
                try:
                    self.f.close()
                except OSError:
                    pass
                self.f = None


def read(path, since=0):
    """The events of a file after `since` (a reader: the tests, the CLI)."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and isinstance(ev.get("seq"), int) and ev["seq"] > since:
                    out.append(ev)
    except OSError:
        pass
    return out


def partial_json_string(text, field):
    """The value of the string `field` in a JSON object that may end anywhere (inside the value, inside an escape): what is decoded so far."""
    m = re.search(r'"%s"\s*:\s*"' % re.escape(field), text or "")
    if not m:
        return ""
    s, i, out = text, m.end(), []
    esc = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}
    while i < len(s):
        c = s[i]
        if c == '"':
            break
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= len(s):
            break                                   # a backslash cut from its escape: the rest has not arrived
        e = s[i + 1]
        if e == "u":
            h = s[i + 2:i + 6]
            if not re.match(r"^[0-9a-fA-F]{4}$", h):
                break
            code = int(h, 16)
            if 0xD800 <= code <= 0xDBFF:                # a surrogate pair: wait for its second half
                lo = re.match(r"^\\u([0-9a-fA-F]{4})", s[i + 6:i + 12])
                if not lo:
                    break
                out.append((chr(code) + chr(int(lo.group(1), 16))).encode("utf-16", "surrogatepass").decode("utf-16"))
                i += 12
                continue
            out.append(chr(code))
            i += 6
            continue
        out.append(esc.get(e, e))
        i += 2
    return "".join(out)


def _cut(s):
    s = s if isinstance(s, str) else ""
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT]


def _fn(name):
    """the sysop's own name of a tool the CLI prefixes (mcp__sysop__run -> run); None for a tool that is not the sysop's"""
    m = re.match(r"^mcp__sysop__([A-Za-z_][A-Za-z0-9_]*)$", str(name or ""))
    return m.group(1) if m else None


class Adapter:
    """Base of the adapters: feed(line) -> [(type, fields)]; what the run needs at the end (session, result, the reply, the text to look for a
    login failure in)."""
    def __init__(self):
        self.session_id = ""
        self.result = {}
        self.assistant_text = ""
        self.tail = []          # the last lines that were not events (where a CLI writes "Not logged in")

    def feed(self, line):
        raise NotImplementedError

    def finish(self):
        return []

    def _keep(self, line):
        self.tail.append(line[:500])
        del self.tail[:-20]


class TextAdapter(Adapter):
    """A CLI that prints its reply as text: every line is free text."""
    def __init__(self):
        Adapter.__init__(self)
        self.lines = []

    def feed(self, line):
        self._keep(line)
        self.lines.append(line[:MAX_TEXT])
        if len(self.lines) > 400:
            del self.lines[:-400]
        self.assistant_text = "\n".join(self.lines).strip()[-MAX_TEXT:]
        return [("text.delta", {"block": "out", "text": line + "\n"})]


class ClaudeStreamAdapter(Adapter):
    """Claude Code's `--output-format stream-json --include-partial-messages --verbose`. Partial messages give the deltas; the complete
    `assistant` messages fill in what a stream without them (or a fake) did not show; the `result` event gives usage and denials."""
    LIVE = {"say": ("say.delta", "text"), "done": ("reply.delta", "summary")}

    def __init__(self):
        Adapter.__init__(self)
        self.msg = 0
        self.blocks = {}         # index -> {kind, id, fn, buf, sent}
        self.seen = set()        # tool-use ids and text blocks already shown through partial messages
        self.last_text = ""

    def _block_id(self, idx):
        return "m%d.%d" % (self.msg, idx)

    def feed(self, line):
        if not line.startswith("{"):
            self._keep(line)
            return []
        try:
            ev = json.loads(line)
        except ValueError:
            self._keep(line)
            return []
        if not isinstance(ev, dict):
            return []
        out = []
        sid = ev.get("session_id")
        if isinstance(sid, str) and sid.strip() and sid.strip() != self.session_id:
            self.session_id = sid.strip()
            out.append(("session", {"id": self.session_id}))
        t = ev.get("type")
        if t == "stream_event" and isinstance(ev.get("event"), dict):
            out += self._stream(ev["event"])
        elif t == "assistant":
            out += self._assistant(ev.get("message"))
        elif t == "result":
            self.result = ev
            out.append(("usage", {"turns": ev.get("num_turns"), "cost": ev.get("total_cost_usd")}))
            for d in ev.get("permission_denials") or []:
                if isinstance(d, dict):
                    out.append(("denied", {"fn": str(d.get("tool_name") or "")[:80]}))
            if not self.assistant_text and isinstance(ev.get("result"), str):
                self.assistant_text = ev["result"].strip()[-MAX_TEXT:]
        return out

    def _stream(self, inner):
        it = inner.get("type")
        idx = inner.get("index") if isinstance(inner.get("index"), int) else 0
        if it == "message_start":
            self.msg += 1
            self.blocks = {}
            return []
        if it == "content_block_start":
            cb = inner.get("content_block") if isinstance(inner.get("content_block"), dict) else {}
            ct = cb.get("type")
            if ct == "text":
                b = {"kind": "text", "id": self._block_id(idx), "buf": cb.get("text") or ""}
                self.blocks[idx] = b
                self.seen.add(b["id"])
                return [("text.delta", {"block": b["id"], "text": b["buf"]})] if b["buf"] else []
            if ct in ("thinking", "redacted_thinking"):
                b = {"kind": "thinking", "id": self._block_id(idx)}
                self.blocks[idx] = b
                return [("thinking", {"block": b["id"], "state": "started"})]
            if ct == "tool_use":
                fn = _fn(cb.get("name"))
                tid = str(cb.get("id") or self._block_id(idx))
                self.seen.add(tid)
                if fn is None:
                    self.blocks[idx] = {"kind": "other", "id": tid}
                    return []
                kind = fn if fn in self.LIVE else "action"
                self.blocks[idx] = {"kind": kind, "id": tid, "fn": fn, "buf": "", "sent": ""}
                return [("action.start", {"block": tid, "fn": fn})]
            return []
        b = self.blocks.get(idx)
        if b is None:
            return []
        if it == "content_block_delta" and isinstance(inner.get("delta"), dict):
            d = inner["delta"]
            if b["kind"] == "text" and d.get("type") == "text_delta" and isinstance(d.get("text"), str):
                b["buf"] += d["text"]
                return [("text.delta", {"block": b["id"], "text": d["text"]})]
            if b["kind"] not in ("text", "thinking", "other") and d.get("type") == "input_json_delta" and isinstance(d.get("partial_json"), str):
                b["buf"] += d["partial_json"]
                if b["kind"] in self.LIVE:
                    typ, field = self.LIVE[b["kind"]]
                    now = partial_json_string(b["buf"], field)
                    if now.startswith(b["sent"]) and len(now) > len(b["sent"]):
                        new, b["sent"] = now[len(b["sent"]):], now
                        return [(typ, {"block": b["id"], "text": new})]
            return []
        if it == "content_block_stop":
            if b["kind"] == "text":
                self.last_text = b["buf"]
                self.assistant_text = b["buf"].strip()[-MAX_TEXT:] or self.assistant_text
                return [("text", {"block": b["id"], "text": _cut(b["buf"])})]
            if b["kind"] == "thinking":
                return [("thinking", {"block": b["id"], "state": "ended"})]
            if b["kind"] not in ("other",):
                try:
                    args = json.loads(b["buf"]) if b["buf"].strip() else {}
                except ValueError:
                    args = {}
                return [("action.args", {"block": b["id"], "fn": b["fn"], "args": _small(args)})]
        return []

    def _assistant(self, msg):
        """A complete message: what the partial messages did not already show (a stream without them, the fake of the tests)."""
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            return []
        out = []
        texts = []
        for n, c in enumerate(content):
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"]:
                texts.append(c["text"])
            if c.get("type") == "tool_use":
                tid = str(c.get("id") or "")
                fn = _fn(c.get("name"))
                if fn is None or (tid and tid in self.seen):
                    continue
                self.seen.add(tid)
                out.append(("action.start", {"block": tid, "fn": fn}))
                out.append(("action.args", {"block": tid, "fn": fn, "args": _small(c.get("input"))}))
        if texts:
            joined = "\n".join(texts)
            self.assistant_text = joined.strip()[-MAX_TEXT:]
            if joined != self.last_text and not any(b.get("kind") == "text" for b in self.blocks.values()):
                bid = "m%d.full" % self.msg
                out.append(("text", {"block": bid, "text": _cut(joined)}))
            self.last_text = joined
        return out


ADAPTERS = {"claude-stream-json": ClaudeStreamAdapter, "text": TextAdapter}


def adapter(fmt):
    return ADAPTERS.get(fmt, TextAdapter)()


def _small(args):
    if not isinstance(args, dict):
        return {}
    return {str(k)[:40]: (_cut(v)[:2000] if isinstance(v, str) else v if isinstance(v, (int, float, bool)) or v is None else str(v)[:300])
            for k, v in list(args.items())[:8]}


# the events the MCP server may send, with the fields kept for each (anything else it writes is dropped)
MCP_EVENTS = {
    "call": ("id", "fn", "args"),
    "approval": ("id", "state", "mode", "risk", "reasons", "text", "tab", "label", "kind", "deadline"),
    "call.end": ("id", "fn", "ok", "summary"),
    "say": ("text",),
    "done": ("summary",),
    "notify": ("text", "level"),
    "question": ("id", "state", "text", "options", "deadline", "answer"),
    "steer": ("text",),
}


def mcp_event(line):
    """(type, fields) of one line the MCP server wrote, or None when it is not one of its events."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict) or ev.get("type") not in MCP_EVENTS:
        return None
    keep = {}
    for k in MCP_EVENTS[ev["type"]]:
        if k in ev:
            v = ev[k]
            keep[k] = _small(v) if isinstance(v, dict) else (_cut(v) if isinstance(v, str) else v)
    return ev["type"], keep
