"""The panel of the sysop (container/addons/sysop/lib/swarmbox_sysop/panel.py): what it shows and what its keys do, without a terminal.

  * Model and render (pure): every state at several sizes, text that came from a tab or the model made safe, the keys, the guard, the line editor,
    the countdown and its expiry, the approval prompt, the text that does not fit.
  * Panel (the object that the terminal loop drives, with a fake clock, a fake bus and a file as its screen): what it reads from the files of a
    service, what each key writes (decision, stop request, goal on the bus), what it draws.
The program itself on a pty (signals, resize, the real service) is tests/slow/test_sysop_panel_pty.py. No tmux, no network, no model.
"""
import fcntl
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import busclient, ipc, panel, service  # noqa: E402
from swarmbox_sysop.panel import Model, Snap, render, strip_ansi, text_width  # noqa: E402

BIDI = "‮⁦‏؜"


SETTINGS = {"topic": "goal", "autonomy": "confirm-risky", "brain": "claude", "model": "haiku", "panel": "always"}


def snap(goal=None, pending=None, queue=(), up=True, bus="connected", gid="g1", settings=None):
    return Snap(up, bus, gid if goal else "", goal, pending, list(queue), settings or {})


def make_goal(state="running", text="list the files", source="voice", calls=(), say=(), **kw):
    g = {"id": "g1", "source": source, "text": text, "state": state, "created": 1.0, "started": 2.0, "ended": None, "say": list(say), "calls": list(calls),
         "pending": None, "summary": "", "error": "", "note": "", "steps": len(calls), "brain": {}}
    g.update(kw)
    return g


def make_pending(mode="veto", risk="low", deadline=None, text="ls -la", pid="p1", **kw):
    p = {"id": pid, "goal": "g1", "tab": "@1", "label": "0:shell", "kind": "run", "text": text, "risk": risk, "reasons": ["it deletes files"] if risk != "low" else [],
         "mode": mode, "created": time.time(), "deadline": time.time() + 30 if deadline is None else deadline}
    p.update(kw)
    return p


def call(tool="run", args=None, summary="ok", t=10.0, **kw):
    c = {"t": t, "tool": tool, "args": args or {}, "verdict": None, "is_error": False, "summary": summary}
    c.update(kw)
    return c


def frame_text(model, cols=60, rows=24, wall=None):
    f = render(model, cols, rows, time.time() if wall is None else wall, color=False)
    return [strip_ansi(x) for x in f.lines], f


def model_with(goal=None, pending=None, now=0.0, **kw):
    m = Model(now)
    m.update(snap(goal, pending, **kw), now)
    return m


class TakeRequest(unittest.TestCase):
    """Every window has a panel and the approval request is one file: only the panel it names (by its tmux pane) takes it."""

    def setUp(self):
        self.st = FakeState()
        self.addCleanup(self.st.close)
        self.saved = os.environ.get("TMUX_PANE")
        self.addCleanup(lambda: os.environ.pop("TMUX_PANE", None) if self.saved is None else os.environ.__setitem__("TMUX_PANE", self.saved))
        self.p = panel.Panel(self.st.paths, in_fd=-1, out_fd=-1)
        self.addCleanup(lambda: [os.close(fd) for fd in (self.p.wake_r, self.p.wake_w)])
        self.p.model.update(snap(make_goal("waiting_approval"), make_pending("approve", "high")), self.p.now() - 5)

    def request(self, **kw):
        ipc.write_json(self.st.paths.panel_request, dict({"action": "approve", "id": "p1", "time": time.time()}, **kw))

    def test_the_panel_that_is_named_takes_it_and_opens_the_prompt(self):
        os.environ["TMUX_PANE"] = "%5"
        self.request(pane="%5")
        self.p.take_request()
        self.assertEqual(self.p.model.mode, "word")
        self.assertFalse(os.path.exists(self.st.paths.panel_request))

    def test_a_panel_of_another_window_leaves_it_alone(self):
        os.environ["TMUX_PANE"] = "%9"
        self.request(pane="%5")
        self.p.take_request()
        self.assertEqual(self.p.model.mode, "view")
        self.assertTrue(os.path.exists(self.st.paths.panel_request), "not deleted: the panel it is for still has to take it")

    def test_a_request_without_a_pane_is_taken_by_any_panel(self):
        os.environ["TMUX_PANE"] = "%9"
        self.request(pane=None)
        self.p.take_request()
        self.assertEqual(self.p.model.mode, "word")
        self.assertFalse(os.path.exists(self.st.paths.panel_request))

    def test_outside_tmux_any_panel_takes_it(self):
        os.environ.pop("TMUX_PANE", None)
        self.request(pane="%5")
        self.p.take_request()
        self.assertEqual(self.p.model.mode, "word")


