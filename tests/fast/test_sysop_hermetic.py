"""Fast tests of the hermetic brain (docs/sysop-brain-design.md 3): what the brain gets and what it does not, run the way the service
runs it: resident (brain.Runtime, docs/sysop-resident-brain-design.md), the goal's MCP server hosted outside the sandbox (brain.McpHost)
behind the reconnecting proxy, the brain home, the environment by allowlist, the Landlock domain (without the suite's extra folder: only
the brain home and /dev), and the live log of the goal.

The brain is the fake claude of tests/support/fixtures/sysop (a scripted brain over the real MCP server); swarmbox-tabs is the fake of
sysop_support. No model, no herdr-core.

Run: python3 tests/fast/test_sysop_hermetic.py
"""
import json
import os
import socket
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import brain, events, history, ipc, landlock, mcpserver  # noqa: E402


class Hermetic(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.tabs = ss.FakeTabs(os.path.join(self.e.dir, "tabs.sock"))
        self.addCleanup(self.tabs.stop)
        self.pth = self.e.paths.make()
        self.gdir = os.path.join(self.pth.goals, "g1")
        os.mkdir(self.gdir, 0o700)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update({k: v for k, v in self.e.env.items() if k.startswith(("SB_", "SWARMBOX_"))})
        os.environ.pop("SWARMBOX_TEST_SANDBOX_DIRS", None)        # the real domain: the fake writes its records in the goal folder
        os.environ["PATH"] = self.e.env["PATH"]
        os.environ.update(self.tabs.cmd_env)
        # the fake writes its records where the brain's domain allows: its home (the goal folder is not the brain's any more)
        records = self.pth.brain_home
        os.makedirs(records, 0o700, exist_ok=True)
        self.log = os.path.join(records, "claude.log")
        self.out = os.path.join(records, "out.jsonl")
        os.environ.update({"SWARMBOX_TEST_FAKE_CLAUDE_LOG": self.log, "SWARMBOX_TEST_FAKE_CLAUDE_OUT": self.out})
        for patcher in (mock.patch.object(brain, "GRACE_AFTER_DONE", 0.2),):
            patcher.start()
            self.addCleanup(patcher.stop)

    def go(self, steps, sandbox=True, goal="do it"):
        p = os.path.join(self.gdir, "script.json")
        with open(p, "w") as f:
            json.dump(steps, f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = p
        cfg = self.e.cfg(max_seconds=30)
        ctx = os.path.join(self.gdir, "context.json")
        ipc.write_json(ctx, {"goal": "g1", "source": "cli", "goal_dir": self.gdir, "audit": self.pth.audit, "countdown": 0,
                             "max_steps": 0, "deadline": time.time() + 30})
        self.events = events.EventLog(os.path.join(self.gdir, "events.jsonl"))
        sock = self.pth.mcp_socket("g1")
        host = brain.McpHost(sock, brain.server_env(ctx, self.pth, ss.LIB), self.events)
        host.start()
        self.addCleanup(host.stop)
        self.sock = sock
        self.home = brain.prepare_home(self.pth.brain_home)
        opts = brain.options(cfg.brain)
        rt = brain.Runtime()
        self.addCleanup(rt.close)
        err = rt.ensure(cfg, opts, self.home, sock, self.pth, ss.LIB, "", sandbox=sandbox)
        if err:
            host.stop()
            self.events.close()
            return brain.Result("failed", err)
        res = rt.run_goal(cfg, goal, self.gdir, lambda: False, lambda: None, time.time() + 30, self.events, opts)
        host.stop()
        self.events.close()
        rt.close()
        return res

    def logged(self):
        with open(self.log) as f:
            return json.load(f)

    def records(self):
        try:
            with open(self.out) as f:
                return [json.loads(x) for x in f]
        except OSError:
            return []

    def test_the_brain_gets_its_own_login_and_home_and_nothing_else_of_the_service(self):
        os.environ.update({"CLAUDE_CODE_OAUTH_TOKEN": "tok", "GH_TOKEN": "other-secret", "OPENAI_API_KEY": "other-secret-2"})
        res = self.go([{"tool": "done", "args": {"summary": "ok"}}])
        self.assertEqual(res.outcome, "done", res.error)
        got = self.logged()
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", got["env_names"], "the agent's SECRET_ENV is its login")
        for name in ("GH_TOKEN", "OPENAI_API_KEY", "SB_RUN_DIR"):
            self.assertNotIn(name, got["env_names"], "%s is the service's, not the brain's" % name)
        self.assertEqual(got["home"], self.home["root"])
        self.assertEqual(got["tmpdir"], self.home["tmp"])
        self.assertEqual(got["claude_config_dir"], self.home["config"], "BRAIN_HOME_ENV points the CLI at its own configuration folder")
        self.assertEqual(got["cwd"], self.home["work"], "a fixed working directory: the session does not depend on the goal folder")
        self.assertEqual(oct(os.stat(self.home["root"]).st_mode & 0o777), "0o700")

    def test_the_preset_turns_off_user_and_project_settings_hooks_and_slash_commands(self):
        self.go([{"tool": "done", "args": {"summary": "ok"}}])
        argv = self.logged()["argv"]
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertIn("--disable-slash-commands", argv)
        with open(argv[argv.index("--settings") + 1]) as f:
            self.assertEqual(json.load(f), {"disableAllHooks": True}, "the settings file of the agent's read-only folder")
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_the_mcp_server_runs_outside_the_sandbox_and_its_events_join_the_brains(self):
        res = self.go([{"tool": "say", "args": {"text": "olhando as abas"}}, {"tool": "box_state"}, {"tool": "done", "args": {"summary": "pronto"}}])
        self.assertEqual(res.outcome, "done", res.error)
        self.assertEqual(res.summary, "pronto")
        got = events.read(os.path.join(self.gdir, "events.jsonl"))
        self.assertEqual([e["seq"] for e in got], list(range(1, len(got) + 1)))
        by = lambda t: [e for e in got if e["type"] == t]       # noqa: E731
        starts = by("action.start")
        self.assertEqual([(e["block"], e["fn"]) for e in starts], [("toolu_fake1_1", "say"), ("toolu_fake1_2", "box_state"), ("toolu_fake1_3", "done")])
        self.assertEqual([(e["id"], e["fn"]) for e in by("call")], [("toolu_fake1_1", "say"), ("toolu_fake1_2", "box_state"), ("toolu_fake1_3", "done")],
                         "the MCP server got the CLI's tool-use id: the call joins its block of the stream exactly")
        self.assertTrue(all(e["ok"] for e in by("call.end")))
        self.assertEqual("".join(e["text"] for e in by("say.delta")), "olhando as abas", "the say streamed before it ran")
        self.assertEqual([e["text"] for e in by("say")], ["olhando as abas"])
        self.assertEqual([e["summary"] for e in by("done")], ["pronto"])
        first_delta = next(e["seq"] for e in got if e["type"] == "say.delta")
        self.assertLess(first_delta, by("call")[0]["seq"], "the text is seen before the call runs")
        # the server wrote the audit of the box (state/sysop/events.jsonl): a folder the brain's domain does not allow
        with open(self.pth.audit) as f:
            self.assertTrue(any('"box_state"' in line for line in f))
        self.assertFalse(os.path.exists(self.sock), "the socket is gone once the brain connected")

    @unittest.skipUnless(landlock.abi(), "Landlock is not available in this kernel or container")
    def test_the_sandbox_denies_writes_outside_the_brain_home(self):
        outside = os.path.join(self.e.dir, "outside.txt")
        res = self.go([{"write": outside}, {"write": os.path.join(self.pth.brain_home, "work", "inside.txt")},
                       {"write": os.path.join(self.gdir, "goal.txt")}, {"tool": "done", "args": {"summary": "ok"}}])
        self.assertEqual(res.outcome, "done", res.error)
        w = {os.path.basename(r["write"]): r for r in self.records() if "write" in r}
        self.assertFalse(w["outside.txt"]["ok"])
        self.assertIn("ermission", w["outside.txt"]["error"])
        self.assertFalse(os.path.exists(outside))
        self.assertTrue(w["inside.txt"]["ok"])
        self.assertFalse(w["goal.txt"]["ok"], "the goal folder changes at each goal: the resident brain's domain does not hold it")

    def test_with_the_sandbox_off_the_brain_writes_where_it_likes(self):
        outside = os.path.join(self.e.dir, "outside.txt")
        res = self.go([{"write": outside}, {"tool": "done", "args": {"summary": "ok"}}], sandbox=False)
        self.assertEqual(res.outcome, "done", res.error)
        self.assertTrue(os.path.exists(outside))

    def test_an_addon_shim_is_resolved_to_the_real_program_outside_the_sandbox(self):
        """found in the nested box: the brain's command is a SwarmBox shim (install on first use, then exec), which inside the sandbox can
        neither take the addon lock in /tmp/swarmbox nor find the user's install (HOME is the brain home). The service resolves it first,
        installing the addon when it has none yet."""
        bindir = os.path.join(self.e.dir, "shimbin")
        os.makedirs(bindir)
        shim = os.path.join(bindir, "swarmbox-shim")
        with open(shim, "w") as f:
            f.write("#!/bin/sh\necho 'the shim ran inside the sandbox' >&2\nexit 69\n")
        os.chmod(shim, 0o755)
        os.symlink(shim, os.path.join(bindir, "claude"))
        calls = os.path.join(self.e.dir, "addon-calls")
        with open(os.path.join(bindir, "swarmbox-addon"), "w") as f:
            f.write("#!/bin/sh\necho \"$*\" >> %s\n"
                    "case $1 in\n"
                    "  install) touch %s.installed ;;\n"
                    "  where) [ -e %s.installed ] && [ \"$2 $3\" = 'claude claude' ] && echo %s && exit 0; exit 1 ;;\n"
                    "esac\n" % (calls, calls, calls, os.path.join(ss.FAKE_BIN, "claude")))
        os.chmod(os.path.join(bindir, "swarmbox-addon"), 0o755)
        os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
        res = self.go([{"tool": "done", "args": {"summary": "ok"}}])
        self.assertEqual(res.outcome, "done", res.error)
        with open(calls) as f:
            self.assertEqual(f.read().split("\n")[:3], ["where claude claude", "install claude", "where claude claude"])
        self.assertTrue(os.path.exists(self.log), "the real program ran")
        self.assertEqual(brain.real_program("/usr/bin/env", {"addon": "claude"}), "/usr/bin/env", "a program that is not a shim runs as it is")

    def test_a_hermetic_brain_without_its_token_says_how_to_log_in(self):
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "notloggedin"
        res = self.go([])
        self.assertEqual(res.outcome, "failed")
        self.assertIn("not logged in", res.error)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", res.error)
        self.assertIn("not with a login made in a tab", res.error)


class McpHostSocket(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()

    def test_one_connection_only_and_a_socket_path_too_long_is_refused(self):
        gdir = os.path.join(self.pth.goals, "g1")
        os.makedirs(gdir, 0o700)
        ctx = os.path.join(gdir, "context.json")
        ipc.write_json(ctx, {"goal": "g1", "source": "cli", "goal_dir": gdir, "audit": self.pth.audit})
        sock = self.pth.mcp_socket("g1")
        host = brain.McpHost(sock, brain.server_env(ctx, self.pth, ss.LIB, base=dict(os.environ, **self.e.env)))
        host.start()
        self.addCleanup(host.stop)
        self.assertEqual(oct(os.stat(sock).st_mode & 0o777), "0o600")
        a = socket.socket(socket.AF_UNIX)
        a.connect(sock)
        self.addCleanup(a.close)
        a.sendall(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        self.assertIn(b'"id": 1', a.recv(4096))
        self.assertTrue(ss.wait_for(lambda: not os.path.exists(sock), 3))
        b = socket.socket(socket.AF_UNIX)
        self.addCleanup(b.close)
        with self.assertRaises(OSError):
            b.connect(sock)
        with self.assertRaises(brain.McpHostError):
            brain.McpHost("/tmp/" + "x" * 120 + ".sock", {}).start()


class ReconnectingProxy(unittest.TestCase):
    """mcp-proxy --reconnect (docs/sysop-resident-brain-design.md 3): one brain, a server per goal on the same socket path."""

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()
        self.sock = self.pth.mcp_socket("brain")

    def host(self, gid):
        gdir = os.path.join(self.pth.goals, gid)
        os.makedirs(gdir, 0o700)
        ctx = os.path.join(gdir, "context.json")
        ipc.write_json(ctx, {"goal": gid, "source": "cli", "goal_dir": gdir, "audit": self.pth.audit})
        h = brain.McpHost(self.sock, brain.server_env(ctx, self.pth, ss.LIB, base=dict(os.environ, **self.e.env)))
        h.start()
        self.addCleanup(h.stop)
        return h

    def proxy(self):
        import subprocess
        p = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_sysop", "mcp-proxy", "--reconnect", self.sock], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=ss.LIB))
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdin.close(), p.stdout.close()))
        return p

    @staticmethod
    def ask(p, rid, method="tools/list"):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method}).encode() + b"\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    def test_the_proxy_follows_the_server_of_each_goal_and_answers_for_none(self):
        p = self.proxy()
        none = self.ask(p, 1)
        self.assertEqual(none["error"]["message"], mcpserver.NO_GOAL, "no goal: the proxy answers, the brain never hangs")
        a = self.host("g1")
        self.assertIn("tools", self.ask(p, 2)["result"])
        a.stop()
        b = self.host("g2")
        self.assertIn("tools", self.ask(p, 3)["result"], "the same proxy reaches the next goal's server, with no handshake of its own")
        self.assertTrue(ss.wait_for(lambda: not os.path.exists(self.sock), 3), "each server still takes one connection only")
        b.stop()
        self.assertEqual(self.ask(p, 4)["error"]["message"], mcpserver.NO_GOAL)
        self.assertIsNone(p.poll(), "the proxy outlives the servers: the brain keeps its MCP server")


