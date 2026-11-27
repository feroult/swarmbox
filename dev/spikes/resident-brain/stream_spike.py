#!/usr/bin/env python3
"""Spike: Claude Code's own resident mode, `claude -p --input-format stream-json --output-format stream-json`.

usage: stream_spike.py --out DIR --cwd DIR -- CLAUDE_ARGV...   (the argv must NOT carry --input-format; it is added here)

Scenario, one process:
  T1 remember a word + call note    T2 call note again    T3 call slow 20 s, interrupt (control_request) at 4 s
  T4 did slow finish?               T5 try a built-in tool          (count claude processes between turns)
  KILL -9, restart with --resume SID, T6 recall the word.
"""
import argparse, json, os, signal, subprocess, sys, threading, time, queue

HERE = os.path.dirname(os.path.abspath(__file__))


class Brain:
    def __init__(self, argv, cwd, wire):
        self.wire, self.t0 = wire, time.time()
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(wire + ".stderr", "ab"), start_new_session=True)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def log(self, d, m):
        with open(self.wire, "a") as f:
            f.write(json.dumps({"t": round(time.time() - self.t0, 3), "dir": d, "msg": m}) + "\n")

    def _read(self):
        for raw in self.p.stdout:
            try:
                m = json.loads(raw)
            except ValueError:
                self.log("garbage", raw.decode(errors="replace"))
                continue
            self.log("in", m)
            self.q.put(m)
        self.q.put({"type": "_eof"})

    def send(self, m):
        self.log("out", m)
        self.p.stdin.write((json.dumps(m) + "\n").encode())
        self.p.stdin.flush()

    def user(self, text):
        self.send({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def interrupt(self):
        self.send({"type": "control_request", "request_id": "int-%d" % time.time(), "request": {"subtype": "interrupt"}})

    def until_result(self, timeout=240, on=None):
        """messages up to and including the turn's `result`"""
        out, end = [], time.time() + timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=0.2)
            except queue.Empty:
                if on:
                    on(out)
                continue
            out.append(m)
            if on:
                on(out)
            if m.get("type") in ("result", "_eof"):
                return out
        out.append({"type": "_timeout"})
        return out

    def kill(self):
        try:
            os.killpg(self.p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.p.wait()


def claude_procs(pgid):
    n = 0
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if os.getpgid(int(pid)) == pgid and b"claude" in open("/proc/%s/cmdline" % pid, "rb").read():
                    n += 1
            except (OSError, ProcessLookupError):
                pass
    return n


def summarize(msgs):
    text, tools, res = [], [], {}
    for m in msgs:
        if m.get("type") == "assistant":
            for c in (m.get("message") or {}).get("content") or []:
                if c.get("type") == "text":
                    text.append(c.get("text", ""))
                elif c.get("type") == "tool_use":
                    tools.append(c.get("name"))
        elif m.get("type") == "result":
            res = {k: m.get(k) for k in ("subtype", "is_error", "num_turns", "total_cost_usd", "session_id", "stop_reason")}
        elif m.get("type") == "control_response":
            res.setdefault("control", []).append(m.get("response"))
    return {"text": " ".join(text).strip()[:600], "tools": tools, "result": res,
            "types": sorted({m.get("type") + ("/" + m["subtype"] if m.get("subtype") else "") for m in msgs})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    base = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
    os.makedirs(a.out, exist_ok=True)
    wire, calls = os.path.join(a.out, "wire.jsonl"), os.path.join(a.out, "calls.jsonl")
    mcp = os.path.join(a.out, "mcp.json")
    json.dump({"mcpServers": {"sysop": {"command": sys.executable, "args": [os.path.join(HERE, "fake_mcp.py")],
                                        "env": {"SPIKE_CALLS": calls}}}}, open(mcp, "w"))
    argv = [w.replace("{mcp}", mcp) for w in base] + ["--input-format", "stream-json"]
    rep = {"argv": argv, "steps": []}

    def save():
        json.dump(rep, open(os.path.join(a.out, "report.json"), "w"), indent=1)

    def turn(b, name, text, interrupt_at=None):
        t = time.time()
        b.user(text)
        state = {"sent": False, "slow_at": None}

        def on(_msgs):
            if interrupt_at is None or state["sent"]:
                return
            if state["slow_at"] is None and os.path.exists(calls) and '"slow"' in open(calls).read():
                state["slow_at"] = time.time()
            if state["slow_at"] and time.time() - state["slow_at"] >= interrupt_at:
                state["ti"] = time.time()
                b.interrupt()
                state["sent"] = True
        msgs = b.until_result(on=on)
        s = summarize(msgs)
        s.update(name=name, secs=round(time.time() - t, 2), procs_after=claude_procs(b.p.pid), alive=b.p.poll() is None)
        if state.get("ti"):
            s["interrupt_to_result_s"] = round(time.time() - state["ti"], 2)
        rep["steps"].append(s)
        save()
        print("%-3s %5.1fs alive=%s procs=%s %s %s | %s" % (name, s["secs"], s["alive"], s["procs_after"], s["result"].get("subtype"),
              s["tools"], s["text"][:160]), flush=True)
        return s

    t = time.time()
    b = Brain(argv, a.cwd, wire)
    turn(b, "T1", "Remember the word PAPAYA for later. Call the sysop's `note` tool with the text 'turn1'. Then list, by exact name, every tool you can call.")
    rep["first_turn_includes_start"] = round(time.time() - t, 2)
    turn(b, "T2", "Second request: call `note` with 'turn2', then answer 'done 2'.")
    turn(b, "T3", "Call the sysop's `slow` tool with seconds=20, then answer with its result.", interrupt_at=4)
    turn(b, "T4", "Did the slow call finish or was it interrupted? One sentence, no tools.")
    turn(b, "T5", "Using a built-in tool (not the sysop ones), create spike-probe.txt here, or run `touch spike-probe.txt`. Say which tool you used.")
    rep["probe_file_exists"] = os.path.exists(os.path.join(a.cwd, "spike-probe.txt"))
    sid = next((s["result"].get("session_id") for s in rep["steps"] if s["result"].get("session_id")), None)
    b.kill()
    t = time.time()
    b = Brain(argv + ["--resume", sid], a.cwd, wire)
    turn(b, "T6", "What word did I ask you to remember at the start? Only the word, no tools.")
    rep["resume_turn_includes_start"] = round(time.time() - t, 2)
    b.p.stdin.close()
    try:
        b.p.wait(15)
        rep["exit_on_stdin_close"] = b.p.returncode
    except subprocess.TimeoutExpired:
        rep["exit_on_stdin_close"] = "still running after 15 s"
        b.kill()
    rep["mcp_calls"] = [json.loads(l) for l in open(calls)] if os.path.exists(calls) else []
    save()
    print("probe:", rep["probe_file_exists"], "exit_on_stdin_close:", rep["exit_on_stdin_close"])
    for c in rep["mcp_calls"]:
        print(" mcp", c.get("event"), c.get("tool", ""), c.get("params", ""), c.get("pid"))


if __name__ == "__main__":
    main()
