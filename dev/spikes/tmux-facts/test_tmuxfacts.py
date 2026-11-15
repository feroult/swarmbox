"""Tests of tmuxfacts.py against a real tmux with real pty clients. Run inside the container (never against a tmux of the box):
    python3 -m unittest -v dev/spikes/tmux-facts/test_tmuxfacts.py     (see run-in-container.sh)
Every test uses its own tmux socket (-L) under a private TMUX_TMPDIR."""
import fcntl
import os
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tmuxfacts as tf  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
VOICE_LIB = next((p for p in (os.path.join(REPO, "container/tools/voice/lib"), "/src/container/tools/voice/lib") if os.path.isdir(p)), None)


class Box:
    """A private tmux server and the pty clients attached to it."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="tf-")
        self.sock = "tf%d" % os.getpid()
        self.env = dict(os.environ, TMUX_TMPDIR=self.dir)
        self.env.pop("TMUX", None)
        os.environ["TMUX_TMPDIR"] = self.dir
        os.environ["TMUXFACTS_TMUX"] = "tmux -L " + self.sock
        os.environ.pop("TMUX", None)
        self.clients = []

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

    def resize(self, c, cols, rows):
        fcntl.ioctl(c[1], termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(c[0], signal.SIGWINCH)
        time.sleep(0.4)

    def close(self):
        for pid, fd in self.clients:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], env=self.env, capture_output=True)
        shutil.rmtree(self.dir, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.b = Box()
        self.addCleanup(self.b.close)
        self.b.tm("new-session", "-d", "-s", "main", "-n", "one", "-x", "100", "-y", "30")

    def pane(self, target="main:"):
        return self.b.tm("display-message", "-p", "-t", target, "#{pane_id}")

    def type(self, pane, cmd, wait=0.4):
        self.b.tm("send-keys", "-t", pane, "-l", "--", cmd)
        self.b.tm("send-keys", "-t", pane, "Enter")
        time.sleep(wait)


class TestTabs(Base):
    def test_duplicate_names_ids_and_renumbering(self):
        b = self.b
        b.tm("set", "-g", "base-index", "1")
        b.tm("set", "-g", "renumber-windows", "on")
        b.tm("new-window", "-t", "main", "-n", "two")
        b.tm("new-window", "-t", "main", "-n", "two")
        b.tm("new-window", "-t", "main", "-n", "three")
        tabs = tf.list_tabs()
        self.assertEqual([t.name for t in tabs], ["one", "two", "two", "three"])
        ids = {t.label: t.id for t in tabs}
        with self.assertRaises(tf.AmbiguousTab):
            tf.resolve("two")
        self.assertEqual(tf.resolve("three").id, tabs[3].id)
        self.assertEqual(tf.resolve(str(tabs[1].index)).id, tabs[1].id)
        self.assertEqual(tf.resolve(tabs[2].id).id, tabs[2].id)
        # close the first "two": the indexes move down (renumber-windows on), the @ids of the others do not
        b.tm("kill-window", "-t", tabs[1].id)
        after = tf.list_tabs()
        self.assertEqual([t.id for t in after], [tabs[0].id, tabs[2].id, tabs[3].id])
        self.assertNotEqual([t.index for t in after], [t.index for t in tabs[:1] + tabs[2:]])   # indexes changed
        self.assertEqual(tf.resolve("two").id, tabs[2].id)   # the name is unique now
        self.assertEqual(tf.resolve(tabs[3].id).name, "three")   # the id still means the same window
        # a stale id raises instead of silently hitting another window
        with self.assertRaises(tf.TmuxError):
            tf.resolve(tabs[1].id)
        # a pane id is global and also resolves
        self.assertEqual(tf.resolve(after[0].pane).id, after[0].id)
        self.assertIn(tf.resolve("%s.%s" % (after[1].id, after[1].pane)).pane, after[1].panes)

    def test_focus_in_the_panel_falls_back_to_the_last_pane(self):
        b = self.b
        first = self.pane()
        second = b.tm("split-window", "-t", first, "-P", "-F", "#{pane_id}")   # focus is in `second`
        b.tm("select-pane", "-t", first)
        panel = b.tm("split-window", "-f", "-v", "-t", "main:", "-P", "-F", "#{pane_id}", "sleep 300")   # the panel takes the focus
        b.tm("set-option", "-p", "-t", panel, "@swarmbox_sysop_panel", "1")
        self.assertEqual(b.tm("display-message", "-p", "-t", "main:", "#{pane_id}"), panel)
        t = tf.list_tabs()[0]
        self.assertEqual(sorted(t.panes), sorted([first, second]))
        self.assertEqual(t.pane, first)   # the pane the user was on before the panel took the focus

    def test_list_fields_cwd_command(self):
        b = self.b
        b.tm("new-window", "-t", "main", "-n", "sl", "-c", "/tmp", "exec sleep 300")
        time.sleep(0.3)
        t = next(t for t in tf.list_tabs() if t.name == "sl")
        self.assertEqual((t.cwd, t.command), ("/tmp", "sleep"))
        self.assertRegex(t.pane, r"^%\d+$")

    def test_same_session_clients_share_the_window(self):
        """Two clients of ONE session always show the same window: `active` is the session's current window, there is no per-client one."""
        b = self.b
        b.tm("new-window", "-t", "main", "-n", "two")
        a = b.client(["attach", "-t", "main"], 100, 30)
        c = b.client(["attach", "-t", "main"], 160, 50)
        b.key(c, b"\x02n")   # prefix + next-window typed in the second client
        wins = b.tm("list-clients", "-F", "#{window_id}").split("\n")
        self.assertEqual(len(set(wins)), 1)
        self.assertEqual(tf.active_tab().name, "two" if wins[0] == tf.resolve("two").id else "one")

    def test_active_is_the_window_of_the_last_active_client(self):
        """The topology of swarmbox-attach: a session per host terminal, its window linked into main, the browser attached to main."""
        b = self.b
        b.tm("kill-session", "-t", "main")
        b.tm("new-session", "-d", "-s", "main", "-n", "idle", "-x", "120", "-y", "40")
        b.tm("new-session", "-d", "-s", "t1", "-x", "100", "-y", "30")
        w1 = b.tm("display-message", "-p", "-t", "=t1:", "#{window_id}")
        b.tm("new-session", "-d", "-s", "t2", "-x", "160", "-y", "50")
        w2 = b.tm("display-message", "-p", "-t", "=t2:", "#{window_id}")
        b.tm("rename-window", "-t", w1, "tab1")
        b.tm("rename-window", "-t", w2, "tab2")
        b.tm("link-window", "-d", "-a", "-s", w1, "-t", "=main:")
        b.tm("link-window", "-d", "-a", "-s", w2, "-t", "=main:")
        self.assertEqual(sorted(t.name for t in tf.list_tabs()), ["idle", "tab1", "tab2"])
        c1 = b.client(["attach", "-t", "=t1"], 100, 30)
        c2 = b.client(["attach", "-t", "=t2"], 160, 50)
        c3 = b.client(["attach", "-t", "=main"], 120, 40)   # the browser: shows main's current window, "idle"
        time.sleep(1.1)   # client_activity has a resolution of one second
        b.key(c1, b"x")
        self.assertEqual(tf.active_tab().name, "tab1")
        time.sleep(1.1)
        b.key(c2, b"x")
        self.assertEqual(tf.active_tab().name, "tab2")
        time.sleep(1.1)
        b.key(c3, b"x")
        self.assertEqual(tf.active_tab().name, "idle")
        # a control-mode client (what the bus itself may use) is never "the active client", even with the newest activity
        time.sleep(1.1)
        cc = b.client(["-C", "attach", "-t", "=main"], 80, 24)
        b.key(cc, b"list-windows\n")
        rows = b.tm("list-clients", "-F", "#{client_activity} #{client_control_mode} #{client_session}").split("\n")
        self.assertIn("1", [r.split()[1] for r in rows])
        self.assertEqual(tf.active_tab().name, "idle")
        # the window each tab got when it was last resized shows the rule of window-size latest
        sizes = {t.name: b.tm("display-message", "-p", "-t", t.id, "#{window_width}x#{window_height}") for t in tf.list_tabs()}
        self.assertEqual(sizes["tab2"], "160x49")   # 50 rows minus the status line of t2

    def test_active_without_clients_is_the_current_window(self):
        self.b.tm("new-window", "-t", "main", "-n", "two")
        self.assertEqual(tf.active_tab().name, "two")
        self.b.tm("select-window", "-t", "main:one")
        self.assertEqual(tf.active_tab().name, "one")

    def test_panel_panes_are_hidden(self):
        b = self.b
        main_pane = self.pane()
        for opt in ("@swarmbox_sysop_panel", "@swarmbox_voice_panel"):
            p = b.tm("split-window", "-t", "main:", "-P", "-F", "#{pane_id}", "sleep 300")
            b.tm("set-option", "-p", "-t", p, opt, "1")
            self.assertEqual(tf.list_tabs()[0].panes, [main_pane] + [x for x in tf.list_tabs()[0].panes if x != main_pane][:0])
            # the panel has the focus now (split selects it): the tab's pane is still the program's
            self.assertEqual(b.tm("display-message", "-p", "-t", "main:", "#{pane_id}"), p)
            self.assertEqual(tf.list_tabs()[0].pane, main_pane)
            with self.assertRaises(tf.TmuxError):
                tf.resolve(p)   # a panel pane cannot be a target
            b.tm("kill-pane", "-t", p)
        # a window made only of a panel pane is not listed at all
        w = b.tm("new-window", "-d", "-t", "main", "-n", "ghost", "-P", "-F", "#{pane_id}", "sleep 300")
        b.tm("set-option", "-p", "-t", w, "@swarmbox_sysop_panel", "1")
        self.assertNotIn("ghost", [t.name for t in tf.list_tabs()])


