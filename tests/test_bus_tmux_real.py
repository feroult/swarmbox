"""The tmux driver of swarmbox-bus against a REAL tmux, with real pty clients and a stand-in agent TUI (tests/fixtures/bus/fake_agent.py).
Skipped when tmux is not installed (the host gate has none): they run in Podman, in the images with tmux 3.5a and 3.7c, see the command at the
end of this docstring. Every test has its own tmux server (-L name under a private TMUX_TMPDIR), never the default socket of the machine.

  podman run --rm --userns=keep-id:uid=1000,gid=1000 -v $PWD:/src:ro --tmpfs /work:rw,exec,mode=1777,size=1g IMAGE \\
      bash -c 'cp -r /src /work/repo && cd /work/repo && HOME=/work/home python3 tests/test_bus_tmux_real.py'
"""
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus_support import BUS_PATH, Process  # noqa: E402
from bus_tmux_support import load_module  # noqa: E402
from helpers import ROOT  # noqa: E402

mod = load_module()
FIX = os.path.join(ROOT, "tests", "fixtures", "bus")
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0"


class Err(Exception):
    def __init__(self, code, message=""):
        Exception.__init__(self, "%s: %s" % (code, message))
        self.code, self.message = code, message


@unittest.skipUnless(shutil.which("tmux"), "no tmux here (run in Podman)")
class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="sbr-", dir="/tmp")
        self.sock = "sbr%d" % os.getpid()
        # Hermetic: the panes run a bash with no rc file and the prompt "$ ", in a private HOME, whatever the machine of the developer has in its
        # ~/.bashrc (a banner, a starship prompt with a coloured band): the tests read the screens
        home = os.path.join(self.dir, "home")
        os.mkdir(home)
        shell = os.path.join(self.dir, "shell")
        with open(shell, "w") as f:
            f.write("#!/bin/sh\nPS1='$ '\nexport PS1\nexec bash --norc --noprofile \"$@\"\n")
        os.chmod(shell, 0o755)
        self.env = dict(os.environ, TMUX_TMPDIR=self.dir, HOME=home, SHELL=shell)
        for k in ("TMUX", "STARSHIP_SHELL", "PROMPT_COMMAND", "BASH_ENV", "ENV"):
            self.env.pop(k, None)
        self.old_env = {k: os.environ.get(k) for k in ("TMUX_TMPDIR", "HOME")}
        os.environ["TMUX_TMPDIR"] = self.dir
        os.environ["HOME"] = home
        self.numbers = os.path.join(self.dir, "n.txt")
        self.clients = []
        self.addCleanup(self.cleanup)
        self.tm("new-session", "-d", "-s", "main", "-n", "one", "-x", "100", "-y", "30")
        self.d = mod.TmuxDriver(Err, socket=self.sock)
        self.w1 = self.tm("display-message", "-p", "-t", "main:", "#{window_id}")      # @0 on a fresh server
        self.p1 = self.pane()

    def cleanup(self):
        for pid, fd in self.clients:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], env=self.env, capture_output=True)
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)

    def tm(self, *a):
        p = subprocess.run(["tmux", "-L", self.sock] + [str(x) for x in a], capture_output=True, text=True, env=self.env)
        return (p.stdout + p.stderr).rstrip("\n")

    def client(self, args, cols, rows):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-L", self.sock] + args)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.clients.append((pid, fd))
        time.sleep(0.3)
        return pid, fd

    def key(self, c, data):
        os.write(c[1], data)
        time.sleep(0.25)

    def pane(self, target="main:"):
        return self.tm("display-message", "-p", "-t", target, "#{pane_id}")

    def wait(self, fn, seconds=8.0):
        end = time.time() + seconds
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.1)
        return None

    def text(self, tab=None, lines=None):
        return self.d.screen(tab or self.w1, lines)["text"]

    def code(self, fn, *a):
        with self.assertRaises(Err) as cm:
            fn(*a)
        return cm.exception.code, cm.exception.message

    def window_id(self, name):
        return next(t["tab"] for t in self.d.list_tabs() if t["name"] == name)

    def agent(self, name="agent", env="", args=""):
        """a window running the stand-in agent; returns (window id, pane id) once its box is on the screen"""
        pid = self.tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-n", name, "%spython3 %s/fake_agent.py %s" % (env, FIX, args))
        wid = self.window_id(name)
        self.assertTrue(self.wait(lambda: "auto mode on" in self.text(wid) or "Do you want to" in self.text(wid)), self.text(wid))
        return wid, pid


