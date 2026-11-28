"""Fast tests for the opt-in `herdr` multiplexer backend (`SWARMBOX_MUX=herdr`):

  - HerdrBackend in container/scripts/swarmbox-tabs.py (list, active, screen, redaction,
    framed `hc connect` literal UTF-8 text delivery, key mapping, native OSC 7501 `tab_state()`
    + heuristic fallback, error codes)
  - container/scripts/mux/herdr.sh (serve init + config seeding, attach interactive,
    attach command + exit code + detach, `swarmbox-web` dispatch with and without voice front)
  - Sysop integration (brain.write_mcp_config forwarding mux env, risk.py guarding hc/herdr)
  - container/web/herdr/server.mjs (CLI arg parsing and Origin security check via Node)

Zero real `hc` daemon, zero network.
Run: python3 tests/fast/test_herdr_backend.py
"""
import io
import importlib.util
import json
import os
import pty
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, stage_herdr_web  # noqa: E402

TABS_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")
ATTACH_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-attach.sh")
WEB_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
HERDR_CLIENT = os.path.join(ROOT, "container", "web", "herdr", "hc-client.mjs")
HERDR_SERVER = os.path.join(ROOT, "container", "web", "herdr", "server.mjs")
HERDR_COCKPIT = os.path.join(ROOT, "container", "web", "herdr", "cockpit.mjs")
SYSOP_LIB = os.path.join(ROOT, "container", "addons", "sysop", "lib")

_spec = importlib.util.spec_from_file_location("swarmbox_tabs_herdr_test", TABS_PATH)
tabs_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tabs_mod)

if SYSOP_LIB not in sys.path:
    sys.path.insert(0, SYSOP_LIB)
from swarmbox_sysop import agent as sysop_agent  # noqa: E402
from swarmbox_sysop import brain as sysop_brain  # noqa: E402
from swarmbox_sysop import ipc as sysop_ipc  # noqa: E402
from swarmbox_sysop import paths as sysop_paths  # noqa: E402
from swarmbox_sysop import risk as sysop_risk  # noqa: E402


FAKE_HC_PY = r"""#!/usr/bin/env python3
import json, os, struct, sys

STATE = os.environ["FAKE_HC_STATE"]
LOG = os.environ["FAKE_HC_LOG"]

def load():
    with open(STATE, encoding="utf-8") as f:
        return json.load(f)

def save(d):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(d, f)

def log(entry):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

argv = sys.argv[1:]
log({"argv": argv})

if not argv:
    sys.exit(0)

st = load()
if st.get("down") and argv[:2] != ["server", "start"]:
    print(json.dumps({"error": {"kind": "not_running", "message": "herdr-core server is not running"}}))
    sys.exit(1)

cmd = argv[0]

if cmd == "server":
    sub = argv[1] if len(argv) > 1 else ""
    if sub == "start":
        st["down"] = False
        save(st)
        print(json.dumps({"ok": True}))
        sys.exit(0)
    if sub == "status":
        print(json.dumps({"core": {"id": "fake", "name": "box"}, "live": len(st.get("terminals", []))}))
        sys.exit(0)
    sys.exit(0)

if cmd == "ls":
    want_labels = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--label" and i + 1 < len(argv):
            kv = argv[i + 1]
            if "=" in kv:
                k, v = kv.split("=", 1)
                want_labels[k] = v
            i += 2
            continue
        i += 1
    out = []
    for t in st.get("terminals", []):
        lbls = t.get("labels") or {}
        if all(lbls.get(k) == v for k, v in want_labels.items()):
            # Mirror real herdr-core 0.1.21: `hc ls --json` omits `labels` from summary entries
            summary = {k: v for k, v in t.items() if k != "labels"}
            out.append(summary)
    print(json.dumps({"hidden_finished": 0, "terminals": out}))
    sys.exit(0)

if cmd == "get":
    tid = argv[-1]
    for t in st.get("terminals", []):
        if t["address"] == tid or t.get("name") == tid:
            print(json.dumps(t))
            sys.exit(0)
    print(json.dumps({"error": {"kind": "not_found", "message": 'no terminal "%s"' % tid}}))
    sys.exit(1)

if cmd == "read":
    tid = argv[-1]
    lines = None
    if "--lines" in argv:
        lines = int(argv[argv.index("--lines") + 1])
    screens = st.get("screens", {})
    if tid not in screens:
        print(json.dumps({"error": {"kind": "not_found", "message": 'no terminal "%s"' % tid}}))
        sys.exit(1)
    txt = screens[tid]
    how = st.get("how", {}).get(tid, "screen")
    print(json.dumps({"complete": True, "how": "history" if lines else how, "text": txt}))
    sys.exit(0)

if cmd == "keys":
    # hc keys --json <tid> <key...>
    args = [a for a in argv[1:] if a != "--json"]
    tid, keys = args[0], args[1:]
    if not any(t["address"] == tid for t in st.get("terminals", [])):
        print(json.dumps({"error": {"kind": "not_found", "message": 'no terminal "%s"' % tid}}))
        sys.exit(1)
    log({"keys": {"terminal": tid, "keys": keys}})
    print(json.dumps({"status": None, "turn": 0}))
    sys.exit(0)

if cmd == "run":
    name = None
    if "--name" in argv:
        name = argv[argv.index("--name") + 1]
    labels = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--label" and i + 1 < len(argv):
            kv = argv[i + 1]
            if "=" in kv:
                k, v = kv.split("=", 1)
                labels[k] = v
            i += 2
            continue
        i += 1
    idx = len(st.get("terminals", [])) + 1
    addr = "t%d" % idx
    t = {"address": addr, "name": name or ("term-%d" % idx), "agent": "bash", "cwd": os.getcwd(),
         "state": "live", "cols": 100, "rows": 30, "created_ms": idx * 1000, "reported": False, "status": None, "labels": labels}
    st.setdefault("terminals", []).append(t)
    st.setdefault("screens", {})[addr] = "$ "
    # If this is a command wrapper run, simulate writing the exit status if requested
    if st.get("cmd_rc") is not None and len(argv) >= 2:
        status_path = argv[-1]
        if os.path.isabs(status_path):
            with open(status_path, "w", encoding="utf-8") as sf:
                sf.write(str(st["cmd_rc"]) + "\n")
    save(st)
    print(json.dumps(t))
    sys.exit(0)

if cmd == "attach":
    sys.exit(0)

if cmd == "rm":
    sys.exit(0)

if cmd == "kill":
    tid = argv[-1]
    if not any(t["address"] == tid for t in st.get("terminals", [])):
        print(json.dumps({"error": {"kind": "not_found", "message": 'no terminal "%s"' % tid}}))
        sys.exit(1)
    st["terminals"] = [t for t in st["terminals"] if t["address"] != tid]
    save(st)
    print(json.dumps({"ok": True}))
    sys.exit(0)

if cmd == "connect":
    # Framed JSON-RPC 2.0 server stub
    line = sys.stdin.buffer.readline()
    hello = json.loads(line.decode("utf-8"))
    resp = json.dumps({"jsonrpc": "2.0", "id": hello["id"], "result": {"framed": True, "version": "0.1.21"}}) + "\n"
    sys.stdout.buffer.write(resp.encode("utf-8"))
    sys.stdout.buffer.flush()
    attached_tid = None
    while True:
        hdr = sys.stdin.buffer.read(9)
        if len(hdr) < 9:
            break
        ch, kind, length = struct.unpack("<IBI", hdr)
        payload = sys.stdin.buffer.read(length) if length else b""
        if ch == 0 and kind == 0:
            req = json.loads(payload.decode("utf-8"))
            if req.get("method") == "terminal.attach":
                tid = req["params"]["terminal"]
                if not any(t["address"] == tid for t in st.get("terminals", [])):
                    err = json.dumps({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": 'no terminal "%s"' % tid, "data": {"kind": "not_found"}}}).encode()
                    sys.stdout.buffer.write(struct.pack("<IBI", 0, 0, len(err)) + err)
                    sys.stdout.buffer.flush()
                    continue
                attached_tid = tid
                ok = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"channel": 7, "terminal": tid}}).encode()
                sys.stdout.buffer.write(struct.pack("<IBI", 0, 0, len(ok)) + ok)
                sys.stdout.buffer.flush()
        elif ch == 7 and kind == 0:
            log({"framed_data": {"terminal": attached_tid, "text": payload.decode("utf-8", "replace")}})
        elif ch == 7 and kind == 2:
            break
    sys.exit(0)

sys.exit(0)
"""


_FAKE_HC_CODE = compile(FAKE_HC_PY, "fake-hc-herdr", "exec")
_FAKE_HC_LOCK = threading.Lock()


def _run_fake_hc_inproc(hc_bin):
    real_run = subprocess.run

    def run(argv, timeout=None, env=None, **kw):
        if not argv or argv[0] != hc_bin:
            return real_run(argv, timeout=timeout, env=env, **kw)
        out, err = io.StringIO(), io.StringIO()
        rc = 0
        with _FAKE_HC_LOCK:
            saved = (sys.argv, sys.stdout, sys.stderr)
            sys.argv, sys.stdout, sys.stderr = list(argv), out, err
            try:
                exec(_FAKE_HC_CODE, {"__name__": "__main__"})
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
            finally:
                sys.argv, sys.stdout, sys.stderr = saved
        want_text = kw.get("text") or kw.get("universal_newlines")
        stdout = out.getvalue() if want_text else out.getvalue().encode("utf-8")
        stderr = err.getvalue() if want_text else err.getvalue().encode("utf-8")
        return subprocess.CompletedProcess(argv, rc, stdout, stderr)

    return run