class TestScreen(Base):
    def test_capture_modes_and_scrollback(self):
        b = self.b
        b.tm("resize-window", "-t", "main:", "-x", "80", "-y", "12")
        p = self.pane()
        self.type(p, "for i in $(seq 1 40); do echo line$i; done; printf 'long %s\\n' $(printf 'x%.0s' $(seq 1 200))")
        s = tf.screen(p, markers=False)
        self.assertLessEqual(len(s["text"].split("\n")), 12)   # the screen only (trailing empty lines are cut)
        s = tf.screen(p, lines=20, markers=False)
        self.assertEqual(len(s["text"].split("\n")), 20)
        self.assertIn("line30", tf.screen(p, lines=20)["text"])
        self.assertNotIn("line10", tf.screen(p, lines=20)["text"])
        # -J joins the wrapped line: one 205-char line instead of three
        long_lines = [l for l in tf.screen(p, lines=20, markers=False)["text"].split("\n") if l.startswith("long")]
        self.assertEqual(len(long_lines), 1)
        self.assertEqual(len(long_lines[0]), 205)
        plain = b.tm("capture-pane", "-p", "-t", p, "-S", "-20")
        self.assertGreater(len([l for l in plain.split("\n") if l.startswith("x")]), 0)   # without -J the wrap shows as broken lines
        # the cursor, in the cells of the pane
        s = tf.screen(p)
        self.assertEqual(s["cursor"], [int(x) for x in b.tm("display-message", "-p", "-t", p, "#{cursor_x},#{cursor_y}").split(",")])
        self.assertFalse(s["alternate"])

    def test_history_limit_is_the_scrollback(self):
        b = self.b
        b.tm("set", "-g", "history-limit", "100")
        p = b.tm("new-window", "-d", "-t", "main", "-P", "-F", "#{pane_id}")
        self.type(p, "seq 1 500", wait=0.6)
        got = tf.screen(p, lines=100000, markers=False)["text"].split("\n")
        self.assertTrue(got[0].isdigit() and int(got[0]) > 300, got[:3])   # only the last ~100 lines of history exist
        self.assertIn("500", got)

    def test_alternate_screen_programs(self):
        b = self.b
        b.tm("resize-window", "-t", "main:", "-x", "80", "-y", "12")
        p = self.pane()
        self.type(p, "seq 1 100 > /tmp/n.txt; echo BEFORE-LESS")
        self.type(p, "less /tmp/n.txt", wait=0.7)
        s = tf.screen(p, lines=500, markers=False)
        self.assertTrue(s["alternate"])
        rows = s["text"].split("\n")
        self.assertEqual(len(rows), 12)   # -S does not reach the shell's scrollback: only the alternate screen is captured
        self.assertEqual(rows[0], "1")
        self.assertNotIn("BEFORE-LESS", s["text"])
        under = b.tm("capture-pane", "-p", "-a", "-t", p)   # -a: the normal screen saved under the alternate one
        self.assertIn("BEFORE-LESS", under)
        b.tm("send-keys", "-t", p, "q")
        time.sleep(0.3)
        self.assertFalse(tf.screen(p)["alternate"])
        self.type(p, "vim -u NONE /tmp/n.txt", wait=0.9)
        s = tf.screen(p)
        self.assertTrue(s["alternate"])
        self.assertIn('"/tmp/n.txt" 100 lines', s["text"])
        self.assertEqual(s["cursor"], [0, 0])
        b.tm("send-keys", "-t", p, "-l", ":q")
        b.tm("send-keys", "-t", p, "Enter")

    def test_copy_mode_flags_and_screen_underneath(self):
        p = self.pane()
        self.type(p, "echo hello-screen")
        self.b.tm("copy-mode", "-t", p)
        s = tf.screen(p)
        self.assertTrue(s["in_mode"])
        self.assertEqual(s["mode"], "copy-mode")
        self.assertIn("hello-screen", s["text"])

    def test_converter_on_synthetic_sgr(self):
        raw = "\x1b[7mrev\x1b[0m \x1b[1m\x1b[31mERR\x1b[0m \x1b[38;5;33mblue\x1b[39m normal  \n\x1b[7m selected item   \x1b[27m rest\x1b(B\x1b[m\n\x1b[7m   \x1b[0m"
        out = tf.to_marked(raw)
        self.assertEqual(out.split("\n")[0], "[sel]rev[/sel] [err]ERR[/err] blue normal")
        self.assertEqual(out.split("\n")[1], " [sel]selected item[/sel]    rest")
        self.assertEqual(len(out.split("\n")), 2)   # a reverse cell of only spaces (a cursor) is not a marker, and the empty line is cut
        self.assertEqual(tf.to_marked("\x1b[1mbold\x1b[0m", bold=True), "[b]bold[/b]")
        self.assertEqual(tf.to_marked("\x1b[1mbold\x1b[0m"), "bold")
        self.assertEqual(tf.to_marked("\x1b[48;5;237mbg\x1b[49m"), "[bg]bg[/bg]")
        self.assertEqual(tf.to_marked("\x1b[48;5;237mbg\x1b[49m", bg=False), "bg")
        self.assertEqual(tf.to_marked("\x1b[48;5;16m\u2588\u2588\x1b[49m"), "\u2588\u2588")   # blocks of colour, no letters: no marker
        self.assertEqual(tf.to_marked("\x1b[48;5;237ma\x1b[1mb\x1b[0m"), "[bg]ab[/bg]")   # neighbours with the same marker are one span
        self.assertEqual(tf.to_marked("\x1b[38;2;255;0;0mrgb\x1b[39m"), "[err]rgb[/err]")
        self.assertEqual(tf.to_marked("a\x1b]0;title\x07b\x1b[?25lc"), "abc")

    def _fixture(self, name):
        with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as f:
            return f.read()

    def test_converter_on_claude_dialogs(self):
        """Claude Code does NOT use reverse video for the selected option: it uses a colour and the pointer character, which is in the text."""
        perm = self._fixture("claude-permission.raw")
        marked = tf.to_marked(perm)
        self.assertIn("Do you want to proceed?", marked)
        self.assertIn("❯ 1. Yes", marked)
        self.assertNotIn("[sel]", marked)   # nothing is in reverse video: the pointer in the text is the selection
        self.assertNotIn("[bg]❯ 1", marked)
        down = tf.to_marked(self._fixture("claude-permission-down1.raw"))
        self.assertIn("❯ 2. Yes, and always allow", down)
        self.assertIn("  1. Yes", down)
        self.assertNotIn("❯ 1.", down)
        # the raw colour of the selected line (38;5;153 on pointer and text) is what changes; the pointer is the stable signal
        self.assertIn("38;5;153m", self._fixture("claude-permission-down1.raw"))
        self.assertIn("❯ No, exit", tf.to_marked(self._fixture("claude-trust.raw")))
        self.assertIn("❯ ✔ Dark mode", tf.to_marked(self._fixture("claude-theme.raw")))
        # the echo of your own prompt has a background: it is a [bg] span (the logo, made of blocks, is not)
        self.assertIn("[bg]", marked)
        self.assertEqual(marked.count("[bg]"), 1)
        self.assertNotIn("[bg]", tf.to_marked(perm, bg=False))

    def test_menus_fzf_and_select_expose_the_highlight(self):
        b = self.b
        b.tm("resize-window", "-t", "main:", "-x", "80", "-y", "14")
        p = self.pane()
        self.type(p, "printf 'alpha\\nbeta\\ngamma\\n' | fzf --height=8; echo done", wait=0.8)
        b.tm("send-keys", "-t", p, "Down")
        time.sleep(0.4)
        s = tf.screen(p)["text"]
        self.assertRegex(s, r"\[bg\][^\n]*(beta|alpha)[^\n]*\[/bg\]", s)   # fzf: the current line has a background colour, not reverse video
        self.assertEqual(s.count("[bg]"), 1)   # exactly one line is the current one
        fzf_uses_reverse = "\x1b[7m" in b.tm("capture-pane", "-p", "-e", "-t", p)
        b.tm("send-keys", "-t", p, "Enter")
        time.sleep(0.4)
        # bash `select` has no highlight at all: the text is the whole menu
        self.type(p, "clear; bash -c \"PS3='pick> '; select x in red green blue; do break; done\"", wait=0.6)
        s = tf.screen(p)["text"]
        self.assertIn("2) green", s)
        self.assertNotIn("[sel]", s)
        self.assertNotIn("[bg]", s)
        b.tm("send-keys", "-t", p, "-l", "1")
        b.tm("send-keys", "-t", p, "Enter")
        time.sleep(0.4)
        # a reverse-video bar as ncurses menus draw (printf), found by the markers
        self.type(p, "clear; printf '  one\\n\\033[7m  two  \\033[0m\\n  three\\n'", wait=0.4)
        self.assertIn("[sel]two[/sel]", tf.screen(p)["text"])
        print("fzf draws the current line with reverse video (SGR 7): %s" % fzf_uses_reverse, file=sys.stderr)


class TestRedaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not VOICE_LIB:
            raise unittest.SkipTest("the voice library is not mounted")
        sys.path.insert(0, VOICE_LIB)
        from swarmbox_voice import context
        cls.redact = staticmethod(context.redact)

    def test_secrets_next_to_markers_and_codes(self):
        r = self.redact
        k = "sk-" + "a1B2c3D4e5F6g7H8i9J0"
        self.assertNotIn(k, r("[sel]%s[/sel]" % k))
        self.assertNotIn(k, r("key: [sel]%s[/sel] and [err]%s[/err]" % (k, k)))
        self.assertEqual(r("API_TOKEN=[sel]hunter2[/sel]"), "API_TOKEN=[REDACTED]")
        pem = "-----BEGIN RSA PRIVATE KEY-----\n[sel]MIIEowIBAAKCAQEA[/sel]\nabc\n-----END RSA PRIVATE KEY-----"
        self.assertEqual(r("x\n" + pem + "\ny"), "x\n[REDACTED]\ny")
        # a secret split by an escape code is NOT found when the filter runs on the raw -e text: filter the converted text
        raw = "sk-\x1b[1ma1B2c3D4e5F6g7H8i9J0\x1b[0m"
        self.assertIn("a1B2c3D4", r(raw))
        self.assertNotIn("a1B2c3D4", r(tf.to_marked(raw)))
        # a marker never turns into something that hides text: the filter does not touch plain tags
        self.assertEqual(r("[sel]ok[/sel] [err]bad[/err]"), "[sel]ok[/sel] [err]bad[/err]")

    def test_long_lines_are_fast(self):
        r = self.redact
        # context.redact is quadratic on a long run of "-" (the --flag pattern): 5000 chars 0.3 s, 20000 chars 4.4 s, 100000 chars 110 s.
        # That is why screen() cuts every line (clip_lines) BEFORE the filter.
        for line in ("a" * 200000, ("key=" + "b" * 50 + " ") * 4000, "A" * 100000 + "\n" + "A" * 100000, "x" * 50 + ("=" * 5000), "-" * 100000,
                     "-" * 100000 + "\n" + "- " * 50000):
            t = time.time()
            r(tf.clip_lines(line))
            self.assertLess(time.time() - t, 1.0, "slow on %r" % line[:20])
        t = time.time()
        r("\n".join("-" * 1000 for _ in range(60)))   # worst case that gets through the cut: 60 lines of the maximum length
        print("redact of 60 lines of 1000 dashes: %.0f ms" % ((time.time() - t) * 1000), file=sys.stderr)


