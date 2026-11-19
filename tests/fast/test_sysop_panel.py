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


class IdleScreen(unittest.TestCase):
    """The idle screen of the panel that is always up: a few quiet words, at any size."""

    def idle(self, cols, rows, goal=None, settings=SETTINGS):
        m = model_with(goal, settings=settings)
        m.panel_mode = "always"
        return frame_text(m, cols, rows)[0]

    def test_it_is_short_and_says_nothing_of_keys_settings_or_a_microphone(self):
        text = "\n".join(self.idle(60, 24)).lower()
        self.assertIn("idle", text)
        self.assertIn("say or type a goal", text)
        for word in ("ctrl+a", "autonomy", "brain", "topic", "micro", "voice", "[q]"):
            self.assertNotIn(word, text)
        self.assertLessEqual(len([x for x in self.idle(60, 24) if x.strip()]), 3, "the head, one line, one button")

    def test_the_title_is_the_first_line_and_the_screen_has_the_size_of_the_pane(self):
        for cols in (16, 24, 30, 40, 60, 100, 200):
            for rows in (4, 8, 12, 24, 50):
                lines = self.idle(cols, rows)
                self.assertEqual(len(lines), rows, (cols, rows))
                self.assertIn("SYSOP", lines[0])
                self.assertTrue(all(text_width(x) <= max(16, cols) for x in lines), (cols, rows, lines))

    def test_in_a_short_pane_the_result_of_the_last_goal_is_on_the_screen(self):
        """found in the e2e screenshot of a phone held upright (28 columns, 8 lines): the panel showed the goal and a marker, and not the result"""
        say = [{"t": 5.0, "text": "I looked at the tab"}] * 12
        g = make_goal("done", "reply with exactly banana 9", "voice", say=say, ended=time.time() - 3, summary="Typed the prompt into the active Claude tab; it replied banana 9.")
        for rows in (8, 9, 10, 12):
            text = " ".join("\n".join(self.idle(28, rows, g)).split())
            self.assertIn("done: Typed", text, rows)
            self.assertIn("[ Goal ]".replace("[ ", "").replace(" ]", ""), text, rows)
        long_goal = make_goal("running", "x " * 400, "voice", say=say)
        self.assertIn("SYSOP", "\n".join(self.idle(28, 8, long_goal)))

    def test_the_last_goal_is_shown_with_how_it_ended_and_what_was_said(self):
        for state, key, why in (("done", "summary", "tests pass"), ("failed", "error", "the brain crashed"), ("stopped", "error", "stopped by the user")):
            g = make_goal(state, "run the tests", "voice", say=[{"t": 5.0, "text": "I looked at the tab"}], ended=time.time() - 125, **{key: why})
            text = "\n".join(self.idle(70, 30, g))
            self.assertIn("run the tests", text)
            self.assertIn("I looked at the tab", text)
            self.assertIn("%s: %s" % (state, why), text)
            self.assertIn("Goal", text, "and it is idle: the button for another goal is there")

    def test_while_a_goal_runs_or_waits_it_does_not_offer_a_new_goal(self):
        for m in (model_with(make_goal("running")), model_with(make_goal("running"), make_pending("veto")), model_with(make_goal("queued"), queue=[{"id": "g2", "source": "cli", "text": "x"}])):
            text = "\n".join(frame_text(m, 70, 30)[0])
            self.assertNotIn("Say or type a goal", text)
            self.assertNotIn("Goal ", text.replace("goal", ""))

    def test_the_service_down_has_its_own_screen(self):
        text = "\n".join(frame_text(model_with(up=False, settings=SETTINGS), 70, 24)[0])
        self.assertIn("off", text)
        self.assertIn("not running", text)
        self.assertNotIn("Say or type", text)

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
                        if m.pending and rows >= 6 and cols >= 20:
                            self.assertIn("Cancel", " ".join(strip_ansi(x) for x in f.lines), (name, cols, rows, "the way to say no is always visible"))

    def test_the_goal_the_steps_in_plain_words_and_the_queue(self):
        g = make_goal("running", "open the logs of the api", "voice", calls=[
            call("list_tabs", summary='[{"tab":"@1"}]', t=1), call("run", {"tab": "@1", "command": "tail -f api.log"}, "line one\nline two", t=2, verdict="medium"),
            call("run", {"tab": "@9", "command": "x"}, "error: no such tab", t=3, is_error=True), call("read_tab", {"tab": "@1"}, "screen", t=4)],
            say=[{"t": 2.5, "text": "I opened the log"}])
        m = model_with(g, queue=[{"id": "g2", "source": "cli", "text": "second goal"}, {"id": "g3", "source": "panel", "text": "third"}])
        lines, _ = frame_text(m, 70, 30)
        text = "\n".join(lines)
        for needle in ("open the logs of the api", "✓ look at the tabs", "✓ run: tail -f api.log", "I opened the log", "✗ run: x", "✓ read tab @1", "+2 queued", "working", "Stop"):
            self.assertIn(needle, text)
        for noise in ("line one", "no such tab", "[medium]", "queue 1", "tool", "verdict"):
            self.assertNotIn(noise, text, "the results stay out of the log: one short line a step")
        order = [text.index(x) for x in ("look at the tabs", "tail -f", "I opened", "run: x")]
        self.assertEqual(order, sorted(order), "steps and says in time order")

    def test_the_end_of_a_goal_is_two_or_three_whole_lines_and_only_a_runaway_summary_is_cut(self):
        ok = "Ran the tests in tab 2: 41 passed and one failed, test_login. I did not touch the code."
        lines, _ = frame_text(model_with(make_goal("done", summary=ok)), 40, 20)
        text = " ".join(" ".join(lines).split())
        self.assertIn(ok, text, "a summary of this size is shown whole, wrapped")
        self.assertNotIn("…", text)
        runaway = "the tests ran and here is everything they printed " * 12
        lines, _ = frame_text(model_with(make_goal("done", summary=runaway)), 40, 20)
        ends = [i for i, x in enumerate(lines) if x.strip().startswith("done:")]
        block = [x for x in lines[ends[0]:] if x.strip() and "[Goal]" not in x]
        self.assertEqual(len(block), 3)
        self.assertTrue(block[-1].rstrip().endswith("…"))
        say = [{"t": float(i), "text": "word " * 60} for i in range(1, 3)]
        lines, _ = frame_text(model_with(make_goal(say=say)), 40, 30)
        self.assertLessEqual(len([x for x in lines if "word" in x]), 4, "a long say takes two lines at most")

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

    def test_the_countdown_and_the_approval_say_what_they_need_in_few_words(self):
        now = time.time()
        m = model_with(make_goal(), make_pending("veto", deadline=now + 3.2, text="echo hi"))
        text = "\n".join(frame_text(m, 70, 24, now)[0])
        for needle in ("sending in 4 s", "tab 0:shell", "echo hi", "Cancel"):
            self.assertIn(needle, text)
        self.assertNotIn("Allow", text, "a countdown sends by itself: only Cancel")
        self.assertNotIn("Ctrl+A", text, "no key to learn")
        self.assertIn("sending in 1 s", "\n".join(frame_text(m, 70, 24, now + 2.5)[0]))
        m = model_with(make_goal(), make_pending("approve", "high", deadline=now + 45, text="rm -rf ~/x"))
        text = "\n".join(frame_text(m, 70, 24, now)[0])
        for needle in ("allow? high risk", "rm -rf ~/x", "it deletes files", "Allow", "Cancel"):
            self.assertIn(needle, text)
        for noise in ("type run", "NOT sent", "0:45", "Ctrl+A"):
            self.assertNotIn(noise, text)

    def test_the_bar_that_needs_you_is_a_full_width_block_of_colour(self):
        now = time.time()
        for mode, risk, want in (("approve", "high", "ff6b78"), ("veto", "medium", "fbbf24")):
            m = model_with(make_goal(), make_pending(mode, risk, deadline=now + 30))
            lines = render(m, 40, 14, now, True).lines
            bar = next(x for x in lines if "tab 0:shell" in x)
            self.assertIn("48;2;%d;%d;%d" % tuple(int(want[i:i + 2], 16) for i in (0, 2, 4)), bar, "a background colour, not only coloured letters")
            self.assertEqual(text_width(strip_ansi(bar)), 40, "the bar spans the pane")
        self.assertNotIn("tab 0:shell", "\n".join(frame_text(model_with(make_goal()), 40, 14)[0]))

    def test_hits_are_the_buttons(self):
        now = time.time()
        for pend, want in ((None, ["c"]), (make_pending("approve", "high", deadline=now + 30), ["a", "c"]), (make_pending("veto", deadline=now + 30), ["c"])):
            f = render(model_with(make_goal(), pend), 60, 12, now, True)
            self.assertEqual([h[3] for h in f.hits], want)
            for row, c0, c1, key in f.hits:
                label = {"a": "Allow", "c": "Cancel" if pend else "Stop"}[key]
                self.assertIn(label, strip_ansi(f.lines[row - 1])[c0 - 1:c1], key)
        f = render(model_with(), 60, 12, now, True)
        self.assertEqual([h[3] for h in f.hits], ["g"])


