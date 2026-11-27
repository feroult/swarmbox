#!/usr/bin/env python3
"""The sysop service (service.py) with the REAL Claude Code as its resident brain, the fake bus and the fake swarmbox-tabs of the suite:
goals from the bus, a Stop (the stop request the panel writes), a new conversation (+ New), and the brain processes behind them.
Needs CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY). Everything lives in a temporary folder that is removed at the end.

    python3 dev/spikes/resident-brain/real_service.py
"""
import json
import os
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tests", "support"))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import ipc, service  # noqa: E402


def main():
    e = ss.Env()
    bus = ss.FakeBus(e.env["SB_BUS_SOCKET"])
    bus.start()
    tabs = ss.FakeTabs(os.path.join(e.dir, "tabs.sock"))
    tabs.start()
    os.environ.update(e.env)
    os.environ.update(tabs.cmd_env)
    os.environ["PATH"] = os.pathsep.join(p for p in e.env["PATH"].split(os.pathsep) if p != ss.FAKE_BIN)      # the real claude
    pth = e.paths
    svc = service.Service(e.cfg(model="haiku", countdown=0), pth, log=lambda m: print("  [sysop]", m))
    th = threading.Thread(target=svc.run, daemon=True)
    th.start()
    svc.wait_ready(10)
    ss.wait_for(lambda: len(bus.subs) >= 1, 10)
    rows = []

    def goal(text, stop_after=None, timeout=120):
        r = bus.publish_goal(text, "voice")
        gid = r["id"]
        if stop_after:
            ss.wait_for(lambda: (ipc.read_json(os.path.join(pth.goals, gid, "state.json")) or {}).get("state") == "running", 30)
            time.sleep(stop_after)
            ipc.request_stop(pth)
        ss.wait_for(lambda: (ipc.read_json(os.path.join(pth.goals, gid, "state.json")) or {}).get("state") in ("done", "failed", "stopped"), timeout)
        st = ipc.read_json(os.path.join(pth.goals, gid, "state.json")) or {}
        row = {"text": text[:40], "state": st.get("state"), "error": st.get("error"), "summary": (st.get("summary") or "")[:160],
               "pid": (st.get("brain") or {}).get("pid"), "cost": (st.get("brain") or {}).get("cost"),
               "secs": round((st.get("ended") or 0) - (st.get("started") or 0), 1)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        return row

    try:
        a = goal("remember the word papaya, and tell me how many shells there are")
        b = goal("wait 25 seconds on the active tab and then say you are done", stop_after=5)
        c = goal("what was the word I asked you to remember")
        ipc.write_json(os.path.join(pth.state, "conversation.json"), {"since": time.time()})       # + New, as the Web Studio writes it
        d = goal("what was the word I asked you to remember? if you do not know, say you do not know")
        ok = (a["state"] == "done" and b["state"] == "stopped" and c["state"] == "done" and "papaya" in c["summary"].lower()
              and a["pid"] == b["pid"] == c["pid"] and d["state"] == "done" and d["pid"] != a["pid"] and "papaya" not in d["summary"].lower())
        print("VERDICT:", "works" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        svc.shutdown()
        th.join(20)
        print("  brain alive after the service ended:", svc.runtime.alive())
        bus.stop()
        tabs.stop()
        e.cleanup()


if __name__ == "__main__":
    sys.exit(main())