def make_exec(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class HerdrTabsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-herdr.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_file = os.path.join(self.tmp, "hc-state.json")
        self.log_file = os.path.join(self.tmp, "hc.log")
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir, exist_ok=True)
        self.hc_bin = os.path.join(self.tmp, "hc")
        make_exec(self.hc_bin, FAKE_HC_PY)
        self.old_env = {k: os.environ.get(k) for k in ("FAKE_HC_STATE", "FAKE_HC_LOG", "SWARMBOX_MUX", "SB_TABS_BACKEND", "SB_TABS_HC_BIN")}
        os.environ["FAKE_HC_STATE"] = self.state_file
        os.environ["FAKE_HC_LOG"] = self.log_file
        self.addCleanup(self._restore_env)
        p = mock.patch.object(tabs_mod.subprocess, "run", side_effect=_run_fake_hc_inproc(self.hc_bin))
        p.start()
        self.addCleanup(p.stop)

    def _restore_env(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write_state(self, state):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

    def read_log(self):
        if not os.path.exists(self.log_file):
            return []
        with open(self.log_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def tabs(self):
        return tabs_mod.Tabs(backend="herdr", binary=self.hc_bin, run_dir=self.run_dir, pause=0.0, verify_timeout=0.0)

    def test_list_active_marker_and_fallback(self):
        home = os.path.expanduser("~")
        self.write_state({
            "terminals": [
                {"address": "t1", "name": "shell", "agent": "bash", "cwd": home + "/proj", "state": "live", "cols": 120, "rows": 40, "created_ms": 100},
                {"address": "t2", "name": "claude", "agent": "claude", "cwd": "/srv/app", "state": "live", "cols": 120, "rows": 40, "created_ms": 200},
            ],
            "screens": {"t1": "$ ", "t2": "> "},
        })
        t = self.tabs()
        items = t.list_tabs()
        self.assertEqual([x["tab"] for x in items], ["t1", "t2"])
        self.assertEqual(items[0]["dir"], "~/proj")
        self.assertEqual(items[0]["label"], "1:shell")
        self.assertTrue(items[0]["active"])
        self.assertFalse(items[1]["active"])

        # Writing herdr-active-tab moves the active tab to t2
        with open(os.path.join(self.run_dir, "herdr-active-tab"), "w", encoding="utf-8") as f:
            f.write("t2\n")
        self.assertEqual(t.active()["tab"], "t2")

    def _two(self):
        self.write_state({
            "terminals": [
                {"address": "t1", "name": "shell", "agent": "bash", "cwd": "/tmp", "state": "live", "cols": 100, "rows": 30, "created_ms": 100},
                {"address": "t2", "name": "claude", "agent": "claude", "cwd": "/tmp", "state": "live", "cols": 100, "rows": 30, "created_ms": 200,
                 "status": {"state": "working", "progress": 74, "msg": "x" * 400, "app": "claude"}},
            ],
            "screens": {"t1": "$ ", "t2": "> "},
        })

    def test_list_tabs_carries_the_osc_status_cut(self):
        self._two()
        items = self.tabs().list_tabs()
        self.assertNotIn("status", items[0])
        self.assertEqual(items[1]["status"]["state"], "working")
        self.assertEqual(items[1]["status"]["progress"], 74)
        self.assertEqual(len(items[1]["status"]["msg"]), 160)

    def test_open_tab_runs_a_kept_terminal_with_the_agent_and_makes_it_active(self):
        self._two()
        res = self.tabs().open_tab(name="Shop.API v2", cwd=self.tmp, agent="Claude")
        self.assertEqual(res, {"ok": True, "tab": "t3", "name": "shop-api-v2", "agent": "claude"})
        run = [e["argv"] for e in self.read_log() if "argv" in e and e["argv"][:1] == ["run"]][-1]
        for flag in ("--bg", "--keep", "--no-parent"):
            self.assertIn(flag, run)
        self.assertEqual(run[run.index("--name") + 1], "shop-api-v2", "the name follows the rule of hc run --name")
        self.assertEqual(run[run.index("--cwd") + 1], self.tmp)
        self.assertEqual(run[run.index("--") + 1:], ["/bin/bash", "-lic", "SWARMBOX_WORKTREE_GUARD=0 claude; exec /bin/bash -l"])
        with open(os.path.join(self.run_dir, "herdr-active-tab"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "t3")

    def test_open_tab_refuses_an_unknown_agent_and_a_missing_dir(self):
        self._two()
        with self.assertRaises(tabs_mod.TabsError):
            self.tabs().open_tab(agent="rm -rf /")
        with self.assertRaises(tabs_mod.TabsError):
            self.tabs().open_tab(cwd=os.path.join(self.tmp, "nope"))
        self.assertFalse([e for e in self.read_log() if "argv" in e and e["argv"][:1] == ["run"]], "nothing was started")

    def test_focus_tab_moves_the_active_marker(self):
        self._two()
        t = self.tabs()
        self.assertEqual(t.focus_tab("claude")["tab"], "t2")
        self.assertEqual(self.tabs().active()["tab"], "t2")

    def test_close_tab_kills_and_removes_the_terminal(self):
        self._two()
        self.assertEqual(self.tabs().close_tab("t2")["tab"], "t2")
        cmds = [e["argv"][:2] for e in self.read_log() if "argv" in e and e["argv"][:1] in (["kill"], ["rm"])]
        self.assertEqual(cmds, [["kill", "t2"], ["rm", "t2"]])
        self.assertEqual([x["tab"] for x in self.tabs().list_tabs()], ["t1"])

    def test_sysop_role_terminal_is_hidden_from_tabs(self):
        self.write_state({
            "terminals": [
                {"address": "t1", "name": "shell", "agent": "bash", "cwd": "/tmp", "state": "live", "cols": 100, "rows": 30, "created_ms": 100, "labels": {}},
                {"address": "t2", "name": "sysop", "agent": "python3", "cwd": "/tmp", "state": "live", "cols": 100, "rows": 30, "created_ms": 200, "labels": {"swarmbox.role": "sysop"}},
            ],
            "screens": {"t1": "$ ", "t2": "sysop ready"},
        })
        items = self.tabs().list_tabs()
        self.assertEqual([x["tab"] for x in items], ["t1"])
        # Even if active marker points to hidden sysop terminal, active() falls back to t1
        with open(os.path.join(self.run_dir, "herdr-active-tab"), "w", encoding="utf-8") as f:
            f.write("t2\n")
        self.assertEqual(self.tabs().active()["tab"], "t1")

    def test_screen_redacts_secrets_and_clips_lines(self):
        self.write_state({
            "terminals": [
                {"address": "t1", "name": "shell", "agent": "bash", "cwd": "/tmp", "state": "live", "cols": 110, "rows": 32, "created_ms": 1},
            ],
            "screens": {
                "t1": "line1\nline2\nAPI_KEY=sk-1234567890abcdefghijklmnop\n\x1b[31merror: boom\x1b[0m\n",
            },
        })
        sc = self.tabs().screen("t1", lines=2)
        self.assertEqual(sc["size"], [110, 32])
        self.assertNotIn("sk-1234567890", sc["text"])
        self.assertIn("[REDACTED]", sc["text"])
        self.assertIn("[err]error: boom[/err]", sc["text"])
        self.assertNotIn("line1", sc["text"])

    def test_send_literal_utf8_and_keys_mapping(self):
        self.write_state({
            "terminals": [
                {"address": "t1", "name": "shell", "agent": "bash", "cwd": "/tmp", "state": "live", "cols": 100, "rows": 30, "created_ms": 1, "reported": False},
            ],
            "screens": {"t1": "$ "},
        })
        res = self.tabs().send("t1", input="echo !?{} café{Esc}{BTab}{C-c}{M-x}{F5}{PgUp}{Delete}{Enter}")
        self.assertTrue(res["ok"])
        self.assertTrue(res["submitted"])
        entries = self.read_log()
        framed = [e["framed_data"]["text"] for e in entries if "framed_data" in e]
        keys = [e["keys"]["keys"][0] for e in entries if "keys" in e]
        self.assertEqual(framed, ["echo !?{} café"])
        self.assertEqual(keys, ["esc", "shift+tab", "ctrl+c", "alt+x", "f5", "pageup", "delete", "enter"])

    def test_native_osc7501_blocked_and_busy_and_idle(self):
        # 1. OSC 7501 blocked -> dialog_open
        self.write_state({
            "terminals": [{
                "address": "t1", "name": "agent", "agent": "bash", "cwd": "/tmp", "state": "live",
                "cols": 100, "rows": 30, "created_ms": 1, "reported": True,
                "status": {"state": "blocked", "kind": "permission", "msg": "Run deploy?"},
            }],
            "screens": {"t1": "waiting..."},
        })
        with self.assertRaises(tabs_mod.TabsError) as ctx:
            self.tabs().send("t1", run="hello")
        self.assertEqual(ctx.exception.code, "dialog_open")

        # 2. OSC 7501 working -> busy_tab unless queue=True
        self.write_state({
            "terminals": [{
                "address": "t1", "name": "agent", "agent": "bash", "cwd": "/tmp", "state": "live",
                "cols": 100, "rows": 30, "created_ms": 1, "reported": True,
                "status": {"state": "working", "progress": 50, "msg": "Running tests"},
            }],
            "screens": {"t1": "working..."},
        })
        with self.assertRaises(tabs_mod.TabsError) as ctx2:
            self.tabs().send("t1", run="next task")
        self.assertEqual(ctx2.exception.code, "busy_tab")
        ok = self.tabs().send("t1", run="next task", queue=True)
        self.assertTrue(ok["ok"])

        # 3. OSC 7501 idle -> accepted cleanly
        self.write_state({
            "terminals": [{
                "address": "t1", "name": "agent", "agent": "bash", "cwd": "/tmp", "state": "live",
                "cols": 100, "rows": 30, "created_ms": 1, "reported": True,
                "status": {"state": "idle"},
            }],
            "screens": {"t1": "ready"},
        })
        ok2 = self.tabs().send("t1", run="run tests")
        self.assertTrue(ok2["ok"])

    def test_heuristic_fallback_when_not_reported(self):
        rule = "─" * 10
        self.write_state({
            "terminals": [{
                "address": "t1", "name": "claude", "agent": "claude", "cwd": "/tmp", "state": "live",
                "cols": 100, "rows": 30, "created_ms": 1, "reported": False, "status": None,
            }],
            "screens": {"t1": "%s\nDo you want to run rm?\nEnter to confirm · Esc to cancel\n" % rule},
        })
        with self.assertRaises(tabs_mod.TabsError) as ctx:
            self.tabs().send("t1", run="hi")
        self.assertEqual(ctx.exception.code, "dialog_open")

    def test_errors_no_backend_no_session_no_such_tab(self):
        # Missing binary -> no_backend (exit 4)
        missing = tabs_mod.Tabs(backend="herdr", binary=os.path.join(self.tmp, "nope-hc"), run_dir=self.run_dir)
        with self.assertRaises(tabs_mod.TabsError) as ctx:
            missing.list_tabs()
        self.assertEqual(ctx.exception.code, "no_backend")
        self.assertEqual(tabs_mod.EXIT[ctx.exception.code], 4)

        # Daemon down -> no_session (exit 4)
        self.write_state({"down": True, "terminals": []})
        with self.assertRaises(tabs_mod.TabsError) as ctx2:
            self.tabs().list_tabs()
        self.assertEqual(ctx2.exception.code, "no_session")
        self.assertEqual(tabs_mod.EXIT[ctx2.exception.code], 4)

        # Unknown tab -> no_such_tab (exit 1)
        self.write_state({"terminals": [], "screens": {}})
        with self.assertRaises(tabs_mod.TabsError) as ctx3:
            self.tabs().screen("t99", None)
        self.assertEqual(ctx3.exception.code, "no_such_tab")

    def test_cli_uses_herdr_without_any_selection(self):
        self.write_state({
            "terminals": [{"address": "t1", "name": "shell", "agent": "bash", "cwd": "/tmp", "state": "live", "cols": 80, "rows": 24, "created_ms": 1}],
            "screens": {"t1": "$ "},
        })
        env = {k: v for k, v in os.environ.items() if k not in ("SWARMBOX_MUX", "SB_TABS_BACKEND")}
        env.update(SB_TABS_HC_BIN=self.hc_bin, SB_RUN_DIR=self.run_dir)
        p = subprocess.run([sys.executable, TABS_PATH, "list"], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["tab"], "t1")


class HerdrShellBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-herdr-sh.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.run_dir = os.path.join(self.tmp, "run")
        self.bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(self.home)
        os.makedirs(self.run_dir)
        os.makedirs(self.bin_dir)
        with open(os.path.join(self.run_dir, "ready"), "w", encoding="utf-8") as f:
            f.write("ok\n")
        self.state_file = os.path.join(self.tmp, "hc-state.json")
        self.log_file = os.path.join(self.tmp, "hc.log")
        self.hc_bin = os.path.join(self.bin_dir, "hc")
        make_exec(self.hc_bin, FAKE_HC_PY)
        self.web_log = os.path.join(self.tmp, "web.log")
        self.fake_web = os.path.join(self.tmp, "fake-herdr-web")
        make_exec(self.fake_web, '#!/bin/sh\nprintf "WEB %%s\\n" "$*" >> "%s"\n' % self.web_log)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"down": True, "terminals": [], "screens": {}}, f)

    def env(self, extra=None):
        e = {
            "PATH": self.bin_dir + os.pathsep + os.environ["PATH"],
            "HOME": self.home,
            "SWARMBOX_MUX": "herdr",
            # the checkout's backend, not the one installed in a box (/usr/local/lib/swarmbox/mux comes first otherwise)
            "SWARMBOX_TEST_MUX_DIR": os.path.join(ROOT, "container", "scripts", "mux"),
            "SWARMBOX_TEST_HC_BIN": self.hc_bin,
            "SWARMBOX_TEST_HERDR_WEB": self.fake_web,
            "SWARMBOX_TEST_LIB": os.path.join(ROOT, "container", "scripts"),
            "SWARMBOX_TEST_RUN_DIR": self.run_dir,
            "FAKE_HC_STATE": self.state_file,
            "FAKE_HC_LOG": self.log_file,
        }
        if extra:
            e.update(extra)
        return e

    def test_serve_init_seeds_config_once_and_creates_initial_tab(self):
        mux_dir = os.path.join(ROOT, "container", "scripts", "mux")
        script = (
            'log() { :; }; warn() { echo "WARN:$*" >&2; }; have() { command -v "$1" >/dev/null 2>&1; }; '
            'run_logged() { "$@"; }; '
            '. "%s/mux.sh"; mux_serve_init' % mux_dir
        )
        p = subprocess.run(["bash", "-c", script], env=self.env(), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        core_cfg = os.path.join(self.home, ".config", "herdr-core", "config.toml")
        self.assertTrue(os.path.isfile(core_cfg))
        # the old herdr TUI is gone, so its config is no longer seeded
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "herdr")))
        with open(core_cfg, encoding="utf-8") as f:
            self.assertIn("notes = false", f.read())
        with open(self.state_file, encoding="utf-8") as f:
            st = json.load(f)
        self.assertFalse(st["down"])
        self.assertEqual(len(st["terminals"]), 1)
        self.assertEqual(st["terminals"][0]["name"], "shell")

        # User edits are preserved on subsequent runs
        with open(core_cfg, "w", encoding="utf-8") as f:
            f.write("# custom user config\n")
        p2 = subprocess.run(["bash", "-c", script], env=self.env(), capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        with open(core_cfg, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# custom user config\n")

    def _run_on_pty(self, argv, env):
        master, slave = pty.openpty()
        try:
            p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=env, text=True)
            os.close(slave)
            slave = -1
            _, err = p.communicate(timeout=10)
            return p.returncode, err
        finally:
            if slave >= 0:
                os.close(slave)
            os.close(master)

    def test_attach_command_returns_exit_code_and_handles_detach(self):
        # Avoid 5x 0.1s status-file flush sleeps in herdr.sh when testing the detached path
        make_exec(os.path.join(self.bin_dir, "sleep"), "#!/bin/sh\nexit 0\n")
        # 1. Command finishes with exit code 42
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"down": False, "terminals": [], "screens": {}, "cmd_rc": 42}, f)
        rc, err = self._run_on_pty(["bash", ATTACH_PATH, "false"], self.env({"SWARMBOX_TEST_READY_TIMEOUT": "2"}))
        self.assertEqual(rc, 42, err)

        # 2. Detached before finishing -> exit 0 + detached note
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump({"down": False, "terminals": [], "screens": {}}, f)
        rc2, err2 = self._run_on_pty(["bash", ATTACH_PATH, "sleep", "10"], self.env({"SWARMBOX_TEST_READY_TIMEOUT": "2"}))
        self.assertEqual(rc2, 0, err2)
        self.assertIn("detached; the command keeps running", err2)

    def test_swarmbox_web_dispatches_to_herdr_gateway_and_voice_front(self):
        # there is no page to render any more: run and restart are the only modes
        p_render = subprocess.run(["bash", WEB_PATH, "render"], env=self.env({"SWARMBOX_VOICE_WEB": "0"}), capture_output=True, text=True)
        self.assertEqual(p_render.returncode, 64, p_render.stderr)

        # Direct run without voice addon
        p_run = subprocess.run(
            ["bash", WEB_PATH, "run"],
            env=self.env({"SWARMBOX_VOICE_WEB": "0", "SWARMBOX_TEST_WEB_PORT": "7788", "SWARMBOX_TEST_WEB_IFACE": "127.0.0.1"}),
            capture_output=True, text=True,
        )
        self.assertEqual(p_run.returncode, 0, p_run.stderr)
        with open(self.web_log, encoding="utf-8") as f:
            self.assertIn("WEB -p 7788 -i 127.0.0.1", f.read())

        # With voice addon present: swarmbox-web wraps herdr-web inside swarmbox-voice front
        voice_prefix = os.path.join(self.tmp, "voice-addon")
        os.makedirs(os.path.join(voice_prefix, "bin"))
        os.makedirs(os.path.join(voice_prefix, "lib", "swarmbox_voice"))
        for rel in ("lib/swarmbox_voice/front.py",):
            open(os.path.join(voice_prefix, rel), "w").close()
        voice_log = os.path.join(self.tmp, "voice-front.log")
        voice_bin = os.path.join(voice_prefix, "bin", "swarmbox-voice")
        make_exec(voice_bin, '#!/bin/sh\nprintf "FRONT %%s\\n" "$*" >> "%s"\n' % voice_log)
        make_exec(os.path.join(self.bin_dir, "swarmbox-addon"), '#!/bin/sh\nprintf "%%s\\n" "%s"\n' % voice_bin)
        p_voice = subprocess.run(
            ["bash", WEB_PATH, "run"],
            env=self.env({"SWARMBOX_VOICE_WEB": "1", "SWARMBOX_TEST_WEB_PORT": "7789", "SWARMBOX_TEST_WEB_IFACE": "127.0.0.1"}),
            capture_output=True, text=True,
        )
        self.assertEqual(p_voice.returncode, 0, p_voice.stderr)
        with open(voice_log, encoding="utf-8") as f:
            line = f.read()
        self.assertIn("FRONT front --listen 127.0.0.1:7789 --server-port 7680 -- %s -p 7789 -i 127.0.0.1" % self.fake_web, line)