class TestTabs(Base):
    def test_active_is_the_window_of_the_last_active_client_two_pty_clients(self):
        """The topology of swarmbox-attach: a session per host terminal, its window linked into main, the browser attached to main."""
        self.tm("kill-session", "-t", "main")
        self.tm("new-session", "-d", "-s", "main", "-n", "idle", "-x", "120", "-y", "40")
        self.tm("new-session", "-d", "-s", "t1", "-x", "100", "-y", "30")
        w1 = self.tm("display-message", "-p", "-t", "=t1:", "#{window_id}")
        self.tm("new-session", "-d", "-s", "t2", "-x", "160", "-y", "50")
        w2 = self.tm("display-message", "-p", "-t", "=t2:", "#{window_id}")
        self.tm("rename-window", "-t", w1, "tab1")
        self.tm("rename-window", "-t", w2, "tab2")
        self.tm("link-window", "-d", "-a", "-s", w1, "-t", "=main:")
        self.tm("link-window", "-d", "-a", "-s", w2, "-t", "=main:")
        self.assertEqual(sorted(t["name"] for t in self.d.list_tabs()), ["idle", "tab1", "tab2"])

        def active():
            return [t["name"] for t in self.d.list_tabs() if t["active"]]
        self.assertEqual(active(), ["idle"])                    # no client: the current window of main
        c1 = self.client(["attach", "-t", "=t1"], 100, 30)
        c2 = self.client(["attach", "-t", "=t2"], 160, 50)
        c3 = self.client(["attach", "-t", "=main"], 120, 40)
        time.sleep(1.1)                                         # client_activity has a resolution of one second
        self.key(c1, b"x")
        self.assertEqual(active(), ["tab1"])
        time.sleep(1.1)
        self.key(c2, b"x")
        self.assertEqual(active(), ["tab2"])
        time.sleep(1.1)
        self.key(c3, b"x")
        self.assertEqual(active(), ["idle"])
        time.sleep(1.1)                                         # a control-mode client is never "the active client"
        cc = self.client(["-C", "attach", "-t", "=main"], 80, 24)
        self.key(cc, b"list-windows\n")
        self.assertEqual(active(), ["idle"])
        self.assertEqual(len([t for t in self.d.list_tabs() if t["active"]]), 1)

    def test_duplicate_names_and_renumbering(self):
        self.tm("set", "-g", "base-index", "1")
        self.tm("set", "-g", "renumber-windows", "on")
        self.tm("new-window", "-d", "-t", "main", "-n", "two")
        self.tm("new-window", "-d", "-t", "main", "-n", "two")
        self.tm("new-window", "-d", "-t", "main", "-n", "three")
        tabs = self.d.list_tabs()
        self.assertEqual([t["name"] for t in tabs], ["one", "two", "two", "three"])
        code, msg = self.code(self.d.send, "two", {"run": "echo no"})
        self.assertEqual(code, "ambiguous_tab")
        for t in tabs[1:3]:
            self.assertIn("%s (%s)" % (t["label"], t["tab"]), msg)
        self.assertEqual(self.d.resolve(tabs[2]["tab"]).pane, tabs[2]["pane"])
        self.tm("kill-window", "-t", tabs[1]["tab"])             # the indexes move down, the ids do not
        self.assertEqual(self.d.resolve("two").id, tabs[2]["tab"])
        self.assertEqual(self.code(self.d.resolve, tabs[1]["tab"])[0], "no_such_tab")

    def test_panels_are_hidden_both_options(self):
        main_pane = self.pane()
        for opt in ("@swarmbox_sysop_panel", "@swarmbox_voice_panel"):
            p = self.tm("split-window", "-t", "main:", "-P", "-F", "#{pane_id}", "sleep 300")
            self.tm("set-option", "-p", "-t", p, opt, "1")
            t = self.d.list_tabs()[0]
            self.assertEqual((t["pane"], t["panes"]), (main_pane, [main_pane]))     # the focus is in the panel: the tab's pane is the program's
            self.assertEqual(self.tm("display-message", "-p", "-t", "main:", "#{pane_id}"), p)
            self.d.send(self.w1, {"input": "echo from-%s{Enter}" % opt[-5:]})
            self.assertTrue(self.wait(lambda: "from-%s" % opt[-5:] in self.text()))
            self.tm("kill-pane", "-t", p)
        # the marker in the start command hides a pane before its option is set (split-window makes the pane first)
        p = self.tm("split-window", "-t", "main:", "-P", "-F", "#{pane_id}", "SWARMBOX_SYSOP_PANEL=1 sleep 300")
        t = self.d.list_tabs()[0]
        self.assertEqual((t["pane"], t["panes"]), (main_pane, [main_pane]))
        self.assertEqual(self.tm("display-message", "-p", "-t", "main:", "#{pane_id}"), p)
        self.d.send(self.w1, {"input": "echo from-marker{Enter}"})
        self.assertTrue(self.wait(lambda: "from-marker" in self.text()))
        self.tm("kill-pane", "-t", p)
        w = self.tm("new-window", "-d", "-t", "main", "-n", "ghost", "-P", "-F", "#{pane_id}", "sleep 300")
        self.tm("set-option", "-p", "-t", w, "@swarmbox_sysop_panel", "1")
        self.assertNotIn("ghost", [t["name"] for t in self.d.list_tabs()])
        self.assertEqual(self.code(self.d.screen, "ghost", None)[0], "no_such_tab")