class CloseControl(unittest.TestCase):
    """The panel of a narrow window (a phone) has a close control at the right end of its head line; a click on it is the key q."""

    def test_the_head_line_of_a_narrow_panel_ends_with_a_close_control_that_is_a_hit_on_q(self):
        for cols in (30, 40, 64, 80):
            f = render(model_with(make_goal()), cols, 12, time.time(), color=False, closer=True)
            head = strip_ansi(f.lines[0])
            self.assertTrue(head.rstrip().endswith("✕ close"), head)
            self.assertEqual(text_width(head), cols, "the control is at the right edge: %r" % head)
            hit = [h for h in f.hits if h[3] == "q"]
            self.assertEqual(len(hit), 1, f.hits)
            row, c0, c1, key = hit[0]
            self.assertEqual(row, 1)
            self.assertIn("✕ close", head[c0 - 1:c1])
            self.assertGreaterEqual(c1 - c0 + 1, 7, "a thumb can hit it")
        for color in (True, False):
            f = render(model_with(make_goal()), 40, 12, time.time(), color=color, closer=True)
            self.assertIn("✕ close", strip_ansi(f.lines[0]))

    def test_a_panel_that_is_not_in_a_narrow_window_has_none(self):
        f = render(model_with(make_goal()), 60, 12, time.time(), color=False)
        self.assertNotIn("close", strip_ansi(f.lines[0]))
        self.assertNotIn("q", [h[3] for h in f.hits])

    def test_the_control_gives_way_when_the_head_has_no_room(self):
        f = render(model_with(make_goal()), 18, 12, time.time(), color=False, closer=True)
        self.assertEqual(text_width(strip_ansi(f.lines[0])) <= 18, True)
        self.assertEqual([h for h in f.hits if h[3] == "q"] != [], "✕ close" in strip_ansi(f.lines[0]))

    def test_the_other_buttons_keep_their_hits_and_the_control_does_not_cover_them(self):
        now = time.time()
        f = render(model_with(make_goal(), make_pending("approve", "high", deadline=now + 30)), 40, 14, now, color=False, closer=True)
        self.assertEqual(sorted(h[3] for h in f.hits), ["a", "c", "q"])
        self.assertEqual([h[0] for h in f.hits if h[3] == "q"], [1])

    def test_the_head_of_a_phones_panel_is_a_dark_purple_bar_edge_to_edge(self):
        band = "\x1b[48;2;42;26;82m"
        for cols in (30, 40, 64):
            head = render(model_with(make_goal()), cols, 12, time.time(), color=True, closer=True).lines[0]
            self.assertTrue(head.startswith(band), "the bar starts with its colour: %r" % head[:30])
            self.assertEqual(text_width(strip_ansi(head)), cols, "and goes to the right edge")
            self.assertTrue(head.endswith("\x1b[0m"))
            self.assertEqual(head.count(band), head.count("\x1b[0m"), "the colour is back after every reset in the line (the words are painted one by one)")
            self.assertIn("SYSOP", strip_ansi(head))
            self.assertIn("✕ close", strip_ansi(head))

    def test_the_head_bar_is_in_colour_only(self):
        band = "\x1b[48;2;42;26;82m"
        self.assertTrue(render(model_with(make_goal()), 60, 12, time.time(), color=True).lines[0].startswith(band), "a wide panel has the bar too")
        plain = render(model_with(make_goal()), 40, 12, time.time(), color=False, closer=True).lines[0]
        self.assertNotIn("\x1b", plain, "no colour, no escape")

    def test_a_tall_enough_panel_of_a_narrow_window_has_a_blank_line_under_its_head(self):
        for rows in (7, 10, 14):
            f = render(model_with(make_goal()), 40, rows, time.time(), color=False, closer=True)
            self.assertEqual(len(f.lines), rows, "the frame is exactly the rows of the pane")
            self.assertEqual(strip_ansi(f.lines[1]).strip(), "", "a space between the head and the content: %r" % f.lines[:3])
            self.assertNotEqual(strip_ansi(f.lines[2]).strip(), "", "and the content follows: %r" % f.lines[:3])

    def test_a_short_panel_keeps_all_its_rows_for_the_content(self):
        for rows in (4, 5, 6):
            f = render(model_with(make_goal()), 40, rows, time.time(), color=False, closer=True)
            self.assertEqual(len(f.lines), rows)
            self.assertNotEqual(strip_ansi(f.lines[1]).strip(), "", "no blank line in a short panel: %r" % f.lines[:3])

    def test_the_tall_narrow_panel_of_a_desktop_leaves_three_blank_lines_under_its_head_two_for_a_bar_of_buttons_and_one_of_space(self):
        band = "\x1b[48;2;42;26;82m"
        for cols in (40, 60, 80):
            for rows in (14, 30, 50):
                f = render(model_with(make_goal()), cols, rows, time.time(), color=True)
                self.assertEqual(len(f.lines), rows, (cols, rows))
                self.assertTrue(f.lines[0].startswith(band) and "SYSOP" in strip_ansi(f.lines[0]), "the title is the first line, on the bar: %r" % f.lines[:2])
                self.assertEqual(text_width(strip_ansi(f.lines[0])), cols, "edge to edge")
                self.assertEqual(strip_ansi(f.lines[1]).strip(), "", "a blank line, the first of the strip of buttons")
                self.assertEqual(strip_ansi(f.lines[2]).strip(), "", "and a second one")
                self.assertEqual(strip_ansi(f.lines[3]).strip(), "", "and a third, the space between the bar of buttons and the content")
                self.assertNotIn(band, "".join(f.lines[1:4]), "they are not lines of the bar: the page draws that strip")
                self.assertNotEqual(strip_ansi(f.lines[4]).strip(), "", "the content follows: %r" % f.lines[:5])

    def test_a_short_panel_or_one_at_the_bottom_of_a_wide_window_has_no_strip_of_buttons(self):
        for cols, rows in ((40, 8), (40, 10), (40, 13), (120, 14), (200, 30)):
            f = render(model_with(make_goal()), cols, rows, time.time(), color=True)
            self.assertIn("SYSOP", strip_ansi(f.lines[0]))
            self.assertNotEqual(strip_ansi(f.lines[1]).strip(), "", "the content follows the title at once: %r" % (((cols, rows), f.lines[:3]),))

    def test_the_buttons_of_the_panel_with_the_strip_are_on_the_rows_where_they_are_drawn(self):
        now = time.time()
        f = render(model_with(make_goal(), make_pending("approve", "high", deadline=now + 30)), 40, 24, now, color=False)
        for row, c0, c1, key in f.hits:
            if key in ("a", "c"):
                self.assertIn({"a": "Allow", "c": "Cancel"}[key], strip_ansi(f.lines[row - 1]), "the hit of %r is on its own row: %r" % (key, f.hits))

    def test_the_head_bar_is_in_colour_only(self):
        band = "\x1b[48;2;42;26;82m"
        self.assertTrue(render(model_with(make_goal()), 60, 12, time.time(), color=True).lines[0].startswith(band), "a wide panel has the bar too")
        plain = render(model_with(make_goal()), 40, 12, time.time(), color=False, closer=True).lines[0]
        self.assertNotIn("\x1b", plain, "no colour, no escape")

    def test_a_tall_enough_panel_of_a_narrow_window_has_a_blank_line_under_its_head(self):
        for rows in (7, 10, 14):
            f = render(model_with(make_goal()), 40, rows, time.time(), color=False, closer=True)
            self.assertEqual(len(f.lines), rows, "the frame is exactly the rows of the pane")
            self.assertEqual(strip_ansi(f.lines[1]).strip(), "", "a space between the head and the content: %r" % f.lines[:3])
            self.assertNotEqual(strip_ansi(f.lines[2]).strip(), "", "and the content follows: %r" % f.lines[:3])

    def test_a_short_panel_keeps_all_its_rows_for_the_content(self):
        for rows in (4, 5, 6):
            f = render(model_with(make_goal()), 40, rows, time.time(), color=False, closer=True)
            self.assertEqual(len(f.lines), rows)
            self.assertNotEqual(strip_ansi(f.lines[1]).strip(), "", "no blank line in a short panel: %r" % f.lines[:3])

    def test_the_buttons_of_a_panel_with_the_blank_line_are_on_the_rows_where_they_are_drawn(self):
        now = time.time()
        f = render(model_with(make_goal(), make_pending("approve", "high", deadline=now + 30)), 40, 14, now, color=False, closer=True)
        for row, c0, c1, key in f.hits:
            if key in ("a", "c"):
                self.assertIn({"a": "Allow", "c": "Cancel"}[key], strip_ansi(f.lines[row - 1]), "the hit of %r is on its own row: %r" % (key, f.hits))

    def test_q_closes_the_panel_the_way_the_key_does(self):
        m = model_with(make_goal(), now=100.0)
        self.assertEqual(m.key("q", 101.0, time.time()), ("quit",))


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
        self.assertEqual(model_with(make_goal(), now=100.0).key("c", 101.0, self.now), ("stop", None), "nothing waits and a goal runs: Cancel is Stop")
        self.assertIsNone(model_with(now=100.0).key("c", 101.0, self.now), "nothing at all: nothing to cancel")

    def test_an_unknown_mode_is_an_approval(self):
        m = model_with(make_goal(), make_pending("whatever", deadline=self.now + 30), now=100.0)
        self.assertEqual(m.pmode(), "approve")
        self.assertEqual(m.key("a", 101.0, self.now), ("decide", "g1", "p1", "approve", "run"))

    def test_nothing_is_allowed_after_the_deadline(self):
        m = model_with(make_goal(), make_pending("approve", "high", deadline=self.now - 1), now=100.0)
        self.assertIsNone(m.key("a", 101.0, self.now))
        self.assertEqual(m.key("c", 101.0, self.now), ("stop", None), "an action that is gone: c stops the goal, it does not refuse a ghost")

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


