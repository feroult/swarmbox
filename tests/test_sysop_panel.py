"""The panel of the sysop (container/tools/sysop/lib/swarmbox_sysop/panel.py): what it shows and what its keys do.

  * Model and render alone (no terminal): every state at several sizes, text that came from a tab or the model made safe, the keys, the guard,
    the line editor, the countdown and its expiry.
  * the program on a pty, as tmux runs it, against a FAKE state dir (the files of ipc.py written by the test): rendering at several widths, every
    key, typing a goal (a fake bus), the approval gesture, expiry, the service down and coming back, SIGWINCH.
  * the program on a pty against the REAL service and the REAL bus (a process) and the fake claude: a goal runs, the
    panel shows its steps, the veto and the typed `run` decide for real, and a goal typed in the panel is run by the service.
No tmux, no network, no model. Run with: python3 -W error tests/test_sysop_panel.py
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import audit, ipc, panel, paths, service  # noqa: E402
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
        self.assertNotIn("voice", text.lower(), "the panel does not know the voice tool: it says speak or type")

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

    def test_the_idle_text_and_the_service_down_message(self):
        lines, _ = frame_text(model_with())
        self.assertIn("no goal. Type one: Ctrl+A g", "\n".join(lines))
        self.assertIn("IDLE", lines[0])
        lines, _ = frame_text(model_with(up=False), 50, 30)
        text = " ".join(" ".join(lines).split())
        self.assertIn("SERVICE DOWN", lines[0])
        self.assertNotIn("no goal. Type", text)
        m = model_with(up=False)
        self.assertIsNone(m.key("g", 5.0, time.time()))
        self.assertIn("not running", m.notice)

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

    def test_the_end_of_a_goal(self):
        for state, key, word in (("done", "summary", "done: the summary"), ("failed", "error", "failed: it broke"), ("stopped", "error", "stopped: by the user")):
            m = model_with(make_goal(state, **{key: word.split(": ", 1)[1]}))
            text = "\n".join(frame_text(m)[0])
            self.assertIn(word, text)
            self.assertIn("no goal. Type one: Ctrl+A g", text, "idle text under the end")

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

    def test_an_action_that_does_not_fit_cannot_be_opened_for_approval(self):
        m = self.approval(text="x" * 3000)
        frame_text(m, 40, 24)           # a render sets how much of the action is hidden
        self.assertEqual(m.request_approve(self.REQ, 5.0, time.time()), "no")
        self.assertEqual(m.mode, "view")

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
    def test_idle_shows_the_text_and_q_closes_the_pane(self):
        self.st.serve()
        t = self.open()
        self.ready(t, "no goal. Type one: Ctrl+A g")
        self.assertIn("IDLE", "\n".join(t.last_frame()))
        self.assertEqual(len(t.last_frame()), 30)
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)
        self.assertIn("\x1b[?1049l", t.raw().decode("utf-8", "replace"), "the screen is given back")

    def test_idle_at_several_widths_in_a_real_pane_and_the_last_goal(self):
        self.st.serve(settings=dict(SETTINGS))
        for cols, rows in ((20, 10), (40, 12), (60, 30), (120, 12), (200, 50)):
            t = self.open(rows=rows, cols=cols)
            self.assertTrue(t.wait_frame("no goal."), (cols, rows, t.last_frame()))
            lines = t.last_frame()
            self.assertEqual(len(lines), rows)
            self.assertTrue(all(text_width(x) <= cols for x in lines), (cols, rows, lines))
            self.assertIn("IDLE", lines[0])
        self.st.goal(state="done", summary="tests pass", text="run the tests", ended=time.time() - 30, say=[{"t": 1.0, "text": "all green"}])
        self.st.serve(settings=dict(SETTINGS))
        t = self.open(rows=30, cols=70)
        self.assertTrue(t.wait_frame("last goal (voice, "), "\n".join(t.last_frame()))
        text = "\n".join(t.last_frame())
        for needle in ("run the tests", "say: all green", "done: tests pass", "no goal. Type one", "topic: goal"):
            self.assertIn(needle, text)

    def test_the_idle_panel_costs_almost_no_cpu_and_follows_a_new_goal(self):
        self.st.serve(settings=dict(SETTINGS))
        t = self.open(rows=30, cols=70)
        self.ready(t, "no goal.")

        def ticks():
            with open("/proc/%d/stat" % t.pid) as f:
                f_ = f.read().rsplit(")", 1)[1].split()
            return (int(f_[11]) + int(f_[12])) / os.sysconf("SC_CLK_TCK")
        before, t0 = ticks(), time.time()
        time.sleep(10)
        used = ticks() - before
        wall = time.time() - t0
        self.assertLess(used / wall, 0.01, "the idle panel used %.3f s of CPU in %.1f s" % (used, wall))
        # and it still sees a goal, within the idle look (one second) and then faster
        self.st.goal(state="running", text="check the thing")
        self.st.serve(current="g1", settings=dict(SETTINGS))
        self.assertTrue(t.wait_frame("check the thing", 4), "\n".join(t.last_frame()))
        self.assertIn("RUNNING", "\n".join(t.last_frame()))

    def test_the_service_coming_and_going_is_seen_by_an_idle_panel(self):
        self.st.serve(settings=dict(SETTINGS))
        t = self.open(rows=20, cols=60)
        self.assertTrue(t.wait_frame("no goal."))
        self.st.serve(on=False)
        self.assertTrue(t.wait_frame("SERVICE DOWN", 4), "\n".join(t.last_frame()))
        self.st.serve(settings=dict(SETTINGS))
        self.assertTrue(t.wait_frame("no goal.", 4), "\n".join(t.last_frame()))

    def test_q_in_the_mode_always_ends_the_panel_like_before(self):
        self.st.e.env["SWARMBOX_SYSOP_PANEL_MODE"] = "always"
        self.st.serve(settings=dict(SETTINGS))
        t = self.open()
        self.ready(t, "[q] Hide")
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_it_shows_the_goal_the_log_and_the_queue_as_the_service_writes_them(self):
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "the next one"}])
        self.st.goal(calls=[call("run", {"tab": "@1", "command": "make test"}, "ok 12 tests")], say=[{"t": 20.0, "text": "running the tests"}], text="run the tests")
        t = self.open(rows=30, cols=70)
        self.ready(t, "make test")
        text = "\n".join(t.last_frame())
        for needle in ("goal (voice): run the tests", "> run @1 make test", "= ok 12 tests", "say: running the tests", "queue 1 (cli): the next one", "RUNNING"):
            self.assertIn(needle, text)
        # it follows the service: a new step appears by itself
        g = self.st.goal(calls=[call("run", {"tab": "@1", "command": "make test"}, "ok 12 tests"), call("run", {"tab": "@1", "command": "git status"}, "clean", t=30.0)],
                         say=[{"t": 20.0, "text": "running the tests"}], text="run the tests")
        self.assertTrue(t.wait_frame("git status"), "\n".join(t.last_frame()))
        self.assertIsNone(self.st.decision())
        # the end of the goal stays on screen
        self.st.goal(state="done", summary="tests pass", calls=g["calls"])
        self.st.serve(current=None)
        self.assertTrue(t.wait_frame("done: tests pass"), "\n".join(t.last_frame()))
        self.assertIn("no goal. Type one: Ctrl+A g", "\n".join(t.last_frame()))

    def test_calls_and_says_come_from_the_files_of_the_mcp_server_while_the_goal_runs(self):
        self.st.serve(current="g1")
        self.st.goal()
        gdir = self.st.paths.goal_dir("g1")
        ipc.append_jsonl(os.path.join(gdir, "calls.jsonl"), call("read_tab", {"tab": "@2"}, "screen text", t=5))
        ipc.append_jsonl(os.path.join(gdir, "say.jsonl"), {"t": 6, "text": "fresher than state.json"})
        t = self.open()
        self.assertTrue(t.wait_frame("fresher than state.json"), "\n".join(t.last_frame()))
        self.assertIn("> read_tab @2", "\n".join(t.last_frame()))

    def test_several_widths(self):
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "q"}])
        self.st.goal(text="a goal with a rather long text that has to wrap at the width of the pane " * 2,
                     calls=[call("run", {"tab": "@1", "command": "echo " + "long " * 30}, "result " * 20)])
        self.st.pending(text="rm -rf " + "x" * 120, risk="high", mode="approve")
        for cols, rows in ((40, 20), (60, 30), (120, 12), (200, 50)):
            t = self.open(rows=rows, cols=cols)
            self.assertTrue(t.wait_frame("APPROVAL"), (cols, rows, t.last_frame()))
            lines = t.last_frame()
            self.assertEqual(len(lines), rows, (cols, rows))
            self.assertTrue(all(text_width(x) <= cols for x in lines), (cols, rows, lines))
            self.assertIn("[q] Hide", "\n".join(lines), "the default mode is always: q hides the panels")

    def test_sigwinch_redraws_at_the_new_size(self):
        self.st.serve(current="g1")
        self.st.goal(text="x " * 100)
        t = self.open(rows=20, cols=80)
        self.assertTrue(t.wait_frame("goal (voice)"))
        wide = t.last_frame()
        t.resize(30, 40)
        self.assertTrue(ss.wait_for(lambda: len(t.last_frame()) == 30, 5), t.last_frame())
        lines = t.last_frame()
        self.assertTrue(all(text_width(x) <= 40 for x in lines), lines)
        self.assertNotEqual(lines[:3], wide[:3])
        t.resize(20, 100)
        self.assertTrue(ss.wait_for(lambda: len(t.last_frame()) == 20 and "SYSOP" in t.last_frame()[0], 5))

    def test_the_countdown_runs_on_screen_and_c_vetoes_it(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() + 20, text="ls /tmp")
        t = self.open()
        self.ready(t, "COUNTDOWN")
        first = [x for x in t.last_frame() if "sent in" in x][0]
        time.sleep(1.2)
        self.assertNotEqual([x for x in t.last_frame() if "sent in" in x][0], first, "the clock ticks by itself")
        self.assertIsNone(self.st.decision(), "showing an action decides nothing")
        t.send("c")
        d = self.wait(self.st.decision, "decision.json")
        self.assertEqual(d, {"id": "p1", "decision": "veto", "by": "panel"})
        self.assertTrue(t.wait_frame("Vetoed: it will not be sent."), t.last_frame())
        self.assertEqual(oct(os.stat(os.path.join(self.st.paths.goal_dir("g1"), "decision.json")).st_mode & 0o777), "0o600")
        self.st.clear_pending()
        self.assertTrue(t.wait_frame("[g] Goal"))

    def test_keys_are_ignored_right_after_an_action_appears(self):
        self.st.serve(current="g1")
        self.st.goal()
        t = self.open()
        self.ready(t, "RUNNING")
        self.st.pending(mode="veto", deadline=time.time() + 20)
        self.assertTrue(t.wait_frame("COUNTDOWN"))
        t.send("c")                  # typing meant for another pane, a moment after the action appeared
        time.sleep(0.25)
        self.assertIsNone(self.st.decision(), "ignored")
        time.sleep(0.6)
        t.send("c")
        self.assertEqual(self.wait(self.st.decision, "decision.json")["decision"], "veto")

    def test_an_expired_countdown_cannot_be_answered(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() + 0.8)
        t = self.open()
        self.assertTrue(t.wait_frame("COUNTDOWN"))
        time.sleep(panel.GUARD + 0.5)
        self.assertTrue(t.wait_frame("sending now"), t.last_frame())
        t.send("c")
        time.sleep(0.4)
        self.assertIsNone(self.st.decision(), "the time is up: the service decides")
        self.st.clear_pending("g1")
        self.st.pending(mode="approve", risk="high", deadline=time.time() + 0.8, pid="p2")
        self.assertTrue(t.wait_frame("APPROVAL"))
        time.sleep(panel.GUARD + 0.6)
        self.assertTrue(t.wait_frame("time is up: refused"), t.last_frame())
        t.send("r")
        t.send("run\r")
        time.sleep(0.4)
        self.assertIsNone(self.st.decision())

    def test_the_approval_gesture(self):
        self.st.serve(current="g1")
        self.st.goal(state="waiting_approval")
        self.st.pending(mode="approve", risk="high", text="rm -rf ~/work", deadline=time.time() + 30)
        t = self.open()
        self.ready(t, "APPROVAL")
        text = "\n".join(t.last_frame())
        for needle in ("HIGH RISK", "rm -rf ~/work", "why: it deletes files", "[r] Allow (type run)", "[c] Refuse"):
            self.assertIn(needle, text)
        for k in ("y", "\r", "a", "\r"):          # a key, Enter: not enough
            t.send(k)
        time.sleep(0.4)
        self.assertIsNone(self.st.decision(), "no key but the word allows a high-risk action")
        t.send("r")
        self.assertTrue(t.wait_frame("type the word run"))
        t.send("yes\r")
        self.assertTrue(t.wait_frame("Not allowed"))
        self.assertIsNone(self.st.decision())
        t.send("r")
        self.assertTrue(t.wait_frame("type the word run"))
        t.send("ru")
        self.assertTrue(t.wait_frame("> ru"))
        t.send("n")
        self.assertTrue(t.wait_frame("> run"))
        t.send("\r")
        d = self.wait(self.st.decision, "decision.json")
        self.assertEqual(d, {"id": "p1", "decision": "approve", "by": "panel", "word": "run"})

    def test_c_refuses_an_approval_and_esc_leaves_the_word_prompt(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="approve", risk="high", deadline=time.time() + 30)
        t = self.open()
        self.ready(t, "APPROVAL")
        t.send("r")
        self.assertTrue(t.wait_frame("type the word run"))
        t.send("\x1b")
        self.assertTrue(t.wait_frame("[r] Allow"), t.last_frame())
        self.assertIsNone(self.st.decision())
        t.send("c")
        self.assertEqual(self.wait(self.st.decision, "decision.json"), {"id": "p1", "decision": "deny", "by": "panel"})

    def test_x_asks_the_service_to_stop_the_goal(self):
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "q"}])
        self.st.goal()
        t = self.open()
        self.ready(t, "RUNNING")
        t.send("x")
        self.assertEqual(self.wait(self.st.stop_request, "stop.request")["goal"], "g1")
        self.assertTrue(t.wait_frame("Stop requested (this goal)."))
        ipc.remove(self.st.paths.stop_request)
        t.send("X")
        req = self.wait(self.st.stop_request, "stop.request")
        self.assertIsNone(req["goal"], "capital X: the goal and the queue")

    def test_typing_a_goal_publishes_it_with_the_source_panel(self):
        bus = ss.FakeBus(self.st.e.env["SB_BUS_SOCKET"])
        self.addCleanup(bus.stop)
        got = []
        orig = bus.deliver
        bus.deliver = lambda env: (got.append(env), orig(env))[1]
        self.st.serve()
        t = self.open()
        self.ready(t, "no goal. Type one: Ctrl+A g")
        t.send("g")
        self.assertTrue(t.wait_frame("New goal."))
        t.send("open the api logs")
        self.assertTrue(t.wait_frame("open the api logs"))
        self.assertEqual(got, [], "typing publishes nothing")
        t.send("\x1b[D\x1b[D\x1b[D\x1b[D\x1b[3~")     # four lefts and a delete: the editor edits
        t.send("\r")
        self.assertTrue(t.wait_frame("The sysop is not running: nobody takes the goal"), "\n".join(t.last_frame()))      # no subscriber on the fake bus: a clear message
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["source"], got[0]["body"]), ("panel", {"text": "open the api ogs"}))
        t.send("g")                                          # the text is kept: g gives it back
        self.assertTrue(t.wait_frame("open the api ogs"))
        t.send("\x1b")
        self.assertTrue(ss.wait_for(lambda: "[g] Goal" in "\n".join(t.last_frame()), 5))

    def test_the_goal_goes_to_the_topic_of_the_setting(self):
        self.st.e.env["SWARMBOX_SYSOP_TOPIC"] = "ops.goals"
        bus = ss.FakeBus(self.st.e.env["SB_BUS_SOCKET"])
        self.addCleanup(bus.stop)
        c = socket.socket(socket.AF_UNIX)
        self.addCleanup(c.close)
        c.connect(self.st.e.env["SB_BUS_SOCKET"])
        c.settimeout(10)
        c.sendall(b'{"op":"sub","topic":"ops.goals"}\n')
        f = c.makefile("rb")
        self.assertTrue(json.loads(f.readline())["ok"])
        self.st.serve()
        t = self.open()
        self.ready(t, "no goal. Type")
        t.send("g")
        t.send("check the disk")
        t.send("\r")
        env = json.loads(f.readline())
        self.assertEqual((env["topic"], env["source"], env["body"]), ("ops.goals", "panel", {"text": "check the disk"}))
        self.assertEqual([p[0] for p in bus.pubs], ["ops.goals"])

    def test_a_goal_typed_in_the_panel_reaches_a_subscriber(self):
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
        self.ready(t, "no goal. Type")
        t.send("g")
        t.send("check the disk")
        t.send("\r")
        env = json.loads(f.readline())
        self.assertEqual((env["topic"], env["source"], env["body"]), ("goal", "panel", {"text": "check the disk"}))
        self.assertTrue(t.wait_frame("Goal sent."), "\n".join(t.last_frame()))

    def test_the_service_down_is_said_and_the_panel_goes_on_looking(self):
        t = self.open()
        self.assertTrue(t.wait_frame("SERVICE DOWN"), "\n".join(t.last_frame()))
        text = " ".join(" ".join(t.last_frame()).split())
        self.assertIn("service is not running", text)
        self.assertNotIn("no goal. Type", text)
        t.send("g")
        self.assertTrue(t.wait_frame("not running: a goal would have nobody"))
        self.st.serve()
        self.assertTrue(t.wait_frame("no goal. Type one: Ctrl+A g"), "\n".join(t.last_frame()))
        self.st.serve(on=False)
        self.assertTrue(t.wait_frame("SERVICE DOWN"), "\n".join(t.last_frame()))
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_text_from_a_tab_never_reaches_the_terminal_as_control_text(self):
        evil = "\x1b]0;pwned\x07\x1b[2Jbig" + BIDI
        self.st.serve(current="g1")
        self.st.goal(text="goal " + evil, calls=[call("run", {"command": evil}, evil)], say=[{"t": 99, "text": evil}])
        self.st.pending(text=evil, mode="veto", deadline=time.time() + 30)
        t = self.open(cols=80)
        self.assertTrue(t.wait_frame("COUNTDOWN"))
        raw = t.raw().decode("utf-8", "replace")
        self.assertNotIn("pwned\x07", raw)
        self.assertNotIn("\x1b]0;", raw)
        self.assertNotIn("\x1b[2Jbig", raw)
        for ch in BIDI:
            self.assertNotIn(ch, raw)
        self.assertEqual(set(re.findall(r"\x1b\[\??[0-9;]*([A-Za-z])", raw)) - set("HKmhlJ"), set(), "only the escape sequences of the panel itself")

    def test_q_ends_the_panel_in_every_mode_but_typing(self):
        self.st.serve(current="g1")
        self.st.goal()
        self.st.pending(mode="veto", deadline=time.time() + 30)
        t = self.open()
        self.ready(t, "COUNTDOWN")
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)
        self.assertIsNone(self.st.decision(), "closing the panel answers nothing: the countdown sends the action")

    def test_sigterm_and_sighup_end_it_cleanly(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            self.st.serve()
            t = self.open()
            self.ready(t, "IDLE")
            os.kill(t.pid, sig)
            self.assertEqual(t.wait_exit(), 0, sig)

    def test_without_a_terminal_it_says_so(self):
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "panel"], env=dict(os.environ, PYTHONPATH=ss.LIB, **self.st.e.env), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn("needs a terminal", p.stderr)


# ---------------------------------------------------------------------------------------------------------------------- the real core

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

    def test_the_panel_follows_a_goal_and_the_veto_key_stops_the_action(self):
        self.start([{"tool": "say", "args": {"text": "listing"}}, {"tool": "run", "args": {"tab": "main", "command": "echo from-the-sysop"}},
                    {"tool": "say", "args": {"text": "it was vetoed"}}, {"tool": "done", "args": {"summary": "vetoed by you"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "no goal. Type")
        gid = self.goal("echo something", "voice")
        self.assertTrue(t.wait_frame("COUNTDOWN"), "\n".join(t.last_frame()))
        text = "\n".join(t.last_frame())
        for needle in ("goal (voice): echo something", "say: listing", "echo from-the-sysop", "tab 0:shell: run", "sent in"):
            if needle.startswith("tab 0"):
                continue                      # the label of a stub tab is its name
            self.assertIn(needle, text)
        time.sleep(panel.GUARD + 0.2)
        t.send("c")
        self.assertTrue(t.wait_frame("done: vetoed by you"), "\n".join(t.last_frame()))
        self.assertEqual(self.decisions(), ["waiting", "vetoed"])
        res = [json.loads(x) for x in open(self.out)]
        self.assertIn("vetoed by the user", res[1]["text"])
        self.assertEqual(self.state(gid)["state"], "done")
        self.assertIn("say: it was vetoed", "\n".join(t.last_frame()))
        self.assertIn("= error: vetoed by the user", " ".join(" ".join(t.last_frame()).split()).replace("! ", "= "))

    def test_the_countdown_runs_out_and_the_action_is_sent(self):
        self.start([{"tool": "run", "args": {"tab": "main", "command": "echo sent"}}, {"tool": "done", "args": {"summary": "sent it"}}], countdown=1.5)
        t = self.open(rows=30, cols=80)
        self.ready(t, "no goal")
        self.goal("echo")
        self.assertTrue(t.wait_frame("COUNTDOWN"))
        self.assertTrue(t.wait_frame("done: sent it", 15), "\n".join(t.last_frame()))
        self.assertEqual(self.decisions(), ["waiting", "allowed"])

    def test_a_high_risk_action_needs_the_typed_word_run(self):
        self.start([{"tool": "run", "args": {"tab": "main", "command": "rm -rf /tmp/sysop-panel-test-nothing"}}, {"tool": "done", "args": {"summary": "removed"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "no goal")
        self.goal("clean up")
        self.assertTrue(t.wait_frame("APPROVAL"), "\n".join(t.last_frame()))
        time.sleep(panel.GUARD + 0.2)
        for k in ("y", "\r", "a"):
            t.send(k)
        time.sleep(0.5)
        self.assertEqual(self.decisions(), ["waiting"], "keys alone allow nothing")
        t.send("r")
        t.send("run")
        t.send("\r")
        self.assertTrue(t.wait_frame("done: removed", 15), "\n".join(t.last_frame()))
        self.assertEqual(self.decisions(), ["waiting", "approved"])

    def test_the_stop_key_ends_the_goal(self):
        self.start([{"tool": "run", "args": {"tab": "main", "command": "echo x"}}, {"tool": "done", "args": {"summary": "never"}}], countdown=30)
        t = self.open(rows=30, cols=80)
        self.ready(t, "no goal")
        gid = self.goal("slow one")
        self.assertTrue(t.wait_frame("COUNTDOWN"))
        time.sleep(panel.GUARD + 0.2)
        t.send("x")
        self.assertTrue(t.wait_frame("STOPPED", 15), "\n".join(t.last_frame()))
        self.assertEqual(self.state(gid)["state"], "stopped")

    def test_a_goal_typed_in_the_panel_is_run_by_the_service(self):
        self.start([{"tool": "say", "args": {"text": "typed goals work"}}, {"tool": "done", "args": {"summary": "got it"}}])
        t = self.open(rows=30, cols=80)
        self.ready(t, "no goal")
        t.send("g")
        t.send("do the thing")
        t.send("\r")
        self.assertTrue(t.wait_frame("done: got it", 15), "\n".join(t.last_frame()))
        gid = self.wait(lambda: self.svc.current is None and next((g for g in service.recent_goals(self.st.paths, 1)), None), "the goal")["id"]
        st = self.state(gid)
        self.assertEqual((st["source"], st["text"], st["state"]), ("panel", "do the thing", "done"))
        self.assertIn("last goal (panel", "\n".join(t.last_frame()))


if __name__ == "__main__":
    unittest.main()
