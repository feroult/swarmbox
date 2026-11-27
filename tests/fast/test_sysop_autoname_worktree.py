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

    def _namer(self, tabs, suggested, busy=None, requests=None, calls=None, **kw):
        def fake(cwd, ag, title, scr, requests=None):
            if calls is not None:
                calls.append({"cwd": cwd, "agent": ag, "title": title, "screen": scr, "requests": requests})
            return suggested[0]
        return autoname.AutoNamer(
            bus=None,
            paths=self.paths,
            audit=self.audit,
            tabs=tabs,
            is_busy=(lambda: busy[0]) if busy is not None else None,
            namer=fake,
            clock=lambda: self.now,
            requests=requests or (lambda agent, cwd: []),
            **kw
        )

    @staticmethod
    def _turn(cwd="/home/a/api", event="turn"):
        return {"body": {"event": event, "tab": "t1", "cwd": cwd, "agent": "claude"}}

    def test_autonamer_renames_on_turn_respects_user_lock_busy_and_backoff(self):
        tabs = FakeTabs(
            [{"tab": "t1", "label": "1:claude", "index": 1, "name": "claude", "dir": "~/api", "cmd": "claude", "active": True}],
            {"t1": "Investigating OAuth 401 callback error in src/auth/oauth.ts and running pytest suite\n18 passed"},
        )
        busy = [False]
        suggested = ["Fix OAuth Login"]
        namer = self._namer(tabs, suggested, busy=busy, cooldowns=(180.0, 600.0), recheck=60.0)

        # Busy sysop skips auto-naming
        busy[0] = True
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(tabs.renames, [])

        # Idle sysop renames on turn and writes system_events.jsonl
        busy[0] = False
        self.assertEqual(namer.handle_event(self._turn()), "Fix OAuth Login")
        self.assertEqual(tabs.renames, [("t1", "Fix OAuth Login", "auto")])
        with open(self.paths.system_events, encoding="utf-8") as f:
            evs = [json.loads(ln) for ln in f if ln.strip()]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "autoname")
        self.assertEqual(evs[0]["agent"], "claude")
        self.assertEqual(evs[0]["new_title"], "Fix OAuth Login")

        # Inside the first backoff step (180 s) a new turn does not rename
        tabs.screens["t1"] += "\nmore output lines here for another turn in the same project"
        suggested[0] = "Login Redirect"
        self.now += 30.0
        self.assertIsNone(namer.handle_event(self._turn()))

        # Past it, an auto-named tab is renamed again when the goal changed: names are not frozen
        self.now += 200.0
        self.assertEqual(namer.handle_event(self._turn()), "Login Redirect")
        self.assertEqual(tabs.tabs[0]["title"], "Login Redirect")

        # The second step is longer (600 s): 300 s later it still keeps the name
        tabs.screens["t1"] += "\nyet another turn of output in the same folder"
        suggested[0] = "Third Name"
        self.now += 300.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(tabs.tabs[0]["title"], "Login Redirect")

        # Changing cwd bypasses the backoff and names the new directory
        self.assertEqual(namer.handle_event(self._turn("/home/a/web", event="cwd")), "Third Name")

        # User-locked title is never overwritten
        tabs.tabs[0]["title"] = "My Custom Name"
        tabs.tabs[0]["title_source"] = "user"
        tabs.screens["t1"] += "\neven more new text after user rename"
        self.now += 5000.0
        suggested[0] = "Should Not Apply"
        self.assertIsNone(namer.handle_event(self._turn("/home/a/web")))
        self.assertEqual(tabs.tabs[0]["title"], "My Custom Name")

    def test_backoff_steps_grow_and_stop_at_the_last(self):
        namer = autoname.AutoNamer(bus=None, paths=self.paths, tabs=FakeTabs([], {}))
        self.assertEqual([namer.cooldown_for(n) for n in range(6)], [0.0, 180.0, 600.0, 1800.0, 3600.0, 3600.0])

    def test_keep_answer_waits_recheck_only_on_a_named_tab_and_unchanged_input_never_calls(self):
        tabs = FakeTabs([{"tab": "t1", "name": "api", "cmd": "claude"}], {"t1": "x" * 80})
        calls = []
        suggested = ["KEEP"]
        namer = self._namer(tabs, suggested, calls=calls, recheck=120.0)
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(len(calls), 1)
        # Still unnamed ('api' is the folder): new input is tried at once, a KEEP costs no wait
        tabs.screens["t1"] = "y" * 80
        self.now += 5.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(len(calls), 2)
        # A named tab (auto) waits the recheck interval after a KEEP
        tabs.tabs[0].update(title="Fix Login", title_source="auto")
        tabs.screens["t1"] = "z" * 80
        self.now += 60.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(len(calls), 2)
        # Past it, with the same screen as the last call: no call either
        tabs.screens["t1"] = "x" * 80
        namer._tab_state["t1"]["last_sig"] = "s|/home/a/api|80|" + "x" * 80
        self.now += 500.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(len(calls), 2)

    def test_user_requests_replace_the_screen_and_gate_on_new_requests(self):
        tabs = FakeTabs([{"tab": "t1", "name": "api", "cmd": "claude"}], {})  # no screen at all: it must not be needed
        reqs = [["entenda o repo"]]
        seen = []
        calls = []
        suggested = ["KEEP"]

        def requests(agent, cwd):
            seen.append((agent, cwd))
            return list(reqs[0])

        namer = self._namer(tabs, suggested, requests=requests, calls=calls, recheck=10.0)
        self.assertIsNone(namer.handle_event(self._turn()))          # exploration only: KEEP, the folder name stays
        self.assertEqual(seen, [("claude", "/home/a/api")])
        self.assertEqual(calls[0]["requests"], ["entenda o repo"])
        self.assertEqual(calls[0]["title"], "")                        # 'api' is the folder name: a placeholder, shown as none
        self.assertEqual(calls[0]["screen"], "")
        # Same requests later: no new call
        self.now += 100.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(len(calls), 1)
        # A real goal arrives: named from it
        reqs[0] = ["entenda o repo", "o sysop deveria renomear as tabs com nomes curtos"]
        suggested[0] = "Renomear Tabs"
        self.now += 100.0
        self.assertEqual(namer.handle_event(self._turn()), "Renomear Tabs")
        with open(self.paths.audit, encoding="utf-8") as f:
            recs = [json.loads(ln) for ln in f if ln.strip()]
        self.assertEqual(recs[-1].get("source"), "requests")
        # The current auto title is passed so the model can answer KEEP
        reqs[0].append("agora adicione testes")
        suggested[0] = "KEEP"
        self.now += 1000.0
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertEqual(calls[-1]["title"], "Renomear Tabs")

    def test_a_sent_request_names_the_tab_after_the_grace_unless_cancelled(self):
        tabs = FakeTabs([{"tab": "t1", "name": "api", "cmd": "claude"}], {})
        reqs = [["corrija o redirect do login oauth"]]
        calls = []
        suggested = ["Login OAuth"]
        logs = []
        namer = self._namer(tabs, suggested, requests=lambda a, c: list(reqs[0]), calls=calls, grace=3.0, log=logs.append)
        # Sent: nothing happens before the grace
        self.assertIsNone(namer.handle_event(self._turn(event="start")))
        self.now += 2.0
        self.assertEqual(namer.run_due(), [])
        self.assertEqual(calls, [])
        # Cancelled inside the grace (the tab stopped working): not named, and that end of work is not evaluated either
        self.assertIsNone(namer.handle_event(self._turn(event="status")))
        self.now += 10.0
        self.assertEqual(namer.run_due(), [])
        self.assertEqual(calls, [])
        self.assertIn("cancelled", logs[-1])
        # Sent again and still working after the grace: named, long before the turn ends
        reqs[0].append("e adicione um teste para o callback")
        namer.handle_event(self._turn(event="start"))
        self.now += 3.0
        self.assertEqual(namer.run_due(), ["Login OAuth"])
        self.assertEqual(tabs.renames, [("t1", "Login OAuth", "auto")])
        self.assertIn("-> 'Login OAuth' on start", logs[-1])
        # The end of that turn, with the same requests, makes no second call
        self.now += 60.0
        self.assertIsNone(namer.handle_event(self._turn(event="status")))
        self.assertEqual(len(calls), 1)

    def test_a_failed_naming_call_is_logged_and_retried(self):
        tabs = FakeTabs([{"tab": "t1", "name": "api", "cmd": "claude"}], {})
        logs = []
        fail = [True]

        def namer_fn(cwd, ag, title, scr, requests=None):
            if fail[0]:
                raise autoname.NamerError("claude -p exit 1: Not logged in")
            return "Login OAuth"

        namer = autoname.AutoNamer(bus=None, paths=self.paths, tabs=tabs, namer=namer_fn, clock=lambda: self.now,
                                   log=logs.append, requests=lambda a, c: ["corrija o login oauth agora"])
        self.assertIsNone(namer.handle_event(self._turn()))
        self.assertIn("Not logged in", logs[-1])
        fail[0] = False
        self.now += 1.0
        self.assertEqual(namer.handle_event(self._turn()), "Login OAuth")   # same input, but the failure was no answer

    def test_titles_fit_the_sidebar(self):
        self.assertEqual(autoname.clean_suggested_title("KEEP"), "")
        self.assertEqual(autoname.clean_suggested_title("shell"), "")
        self.assertEqual(autoname.clean_suggested_title('"Fix Cache TTL."'), "Fix Cache TTL")
        self.assertEqual(autoname.clean_suggested_title("Checkout Cache Tests Suite"), "Checkout Cache")
        self.assertEqual(autoname.clean_suggested_title("Renomear Tabs de Agentes"), "Renomear Tabs")
        self.assertEqual(autoname.clean_suggested_title("Supercalifragilisticexpialidocious"), "Supercalifragilist")
        # Real answers of the naming model (November 2026) that ignored the limit: a label and the activity verb are
        # dropped so the cut keeps the subject, and an answer that is only an activity names nothing.
        self.assertEqual(autoname.clean_suggested_title("Goal: evaluate Rex vs Herdr as terminal engine"), "Rex vs Herdr")
        self.assertEqual(autoname.clean_suggested_title("Comparar Rex e Herdr como engine de terminal"), "Rex e Herdr")
        self.assertEqual(autoname.clean_suggested_title("Goal: evaluate"), "")
        self.assertEqual(autoname.clean_suggested_title("Avaliar"), "")
        self.assertEqual(autoname.clean_suggested_title("Title:\nTab Autonamer"), "Tab Autonamer")
        self.assertEqual(autoname.clean_suggested_title("Rex vs. Herdr"), "Rex vs. Herdr")
        for raw in ("Mobile Sysop Sheet Redesign", "Fix the OAuth login flow", "Cmd+C macOS"):
            self.assertLessEqual(len(autoname.clean_suggested_title(raw)), autoname.MAX_TITLE_CHARS)

    def test_an_explanation_is_no_title(self):
        # Real answers (November 2026) that explained instead of naming: the cut made "Current title" and "Título atual".
        for raw in ('Current title "Plano CI&T" is about a CI&T plan/doc. Latest request is about AWS questions',
                    "Título atual: nenhum. O pedido é claro: adicionar uma tela/seção",
                    "Folder: /home/a/api",
                    "The user is asking about questions to ask in a meeting with the team"):
            self.assertEqual(autoname.clean_suggested_title(raw), "", raw)

    def test_prompt_carries_requests_or_screen(self):
        p = autoname.build_prompt("/home/a/api", "claude", "", "SCREEN", ["fix login", "add tests"])
        self.assertIn("Current title: (none)", p)
        self.assertIn("- fix login\n- add tests\n", p)
        self.assertNotIn("SCREEN", p)
        p2 = autoname.build_prompt("/home/a/api", "agy", "Fix Login", "z" * 5000)
        self.assertIn("Current title: Fix Login", p2)
        self.assertIn("SCREEN START", p2)
        self.assertLess(len(p2), 1700)
        self.assertIn("at most 18 characters", autoname.SYSTEM_PROMPT)

    def test_default_namer_uses_its_own_system_prompt_and_no_tools(self):
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        out = os.path.join(self.tmp, "argv.json")
        with open(os.path.join(bindir, "claude"), "w") as f:
            f.write("#!/usr/bin/env python3\nimport json,sys\n"
                    "json.dump({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}, open(%r, 'w'))\nprint('Tab Autonamer')\n" % out)
        os.chmod(os.path.join(bindir, "claude"), 0o755)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
        got = autoname.default_namer("/home/a/api", "claude", "", "", requests=["rename tabs"], env=env)
        self.assertEqual(got, "Tab Autonamer")
        with open(out) as f:
            rec = json.load(f)
        argv = rec["argv"]
        self.assertEqual(argv[argv.index("--system-prompt") + 1], autoname.SYSTEM_PROMPT)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotIn("--bare", argv)          # --bare reads no OAuth login: a logged-in box would fail
        self.assertIn("- rename tabs", rec["stdin"])

    def test_the_namer_is_the_one_an_agent_declares(self):
        """a box whose only agent is a declared one (no Claude Code) names its tabs with that agent's NAMER: {prompt} as one word"""
        user = os.path.join(self.tmp, "user-addons")
        d = os.path.join(user, "fbot")
        os.makedirs(os.path.join(d, "agent"))
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=fbot\nDESCRIPTION="x"\nVERSION=1\nCOMMANDS="fbot"\n')
        with open(os.path.join(d, "agent", "agent.conf"), "w") as f:
            f.write('ID=fbot\nNAMER="fbot ask --model {model} {prompt}"\nNAMER_MODEL=tiny\n')
        bindir = os.path.join(self.tmp, "fbin")
        os.makedirs(bindir)
        out = os.path.join(self.tmp, "fbot.json")
        with open(os.path.join(bindir, "fbot"), "w") as f:
            f.write("#!/usr/bin/env python3\nimport json,sys\n"
                    "json.dump({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}, open(%r, 'w'))\nprint('Fake Title')\n" % out)
        os.chmod(os.path.join(bindir, "fbot"), 0o755)
        empty = os.path.join(self.tmp, "no-image-addons")
        os.makedirs(empty)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), SWARMBOX_TEST_IMAGE_ADDONS=empty,
                   SWARMBOX_TEST_USER_ADDONS=user, HOME=self.tmp)
        env.pop("SWARMBOX_AGENT", None)
        self.assertEqual(autoname.default_namer("/home/a/api", "fbot", "", "", requests=["fix the login"], env=env), "Fake Title")
        with open(out) as f:
            rec = json.load(f)
        self.assertEqual(rec["argv"][:3], ["ask", "--model", "tiny"])
        self.assertEqual(len(rec["argv"]), 4, "the prompt is one word")
        self.assertTrue(rec["argv"][3].startswith(autoname.SYSTEM_PROMPT))
        self.assertIn("- fix the login", rec["argv"][3])
        self.assertEqual(rec["stdin"], "", "with {prompt} nothing goes on standard input")
        env["SWARMBOX_TEST_USER_ADDONS"] = empty
        with self.assertRaises(autoname.NamerError) as cm:
            autoname.default_namer("/home/a/api", "fbot", "", "", env=env)
        self.assertIn("can name tabs", str(cm.exception))

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

        # worktree status (read-only), merge with clean=True, and remove all close the live tab
        st_out = json.loads(srv.t_worktree({"target": "t1", "action": "status"}))
        self.assertTrue(st_out["can_merge"])
        m_out = json.loads(srv.t_worktree({"target": "t1", "action": "merge", "clean": True}))
        self.assertTrue(m_out["cleaned"])
        self.assertEqual(tabs.closed, ["t1"])
        r_out = json.loads(srv.t_worktree({"target": "t1", "action": "remove"}))
        self.assertTrue(r_out["ok"])
        self.assertEqual(tabs.closed, ["t1", "t1"])


if __name__ == "__main__":
    unittest.main()