class Approval(unittest.TestCase):
    """Allow is one press (a or y, or a click on the button); text that is cut off cannot be allowed."""

    def approval(self, now=0.0, **kw):
        kw.setdefault("text", "rm -rf ~/x")
        return model_with(make_goal("waiting_approval"), make_pending("approve", "high", **kw), now=now)

    def test_one_press_allows_after_the_guard(self):
        m = self.approval(now=10.0)
        self.assertIsNone(m.key("a", 10.1, time.time()), "the guard of a new action: a key meant for another pane")
        for k in ("a", "y", "A"):
            self.assertEqual(m.key(k, 11.0, time.time()), ("decide", "g1", "p1", "approve", "run"))

    def test_an_action_that_does_not_fit_says_so_and_cannot_be_allowed(self):
        """Allow means what is on the screen: text that is cut off could hide the end of a command ("...; rm -rf ~")"""
        text = "rm -rf ./build-cache " + "# cleaning the build cache ... " * 80 + "; rm -rf ~"
        m = self.approval(text=text)
        joined = "\n".join(frame_text(m, 40, 40)[0])
        self.assertGreater(m.hidden, 0)
        self.assertIn("not shown", joined)
        self.assertIn("cancel it", " ".join(joined.split()))
        self.assertNotIn("Allow", joined)
        self.assertIsNone(m.key("a", 100.0, time.time()))
        self.assertIn("cannot be allowed", m.notice)
        self.assertEqual(m.key("c", 100.0, time.time())[3], "deny", "it can be cancelled")

    def test_a_command_of_600_characters_is_shown_whole_on_a_wide_pane(self):
        """a past bug: the budget of the pane hid the end of a 615 character command that did fit"""
        m = self.approval(text="rm -rf ./build-cache " + "# cleaning the build cache ... " * 20 + "; rm -rf ~")
        self.assertIn("; rm -rf ~", " ".join(" ".join(frame_text(m, 200, 40)[0]).split()))
        self.assertEqual(m.hidden, 0)