class IdleScreen(unittest.TestCase):
    """The idle screen of the panel that is always up: one clear screen, at any size."""

    def idle(self, cols, rows, goal=None, settings=SETTINGS):
        m = model_with(goal, settings=settings)
        m.panel_mode = "always"
        return frame_text(m, cols, rows)[0]

    def test_it_says_what_there_is_and_how_to_give_a_goal(self):
        text = "\n".join(self.idle(70, 24))
        for needle in ("SYSOP", "IDLE", "no goal. Type one: Ctrl+A g", "From any tab: Ctrl+A, then g goal, V veto, X stop, a approve, S hide this panel",
                       "autonomy: confirm-risky", "brain: claude (haiku)", "topic: goal", "[g] Goal", "[q] Hide"):
            self.assertIn(needle, " ".join(text.split()) if len(needle) > 40 else text, needle)
        self.assertNotIn("voice", text.lower(), "the panel does not know the voice addon: it says speak or type")

    def test_the_panel_knows_nothing_of_a_microphone_nor_of_speaking(self):
        keys = [("c", "Veto"), ("x", "Stop"), ("g", "Goal"), ("l", "Log"), ("q", "Hide")]
        lines, _ = panel._key_line(keys, 30, False)
        self.assertEqual(len(lines), 2, "the key line wraps at the width of the pane: nothing covers the last columns any more")
        self.assertFalse(hasattr(panel, "MIC_RESERVE"))
        self.assertNotRegex(panel.IDLE_TEXT.lower(), "speak|voice|micro")

    def test_the_title_is_the_first_line_and_the_screen_has_the_size_of_the_pane(self):
        for cols in (16, 24, 30, 40, 60, 100, 200):
            for rows in (4, 8, 12, 24, 50):
                lines = self.idle(cols, rows)
                self.assertEqual(len(lines), rows, (cols, rows))
                self.assertIn("SYSOP", lines[0])
                self.assertTrue(all(text_width(x) <= max(16, cols) for x in lines), (cols, rows, lines))
                self.assertIn("no goal.", "\n".join(lines), (cols, rows, "the first thing under the title survives any size"))

    def test_what_is_dropped_in_a_short_pane_is_the_least_important_and_the_keys_stay(self):
        short = "\n".join(self.idle(60, 8))
        self.assertIn("no goal. Type one", short)
        self.assertIn("[q] Hide", short)
        self.assertNotIn("topic:", short)
        tall = "\n".join(self.idle(60, 24))
        self.assertIn("topic: goal", tall)
        self.assertLess(tall.index("no goal"), tall.index("From any tab"))
        self.assertLess(tall.index("From any tab"), tall.index("autonomy"))
        self.assertLess(tall.index("autonomy"), tall.index("topic:"))

    def test_in_a_short_pane_the_result_of_the_last_goal_is_on_the_screen(self):
        """found in the e2e screenshot of a phone held upright (28 columns, 8 lines): the panel showed the goal, `49 earlier (Up)` and the idle line, and not the
        result: the marker took the only line the log had. The test used to pass on the DONE badge alone"""
        say = [{"t": 5.0, "text": "I looked at the tab"}] * 12
        g = make_goal("done", "reply with exactly banana 9", "voice", say=say, ended=time.time() - 3, summary="Typed the prompt into the active Claude tab; it replied banana 9.")
        for rows in (8, 9, 10, 12):
            text = " ".join("\n".join(self.idle(28, rows, g)).split())
            self.assertIn("banana 9.", text.split("no goal.")[0], (rows, text))     # the end of the summary, above the idle line
            self.assertIn("no goal.", text, rows)
            self.assertIn("[q] Hide", text, rows)
        long_goal = make_goal("running", "x " * 400, "voice", say=say)
        text = "\n".join(self.idle(28, 8, long_goal))
        self.assertIn("SYSOP", text)

    def test_a_paragraph_of_the_idle_screen_is_whole_or_gone_never_half(self):
        """found in the e2e screenshot of a phone held sideways (64 columns, 8 lines): the hint `From any tab: ...` was cut after `a approve, S`, so it ended
        in a letter that means nothing. A paragraph (a wrapped text) goes whole, the facts (autonomy, brain, topic) go one by one."""
        full = ("From any tab: Ctrl+A, then g goal, V veto, X stop, a approve, S hide this panel. The keys below work after a click on this pane.").split()
        for cols in (28, 30, 40, 64, 100):
            for rows in range(4, 30):
                for goal in (None, make_goal("done", "run the tests", "voice", ended=time.time() - 5, summary="ok")):
                    text = " ".join("\n".join(self.idle(cols, rows, goal)).split())
                    at = text.find("From any tab")
                    if at < 0:
                        continue
                    shown = text[at:].split()
                    seen = []
                    for w in shown:
                        if w in ("[g]", "[q]", "autonomy:", "brain:", "topic:", "last", "say:", "done:"):
                            break
                        seen.append(w)
                    self.assertEqual(seen, full[:len(seen)], (cols, rows))
                    self.assertIn(len(seen), (len(full) - 9, len(full)), "the hint is the sentence or the sentence and the note, not a piece (%d cols, %d rows): %r" % (cols, rows, seen))

    def test_the_last_goal_is_shown_with_how_it_ended_and_what_was_said(self):
        for state, key, why in (("done", "summary", "tests pass"), ("failed", "error", "the brain crashed"), ("stopped", "error", "stopped by the user")):
            g = make_goal(state, "run the tests", "voice", say=[{"t": 5.0, "text": "I looked at the tab"}], ended=time.time() - 125, **{key: why})
            text = "\n".join(self.idle(70, 30, g))
            self.assertIn("last goal (voice, 2 min ago): run the tests", text)
            self.assertIn("say: I looked at the tab", text)
            self.assertIn("%s: %s" % (state, why), text)
            self.assertIn("no goal. Type one", text, "and it is idle: the way to give another one is there")
            self.assertIn("autonomy: confirm-risky", text)

    def test_while_a_goal_runs_or_waits_there_is_no_idle_text(self):
        for m in (model_with(make_goal("running")), model_with(make_goal("running"), make_pending("veto")), model_with(make_goal("queued"), queue=[{"id": "g2", "source": "cli", "text": "x"}])):
            text = "\n".join(frame_text(m, 70, 30)[0])
            self.assertNotIn("no goal.", text)
            self.assertNotIn("topic:", text)

    def test_the_service_down_has_its_own_screen(self):
        text = "\n".join(frame_text(model_with(up=False, settings=SETTINGS), 70, 24)[0])
        self.assertIn("SERVICE DOWN", text)
        self.assertNotIn("no goal.", text)

    def test_a_service_without_settings_still_gives_a_screen(self):
        text = "\n".join(self.idle(60, 24, settings={}))
        self.assertIn("no goal. Type one", text)
        self.assertNotIn("autonomy", text)

    def test_text_in_the_settings_is_made_safe(self):
        text = "\n".join(self.idle(80, 24, settings=dict(SETTINGS, brain="x\x1b[31mred", topic="t\x07")))
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)

    def test_the_quit_key_says_hide_in_the_mode_always_and_close_in_the_others(self):
        m = model_with(settings=SETTINGS)
        self.assertIn("[q] Close", "\n".join(frame_text(m)[0]))
        m.panel_mode = "always"
        self.assertIn("[q] Hide", "\n".join(frame_text(m)[0]))

    def test_ago(self):
        for secs, want in ((0, "just now"), (9, "just now"), (10, "10 s ago"), (59, "59 s ago"), (60, "1 min ago"), (3599, "59 min ago"), (3600, "1 h ago"), (86400 * 3, "3 d ago")):
            self.assertEqual(panel.ago(secs), want)

    def test_quiet_is_idle_and_not_typing(self):
        self.assertFalse(Model().quiet(), "not looked yet")
        self.assertTrue(model_with().quiet())
        self.assertTrue(model_with(make_goal("done")).quiet())
        self.assertTrue(model_with(up=False).quiet(), "down: it only waits for the service to come")
        self.assertFalse(model_with(make_goal("running")).quiet())
        self.assertFalse(model_with(make_goal("queued"), queue=[{"id": "g2", "source": "cli", "text": "x"}]).quiet())
        self.assertFalse(model_with(make_goal("running"), make_pending()).quiet())
        m = model_with()
        m.key("g", 5.0, time.time())
        self.assertFalse(m.quiet(), "typing a goal: look often")