class TestSendShell(Base):
    def test_run_multi_line_and_literal_text(self):
        self.d.send(self.w1, {"run": "printf '%s\\n' \"a  b\" 'it'\"'\"'s' `echo bt` $(echo sub) $HOME { }"})
        self.assertTrue(self.wait(lambda: "sub" in self.text()), self.text())
        t = self.text()
        self.assertIn("a  b", t)
        self.assertIn("it's", t)
        self.assertIn("bt", t)
        self.d.send(self.w1, {"run": "echo multi-1\necho multi-2"})
        self.assertTrue(self.wait(lambda: "multi-2" in self.text()), self.text())

    def test_literal_brace_and_braces_that_are_keys(self):
        self.d.send(self.w1, {"input": "echo {\"a\": 1} {{x}} ${HOME} {foo}{Enter}"})
        self.assertTrue(self.wait(lambda: "{foo}" in self.text().split("\n")[-3] or "{foo}" in self.text()), self.text())
        t = self.text()
        self.assertIn('echo {"a": 1} {x}', t)           # the typed line, with {{x}} turned into {x}
        self.assertIn("{a: 1} {x} " + os.path.expanduser("~") + " {foo}", t)      # the output: bash took the quotes away, expanded $HOME; {foo} is text
        # the bytes that reach the program: cat -vT shows them
        self.d.send(self.w1, {"run": "cat -vT"})
        time.sleep(0.4)
        self.d.send(self.w1, {"input": "a{C-a}b{Tab}{Esc}{Enter}"})
        self.assertTrue(self.wait(lambda: "a^Ab^I^[" in self.text()), self.text())
        self.d.send(self.w1, {"input": "{C-d}"})

    def test_a_semicolon_at_the_end_is_typed_and_long_text_goes_through(self):
        # tmux takes a trailing `;` of an argv word for the end of the command (and a trailing backslash-semicolon becomes `;`); the driver
        # sends it as a key. The text is checked on the screen, before any Enter.
        for text in ("echo SEMI;", "echo B ;", "echo A\\;", ";", "echo ;;;", "echo a;b;"):
            self.d.send(self.w1, {"input": text})
            self.assertTrue(self.wait(lambda: self.text().split("\n")[-1] == "$ " + text), (text, self.text()[-200:]))
            self.d.send(self.w1, {"input": "{C-c}"})
            self.assertTrue(self.wait(lambda: self.text().split("\n")[-1] == "$"), self.text()[-200:])
        # the old single word: `command too long` over 16 KB of text, and E2BIG (reported as no_tmux) over 128 KB
        self.d.send(self.w1, {"run": "echo " + "y" * 200000 + " | wc -c"})
        self.assertTrue(self.wait(lambda: "200001" in self.text(), 20), self.text()[-300:])

    def test_a_window_named_with_the_separator_stays_in_the_list(self):
        self.tm("new-window", "-d", "-n", "a" + mod.SEP + "b", "sleep 300")
        self.tm("new-window", "-d", "-n", "last", "sleep 300")
        names = [t["name"] for t in self.d.list_tabs()]
        self.assertEqual(names, ["one", "a" + mod.SEP + "b", "last"])

    def test_a_shell_is_not_judged_slash_and_dialog_words_are_typed(self):
        self.d.send(self.w1, {"run": "/bin/echo from-slash"})
        self.assertTrue(self.wait(lambda: "from-slash" in self.text()))
        self.d.send(self.w1, {"run": "echo 'Do you want to continue? Esc to cancel'"})
        self.d.send(self.w1, {"run": "echo after-dialog-words"})
        self.assertTrue(self.wait(lambda: "after-dialog-words" in self.text()))

    def test_a_pane_in_copy_mode_gets_the_text_in_the_program(self):
        self.d.send(self.w1, {"run": "echo before-copy-mode"})
        self.assertTrue(self.wait(lambda: "before-copy-mode" in self.text()))
        p = self.pane()
        self.tm("copy-mode", "-t", p)
        self.assertEqual(self.tm("display-message", "-p", "-t", p, "#{pane_in_mode}"), "1")
        s = self.d.screen(self.w1, None)
        self.assertTrue(s["in_mode"])
        self.assertEqual(s["mode"], "copy-mode")
        self.d.send(self.w1, {"run": "echo after-copy-mode"})
        self.assertEqual(self.tm("display-message", "-p", "-t", p, "#{pane_in_mode}"), "0")
        self.assertTrue(self.wait(lambda: "after-copy-mode" in self.text().replace("echo after-copy-mode", "")), self.text())

    def test_a_window_closed_between_the_list_and_the_send(self):
        self.tm("new-window", "-d", "-t", "main", "-n", "gone")
        tabs = self.d.list_tabs()
        wid = next(t["tab"] for t in tabs if t["name"] == "gone")
        self.tm("kill-window", "-t", wid)
        self.assertEqual(self.code(self.d.send, wid, {"run": "echo late"})[0], "no_such_tab")
        # the race inside one call: the pane id is resolved, then the pane dies before the keys
        pane = tabs[-1]["pane"]
        t = mod.Tab(wid, 9, "gone", "/", "bash", pane, [pane], False, "9:gone")
        self.d.resolve = lambda tab: t
        self.assertEqual(self.code(self.d.send, wid, {"run": "x"})[0], "no_such_tab")
        self.assertEqual(self.code(self.d.screen, wid, None)[0], "no_such_tab")

    def test_no_session(self):
        self.assertEqual(self.code(mod.TmuxDriver(Err, socket=self.sock, session="nope").list_tabs)[0], "no_session")
        self.assertEqual(self.code(mod.TmuxDriver(Err, socket="no-such-server").list_tabs)[0], "no_session")


