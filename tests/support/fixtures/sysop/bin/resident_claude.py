"""The resident mode of the fake `claude` (claude -p --input-format stream-json), as Claude Code 2.1.332 behaves (docs/spikes/resident-brain.md):

- it starts the MCP server of --mcp-config ONCE (the sysop's reconnecting proxy) and keeps it;
- each user message on stdin is one turn: a `system/init`, the steps of SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT (read again at every message), then
  one `result` whose total_cost_usd is the total of the process;
- a control_request interrupt gets a control_response at once and ends the turn with `result` subtype error_during_execution;
- a closed stdin ends the process with status 0.
Modes (SWARMBOX_TEST_FAKE_CLAUDE_MODE): script | notloggedin (the line, exit 1 at the first message) | crash (exit 3 at the first message, a line on
stderr) | hang (never ends a turn, ignores the interrupt) | hang-ignore-term (also ignores SIGTERM) | quiet (a result, no tool) |
crash-after (the first turn ends normally, the process dies during the second) | slow-interrupt (the interrupt is answered after 10 s) |
badresume (a --resume is refused: the line on stderr, exit 1).
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import queue

COST = 0.0012


def main(argv, write_log, goals):
    mode = os.environ.get("SWARMBOX_TEST_FAKE_CLAUDE_MODE") or "script"
    session = {"session_id": os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SESSION"]} if os.environ.get("SWARMBOX_TEST_FAKE_CLAUDE_SESSION") else {}
    if "--resume" in argv:
        session = {"session_id": argv[argv.index("--resume") + 1]}
    out_lock = threading.Lock()

    def emit(obj):
        with out_lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()

    if mode == "badresume":         # what the real CLI says for a session it does not have, then it exits
        # Claude Code 2.1.332, measured: the line on stderr, then a result that carries the refused id, then exit 1
        print("No conversation found with session ID: %s" % session["session_id"], file=sys.stderr, flush=True)
        emit({"type": "result", "subtype": "error_during_execution", "duration_ms": 0, "is_error": True, "num_turns": 0, "stop_reason": None,
              **session, "total_cost_usd": 0})
        return 1
    if mode == "hang-ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    messages = queue.Queue()
    interrupted = threading.Event()

    def reader():
        for line in sys.stdin:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("type") == "control_request":
                if mode in ("hang", "hang-ignore-term"):
                    continue
                if mode == "slow-interrupt":
                    time.sleep(10)
                interrupted.set()
                emit({"type": "control_response", "response": {"subtype": "success", "request_id": m.get("request_id"), "response": {}}})
            elif m.get("type") == "user":
                content = (m.get("message") or {}).get("content") or []
                messages.put("".join(c.get("text", "") for c in content if isinstance(c, dict)))
        messages.put(None)
    threading.Thread(target=reader, daemon=True).start()

    # the MCP server: started once, as the real CLI does
    cfg = json.load(open(argv[argv.index("--mcp-config") + 1]))
    srv = cfg["mcpServers"]["sysop"]
    env = dict(os.environ)
    env.update(srv.get("env", {}))
    p = subprocess.Popen([srv["command"]] + srv.get("args", []), stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True, bufsize=1)
    mid = [0]

    def rpc(method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            mid[0] += 1
            msg["id"] = mid[0]
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        if notify:
            return None
        line = p.stdout.readline()
        if not line:
            raise SystemExit("the MCP server went away")
        return json.loads(line)

    tools = None
    total = [0.0]

    def result(sub="success", err=False, text="", turns=1):
        total[0] += COST
        # the key order of the real CLI: "type" is not the first key of its result
        emit({"duration_api_ms": 1, "stop_reason": "end_turn", "type": "result", "subtype": sub, "is_error": err, "num_turns": turns, "total_cost_usd": round(total[0], 6), "result": text, **session})

    def wait_or_interrupt(seconds):
        return interrupted.wait(seconds)

    while True:
        text = messages.get()
        if text is None:
            break
        goals[0] += 1
        write_log(text)
        interrupted.clear()
        if mode == "notloggedin":
            print("Not logged in · Please run /login", flush=True)
            return 1
        if mode == "crash" or (mode == "crash-after" and goals[0] >= 2):
            print("boom: the brain crashed", file=sys.stderr, flush=True)
            return 3
        if mode in ("hang", "hang-ignore-term"):
            emit({"type": "system", "subtype": "init", **session, "tools": [], "mcp_servers": []})        # the CLI says its session first
            while True:
                time.sleep(1)
        if tools is None:
            rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "claude-code", "version": "0"}})
            rpc("notifications/initialized", notify=True)
            r = rpc("tools/list")
            tools = (r.get("result") or {}).get("tools") or []
        emit({"type": "system", "subtype": "init", **session, "tools": ["mcp__sysop__" + t["name"] for t in tools],
              "mcp_servers": [{"name": "sysop", "status": "connected"}]})
        if mode == "quiet":
            result(text="nothing to do")
            continue
        steps = json.load(open(os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"])) if os.environ.get("SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT") else []
        out = os.environ.get("SWARMBOX_TEST_FAKE_CLAUDE_OUT")
        n, cut = 0, False
        for st in steps:
            if interrupted.is_set():
                cut = True
                break
            if "sleep" in st:
                if wait_or_interrupt(st["sleep"]):
                    cut = True
                    break
                continue
            if "touch" in st:
                open(st["touch"], "w").close()
                continue
            if "waitfile" in st:
                end = time.time() + 60
                while not os.path.exists(st["waitfile"]) and time.time() < end:
                    if wait_or_interrupt(0.02):
                        cut = True
                        break
                if cut:
                    break
                continue
            if "write" in st:
                try:
                    with open(st["write"], "w") as f:
                        f.write("x")
                    rec = {"write": st["write"], "ok": True, "error": ""}
                except OSError as e:
                    rec = {"write": st["write"], "ok": False, "error": e.strerror or str(e)}
                if out:
                    with open(out, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                continue
            if "text" in st:
                emit({"type": "stream_event", "event": {"type": "message_start", "message": {}}})
                emit({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}})
                for w in st["text"].split(" "):
                    emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": w + " "}}})
                emit({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
                emit({"type": "assistant", "message": {"content": [{"type": "text", "text": st["text"]}]}})
                continue
            n += 1
            tid = "toolu_fake%d_%d" % (goals[0], n)
            body = json.dumps(st.get("args", {}))
            emit({"type": "stream_event", "event": {"type": "message_start", "message": {}}})
            emit({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": tid, "name": "mcp__sysop__" + st["tool"], "input": {}}}})
            for part in (body[:len(body) // 2], body[len(body) // 2:]):
                emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": part}}})
            emit({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "mcp__sysop__" + st["tool"], "input": st.get("args", {})}]}})
            # the real CLI runs a tool after the model wrote it out: the stream of the block is read before the call reaches the server
            time.sleep(0.05)
            rep = rpc("tools/call", {"name": st["tool"], "arguments": st.get("args", {}), "_meta": {"claudecode/toolUseId": tid, "progressToken": n}})
            r = rep.get("result") or {}
            text_out = "".join(c.get("text", "") for c in r.get("content", [])) if r else json.dumps(rep.get("error"))
            emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": bool(r.get("isError")), "content": [{"type": "text", "text": text_out}]}]}})
            if out:
                with open(out, "a") as f:
                    f.write(json.dumps({"tool": st["tool"], "args": st.get("args", {}), "is_error": bool(r.get("isError")), "text": text_out}) + "\n")
            if interrupted.is_set():
                cut = True
                break
        if cut:
            result(sub="error_during_execution", err=True, turns=n + 1)
        else:
            result(text="finished", turns=n + 1)
    try:
        p.stdin.close()
        p.wait(5)
    except Exception:
        p.kill()
    return 0
