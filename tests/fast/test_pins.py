"""Fast tests for container/scripts/swarmbox-pins.py.

Covers: atomic pins.json persistence (mode 0600, preserving unknown keys), add/update/remove/list,
safe --continue agent wrapper fallback, and idempotent autostart restoration against a fake `hc`.

Run: python3 tests/fast/test_pins.py
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

PINS_SCRIPT = os.path.join(ROOT, "container", "scripts", "swarmbox-pins.py")
_spec = importlib.util.spec_from_file_location("swarmbox_pins_mod", PINS_SCRIPT)
pins_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pins_mod)


FAKE_HC = r"""#!/usr/bin/env python3
import json, os, sys
STATE = os.environ["FAKE_HC_STATE"]
with open(STATE, encoding="utf-8") as f:
    st = json.load(f)
argv = sys.argv[1:]
cmd = argv[0] if argv else ""
if cmd == "ls":
    want = []
    i = 1
    while i < len(argv):
        if argv[i] == "--label" and i + 1 < len(argv):
            if "=" in argv[i + 1]:
                want.append(tuple(argv[i + 1].split("=", 1)))
            i += 2
            continue
        i += 1
    terms = st.get("terminals", [])
    if want:
        terms = [t for t in terms if all((t.get("labels") or {}).get(k) == v for k, v in want)]
    print(json.dumps({"terminals": terms}))
    sys.exit(0)
if cmd == "get":
    tid = argv[-1]
    for t in st.get("terminals", []):
        if t["address"] == tid:
            print(json.dumps(t))
            sys.exit(0)
    sys.exit(1)
if cmd == "label":
    tid = argv[1]
    for t in st.get("terminals", []):
        if t["address"] == tid:
            lbls = t.setdefault("labels", {})
            for kv in argv[2:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    if v == "":
                        lbls.pop(k, None)
                    else:
                        lbls[k] = v
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump(st, f)
            print(json.dumps(t))
            sys.exit(0)
    sys.exit(1)
if cmd == "run":
    name = argv[argv.index("--name") + 1] if "--name" in argv else "term"
    cwd = argv[argv.index("--cwd") + 1] if "--cwd" in argv else os.getcwd()
    labels = {}
    i = 1
    while i < len(argv):
        if argv[i] == "--label" and i + 1 < len(argv):
            k, v = argv[i + 1].split("=", 1)
            labels[k] = v
            i += 2
            continue
        i += 1
    cmd_argv = argv[argv.index("--") + 1:] if "--" in argv else []
    addr = "t%d" % (len(st.get("terminals", [])) + 1)
    t = {"address": addr, "name": name, "cwd": cwd, "state": "live", "labels": labels, "argv": cmd_argv}
    st.setdefault("terminals", []).append(t)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f)
    print(json.dumps(t))
    sys.exit(0)
