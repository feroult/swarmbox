"""Mux isolation tests: prove the SwarmBox core (entrypoint serve, swarmbox-attach, swarmbox-web, swarmbox-tabs,
and sysop state/actions/ui_host) operates cleanly against a synthetic backend: the multiplexer is only reached through mux/ and TabsBackend.

Run with: python3 -W error tests/fast/test_mux_isolation.py
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import attach_support as att  # noqa: E402
import serve_support as ss_serve  # noqa: E402
import sysop_support as ss  # noqa: E402
import tabs_support as ts  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_sysop import actions, busclient, config, ipc, state, ui_host  # noqa: E402

MUX_SH = os.path.join(ROOT, "container", "scripts", "mux", "mux.sh")
WEB_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")

FAKE_MUX = r'''#!/bin/bash
# Synthetic multiplexer backend for isolation tests.
mux_available() {
    [ "${FAKE_MUX_UNAVAILABLE:-0}" = 0 ]
}
mux_serve_init() {
    log "step 9: starting fake mux backend"
    echo "serve_init" >> "$FAKE_MUX_LOG"
}
mux_serve_shutdown_note() {
    log "leaving the fake mux backend to end with the container"
    echo "serve_shutdown" >> "$FAKE_MUX_LOG"
}
mux_attach_interactive() {
    echo "attach_interactive" >> "$FAKE_MUX_LOG"
    exit 0
}
mux_attach_command() {
    echo "attach_command:$1" >> "$FAKE_MUX_LOG"
    exit "${FAKE_MUX_CMD_RC:-0}"
}
mux_web_run() {
    echo "web_run:$1:$2:$3" >> "$FAKE_MUX_LOG"
    exit 0
}
'''


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_text(path, text):
    with open(path, "w") as f:
        f.write(text)


def read_text(path):
    with open(path) as f:
        return f.read()


class ShellMuxLoader(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sb-mux-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.mux_dir = os.path.join(self.base, "mux")
        os.mkdir(self.mux_dir)
        shutil.copy(MUX_SH, os.path.join(self.mux_dir, "mux.sh"))
        with open(os.path.join(self.mux_dir, "fake.sh"), "w") as f:
            f.write(FAKE_MUX)
        self.log_path = os.path.join(self.base, "mux.log")

    def test_loader_rejects_invalid_and_unknown_mux_names(self):
        for bad, rc in (("../escape", 2), ("UPPER", 2), ("-dash", 2), ("missing-mux", 1)):
            with self.subTest(bad=bad):
                r = subprocess.run(
                    ["bash", "-c", 'source "$1"', "_", os.path.join(self.mux_dir, "mux.sh")],
                    env={"PATH": "/usr/bin:/bin", "SWARMBOX_MUX": bad, "SWARMBOX_TEST_MUX_DIR": self.mux_dir},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(r.returncode, rc, r.stderr)

    def test_entrypoint_serve_runs_with_custom_mux_and_no_hc_on_path(self):
        c = ss_serve.ServeCase()
        c.setUp()
        self.addCleanup(c.doCleanups)
        # Remove the fake hc so any accidental direct `hc` call would fail loudly
        os.unlink(os.path.join(c.fake, "hc"))
        env = {
            "PATH": c.fake + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
            "HOME": c.home,
            "FAKE_DIR": c.fake,
            "SWARMBOX_TEST_LIB": c.lib,
            "SWARMBOX_TEST_MUX_DIR": self.mux_dir,
            "SWARMBOX_MUX": "fake",
            "FAKE_MUX_LOG": self.log_path,
            "SWARMBOX_TEST_RUN_DIR": c.run_dir,
            "SWARMBOX_TEST_TUN": c.tun,
            "SWARMBOX_TEST_PODMAN_RUNROOT": os.path.join(c.base, "storage-run"),
            "SWARMBOX_TEST_PODMAN_LIBPOD_RUN": os.path.join(c.base, "podman-run"),
            "SWARMBOX_TEST_FALLBACK_SOCK": os.path.join(c.base, "fallback.sock"),
            "SWARMBOX_TEST_BACKOFF_SCALE": "0",
            "SWARMBOX_TEST_SERVICE_WAIT": "2",
            "SWARMBOX_TEST_BUS_WAIT": "1",
            "LANG": "C.UTF-8",
        }
        p = subprocess.Popen(
            ["bash", ss_serve.ENTRYPOINT, "serve"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        c.procs.append(p)
        ss_serve.wait_for(lambda: os.path.exists(os.path.join(c.run_dir, "ready")), 15)
        self.assertEqual(c.marker(), "ok")
        self.assertEqual(c.health_lines(), [])
        rc = c.stop(p, signal.SIGTERM)
        self.assertEqual(rc, 143)
        events = read_text(self.log_path).splitlines()
        self.assertEqual(events, ["serve_init", "serve_shutdown"])
        self.assertIn("starting fake mux backend", c.serve_log())
        self.assertIn("leaving the fake mux backend", c.serve_log())

    def test_attach_delegates_all_modes_to_custom_mux_without_tmux(self):
        run_dir = os.path.join(self.base, "run")
        lib_dir = os.path.join(self.base, "lib")
        os.mkdir(run_dir)
        os.mkdir(lib_dir)
        os.symlink(att.DIRS_SH, os.path.join(lib_dir, "dirs.sh"))
        write_text(os.path.join(run_dir, "ready"), "ok\n")
        frag = os.path.join(self.base, "bashrc.sh")
        write_text(frag, "")

        base_env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.base,
            "SWARMBOX_TEST_LIB": lib_dir,
            "SWARMBOX_TEST_MUX_DIR": self.mux_dir,
            "SWARMBOX_TEST_RUN_DIR": run_dir,
            "SWARMBOX_TEST_FRAGMENT": frag,
            "SWARMBOX_MUX": "fake",
            "FAKE_MUX_LOG": self.log_path,
            "LANG": "C.UTF-8",
        }
        for args, extra, want_rc, want_entry in (
            ([], {}, 0, "attach_interactive"),
            (["echo", "hello"], {"FAKE_MUX_CMD_RC": "7"}, 7, "attach_command:echo hello "),
        ):
            with self.subTest(args=args):
                if os.path.exists(self.log_path):
                    os.unlink(self.log_path)
                env = dict(base_env, **extra)
                proc = att.PtyProc(["bash", att.ATTACH, *args], env=env, cwd=self.base)
                self.addCleanup(proc.close)
                rc = proc.wait(10)
                self.assertEqual(rc, want_rc, proc.out)
                self.assertEqual(read_text(self.log_path).splitlines(), [want_entry])

        # When mux_available returns false, attach falls back to direct execution without failing
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)
        env = dict(base_env, FAKE_MUX_UNAVAILABLE="1")
        proc = att.PtyProc(["bash", att.ATTACH, "true"], env=env, cwd=self.base)
        self.addCleanup(proc.close)
        self.assertEqual(proc.wait(10), 0)
        self.assertFalse(os.path.exists(self.log_path))

    def test_web_run_is_the_backends_web_server(self):
        lib_dir = os.path.join(self.base, "lib")
        run_dir = os.path.join(self.base, "run")
        os.mkdir(lib_dir)
        os.mkdir(run_dir)
        os.symlink(att.DIRS_SH, os.path.join(lib_dir, "dirs.sh"))
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.base,
            "SWARMBOX_TEST_LIB": lib_dir,
            "SWARMBOX_TEST_MUX_DIR": self.mux_dir,
            "SWARMBOX_TEST_RUN_DIR": run_dir,
            "SWARMBOX_MUX": "fake",
            "SWARMBOX_VOICE_WEB": "0",
            "SWARMBOX_TEST_WEB_PORT": "7799",
            "FAKE_MUX_LOG": self.log_path,
            "LANG": "C.UTF-8",
        }
        r = subprocess.run(["bash", WEB_SH, "run"], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_text(self.log_path).splitlines(), ["web_run:7799:0.0.0.0:"])


class TabsCustomBackend(unittest.TestCase):
    def setUp(self):
        self.mod = ts.load_module()
        self.run_dir = tempfile.mkdtemp(prefix="sb-tabs-backend-")
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)

    def make_memory_backend(self, tabs_data, active_id="t1"):
        mod = self.mod

        class MemoryBackend(mod.TabsBackend):
            name = "memory"

            def __init__(self):
                self.data = tabs_data
                self.active_id = active_id
                self.prepared = []
                self.typed = []

            def list_tabs_raw(self):
                return [
                    mod.Tab(d["id"], i, d["name"], d.get("cwd", "/work"), d.get("cmd", "bash"),
                            d["id"], [d["id"]], False, "%d:%s" % (i, d["name"]))
                    for i, d in enumerate(self.data)
                ]

            def active_tab_id(self, tab_ids):
                return self.active_id if self.active_id in tab_ids else (tab_ids[0] if tab_ids else None)

            def capture_screen(self, tab, lines):
                d = next(x for x in self.data if x["id"] == tab.id)
                alt = bool(d.get("alternate", False))
                return mod.ScreenCapture(d.get("raw", ""), [1, 2], alt, False, "", [100, 30], None if alt else lines)

            def capture_plain_rows(self, tab):
                d = next(x for x in self.data if x["id"] == tab.id)
                return d.get("plain", "").split("\n")

            def prepare_send(self, tab):
                self.prepared.append(tab.id)

            def send_text(self, tab, text):
                self.typed.append((tab.id, "text", text))

            def send_key(self, tab, key):
                self.typed.append((tab.id, "key", key))

            def tab_state(self, tab):
                d = next(x for x in self.data if x["id"] == tab.id)
                return d.get("native_state")

        return MemoryBackend()

    def test_tabs_facade_works_end_to_end_on_a_non_tmux_backend(self):
        key = "sk-" + "z9Y8x7W6v5U4t3S2r1Q0"
        backend = self.make_memory_backend([
            {"id": "t1", "name": "agent", "cmd": "claude", "raw": "token " + key + " end\nstatus: \x1b[7mready\x1b[27m",
             "native_state": (True, "idle")},
            {"id": "t2", "name": "shell", "cmd": "bash", "raw": "ok"},
        ], active_id="t1")
        tabs = self.mod.Tabs(backend=backend, run_dir=self.run_dir, pause=0.0, verify_timeout=0.1)

        listed = tabs.list_tabs()
        self.assertEqual([(t["tab"], t["active"]) for t in listed], [("t1", True), ("t2", False)])
        self.assertEqual(tabs.active()["tab"], "t1")
        self.assertEqual(tabs.resolve("agent").id, "t1")
        self.assertEqual(tabs.resolve("1:shell").id, "t2")

        scr = tabs.screen("t1", None)
        self.assertNotIn(key, scr["text"])
        self.assertIn("[REDACTED]", scr["text"])
        self.assertIn("[sel]ready[/sel]", scr["text"])

        res = tabs.send("t1", run="fix tests")
        # no input box to read and the agent stays idle: typed, but nothing showed it was taken
        self.assertEqual(res, {"ok": True, "tab": "t1", "pane": "t1", "submitted": True, "verified": False})
        self.assertEqual(backend.prepared, ["t1"])
        self.assertEqual(backend.typed, [("t1", "text", "fix tests"), ("t1", "key", "Enter")])

    def test_native_tab_state_blocks_dialog_and_busy_without_screen_scraping(self):
        backend = self.make_memory_backend([
            {"id": "t1", "name": "blocked-agent", "cmd": "claude", "plain": "no box at all", "native_state": (True, "dialog")},
            {"id": "t2", "name": "busy-agent", "cmd": "claude", "plain": "no footer at all", "native_state": (True, "busy")},
        ])
        tabs = self.mod.Tabs(backend=backend, run_dir=self.run_dir, pause=0.0, verify_timeout=0.1)

        with self.assertRaises(self.mod.TabsError) as cm:
            tabs.send("t1", run="go")
        self.assertEqual(cm.exception.code, "dialog_open")

        with self.assertRaises(self.mod.TabsError) as cm:
            tabs.send("t2", run="next")
        self.assertEqual(cm.exception.code, "busy_tab")

        # Queued send succeeds even when native state is busy
        tabs.send("t2", run="next", queue=True)
        self.assertEqual(backend.typed[-2:], [("t2", "text", "next"), ("t2", "key", "Enter")])

    def test_unknown_backend_fails_with_no_backend_and_exit_4(self):
        with self.assertRaises(self.mod.TabsError) as cm:
            self.mod.Tabs(backend="nonexistent")
        self.assertEqual(cm.exception.code, "no_backend")
        self.assertEqual(self.mod.EXIT["no_backend"], 4)


class SysopMuxAgnostic(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)

    def test_state_snapshot_and_state_dict_work_without_tmux(self):
        self.svc.goal("build the release")
        self.svc.pending("approve", "high", text="rm -rf dist")
        snap = state.snapshot(self.pth)
        d = state.state_dict(snap, wall=time.time())
        self.assertTrue(d["up"])
        self.assertEqual(d["state"], "allow?")
        self.assertEqual(d["sentence"], "rm -rf dist")
        self.assertEqual(d["goal_id"], "g1")
        self.assertIsNotNone(d["pending"])

    def test_actions_approve_veto_and_publish_goal_work_without_tmux(self):
        self.svc.goal("deploy")
        self.svc.pending("approve", "high")
        r = actions.approve(self.pth, by="web")
        self.assertTrue(r.ok)
        self.assertEqual(r.rc, 0)
        self.assertEqual(self.svc.decision(), {"id": "p1", "decision": "approve", "by": "web", "word": "run"})

        self.svc.pending("veto", "medium")
        r = actions.veto(self.pth, by="web")
        self.assertTrue(r.ok)
        self.assertEqual(self.svc.decision(), {"id": "p1", "decision": "veto", "by": "web"})

        bus = ss.FakeBus(self.e.env["SB_BUS_SOCKET"])
        self.addCleanup(bus.stop)
        import socket
        sub = socket.socket(socket.AF_UNIX)
        sub.connect(bus.path)
        sub.sendall(b'{"op":"sub","topic":"goal"}\n')
        f = sub.makefile("rb")
        self.addCleanup(sub.close)
        f.readline()
        self.assertTrue(ss.wait_for(lambda: bus.subs, 5))
        gid, _ = actions.publish_goal(busclient.Bus(self.e.env["SB_BUS_SOCKET"]), "run checks", source="web", topic="goal")
        self.assertTrue(gid)
        env = json.loads(f.readline())
        self.assertEqual((env["source"], env["body"]), ("web", {"text": "run checks"}))

    def test_ui_host_headless_and_unknown_mux_never_start_a_ui(self):
        cfg = config.load({})
        logs = []
        for mux in ("none", "custom-mux"):
            sess = ui_host.start_ui(self.pth, cfg, log=logs.append, enabled=True, mux=mux)
            sess.shutdown(unset=True)
        self.assertTrue(any("custom-mux" in m for m in logs))
        self.assertFalse(any("herdr" in m for m in logs), "no agent bridge is started")
        self.assertEqual(ui_host.mux_name({}), "herdr", "herdr is the default (the only multiplexer of the box)")


if __name__ == "__main__":
    unittest.main()