class Rendering(unittest.TestCase):
    def test_every_state_fits_every_size(self):
        states = {
            "idle": model_with(),
            "down": model_with(up=False),
            "queued": model_with(make_goal("queued"), queue=[{"id": "g2", "source": "cli", "text": "later"}]),
            "running": model_with(make_goal("running", calls=[call("list_tabs", summary="[ {tab}"), call("run", {"tab": "@1", "command": "ls"}, "a.txt b.txt")], say=[{"t": 11.0, "text": "found it"}])),
            "veto": model_with(make_goal(), make_pending("veto")),
            "approve": model_with(make_goal("waiting_approval"), make_pending("approve", "high", text="rm -rf ~/work")),
            "done": model_with(make_goal("done", summary="all done")),
            "failed": model_with(make_goal("failed", error="the brain crashed", note="a note")),
        }
        for name, m in states.items():
            for cols in (16, 20, 30, 40, 60, 100, 200):
                for rows in (4, 6, 10, 24, 50):
                    for color in (False, True):
                        f = render(m, cols, rows, time.time(), color)
                        self.assertEqual(len(f.lines), rows, (name, cols, rows))
                        for ln in f.lines:
                            self.assertLessEqual(text_width(strip_ansi(ln)), max(16, cols), (name, cols, rows, strip_ansi(ln)))
                        self.assertIn("[q]" if color else "[q]", " ".join(strip_ansi(x) for x in f.lines), (name, cols, rows, "the close key is always visible"))

    def test_the_goal_its_source_the_steps_and_the_queue(self):
        g = make_goal("running", "open the logs of the api", "voice", calls=[
            call("list_tabs", summary='[{"tab":"@1"}]', t=1), call("run", {"tab": "@1", "command": "tail -f api.log"}, "line one\nline two", t=2, verdict="medium"),
            call("run", {"tab": "@9", "command": "x"}, "error: no such tab", t=3, is_error=True)], say=[{"t": 2.5, "text": "I opened the log"}])
        m = model_with(g, queue=[{"id": "g2", "source": "cli", "text": "second goal"}, {"id": "g3", "source": "panel", "text": "third"}])
        lines, _ = frame_text(m, 70, 30)
        text = "\n".join(lines)
        for needle in ("goal (voice): open the logs of the api", "> list_tabs", "> run @1 tail -f api.log [medium]", "= line one | line two", "say: I opened the log",
                       "! error: no such tab", "queue 1 (cli): second goal", "queue 2 (panel): third", "2 queued", "RUNNING", "[x] Stop", "[g] Goal"):
            self.assertIn(needle, text)
        order = [text.index(x) for x in ("> list_tabs", "> run @1 tail", "say: I opened", "> run @9")]
        self.assertEqual(order, sorted(order), "calls and says in time order")

    def test_the_log_shows_its_end_and_scrolls(self):
        calls = [call("run", {"command": "step %d" % i}, "r%d" % i, t=float(i)) for i in range(12)]
        m = model_with(make_goal(calls=calls))
        lines, _ = frame_text(m, 50, 12)
        text = "\n".join(lines)
        self.assertIn("step 11", text)
        self.assertNotIn("step 0", text)
        self.assertIn("earlier (Up)", text)
        for _ in range(40):
            m.key("up", 5.0, time.time())
        lines, _ = frame_text(m, 50, 12)
        text = "\n".join(lines)
        self.assertIn("step 0", text)
        self.assertNotIn("step 11", text)
        self.assertIn("later (Down)", text)
        m.key("end", 5.0, time.time())
        self.assertEqual(m.scroll, 0)

    def test_text_from_tabs_and_the_model_is_printed_safe(self):
        evil = "\x1b]0;pwned\x07\x1b[2J\x1b[31mred" + BIDI + "end\x00\x07\x7f "
        g = make_goal(text="do " + evil, source="vo\x1bice", calls=[call("run", {"tab": "@1", "command": evil}, evil, verdict=evil)], say=[{"t": 20, "text": evil}],
                      summary=evil, state="done", note=evil)
        p = make_pending("approve", "high", text=evil, label=evil, reasons=[evil], kind=evil)
        for m in (model_with(g, queue=[{"id": "q", "source": evil, "text": evil}]), model_with(make_goal(calls=g["calls"], say=g["say"], text=evil, source=evil), p)):
            f = render(m, 80, 40, time.time(), True)
            for ln in f.lines:
                plain = re.sub(r"\x1b\[[0-9;]*m", "", ln)
                self.assertNotRegex(plain, r"[\x00-\x08\x0b-\x1f\x7f\x1b  " + BIDI + "]", plain)
                self.assertNotIn("pwned\x07", plain)
            self.assertIn("�", "\n".join(f.lines), "the characters are replaced, not dropped")
        self.assertEqual(panel.clean("a\x1b[1mb‮c\n"), "a�[1mb�c\n")

    def test_a_long_text_wraps_to_the_width(self):
        m = model_with(make_goal(text="word " * 80), make_pending("veto", text="x" * 300))
        for cols in (20, 33, 61):
            lines, _ = frame_text(m, cols, 40)
            self.assertTrue(all(text_width(x) <= cols for x in lines), cols)
        self.assertGreater(len([x for x in frame_text(m, 30, 60)[0] if "word" in x]), 1)

    def test_the_countdown_and_the_approval_prompt(self):
        now = time.time()
        m = model_with(make_goal(), make_pending("veto", deadline=now + 3.2, text="echo hi"))
        text = "\n".join(frame_text(m, 70, 24, now)[0])
        for needle in ("COUNTDOWN", "echo hi", "tab 0:shell: run", "sent in 4 s unless you veto it", "Ctrl+A V", "[c] Veto"):
            self.assertIn(needle, text)
        self.assertNotIn("[g] Goal", text, "no new goal while an action waits")
        self.assertIn("sent in 1 s", "\n".join(frame_text(m, 70, 24, now + 2.5)[0]))
        self.assertIn("sending now", "\n".join(frame_text(m, 70, 24, now + 3.3)[0]))
        m = model_with(make_goal(), make_pending("approve", "high", deadline=now + 45, text="rm -rf ~/x"))
        text = "\n".join(frame_text(m, 70, 24, now)[0])
        for needle in ("APPROVAL", "HIGH RISK", "rm -rf ~/x", "why: it deletes files", "NOT sent unless you allow it", "0:45", "[r] Allow (type run)", "[c] Refuse"):
            self.assertIn(needle, text)
        self.assertIn("time is up: refused", "\n".join(frame_text(m, 70, 24, now + 46)[0]))
        m.key("r", 5.0, now)
        text = "\n".join(frame_text(m, 70, 24, now)[0])
        self.assertIn("type the word run, then Enter", text)
        self.assertIn(" > ", text)

    def test_the_risk_is_a_word_as_well_as_a_colour(self):
        for risk in ("low", "medium", "high", "nonsense"):
            m = model_with(make_goal(), make_pending("veto", risk))
            self.assertIn(("HIGH" if risk == "nonsense" else risk.upper()) + " RISK", "\n".join(frame_text(m, 70, 24)[0]))

    def test_hits_are_the_key_labels(self):
        m = model_with(make_goal())
        f = render(m, 60, 12, time.time(), True)
        keys = [h[3] for h in f.hits]
        self.assertEqual(keys, ["x", "g", "q"])
        for row, c0, c1, key in f.hits:
            self.assertIn("[%s]" % key, strip_ansi(f.lines[row - 1])[c0 - 1:c1 + 1])