sys.exit(0)
"""


class PinsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-pins.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.proj1 = os.path.join(self.home, "shop-api")
        self.proj2 = os.path.join(self.home, "api-pay")
        os.makedirs(self.proj1, exist_ok=True)
        os.makedirs(self.proj2, exist_ok=True)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
        }

    def test_crud_mode_and_unknown_field_preservation(self):
        p1 = pins_mod.add_pin(self.proj1, agent="claude", title="", env=self.env)
        self.assertEqual(p1["title"], "shop-api")
        self.assertEqual(p1["resume"], "continue")
        self.assertFalse(p1["autostart"])

        # Check file permissions are 0600
        fp = pins_mod.pins_path(self.env)
        self.assertEqual(stat.S_IMODE(os.stat(fp).st_mode), 0o600)

        # Inject a future/unknown key and verify update preserves it
        with open(fp, encoding="utf-8") as f:
            raw = json.load(f)
        raw["pins"][0]["future_flag"] = "keep-me"
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(raw, f)

        updated = pins_mod.update_pin(p1["id"], title="Auth Refactor", title_source="user", autostart=True, env=self.env)
        self.assertEqual(updated["title"], "Auth Refactor")
        self.assertEqual(updated["title_source"], "user")
        self.assertTrue(updated["autostart"])
        self.assertEqual(updated["future_flag"], "keep-me")

        rem = pins_mod.remove_pin(p1["id"], env=self.env)
        self.assertTrue(rem["ok"])
        self.assertEqual(pins_mod.load_pins(env=self.env), [])

    def test_build_agent_argv_continue_fallback(self):
        argv_c = pins_mod.build_agent_argv("claude", "continue")
        self.assertEqual(argv_c[:2], ["/bin/bash", "-lic"])
        self.assertIn("claude --continue", argv_c[2])
        argv_f = pins_mod.build_agent_argv("claude", "fresh")
        self.assertNotIn("--continue", argv_f[2])
        self.assertEqual(pins_mod.build_agent_argv("shell", "continue"), ["/bin/bash", "-l"])

        # Execute the fallback logic against a fake claude binary:
        # --continue exits 1 immediately -> falls back to plain `claude`
        fbin = os.path.join(self.tmp, "bin")
        os.makedirs(fbin)
        calls = os.path.join(self.tmp, "claude-calls.log")
        fake_claude = os.path.join(fbin, "claude")
        with open(fake_claude, "w", encoding="utf-8") as f:
            f.write(
                f"#!/bin/sh\necho \"$*\" >> {calls}\n"
                "if [ \"$1\" = \"--continue\" ]; then exit 1; fi\nexit 0\n"
            )
        os.chmod(fake_claude, 0o755)
        script = argv_c[2].replace("exec /bin/bash -l", "true")
        subprocess.run(
            ["/bin/bash", "-c", script],
            env={"PATH": fbin + ":" + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home},
            check=True,
        )
        with open(calls, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines, ["--continue", ""])

    def test_restore_autostart_only_idempotent_and_skips_missing_cwd(self):
        hc_state = os.path.join(self.tmp, "hc-state.json")
        with open(hc_state, "w", encoding="utf-8") as f:
            json.dump({"terminals": []}, f)
        hc_bin = os.path.join(self.tmp, "hc")
        with open(hc_bin, "w", encoding="utf-8") as f:
            f.write(FAKE_HC)
        os.chmod(hc_bin, 0o755)

        env = {**self.env, "FAKE_HC_STATE": hc_state, "SWARMBOX_TEST_HC_BIN": hc_bin}
        p_auto = pins_mod.add_pin(self.proj1, agent="agy", title="SwarmBox Web", title_source="user", autostart=True, env=env)
        pins_mod.add_pin(self.proj2, agent="claude", title="Parked One", autostart=False, env=env)
        p_miss = pins_mod.add_pin(os.path.join(self.home, "deleted-dir"), agent="claude", title="Gone", autostart=True, env=env)

        r1 = pins_mod.restore_autostart_pins(env=env)
        self.assertEqual(len(r1["spawned"]), 1)
        self.assertEqual(r1["spawned"][0]["id"], p_auto["id"])
        self.assertEqual(len(r1["skipped"]), 1)
        self.assertEqual(r1["skipped"][0]["id"], p_miss["id"])
        self.assertEqual(r1["skipped"][0]["reason"], "missing_cwd")

        with open(hc_state, encoding="utf-8") as f:
            st = json.load(f)
        self.assertEqual(len(st["terminals"]), 1)
        self.assertEqual(st["terminals"][0]["labels"]["swarmbox.pin_id"], p_auto["id"])
        self.assertEqual(st["terminals"][0]["labels"]["swarmbox.title"], "SwarmBox Web")

        # Second restore is idempotent (does not duplicate already-live pin)
        r2 = pins_mod.restore_autostart_pins(env=env)
        self.assertEqual(len(r2["spawned"]), 0)

    def test_tabs_rename_syncs_pin_and_resolves_by_title_and_open_worktree(self):
        hc_state = os.path.join(self.tmp, "hc-tabs.json")
        hc_bin = os.path.join(self.tmp, "hc-tabs")
        with open(hc_bin, "w", encoding="utf-8") as f:
            f.write(FAKE_HC)
        os.chmod(hc_bin, 0o755)
        env = {**self.env, "FAKE_HC_STATE": hc_state, "SB_TABS_HC_BIN": hc_bin}

        # Create a real temp git repo for open --worktree
        git_env = {
            **env,
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@e.com",
        }
        subprocess.run(["git", "init", "-b", "main"], cwd=self.proj1, env=git_env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.proj1, env=git_env, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=self.proj1, env=git_env, check=True)
        with open(os.path.join(self.proj1, "a.txt"), "w", encoding="utf-8") as f:
            f.write("hi\n")
        subprocess.run(["git", "add", "a.txt"], cwd=self.proj1, env=git_env, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.proj1, env=git_env, check=True, stdout=subprocess.DEVNULL)

        pin = pins_mod.add_pin(self.proj1, agent="claude", title="Old Name", env=env)
        with open(hc_state, "w", encoding="utf-8") as f:
            json.dump({
                "terminals": [{
                    "address": "t1", "name": "claude", "cwd": self.proj1, "state": "live",
                    "labels": {"swarmbox.pin_id": pin["id"], "swarmbox.title": "Old Name"},
                }],
            }, f)

        tabs_script = os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")
        # Rename tab -> updates hc label AND syncs pins.json
        r_ren = subprocess.run([sys.executable, tabs_script, "rename", "t1", "Fix OAuth", "--source", "user"],
                               env=env, capture_output=True, text=True, check=True)
        ren_data = json.loads(r_ren.stdout)
        self.assertEqual(ren_data["title"], "Fix OAuth")
        self.assertEqual(pins_mod.load_pins(env=env)[0]["title"], "Fix OAuth")

        # Resolve tab by its custom display title (case-insensitive)
        r_foc = subprocess.run([sys.executable, tabs_script, "focus", "fix oauth"], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(r_foc.stdout)["tab"], "t1")

        # Open a new tab with --worktree creates an isolated git worktree and attaches labels
        env["XDG_DATA_HOME"] = os.path.join(self.home, ".local", "share")
        r_wt = subprocess.run([sys.executable, tabs_script, "open", "--agent", "claude", "--cwd", self.proj1, "--worktree"],
                              env=env, capture_output=True, text=True, check=True)
        wt_out = json.loads(r_wt.stdout)
        self.assertTrue(wt_out["ok"])
        self.assertIn("worktree", wt_out)
        self.assertTrue(os.path.isdir(wt_out["worktree"]["path"]))
        self.assertTrue(wt_out["worktree"]["branch"].startswith("sb/wt-"))

    def test_herdr_ensure_initial_tab_uses_autostart_pins_or_falls_back_to_shell(self):
        hc_state = os.path.join(self.tmp, "hc-boot.json")
        hc_bin = os.path.join(self.tmp, "hc-boot")
        with open(hc_bin, "w", encoding="utf-8") as f:
            f.write(FAKE_HC)
        os.chmod(hc_bin, 0o755)
        herdr_sh = os.path.join(ROOT, "container", "scripts", "mux", "herdr.sh")

        # Case 1: autostart pin exists -> herdr.sh restores it without spawning extra shell
        with open(hc_state, "w", encoding="utf-8") as f:
            json.dump({"terminals": []}, f)
        env = {
            **self.env,
            "FAKE_HC_STATE": hc_state,
            "SWARMBOX_TEST_HC_BIN": hc_bin,
            "SWARMBOX_TEST_PINS_BIN": PINS_SCRIPT,
        }
        p_auto = pins_mod.add_pin(self.proj1, agent="claude", title="Boot Pin", autostart=True, env=env)
        subprocess.run(
            ["/bin/bash", "-c", f'source "{herdr_sh}" && _herdr_ensure_initial_tab'],
            env=env, check=True,
        )
        with open(hc_state, encoding="utf-8") as f:
            terms = json.load(f)["terminals"]
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]["labels"].get("swarmbox.pin_id"), p_auto["id"])

        # Case 2: only parked (autostart=False) pins exist -> herdr.sh spawns default shell
        pins_mod.update_pin(p_auto["id"], autostart=False, env=env)
        with open(hc_state, "w", encoding="utf-8") as f:
            json.dump({"terminals": []}, f)
        subprocess.run(
            ["/bin/bash", "-c", f'source "{herdr_sh}" && _herdr_ensure_initial_tab'],
            env=env, check=True,
        )
        with open(hc_state, encoding="utf-8") as f:
            terms2 = json.load(f)["terminals"]
        self.assertEqual(len(terms2), 1)
        self.assertEqual(terms2[0]["name"], "shell")


if __name__ == "__main__":
    unittest.main()
