#!/usr/bin/env python3
"""ACP spike client: drives one agent through the sysop-brain scenario and writes a report.

usage: acp_spike.py --out DIR --cwd DIR [--mcp-python PY] -- AGENT_CMD...

Scenario (one resident process, one session):
  T1 remember a word + call note          (tools reach the agent? which tools does it claim to have?)
  T2 call note again                       (second goal in the same session)
  T3 call slow 20 s, client cancels at 4 s (session/cancel latency, what the MCP server saw)
  T4 ask what happened to slow             (does the model know the truth after a cancel?)
  T5 try a built-in tool (write a file)    (does a tool that is not ours exist / ask permission? we reject)
  KILL -9, restart, session/load           (crash recovery)
  T6 recall the word                       (memory survives)
Every message in and out is logged to DIR/wire.jsonl.
"""
import argparse, json, os, queue, signal, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
SYSOP_TOOLS = ("note", "slow", "done")


class Agent:
    def __init__(self, argv, env, wire, report):
        self.wire, self.report = wire, report
        self.t0 = time.time()
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(wire + ".stderr", "ab"),
                                  env=env, start_new_session=True)
        self.next_id, self.pending, self.updates = 0, {}, queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def log(self, direction, obj):
        with open(self.wire, "a") as f:
            f.write(json.dumps({"t": round(time.time() - self.t0, 3), "dir": direction, "msg": obj}) + "\n")

    def _write(self, obj):
        self.log("out", obj)
        with self.lock:
            self.p.stdin.write((json.dumps(obj) + "\n").encode())
            self.p.stdin.flush()

    def _reader(self):
        for raw in self.p.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                self.log("garbage", raw.decode(errors="replace"))
                continue
            self.log("in", msg)
            if "method" in msg and "id" in msg:
                self._on_request(msg)
            elif "method" in msg:
                self.updates.put(msg)
            elif msg.get("id") in self.pending:
                self.pending.pop(msg["id"]).put(msg)
        for q in list(self.pending.values()):
            q.put({"error": {"message": "agent exited"}})

    def _on_request(self, msg):
        m, p = msg["method"], msg.get("params") or {}
        if m == "session/request_permission":
            tc = p.get("toolCall") or {}
            blob = json.dumps(tc).lower()
            ours = any(('"%s"' % n) in blob or ("sysop" in blob and n in blob) for n in SYSOP_TOOLS)
            opts = p.get("options") or []
            want = ("allow_once", "allow_always") if ours else ("reject_once", "reject_always")
            pick = next((o for o in opts if o.get("kind") in want), None)
            self.report.setdefault("permission_requests", []).append(
                {"title": tc.get("title"), "kind": tc.get("kind"), "ours": ours, "answer": pick and pick.get("optionId")})
            res = {"outcome": {"outcome": "selected", "optionId": pick["optionId"]}} if pick else {"outcome": {"outcome": "cancelled"}}
            self._write({"jsonrpc": "2.0", "id": msg["id"], "result": res})
        else:
            self.report.setdefault("client_requests", []).append(m)
            self._write({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "not supported by the sysop"}})

    def request(self, method, params, timeout=180):
        self.next_id += 1
        q = queue.Queue()
        self.pending[self.next_id] = q
        self._write({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return {"error": {"message": "timeout %ss" % timeout}}

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.updates.get_nowait())
            except queue.Empty:
                return out

    def kill(self):
        try:
            os.killpg(self.p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.p.wait()


def summarize(updates):
    text, tools, kinds = [], [], {}
    for u in updates:
        up = (u.get("params") or {}).get("update") or {}
        k = up.get("sessionUpdate")
        kinds[k] = kinds.get(k, 0) + 1
        if k == "agent_message_chunk":
            c = up.get("content") or {}
            text.append(c.get("text", ""))
        elif k == "tool_call":
            tools.append({"title": up.get("title"), "kind": up.get("kind"), "status": up.get("status")})
        elif k == "tool_call_update" and up.get("status") in ("completed", "failed"):
            tools.append({"update": up.get("status"), "id": up.get("toolCallId")})
    return {"text": "".join(text).strip()[:1500], "tools": tools, "update_kinds": kinds}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--skip", default="", help="comma list of steps to skip (t5,kill)")
    ap.add_argument("--meta", default="", help="JSON _meta for session/new and session/load")
    ap.add_argument("--extra", default="", help="JSON file: [{name, text, idle_after}] turns run after T6 (or after T2 with --only-extra)")
    ap.add_argument("--only-extra", action="store_true")
    ap.add_argument("agent", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    argv = a.agent[1:] if a.agent[:1] == ["--"] else a.agent
    os.makedirs(a.out, exist_ok=True)
    wire, rep_path = os.path.join(a.out, "wire.jsonl"), os.path.join(a.out, "report.json")
    calls = os.path.join(a.out, "calls.jsonl")
    report = {"argv": argv, "steps": []}
    env = dict(os.environ)
    mcp = [{"name": "sysop", "command": sys.executable, "args": [os.path.join(HERE, "fake_mcp.py")],
            "env": [{"name": "SPIKE_CALLS", "value": calls}]}]
    skip = set(filter(None, a.skip.split(",")))
    meta = json.loads(a.meta) if a.meta else None
    def P(d):
        if meta:
            d["_meta"] = meta
        return d

    def save():
        with open(rep_path, "w") as f:
            json.dump(report, f, indent=1)

    def start():
        ag = Agent(argv, env, wire, report)
        t = time.time()
        r = ag.request("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                                      "clientInfo": {"name": "sysop-spike", "version": "0"}}, timeout=60)
        report.setdefault("initialize", []).append({"secs": round(time.time() - t, 2), "result": r.get("result"), "error": r.get("error")})
        return ag

    def turn(ag, name, sid, text, cancel_after=None, timeout=240):
        t = time.time()
        res = {}
        if cancel_after is None:
            r = ag.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": text}]}, timeout=timeout)
        else:
            box = {}
            th = threading.Thread(target=lambda: box.update(r=ag.request("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": text}]}, timeout=timeout)))
            th.start()
            # cancel only once the slow tool really started on the MCP side
            deadline = time.time() + 90
            while time.time() < deadline and not (os.path.exists(calls) and '"slow"' in open(calls).read()):
                time.sleep(0.1)
            started = time.time()
            time.sleep(cancel_after)
            tc = time.time()
            ag.notify("session/cancel", {"sessionId": sid})
            th.join(timeout)
            r = box.get("r", {"error": {"message": "no answer"}})
            res["slow_seen_after_s"] = round(started - t, 2)
            res["cancel_to_answer_s"] = round(time.time() - tc, 2)
        time.sleep(0.5)
        res.update(name=name, secs=round(time.time() - t, 2), result=r.get("result"), error=r.get("error"), **summarize(ag.drain()))
        report["steps"].append(res)
        save()
        print("%-5s %6.1fs %s | %s" % (name, res["secs"], (r.get("result") or r.get("error")), res["text"][:200].replace("\n", " ")), flush=True)
        return res

    ag = start()
    caps = (report["initialize"][0].get("result") or {}).get("agentCapabilities") or {}
    t = time.time()
    r = ag.request("session/new", P({"cwd": a.cwd, "mcpServers": mcp}), timeout=90)
    report["session_new"] = {"secs": round(time.time() - t, 2), "result": r.get("result"), "error": r.get("error")}
    save()
    if "result" not in r:
        print("session/new failed:", r.get("error"))
        ag.kill()
        return 2
    sid = r["result"]["sessionId"]
    ag.drain()
    def extras():
        for x in json.load(open(a.extra)):
            turn(ag, x["name"], sid, x["text"])
            idle = x.get("idle_after", 0)
            if idle:
                t = time.time()
                time.sleep(idle)
                got = summarize(ag.drain())
                got.update(name=x["name"] + "-idle", secs=idle)
                report["steps"].append(got)
                save()
                print("%s-idle %ss unsolicited: %s | %s" % (x["name"], idle, got["update_kinds"], got["text"][:300].replace("\n", " ")), flush=True)
    if a.only_extra:
        extras()
        ag.kill()
        report["mcp_calls"] = [json.loads(l) for l in open(calls)] if os.path.exists(calls) else []
        save()
        print("report:", rep_path)
        return 0
    turn(ag, "T1", sid, "Remember the word PAPAYA for later. Call the sysop's `note` tool with the text 'turn1'. Then list, by exact name, every tool you can call, and stop.")
    turn(ag, "T2", sid, "Second request: call the sysop's `note` tool with the text 'turn2', then answer 'done 2'.")
    turn(ag, "T3", sid, "Call the sysop's `slow` tool with seconds=20, then answer with its result.", cancel_after=4)
    turn(ag, "T4", sid, "Did the slow call you started finish or was it interrupted? Answer in one sentence; do not call any tool.")
    if "t5" not in skip:
        turn(ag, "T5", sid, "Using one of your own built-in tools (not the sysop ones), create the file spike-probe.txt in the current folder with the text hi, or run the shell command `touch spike-probe.txt`. Say exactly which tool you used and whether it worked.")
        report["probe_file_exists"] = os.path.exists(os.path.join(a.cwd, "spike-probe.txt"))
    if "kill" not in skip:
        ag.kill()
        report["killed"] = True
        ag = start()
        if not caps.get("loadSession"):
            report["session_load"] = "agent does not advertise loadSession"
        t = time.time()
        r = ag.request("session/load", P({"sessionId": sid, "cwd": a.cwd, "mcpServers": mcp}), timeout=90)
        replay = summarize(ag.drain())
        report["session_load"] = {"secs": round(time.time() - t, 2), "result": r.get("result"), "error": r.get("error"),
                                  "replayed_update_kinds": replay["update_kinds"]}
        save()
        if "error" not in r:
            turn(ag, "T6", sid, "What word did I ask you to remember at the start? Answer with the word only; do not call any tool.")
            if a.extra:
                extras()
    ag.kill()
    try:
        report["mcp_calls"] = [json.loads(l) for l in open(calls)]
    except OSError:
        report["mcp_calls"] = []
    save()
    print("report:", rep_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