class TestCost(Base):
    def test_capture_cost_of_ten_windows(self):
        b = self.b
        for i in range(9):
            b.tm("new-window", "-d", "-t", "main", "-n", "w%d" % i)
        for t in tf.list_tabs():
            self.type(t.pane, "seq 1 200", wait=0)
        time.sleep(0.5)
        tabs = tf.list_tabs()
        self.assertEqual(len(tabs), 10)
        t0 = time.time()
        tf.list_tabs()
        t_list = time.time() - t0
        t0 = time.time()
        for t in tabs:
            tf.screen(t, lines=50)
        t_all = time.time() - t0
        t0 = time.time()
        for t in tabs:
            b.tm("capture-pane", "-p", "-J", "-e", "-t", t.pane, "-S", "-50")
        t_raw = time.time() - t0
        print("list_tabs(10 windows): %.1f ms; screen() of 10 windows, 50 lines each: %.1f ms (%.1f ms of it is the raw capture, "
              "one process per window)" % (t_list * 1000, t_all * 1000, t_raw * 1000), file=sys.stderr)
        self.assertLess(t_all, 3.0)


class TestSend(Base):
    PROBE = ("import os,sys,tty\ntty.setraw(0)\nf=open('/tmp/tf-bytes','wb',0)\n"
             "while True:\n    d=os.read(0,4096)\n    f.write(d)\n    if b'\\x04' in d: break\n")

    def probe(self):
        with open(os.path.join(self.b.dir, "probe.py"), "w") as f:
            f.write(self.PROBE)
        try:
            os.unlink("/tmp/tf-bytes")
        except OSError:
            pass
        p = self.pane()
        self.type(p, "python3 %s" % os.path.join(self.b.dir, "probe.py"), wait=0.6)
        return p

    def bytes(self):
        time.sleep(0.3)
        with open("/tmp/tf-bytes", "rb") as f:
            return f.read()

    def test_parse_keys(self):
        P = tf.parse_keys
        self.assertEqual(P("ls{Enter}"), [("text", "ls"), ("key", "Enter")])
        self.assertEqual(P("{Esc}{C-c}{Up}{BSpace}{Tab}"), [("key", "Escape"), ("key", "C-c"), ("key", "Up"), ("key", "BSpace"), ("key", "Tab")])
        self.assertEqual(P("{Enter}{M-x}{F5}"), [("key", "Enter"), ("key", "M-x"), ("key", "F5")])
        self.assertEqual(P("{esc}{ENTER}{C-C}"), [("text", "{esc}{ENTER}{C-C}")])   # case sensitive: only the documented spellings are keys
        self.assertEqual(P("echo ${Home} ${HOME}{Enter}"), [("text", "echo ${Home} ${HOME}"), ("key", "Enter")])   # `${` is never a key
        self.assertEqual(P('echo {"a": 1} ${HOME} {foo}'), [("text", 'echo {"a": 1} ${HOME} {foo}')])   # not keys: literal
        self.assertEqual(P("{{Esc}}"), [("text", "{Esc}")])   # the escape for a literal key-looking text
        self.assertEqual(P("a{{b}}c{Enter}"), [("text", "a{b}c"), ("key", "Enter")])
        self.assertEqual(P(""), [])
        self.assertEqual(P("{Enter}{Enter}"), [("key", "Enter")] * 2)
        self.assertEqual(P("line1\nline2"), [("text", "line1\nline2")])

    def test_bytes_that_reach_the_program(self):
        p = self.probe()
        tf.send(p, "ab{Enter}{Esc}{C-c}{Tab}{BSpace}{Space}x", pause=0.05)
        got = self.bytes()
        self.assertEqual(got, b"ab\r\x1b\x03\t\x7f x")
        tf.send(p, "{Up}{Down}", pause=0.05)
        self.assertEqual(self.bytes()[len(got):], b"\x1b[A\x1b[B")   # normal cursor-key mode of a program that did not ask for application mode
        n = len(self.bytes())
        tf.send(p, 'ç{"a": {{1}}}\tT\\ \'q\' $HOME ; -n', pause=0)
        self.assertEqual(self.bytes()[n:], 'ç{"a": {1}}\tT\\ \'q\' $HOME ; -n'.encode())
        n = len(self.bytes())
        tf.send(p, "one\ntwo", pause=0)
        multi = self.bytes()[n:]
        print("multi-line text 'one\\ntwo' arrives as %r" % multi, file=sys.stderr)
        self.assertEqual(multi, b"one\ntwo")   # send-keys -l sends a newline as LF (0x0a, Ctrl-J), NOT as Enter (CR, 0x0d)
        n = len(self.bytes())
        tf.send(p, "-l", pause=0)
        self.assertEqual(self.bytes()[n:], b"-l")   # a text that starts with a dash is safe because of `--`

    def test_copy_mode_swallows_keys(self):
        b = self.b
        p = self.probe()
        tf.send(p, "before")
        b.tm("copy-mode", "-t", p)
        self.assertEqual(b.tm("display-message", "-p", "-t", p, "#{pane_in_mode}"), "1")
        with self.assertRaises(tf.TmuxError):
            tf.send(p, "lost", cancel_mode=False)
        b.tm("send-keys", "-t", p, "-l", "lost-in-copy-mode")   # the raw way: nothing reaches the program
        self.assertEqual(self.bytes(), b"before")
        self.assertEqual(b.tm("display-message", "-p", "-t", p, "#{pane_in_mode}"), "1")
        tf.send(p, "after")   # send() cancels the mode first
        self.assertEqual(self.bytes(), b"beforeafter")
        self.assertEqual(b.tm("display-message", "-p", "-t", p, "#{pane_in_mode}"), "0")

    def test_bracketed_paste_for_multiline(self):
        """Alternative for several lines: paste-buffer -p (bracketed paste, only when the program asked for it with ESC[?2004h)."""
        b = self.b
        p = self.probe()
        b.tm("set-buffer", "-b", "tfb", "a\nb")
        b.tm("paste-buffer", "-p", "-d", "-b", "tfb", "-t", p)
        plain = self.bytes()
        self.assertEqual(plain, b"a\rb")   # the program did not enable bracketed paste: tmux sends plain text and turns the newline into CR (unlike send-keys -l)
        b.tm("send-keys", "-t", p, "-l", "\x04")

    def test_target_forms(self):
        b = self.b
        b.tm("new-window", "-t", "main", "-n", "two")
        w = b.tm("display-message", "-p", "-t", "main:one", "#{window_id}")
        pid = b.tm("display-message", "-p", "-t", "main:one", "#{pane_id}")
        self.assertEqual(b.tm("display-message", "-p", "-t", pid, "#{window_id}"), w)         # %id alone is global
        self.assertEqual(b.tm("display-message", "-p", "-t", w + "." + pid, "#{pane_id}"), pid)   # @id.%id works
        self.assertEqual(b.tm("display-message", "-p", "-t", w, "#{pane_id}"), pid)             # @id alone: its active pane


