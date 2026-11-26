"""Fast tests for swarmbox-state: repo-grouped agents, shells, parked sessions, pending worktrees, and system diagnostics.
Run with: python3 -W error tests/fast/test_state.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(ROOT, "container", "scripts", "swarmbox-state.py")


def load_state():
    spec = importlib.util.spec_from_file_location("swarmbox_state", STATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sb_state = load_state()


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="sbstate-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.home = os.path.join(self.tmp, "home")
        self.run_dir = os.path.join(self.tmp, "run")
        self.state_dir = os.path.join(self.tmp, "state")
        os.makedirs(self.home)
        os.makedirs(self.run_dir)
        os.makedirs(self.state_dir)
        self.env = {
            "HOME": self.home,
            "SB_RUN_DIR": self.run_dir,
            "SB_STATE_DIR": self.state_dir,
            "PATH": "/usr/bin:/bin",
            "SWARMBOX_WITH": "claude,antigravity",
        }

    def _mk_repo(self, rel, branch="main"):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.join(p, ".git"), exist_ok=True)
        with open(os.path.join(p, ".git", "HEAD"), "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/%s\n" % branch)
        return p

    def test_workspace_groups_agents_by_repo_and_separates_shells_parked_and_pending_worktrees(self):
        repo_a = self._mk_repo("shop-api", "main")
        repo_b = self._mk_repo("payments", "develop")
        wt_live = os.path.join(self.tmp, "wt-1795")
        wt_pend = os.path.join(self.tmp, "wt-5f3e")
        os.makedirs(wt_live)
        os.makedirs(wt_pend)

        tabs = [
            {
                "tab": "t1", "name": "claude", "title": "Fix retries", "dir": wt_live, "cmd": "claude", "active": True,
                "status": {"state": "working", "progress": 74, "msg": "Running tests", "app": "claude"},
                "worktree": {"path": wt_live, "branch": "sb/wt-1795", "base": "main", "repo": repo_a},
            },
            {
                "tab": "t2", "name": "agy", "dir": repo_a, "cmd": "agy", "active": False,
                "status": {"state": "idle", "app": "antigravity"},
            },
            {
                "tab": "t3", "name": "shell", "dir": repo_a, "cmd": "bash", "active": False,
            },
        ]
        pins = [
            {"id": "pin-1", "title": "Billing fix", "agent": "claude", "cwd": repo_b, "resume": "continue"},
        ]
        worktrees = [
            {"id": "wt-1795", "path": wt_live, "repo_root": repo_a, "branch": "sb/wt-1795", "base": "main", "dirty": False, "can_merge": True},
            {"id": "wt-5f3e", "path": wt_pend, "repo_root": repo_a, "branch": "sb/wt-5f3e", "base": "main", "dirty": False, "can_merge": True},
        ]

        ws = sb_state.build_workspace(env=self.env, tabs_list=tabs, pins_list=pins, worktrees_list=worktrees)
        self.assertEqual(ws["active"], "t1")
        self.assertEqual(ws["installed_agents"], ["agy", "claude"])

        # Repos: active repo first (shop-api), idle discovered repo second (payments)
        self.assertEqual([r["name"] for r in ws["repos"]], ["shop-api", "payments"])
        shop = ws["repos"][0]
        self.assertEqual(shop["branch"], "main")
        self.assertEqual(len(shop["agents"]), 2)
        self.assertEqual(shop["agents"][0]["name"], "Fix retries")
        self.assertEqual(shop["agents"][0]["state"], "working")
        self.assertEqual(shop["agents"][0]["progress"], 74)
        self.assertEqual(shop["agents"][0]["worktree"], "wt-1795")
        self.assertEqual(shop["agents"][1]["agent"], "agy")
        self.assertNotIn("worktree", shop["agents"][1])

        # Only detached worktree appears in pending_worktrees
        self.assertEqual([w["id"] for w in shop["pending_worktrees"]], ["wt-5f3e"])

        # Idle repo has empty agents list and no pending_worktrees key
        pay = ws["repos"][1]
        self.assertEqual(pay["agents"], [])
        self.assertNotIn("pending_worktrees", pay)

        # Plain shell separated from agents
        self.assertEqual(len(ws["shells"]), 1)
        self.assertEqual(ws["shells"][0]["tab"], "t3")
        self.assertEqual(ws["shells"][0]["name"], "shop-api")

        # Parked pin present
        self.assertEqual(len(ws["parked"]), 1)
        self.assertEqual(ws["parked"][0]["id"], "pin-1")
        self.assertEqual(ws["parked"][0]["title"], "Billing fix")

    def test_system_section_reads_health_resources_and_addons(self):
        with open(os.path.join(self.run_dir, "ready"), "w", encoding="utf-8") as f:
            f.write("ok\n")
        with open(os.path.join(self.state_dir, "health"), "w", encoding="utf-8") as f:
            f.write("podman: slow start\n")
        sys_info = sb_state.build_system(env=self.env)
        self.assertEqual(sys_info["health"]["ready"], "ok")
        self.assertEqual(sys_info["health"]["warnings"], ["podman: slow start"])
        self.assertIn("disk_free_gb", sys_info["resources"])
        self.assertEqual(sys_info["addons"], ["antigravity", "claude"])

    def test_cli_usage_and_system_section(self):
        p = subprocess.run([sys.executable, STATE_PATH, "--section", "system"], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["schema"], 1)
        self.assertIn("health", data)

        bad = subprocess.run([sys.executable, STATE_PATH, "--section", "bogus"], env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["err"], "usage")


class DetectAgent(unittest.TestCase):
    def test_the_names_an_agent_reports_map_to_its_command(self):
        # Claude Code reports `claude-code` as its OSC 7501 app; the addon of agy is named antigravity.
        self.assertEqual(sb_state.detect_agent({"cmd": "2.1.332", "status": {"app": "claude-code"}}), "claude")
        self.assertEqual(sb_state.detect_agent({"cmd": "node", "status": {"app": "antigravity"}}), "agy")
        self.assertEqual(sb_state.detect_agent({"cmd": "node", "agent": "antigravity"}), "agy")
        # the sticky label of a tab whose agent exited (back at its shell) names no running agent: one rule with the worktree check
        self.assertEqual(sb_state.detect_agent({"cmd": "bash", "agent": "antigravity"}), "")
        self.assertEqual(sb_state.detect_agent({"cmd": "opencode"}), "opencode")
        self.assertEqual(sb_state.detect_agent({"cmd": "bash"}), "")


if __name__ == "__main__":
    unittest.main()