class ApprovalPane(unittest.TestCase):
    """The approval pane of a narrow window (render_approval, the keys with approval_only): the action and two big buttons, nothing else."""

    def pending_model(self, **kw):
        kw.setdefault("mode", "approve")
        kw.setdefault("risk", "high")
        m = model_with(make_goal(text="deploy the site"), make_pending(**kw))
        m.approval_only = True
        return m

    def lines(self, m, cols=64, rows=10, color=False, wall=None):
        f = panel.render_approval(m, cols, rows, time.time() if wall is None else wall, color)
        return [strip_ansi(x) for x in f.lines], f

    def test_it_shows_the_risk_the_action_and_two_buttons_and_nothing_else(self):
        m = self.pending_model(text="git push --force origin main", risk="high")
        lines, f = self.lines(m)
        text = "\n".join(lines)
        self.assertEqual(len(lines), 10)
        self.assertIn("ALLOW?", lines[0])
        self.assertIn("high risk", lines[0])
        self.assertIn("git push --force origin main", text)
        self.assertIn("Allow", text)
        self.assertIn("Cancel", text)
        for word in ("deploy the site", "SYSOP", "Goal", "Stop", "earlier", "Say or type"):
            self.assertNotIn(word, text, "the goal, the log and the panel's own words stay out")

    def test_the_risk_colours_the_bar_and_medium_says_medium(self):
        for risk, name in (("high", "ff6b78"), ("medium", "fbbf24")):
            lines, f = self.lines(self.pending_model(risk=risk), color=True)
            r, g, b = int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16)
            self.assertIn("48;2;%d;%d;%d" % (r, g, b), f.lines[0], risk)
        self.assertIn("medium risk", self.lines(self.pending_model(risk="medium"))[0][0])

    def test_the_buttons_are_three_rows_high_and_each_takes_half_the_width(self):
        lines, f = self.lines(self.pending_model(), cols=64, rows=10)
        allow = [h for h in f.hits if h[3] == "a"]
        cancel = [h for h in f.hits if h[3] == "c"]
        self.assertEqual(sorted(h[0] for h in allow), [8, 9, 10], "Allow: three rows at the bottom")
        self.assertEqual(sorted(h[0] for h in cancel), [8, 9, 10])
        a0, a1 = allow[0][1], allow[0][2]
        c0, c1 = cancel[0][1], cancel[0][2]
        self.assertLess(a1, c0, "side by side, Allow first")
        self.assertAlmostEqual(a1 - a0, c1 - c0, delta=1)
        self.assertGreaterEqual((a1 - a0 + 1) * 2 + 3, 64 - 3, "and each is about half of the width")
        self.assertTrue(lines[9].strip() or lines[8].strip(), "the buttons are drawn")

    def test_a_pane_that_is_short_has_one_row_buttons_and_every_size_fits(self):
        for cols in (16, 24, 40, 64, 80):
            for rows in (3, 4, 5, 6, 7, 8, 10, 12):
                for text in ("ls", "x " * 300):
                    m = self.pending_model(text=text)
                    lines, f = self.lines(m, cols=cols, rows=rows)
                    self.assertEqual(len(lines), max(3, rows), (cols, rows))
                    for ln in lines:
                        self.assertLessEqual(text_width(ln), cols, (cols, rows))
                    for row, c0, c1, key in f.hits:
                        self.assertTrue(1 <= row <= len(lines) and 1 <= c0 <= c1 <= cols, (cols, rows, f.hits))

    def test_an_action_that_does_not_fit_says_so_and_can_only_be_cancelled(self):
        m = self.pending_model(text="word " * 200)
        lines, f = self.lines(m, cols=40, rows=10)
        self.assertIn("more characters not shown", "\n".join(lines))
        self.assertEqual({h[3] for h in f.hits}, {"c"}, "no Allow")
        self.assertEqual(m.hidden > 0, True)
        m.update(snap(make_goal(), make_pending(mode="approve", risk="high", text="word " * 200)), 0.0)
        self.assertIsNone(m.key("a", 99.0, time.time()), "and the key refuses too")

    def test_five_lines_of_the_action_are_shown(self):
        m = self.pending_model(text=" ".join("w%02d" % i for i in range(60)))
        lines, f = self.lines(m, cols=40, rows=12)
        self.assertEqual(sum(1 for ln in lines if ln.startswith(" \u203a")), 4, "four lines and the note that the rest is not shown")
        m2 = self.pending_model(text=" ".join("w%02d" % i for i in range(44)))
        lines2, _ = self.lines(m2, cols=40, rows=12)
        self.assertEqual(sum(1 for ln in lines2 if ln.startswith(" \u203a")), 5)

    def test_with_nothing_to_approve_it_is_empty(self):
        for m in (model_with(), model_with(make_goal(), make_pending(mode="veto")), model_with(make_goal(), make_pending(mode="approve", deadline=time.time() - 5))):
            m.approval_only = True
            lines, f = self.lines(m)
            self.assertEqual("".join(lines).strip(), "", "an empty, calm screen")
            self.assertEqual(f.hits, [])

    def test_the_text_of_a_tab_in_the_action_is_printed_safe(self):
        m = self.pending_model(text="echo \x1b[31mred\x1b[0m \u202eevil")
        lines, f = self.lines(m, color=True)
        shown = "".join(f.lines)
        self.assertNotIn("\x1b[31m", shown)
        self.assertNotIn("\u202e", shown)

    def test_keys_a_and_y_allow_c_and_n_refuse_and_nothing_else_does_anything(self):
        for k, want in (("a", "approve"), ("y", "approve"), ("c", "deny"), ("n", "deny")):
            m = self.pending_model()
            cmd = m.key(k, 99.0, time.time())
            self.assertEqual(cmd[0], "decide", k)
            self.assertEqual(cmd[3], want, k)
        for k in ("q", "ctrl-c", "g", "x", "X", "up", "down", "pgup", " ", "enter", "esc"):
            m = self.pending_model()
            self.assertIsNone(m.key(k, 99.0, time.time()), "a stray %r does nothing here" % k)
            self.assertFalse(m.finished or m.quit_key, k)
            self.assertEqual((m.mode, m.scroll), ("view", 0), k)

    def test_it_answers_after_the_guard_only_an_approval_that_is_live_and_never_a_countdown(self):
        m = self.pending_model()
        m.ready_at = 5.0
        self.assertIsNone(m.key("a", 4.0, time.time()), "the half second guard")
        self.assertIsNotNone(m.key("a", 6.0, time.time()))
        veto = model_with(make_goal(), make_pending(mode="veto"))
        veto.approval_only = True
        self.assertIsNone(veto.key("c", 99.0, time.time()), "a countdown is not for this pane")
        late = model_with(make_goal(), make_pending(mode="approve", deadline=time.time() - 1))
        late.approval_only = True
        self.assertIsNone(late.key("a", 99.0, time.time()))


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

    def test_a_click_on_the_close_control_of_a_narrow_panel_ends_it_as_q_does(self):
        os.environ["SWARMBOX_SYSOP_PANEL_COMPACT"] = "1"
        self.st.serve(current="g1")
        self.st.goal()
        self.p.look()
        self.p.draw(force=True)
        hit = [h for h in self.p.hits if h[3] == "q"]
        self.assertEqual(len(hit), 1, self.p.hits)
        row, c0, c1, key = hit[0]
        self.clock[0] += 1.0
        self.p.handle_key(("click", c0 + 1, row))
        self.assertTrue(self.p.model.finished and self.p.model.quit_key, "it ends and says it was asked to (q), not killed")

    def test_without_the_environment_of_a_narrow_window_there_is_no_close_control(self):
        os.environ.pop("SWARMBOX_SYSOP_PANEL_COMPACT", None)
        self.st.serve(current="g1")
        self.st.goal()
        self.p.look()
        self.p.draw(force=True)
        self.assertEqual([h for h in self.p.hits if h[3] == "q"], [])

    def test_it_shows_what_the_service_writes_and_follows_it(self):
        self.assertIn("not running", self.see())
        self.st.serve(current="g1", queue=[{"id": "g2", "source": "cli", "text": "the next one"}])
        self.st.goal(calls=[call("run", {"tab": "@1", "command": "make test"}, "ok 12 tests")], say=[{"t": 20.0, "text": "running the tests"}], text="run the tests")
        text = self.see()
        for needle in ("run the tests", "✓ run: make test", "running the tests", "+1 queued", "working"):
            self.assertIn(needle, text)
        gdir = self.st.paths.goal_dir("g1")                  # the files of the mcp server are fresher than state.json
        ipc.append_jsonl(os.path.join(gdir, "calls.jsonl"), call("read_tab", {"tab": "@2"}, "screen text", t=30))
        ipc.append_jsonl(os.path.join(gdir, "say.jsonl"), {"t": 31, "text": "fresher than state.json"})
        text = self.see()
        self.assertIn("✓ read tab @2", text)
        self.assertIn("fresher than state.json", text)
        self.st.goal(state="done", summary="tests pass")      # the end of the goal stays on screen under the idle text
        self.st.serve(current=None, settings=dict(SETTINGS))
        text = self.see()
        self.assertIn("done: tests pass", text)
        self.assertIn("[Goal]", text)
        self.st.serve(on=False)
        self.assertIn("not running", self.see())

    def test_the_last_goal_that_ended_between_two_looks_is_shown(self):
        self.st.serve(settings=dict(SETTINGS))
        self.st.goal(state="done", summary="tests pass", text="run the tests", ended=time.time() - 30, say=[{"t": 1.0, "text": "all green"}])
        text = self.see()
        for needle in ("run the tests", "all green", "done: tests pass", "Goal"):
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
        self.assertIn("sending", self.text())
        self.keys("c")
        self.assertIsNone(self.st.decision(), "the time is up: the service decides")
        self.st.pending(mode="approve", risk="high", deadline=time.time() - 1, pid="p2")
        self.p.look()
        self.keys("a", "y")
        self.assertIsNone(self.st.decision(), "the time is up: nothing is allowed")

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
        self.assertIn("sending in", raw)
        for bad in ("pwned\x07", "\x1b]0;", "\x1b[2Jbig") + tuple(BIDI):
            self.assertNotIn(bad, raw)
        self.assertEqual(set(re.findall(r"\x1b\[\??[0-9;]*([A-Za-z])", raw)) - set("HKmhlJ"), set(), "only the escape sequences of the panel itself")