class TestEvents(Base):
    def test_control_mode_events(self):
        b = self.b
        proc = subprocess.Popen(["tmux", "-L", b.sock, "-C", "attach", "-t", "main"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=b.env)
        os.set_blocking(proc.stdout.fileno(), False)
        buf = b""

        def drain(t=0.4):
            nonlocal buf
            end = time.time() + t
            while time.time() < end:
                if select.select([proc.stdout], [], [], 0.05)[0]:
                    buf += os.read(proc.stdout.fileno(), 65536)
            lines, buf = buf.split(b"\n")[:-1], buf.split(b"\n")[-1]
            return [l.decode("utf-8", "replace") for l in lines]
        drain(0.5)
        proc.stdin.write(b"refresh-client -B 'w:@*:#{window_name}'\n")   # a format subscription (QUOTED: an unquoted # starts a comment); polled once a second
        proc.stdin.flush()
        drain(0.3)
        t0 = time.time()
        b.tm("new-window", "-d", "-t", "main", "-n", "evt")
        ev = drain(0.3)
        t_add = time.time() - t0
        self.assertTrue(any(l.startswith("%window-add @") for l in ev), ev)
        wid = next(l.split()[1] for l in ev if l.startswith("%window-add"))
        b.tm("rename-window", "-t", wid, "renamed")
        ev = drain(0.3)
        self.assertTrue(any(l.startswith("%window-renamed " + wid + " renamed") for l in ev), ev)
        ev += drain(1.5)   # subscriptions are polled once a second
        self.assertTrue(any(l.startswith("%subscription-changed w") and "renamed" in l for l in ev), ev)
        pane = b.tm("display-message", "-p", "-t", wid, "#{pane_id}")
        drain(0.2)
        b.tm("send-keys", "-t", pane, "-l", "echo OUTPUT-EVENT")
        b.tm("send-keys", "-t", pane, "Enter")
        ev = drain(0.5)
        out = [l for l in ev if l.startswith("%output " + pane)]
        self.assertTrue(out, ev)   # %output carries the bytes (octal escaped) of every pane, even one nobody looks at
        self.assertTrue(any("OUTPUT-EVENT" in l for l in out))
        b.tm("kill-window", "-t", wid)
        ev = drain(0.3)
        self.assertTrue(any(l.startswith("%window-close " + wid) or l.startswith("%unlinked-window-close " + wid) for l in ev), ev)
        b.tm("new-session", "-d", "-s", "other")
        c = b.client(["attach", "-t", "other"], 90, 20)
        ev = drain(0.5)
        print("control-mode events seen: %s; window-add event arrived within %.0f ms" % (sorted({l.split()[0] for l in ev + []}), t_add * 1000), file=sys.stderr)
        proc.stdin.close()
        proc.terminate()
        proc.wait()


class TestHook(Base):
    def test_window_resized_hook_per_window(self):
        """What the dock needs: the hook fires per window, with #{hook_window}, when the client that sizes the window resizes; the
        window other clients do not show is not resized."""
        b = self.b
        log = os.path.join(b.dir, "hook.log")
        b.tm("new-window", "-d", "-t", "main", "-n", "bg")
        b.tm("set-hook", "-g", "window-resized", 'run-shell "echo #{hook_window} #{window_width}x#{window_height} >> %s"' % log)
        c = b.client(["attach", "-t", "main"], 100, 30)
        open(log, "a").close()
        os.truncate(log, 0)
        b.resize(c, 150, 40)
        time.sleep(0.4)
        lines = open(log).read().split("\n")
        shown = b.tm("display-message", "-p", "-t", "main:one", "#{window_id}")
        print("window-resized log after one client resize: %r (shown window %s)" % (lines, shown), file=sys.stderr)
        self.assertTrue(any(l.startswith(shown + " 150x39") for l in lines), lines)
        # the hook runs in the context of the window: #{window_id} works inside the command too
        os.truncate(log, 0)
        b.tm("set-hook", "-g", "window-resized", 'run-shell "echo #{window_id}:#{hook_window}:#{pane_id} >> %s"' % log)
        b.resize(c, 120, 30)
        self.assertRegex(open(log).read(), r"@\d+:@\d+:%\d+")


if __name__ == "__main__":
    unittest.main(verbosity=2)