class Keys(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def veto_model(self, **kw):
        return model_with(make_goal(), make_pending("veto", deadline=self.now + 30, **kw), now=100.0)

    def test_keys_are_ignored_for_half_a_second_after_a_new_action(self):
        m = self.veto_model()
        self.assertIsNone(m.key("c", 100.4, self.now))
        self.assertEqual(m.key("c", 100.6, self.now), ("decide", "g1", "p1", "veto", None))
        m.update(snap(make_goal(), make_pending("veto", pid="p2", deadline=self.now + 30)), 200.0)
        self.assertIsNone(m.key("c", 200.1, self.now), "the next action has its own guard")
        self.assertEqual(m.key("c", 200.6, self.now)[2], "p2")
        m.update(snap(make_goal(), make_pending("veto", pid="p2", deadline=self.now + 30)), 300.0)
        self.assertEqual(m.key("c", 300.0, self.now)[2], "p2", "the same action seen again starts no new guard")

    def test_c_vetoes_a_countdown_and_refuses_an_approval(self):
        self.assertEqual(self.veto_model().key("C", 101.0, self.now), ("decide", "g1", "p1", "veto", None))
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now + 30), now=100.0)
        self.assertEqual(m.key("c", 101.0, self.now), ("decide", "g1", "p1", "deny", None))
        self.assertIsNone(model_with(make_goal(), now=100.0).key("c", 101.0, self.now), "nothing waits: c does nothing")

    def test_an_unknown_mode_is_an_approval(self):
        m = model_with(make_goal(), make_pending("whatever", deadline=self.now + 30), now=100.0)
        self.assertEqual(m.pmode(), "approve")
        m.key("r", 101.0, self.now)
        self.assertEqual(m.mode, "word")

    def test_the_approval_needs_the_word_run_and_enter(self):
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now + 30), now=100.0)
        for k in ("y", "enter", "a", "x", "g"):
            self.assertIsNone(m.key(k, 101.0, self.now) if k != "x" else None)
        self.assertEqual(m.mode, "view", "no key but r starts the typing; y, a and Enter alone allow nothing")
        m.key("r", 101.0, self.now)
        self.assertEqual(m.mode, "word")
        for k in "yes":
            self.assertIsNone(m.key(k, 101.0, self.now))
        self.assertIsNone(m.key("enter", 101.0, self.now), "a wrong word allows nothing")
        self.assertIn("Not allowed", m.notice)
        self.assertEqual(m.mode, "view")
        m.key("r", 101.0, self.now)
        for k in "run":
            m.key(k, 101.0, self.now)
        self.assertEqual(m.key("enter", 101.0, self.now), ("decide", "g1", "p1", "approve", "run"))
        m.key("r", 101.0, self.now)
        for k in "RUN":
            m.key(k, 101.0, self.now)
        self.assertEqual(m.key("enter", 101.0, self.now)[3], "approve", "the word is not case sensitive")
        m.key("r", 101.0, self.now)
        m.key("r", 101.0, self.now)
        m.key("esc", 101.0, self.now)
        self.assertEqual((m.mode, m.word), ("view", ""))

    def test_r_does_nothing_for_a_countdown(self):
        m = self.veto_model()
        m.key("r", 101.0, self.now)
        self.assertEqual(m.mode, "view")

    def test_nothing_is_decided_after_the_deadline(self):
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now - 1), now=100.0)
        self.assertIsNone(m.key("c", 101.0, self.now))
        self.assertIsNone(m.key("r", 101.0, self.now))
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now + 0.5), now=100.0)
        m.key("r", 101.0, self.now)
        for k in "run":
            m.key(k, 101.0, self.now)
        self.assertIsNone(m.key("enter", 101.0, self.now + 1), "the word typed too late allows nothing")
        self.assertIn("time is up", m.notice)

    def test_the_action_vanishing_ends_the_word_mode(self):
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now + 30), now=100.0)
        m.key("r", 101.0, self.now)
        m.key("r", 101.0, self.now)
        m.update(snap(make_goal()), 102.0)
        self.assertEqual((m.mode, m.word), ("view", ""))

    def test_x_stops_the_goal_and_big_x_everything(self):
        m = model_with(make_goal(), now=0.0)
        self.assertEqual(m.key("x", 1.0, self.now), ("stop", "g1"))
        self.assertEqual(m.key("X", 1.0, self.now), ("stop", None))
        m = model_with(make_goal("done"), queue=[{"id": "g7", "source": "cli", "text": "t"}])
        self.assertEqual(m.key("x", 1.0, self.now), ("stop", "g7"), "no goal runs: the first of the queue")
        m = model_with()
        self.assertIsNone(m.key("x", 1.0, self.now))
        self.assertIn("no goal to stop", m.notice)

    def test_q_and_ctrl_c_close(self):
        for k in ("q", "Q", "ctrl-c"):
            self.assertEqual(model_with().key(k, 1.0, self.now), ("quit",))

    def test_g_types_a_goal_with_the_line_editor(self):
        m = model_with()
        m.key("g", 1.0, self.now)
        self.assertEqual(m.mode, "edit")
        for k in "open the logs":
            m.key(k, 1.0, self.now)
        m.key("left", 1.0, self.now)
        m.key("backspace", 1.0, self.now)
        m.key("home", 1.0, self.now)
        m.key("X", 1.0, self.now)
        self.assertEqual(m.editor.text, "Xopen the los", "left, backspace (deletes the g), home, X")
        self.assertIsNone(m.key("q", 1.0, self.now), "q is text while you type")
        self.assertEqual(m.key("enter", 1.0, self.now), ("goal", "Xqopen the los"))
        self.assertEqual(m.mode, "view")
        m.key("g", 1.0, self.now)
        self.assertIsNone(m.key("enter", 1.0, self.now), "an empty line sends nothing")
        m.key("g", 1.0, self.now)
        m.key("a", 1.0, self.now)
        m.key("esc", 1.0, self.now)
        self.assertEqual((m.mode, m.draft), ("view", ""))
        m.key("g", 1.0, self.now)
        self.assertEqual(m.editor.text, "")

    def test_typing_a_goal_yields_to_an_action_that_appears_and_keeps_the_text(self):
        m = model_with(make_goal(), now=0.0)
        m.key("g", 1.0, self.now)
        for k in "half a goal":
            m.key(k, 1.0, self.now)
        m.update(snap(make_goal(), make_pending("veto", deadline=self.now + 30)), 2.0)
        self.assertEqual((m.mode, m.draft), ("view", "half a goal"))
        self.assertIn("answer it first", m.notice)
        self.assertEqual(m.key("c", 2.6, self.now)[3], "veto", "the key is for the countdown now, not for the text")
        m.update(snap(make_goal()), 3.0)
        m.key("g", 3.0, self.now)
        self.assertEqual(m.editor.text, "half a goal")

    def test_g_is_refused_while_the_service_is_down(self):
        m = model_with(up=False)
        self.assertIsNone(m.key("g", 5.0, time.time()))
        self.assertIn("not running", m.notice)

    def test_g_is_refused_while_an_action_waits(self):
        m = self.veto_model()
        m.key("g", 101.0, self.now)
        self.assertEqual(m.mode, "view")
        self.assertIn("answer it first", m.notice)

    def test_scroll_keys(self):
        m = model_with(make_goal())
        for k, want in (("up", 1), ("up", 2), ("pgup", 7), ("down", 6), ("pgdn", 1), ("pgdn", 0), ("down", 0), ("home", 10 ** 6), ("end", 0)):
            m.key(k, 1.0, self.now)
            self.assertEqual(m.scroll, want, k)

    def test_the_mouse_is_no_key_for_the_model(self):
        self.assertIsNone(model_with().key(("click", 3, 3), 1.0, self.now))