class ApprovalPaneObject(unittest.TestCase):
    """The Panel that runs in the approval pane: the same decision file as the panel, one tap, and it never takes the pane for a panel."""

    def setUp(self):
        self.st = FakeState()
        self.addCleanup(self.st.close)
        self.clock = [100.0]
        self.screen = tempfile.TemporaryFile()
        self.addCleanup(self.screen.close)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.pop("TMUX_PANE", None)
        self.plain = panel.Panel(self.st.paths, in_fd=-1, out_fd=self.screen.fileno(), now=lambda: self.clock[0], bus=FakeBus(), color=False)
        os.environ[panel.dock.APPROVAL_ENV] = "1"
        self.p2 = panel.Panel(self.st.paths, in_fd=-1, out_fd=self.screen.fileno(), now=lambda: self.clock[0], bus=FakeBus(), color=False)
        for q in (self.plain, self.p2):
            self.addCleanup(lambda q=q: [os.close(fd) for fd in (q.wake_r, q.wake_w)])
        self.st.serve(current="g1")
        self.st.goal()

    def hit(self, key):
        row, c0, c1, _ = next(h for h in self.p2.hits if h[3] == key)
        self.p2.handle_key(("click", (c0 + c1) // 2, row))

    def test_the_env_var_makes_it_an_approval_pane(self):
        self.assertTrue(self.p2.approval and self.p2.model.approval_only)
        self.assertFalse(self.plain.approval, "a panel made without the variable is the sysop panel")

    def test_a_tap_on_allow_writes_the_decision_the_panel_writes(self):
        self.st.pending(mode="approve", risk="high", text="git push --force")
        self.p2.look()
        self.p2.draw(force=True)
        self.clock[0] += 1.0
        self.p2.focus_at = self.clock[0] - 0.05          # the tap that gave the pane the focus is the tap that answers
        self.hit("a")
        self.assertEqual(self.st.decision(), {"id": "p1", "decision": "approve", "by": "panel", "word": "run"})

    def test_a_tap_on_cancel_refuses(self):
        self.st.pending(mode="approve", risk="high", text="rm -rf build")
        self.p2.look()
        self.p2.draw(force=True)
        self.clock[0] += 1.0
        self.hit("c")
        self.assertEqual(self.st.decision(), {"id": "p1", "decision": "deny", "by": "panel"})

    def test_a_tap_inside_the_guard_is_ignored(self):
        self.st.pending(mode="approve", risk="high")
        self.p2.look()
        self.p2.draw(force=True)
        self.hit("a")
        self.assertIsNone(self.st.decision(), "half a second after it appeared nothing is answered")

    def test_a_stray_q_does_not_end_it(self):
        self.st.pending(mode="approve", risk="high")
        self.p2.look()
        self.clock[0] += 1.0
        self.p2.handle_key("q")
        self.assertFalse(self.p2.model.finished)

    def test_it_draws_no_sysop_word_and_no_goal(self):
        self.st.pending(mode="approve", risk="high", text="git push --force")
        self.p2.look()
        self.p2.draw(force=True)
        self.screen.seek(0)
        raw = strip_ansi(self.screen.read().decode("utf-8", "replace"))
        self.assertIn("ALLOW?", raw)
        self.assertNotIn("SYSOP", raw)
        self.assertNotIn("list the files", raw)


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
