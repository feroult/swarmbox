"""The panel of the sysop as a PROGRAM on a pty, as tmux runs it (container/addons/sysop/lib/swarmbox_sysop/panel.py). What is on the screen for each
state, what each key does and what it writes are tested without a terminal in tests/fast/test_sysop_panel.py; here only what needs the process:
the terminal loop (raw mode, alternate screen, resize, signals), the keys as bytes through a pty, the clock that ticks, the files of a service seen by
another process, and the real service and the real bus behind it.

  * against a FAKE state dir (the files of ipc.py written by the test): idle, resize and q, signals, the idle CPU, the countdown and the approval
    gesture as keystrokes, a goal typed and published on a bus, the service going and coming.
  * against the REAL service, the REAL bus (a process) and the fake claude: the cancel key, the allow key, a goal typed in the panel.
No tmux, no network, no model. Run with: python3 -W error tests/slow/test_sysop_panel_pty.py
"""
import fcntl
import json
import os
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fast"))
sys.path.insert(0, os.path.join(HERE, "..", "support"))
import sysop_support as ss  # noqa: E402
from test_sysop_panel import SETTINGS, FakeState  # noqa: E402  (helpers only: the tests of that file are not imported by name)

from swarmbox_sysop import audit, ipc, panel, paths, service  # noqa: E402
from swarmbox_sysop.panel import strip_ansi, text_width  # noqa: E402

