#!/usr/bin/env python3
"""Drives mcp_tmux.py over stdio without any model (needs tmux). Usage: selftest.py"""
import json, os, subprocess, sys, tempfile, time
os.environ["TMUX_TMPDIR"] = tempfile.mkdtemp(); os.environ["SYSOP_TMUX_SOCKET"] = "st"
tm = lambda *a: subprocess.run(["tmux", "-L", "st", *a], capture_output=True, text=True).stdout
tm("new-session", "-d", "-s", "m", "-n", "one", "-x", "80", "-y", "10"); tm("new-window", "-d", "-n", "two")
p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_tmux.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
n = 0
def rpc(method, params=None):
    global n; n += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n"); p.stdin.flush()
    return json.loads(p.stdout.readline())["result"]
def call(name, **a):
    r = rpc("tools/call", {"name": name, "arguments": a}); return r["isError"], r["content"][0]["text"]
ok = True
def check(label, cond): 
    global ok; ok &= bool(cond); print("PASS" if cond else "FAIL", label)
check("negotiates unknown version", rpc("initialize", {"protocolVersion": "9999-01-01"})["protocolVersion"] == "2025-11-25")
check("tools/list has 6", len(rpc("tools/list")["tools"]) == 6)
check("list_tabs", [w["tab"] for w in json.loads(call("list_tabs")[1])] == ["one", "two"])
call("run", tab="one", command="echo 'Enter {Esc} $HOME' > /dev/null; echo marker-$((6*7))"); time.sleep(0.5)
check("run types literally and presses Enter", "marker-42" in call("read_tab", tab="one")[1])
call("run", tab="two", command="sleep 100"); time.sleep(0.3)
call("input", tab="two", text="{C-c}"); time.sleep(0.3)
call("run", tab="two", command="echo after-ctrl-c"); time.sleep(0.4)
check("input {C-c} interrupts", "after-ctrl-c" in call("read_tab", tab="two")[1])
call("input", tab="two", text="abc{BSpace}d"); time.sleep(0.3)
check("input with braces keys, no Enter", "abd" in call("read_tab", tab="two")[1].splitlines()[-1])
e, t = call("input", tab="two", text="{Bogus}"); check("unknown key -> isError", e and "unknown key" in t)
e, t = call("read_tab", tab="nope"); check("unknown tab -> isError", e)
p.stdin.close(); tm("kill-server"); sys.exit(0 if ok else 1)
