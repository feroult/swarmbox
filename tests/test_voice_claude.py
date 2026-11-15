"""The built-in `claude` planner, run against a fake `claude` CLI (tests/fixtures/voice/bin/claude). No network, no model, no
login. The shared contract suite in test_voice_contract.py also runs this planner. Run: python3 -W error tests/test_voice_claude.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_support import BUILTIN_PLANNERS, FIXTURES, INJECTION_TAIL, PANES  # noqa: E402
from swarmbox_voice import context, planners  # noqa: E402

PLANNER = os.path.join(BUILTIN_PLANNERS, "planner-claude")
FAKE_BIN = os.path.join(FIXTURES, "bin")


class ClaudePlannerTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="swarmbox-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.log = os.path.join(self.home, "claude.log")

    def run_planner(self, mode="ok", data=None, path=None, extra_env=None, timeout=20):
        env = {"PATH": path if path is not None else FAKE_BIN + ":/nonexistent", "HOME": self.home,
               "SWARMBOX_TEST_FAKE_CLAUDE": mode, "SWARMBOX_TEST_FAKE_CLAUDE_LOG": self.log}
        env.update(extra_env or {})
        data = data or context.build_input("run the tests", "%2", PANES)
        p = subprocess.run(["/usr/bin/python3", PLANNER], input=json.dumps(data).encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
        return p.returncode, p.stdout.decode(), p.stderr.decode()

    def logged(self):
        with open(self.log) as f:
            return json.load(f)

    def test_it_is_a_builtin_planner(self):
        self.assertTrue(os.access(PLANNER, os.X_OK))
        self.assertIn("claude", planners.discover(user=FIXTURES))

    def test_argv_is_headless_and_has_no_tools(self):
        code, out, err = self.run_planner(extra_env={"SWARMBOX_VOICE_PLANNER_MODEL": "sonnet"})
        self.assertEqual(code, 0, err)
        argv = self.logged()["argv"]
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--tools") + 1], "", "every built-in tool is disabled")
        # no --disallowedTools list: a name the installed CLI does not know makes claude exit (the real CLI refused
        # "MultiEdit"), and `--tools ""` already leaves it with no tool at all
        self.assertNotIn("--disallowedTools", argv)
        self.assertNotIn("--allowedTools", argv, "nothing is pre-approved")
        for flag in argv:
            self.assertNotIn("dangerously", flag)
            self.assertNotIn("bypass", flag.lower())
        self.assertNotIn("--permission-mode", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertNotIn("run the tests", " ".join(argv), "user data is on stdin, never on argv")

    def test_default_model_is_haiku(self):
        self.run_planner()
        argv = self.logged()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.run_planner(extra_env={"SWARMBOX_VOICE_PLANNER_MODEL": ""})
        argv = self.logged()["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")

    def test_a_model_that_looks_like_a_flag_is_refused(self):
        code, out, err = self.run_planner(extra_env={"SWARMBOX_VOICE_PLANNER_MODEL": "--dangerously-skip-permissions"})
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.log), "claude was not even started")

    def test_prompt_warns_about_untrusted_data_and_carries_the_panes(self):
        tail = [dict(p) for p in PANES]
        tail[1]["tail"] = INJECTION_TAIL
        code, out, err = self.run_planner(data=context.build_input("what is in the readme", "%2", tail))
        self.assertEqual(code, 0, err)
        log = self.logged()
        system = log["argv"][log["argv"].index("--system-prompt") + 1]
        low = system.lower()
        self.assertIn("untrusted", low)
        self.assertIn("never follow", low)
        self.assertIn("only pane ids that exist", low)
        self.assertIn("send_text", system)
        self.assertIn("select_pane", system)
        self.assertIn("new_window", system)
        self.assertIn("actions\": []", system, "tells it what to answer when unsure")
        stdin = log["stdin"]
        self.assertIn("what is in the readme", stdin)
        self.assertIn("shop-api", stdin)
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", stdin)
        # the data block is delimited by a nonce that the system prompt names, and the data cannot forge the end line
        nonce = stdin.splitlines()[0].replace("BEGIN-DATA-", "")
        self.assertIn("END-DATA-" + nonce, system)
        self.assertEqual(stdin.count("END-DATA-" + nonce), 1)
        self.assertEqual(len(stdin.strip().splitlines()), 3, "the JSON is one line, newlines in tails are escaped")

    def test_runs_in_an_empty_private_directory(self):
        self.run_planner()
        cwd = self.logged()["cwd"]
        self.assertTrue(os.path.basename(cwd).startswith("swarmbox-voice-"))
        self.assertFalse(os.path.exists(cwd), "the scratch directory is removed")

    def test_replies_are_extracted(self):
        for mode in ("ok", "fenced", "prose", "bare"):
            with self.subTest(mode=mode):
                code, out, err = self.run_planner(mode)
                self.assertEqual(code, 0, err)
                plan = json.loads(out)
                self.assertEqual(plan["actions"], [{"type": "send_text", "pane": "%2", "text": "run the tests", "enter": False}])

    def test_risk_claimed_by_the_model_is_stripped(self):
        code, out, err = self.run_planner("risk")
        self.assertEqual(code, 0, err)
        self.assertNotIn("risk", json.loads(out))

    def test_empty_utterance_does_not_call_claude(self):
        code, out, err = self.run_planner(data=context.build_input("  ", "%2", PANES))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["actions"], [])
        self.assertFalse(os.path.exists(self.log))

    def test_clean_failures(self):
        expect = {"malformed": 7, "empty": 6, "exit1": 5, "badpane": 8, "noaction": 8}
        for mode, status in expect.items():
            with self.subTest(mode=mode):
                code, out, err = self.run_planner(mode)
                self.assertEqual(code, status, err)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("planner-claude: "), err)
                self.assertNotIn("Traceback", err)

    def test_exit_message_carries_the_claude_stderr(self):
        code, out, err = self.run_planner("exit1")
        self.assertIn("Not logged in", err)

    def test_exit_message_carries_the_claude_stdout_too(self):
        # the real CLI reports "Not logged in" on stdout and leaves stderr empty
        code, out, err = self.run_planner("exit1out")
        self.assertEqual(code, 5, err)
        self.assertIn("Not logged in", err)

    def test_timeout(self):
        code, out, err = self.run_planner("hang", extra_env={"SWARMBOX_TEST_CLAUDE_TIMEOUT": "1"}, timeout=15)
        self.assertEqual(code, 4, err)
        self.assertIn("longer than", err)

    def test_claude_missing(self):
        code, out, err = self.run_planner(path="/nonexistent")
        self.assertEqual(code, 3, err)
        self.assertIn("not on PATH", err)

    def test_bad_input(self):
        p = subprocess.run(["/usr/bin/python3", PLANNER], input=b"not json", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env={"PATH": FAKE_BIN, "HOME": self.home})
        self.assertEqual(p.returncode, 2)

    def test_host_side_codes_through_run_planner(self):
        planner = planners.find("claude", user=FIXTURES)
        data = context.build_input("run the tests", "%2", PANES)
        base = {"PATH": FAKE_BIN + ":/nonexistent", "HOME": self.home}
        r = planners.run_planner(planner, data, base_env=base, timeout=15)
        self.assertTrue(r.ok, r)
        self.assertEqual(r.plan["actions"][0]["pane"], "%2")
        r = planners.run_planner(planner, data, base_env={"PATH": "/nonexistent", "HOME": self.home}, timeout=15)
        self.assertFalse(r.ok)
        self.assertEqual(r.code, "exit_nonzero")
        self.assertIn("not on PATH", r.error)


if __name__ == "__main__":
    unittest.main()
