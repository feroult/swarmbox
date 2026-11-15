#!/usr/bin/env python3
"""Summarize a stream-json log from claude -p: turns, tool calls, usage, cost."""
import json, sys
ev = []
for l in open(sys.argv[1]):
    try: ev.append(json.loads(l))
    except Exception: pass
for e in ev:
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("init: model", e.get("model"), "tools", e.get("tools"), "mcp", e.get("mcp_servers"), "perm", e.get("permissionMode"))
    elif e.get("type") == "assistant":
        for c in e["message"]["content"]:
            if c["type"] == "tool_use": print("CALL", c["name"], json.dumps(c["input"]))
            elif c["type"] == "text": print("TEXT", c["text"][:200].replace("\n", " "))
    elif e.get("type") == "user":
        for c in (e["message"]["content"] if isinstance(e["message"]["content"], list) else []):
            if c.get("type") == "tool_result":
                t = c["content"] if isinstance(c["content"], str) else " ".join(x.get("text", "") for x in c["content"])
                print("  RESULT", "ERR" if c.get("is_error") else "ok", t[:90].replace("\n", " | "))
    elif e.get("type") == "result":
        print("RESULT subtype", e.get("subtype"), "turns", e.get("num_turns"), "duration_ms", e.get("duration_ms"), "api_ms", e.get("duration_api_ms"), "cost_usd", e.get("total_cost_usd"))
        print("usage", json.dumps(e.get("usage")))
        print("denials", e.get("permission_denials"))
