"""Fast tests for the opt-in `herdr` multiplexer backend (`SWARMBOX_MUX=herdr`):

  - HerdrBackend in container/scripts/swarmbox-tabs.py (list, active, screen, redaction,
    framed `hc connect` literal UTF-8 text delivery, key mapping, native OSC 7501 `tab_state()`
    + heuristic fallback, error codes)
  - container/scripts/mux/herdr.sh (serve init + config seeding, attach interactive,
    attach command + exit code + detach, `swarmbox-web` dispatch with and without voice front)
  - Sysop integration (brain.write_mcp_config forwarding mux env, risk.py guarding hc/herdr)
  - container/config/herdr.toml (valid TOML using SwarmBox Purple Glow palette)
  - container/web/herdr/server.mjs (CLI arg parsing and Origin security check via Node)

Zero real `hc` daemon, zero network.
Run: python3 tests/fast/test_herdr_backend.py
"""
import importlib.util
import json
import os
import pty
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

TABS_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")
ATTACH_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-attach.sh")
WEB_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
HERDR_TOML = os.path.join(ROOT, "container", "config", "herdr.toml")
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
        return tabs_mod.Tabs(backend="herdr", binary=self.hc_bin, run_dir=self.run_dir, pause=0.0, verify_timeout=0.2)

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
        self.assertEqual(run[run.index("--") + 1:], ["bash", "-lc", "exec claude"])
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
            "SWARMBOX_TEST_HC_BIN": self.hc_bin,
            "SWARMBOX_TEST_HERDR_WEB": self.fake_web,
            "SWARMBOX_TEST_HERDR_CONFIG": HERDR_TOML,
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
        herdr_cfg = os.path.join(self.home, ".config", "herdr", "config.toml")
        core_cfg = os.path.join(self.home, ".config", "herdr-core", "config.toml")
        self.assertTrue(os.path.isfile(herdr_cfg))
        self.assertTrue(os.path.isfile(core_cfg))
        with open(herdr_cfg, encoding="utf-8") as f:
            self.assertIn("#a78bfa", f.read())
        with open(core_cfg, encoding="utf-8") as f:
            self.assertIn("notes = false", f.read())
        with open(self.state_file, encoding="utf-8") as f:
            st = json.load(f)
        self.assertFalse(st["down"])
        self.assertEqual(len(st["terminals"]), 1)
        self.assertEqual(st["terminals"][0]["name"], "shell")

        # User edits are preserved on subsequent runs
        with open(herdr_cfg, "w", encoding="utf-8") as f:
            f.write("# custom user theme\n")
        p2 = subprocess.run(["bash", "-c", script], env=self.env(), capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0, p2.stderr)
        with open(herdr_cfg, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# custom user theme\n")

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
    def test_herdr_toml_is_valid_and_uses_purple_glow_palette(self):
        with open(HERDR_TOML, encoding="utf-8") as f:
            cfg = tomllib.loads(f.read())
        self.assertFalse(cfg.get("onboarding", True))
        custom = cfg["theme"]["custom"]
        self.assertEqual(custom["panel_bg"], "#0c0b10")
        self.assertEqual(custom["active_row_bg"], "#27222f")
        self.assertEqual(custom["selection_bg"], "#6d28d9")
        self.assertEqual(custom["accent"], "#a78bfa")
        self.assertEqual(custom["text"], "#d4d4d8")
        self.assertEqual(custom["red"], "#ff6b78")
        self.assertEqual(custom["green"], "#4ade80")
        self.assertEqual(custom["yellow"], "#fbbf24")
        self.assertEqual(custom["blue"], "#8b5cf6")
        self.assertEqual(cfg["keys"]["prefix"], "ctrl+a")
        self.assertEqual(cfg["ui"]["status_indicators"], "dots")
        self.assertFalse(cfg["ui"]["pane_outer_borders"])
        self.assertFalse(cfg["ui"]["pane_scrollbars"])
        self.assertEqual(cfg["ui"]["accent"], "#a78bfa")

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
assert.equal(b.live_action, 'Running in t1: pytest -q');
assert.equal(s.state, 'working');
assert.equal(s.sentence, 'Running in t1: pytest -q');
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
  { address: 't6', name: 'sabrina', aliases: ['shell-4'], kind: 'claude', live: true },
  { address: 't3', name: 'winix', aliases: ['shell-3'], kind: 'agy', live: false },
];
const show = (s) => parse(s, tabs).map((x) => x.t === 'text' ? x.v : x.t === 'tab' ? '[' + x.tab.name + (x.tab.live ? '' : '*') + ']' : '<' + x.t + ':' + x.v + '>').join('');
assert.equal(show('agentes: `t2` (~/swarmbox, ativa), t3 (~/winix) e t9.'), 'agentes: [swarmbox] (~/swarmbox, ativa), [winix*] (~/winix) e [t9*].');
assert.equal(show('- `1:shell` (`t2`, ativa): em ~/swarmbox'), '- [swarmbox] (ativa): em ~/swarmbox', 'the numbered label resolves; the id after it goes');
assert.equal(show('a aba `sabrina` (t6) e shell-4'), 'a aba [sabrina] e [sabrina]', 'the herdr name is an alias of the shown name');
assert.equal(show('voltou ao shell; SwarmBox em ~/swarmbox/x.py e swarmbox.md'), 'voltou ao shell; SwarmBox em ~/swarmbox/x.py e swarmbox.md', 'a word, a product, a path, a file: never a tab');
assert.equal(show('`main`: 24 testes passaram, 2 failed, 0 failed'), '<code:main>: <ok:24 testes passaram>, <bad:2 failed>, <ok:0 failed>');
assert.equal(show('swarmbox'), '[swarmbox]');
assert.equal(show('- `9:escritorio`: fresh; and 7:gone'), '- [escritorio*]: fresh; and [gone*]', 'a numbered label of a tab this page never saw is still a chip, by its name');
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

    def test_herdr_web_cli_args_and_origin_guard(self):
        if not shutil.which("node"):
            self.skipTest("node not on PATH")
        with open(HERDR_SERVER, encoding="utf-8") as f:
            server_src = f.read()
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
        for js_path in (HERDR_CLIENT, HERDR_SERVER, HERDR_COCKPIT):
            p = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, "%s: %s" % (js_path, p.stderr))

        # Exercise hc-client.mjs pure helpers directly in Node (no external npm deps needed)
        check_js = """
import assert from 'node:assert/strict';
import { isHiddenTerminal, sanitizeTabName, uniqueTabName, THEME_ORDER, readBoxConfigSnapshot } from %r;
assert.equal(isHiddenTerminal({ labels: { 'swarmbox.role': 'sysop' } }), true);
assert.equal(isHiddenTerminal({ labels: {} }), false);
assert.equal(isHiddenTerminal({}), false);
assert.ok(!/^t\\d+$/.test(sanitizeTabName('t1', 'shell')));
assert.equal(uniqueTabName('shell', 'shell', [{ name: 'shell' }, { name: 'shell-2' }]), 'shell-3');
assert.equal(THEME_ORDER.length, 5);
const cfg = readBoxConfigSnapshot([], { SWARMBOX_MUX: 'tmux', SWARMBOX_WEB_PORT: '7699', SWARMBOX_SYSOP_AUTONOMY: 'confirm-all', SWARMBOX_VOICE_LANGUAGE: 'pt' });
assert.equal(cfg.box.MUX, undefined);
assert.equal(cfg.sysop.settings['sysop.panel'], undefined);
assert.equal(cfg.box.WEB_PORT.value, '7699');
assert.equal(cfg.box.WEB_PORT.custom, true);
assert.equal(cfg.sysop.settings['sysop.autonomy'].value, 'confirm-all');
assert.equal(cfg.voice.settings['voice.language'].value, 'pt');
assert.ok(Array.isArray(cfg.addons));
assert.ok(Array.isArray(cfg.mcp));
""" % (HERDR_CLIENT,)
        p2 = subprocess.run(["node", "--input-type=module", "-e", check_js], capture_output=True, text=True)
        self.assertEqual(p2.returncode, 0, p2.stderr)

        # Verify app.js syntax, per-tab live sessions, zero-scroll hydration, reconnect resilience, mobile inertia scroll, and Settings panel
        app_js = os.path.join(ROOT, "container", "web", "herdr", "public", "app.js")
        p3 = subprocess.run(["node", "--check", app_js], capture_output=True, text=True)
        self.assertEqual(p3.returncode, 0, p3.stderr)
        with open(app_js, encoding="utf-8") as f:
            app_src = f.read()
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
            "installAddonLive",
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
            "SWARMBOX_TEST_HERDR_CONFIG": HERDR_TOML,
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


if __name__ == "__main__":
    unittest.main()