class ApprovalRequest(unittest.TestCase):
    """`swarmbox-sysop approve` asks the panel for its approval prompt (Model.request_approve); keys.py then gives it the focus."""
    REQ = {"action": "approve", "id": "p1"}

    def approval(self, now=0.0, **kw):
        kw.setdefault("text", "rm -rf ~/x")
        return model_with(make_goal("waiting_approval"), make_pending("approve", "high", **kw), now=now)

    def test_the_request_opens_the_word_prompt_of_the_pending_approval(self):
        m = self.approval()
        self.assertEqual(m.request_approve(self.REQ, 1.0, time.time()), "ok")
        self.assertEqual((m.mode, m.word), ("word", ""))
        self.assertIsNone(m.key("x", 1.0, time.time()), "in the word prompt x is a letter, not a stop")
        self.assertEqual(m.word, "x")

    def test_the_key_guard_of_a_new_action_still_holds(self):
        m = self.approval(now=10.0)
        self.assertEqual(m.request_approve(self.REQ, 10.1, time.time()), "wait", "the request stays until the guard has passed")
        self.assertEqual(m.mode, "view")
        self.assertEqual(m.request_approve(self.REQ, 10.0 + panel.GUARD + 0.01, time.time()), "ok")

    def test_a_request_for_another_action_a_countdown_or_nothing_is_dropped(self):
        for m, req in ((self.approval(), {"action": "approve", "id": "p9"}), (self.approval(), {"action": "stop", "id": "p1"}),
                       (model_with(make_goal(), make_pending("veto")), self.REQ), (model_with(make_goal()), self.REQ),
                       (self.approval(deadline=time.time() - 1), self.REQ)):
            self.assertEqual(m.request_approve(req, 5.0, time.time()), "no")
            self.assertEqual(m.mode, "view")

    def test_an_action_that_does_not_fit_says_so_and_cannot_be_allowed(self):
        """the word `run` allows what is on the screen: text that is cut off could hide the end of a command ("...; rm -rf ~")"""
        text = "rm -rf ./build-cache " + "# cleaning the build cache ... " * 80 + "; rm -rf ~"
        m = self.approval(text=text)
        joined = "\n".join(frame_text(m, 40, 40)[0])
        self.assertGreater(m.hidden, 0)
        self.assertIn("NOT shown", joined)
        self.assertIn("only refused", " ".join(joined.split()))
        self.assertNotIn("Allow", joined)
        m.key("r", 100.0, time.time())
        self.assertNotEqual(m.mode, "word", "the word `run` cannot be typed for text that is not on the screen")
        self.assertEqual(m.request_approve(self.REQ, 5.0, time.time()), "no", "nor can `swarmbox-sysop approve` open it")
        self.assertEqual(m.mode, "view")

    def test_a_command_of_600_characters_is_shown_whole_on_a_wide_pane(self):
        """a past bug: the budget of the pane hid the end of a 615 character command that did fit"""
        m = self.approval(text="rm -rf ./build-cache " + "# cleaning the build cache ... " * 20 + "; rm -rf ~")
        self.assertIn("; rm -rf ~", " ".join(" ".join(frame_text(m, 200, 40)[0]).split()))
        self.assertEqual(m.hidden, 0)

    def test_losing_the_focus_drops_a_half_typed_word(self):
        pn = panel.Panel(pth=None, in_fd=-1, out_fd=-1, bus=object())
        pn.model = self.approval()
        pn.model.request_approve(self.REQ, 5.0, time.time())
        pn.model.word = "ru"
        pn.handle_key("focus-out")
        self.assertEqual((pn.model.mode, pn.model.word, pn.model.focused), ("view", "", False))
        pn.handle_key("focus-in")
        self.assertTrue(pn.model.focused)

    def test_the_text_says_which_keys_work_unfocused_and_drops_it_when_focused(self):
        m = self.approval()
        text = " ".join(frame_text(m, 70, 30)[0])
        for needle in ("Ctrl+A a, then type run", "type run", "Ctrl+A, then V veto, X stop, a approve, g goal"):
            self.assertIn(needle, text)
        m.focused = True
        self.assertNotIn("Ctrl+A, then V", " ".join(frame_text(m, 70, 30)[0]))


