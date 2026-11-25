"""Fast tests for Sysop event-driven AutoNamer (`tab.events`), `rename_tab`, and `worktree` MCP actions.

Run: python3 tests/fast/test_sysop_autoname_worktree.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SYSOP_LIB = os.path.join(ROOT, "container", "addons", "sysop", "lib")
if SYSOP_LIB not in sys.path:
    sys.path.insert(0, SYSOP_LIB)

from swarmbox_sysop import audit as auditmod  # noqa: E402
from swarmbox_sysop import autoname  # noqa: E402
from swarmbox_sysop import config as sysop_config  # noqa: E402
from swarmbox_sysop import history as sysop_history  # noqa: E402
from swarmbox_sysop import mcpserver  # noqa: E402
from swarmbox_sysop import paths as sysop_paths  # noqa: E402


class FakeTabs:
    def __init__(self, tabs, screens):
        self.tabs = tabs
        self.screens = screens
        self.renames = []
        self.opened = []
        self.closed = []
        self.wt_calls = []

    def list_tabs(self):
        return [dict(t) for t in self.tabs]

    def screen(self, tab, lines=None):
        return {"tab": tab, "pane": tab, "text": self.screens.get(tab, ""), "cursor": [0, 0], "alternate": False}

    def rename_tab(self, tab, title, source="auto"):
        old = ""
        for t in self.tabs:
            if t["tab"] == tab:
                old = t.get("title") or t.get("name") or tab
                t["title"] = title
                t["title_source"] = source
        self.renames.append((tab, title, source))
        return {"ok": True, "tab": tab, "title": title, "old_title": old, "source": source}

    def open_tab(self, name=None, cwd=None, agent=None, worktree=False):
        self.opened.append({"name": name, "cwd": cwd, "agent": agent, "worktree": worktree})
        res = {"ok": True, "tab": "t9", "name": name or agent or "shell", "agent": agent or "shell"}
        if worktree:
            res["worktree"] = {"path": "/tmp/wt-9", "branch": "sb/wt-9", "base": "main", "repo": cwd or "/work"}
        return res

    def close_tab(self, tab):
        self.closed.append(tab)
        return {"ok": True, "tab": tab}

    def worktree(self, action, path, clean=False, force=False):
        self.wt_calls.append({"action": action, "path": path, "clean": clean, "force": force})
        if action == "status":
            return {"ok": True, "path": path, "branch": "sb/wt-1", "base": "main", "ahead": 2, "dirty": False, "can_merge": True}
        if action == "merge":
            return {"ok": True, "branch": "sb/wt-1", "base": "main", "cleaned": clean}
        return {"ok": True, "path": path}


class AutoNamerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-autoname.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {
            "HOME": self.tmp,
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
            "SB_STATE_DIR": os.path.join(self.tmp, "state"),
        }
        self.paths = sysop_paths.Paths(self.env).make()
        self.now = 1000.0
        self.audit = auditmod.Audit(self.paths.audit, clock=lambda: self.now)

    def test_autonamer_renames_on_turn_respects_user_lock_busy_and_cooldown(self):
        tabs = FakeTabs(
            [{"tab": "t1", "label": "1:claude", "index": 1, "name": "claude", "dir": "~/api", "cmd": "claude", "active": True}],
            {"t1": "Investigating OAuth 401 callback error in src/auth/oauth.ts and running pytest suite\n18 passed"},
        )
        busy = [False]
        suggested = ["Fix OAuth Login"]
        namer = autoname.AutoNamer(
            bus=None,
            paths=self.paths,
            audit=self.audit,
            tabs=tabs,
            is_busy=lambda: busy[0],
            namer=lambda cwd, ag, title, scr: suggested[0],
            clock=lambda: self.now,
            cooldown=180.0,
        )

        # Busy sysop skips auto-naming
        busy[0] = True
        self.assertIsNone(namer.handle_event({"body": {"event": "turn", "tab": "t1", "cwd": "/home/a/api", "agent": "claude"}}))
        self.assertEqual(tabs.renames, [])

        # Idle sysop renames on turn and writes system_events.jsonl
        busy[0] = False
        got = namer.handle_event({"body": {"event": "turn", "tab": "t1", "cwd": "/home/a/api", "agent": "claude"}})
        self.assertEqual(got, "Fix OAuth Login")
        self.assertEqual(tabs.renames, [("t1", "Fix OAuth Login", "auto")])
        with open(self.paths.system_events, encoding="utf-8") as f:
            evs = [json.loads(ln) for ln in f if ln.strip()]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "autoname")
        self.assertEqual(evs[0]["agent"], "claude")
        self.assertEqual(evs[0]["new_title"], "Fix OAuth Login")

        # Cooldown skips second turn in same cwd
        tabs.screens["t1"] += "\nmore output lines here for another turn in the same project"
        suggested[0] = "Another Name"
        self.now += 30.0
        self.assertIsNone(namer.handle_event({"body": {"event": "turn", "tab": "t1", "cwd": "/home/a/api", "agent": "claude"}}))

        # Even past cooldown, an already auto-named tab in the same cwd does not churn
        tabs.screens["t1"] += "\nadditional turn output in the same folder after cooldown"
        self.now += 500.0
        self.assertIsNone(namer.handle_event({"body": {"event": "turn", "tab": "t1", "cwd": "/home/a/api", "agent": "claude"}}))
        self.assertEqual(tabs.tabs[0]["title"], "Fix OAuth Login")

        # Changing cwd bypasses cooldown and re-names for the new directory
        got2 = namer.handle_event({"body": {"event": "cwd", "tab": "t1", "cwd": "/home/a/web", "agent": "claude"}})
        self.assertEqual(got2, "Another Name")

        # User-locked title is never overwritten
        tabs.tabs[0]["title"] = "My Custom Name"
        tabs.tabs[0]["title_source"] = "user"
        tabs.screens["t1"] += "\neven more new text after user rename"
        self.now += 500.0
        suggested[0] = "Should Not Apply"
        self.assertIsNone(namer.handle_event({"body": {"event": "turn", "tab": "t1", "cwd": "/home/a/web", "agent": "claude"}}))
        self.assertEqual(tabs.tabs[0]["title"], "My Custom Name")

        # KEEP and generic titles are ignored
        self.assertEqual(autoname.clean_suggested_title("KEEP"), "")
        self.assertEqual(autoname.clean_suggested_title("shell"), "")
        self.assertEqual(autoname.clean_suggested_title('"Fix Cache TTL."'), "Fix Cache TTL")

    def test_mcp_box_state_open_worktree_rename_and_worktree_action(self):
        cfg = sysop_config.load({"SWARMBOX_SYSOP_AUTONAME": "0"})
        self.assertFalse(cfg.autoname)
        self.assertTrue(sysop_config.load({}).autoname)

        gdir = self.paths.goal_dir("g1")
        os.makedirs(gdir, exist_ok=True)
        ctx = mcpserver.Context({"goal": "g1", "source": "web", "goal_dir": gdir, "audit": self.paths.audit, "autonomy": "full-auto"})
        tabs = FakeTabs(
            [
                {
                    "tab": "t1", "label": "1:claude", "index": 1, "name": "claude", "title": "Fix Cache Bug",
                    "pinned": True, "dir": "/tmp/wt-1", "cmd": "claude", "active": True,
                    "worktree": {"path": "/tmp/wt-1", "branch": "sb/wt-1", "base": "main", "repo": "/home/a/shop"},
                }
            ],
            {"t1": "done"},
        )
        tabs.box_state = lambda section="workspace": {
            "schema": 1, "active": "t1",
            "repos": [{"name": "shop", "path": "/home/a/shop", "branch": "main", "agents": [
                {"tab": "t1", "name": "Fix Cache Bug", "agent": "claude", "state": "idle", "branch": "sb/wt-1", "worktree": "wt-1"},
            ]}],
        }
        srv = mcpserver.Server(ctx, tabs=tabs, clock=lambda: self.now)

        # box_state exposes repo-grouped agent with display title and worktree branch
        listed = srv.t_box_state({})
        ws = json.loads(listed.splitlines()[1])
        self.assertEqual(ws["repos"][0]["agents"][0]["name"], "Fix Cache Bug")
        self.assertEqual(ws["repos"][0]["agents"][0]["branch"], "sb/wt-1")

        # tab(action="open") resolves repo name and forwards worktree=True
        opened = srv.t_tab({"action": "open", "agent": "claude", "repo": "shop", "worktree": True})
        self.assertIn("sb/wt-9", opened)
        self.assertEqual(tabs.opened[-1]["cwd"], "/home/a/shop")
        self.assertTrue(tabs.opened[-1]["worktree"])

        # tab(action="rename") locks title as user-owned without duplicating background system_events or polluting history
        srv.t_tab({"action": "rename", "tab": "t1", "title": "Cache TTL Fix"})
        self.assertEqual(tabs.renames[-1], ("t1", "Cache TTL Fix", "user"))
        self.assertEqual(sysop_history.conversation(sysop_history.load(self.paths), "g2", self.now), "")

        # worktree status (read-only) & merge with clean=True closes tab
        st_out = json.loads(srv.t_worktree({"target": "t1", "action": "status"}))
        self.assertTrue(st_out["can_merge"])
        m_out = json.loads(srv.t_worktree({"target": "t1", "action": "merge", "clean": True}))
        self.assertTrue(m_out["cleaned"])
        self.assertEqual(tabs.closed, ["t1"])


if __name__ == "__main__":
    unittest.main()
