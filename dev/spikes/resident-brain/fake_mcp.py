#!/usr/bin/env python3
"""Fake sysop MCP server for the ACP spikes (stdio, newline-delimited JSON-RPC).

Tools: note(text), slow(seconds), done(summary). Every call, cancel notification and exit is logged
as one JSON line to $SPIKE_CALLS (default ./calls.jsonl) with time and pid.
"""
import json, os, sys, time, threading

LOG = os.environ.get("SPIKE_CALLS", "calls.jsonl")
lock = threading.Lock()


def log(**kw):
    kw.update(t=round(time.time(), 3), pid=os.getpid())
    with lock, open(LOG, "a") as f:
        f.write(json.dumps(kw) + "\n")


def send(obj):
    with lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


TOOLS = [
    {"name": "note", "description": "Write a short note to the operator log. Returns ok.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "slow", "description": "A slow operation: waits the given seconds, then returns 'slow finished'.",
     "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}, "required": ["seconds"]}},
    {"name": "done", "description": "End the task with a one-sentence summary for the user.",
     "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]


def handle(msg):
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        log(event="initialize", client=p.get("clientInfo"))
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": p.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "sysop", "version": "0.0.1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name, args = p.get("name"), p.get("arguments") or {}
        log(event="call", tool=name, args=args)
        if name == "slow":
            secs = float(args.get("seconds", 1))
            time.sleep(secs)
            log(event="call_end", tool=name)
            text = "slow finished after %s s" % secs
        elif name == "note":
            text = "ok"
        elif name == "done":
            text = "ended"
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "no such tool"}})
            return
        send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})
    elif method == "notifications/cancelled":
        log(event="cancelled", params=p)
    elif method and method.startswith("notifications/"):
        pass
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})


def main():
    log(event="start", argv=sys.argv)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        # tools/call runs in a thread so a cancel notification can arrive while `slow` sleeps
        threading.Thread(target=handle, args=(msg,), daemon=True).start()
    log(event="exit")


if __name__ == "__main__":
    main()