class Terminal:
    """The panel program on a pty, as tmux runs it: bytes in, bytes out, a window size, signals."""

    def __init__(self, env, rows=30, cols=60):
        self.rows, self.cols = rows, cols
        self.out = b""
        self.lock = threading.Lock()
        e = {"PATH": os.environ["PATH"], "PYTHONPATH": ss.LIB, "TERM": "xterm-256color", "LANG": "C.UTF-8", "HOME": env.get("HOME", "/tmp")}
        e.update({k: v for k, v in env.items() if k.startswith(("SB_", "SWARMBOX_SYSOP_"))})
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(sys.executable, [sys.executable, "-B", "-m", "swarmbox_sysop", "panel"], e)
        self.resize(rows, cols, signal_it=False)
        self.status = None
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.2)
                if not r:
                    if self.status is not None:
                        return
                    continue
                data = os.read(self.fd, 65536)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.out += data

    def resize(self, rows, cols, signal_it=True):
        self.rows, self.cols = rows, cols
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        if signal_it:
            os.kill(self.pid, signal.SIGWINCH)

    def send(self, data):
        os.write(self.fd, data if isinstance(data, bytes) else data.encode())

    def raw(self):
        with self.lock:
            return self.out

    def text(self):
        return strip_ansi(self.raw().decode("utf-8", "replace"))

    def last_frame(self):
        """The rows of the last full redraw (each frame starts with a move to row 1)."""
        raw = self.raw().decode("utf-8", "replace")
        i = raw.rfind("\x1b[1;1H")
        rows = {}
        for m in re.finditer(r"\x1b\[(\d+);1H(.*?)(?=\x1b\[\d+;1H|\x1b\[\?25|\Z)", raw[i:], re.S):
            rows[int(m.group(1))] = strip_ansi(m.group(2)).replace("\x1b[K", "").rstrip()
        return [rows.get(n, "") for n in range(1, max(rows) + 1)] if rows else []

    def wait_frame(self, needle, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if needle in "\n".join(self.last_frame()):
                return True
            if self.exited():
                break
            time.sleep(0.05)
        return needle in "\n".join(self.last_frame())

    def exited(self):
        if self.status is not None:
            return True
        try:
            pid, st = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.status = -1
            return True
        if pid:
            self.status = os.waitstatus_to_exitcode(st)
            return True
        return False

    def wait_exit(self, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.exited():
                return self.status
            time.sleep(0.05)
        return None

    def close(self):
        if not self.exited():
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
            self.wait_exit(3)
        try:
            os.close(self.fd)
        except OSError:
            pass



class PtyBase(unittest.TestCase):
    def setUp(self):
        self.st = FakeState()
        self.addCleanup(self.st.close)
        self.terms = []
        self.addCleanup(lambda: [t.close() for t in self.terms])

    def open(self, **kw):
        t = Terminal(self.st.e.env, **kw)
        self.terms.append(t)
        return t

    def ready(self, t, needle):
        self.assertTrue(t.wait_frame(needle), "\n".join(t.last_frame()))
        time.sleep(panel.GUARD + 0.15)       # past the guard against stray typing

    def wait(self, fn, what, seconds=8.0):
        v = ss.wait_for(fn, seconds)
        self.assertTrue(v, "timed out waiting for " + what)
        return v



class PanelProgram(PtyBase):
    def test_idle_screen_resize_and_q(self):
        self.st.serve(settings=dict(SETTINGS))
        t = self.open(rows=20, cols=80)
        self.ready(t, "Say a goal, or type it below.")
        self.assertEqual(len(t.last_frame()), 20)
        self.assertIn("SYSOP  idle", t.last_frame()[0])
        self.assertIn("Type a goal", t.last_frame()[-1], "the idle panel offers the Goal button on its last row")
        t.resize(30, 40)                                       # SIGWINCH: redrawn at the new size, nothing wider than the pane
        self.assertTrue(ss.wait_for(lambda: len(t.last_frame()) == 30, 5), t.last_frame())
        self.assertTrue(all(text_width(x) <= 40 for x in t.last_frame()), t.last_frame())
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)
        self.assertIn("\x1b[?1049l", t.raw().decode("utf-8", "replace"), "the screen is given back")

    def test_sigterm_and_sighup_end_it_cleanly(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            self.st.serve()
            t = self.open()
            self.ready(t, "idle")
            os.kill(t.pid, sig)
            self.assertEqual(t.wait_exit(), 0, sig)

    def test_the_idle_panel_costs_almost_no_cpu_and_follows_a_new_goal(self):
        """a past bug: the idle panel looked at the files every turn. (The rule, a look only when a file changed, is Panel.changed in the fast tests.)"""
        self.st.serve(settings=dict(SETTINGS))
        t = self.open(rows=30, cols=70)
        self.ready(t, "Say a goal, or type it below.")

        def cpu():
            with open("/proc/%d/stat" % t.pid) as f:
                f_ = f.read().rsplit(")", 1)[1].split()
            return (int(f_[11]) + int(f_[12])) / os.sysconf("SC_CLK_TCK")
        before, t0 = cpu(), time.time()
        time.sleep(4)
        used, wall = cpu() - before, time.time() - t0
        self.assertLess(used / wall, 0.02, "the idle panel used %.3f s of CPU in %.1f s" % (used, wall))
        self.st.goal(state="running", text="check the thing")        # and it still sees a goal, within the idle look (one second)
        self.st.serve(current="g1", settings=dict(SETTINGS))
        self.assertTrue(t.wait_frame("check the thing", 4), "\n".join(t.last_frame()))
        self.assertIn("working", "\n".join(t.last_frame()))

    def test_the_service_coming_and_going_is_seen_by_the_panel(self):
        t = self.open(rows=20, cols=60)
        self.assertTrue(t.wait_frame("The sysop is not running. It starts with the box."), "\n".join(t.last_frame()))
        self.assertIn("SYSOP  off", t.last_frame()[0])
        self.st.serve(settings=dict(SETTINGS))
        self.assertTrue(t.wait_frame("Say a goal, or type it below.", 4), "\n".join(t.last_frame()))
        self.st.serve(on=False)
        self.assertTrue(t.wait_frame("The sysop is not running.", 4), "\n".join(t.last_frame()))

    def test_the_countdown_ticks_and_the_keys_decide(self):
        self.st.serve(current="g1")
        self.st.goal(state="waiting_approval")
        self.st.pending(mode="veto", deadline=time.time() + 20, text="ls /tmp")
        t = self.open()
        self.assertTrue(t.wait_frame("sending in"))
        t.send("c")                                           # typing meant for another pane, a moment after the action appeared: ignored
        time.sleep(0.2)
        self.assertIsNone(self.st.decision())
        time.sleep(panel.GUARD)
        first = [x for x in t.last_frame() if "sending in" in x][0]
        time.sleep(1.1)
        self.assertNotEqual([x for x in t.last_frame() if "sending in" in x][0], first, "the clock ticks by itself")
        t.send("c")
        self.assertEqual(self.wait(self.st.decision, "decision.json"), {"id": "p1", "decision": "veto", "by": "panel"})
        self.st.clear_pending()
        self.st.pending(mode="approve", risk="high", text="rm -rf ~/work", deadline=time.time() + 30, pid="p2")
        self.assertTrue(t.wait_frame("allow? high risk"), "\n".join(t.last_frame()))
        ipc.remove(os.path.join(self.st.paths.goal_dir("g1"), "decision.json"))
        time.sleep(panel.GUARD + 0.15)
        for k in ("\r", "r", "u", "z", "\r"):                 # Enter and letters that are no answer allow nothing
            t.send(k)
        time.sleep(0.3)
        self.assertIsNone(self.st.decision(), "only a, y (allow) or c, n (cancel) answer")
        t.send("y")                                           # one key, no typed word (the word of the decision file is written by the panel)
        self.assertEqual(self.wait(self.st.decision, "decision.json"), {"id": "p2", "decision": "approve", "by": "panel", "word": "run"})

    def test_a_goal_typed_in_the_panel_is_published_on_the_bus(self):
        bus = ss.FakeBus(self.st.e.env["SB_BUS_SOCKET"])
        self.addCleanup(bus.stop)
        c = socket.socket(socket.AF_UNIX)
        self.addCleanup(c.close)
        c.connect(self.st.e.env["SB_BUS_SOCKET"])
        c.settimeout(10)
        c.sendall(b'{"op":"sub","topic":"goal"}\n')
        f = c.makefile("rb")
        self.assertTrue(json.loads(f.readline())["ok"])
        self.st.serve()
        t = self.open()
        self.ready(t, "Say a goal, or type it below.")
        t.send("g")
        self.assertTrue(t.wait_frame("Goal (Enter sends, Esc cancels):"))
        t.send("check the disk")
        self.assertTrue(t.wait_frame("check the disk"))
        t.send("\r")
        env = json.loads(f.readline())
        self.assertEqual((env["topic"], env["source"], env["body"]), ("goal", "panel", {"text": "check the disk"}))
        self.assertTrue(t.wait_frame("Goal sent."), "\n".join(t.last_frame()))


class RealCore(PtyBase):
    """The real service, the real broker (a process), a fake swarmbox-tabs and the fake claude: the panel shows and answers what the core does."""

    def setUp(self):
        super().setUp()
        from bus_support import Process
        self.saved = dict(os.environ)
        self.addCleanup(self.restore)
        self.bus = Process()
        self.bus.start()
        self.addCleanup(self.bus.close)
        self.st.e.env["SB_BUS_SOCKET"] = self.bus.path
        self.st.paths = paths.Paths(self.st.e.env)
        self.tabs = ss.FakeTabs(os.path.join(self.st.e.dir, "tabs.sock"), {"main": dict(tab="main", label="0:shell", index=0, name="shell", dir="/work", cmd="bash",
                                                                                       active=True, pane="%1", panes=1)})
        self.addCleanup(self.tabs.stop)
        self.tabs.screens["main"] = "$ "
        os.environ.update(self.st.e.env)
        os.environ.update(self.tabs.cmd_env)
        self.out = os.path.join(self.st.e.dir, "out.jsonl")
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_OUT"] = self.out
        self.svc = None
        self.cli_env = dict(os.environ, PYTHONPATH=ss.LIB)

    def restore(self):
        if self.svc:
            self.svc.shutdown()
            self.thread.join(20)
        os.environ.clear()
        os.environ.update(self.saved)

    def start(self, steps, **cfg):
        path = os.path.join(self.st.e.dir, "script.json")
        with open(path, "w") as f:
            json.dump(steps, f)
        os.environ["SWARMBOX_TEST_FAKE_CLAUDE_SCRIPT"] = path
        self.svc = service.Service(self.st.e.cfg(**dict({"countdown": 6, "approval_timeout": 20}, **cfg)), self.st.paths, backoff=(0.1, 0.5), log=lambda m: None)
        self.thread = threading.Thread(target=self.svc.run, daemon=True)
        self.thread.start()
        self.assertTrue(self.svc.wait_ready(10))
        self.assertTrue(ss.wait_for(lambda: self.svc.bus_state == "connected", 10))

    def goal(self, text, source="cli"):
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "goal", "--source", source, text], env=self.cli_env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout.strip()

    def decisions(self):
        return [e["decision"] for e in audit.read(self.st.paths.audit) if e["event"] == "decision"]

    def state(self, gid):
        return ipc.read_json(os.path.join(self.st.paths.goals, gid, "state.json"))

    def test_the_panel_follows_a_goal_and_the_cancel_key_stops_the_action(self):
        # cp is medium risk: in auto it waits out a countdown (a low-risk command would be sent at once, with nothing to cancel)
        self.start([{"tool": "say", "args": {"text": "listing"}}, {"tool": "run", "args": {"tab": "main", "command": "cp /dev/null /tmp/panel-test-nothing"}},
                    {"tool": "say", "args": {"text": "it was vetoed"}}, {"tool": "done", "args": {"summary": "vetoed by you"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "Say a goal, or type it below.")
        gid = self.goal("echo something", "voice")
        self.assertTrue(t.wait_frame("sending in"), "\n".join(t.last_frame()))
        text = "\n".join(t.last_frame())
        for needle in ("echo something", "listing", "cp /dev/null /tmp/panel-test-nothing", "Cancel"):
            self.assertIn(needle, text)
        self.assertNotIn("Allow", text, "a countdown has only Cancel")
        time.sleep(panel.GUARD + 0.2)
        t.send("c")
        self.assertTrue(t.wait_frame("done: vetoed by you"), "\n".join(t.last_frame()))
        self.assertEqual(self.decisions(), ["waiting", "vetoed"])
        with open(self.out) as f:
            res = [json.loads(x) for x in f]
        self.assertIn("vetoed by the user", res[1]["text"])
        self.assertEqual(self.state(gid)["state"], "done")
        frame = "\n".join(t.last_frame())
        self.assertIn("it was vetoed", frame)
        self.assertIn("✗ run: cp /dev/null /tmp/panel-test-nothing", frame, "the vetoed step is a cross")

    def test_a_low_risk_action_is_sent_at_once_with_nothing_to_answer(self):
        self.start([{"tool": "run", "args": {"tab": "main", "command": "echo from-the-sysop"}}, {"tool": "done", "args": {"summary": "echoed"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "Say a goal, or type it below.")
        self.goal("echo something", "voice")
        self.assertTrue(t.wait_frame("done: echoed", 15), "\n".join(t.last_frame()))
        self.assertNotIn("sending in", t.text(), "no countdown was ever drawn")
        self.assertEqual(self.decisions(), ["allowed"])
        self.assertIn("✓ run: echo from-the-sysop", "\n".join(t.last_frame()))

    def test_a_high_risk_action_is_allowed_with_one_key(self):
        self.start([{"tool": "run", "args": {"tab": "main", "command": "rm -rf /tmp/sysop-panel-test-nothing"}}, {"tool": "done", "args": {"summary": "removed"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "Say a goal, or type it below.")
        self.goal("clean up")
        self.assertTrue(t.wait_frame("allow? high risk"), "\n".join(t.last_frame()))
        text = "\n".join(t.last_frame())
        self.assertIn("Allow", text)
        self.assertIn("Cancel", text)
        time.sleep(panel.GUARD + 0.2)
        for k in ("\r", "r", "u", "z"):
            t.send(k)
        time.sleep(0.5)
        self.assertEqual(self.decisions(), ["waiting"], "Enter and letters that are no answer allow nothing")
        t.send("y")
        self.assertTrue(t.wait_frame("done: removed", 15), "\n".join(t.last_frame()))
        self.assertEqual(self.decisions(), ["waiting", "approved"])

    def test_a_goal_typed_in_the_panel_is_run_by_the_service(self):
        self.start([{"tool": "say", "args": {"text": "typed goals work"}}, {"tool": "done", "args": {"summary": "got it"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "Say a goal, or type it below.")
        t.send("g")
        t.send("do the thing")
        t.send("\r")
        self.assertTrue(t.wait_frame("done: got it", 15), "\n".join(t.last_frame()))
        gid = self.wait(lambda: self.svc.current is None and next((g for g in service.recent_goals(self.st.paths, 1)), None), "the goal")["id"]
        st = self.state(gid)
        self.assertEqual((st["source"], st["text"], st["state"]), ("panel", "do the thing", "done"))
        self.assertIn("do the thing", "\n".join(t.last_frame()), "the goal stays on screen with its end")


if __name__ == "__main__":
    unittest.main()
