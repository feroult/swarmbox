"""The sysop against the REAL bus process and a REAL tmux (an isolated server, -L name under a private TMUX_TMPDIR), with the fake claude scripted
to call the MCP tools and the stand-in agent TUI of tests/fixtures/bus/fake_agent.py. No model, no network. Covers: goal -> brain -> MCP ->
bus -> tab typing; the policy holding a high-risk run (and an approval that sends it); the veto; the stop; errors of the driver as results.

Run in Podman only (a developer's machine may have a tmux of its own that these tests must never touch): they skip unless tmux is installed
AND SWARMBOX_TEST_REAL_TMUX=1 is set, which only this command does:

  podman run --rm -e SWARMBOX_TEST_REAL_TMUX=1 --userns=keep-id:uid=1000,gid=1000 -v $PWD:/src:ro --tmpfs /work:rw,exec,mode=1777,size=1g IMAGE \\
      bash -c 'cp -r /src /work/repo && cd /work/repo && HOME=/work/home python3 -W error tests/test_sysop_real.py'
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402
from bus_support import Process  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_sysop import audit, busclient, ipc, service  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "bus")
HAVE = bool(shutil.which("tmux")) and os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"      # the podman command below sets it: never on a machine with a tmux of its own


class Panel(threading.Thread):
    def __init__(self, goals_dir, decide):
        threading.Thread.__init__(self, daemon=True)
        self.dir, self.decide, self.stop_flag, self.seen = goals_dir, decide, False, []
        self.start()

    def run(self):
        done = set()
        while not self.stop_flag:
            try:
                for g in os.listdir(self.dir):
                    p = ipc.read_json(os.path.join(self.dir, g, "pending_action.json"))
                    if p and p["id"] + g not in done:
                        done.add(p["id"] + g)
                        self.seen.append(p)
                        d = self.decide(p)
                        if d:
                            ipc.write_json(os.path.join(self.dir, g, "decision.json"), {"id": p["id"], "decision": d, "by": "panel", "word": "run"})
            except OSError:
                pass
            time.sleep(0.02)


@unittest.skipUnless(HAVE, "needs tmux and a container (run it in Podman, see the docstring)")
class Real(unittest.TestCase):
    def setUp(self):
        self.e = ss.Env()
        self.e.env["SB_BUS_SOCKET"] = os.path.join(self.e.dir, "b.sock")
        self.tmux_sock = "sysop%d" % os.getpid()
        self.tmpdir = os.path.join(self.e.dir, "tmx")
        os.mkdir(self.tmpdir)
        self.saved = dict(os.environ)
        self.addCleanup(self.cleanup)
        shell = os.path.join(self.e.dir, "shell")
        with open(shell, "w") as f:
            f.write("#!/bin/sh\nPS1='$ '\nexport PS1\nexec bash --norc --noprofile \"$@\"\n")
        os.chmod(shell, 0o755)
        # a program named `claude` (what the policy and the driver see in pane_current_command): a link to python running the stand-in agent
        os.mkdir(os.path.join(self.e.dir, "bin"))
        self.claude = os.path.join(self.e.dir, "bin", "claude")
        os.symlink(shutil.which("python3"), self.claude)
        self.env = dict(os.environ, TMUX_TMPDIR=self.tmpdir, SHELL=shell, HOME=self.e.env["HOME"])
        for k in ("TMUX", "STARSHIP_SHELL", "PROMPT_COMMAND", "BASH_ENV", "ENV"):
            self.env.pop(k, None)
        os.environ.update(self.e.env)
        os.environ["TMUX_TMPDIR"] = self.tmpdir
        os.environ.pop("TMUX", None)
        self.tm("new-session", "-d", "-s", "main", "-n", "shell", "-x", "100", "-y", "30")
        self.agent_pane = self.tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-n", "agent", "%s %s/fake_agent.py" % (self.claude, FIX))
        self.sh = self.window("shell")
        self.ag = self.window("agent")
        self.assertTrue(ss.wait_for(lambda: "auto mode on" in self.text(self.ag), 10), self.text(self.ag))
        self.bus = Process(env_extra={"SB_BUS_TMUX_SOCKET": self.tmux_sock, "TMUX_TMPDIR": self.tmpdir, "SB_BUS_SOCKET": self.e.env["SB_BUS_SOCKET"]}, driver="tmux")
        self.bus.path = self.e.env["SB_BUS_SOCKET"]
        self.bus.start(wait=False)
        self.addCleanup(self.bus.close)
        self.assertTrue(ss.wait_for(lambda: self.bus_up(), 15), self.bus.log())
        self.victim = os.path.join(self.e.dir, "victim")
        os.mkdir(self.victim)
        self.out = os.path.join(self.e.dir, "out.jsonl")
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_OUT"] = self.out
        self.panel = None
        self.svc = None

    def bus_up(self):
        try:
            busclient.Bus(self.e.env["SB_BUS_SOCKET"]).ping()
            return True
        except busclient.BusError:
            return False

    def cleanup(self):
        if self.panel:
            self.panel.stop_flag = True
        if self.svc:
            self.svc.shutdown()
            self.thread.join(20)
        subprocess.run(["tmux", "-L", self.tmux_sock, "kill-server"], env=self.env, capture_output=True)
        os.environ.clear()
        os.environ.update(self.saved)
        self.e.cleanup()

    def tm(self, *a):
        p = subprocess.run(["tmux", "-L", self.tmux_sock] + [str(x) for x in a], capture_output=True, text=True, env=self.env)
        return (p.stdout + p.stderr).rstrip("\n")

    def window(self, name):
        return self.tm("display-message", "-p", "-t", "main:" + name, "#{window_id}")

    def text(self, win):
        return self.tm("capture-pane", "-p", "-J", "-t", win)

    def start(self, steps, **cfg):
        path = os.path.join(self.e.dir, "script.json")
        with open(path, "w") as f:
            json.dump(steps, f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = path
        self.svc = service.Service(self.e.cfg(**dict({"countdown": 0.3, "approval_timeout": 2}, **cfg)), self.e.paths, backoff=(0.1, 0.5), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.assertTrue(self.svc.wait_ready(10))
        self.assertTrue(ss.wait_for(lambda: self.cli("status", "-q").returncode == 0 and self.svc.bus_state == "connected", 10))

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop"] + list(args), env=dict(os.environ, PYTHONPATH=ss.LIB), capture_output=True, text=True, timeout=120)

    def goal(self, text="x", source="cli", wait=True):
        p = self.cli("goal", "--source", source, *(["--wait"] if wait else []), text)
        return p

    def results(self):
        try:
            with open(self.out) as f:
                return [json.loads(x) for x in f]
        except OSError:
            return []

    def state(self, gid):
        return ipc.read_json(os.path.join(self.e.paths.goals, gid, "state.json"))

    def decisions(self):
        return [e["decision"] for e in audit.read(self.e.paths.audit) if e["event"] == "decision"]


class Typing(Real):
    def test_a_goal_types_a_command_in_the_active_tab_and_reads_the_result(self):
        self.start([{"tool": "list_tabs"}, {"tool": "run", "args": {"command": "echo hello-from-the-sysop"}}, {"tool": "say", "args": {"text": "ran it"}},
                    {"tool": "done", "args": {"summary": "echoed"}}])
        p = self.goal("echo hello", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("done: echoed", p.stdout)
        self.assertIn("hello-from-the-sysop", self.text(self.sh))
        res = self.results()
        self.assertEqual([r["tool"] for r in res], ["list_tabs", "run", "say", "done"])
        self.assertFalse(res[1]["is_error"], res[1]["text"])
        self.assertIn("hello-from-the-sysop\n", res[1]["text"], "run answers with the settled screen, output included")
        tabs = json.loads(res[0]["text"])
        self.assertEqual({t["label"]: t["cmd"] for t in tabs}, {"0:shell": "bash", "1:agent": "claude"})
        self.assertEqual([t["active"] for t in tabs], [True, False])
        self.assertEqual(self.decisions(), ["waiting", "allowed"], "a low-risk command went through the countdown")

    def test_a_prompt_for_the_agent_tab_is_typed_and_submitted(self):
        self.start([{"tool": "run", "args": {"tab": "agent", "command": "please list the files"}}, {"tool": "done", "args": {"summary": "asked"}}])
        p = self.goal("ask the agent")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(ss.wait_for(lambda: "ANSWER please list the files" in self.text(self.ag), 10), self.text(self.ag))
        res = self.results()
        self.assertFalse(res[0]["is_error"], res[0]["text"])
        self.assertEqual(self.decisions(), ["waiting", "allowed"])

    def test_input_with_keys_into_the_shell(self):
        self.start([{"tool": "input", "args": {"tab": "shell", "text": "echo ab{Left}X{Enter}"}}, {"tool": "done", "args": {"summary": "x"}}], autonomy="auto")
        p = self.goal("keys")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        res = self.results()
        self.assertFalse(res[0]["is_error"], res[0]["text"])
        # the line was edited with {Left}, so it was rated medium (held for a countdown in auto)
        self.assertIn("aXb", self.text(self.sh))

    def test_driver_errors_reach_the_model_as_results(self):
        dlg = self.tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-n", "dialog", "env FAKE_AGENT_DIALOG=1 %s %s/fake_agent.py" % (self.claude, FIX))
        wid = self.window("dialog")
        self.assertTrue(ss.wait_for(lambda: "Do you want to" in self.text(wid), 10))
        self.start([{"tool": "run", "args": {"tab": wid, "command": "hello"}}, {"tool": "run", "args": {"tab": "agent", "command": "first"}},
                    {"tool": "run", "args": {"tab": "agent", "command": "second"}}, {"tool": "run", "args": {"tab": "@999", "command": "x"}},
                    {"tool": "done", "args": {"summary": "x"}}], countdown=0)
        p = self.goal("errors")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        res = self.results()
        self.assertTrue(res[0]["is_error"])
        self.assertIn("dialog_open", res[0]["text"])
        self.assertFalse(res[1]["is_error"], res[1]["text"])
        self.assertTrue(res[2]["is_error"])
        self.assertIn("busy_tab", res[2]["text"])
        self.assertTrue(res[3]["is_error"])
        self.assertIn("no_such_tab", res[3]["text"])
        self.assertNotIn("second", self.text(self.ag))


class Policy(Real):
    def test_a_high_risk_run_is_held_and_never_typed_without_approval(self):
        self.start([{"tool": "run", "args": {"command": "rm -rf %s" % self.victim}}, {"tool": "say", "args": {"text": "I was not allowed to"}},
                    {"tool": "done", "args": {"summary": "refused"}}], approval_timeout=1)
        t0 = time.time()
        p = self.goal("delete the victim folder", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertGreaterEqual(time.time() - t0, 1.0)
        self.assertTrue(os.path.isdir(self.victim), "nothing was deleted")
        self.assertNotIn("victim", self.text(self.sh), "not even typed")
        res = self.results()
        self.assertTrue(res[0]["is_error"])
        self.assertIn("not approved in time", res[0]["text"])
        self.assertEqual(self.decisions(), ["waiting", "timed_out"])

    def test_the_same_run_with_an_approval_from_the_panel_goes(self):
        self.panel = Panel(self.e.paths.goals, lambda p: "approve")
        self.start([{"tool": "run", "args": {"command": "rm -rf %s" % self.victim}}, {"tool": "done", "args": {"summary": "removed"}}])
        p = self.goal("delete the victim folder", "panel")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(ss.wait_for(lambda: not os.path.isdir(self.victim), 10), self.text(self.sh))
        self.assertEqual(self.panel.seen[0]["risk"], "high")
        self.assertEqual(self.panel.seen[0]["mode"], "approve")

    def test_a_slash_command_for_the_agent_is_blocked_before_the_bus(self):
        self.start([{"tool": "run", "args": {"tab": "agent", "command": "/exit"}}, {"tool": "done", "args": {"summary": "blocked"}}])
        before = self.text(self.ag)
        p = self.goal("exit the agent", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        res = self.results()
        self.assertTrue(res[0]["is_error"])
        self.assertIn("blocked by the policy", res[0]["text"])
        self.assertEqual(self.text(self.ag), before)
        self.assertEqual(self.decisions(), ["blocked"])

    def test_the_veto_stops_a_low_risk_action(self):
        marker = os.path.join(self.e.dir, "marker")
        self.panel = Panel(self.e.paths.goals, lambda p: "veto")
        self.start([{"tool": "run", "args": {"command": "touch %s" % marker}}, {"tool": "done", "args": {"summary": "vetoed"}}], countdown=3)
        t0 = time.time()
        p = self.goal("make the marker", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertLess(time.time() - t0, 3, "the veto ended the countdown")
        time.sleep(0.5)
        self.assertFalse(os.path.exists(marker))
        self.assertNotIn("marker", self.text(self.sh))
        self.assertIn("vetoed by the user", self.results()[0]["text"])
        self.assertEqual(self.panel.seen[0]["mode"], "veto")

    def test_without_a_veto_the_countdown_sends_it(self):
        marker = os.path.join(self.e.dir, "marker")
        self.start([{"tool": "run", "args": {"command": "touch %s" % marker}}, {"tool": "done", "args": {"summary": "ok"}}], countdown=1)
        t0 = time.time()
        p = self.goal("make the marker", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertGreaterEqual(time.time() - t0, 1.0)
        self.assertTrue(ss.wait_for(lambda: os.path.exists(marker), 5))

    def test_a_command_typed_in_parts_is_held_when_it_completes(self):
        self.start([{"tool": "input", "args": {"tab": "shell", "text": "r"}}, {"tool": "input", "args": {"tab": "shell", "text": "m -rf %s{Enter}" % self.victim}},
                    {"tool": "done", "args": {"summary": "x"}}], approval_timeout=1)
        p = self.goal("tricky", "voice")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        res = self.results()
        self.assertFalse(res[0]["is_error"], res[0]["text"])
        self.assertTrue(res[1]["is_error"])
        self.assertIn("not approved", res[1]["text"])
        self.assertTrue(os.path.isdir(self.victim))
        self.assertNotIn(self.victim, self.text(self.sh))


class Stop(Real):
    def test_stop_ends_the_goal_and_nothing_more_is_typed(self):
        m2 = os.path.join(self.e.dir, "marker2")
        self.start([{"tool": "run", "args": {"command": "echo step-one"}}, {"sleep": 60}, {"tool": "run", "args": {"command": "touch %s" % m2}}], countdown=0)
        p = self.goal("two steps", "voice", wait=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        gid = p.stdout.strip()
        self.assertTrue(ss.wait_for(lambda: "step-one" in self.text(self.sh), 15))
        time.sleep(0.3)
        t0 = time.time()
        s = self.cli("stop")
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertTrue(ss.wait_for(lambda: (self.state(gid) or {}).get("state") == "stopped", 10), self.state(gid))
        self.assertLess(time.time() - t0, 8)
        time.sleep(0.5)
        self.assertFalse(os.path.exists(m2))
        self.assertNotIn("marker2", self.text(self.sh))
        # no brain left
        left = subprocess.run(["pgrep", "-f", "fixtures/sysop/bin/claude"], capture_output=True, text=True).stdout.split()
        self.assertEqual(left, [])

    def test_stop_during_the_countdown_types_nothing(self):
        marker = os.path.join(self.e.dir, "marker")
        self.start([{"tool": "run", "args": {"command": "touch %s" % marker}}], countdown=30)
        p = self.goal("later", "voice", wait=False)
        gid = p.stdout.strip()
        self.assertTrue(ss.wait_for(lambda: (self.state(gid) or {}).get("state") == "waiting_approval", 15))
        self.assertEqual(self.cli("stop").returncode, 0)
        self.assertTrue(ss.wait_for(lambda: (self.state(gid) or {}).get("state") == "stopped", 10))
        time.sleep(0.5)
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
