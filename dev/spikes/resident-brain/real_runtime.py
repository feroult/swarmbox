#!/usr/bin/env python3
"""The resident brain of the sysop with the REAL Claude Code, its real MCP servers (one per goal, behind the reconnecting proxy) and the fake
swarmbox-tabs of the suite: three goals in one process, a Stop in the middle of the second, then a kill and a resumed session.
Needs CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY) in the environment. Everything lives in a temporary folder that is removed at the end.

    python3 dev/spikes/resident-brain/real_runtime.py
"""
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import brain, events, ipc  # noqa: E402


def main():
    e = ss.Env()
    tabs = ss.FakeTabs(os.path.join(e.dir, "tabs.sock"))
    tabs.start()
    os.environ.update({k: v for k, v in e.env.items() if k.startswith(("SB_", "SWARMBOX_"))})
    os.environ.update(tabs.cmd_env)
    os.environ["PATH"] = os.pathsep.join(p for p in e.env["PATH"].split(os.pathsep) if p != ss.FAKE_BIN)      # the real claude
    pth = e.paths.make()
    cfg = e.cfg(max_seconds=120, model="haiku")
    opts = brain.options(cfg.brain)
    home = brain.prepare_home(pth.brain_home)
    sock = pth.mcp_socket("brain")
    rt = brain.Runtime(log=lambda m: print("  [runtime]", m))
    report = []

    def goal(n, text, sid, stop_after=None):
        gid = "g%d" % n
        gdir = os.path.join(pth.goals, gid)
        os.makedirs(gdir, 0o700)
        ctx = os.path.join(gdir, "context.json")
        ipc.write_json(ctx, {"goal": gid, "source": "cli", "goal_dir": gdir, "audit": pth.audit, "countdown": 0, "deadline": time.time() + 120})
        ev = events.EventLog(os.path.join(gdir, "events.jsonl"))
        host = brain.McpHost(sock, brain.server_env(ctx, pth, ss.LIB), ev)
        host.start()
        t0 = time.time()
        err = rt.ensure(cfg, opts, home, sock, pth, ss.LIB, sid)
        if err:
            print("cannot start:", err)
            sys.exit(2)
        pid = rt.proc.pid
        stop = (lambda: time.time() - t0 > stop_after) if stop_after else (lambda: False)
        res = rt.run_goal(cfg, "[" + brain.source_note("cli") + "]\n\nThe goal now (cli):\n" + text, gdir, stop, lambda: None,
                          time.time() + 120, ev, opts)
        host.stop()
        ev.close()
        calls = [json.loads(x)["tool"] for x in open(os.path.join(gdir, "calls.jsonl"))] if os.path.exists(os.path.join(gdir, "calls.jsonl")) else []
        row = {"goal": n, "secs": round(time.time() - t0, 1), "pid": pid, "outcome": res.outcome, "error": res.error, "summary": res.summary[:200],
               "calls": calls, "cost": res.cost, "session": res.session_id, "alive_after": rt.alive()}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False))
        return res

    try:
        a = goal(1, "Remember the word PAPAYA. Call box_state, then call done with a one-line summary of how many shells there are.", "")
        if os.environ.get("ONLY1"):
            return 0
        b = goal(2, "Call wait with seconds=25 on the active tab, then call done.", a.session_id, stop_after=6)
        c = goal(3, "What word did I ask you to remember? Answer with done; call no other tool.", b.session_id or a.session_id)
        os.kill(rt.proc.pid, 9)
        time.sleep(0.5)
        d = goal(4, "Once more: what word did I ask you to remember? Answer with done only.", c.session_id)
        ok = (a.outcome == "done" and "box_state" in report[0]["calls"] and b.outcome == "stopped" and report[1]["alive_after"]
              and report[1]["pid"] == report[0]["pid"] and c.outcome == "done" and "PAPAYA" in c.summary.upper()
              and report[2]["pid"] == report[0]["pid"] and d.outcome == "done" and "PAPAYA" in d.summary.upper() and report[3]["pid"] != report[0]["pid"])
        print("VERDICT:", "works" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        rt.close()
        tabs.stop()
        if not os.environ.get("KEEP"):
            e.cleanup()
        else:
            print("kept:", e.dir)


if __name__ == "__main__":
    sys.exit(main())
