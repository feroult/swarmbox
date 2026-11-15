#!/usr/bin/python3
"""The brain of the soak test (tests/soak_v1.py): a stand-in for `claude -p` chosen goal by goal, so one service can run a mix of well behaved
goals, goals whose brain hangs or crashes, and (a few) goals for the real claude.

The service starts it from SWARMBOX_SYSOP_BRAIN as   python3 brain.py {mcp_config} {model} {max_turns} {system_prompt_file}
and the goal arrives on stdin. A tag in the goal text picks the behaviour (`#s=NAME` and, for `run`, `#tab=@3`):
  ok (default)  list_tabs, run `echo soak` in the tab, done           slow   the same with a 2 s pause between the steps (to be killed mid-goal)
  read          list_tabs, read_tab, done                             hang   sleeps until the budget kills it     noterm  hangs and ignores SIGTERM
  crash         exits 3                                               real   the real `claude -p` with the preset of the sysop (needs the login)
Every other mode is the fake claude of tests/fixtures/sysop/bin/claude over the REAL MCP server of the goal.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(os.path.dirname(HERE), "sysop", "bin", "claude")
mcp, model, max_turns, prompt_file = (sys.argv[1:5] + ["", "", "", ""])[:4]
goal = sys.stdin.read()
m = re.search(r"#s=([a-z]+)", goal)
mode = m.group(1) if m else "ok"
tab = (re.search(r"#tab=(@\d+)", goal) or [None, None])[1]

if mode == "real":
    prompt = open(prompt_file, encoding="utf-8").read() if prompt_file else ""
    argv = ["claude", "-p", "--model", model or "haiku", "--mcp-config", mcp, "--strict-mcp-config", "--tools", "", "--allowedTools", "mcp__sysop__*",
            "--permission-mode", "dontAsk", "--no-session-persistence", "--max-turns", max_turns or "23", "--system-prompt", prompt,
            "--output-format", "stream-json", "--verbose"]
    r, w = os.pipe()
    os.write(w, goal.encode())
    os.close(w)
    os.dup2(r, 0)
    os.execvp("claude", argv)

env = dict(os.environ)
fake_mode = {"crash": "crash", "hang": "hang", "noterm": "hang-ignore-term"}.get(mode, "script")
env["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = fake_mode
args = {"tab": tab} if tab else {}
pause = [{"sleep": 2}] if mode == "slow" else []
if mode == "read":
    steps = [{"tool": "list_tabs"}, {"tool": "read_tab", "args": dict(args)}, {"tool": "done", "args": {"summary": "read"}}]
else:
    steps = [{"tool": "list_tabs"}] + pause + [{"tool": "run", "args": dict(args, command="echo soak")}] + pause + [{"tool": "done", "args": {"summary": "ok"}}]
script = os.path.join(os.getcwd(), "soak-script.json")           # the working directory is the folder of the goal, pruned with it
with open(script, "w") as f:
    json.dump(steps, f)
env["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = script
r, w = os.pipe()
os.write(w, goal.encode())
os.close(w)
os.dup2(r, 0)
try:
    os.execve(sys.executable, [sys.executable, FAKE, "-p", "--mcp-config", mcp], env)
finally:
    pass