class KeyBytes(unittest.TestCase):
    def test_the_parser(self):
        kp = panel.KeyParser()
        self.assertEqual(kp.feed(b"cX\x1b[A\x1b[B\x1b[5~\x1b[6~\r\x7f\x03"), ["c", "X", "up", "down", "pgup", "pgdn", "enter", "backspace", "ctrl-c"])
        self.assertEqual(kp.feed(b"\x1b"), [])
        self.assertEqual(kp.flush(), ["esc"])
        self.assertEqual(kp.feed("é".encode()), ["é"])
        self.assertEqual(kp.feed(b"\x1b[<64;5;5M\x1b[<0;7;3M"), [("wheel", "up"), ("click", 7, 3)])


# ---------------------------------------------------------------------------------------------------------------------- the pty

class FakeState:
    """The folders and files of a service, written by hand: what the panel reads (ipc.py)."""

    def __init__(self):
        self.e = ss.Env()
        self.paths = self.e.paths.make()
        self.lock_fd = None

    def serve(self, on=True, **status):
        """hold the single-instance lock like a running service, and write status.json"""
        if on and self.lock_fd is None:
            self.lock_fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not on and self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
        if on:
            st = {"pid": os.getpid(), "version": "1", "started": 1.0, "updated": time.time(), "bus": "connected", "current": None, "queue": [], "rejected": 0, "settings": {}}
            st.update(status)
            ipc.write_json(self.paths.status, st)

    def goal(self, gid="g1", **kw):
        os.makedirs(self.paths.goal_dir(gid), exist_ok=True)
        g = make_goal(**kw)
        g["id"] = gid
        ipc.write_json(os.path.join(self.paths.goal_dir(gid), "state.json"), g)
        return g

    def pending(self, gid="g1", **kw):
        ipc.write_json(os.path.join(self.paths.goal_dir(gid), "pending_action.json"), make_pending(**kw))

    def clear_pending(self, gid="g1"):
        ipc.remove(os.path.join(self.paths.goal_dir(gid), "pending_action.json"))

    def decision(self, gid="g1"):
        return ipc.read_json(os.path.join(self.paths.goal_dir(gid), "decision.json"))

    def stop_request(self):
        return ipc.read_json(self.paths.stop_request)

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
        self.e.cleanup()


class FakeBus:
    """what Panel needs of busclient.Bus: pub(topic, body, source); an error to raise, the calls to read"""

    def __init__(self, error=None):
        self.error, self.pubs = error, []

    def pub(self, topic, body, source):
        if self.error:
            raise self.error
        self.pubs.append((topic, body, source))