class TestScreen(Base):
    def test_markers_on_a_reverse_video_bar_and_error_colour(self):
        self.d.send(self.w1, {"run": "clear; printf '  one\\n\\033[7m  two  \\033[0m\\n  three \\033[31mfailed\\033[0m\\n'"})
        self.assertTrue(self.wait(lambda: "[sel]two[/sel]" in self.text()), self.text())
        self.assertIn("[err]failed[/err]", self.text())

    def test_the_real_claude_permission_dialog_fixture(self):
        self.d.send(self.w1, {"run": "clear; cat %s/claude-permission.raw; sleep 300" % FIX})
        self.assertTrue(self.wait(lambda: "Do you want to proceed?" in self.text()), self.text())
        t = self.text()
        self.assertIn("❯ 1. Yes", t)               # the selected option is the pointer in the text
        self.assertNotIn("[sel]", t)
        self.assertLessEqual(t.count("[bg]"), 1)        # the echo of the user's prompt has a background (it may be above the 30 rows); the logo has none
        rows = [x.rstrip() for x in self.tm("capture-pane", "-p", "-J", "-t", self.p1).split("\n")]
        self.assertEqual(mod.agent_state(rows, "sleep"), (True, "dialog"))
        # typing a prompt into it is refused
        self.assertEqual(self.code(self.d.send, self.w1, {"run": "hello"})[0], "dialog_open")
        self.assertNotIn("hello", self.text())
        self.tm("send-keys", "-t", self.p1, "C-c")

    def test_a_select_menu_has_no_marker_and_fzf_has_the_background_one(self):
        self.d.send(self.w1, {"run": "bash -c \"PS3='pick> '; select x in red green blue; do break; done\""})
        self.assertTrue(self.wait(lambda: "2) green" in self.text()), self.text())
        t = self.text()
        self.assertNotIn("[sel]", t)
        self.assertNotIn("[bg]", t)
        self.d.send(self.w1, {"input": "1{Enter}"})
        if not shutil.which("fzf"):
            self.skipTest("no fzf in this image (the select menu part passed)")
        self.d.send(self.w1, {"run": "clear; printf 'alpha\\nbeta\\ngamma\\n' | fzf --height=8; echo fzf-done"})
        self.assertTrue(self.wait(lambda: "gamma" in self.text()), self.text())
        self.d.send(self.w1, {"input": "{Down}"})
        time.sleep(0.4)
        t = self.text()
        self.assertEqual(len([x for x in t.split("\n") if "[bg]" in x or "[sel]" in x]), 1, t)    # exactly one current line
        self.d.send(self.w1, {"input": "{Enter}"})

    def test_secrets_are_removed_from_a_real_screen(self):
        self.d.send(self.w1, {"run": "printf 'key %s\\nAPI_TOKEN=\\033[7mhunter2\\033[0m\\nplain visible\\n' '" + KEY + "'"})
        self.assertTrue(self.wait(lambda: "plain visible" in self.text()), self.text())
        t = self.text()
        self.assertNotIn(KEY, t)
        self.assertNotIn("a1B2c3D4", t)
        self.assertNotIn("hunter2", t)
        self.assertIn("[REDACTED]", t)
        # also when an escape code splits the key (the filter runs on the converted text)
        self.d.send(self.w1, {"run": "clear; printf 'sk-\\033[1m%s\\033[0m end\\n' '" + KEY[3:] + "'"})
        self.assertTrue(self.wait(lambda: " end" in self.text()), self.text())
        self.assertNotIn(KEY[3:], self.text())

    def test_lines_scrollback_and_alternate_screen(self):
        self.d.send(self.w1, {"run": "seq 1 100 > %s; seq 1 60" % self.numbers})
        # not `"60" in text`: the typed command line says "seq 1 60" too, so that would not wait for the output
        self.assertTrue(self.wait(lambda: self.text().split("\n")[-2:] == ["60", "$"]), self.text()[-200:])
        s = self.d.screen(self.w1, 40)
        rows = s["text"].split("\n")
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[-2], "60")                      # the last line is the prompt
        self.assertEqual(len(self.d.screen(self.w1, 5)["text"].split("\n")), 5)
        self.d.send(self.w1, {"run": "less " + self.numbers})
        self.assertTrue(self.wait(lambda: self.d.screen(self.w1, None)["alternate"]))
        s = self.d.screen(self.w1, 500)
        self.assertTrue(s["alternate"])
        self.assertIsNone(s["lines"])                       # a full-screen program offers no `lines`
        self.assertEqual(len(s["text"].split("\n")), 30)
        self.assertEqual(s["text"].split("\n")[0], "1")
        self.d.send(self.w1, {"input": "q"})

    def test_the_cost_of_ten_windows(self):
        for i in range(9):
            self.tm("new-window", "-d", "-t", "main", "-n", "w%d" % i)
        tabs = self.d.list_tabs()
        self.assertEqual(len(tabs), 10)
        for t in tabs:
            self.tm("send-keys", "-t", t["pane"], "-l", "--", "seq 1 200")
            self.tm("send-keys", "-t", t["pane"], "Enter")
        time.sleep(0.6)
        t0 = time.time()
        self.d.list_tabs()
        t_list = time.time() - t0
        t0 = time.time()
        for t in tabs:
            self.d.screen(t["tab"], 50)
        t_all = time.time() - t0
        print("\nlist_tabs (10 windows): %.0f ms; screen of 10 windows, 50 lines: %.0f ms (%.0f ms per tab)" % (t_list * 1000, t_all * 1000, t_all * 100),
              file=sys.stderr)
        self.assertLess(t_all, 3.0)
        self.assertLess(t_list, 1.0)