class Resident(unittest.TestCase):
    """The resident brain (brain.Runtime) with the fake claude in its resident mode, goal after goal, as the service runs it."""

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.tabs = ss.FakeTabs(os.path.join(self.e.dir, "tabs.sock"))
        self.addCleanup(self.tabs.stop)
        self.pth = self.e.paths.make()
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update({k: v for k, v in self.e.env.items() if k.startswith(("SB_", "SWARMBOX_"))})
        os.environ["PATH"] = self.e.env["PATH"]
        os.environ.update(self.tabs.cmd_env)
        self.log = os.path.join(self.e.dir, "claude.log")
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_LOG"] = self.log
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SESSION"] = "s-1"
        p = os.path.join(self.e.dir, "script.json")
        with open(p, "w") as f:
            json.dump([{"tool": "say", "args": {"text": "hi"}}, {"tool": "done", "args": {"summary": "ok"}}], f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = p
        self.cfg = self.e.cfg(max_seconds=30)
        self.opts = brain.options(self.cfg.brain)
        self.home = brain.prepare_home(self.pth.brain_home)
        self.sock = self.pth.mcp_socket("brain")
        self.rt = brain.Runtime()
        self.addCleanup(self.rt.close)
        self.n = 0
        for patcher in (mock.patch.object(brain, "GRACE_AFTER_DONE", 0.1), mock.patch.object(brain, "INTERRUPT_WAIT", 0.5)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def goal(self, sid="", stop_after=None):
        self.n += 1
        gid = "g%d" % self.n
        gdir = os.path.join(self.pth.goals, gid)
        os.makedirs(gdir, 0o700)
        ctx = os.path.join(gdir, "context.json")
        ipc.write_json(ctx, {"goal": gid, "source": "cli", "goal_dir": gdir, "audit": self.pth.audit, "countdown": 0,
                             "deadline": time.time() + 30})
        ev = events.EventLog(os.path.join(gdir, "events.jsonl"))
        host = brain.McpHost(self.sock, brain.server_env(ctx, self.pth, ss.LIB), ev)
        host.start()
        try:
            err = self.rt.ensure(self.cfg, self.opts, self.home, self.sock, self.pth, ss.LIB, sid)
            self.assertIsNone(err)
            t0 = time.time()
            stop = (lambda: time.time() - t0 > stop_after) if stop_after else (lambda: False)
            return self.rt.run_goal(self.cfg, "goal %d" % self.n, gdir, stop, lambda: None, time.time() + 30, ev, self.opts), gdir
        finally:
            host.stop()
            ev.close()

    def logged(self):
        with open(self.log) as f:
            return json.load(f)

    def test_two_goals_are_two_turns_of_one_process_and_each_pays_its_own_cost(self):
        a, adir = self.goal()
        first = self.logged()
        b, bdir = self.goal("s-1")
        second = self.logged()
        self.assertEqual((a.outcome, a.summary, b.outcome, b.summary), ("done", "ok", "done", "ok"))
        self.assertEqual((first["pid"], second["goals"]), (second["pid"], 2), "one process, two turns")
        self.assertNotIn("--resume", second["argv"])
        self.assertEqual((a.cost, b.cost), (0.0012, 0.0012), "the CLI reports a total: each goal gets the difference")
        self.assertEqual([e["cost"] for e in events.read(os.path.join(bdir, "events.jsonl")) if e["type"] == "usage"], [0.0012],
                         "the live log of a goal says its own cost too")
        self.assertEqual(b.session_id, "s-1")
        for d in (adir, bdir):
            with open(os.path.join(d, "stream.jsonl")) as f:
                self.assertEqual(sum('"type": "result"' in line for line in f), 1, "each goal keeps the lines of its own turn")

    def test_a_new_conversation_starts_a_new_process_and_a_dead_one_resumes_the_session(self):
        self.goal()
        pid = self.logged()["pid"]
        self.goal("")                 # + New: the conversation has no session, the live process does
        fresh = self.logged()
        self.assertNotEqual(fresh["pid"], pid)
        self.assertNotIn("--resume", fresh["argv"])
        os.kill(fresh["pid"], 9)
        self.assertTrue(ss.wait_for(lambda: not self.rt.alive(), 5))
        self.goal("s-1")
        again = self.logged()
        self.assertNotEqual(again["pid"], fresh["pid"])
        self.assertEqual(again["argv"][again["argv"].index("--resume") + 1], "s-1")

    def test_a_session_the_cli_refuses_to_resume_is_not_given_back(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "badresume"
        res, _ = self.goal("gone-1")
        self.assertEqual(res.outcome, "failed")
        self.assertIn("No conversation found", res.error, "the words that make the service clear the session")
        self.assertEqual(res.session_id, "", "never saved again: every next goal would fail on it")

    def test_a_brain_that_dies_during_a_goal_fails_it_with_its_last_words(self):
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "crash-after"
        self.assertEqual(self.goal()[0].outcome, "done")
        res, _ = self.goal("s-1")
        self.assertEqual(res.outcome, "failed")
        self.assertIn("exited with status 3: boom: the brain crashed", res.error)
        self.assertFalse(self.rt.alive())

    def test_stop_interrupts_the_turn_and_a_brain_that_ignores_it_is_killed(self):
        with open(os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"], "w") as f:
            json.dump([{"sleep": 30}], f)
        t0 = time.time()
        res, _ = self.goal(stop_after=0.3)
        self.assertEqual(res.outcome, "stopped")
        self.assertLess(time.time() - t0, 5)
        self.assertTrue(self.rt.alive(), "the interrupt ended the turn, the process stays")
        self.rt.close()
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_MODE"] = "slow-interrupt"
        res, _ = self.goal(stop_after=0.3)
        self.assertEqual(res.outcome, "stopped")
        self.assertFalse(self.rt.alive(), "no end of the turn within INTERRUPT_WAIT: killed")


class SessionAndStopNote(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths.make()

    def test_a_session_saved_before_the_brain_home_is_not_resumed(self):
        ipc.write_json(os.path.join(self.pth.state, "conversation.json"), {"since": 1, "session_id": "old-one"})
        self.assertEqual(history.session_id(self.pth), "", "an id of the user's own configuration folder: not found in the brain home")
        history.save_session_id(self.pth, "new-one")
        self.assertEqual(history.session_id(self.pth), "new-one")
        history.save_stop_note(self.pth, "- `run` in t1: ls (ran)")
        self.assertEqual(history.stop_note(self.pth), "- `run` in t1: ls (ran)")
        self.assertEqual(ipc.read_json(os.path.join(self.pth.state, "conversation.json"))["since"], 1)
        history.save_stop_note(self.pth, "")
        self.assertEqual(history.stop_note(self.pth), "")

    def test_the_note_names_the_calls_that_ran(self):
        note = history.describe_calls([{"tool": "say", "args": {"text": "x"}}, {"tool": "run", "args": {"tab": "t1", "command": "pytest -q"}},
                                       {"tool": "input", "args": {"text": "{Esc}"}, "is_error": True}])
        self.assertEqual(note, "- `run` in t1: pytest -q (ran)\n- `input`: {Esc} (error)")


class Options(unittest.TestCase):
    def test_the_agent_declares_how_its_brain_runs(self):
        o = brain.options("claude")
        self.assertEqual((o["format"], o["resume"], o["stop"], o["home_env"]), ("claude-stream-json", "--resume {session_id}", "INT", "CLAUDE_CONFIG_DIR"))
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", o["secrets"])
        self.assertTrue(os.path.isfile(os.path.join(o["agent_dir"], "brain-settings.json")))
        self.assertTrue(o["login"].search("Not logged in"))
        x = brain.options("some-program --mcp {mcp_config}")
        self.assertEqual((x["format"], x["resume"], x["stop"], x["home_env"], x["secrets"]), ("text", "", "TERM", "", []))
        self.assertEqual(brain.options("some-program --output-format stream-json {mcp_config}")["format"], "claude-stream-json")

    def test_the_environment_is_built_not_inherited(self):
        home = {"root": "/b", "config": "/b/config", "tmp": "/b/tmp", "work": "/b/work"}
        env = brain.environment({"FOO": "1"}, {"secrets": ["MY_TOKEN"], "home_env": "CFG"}, home,
                                base={"PATH": "/bin", "MY_TOKEN": "t", "AWS_SECRET": "no", "LANG": "pt_BR.UTF-8", "HOME": "/home/u"})
        self.assertEqual(env, {"PATH": "/bin", "LANG": "pt_BR.UTF-8", "MY_TOKEN": "t", "HOME": "/b", "TMPDIR": "/b/tmp", "CFG": "/b/config", "FOO": "1"})


if __name__ == "__main__":
    unittest.main()