class HerdrSysopAndAssetsTest(unittest.TestCase):
    def test_sysop_brain_forwards_tabs_env_and_web_source_note(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-herdr-sysop.")
        self.addCleanup(shutil.rmtree, tmp, True)
        pth = sysop_paths.Paths({"SB_RUN_DIR": os.path.join(tmp, "run"), "SB_STATE_DIR": os.path.join(tmp, "state")})
        mcp_path = os.path.join(tmp, "mcp.json")
        old = {k: os.environ.get(k) for k in ("SWARMBOX_MUX", "SB_TABS_BACKEND", "SB_TABS_HC_BIN")}
        os.environ["SWARMBOX_MUX"] = "herdr"
        os.environ["SB_TABS_BACKEND"] = "herdr"
        os.environ["SB_TABS_HC_BIN"] = "/usr/local/bin/hc"
        try:
            sysop_brain.write_mcp_config(mcp_path, os.path.join(tmp, "ctx.json"), pth, SYSOP_LIB)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        with open(mcp_path, encoding="utf-8") as f:
            doc = json.load(f)
        env = doc["mcpServers"]["sysop"]["env"]
        self.assertNotIn("SWARMBOX_MUX", env)
        self.assertEqual(env["SB_TABS_BACKEND"], "herdr")
        self.assertEqual(env["SB_TABS_HC_BIN"], "/usr/local/bin/hc")
        self.assertIn("web", sysop_brain.SOURCE_NOTES)

    def test_sysop_snapshot_turns_are_the_recent_goals_as_a_conversation(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-turns.")
        self.addCleanup(shutil.rmtree, tmp, True)
        run_dir, state = os.path.join(tmp, "run"), os.path.join(tmp, "state")
        goals = os.path.join(state, "swarmbox", "sysop", "goals")
        now = __import__("time").time()

        FN = "too" + "l"     # the key of a call in calls.jsonl, as hc-client.mjs spells it (FN_KEY)

        def goal(gid, **st):
            d = os.path.join(goals, gid)
            os.makedirs(d)
            with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
                json.dump(dict({"id": gid, "source": "web", "calls": [], "say": []}, **st), f)
            return d

        goal("old", text="ancient", state="done", started=now - 14 * 3600, ended=now - 13 * 3600, summary="old reply")
        goal("g1", text="o que esta rodando?", state="done", started=now - 60, ended=now - 50,
             calls=[{FN: "list_tabs", "args": {}, "t": now - 58}, {FN: "say", "args": {"text": "x"}, "t": now - 57},
                    {FN: "read_tab", "args": {"tab": "t2"}, "t": now - 55, "is_error": True}, {FN: "done", "args": {}, "t": now - 50}],
             say=[{"text": "olhando as abas", "t": now - 57}, {"text": "- t2: claude idle", "t": now - 51}], summary="- t2: claude idle")
        cur = goal("g2", text="roda os testes", state="running", started=now - 5)
        with open(os.path.join(cur, "calls.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({FN: "run", "args": {"tab": "t1", "command": "pytest -q"}, "t": now - 2}) + "\n")
        os.makedirs(os.path.join(run_dir, "sysop"))
        with open(os.path.join(run_dir, "sysop", "status.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "current": "g2", "queue": []}, f)
        js = r"""
import assert from 'node:assert/strict';
import { readSysopSnapshot, startNewConversation } from %s;
const s = readSysopSnapshot([]);
assert.equal(s.up, true);
assert.deepEqual(s.turns.map((t) => t.id), ['g1', 'g2'], 'oldest first, a goal older than 12 h is left out');
const [a, b] = s.turns;
assert.equal(a.prompt, 'o que esta rodando?');
assert.equal(a.reply, '- t2: claude idle');
assert.deepEqual(a.notes, ['olhando as abas'], 'a say that repeats the reply is not shown twice');
assert.deepEqual(a.actions.map((x) => x.fn), ['list_tabs', 'read_tab'], 'say and done are not actions');
assert.equal(a.actions[1].ok, false);
assert.equal(a.running, false);
assert.equal(b.running, true);
assert.equal(b.reply, '');
assert.equal(b.live_action, 'run → t1');
assert.equal(s.state, 'working');
assert.equal(s.sentence, 'run → t1');
assert.ok(s.steps.some((x) => x.kind === 'goal' && x.text === 'roda os testes'), 'the flat steps of the current goal stay for the cockpit');
// New: the goals before it leave the panel (the running one stays), and history.py reads the same file
startNewConversation(Date.now() / 1000 - 30);
assert.deepEqual(readSysopSnapshot([]).turns.map((t) => t.id), ['g2']);
const fs = await import('node:fs');
const saved = JSON.parse(fs.readFileSync(process.env.XDG_STATE_HOME + '/swarmbox/sysop/conversation.json', 'utf8'));
assert.ok(saved.since > 0);
assert.equal((fs.statSync(process.env.XDG_STATE_HOME + '/swarmbox/sysop/conversation.json').mode & 0o777), 0o600);
""" % json.dumps(HERDR_CLIENT)
        env = dict(os.environ, SB_RUN_DIR=run_dir, XDG_STATE_HOME=state)
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_the_panel_reads_the_automations_and_the_notes_of_the_sysop(self):
        """sysop-store.mjs: the live schedules and triggers (ended ones for 6 hours, newest first) and the notes, with the line the sysop
        wrote for each (docs/sysop-automations-design.md)"""
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, True)
        sysop = os.path.join(state, "sysop")
        os.makedirs(os.path.join(sysop, "notes"))
        now = time.time()
        with open(os.path.join(sysop, "automations.json"), "w", encoding="utf-8") as f:
            json.dump({"seq": 4, "items": [
                {"id": "a1", "kind": "schedule", "state": "active", "desc": "a1 [active] every 10 min, 2 runs", "prompt": "look at agy", "runs": 2, "next": now + 60},
                {"id": "a2", "kind": "trigger", "state": "ended", "desc": "a2 [ended] when 1:api becomes blocked", "prompt": "p", "ended": now - 8 * 3600},
                {"id": "a3", "kind": "trigger", "state": "paused", "desc": "a3 [paused] when 1:api shows /FAILED/", "prompt": "p"},
                {"id": "../x", "kind": "schedule", "state": "active"}]}, f)
        with open(os.path.join(sysop, "notes", "agy-quota.md"), "w", encoding="utf-8") as f:
            f.write("- quota resets at 14:00\n- then tell it to go on\n")
        with open(os.path.join(sysop, "notes", "Bad Name.md"), "w", encoding="utf-8") as f:
            f.write("x\n")
        js = r"""
import assert from 'node:assert/strict';
import { readAutomations, readNotes } from %s;
const a = readAutomations(%s);
assert.deepEqual(a.map((x) => [x.id, x.state]), [['a1', 'active'], ['a3', 'paused']], 'an automation ended 8 h ago and a bad id are left out');
assert.equal(a[0].desc, 'a1 [active] every 10 min, 2 runs');
assert.ok(a[0].next > Date.now(), 'times in milliseconds for the page');
const n = readNotes(%s);
assert.deepEqual(n.map((x) => x.name), ['agy-quota'], 'only the names the sysop writes');
assert.equal(n[0].preview, 'quota resets at 14:00 / then tell it to go on');
""" % (json.dumps(os.path.join(ROOT, "container", "web", "herdr", "sysop-store.mjs")), json.dumps(sysop), json.dumps(sysop))
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_rename_from_the_page_keeps_the_older_titles_as_swarmbox_tabs_does(self):
        """routes-tabs.mjs pastTitles/nextPastTitles: the label swarmbox.past_titles is written by both renames, so they agree on it"""
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        js = r"""
import assert from 'node:assert/strict';
const { pastTitles, nextPastTitles, PAST_TITLES } = await import(%s);
assert.equal(PAST_TITLES, 'swarmbox.past_titles');
assert.deepEqual(nextPastTitles('', '', 'timer'), [], 'no title before: nothing to keep');
assert.deepEqual(nextPastTitles('["timer"]', 'Canal do Sysop', 'Timer Canal'), ['Canal do Sysop', 'timer']);
assert.deepEqual(nextPastTitles('["Timer Canal","Canal do Sysop"]', 'x', 'TIMER CANAL'), ['x', 'Canal do Sysop'], 'the new title is no older one');
assert.deepEqual(nextPastTitles(JSON.stringify(['a', 'b', 'c', 'd', 'e']), 'z', 'new').length, 4);
for (const raw of ['', 'not json', '{"a":1}', '[1,null]']) assert.deepEqual(pastTitles(raw), [], raw);
""" % json.dumps("file://" + os.path.join(ROOT, "container", "web", "herdr", "routes-tabs.mjs"))
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_tab_references_in_a_reply_are_one_chip_each(self):
        """public/tabrefs.js: every way a reply names a tab resolves to the same tab, with its name as the page shows it (the replies of a real
        session wrote `t2`, t3, `1:shell` and "`escritorio` (t8)" in one conversation, and only some of them were highlighted)"""
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        js = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const ctx = { module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(%s, 'utf8'), ctx);
const { parse } = ctx.module.exports;
const tabs = [
  { address: 't2', name: 'swarmbox', aliases: ['shell'], kind: 'claude', live: true },
  { address: 't1x', name: 'Sysop Review', aliases: ['agy-wt-5f3e'], kind: 'agy', live: true },
  { address: 't6', name: 'sabrina', aliases: ['shell-4'], kind: 'claude', live: true },
  { address: 't3', name: 'winix', aliases: ['shell-3'], kind: 'agy', live: false },
];
const show = (s) => parse(s, tabs).map((x) => x.t === 'text' ? x.v : x.t === 'tab' ? '[' + x.tab.name + (x.tab.live ? '' : '*') + ']' : '<' + x.t + ':' + x.v + '>').join('');
assert.equal(show('read tab t1x and t2'), 'read tab [Sysop Review] and [swarmbox]', 'base-36 herdr-core addresses like t1x resolve to chips');
assert.equal(show('agentes: `t2` (~/swarmbox, ativa), t3 (~/winix) e t9.'), 'agentes: [swarmbox] (~/swarmbox, ativa), [winix*] (~/winix) e [t9*].');
assert.equal(show('- `1:shell` (`t2`, ativa): em ~/swarmbox'), '- [swarmbox] (ativa): em ~/swarmbox', 'the numbered label resolves; the id after it goes');
assert.equal(show('a aba `sabrina` (t6) e shell-4'), 'a aba [sabrina] e [sabrina]', 'the herdr name is an alias of the shown name');
assert.equal(show('voltou ao shell; SwarmBox em ~/swarmbox/x.py e swarmbox.md'), 'voltou ao shell; SwarmBox em ~/swarmbox/x.py e swarmbox.md', 'a word, a product, a path, a file: never a tab');
assert.equal(show('`main`: 24 testes passaram, 2 failed, 0 failed'), '<code:main>: <ok:24 testes passaram>, <bad:2 failed>, <ok:0 failed>');
assert.equal(show('swarmbox'), '[swarmbox]');
assert.equal(show('- `9:escritorio`: fresh; and 7:gone'), '- [escritorio*]: fresh; and [gone*]', 'a numbered label of a tab this page never saw is still a chip, by its name');
assert.equal(show('Agendado: em 1 minuto (2026-11-27 13:24), de novo às `14:05`'), 'Agendado: em 1 minuto (2026-11-27 13:24), de novo às <code:14:05>', 'a time is never a numbered label');
assert.equal(show('**Resumo:** **swarmbox** e **`sabrina`** ok'), '<bold:Resumo:> [swarmbox] e [sabrina] ok', 'markdown bold renders cleanly and bold tab names become chips');
""" % json.dumps(os.path.join(ROOT, "container", "web", "herdr", "public", "tabrefs.js"))
        p = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(os.path.join(ROOT, "container", "web", "herdr", "public", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertLess(html.index('src="/tabrefs.js"'), html.index('src="/app.js"'), "the parser loads before the page that uses it")

    def test_sysop_risk_guards_hc_and_herdr_controls(self):
        for cmd in ("hc send t1 ls", "hc kill t1", "herdr-core server stop", "herdr server stop"):
            lvl, _ = sysop_risk.classify_command(cmd)
            self.assertEqual(lvl, "high", cmd)
        for safe in ("ls -la", "git status", "cat arch.txt"):
            lvl, _ = sysop_risk.classify_command(safe)
            self.assertEqual(lvl, "low", safe)

    def test_settings_addon_state_follows_the_install_record(self):
        # Settings > Addons shows Install for an addon that is not installed. An addon that updates itself has no `current` link
        # (its record is self/.swarmbox-env), so it must read as installed by that record, like `swarmbox-addon list` does; a
        # managed addon whose link exists without the record is an install that did not finish. A floating install (`latest`) shows
        # the version its program reports (`--version`, standard output only), read again when an update replaces the program; a
        # pinned one shows its version; a program that cannot say leaves the channel.
        if not shutil.which("node"):
            self.skipTest("node not on PATH")
        tmp = tempfile.mkdtemp(prefix="addon-state-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        image, data = os.path.join(tmp, "image"), os.path.join(tmp, "data", "swarmbox", "addons")
        home_bin = os.path.join(tmp, "home", ".local", "bin")
        os.makedirs(home_bin)

        def prog(path, out):
            with open(path, "w") as f:
                f.write("#!/bin/sh\n[ \"$1\" = --version ] || exit 9\necho 'warning: noise' >&2\n%s\n" % out)
            os.chmod(path, 0o755)

        addons = (("selfup", "self", "latest"), ("selfmute", "self", "latest"), ("selfnone", "self", "latest"),
                  ("floating", "managed", "latest"), ("managed", "managed", "1.2.3"), ("halfdone", "managed", "1.2.3"))
        for name, update, version in addons:
            os.makedirs(os.path.join(image, name))
            with open(os.path.join(image, name, "addon.conf"), "w") as f:
                f.write('SCHEMA=1\nNAME=%s\nDESCRIPTION="x"\nVERSION=%s\nUPDATE=%s\nCOMMANDS="%s"\n' % (name, version, update, name))
        for name in ("selfup", "selfmute"):
            os.makedirs(os.path.join(data, name, "self"))
            open(os.path.join(data, name, "self", ".swarmbox-env"), "w").close()
        prog(os.path.join(home_bin, "selfup"), "echo '2.1.332 (Claude Code)'")
        prog(os.path.join(home_bin, "selfmute"), "exit 1")
        os.makedirs(os.path.join(data, "selfnone", "self"))   # a folder without the record: not installed
        for name, ver, record in (("floating", "latest", True), ("managed", "1.2.3", True), ("halfdone", "1.2.3", False)):
            os.makedirs(os.path.join(data, name, ver, "bin"))
            os.symlink(ver, os.path.join(data, name, "current"))
            prog(os.path.join(data, name, ver, "bin", name), "echo 'opencode v2.4.2'")
            if record:
                open(os.path.join(data, name, ver, ".swarmbox-env"), "w").close()
        js = """
import fs from 'node:fs';
import { readBoxConfigSnapshot } from %r;
const show = () => Object.fromEntries(readBoxConfigSnapshot([], process.env).addons
  .map((a) => [a.name, [a.installed, a.installedVersion, a.selfUpdate]]));
console.log(JSON.stringify(show()));
// an update of itself replaces the program: the version shown follows
const p = process.env.HOME + '/.local/bin/selfup';
fs.writeFileSync(p + '.new', "#!/bin/sh\\necho 2.1.400\\n", { mode: 0o755 });
fs.renameSync(p + '.new', p);
console.log(JSON.stringify(show()));
""" % (HERDR_CLIENT,)
        env = dict(os.environ, HOME=os.path.join(tmp, "home"), XDG_DATA_HOME=os.path.join(tmp, "data"),
                   XDG_CONFIG_HOME=os.path.join(tmp, "config"), SWARMBOX_IMAGE_ADDONS_DIR=image,
                   SWARMBOX_TEST_IMAGE_STATE=os.path.join(tmp, "baked"))
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        first, second = [json.loads(l) for l in p.stdout.strip().splitlines()[-2:]]
        self.assertEqual(first, {
            "selfup": [True, "2.1.332", True], "selfmute": [True, "latest", True], "selfnone": [False, "", True],
            "floating": [True, "2.4.2", False], "managed": [True, "1.2.3", False], "halfdone": [False, "", False]})
        self.assertEqual(second["selfup"], [True, "2.1.400", True])
        self.assertEqual(os.listdir(os.path.join(tmp, "home")), [".local"], "the version check made nothing in HOME")

    def test_build_commit_is_the_baked_file_else_the_checkout_head(self):
        # About shows the commit: the image's COMMIT file (the SWARMBOX_COMMIT build argument), else, run from a checkout, its HEAD
        if not shutil.which("node"):
            self.skipTest("node not on PATH")
        tmp = tempfile.mkdtemp(prefix="sb-commit-")
        self.addCleanup(shutil.rmtree, tmp, True)
        baked = os.path.join(tmp, "COMMIT")
        with open(baked, "w") as f:
            f.write("0123456789abcdef0123456789abcdef01234567-dirty\n")
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git = ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        js = """
import { readBuildCommit } from %r;
console.log(JSON.stringify([readBuildCommit(%r, %r), readBuildCommit(%r, %r)]));
""" % (os.path.join(os.path.dirname(HERDR_CLIENT), "box-config.mjs"), baked, repo, os.path.join(tmp, "none"), repo)
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True,
                           env=dict(os.environ, HOME=tmp))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]),
                         ["0123456789abcdef0123456789abcdef01234567-dirty", head])

    def test_herdr_web_cli_args_and_origin_guard(self):
        if not shutil.which("node"):
            self.skipTest("node not on PATH")
        herdr_dir = os.path.dirname(HERDR_SERVER)
        herdr_modules = sorted(
            os.path.join(herdr_dir, name)
            for name in os.listdir(herdr_dir)
            if name.endswith(".mjs")
        )
        server_parts = []
        for p in herdr_modules:
            with open(p, encoding="utf-8") as f:
                server_parts.append(f.read())
        server_src = "\n".join(server_parts)
        with open(HERDR_CLIENT, encoding="utf-8") as f:
            client_src = f.read()
        with open(HERDR_COCKPIT, encoding="utf-8") as f:
            cockpit_src = f.read()
        self.assertIn("frame-ancestors 'self'", server_src)
        self.assertIn("X-Frame-Options", server_src)
        self.assertIn("checkSameOrigin", server_src)
        self.assertIn("FRAME_CREDIT", client_src)
        self.assertIn("herdr-active-tab", client_src)
        self.assertIn("swarmbox.role", client_src)
        self.assertIn("computeLayout", cockpit_src)
        # Batch syntax checks for all .mjs modules + app.js + public/app/*.js + hc-client.mjs pure helper assertions into ONE node process
        app_js = os.path.join(ROOT, "container", "web", "herdr", "public", "app.js")
        app_sub_dir = os.path.join(ROOT, "container", "web", "herdr", "public", "app")
        app_modules = [app_js] + (
            sorted(
                os.path.join(app_sub_dir, name)
                for name in os.listdir(app_sub_dir)
                if name.endswith(".js")
            )
            if os.path.isdir(app_sub_dir)
            else []
        )
        check_js = """
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { isHiddenTerminal, sanitizeTabName, uniqueTabName, DEFAULT_THEME, THEME_ORDER, readBoxConfigSnapshot } from %s;
for (const p of %s) {
  new vm.SourceTextModule(fs.readFileSync(p, 'utf8'), { identifier: p });
}
for (const p of %s) {
  new vm.SourceTextModule(fs.readFileSync(p, 'utf8'), { identifier: p });
}
assert.equal(isHiddenTerminal({ labels: { 'swarmbox.role': 'sysop' } }), true);
assert.equal(isHiddenTerminal({ labels: {} }), false);
assert.equal(isHiddenTerminal({}), false);
assert.ok(!/^t\\d+$/.test(sanitizeTabName('t1', 'shell')));
assert.equal(uniqueTabName('shell', 'shell', [{ name: 'shell' }, { name: 'shell-2' }]), 'shell-3');
assert.equal(DEFAULT_THEME, 'catppuccin');
assert.equal(THEME_ORDER.length, 5);
assert.equal(THEME_ORDER[0], 'catppuccin');
const cfg = readBoxConfigSnapshot([], { SWARMBOX_WEB_PORT: '7699', SWARMBOX_SYSOP_AUTONOMY: 'confirm-all', SWARMBOX_VOICE_LANGUAGE: 'pt' });
assert.equal(cfg.box.WEB_PORT.value, '7699');
assert.equal(cfg.box.WEB_PORT.custom, true);
assert.equal(cfg.sysop.settings['sysop.autonomy'].value, 'confirm-all');
assert.equal(cfg.voice.settings['voice.language'].value, 'pt');
assert.ok(Array.isArray(cfg.addons));
assert.ok(Array.isArray(cfg.mcp));
""" % (json.dumps(HERDR_CLIENT), json.dumps(herdr_modules), json.dumps(app_modules))
        p2 = subprocess.run(["node", "--experimental-vm-modules", "--no-warnings", "--input-type=module", "-e", check_js], capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0, p2.stderr)

        # Verify app.js (+ public/app/*.js) per-tab live sessions, zero-scroll hydration, reconnect resilience, mobile inertia scroll, and Settings panel
        app_parts = []
        for p in app_modules:
            with open(p, encoding="utf-8") as f:
                app_parts.append(f.read())
        app_src = "\n".join(app_parts)
        for token in (
            "term-loading",
            "finishHydration",
            "tabSessions",
            "pendingInput",
            "ensureConnectionsAlive",
            "ws.onclose",
            "startTouchCoast",
            "TOUCH_FRICTION",
            "openSettings",
            "stagedHostConfig",
            "buildHostApplyCommand",
            "addonActionLive",
            "term.paste(",
            "getSmartSelection",
            "looksLikeMidTokenWrap",
            "uploadAndPasteImages",
            "/api/paste-image",
        ):
            self.assertIn(token, app_src)
        self.assertNotIn("sendPtyInput(txt", app_src)
        self.assertIn("wsPingTimer", server_src)
        self.assertIn("type: 'hydrated'", server_src)
        self.assertIn("/api/config", server_src)
        self.assertIn("/api/paste-image", server_src)
        self.assertIn("detectImageFormat", server_src)
        self.assertIn("api\\/addons\\/", server_src)
        self.assertIn("JetBrainsMono-Regular.woff2", server_src)
        self.assertIn("noto-symbols-braille.woff2", server_src)
        self.assertIn("addon-canvas.js", server_src)
        self.assertIn("addon-unicode11.js", server_src)
        self.assertIn("nerd-symbols.woff2", server_src)
        self.assertIn("JetBrains Mono", app_src)
        self.assertIn("customGlyphs: true", app_src)
        self.assertIn("attachCanvasRenderer", app_src)
        self.assertIn("term-stage-loader", app_src)
        self.assertIn("syncStageLoader", app_src)
        self.assertIn("fontsReadyPromise", app_src)
        self.assertIn("setDesktopSidebar", app_src)
        self.assertIn("setDesktopSysop", app_src)
        self.assertIn("isTuiTerminal", server_src)
        self.assertIn("type: 'resized', seq: doneSeq", server_src)
        self.assertIn("resolveGitRepoInfo", server_src)
        self.assertIn("discoverProjects", server_src)
        self.assertIn("/api/projects", server_src)
        self.assertIn("purgePinsForWorktree", server_src)
        self.assertIn("closeTerminalCleanly", server_src)
        self.assertIn("terminalRepoGroupInfo", app_src)
        self.assertIn("openRepoWorktreesPopover", app_src)
        self.assertIn("buildSysopMergeAllGoal", app_src)
        self.assertIn("Ask Sysop to merge all", app_src)
        self.assertIn("repo-group-head", app_src)
        self.assertIn("showProjectPicker", app_src)
        self.assertIn("proj-list", app_src)

    def test_attach_interactive_launches_cockpit_and_respects_raw_override(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-cockpit-sh.")
        self.addCleanup(shutil.rmtree, tmp, True)
        home = os.path.join(tmp, "home")
        run_dir = os.path.join(tmp, "run")
        os.makedirs(home)
        os.makedirs(run_dir)
        with open(os.path.join(run_dir, "ready"), "w", encoding="utf-8") as f:
            f.write("ok\n")
        state_file = os.path.join(tmp, "hc-state.json")
        log_file = os.path.join(tmp, "hc.log")
        hc_bin = os.path.join(tmp, "hc")
        make_exec(hc_bin, FAKE_HC_PY)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"down": False, "terminals": [{"address": "t1", "name": "sysop", "state": "live", "labels": {"swarmbox.role": "sysop"}}], "screens": {}}, f)
        cockpit_log = os.path.join(tmp, "cockpit.log")
        fake_cockpit = os.path.join(tmp, "fake-cockpit")
        make_exec(fake_cockpit, '#!/bin/sh\necho COCKPIT_RAN >> "%s"\n' % cockpit_log)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": home,
            "SWARMBOX_MUX": "herdr",
            "SWARMBOX_TEST_HC_BIN": hc_bin,
            "SWARMBOX_TEST_HERDR_COCKPIT": fake_cockpit,
            "SWARMBOX_TEST_LIB": os.path.join(ROOT, "container", "scripts"),
            "SWARMBOX_TEST_RUN_DIR": run_dir,
            "SWARMBOX_TEST_READY_TIMEOUT": "2",
            "FAKE_HC_STATE": state_file,
            "FAKE_HC_LOG": log_file,
        }
        master, slave = pty.openpty()
        try:
            p = subprocess.Popen(["bash", ATTACH_PATH], stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=env, text=True)
            os.close(slave)
            slave = -1
            _, err = p.communicate(timeout=10)
            self.assertEqual(p.returncode, 0, err)
        finally:
            if slave >= 0:
                os.close(slave)
            os.close(master)
        with open(cockpit_log, encoding="utf-8") as f:
            self.assertIn("COCKPIT_RAN", f.read())
        # Initial shell tab was created because the only live terminal had swarmbox.role=sysop
        with open(state_file, encoding="utf-8") as f:
            st = json.load(f)
        self.assertEqual(len(st["terminals"]), 2)
        self.assertEqual(st["terminals"][1]["name"], "shell")


class HerdrSysopAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-sysop-agent.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        self.state_dir = os.path.join(self.tmp, "state")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.pth = sysop_paths.Paths({"SB_RUN_DIR": self.run_dir, "SB_STATE_DIR": self.state_dir})
        self.pth.make()

    def test_osc_status_matches_herdr_core_colon_syntax(self):
        self.assertEqual(sysop_agent.osc_status("idle"), "\x1b]7501;state=idle\x07")
        self.assertEqual(sysop_agent.osc_status("working"), "\x1b]7501;state=working\x07")
        self.assertEqual(sysop_agent.osc_status("queued"), "\x1b]7501;state=working\x07")
        self.assertEqual(sysop_agent.osc_status("allow?"), "\x1b]7501;state=blocked:kind=permission\x07")
        self.assertEqual(sysop_agent.osc_status("sending"), "\x1b]7501;state=blocked:kind=permission\x07")
        self.assertEqual(sysop_agent.osc_status("done"), "\x1b]7501;state=done\x07")
        self.assertEqual(sysop_agent.osc_status("failed"), "\x1b]7501;state=error\x07")
        # Base64 msg payload per herdr-core OSC 7501 spec
        self.assertEqual(sysop_agent.osc_status("allow?", "Deploy?"), "\x1b]7501;state=blocked:kind=permission:msg=RGVwbG95Pw==\x07")

    def test_seed_template_once_preserves_user_edits(self):
        env = {"HOME": self.home}
        tpl = sysop_agent.seed_template(env)
        self.assertTrue(os.path.isfile(tpl))
        with open(tpl, encoding="utf-8") as f:
            txt = f.read()
        self.assertIn('command: ["swarmbox-sysop", "agent"]', txt)
        with open(tpl, "w", encoding="utf-8") as f:
            f.write("# custom user template\n")
        sysop_agent.seed_template(env)
        with open(tpl, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# custom user template\n")

    def test_handle_line_publishes_goal_and_answers_pending_approval(self):
        import io

        class FakeBus:
            def __init__(self):
                self.published = []

            def pub(self, topic, body, source):
                self.published.append((topic, body, source))
                return {"id": "g-123"}

        bus = FakeBus()
        buf = io.StringIO()
        ok, gid = sysop_agent.handle_line("run the unit tests", self.pth, bus, out=buf)
        self.assertTrue(ok)
        self.assertEqual(gid, "g-123")
        self.assertEqual(bus.published[0][1]["text"], "run the unit tests")
        self.assertEqual(bus.published[0][2], "agent")

        # Simulate live service (flock on pth.lock) + pending approval, then reply `y` and `n`
        import fcntl
        lock_fd = os.open(self.pth.lock, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(os.close, lock_fd)
        gdir = self.pth.goal_dir("g-123")
        os.makedirs(gdir, exist_ok=True)
        sysop_ipc.write_json(self.pth.status, {"pid": os.getpid(), "current": "g-123", "bus": "up", "queue": [], "settings": {}})
        sysop_ipc.write_json(os.path.join(gdir, "pending_action.json"), {"id": "act-1", "mode": "approve", "text": "rm -rf /tmp/x", "deadline": 9999999999.0})
        buf2 = io.StringIO()
        ok2, msg2 = sysop_agent.handle_line("y", self.pth, bus, out=buf2, wall=1000.0)
        self.assertTrue(ok2)
        self.assertEqual(msg2, "allowed")
        dec = sysop_ipc.read_json(os.path.join(gdir, "decision.json"))
        self.assertEqual(dec["decision"], "approve")
        self.assertEqual(dec["by"], "agent")

        buf3 = io.StringIO()
        ok3, msg3 = sysop_agent.handle_line("n", self.pth, bus, out=buf3, wall=1000.0)
        self.assertTrue(ok3)
        self.assertEqual(msg3, "refused")
        dec2 = sysop_ipc.read_json(os.path.join(gdir, "decision.json"))
        self.assertEqual(dec2["decision"], "deny")
        self.assertEqual(dec2["by"], "agent")

    def test_herdr_bridge_publishes_once_and_does_not_duplicate(self):
        state_file = os.path.join(self.tmp, "hc-state.json")
        log_file = os.path.join(self.tmp, "hc.log")
        hc_bin = os.path.join(self.tmp, "hc")
        make_exec(hc_bin, FAKE_HC_PY)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"down": False, "terminals": [], "screens": {}}, f)
        env = dict(os.environ, HOME=self.home, FAKE_HC_STATE=state_file, FAKE_HC_LOG=log_file)
        bridge = sysop_agent.HerdrBridge(self.pth, hc_bin=hc_bin, sysop_bin="/usr/local/bin/swarmbox-sysop", env=env)
        self.assertTrue(bridge.ensure_once())
        self.assertTrue(bridge.ensure_once())
        with open(state_file, encoding="utf-8") as f:
            st = json.load(f)
        self.assertEqual(len(st["terminals"]), 1)
        self.assertEqual(st["terminals"][0]["name"], "sysop")
        self.assertEqual(st["terminals"][0]["labels"].get("swarmbox.role"), "sysop")
        self.assertIn("cockpit", sysop_brain.SOURCE_NOTES)
        self.assertIn("agent", sysop_brain.SOURCE_NOTES)


class PtyViewportOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-pty-owner.")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_idle_reconnecting_client_cannot_hijack_active_viewport_resolution(self):
        web_dir = os.path.join(self.tmp, "web")
        ws_dir = os.path.join(web_dir, "node_modules", "ws")
        os.makedirs(ws_dir, exist_ok=True)
        stage_herdr_web(web_dir)
        with open(os.path.join(ws_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws_dir, "index.js"), "w", encoding="utf-8") as f:
            f.write(
                "import { EventEmitter } from 'node:events';\n"
                "export class WebSocketServer extends EventEmitter {\n"
                "  constructor() { super(); this.clients = new Set(); }\n"
                "  handleUpgrade(_req, _sock, _head, cb) { cb(new FakeWs()); }\n"
                "  close() {}\n"
                "}\n"
                "export class FakeWs extends EventEmitter {\n"
                "  constructor() { super(); this.readyState = 1; this.sent = []; }\n"
                "  send(d) { this.sent.push(d); }\n"
                "  ping() {}\n"
                "  close() { this.readyState = 3; this.emit('close'); }\n"
                "}\n"
            )
        harness = os.path.join(web_dir, "run.mjs")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(
                "import assert from 'node:assert/strict';\n"
                "import { EventEmitter } from 'node:events';\n"
                "import { FakeWs } from './node_modules/ws/index.js';\n"
                "const _realSetTimeout = globalThis.setTimeout;\n"
                "globalThis.setTimeout = (fn, ms, ...args) => _realSetTimeout(fn, ms > 5 ? Math.max(2, Math.round(ms / 30)) : ms, ...args);\n"
                "const { createGateway, createSyncOutputCoalescer } = await import('./server.mjs');\n"
                "\n"
                "class FakeHc extends EventEmitter {\n"
                "  constructor() {\n"
                "    super();\n"
                "    this.terminals = new Map([\n"
                "      ['t1', { address: 't1', name: 'claude', state: 'live', cols: 100, rows: 30, created_ms: 1 }],\n"
                "      ['t2', { address: 't2', name: 'shell', state: 'live', cols: 100, rows: 30, created_ms: 2 }],\n"
                "    ]);\n"
                "    this.attaches = [];\n"
                "    this.resizes = [];\n"
                "    this.ops = [];\n"
                "    this.handlersBySid = new Map();\n"
                "  }\n"
                "  async start() {}\n"
                "  close() {}\n"
                "  listSnapshot() { return Array.from(this.terminals.values()); }\n"
                "  async attach(termId, cols, rows, handlers) {\n"
                "    this.attaches.push({ termId, cols, rows });\n"
                "    const sid = this.attaches.length;\n"
                "    this.handlersBySid.set(sid, handlers || {});\n"
                "    const t = this.terminals.get(termId);\n"
                "    if (t) { t.cols = cols; t.rows = rows; }\n"
                "    return {\n"
                "      sid,\n"
                "      write() {},\n"
                "      resize: (c, r) => {\n"
                "        this.resizes.push({ termId, cols: c, rows: r });\n"
                "        this.ops.push(['resize', sid, c, r]);\n"
                "        if (t) { t.cols = c; t.rows = r; }\n"
                "      },\n"
                "      focus: (on) => { this.ops.push(['focus', sid, Boolean(on)]); },\n"
                "      close() {},\n"
                "    };\n"
                "  }\n"
                "}\n"
                "\n"
                "const hc = new FakeHc();\n"
                "const { wss, shutdown } = createGateway({ hc });\n"
                "async function openClient(query, termId = 't1') {\n"
                "  const ws = new FakeWs();\n"
                "  const url = new URL(`http://127.0.0.1:7681/ws/pty/${termId}?${query}`);\n"
                "  wss.emit('connection', ws, {}, url);\n"
                "  await new Promise((r) => _realSetTimeout(r, 2));\n"
                "  return ws;\n"
                "}\n"
                "\n"
                "// 1. Home ultrawide opens t1 at 220x60\n"
                "const home1 = await openClient('cols=220&rows=60');\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't1', cols: 220, rows: 60 });\n"
                "\n"
                "// 2. Work Mac opens t1 at 120x35 -> becomes owner\n"
                "const mac = await openClient('cols=120&rows=35');\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "\n"
                "// 3. Home ultrawide drops & auto-reconnects (reconnect=1) -> attaches at Mac's 120x35, no hijack\n"
                "home1.close();\n"
                "const home2 = await openClient('cols=220&rows=60&reconnect=1');\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "\n"
                "// 4. Spurious resize, passive focus, and automated DA1 reply from Home do NOT resize PTY\n"
                "home2.emit('message', Buffer.from(JSON.stringify({ type: 'resize', cols: 220, rows: 60, seq: 7 })), false);\n"
                "assert.equal(hc.resizes.length, 0);\n"
                "assert.ok(home2.sent.some((m) => typeof m === 'string' && JSON.parse(m).type === 'resized' && JSON.parse(m).seq === 7));\n"
                "home2.emit('message', Buffer.from(JSON.stringify({ type: 'focus', focused: true })), false);\n"
                "home2.emit('message', Buffer.from(JSON.stringify({ type: 'input', data: '\\x1b[?1;2c' })), false);\n"
                "assert.equal(hc.resizes.length, 0);\n"
                "\n"
                "// 5. Explicit user claim on Home reclaims 220x60\n"
                "home2.emit('message', Buffer.from(JSON.stringify({ type: 'focus', focused: true, claim: true, cols: 220, rows: 60 })), false);\n"
                "assert.deepEqual(hc.resizes.at(-1), { termId: 't1', cols: 220, rows: 60 });\n"
                "\n"
                "// 6. Real keystroke on Mac reclaims 120x35\n"
                "mac.emit('message', Buffer.from(JSON.stringify({ type: 'input', data: 'a' })), false);\n"
                "assert.deepEqual(hc.resizes.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "\n"
                "const ctl = (ws) => ws.sent.filter((m) => typeof m === 'string').map((m) => JSON.parse(m));\n"
                "const resizingCount = (ws) => ctl(ws).filter((m) => m.type === 'resizing').length;\n"
                "// A window still hydrating is already behind its loader and buffers output: masks apply once it is live\n"
                "const hydrated = async (ws) => { for (let i = 0; i < 300 && !ctl(ws).some((m) => m.type === 'hydrated'); i++) await new Promise((r) => _realSetTimeout(r, 2)); };\n"
                "await hydrated(mac); await hydrated(home2);\n"
                "\n"
                "// 6b. A resize asked by one window redraws the agent for every window: the others are masked too\n"
                "const macMasks = resizingCount(mac);\n"
                "home2.emit('message', Buffer.from(JSON.stringify({ type: 'focus', focused: true, claim: true, cols: 220, rows: 60 })), false);\n"
                "assert.deepEqual(hc.resizes.at(-1), { termId: 't1', cols: 220, rows: 60 });\n"
                "assert.equal(resizingCount(mac), macMasks + 1, 'the window that did not ask must get a resizing mask');\n"
                "mac.emit('message', Buffer.from(JSON.stringify({ type: 'input', data: 'b' })), false);\n"
                "assert.deepEqual(hc.resizes.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "\n"
                "// 6c. A passive attach joins at the owner's exact size even when hc's cached size is stale\n"
                "hc.terminals.get('t1').cols = 200; hc.terminals.get('t1').rows = 50;\n"
                "const bg = await openClient('cols=200&rows=50&focused=0');\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "\n"
                "// 6d. An attach that changes the PTY size masks the windows already attached\n"
                "await hydrated(bg);\n"
                "const masksBefore = resizingCount(mac);\n"
                "const phone = await openClient('cols=60&rows=40');\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't1', cols: 60, rows: 40 });\n"
                "assert.equal(resizingCount(mac), masksBefore + 1);\n"
                "\n"
                "// 6e. herdr-core re-applies a stream's last size on focus(true): a claim refreshes it first, even when\n"
                "//     the PTY already has the wanted size (set by another stream), so focus never restores a stale size\n"
                "await hydrated(phone);\n"
                "mac.emit('message', Buffer.from(JSON.stringify({ type: 'input', data: 'c' })), false);\n"
                "assert.deepEqual(hc.resizes.at(-1), { termId: 't1', cols: 120, rows: 35 });\n"
                "phone.emit('message', Buffer.from(JSON.stringify({ type: 'focus', focused: false })), false);\n"
                "const phoneSid = hc.attaches.length;\n"
                "hc.ops.length = 0;\n"
                "phone.emit('message', Buffer.from(JSON.stringify({ type: 'focus', focused: true, claim: true, cols: 120, rows: 35 })), false);\n"
                "const iResize = hc.ops.findIndex((o) => o[0] === 'resize' && o[1] === phoneSid && o[2] === 120 && o[3] === 35);\n"
                "const iFocus = hc.ops.findIndex((o) => o[0] === 'focus' && o[1] === phoneSid && o[2] === true);\n"
                "assert.ok(iResize !== -1 && iFocus !== -1 && iResize < iFocus, `stream size must be refreshed before focus: ${JSON.stringify(hc.ops)}`);\n"
                "\n"
                "// 7. DEC 2026 synchronized output coalescer keeps split frames atomic\n"
                "const emitted = [];\n"
                "const co = createSyncOutputCoalescer((b) => emitted.push(b.toString('utf8')), { maxMs: 50 });\n"
                "co.push(Buffer.from('plain'));\n"
                "assert.deepEqual(emitted, ['plain']);\n"
                "co.push(Buffer.from('\\x1b[?2026h\\x1b[2Jpart1'));\n"
                "assert.equal(emitted.length, 1);\n"
                "co.push(Buffer.from('part2'));\n"
                "assert.equal(emitted.length, 1);\n"
                "co.push(Buffer.from('part3\\x1b[?2026l'));\n"
                "assert.equal(emitted.length, 2);\n"
                "assert.equal(emitted[1], '\\x1b[?2026h\\x1b[2Jpart1part2part3\\x1b[?2026l');\n"
                "\n"
                "// 8. Global last-active-channel ownership (clientId): passive follow & reconnect respect the active channel\n"
                "const deskEv = new FakeWs();\n"
                "wss.emit('connection', deskEv, {}, new URL('http://127.0.0.1:7681/ws/events?clientId=desk'));\n"
                "const phoneEv = new FakeWs();\n"
                "wss.emit('connection', phoneEv, {}, new URL('http://127.0.0.1:7681/ws/events?clientId=phone'));\n"
                "const deskT2 = await openClient('cols=140&rows=42&clientId=desk', 't2');\n"
                "await hydrated(deskT2);\n"
                "assert.equal(ctl(deskT2).find((m) => m.type === 'hydrated').owner, true);\n"
                "// Phone actively attaches to t2 at 51x30 -> becomes lastActiveClientId; desktop gets owner:false\n"
                "const phoneT2 = await openClient('cols=51&rows=30&clientId=phone', 't2');\n"
                "await hydrated(phoneT2);\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't2', cols: 51, rows: 30 });\n"
                "assert.equal(ctl(phoneT2).find((m) => m.type === 'hydrated').owner, true);\n"
                "assert.equal(ctl(deskT2).filter((m) => m.type === 'resizing').at(-1).owner, false);\n"
                "// Phone drops & reconnects (reconnect=1) while still lastActiveClientId -> keeps 51x30 and owner:true\n"
                "phoneT2.close();\n"
                "const phoneT2Re = await openClient('cols=51&rows=30&reconnect=1&clientId=phone', 't2');\n"
                "await hydrated(phoneT2Re);\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't2', cols: 51, rows: 30 });\n"
                "assert.equal(ctl(phoneT2Re).find((m) => m.type === 'hydrated').owner, true);\n"
                "// Desktop drops & reconnects (reconnect=1) while phone is active -> stays passive at 51x30, owner:false\n"
                "deskT2.close();\n"
                "const deskT2Re = await openClient('cols=140&rows=42&reconnect=1&clientId=desk', 't2');\n"
                "await hydrated(deskT2Re);\n"
                "assert.deepEqual(hc.attaches.at(-1), { termId: 't2', cols: 51, rows: 30 });\n"
                "assert.equal(ctl(deskT2Re).find((m) => m.type === 'hydrated').owner, false);\n"
                "// Same-size resize from owner returns resized immediately without masking peers\n"
                "const deskMasksBefore = resizingCount(deskT2Re);\n"
                "phoneT2Re.emit('message', Buffer.from(JSON.stringify({ type: 'resize', cols: 51, rows: 30, seq: 99 })), false);\n"
                "assert.equal(resizingCount(deskT2Re), deskMasksBefore);\n"
                "assert.ok(ctl(phoneT2Re).some((m) => m.type === 'resized' && m.seq === 99 && m.owner === true));\n"
                "\n"
                "// 9. Late-redraw detector catches at most ONE late clear-screen pass per real resize (no loop)\n"
                "const tuiPhone = await openClient('cols=51&rows=30&clientId=phone', 't1');\n"
                "const tuiSid = hc.attaches.length;\n"
                "const hTui = hc.handlersBySid.get(tuiSid);\n"
                "// Alternate screen signal marks t1 as a TUI\n"
                "hTui.onData(Buffer.from('\\x1b[?1049hinitial'));\n"
                "await hydrated(tuiPhone);\n"
                "tuiPhone.emit('message', Buffer.from(JSON.stringify({ type: 'resize', cols: 52, rows: 30, seq: 101 })), false);\n"
                "const waitFor = async (pred, ms = 2000) => {\n"
                "  const t0 = Date.now();\n"
                "  while (Date.now() - t0 < ms) { if (pred()) return true; await new Promise((r) => _realSetTimeout(r, 2)); }\n"
                "  return false;\n"
                "};\n"
                "assert.ok(await waitFor(() => ctl(tuiPhone).some((m) => m.type === 'resized' && m.seq === 101)));\n"
                "const masksAfterResize = resizingCount(tuiPhone);\n"
                "// First late \\x1b[2J within late_redraw_ms triggers ONE catch\n"
                "hTui.onData(Buffer.from('\\x1b[2Jfirst-late-pass'));\n"
                "assert.equal(resizingCount(tuiPhone), masksAfterResize + 1);\n"
                "const resizedBeforeLate = ctl(tuiPhone).filter((m) => m.type === 'resized').length;\n"
                "assert.ok(await waitFor(() => ctl(tuiPhone).filter((m) => m.type === 'resized').length > resizedBeforeLate, 2000));\n"
                "// Second \\x1b[2J right after must NOT trigger another resize mask loop\n"
                "hTui.onData(Buffer.from('\\x1b[2Jsecond-pass-must-not-loop'));\n"
                "assert.equal(resizingCount(tuiPhone), masksAfterResize + 1, 'late-redraw detector must never loop');\n"
                "\n"
                "shutdown();\n"
                "console.log('PTY_VIEWPORT_OWNERSHIP_OK');\n"
            )
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons"),   # the staged agents.mjs is not next to them
            "HOME": self.tmp,
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
        }
        p = subprocess.run(["node", harness], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, "stdout:\n%s\nstderr:\n%s" % (p.stdout, p.stderr))
        self.assertIn("PTY_VIEWPORT_OWNERSHIP_OK", p.stdout)


class WorktreeOrchestratorApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-wt-api.")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_worktree_orchestrator_endpoints_and_hybrid_verify_push(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        web_dir = os.path.join(self.tmp, "web")
        ws_dir = os.path.join(web_dir, "node_modules", "ws")
        os.makedirs(ws_dir, exist_ok=True)
        stage_herdr_web(web_dir)
        with open(os.path.join(ws_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws_dir, "index.js"), "w", encoding="utf-8") as f:
            f.write(
                "import { EventEmitter } from 'node:events';\n"
                "export class WebSocketServer extends EventEmitter {\n"
                "  constructor() { super(); this.clients = new Set(); }\n"
                "  handleUpgrade(_req, _sock, _head, cb) { cb(new FakeWs()); }\n"
                "  close() {}\n"
                "}\n"
                "export class FakeWs extends EventEmitter {\n"
                "  constructor() { super(); this.readyState = 1; this.sent = []; }\n"
                "  send(d) { this.sent.push(d); }\n"
                "  ping() {}\n"
                "  close() { this.readyState = 3; this.emit('close'); }\n"
                "}\n"
            )
        harness = os.path.join(web_dir, "run_wt_api.mjs")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(r"""
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { FakeWs } from './node_modules/ws/index.js';
const _realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms, ...args) => _realSetTimeout(fn, ms > 5 ? Math.max(2, Math.round(ms / 30)) : ms, ...args);
const { createGateway } = await import('./server.mjs');

class FakeHc extends EventEmitter {
  constructor() {
    super();
    this.terminals = new Map();
    this.calls = [];
  }
  async start() {}
  close() {}
  listSnapshot() { return Array.from(this.terminals.values()); }
  async call(method, params) {
    this.calls.push({ method, params });
    if (method === 'terminal.kill') this.terminals.delete(params.terminal);
    return { ok: true };
  }
  // A button's prompt is typed through an attach stream: record each write as a 'typed' call.
  async attach(terminal, cols, rows) {
    this.calls.push({ method: 'attach', params: { terminal, cols, rows } });
    return {
      write: (buf) => this.calls.push({ method: 'typed', params: { terminal, text: Buffer.from(buf).toString('utf8') } }),
      close: () => this.calls.push({ method: 'attach.close', params: { terminal } }),
    };
  }
}

const wtCalls = [];
let mockRepoStatus = {
  ok: true,
  repo_root: '/fake/repo',
  repo_name: 'repo',
  branch: 'main',
  head: 'abc1234',
  dirty: false,
  uncommitted_count: 0,
  upstream: 'origin/main',
  ahead_origin: 1,
  behind_origin: 0,
  verify_cmd: 'npm test',
  can_undo_merge: true,
  last_merge: { branch: 'sb/feat-a', pre_sha: '111', post_sha: '222' },
};
let mockSyncConflict = false;
let mockVerifyOk = true;
let mockMergeFailPath = null;
let mockList = [
  { path: '/fake/wt-1', repo_root: '/fake/repo', branch: 'sb/feat-1', dirty: false, ahead: 2, can_merge: true },
  { path: '/fake/wt-dirty', repo_root: '/fake/repo', branch: 'sb/dirty', dirty: true, ahead: 1, can_merge: true },
  { path: '/fake/wt-zero', repo_root: '/fake/repo', branch: 'sb/zero', dirty: false, ahead: 0, can_merge: true },
  { path: '/fake/wt-2', repo_root: '/fake/repo', branch: 'sb/feat-2', dirty: false, ahead: 1, can_merge: true },
];

async function fakeRunWorktreeCmd(args, timeoutMs) {
  wtCalls.push({ args, timeoutMs });
  const sub = args[0];
  if (sub === 'repo-status') {
    return { ...mockRepoStatus, repo_root: args[1] };
  }
  if (sub === 'diff') {
    const fIdx = args.indexOf('--file');
    const file = fIdx >= 0 ? args[fIdx + 1] : null;
    return { ok: true, branch: 'sb/feat-1', base: 'main', file, diff: '+hello\n', truncated: false };
  }
  if (sub === 'sync') {
    if (mockSyncConflict) {
      const err = new Error('merge conflict during sync');
      err.code = 'sync_conflict';
      err.data = { conflict_files: ['src/app.js'] };
      throw err;
    }
    return { ok: true, branch: 'sb/feat-1', base: 'main', mode: args.includes('--rebase') ? 'rebase' : 'merge', ahead: 1, behind: 0, repo_root: '/fake/repo' };
  }
  if (sub === 'merge') {
    const wtPath = args[1];
    if (mockMergeFailPath && wtPath === mockMergeFailPath) {
      const err = new Error('conflict on merge');
      err.code = 'merge_conflict';
      err.data = { conflict_files: ['README.md'] };
      throw err;
    }
    return {
      ok: true,
      repo_root: '/fake/repo',
      branch: wtPath === '/fake/wt-2' ? 'sb/feat-2' : 'sb/feat-1',
      pre_sha: '111',
      post_sha: '222',
      commits_list: ['feat: add widget'],
      files: ['src/widget.js'],
    };
  }
  if (sub === 'list') {
    return mockList;
  }
  if (sub === 'verify') {
    if (!mockVerifyOk) {
      return { ok: false, exit_code: 2, cmd: 'npm test', duration_ms: 12, output: 'FAIL test_a' };
    }
    return { ok: true, exit_code: 0, cmd: 'npm test', duration_ms: 10, output: 'PASS all' };
  }
  if (sub === 'push') {
    return { ok: true, repo_root: args[1], branch: 'main', upstream: 'origin/main', head: '222' };
  }
  if (sub === 'undo-merge') {
    return { ok: true, repo_root: args[1], restored_sha: '111', undone_branch: 'sb/feat-1' };
  }
  return { ok: true };
}

const hc = new FakeHc();
hc.terminals.set('t-shell', {
  address: 't-shell', name: 'shell', agent: 'bash', cwd: '/fake/repo', state: 'live',
  labels: { 'swarmbox.agent': 'shell' },
});
hc.terminals.set('t-wt', {
  address: 't-wt', name: 'claude-wt', agent: 'claude', cwd: '/fake/wt-1', state: 'live',
  labels: { 'swarmbox.agent': 'claude', 'swarmbox.worktree': '/fake/wt-1', 'swarmbox.repo': '/fake/repo' },
});
hc.terminals.set('t-main', {
  address: 't-main', name: 'main-claude', agent: 'claude', cwd: '/fake/repo/sub', state: 'live',
  labels: { 'swarmbox.agent': 'claude', 'swarmbox.title': 'Main Agent' },
});

const { server, wss, shutdown } = createGateway({ hc, runWorktreeCmd: fakeRunWorktreeCmd });
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const { port } = server.address();
const base = `http://127.0.0.1:${port}`;

// Connect a fake /ws/events client to verify reactive snapshot broadcasts
const evWs = new FakeWs();
wss.emit('connection', evWs, {}, new URL(`${base}/ws/events`));

async function reqJson(method, p, body) {
  const res = await fetch(`${base}${p}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return { status: res.status, data: await res.json() };
}

// 1. GET /api/worktrees/repo-status
{
  const r = await reqJson('GET', '/api/worktrees/repo-status?repo=/fake/repo');
  assert.equal(r.status, 200);
  assert.equal(r.data.branch, 'main');
  assert.deepEqual(r.data.main_agent, { address: 't-main', title: 'Main Agent' });
  const lastSnap = JSON.parse(evWs.sent.at(-1));
  assert.ok(lastSnap.repo_statuses['/fake/repo']);
  assert.equal(lastSnap.repo_statuses['/fake/repo'].main_agent.address, 't-main');
}

// 2. GET /api/worktrees/diff
{
  const r1 = await reqJson('GET', '/api/worktrees/diff?path=/fake/wt-1');
  assert.equal(r1.status, 200);
  assert.equal(r1.data.diff, '+hello\n');
  assert.deepEqual(wtCalls.at(-1).args, ['diff', '/fake/wt-1']);

  const r2 = await reqJson('GET', '/api/worktrees/diff?path=/fake/wt-1&file=src/a.js');
  assert.equal(r2.status, 200);
  assert.equal(r2.data.file, 'src/a.js');
  assert.deepEqual(wtCalls.at(-1).args, ['diff', '/fake/wt-1', '--file', 'src/a.js']);
}

// 3. POST /api/worktrees/sync (success + rebase + 409 conflict)
{
  const r1 = await reqJson('POST', '/api/worktrees/sync', { terminal: 't-wt', rebase: true });
  assert.equal(r1.status, 200);
  assert.equal(r1.data.mode, 'rebase');

  mockSyncConflict = true;
  const r2 = await reqJson('POST', '/api/worktrees/sync', { path: '/fake/wt-1' });
  assert.equal(r2.status, 409);
  assert.equal(r2.data.error, 'sync_conflict');
  assert.deepEqual(r2.data.conflict_files, ['src/app.js']);
  mockSyncConflict = false;
}

// 4. POST /api/worktrees/merge with verify_and_push -> hands off to live main agent
{
  hc.calls.length = 0;
  const r = await reqJson('POST', '/api/worktrees/merge', {
    path: '/fake/wt-1', terminal: 't-wt', verify_and_push: true,
  });
  assert.equal(r.status, 200);
  assert.equal(r.data.handoff.mode, 'agent');
  assert.equal(r.data.handoff.terminal, 't-main');
  assert.equal(hc.calls.some((c) => c.method === 'terminal.send'), false, 'a button must not wait in terminal.send');
  const typed = hc.calls.filter((c) => c.method === 'typed');
  assert.equal(typed.length, 2, 'the text, then the Enter as its own write');
  const sendCall = typed[0];
  assert.equal(sendCall.params.terminal, 't-main');
  assert.equal(typed[1].params.text, '\r');
  assert.match(sendCall.params.text, /sb\/feat-1/);
  assert.match(sendCall.params.text, /npm test/);
  assert.match(sendCall.params.text, /push main/i);
}

// 5. POST /api/worktrees/merge with verify_and_push & NO main agent -> backend_verify -> pushed
{
  hc.terminals.delete('t-main');
  wtCalls.length = 0;
  const r = await reqJson('POST', '/api/worktrees/merge', {
    path: '/fake/wt-1', verify_and_push: true,
  });
  assert.equal(r.status, 200);
  assert.equal(r.data.handoff.mode, 'backend_verify');
  assert.equal(r.data.handoff.state, 'running');
  // Wait for async verify+push job to settle
  await new Promise((res) => _realSetTimeout(res, 15));
  const verifyCall = wtCalls.find((c) => c.args[0] === 'verify');
  assert.ok(verifyCall);
  assert.equal(verifyCall.timeoutMs, 190000);
  assert.ok(wtCalls.some((c) => c.args[0] === 'push'));
  const st = await reqJson('GET', '/api/worktrees/repo-status?repo=/fake/repo');
  assert.equal(st.data.verify_job.state, 'pushed');
}

// 6. Backend verify failure -> state='failed', no push, then undo_merge clears failed job
{
  mockVerifyOk = false;
  wtCalls.length = 0;
  const r = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'verify_and_push',
  });
  assert.equal(r.status, 200);
  assert.equal(r.data.handoff.mode, 'backend_verify');
  await new Promise((res) => _realSetTimeout(res, 15));
  assert.equal(wtCalls.some((c) => c.args[0] === 'push'), false);
  const st1 = await reqJson('GET', '/api/worktrees/repo-status?repo=/fake/repo');
  assert.equal(st1.data.verify_job.state, 'failed');
  assert.equal(st1.data.verify_job.exit_code, 2);

  const undo = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'undo_merge',
  });
  assert.equal(undo.status, 200);
  assert.equal(undo.data.restored_sha, '111');
  const st2 = await reqJson('GET', '/api/worktrees/repo-status?repo=/fake/repo');
  assert.equal(st2.data.verify_job, null);
  mockVerifyOk = true;
}

// 7. Manual push fallback when no main agent and no verify_cmd
{
  mockRepoStatus.verify_cmd = '';
  await reqJson('GET', '/api/worktrees/repo-status?repo=/fake/repo');
  const r = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'verify_and_push',
  });
  assert.equal(r.status, 200);
  assert.equal(r.data.handoff.mode, 'manual_push');
  mockRepoStatus.verify_cmd = 'npm test';
}

// 8. POST /api/worktrees/main/action: commit (409 without main agent, 200 with main agent) & push
{
  const r409 = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'commit',
  });
  assert.equal(r409.status, 409);
  assert.equal(r409.data.error, 'no_main_agent');

  hc.terminals.set('t-main', {
    address: 't-main', name: 'main-claude', agent: 'claude', cwd: '/fake/repo', state: 'live',
    labels: { 'swarmbox.agent': 'claude', 'swarmbox.title': 'Main Agent' },
  });
  hc.calls.length = 0;
  const r200 = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'commit',
  });
  assert.equal(r200.status, 200);
  assert.equal(r200.data.terminal, 't-main');
  assert.ok(hc.calls.some((c) => c.method === 'typed' && c.params.terminal === 't-main' && /clean git commit/.test(c.params.text)));

  const rPush = await reqJson('POST', '/api/worktrees/main/action', {
    repo: '/fake/repo', action: 'push',
  });
  assert.equal(rPush.status, 200);
  assert.equal(rPush.data.head, '222');
}

// 9. POST /api/worktrees/merge-all: filters, stops on conflict, sends ONE handoff for merged branches
{
  hc.calls.length = 0;
  mockMergeFailPath = '/fake/wt-2';
  const r = await reqJson('POST', '/api/worktrees/merge-all', {
    repo: '/fake/repo', clean: true, verify_and_push: true,
  });
  assert.equal(r.status, 200);
  assert.equal(r.data.ok, true);
  assert.equal(r.data.merged.length, 1);
  assert.equal(r.data.merged[0].branch, 'sb/feat-1');
  assert.equal(r.data.failed.length, 1);
  assert.equal(r.data.failed[0].branch, 'sb/feat-2');
  assert.equal(r.data.failed[0].error, 'merge_conflict');
  assert.equal(r.data.handoff.mode, 'agent');
  // t-wt should have been closed because clean: true
  assert.equal(hc.terminals.has('t-wt'), false);
  const sends = hc.calls.filter((c) => c.method === 'typed' && c.params.text !== '\r');
  assert.equal(sends.length, 1);
  mockMergeFailPath = null;
}

shutdown();
console.log('WORKTREE_ORCHESTRATOR_API_OK');
""")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons"),   # the staged agents.mjs is not next to them
            "HOME": self.tmp,
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
        }
        p = subprocess.run(["node", harness], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, "stdout:\n%s\nstderr:\n%s" % (p.stdout, p.stderr))
        self.assertIn("WORKTREE_ORCHESTRATOR_API_OK", p.stdout)


class HerdrSysopUiActionTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-ui-action.")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_routes_system_sysop_goal_ui_action_contract(self):
        run_dir = os.path.join(self.tmp, "run")
        state_dir = os.path.join(self.tmp, "state")
        os.makedirs(run_dir)
        os.makedirs(state_dir)
        log_file = os.path.join(self.tmp, "sysop-calls.jsonl")
        fake_sysop = os.path.join(self.tmp, "fake-sysop")
        make_exec(
            fake_sysop,
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "rec = {'argv': sys.argv[1:], 'stdin': sys.stdin.read()}\n"
            "with open(%r, 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(rec) + '\\n')\n"
            "print('g-ui-1')\n" % (log_file,),
        )
        routes_path = os.path.join(ROOT, "container", "web", "herdr", "routes-system.mjs")
        js = r"""
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import { formatSysopGoalPayload, handleSystemRoutes } from %s;

// 1. Pure payload formatting & sanitization
assert.deepEqual(formatSysopGoalPayload({ goal: 'check tabs' }), {
  goal: 'check tabs', source: 'web', text: 'check tabs',
});
assert.deepEqual(formatSysopGoalPayload({ goal: 'merge all', source: 'ui', label: 'Merge 2 worktrees · app → main', lang: 'pt-BR' }), {
  goal: 'merge all',
  source: 'ui',
  text: '[ui-action lang=pt-BR: Merge 2 worktrees · app → main]\nmerge all',
});
assert.deepEqual(formatSysopGoalPayload({ goal: 'merge all', source: 'ui', label: 'Line1\nLine2\r\n  Line3', lang: 'bad lang!' }), {
  goal: 'merge all',
  source: 'ui',
  text: '[ui-action: Line1 Line2 Line3]\nmerge all',
});
assert.equal(
  formatSysopGoalPayload({ goal: 'x', source: 'ui', label: 'a'.repeat(260) }).text.split('\n')[0].length,
  '[ui-action: ]'.length + 200,
);
assert.equal(formatSysopGoalPayload({ goal: 'x', source: 'BAD SOURCE!' }).source, 'web');

// 2. End-to-end POST /api/sysop/goal through handleSystemRoutes
const hub = { buildSnapshot: () => ({}), broadcast: () => {} };
const hc = { listSnapshot: () => [] };
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  const handled = await handleSystemRoutes(req, res, url, url.pathname, { hc, hub });
  if (!handled) { res.writeHead(404); res.end(); }
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
try {
  const post = async (payload) => {
    const r = await fetch(`http://127.0.0.1:${port}/api/sysop/goal`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return { status: r.status, data: await r.json() };
  };
  const r1 = await post({
    goal: 'Consolidate all worktrees\nStep 1...',
    source: 'ui',
    label: 'Merge 3 worktrees · swarmbox → main → Verify',
    lang: 'pt-BR',
  });
  assert.equal(r1.status, 200);
  assert.equal(r1.data.ok, true);

  const r2 = await post({ goal: 'oi sysop' });
  assert.equal(r2.status, 200);

  const calls = fs.readFileSync(%s, 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].argv, ['goal', '--source', 'ui', '--', '-']);
  assert.equal(calls[0].stdin, '[ui-action lang=pt-BR: Merge 3 worktrees · swarmbox → main → Verify]\nConsolidate all worktrees\nStep 1...\n');
  assert.deepEqual(calls[1].argv, ['goal', '--source', 'web', '--', '-']);
  assert.equal(calls[1].stdin, 'oi sysop\n');
} finally {
  server.close();
}
""" % (json.dumps(routes_path), json.dumps(log_file))
        env = dict(
            os.environ,
            HOME=self.tmp,
            SB_RUN_DIR=run_dir,
            XDG_STATE_HOME=state_dir,
            SWARMBOX_TEST_SYSOP_BIN=fake_sysop,
            SWARMBOX_IMAGE_ADDONS_DIR=os.path.join(ROOT, "container", "addons"),
        )
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_sysop_store_parses_ui_action_turn_label_and_prompt(self):
        run_dir = os.path.join(self.tmp, "run")
        state_dir = os.path.join(self.tmp, "state")
        goals = os.path.join(state_dir, "swarmbox", "sysop", "goals")
        now = time.time()

        def write_goal(gid, **st):
            d = os.path.join(goals, gid)
            os.makedirs(d)
            with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
                json.dump(dict({"id": gid, "calls": [], "say": []}, **st), f)

        write_goal(
            "g1",
            source="ui",
            text="[ui-action lang=pt-BR: Merge 2 worktrees · app → main → Verify]\nConsolidate ALL worktrees.\nStep 1: merge.",
            state="done",
            started=now - 30,
            ended=now - 20,
            summary="Tudo mesclado.",
        )
        write_goal(
            "g2",
            source="ui",
            text="[ui-action: Merge 1 worktree · app → main]\nBody only.",
            state="done",
            started=now - 15,
            ended=now - 10,
            summary="Done.",
        )
        write_goal(
            "g3",
            source="web",
            text="Oi sysop",
            state="done",
            started=now - 5,
            ended=now - 2,
            summary="Oi!",
        )
        os.makedirs(os.path.join(run_dir, "sysop"))
        with open(os.path.join(run_dir, "sysop", "status.json"), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "current": "", "queue": []}, f)

        js = r"""
import assert from 'node:assert/strict';
import { readSysopSnapshot } from %s;
const s = readSysopSnapshot([]);
assert.deepEqual(s.turns.map((t) => t.id), ['g1', 'g2', 'g3']);
assert.equal(s.turns[0].source, 'ui');
assert.equal(s.turns[0].ui_label, 'Merge 2 worktrees · app → main → Verify');
assert.equal(s.turns[0].prompt, 'Consolidate ALL worktrees.\nStep 1: merge.');
assert.equal(s.turns[1].source, 'ui');
assert.equal(s.turns[1].ui_label, 'Merge 1 worktree · app → main');
assert.equal(s.turns[1].prompt, 'Body only.');
assert.equal(s.turns[2].source, 'web');
assert.equal(s.turns[2].ui_label, '');
assert.equal(s.turns[2].prompt, 'Oi sysop');
""" % json.dumps(HERDR_CLIENT)
        env = dict(os.environ, SB_RUN_DIR=run_dir, XDG_STATE_HOME=state_dir)
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_sysop_chat_and_worktrees_ui_action_rendering(self):
        worktrees_js = os.path.join(ROOT, "container", "web", "herdr", "public", "app", "worktrees.js")
        sysop_chat_js = os.path.join(ROOT, "container", "web", "herdr", "public", "app", "sysop-chat.js")
        js = r"""
import assert from 'node:assert/strict';

// Minimal DOM stub for browser ES modules
class FakeEl {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.className = '';
    this.dataset = {};
    this.attrs = {};
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this._text = '';
    this._html = '';
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  append(...items) {
    for (const it of items) this.children.push(typeof it === 'string' ? { nodeType: 3, data: it } : it);
  }
  addEventListener(ev, fn) { (this.listeners[ev] ||= []).push(fn); }
  click() { for (const fn of (this.listeners.click || [])) fn({}); }
  find(pred) {
    if (pred(this)) return this;
    for (const c of this.children) {
      if (c && typeof c.find === 'function') {
        const hit = c.find(pred);
        if (hit) return hit;
      }
    }
    return null;
  }
}

globalThis.window = { SWARMBOX_AGENTS: { list: [], shells: [] } };
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.document = {
  createElement: (tag) => new FakeEl(tag),
  createDocumentFragment: () => new FakeEl('#frag'),
  createTextNode: (t) => ({ nodeType: 3, data: String(t) }),
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
};

const { buildSysopMergeAllLabel } = await import(%s);
assert.equal(
  buildSysopMergeAllLabel({ repoName: 'swarmbox', targetBranch: 'main', total: 1, afterMerge: 'none' }),
  'Merge 1 worktree · swarmbox → main',
);
assert.equal(
  buildSysopMergeAllLabel({ repoName: 'swarmbox', targetBranch: 'main', total: 3, afterMerge: 'verify' }),
  'Merge 3 worktrees · swarmbox → main → Verify',
);
assert.equal(
  buildSysopMergeAllLabel({ repoName: 'swarmbox', targetBranch: 'dev', total: 2, afterMerge: 'verify_push' }),
  'Merge 2 worktrees · swarmbox → dev → Verify & Push',
);

const { renderTurn } = await import(%s);

// UI action turn renders compact command card (NOT .turn-ask) with collapsed-by-default prompt toggle
const uiEl = renderTurn({
  id: 'g-ui',
  source: 'ui',
  ui_label: 'Merge 2 worktrees · swarmbox → main → Verify',
  prompt: 'Consolidate ALL worktrees...\nLine 2',
  state: 'done',
  started: Date.now() - 5000,
  ended: Date.now(),
  running: false,
  actions: [],
  notes: [],
  reply: 'Concluído.',
});
assert.equal(uiEl.find((e) => e.className === 'turn-ask'), null);
const card = uiEl.find((e) => e.className === 'turn-ui-cmd');
assert.ok(card, 'expected .turn-ui-cmd card');
assert.equal(card.find((e) => e.className === 'turn-ui-cmd-tag').textContent, 'Action');
assert.equal(card.find((e) => e.className === 'turn-ui-cmd-label').textContent, 'Merge 2 worktrees · swarmbox → main → Verify');
const toggle = card.find((e) => e.className === 'turn-ui-cmd-toggle');
const body = card.find((e) => e.className === 'turn-ui-cmd-prompt');
assert.ok(toggle && body);
assert.equal(toggle.textContent, '▸ prompt');
assert.equal(toggle.getAttribute('aria-expanded'), 'false');
assert.equal(body.hidden, true);
assert.equal(body.textContent, 'Consolidate ALL worktrees...\nLine 2');
toggle.click();
assert.equal(toggle.textContent, '▾ prompt');
assert.equal(toggle.getAttribute('aria-expanded'), 'true');
assert.equal(body.hidden, false);

// Fallback to first line of prompt when ui_label is empty
const uiFallback = renderTurn({
  id: 'g-ui-2',
  source: 'ui',
  ui_label: '',
  prompt: 'First line fallback\nSecond line',
  state: 'done',
  started: Date.now(),
  ended: Date.now(),
  running: false,
  actions: [],
  notes: [],
  reply: '',
});
assert.equal(uiFallback.find((e) => e.className === 'turn-ui-cmd-label').textContent, 'First line fallback');
""" % (json.dumps(worktrees_js), json.dumps(sysop_chat_js))
        p = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