class PanelObject(unittest.TestCase):
    """The Panel that the terminal loop drives, with a fake clock, a fake bus and a file as its screen: what it reads from the files of a service,
    what each key writes, what it draws. (The real program on a pty: tests/slow/test_sysop_panel_pty.py.)"""

    def setUp(self):
        self.st = FakeState()
        self.addCleanup(self.st.close)
        self.clock = [100.0]
        self.bus = FakeBus()
        self.screen = tempfile.TemporaryFile()
        self.addCleanup(self.screen.close)
        self.p = panel.Panel(self.st.paths, in_fd=-1, out_fd=self.screen.fileno(), now=lambda: self.clock[0], bus=self.bus, color=False)
        self.addCleanup(lambda: [os.close(fd) for fd in (self.p.wake_r, self.p.wake_w)])
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop("TMUX_PANE", None)
        os.environ.pop("SWARMBOX_SYSOP_TOPIC", None)

    def text(self):
        return "\n".join(strip_ansi(x) for x in render(self.p.model, 80, 30, time.time(), False).lines)

    def see(self):
        self.p.look()
        return self.text()

    def keys(self, *ks, wait=1.0):
        self.clock[0] += wait                 # past the guard against stray typing
        for k in ks:
            self.p.handle_key(k)

    def test_it_shows_what_the_service_writes_and_follows_it(self):
        self.assertIn("SERVICE DOWN", self.see())
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "the next one"}])
        self.st.goal(calls=[call("run", {"tab": "@1", "command": "make test"}, "ok 12 tests")], say=[{"t": 20.0, "text": "running the tests"}], text="run the tests")
        text = self.see()
        for needle in ("goal (voice): run the tests", "> run @1 make test", "= ok 12 tests", "say: running the tests", "queue 1 (cli): the next one", "RUNNING"):
            self.assertIn(needle, text)
        gdir = self.st.paths.goal_dir("g1")                  # the files of the mcp server are fresher than state.json
        ipc.append_jsonl(os.path.join(gdir, "calls.jsonl"), call("read_tab", {"tab": "@2"}, "screen text", t=30))
        ipc.append_jsonl(os.path.join(gdir, "say.jsonl"), {"t": 31, "text": "fresher than state.json"})
        text = self.see()
        self.assertIn("> read_tab @2", text)
        self.assertIn("fresher than state.json", text)
        self.st.goal(state="done", summary="tests pass")      # the end of the goal stays on screen under the idle text
        self.st.serve(current=None, settings=dict(SETTINGS))
        text = self.see()
        self.assertIn("done: tests pass", text)
        self.assertIn("no goal. Type one: Ctrl+A g", text)
        self.st.serve(on=False)
        self.assertIn("SERVICE DOWN", self.see())

    def test_the_last_goal_that_ended_between_two_looks_is_shown(self):
        self.st.serve(settings=dict(SETTINGS))
        self.st.goal(state="done", summary="tests pass", text="run the tests", ended=time.time() - 30, say=[{"t": 1.0, "text": "all green"}])
        text = self.see()
        for needle in ("last goal (voice, ", "run the tests", "say: all green", "done: tests pass", "no goal. Type one", "topic: goal"):
            self.assertIn(needle, text)

    def test_an_idle_panel_looks_only_when_a_file_changed(self):
        """the idle panel costs almost no CPU: a stat of two files and a lock probe, a full look only on a change (a past bug: a look every turn)"""
        self.st.serve(settings=dict(SETTINGS))
        self.assertTrue(self.p.changed())
        self.assertFalse(self.p.changed())
        self.st.serve(settings=dict(SETTINGS, brain="other"))
        self.assertTrue(self.p.changed(), "status.json was written")
        self.assertFalse(self.p.changed())
        self.st.serve(on=False)
        self.assertTrue(self.p.changed(), "the service went away")

    def test_the_veto_key_writes_the_decision_once_the_guard_has_passed(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() + 20)
        self.p.look()
        self.p.handle_key("c")                         # typing meant for another pane, at the moment the action appeared
        self.assertIsNone(self.st.decision(), "showing an action decides nothing, and the guard ignores the key")
        self.keys("c")
        self.assertEqual(self.st.decision(), {"id": "p1", "decision": "veto", "by": "panel"})
        self.assertEqual(os.stat(os.path.join(self.st.paths.goal_dir("g1"), "decision.json")).st_mode & 0o777, 0o600)
        self.assertIn("Vetoed: it will not be sent.", self.text())

    def test_an_expired_countdown_and_an_expired_approval_cannot_be_answered(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() - 1)
        self.p.look()
        self.assertIn("sending now", self.text())
        self.keys("c")
        self.assertIsNone(self.st.decision(), "the time is up: the service decides")
        self.st.pending(mode="approve", risk="high", deadline=time.time() - 1, pid="p2")
        self.p.look()
        self.assertIn("time is up: refused", self.text())
        self.keys("r", "r", "u", "n", "enter")
        self.assertIsNone(self.st.decision())

    def test_the_approval_gesture_writes_a_decision_only_with_the_word(self):
        self.st.serve(current="g1")
        self.st.goal(state="waiting_approval")
        self.st.pending(mode="approve", risk="high", text="rm -rf ~/work", deadline=time.time() + 30)
        text = self.see()
        for needle in ("HIGH RISK", "rm -rf ~/work", "why: it deletes files", "[r] Allow (type run)", "[c] Refuse"):
            self.assertIn(needle, text)
        self.keys("y", "enter", "a", "enter")
        self.assertIsNone(self.st.decision(), "no key but the word allows a high-risk action")
        self.keys("r", "y", "e", "s", "enter")
        self.assertIsNone(self.st.decision())
        self.assertIn("Not allowed", self.text())
        self.keys("r", "r", "u", "n")
        self.assertIn("> run", self.text())
        self.keys("enter")
        self.assertEqual(self.st.decision(), {"id": "p1", "decision": "approve", "by": "panel", "word": "run"})

    def test_c_refuses_an_approval_and_esc_leaves_the_word_prompt(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="approve", risk="high", deadline=time.time() + 30)
        self.see()
        self.keys("r")
        self.assertIn("type the word run", self.text())
        self.keys("esc")
        self.assertIn("[r] Allow", self.text())
        self.assertIsNone(self.st.decision())
        self.keys("c")
        self.assertEqual(self.st.decision(), {"id": "p1", "decision": "deny", "by": "panel"})

    def test_x_asks_the_service_to_stop_the_goal_and_big_x_everything(self):
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "q"}])
        self.st.goal()
        self.see()
        self.keys("x")
        self.assertEqual(self.st.stop_request()["goal"], "g1")
        self.assertIn("Stop requested (this goal).", self.text())
        ipc.remove(self.st.paths.stop_request)
        self.keys("X")
        self.assertIsNone(self.st.stop_request()["goal"], "capital X: the goal and the queue")

    def test_q_closes_in_every_mode_but_typing_and_answers_nothing(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() + 30)
        self.see()
        self.keys("q")
        self.assertTrue(self.p.model.finished)
        self.assertIsNone(self.st.decision(), "closing the panel answers nothing: the countdown sends the action")

    def test_a_goal_typed_in_the_panel_goes_to_the_bus_with_the_source_panel(self):
        self.st.serve(settings=dict(SETTINGS))
        self.see()
        self.keys("g")
        for ch in "open the api logs":
            self.p.handle_key(ch)
        self.assertEqual(self.bus.pubs, [], "typing publishes nothing")
        for k in ("left", "left", "left", "left", "delete"):         # the editor edits
            self.p.handle_key(k)
        self.p.handle_key("enter")
        self.assertEqual(self.bus.pubs, [("goal", {"text": "open the api ogs"}, "panel")])
        self.assertEqual(self.p.model.notice, "Goal sent.")

    def test_the_goal_goes_to_the_topic_of_the_setting(self):
        os.environ["SWARMBOX_SYSOP_TOPIC"] = "ops.goals"
        self.st.serve()
        self.see()
        self.keys("g", "x", "enter")
        self.assertEqual([p[0] for p in self.bus.pubs], ["ops.goals"])

    def test_a_goal_that_was_not_taken_says_why_and_keeps_the_text(self):
        for code, words in (("no_subscriber", "The sysop is not running: nobody takes the goal"), ("bus_down", "the bus is not answering")):
            self.bus.error = busclient.BusError(code)
            self.st.serve()
            self.see()
            self.keys("g", "h", "i", "enter")
            self.assertIn(words, self.text())
            self.keys("esc")                     # leave the notice's mode
            self.keys("g")
            self.assertEqual(self.p.model.editor.text, "hi", "the text is kept: g gives it back")
            self.keys("esc")
        self.keys("g")
        self.p.model.editor.text = "x" * (service.MAX_GOAL_TEXT + 1)
        self.p.handle_key("enter")
        self.assertIn("at most %d" % service.MAX_GOAL_TEXT, self.p.model.notice)

    def test_what_it_draws_has_no_control_text_from_a_tab(self):
        """text of a tab or the model reaches the terminal only as printable text: only the escape sequences of the panel itself are in the bytes"""
        evil = "\x1b]0;pwned\x07\x1b[2Jbig" + BIDI
        self.st.serve(current="g1")
        self.st.goal(text="goal " + evil, calls=[call("run", {"command": evil}, evil)], say=[{"t": 99, "text": evil}])
        self.st.pending(text=evil, mode="veto", deadline=time.time() + 30)
        self.p.size = lambda: (80, 30)
        self.p.look()
        self.p.draw()
        self.screen.seek(0)
        raw = self.screen.read().decode("utf-8", "replace")
        self.assertIn("COUNTDOWN", raw)
        for bad in ("pwned\x07", "\x1b]0;", "\x1b[2Jbig") + tuple(BIDI):
            self.assertNotIn(bad, raw)
        self.assertEqual(set(re.findall(r"\x1b\[\??[0-9;]*([A-Za-z])", raw)) - set("HKmhlJ"), set(), "only the escape sequences of the panel itself")