class TestAgent(Base):
    def test_a_prompt_is_submitted_with_the_pause_and_the_answer_appears(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=0.5 ")
        self.d.send(wid, {"run": "reply with exactly PONG-1"})
        self.assertTrue(self.wait(lambda: "● ANSWER reply with exactly PONG-1" in self.text(wid)), self.text(wid))

    def test_a_burst_would_have_failed_and_the_driver_does_not_burst(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=0.3 ")
        long = "xxxxxxxxxxxx " * 46      # blanks: a run of 120 base64 characters is redacted on its own
        self.tm("send-keys", "-t", pane, "-l", "--", long, ";", "send-keys", "-t", pane, "Enter")    # one burst: the stand-in sees a paste
        time.sleep(0.6)
        self.assertIn("xxxxxxxxxxxx", self.text(wid))
        self.assertNotIn("● ANSWER", self.text(wid))                                     # nothing was submitted: the Enter was a line break
        self.tm("send-keys", "-t", pane, "C-c")
        time.sleep(0.4)
        self.d.send(wid, {"run": long})
        self.assertTrue(self.wait(lambda: "● ANSWER xxxx" in self.text(wid)), self.text(wid))

    def test_multi_line_prompt_is_one_prompt(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=0.3 ")
        self.d.send(wid, {"run": "first line\nsecond line {literal}"})
        self.assertTrue(self.wait(lambda: "● ANSWER first line second line {literal}" in self.text(wid)), self.text(wid))

    def test_busy_is_refused_unless_queue_then_the_answer_runs_the_queued_one(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=2.0 ")
        self.d.send(wid, {"run": "first one"})
        self.assertTrue(self.wait(lambda: "esc to interrupt" in self.text(wid)))
        code, msg = self.code(self.d.send, wid, {"run": "second one"})
        self.assertEqual(code, "busy_tab")
        self.assertNotIn("second one", self.text(wid))
        self.d.send(wid, {"run": "third one", "queue": True})
        self.assertTrue(self.wait(lambda: "● ANSWER third one" in self.text(wid), 10), self.text(wid))
        self.assertNotIn("second one", self.text(wid))

    def test_esc_interrupts_a_busy_agent(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=30 ")
        self.d.send(wid, {"run": "slow"})
        self.assertTrue(self.wait(lambda: "esc to interrupt" in self.text(wid)))
        self.d.send(wid, {"input": "{Esc}"})
        self.assertTrue(self.wait(lambda: "esc to interrupt" not in self.text(wid)), self.text(wid))

    def test_a_dialog_is_refused_and_answered_by_input(self):
        wid, pane = self.agent(env="FAKE_AGENT_DIALOG=1 FAKE_AGENT_BUSY=0.3 ")
        self.assertEqual(self.code(self.d.send, wid, {"run": "hello"})[0], "dialog_open")
        self.d.send(wid, {"input": "1"})
        self.assertTrue(self.wait(lambda: "auto mode on" in self.text(wid)), self.text(wid))
        self.d.send(wid, {"run": "hello"})
        self.assertTrue(self.wait(lambda: "● ANSWER hello" in self.text(wid)), self.text(wid))

    def test_slash_and_bang_are_refused(self):
        wid, pane = self.agent()
        for text in ("/help", "!ls"):
            self.assertEqual(self.code(self.d.send, wid, {"run": text})[0], "slash_refused")
        self.assertNotIn("/help", self.text(wid))


class TestThroughTheBus(Base):
    """swarmbox-bus as a process (python3 -S, driver auto) on this tmux server: pub tab/<tab>/in, get tab/<tab>/screen, ls tab/."""

    def test_the_whole_path(self):
        wid, pane = self.agent(env="FAKE_AGENT_BUSY=0.4 ")
        p = Process(env_extra={"SB_BUS_TMUX_SOCKET": self.sock, "TMUX_TMPDIR": self.dir}, driver="auto").start()
        self.addCleanup(p.close)
        out = p.cli("ls", "tab/")
        self.assertEqual(out.returncode, 0, out.stderr)
        tabs = json.loads(out.stdout)
        self.assertEqual(sorted(t["name"] for t in tabs), ["agent", "one"])
        self.assertEqual(sum(t["active"] for t in tabs), 1)
        out = p.cli("pub", "tab/agent/in", json.dumps({"run": "reply with exactly PONG-1"}))
        self.assertEqual(out.returncode, 0, out.stderr)
        end = time.time() + 10
        text = ""
        while time.time() < end and "ANSWER reply with exactly PONG-1" not in text:
            time.sleep(0.2)
            out = p.cli("get", "tab/%s/screen" % wid)
            self.assertEqual(out.returncode, 0, out.stderr)
            text = json.loads(out.stdout)["text"]
        self.assertIn("● ANSWER reply with exactly PONG-1", text)
        out = p.cli("pub", "tab/one/in", json.dumps({"run": "echo through-the-bus"}))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.wait(lambda: "through-the-bus" in json.loads(p.cli("get", "tab/one/screen", "--lines", "20").stdout)["text"]))
        out = p.cli("pub", "tab/agent/in", json.dumps({"run": "/help"}))
        self.assertEqual(out.returncode, 1)
        self.assertIn("slash_refused", out.stderr.decode())
        out = p.cli("pub", "tab/nope/in", json.dumps({"run": "x"}))
        self.assertIn("no_such_tab", out.stderr.decode())
        self.assertEqual(p.cli("get", "tab/one/screen", "--lines", "3").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
