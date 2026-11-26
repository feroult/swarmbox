"""A minimal stdio MCP server for the spikes: tools say, run (sleeps RUN_SLEEP s), done, envnames. Logs every request raw with a timestamp."""
import json, os, sys, time
LOG = os.environ["SPIKE_MCP_LOG"]
SLEEP = float(os.environ.get("RUN_SLEEP", "0"))
def log(kind, obj):
    with open(LOG, "a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "msg": obj}) + "\n")
TOOLS = [
    {"name": "say", "description": "Send a short progress note to the user.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "run", "description": "Run a shell command in a tab and return its output.", "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "done", "description": "Finish with the final reply.", "inputSchema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
    {"name": "envnames", "description": "List the names of the environment variables of this server.", "inputSchema": {"type": "object", "properties": {}}},
]
for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    log("req", req)
    mid, m = req.get("id"), req.get("method")
    if mid is None:
        continue
    if m == "initialize":
        res = {"protocolVersion": req["params"].get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}}, "serverInfo": {"name": "spike", "version": "0"}}
    elif m == "tools/list":
        res = {"tools": TOOLS}
    elif m == "tools/call":
        name, args = req["params"]["name"], req["params"].get("arguments", {})
        if name == "run" and SLEEP:
            time.sleep(SLEEP)
        text = {"envnames": " ".join(sorted(os.environ)), "run": "ran: %s" % args.get("command")}.get(name, "ok")
        res = {"content": [{"type": "text", "text": text}]}
        log("end", {"name": name, "args": args})
    else:
        res = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
    sys.stdout.flush()