class PanelLoop(unittest.TestCase):
    """the loop never ends on a failing turn (a file that went away, a disk that refuses, a state of an unexpected shape): ONE line in the panel,
    never a traceback on the screen of the user's tab and a pane that dies and comes back every few seconds; twenty failures in a row end it"""

    def setUp(self):
        self.st = FakeState()
        self.addCleanup(self.st.close)
        self.r, self.w = os.pipe()
        self.out = os.open(os.devnull, os.O_WRONLY)
        self.addCleanup(lambda: [os.close(fd) for fd in (self.r, self.w, self.out)])
        self.p = panel.Panel(self.st.paths, in_fd=self.r, out_fd=self.out)
        self.addCleanup(lambda: [os.close(fd) for fd in (self.p.wake_r, self.p.wake_w)])
        real = time.sleep
        patcher = mock.patch.object(panel.time, "sleep", lambda s: real(min(s, 0.002)))      # the pause that grows after a failed turn
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_failing_turn_is_one_short_line_and_the_panel_goes_on(self):
        calls, seen = [], []

        def look():
            calls.append(1)
            seen.append(self.p.model.notice)
            if len(calls) <= 2:
                raise ValueError("x" * 500)
            self.p.model.finished = True
        self.p.look = look
        self.p.loop()
        self.assertEqual(len(calls), 3)
        notice = seen[1]
        self.assertTrue(notice.startswith("The panel hit a problem and goes on (ValueError: x"), notice)
        self.assertLessEqual(len(notice), 140)
        self.assertNotIn("Traceback", notice)

    def test_twenty_failures_in_a_row_end_it_and_a_gone_terminal_ends_it_quietly(self):
        self.p.look = lambda: 1 / 0
        with self.assertRaises(ZeroDivisionError):
            self.p.loop()
        self.p.look = lambda: None
        os.close(self.w)                                          # the other end of the pipe is closed: EOF, the loop ends without a word
        self.w = os.open(os.devnull, os.O_WRONLY)
        self.assertIsNone(self.p.loop())


if __name__ == "__main__":
    unittest.main()
