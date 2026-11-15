"""The panel (container/tools/voice/lib/swarmbox_voice/panel.py): `swarmbox-voice panel`, the text program that shows the pending plan in a
tmux pane. Three layers, each tested the way it can be:

  * the pure parts: text wrapping and cleaning, the line editor, the key parser, the Model (what each key does) and render (state and size
    -> text) at several widths, with and without colour;
  * the whole program on a pty against a FAKE service (an HTTP server in this process that records every call), with real keys: run, edit,
    cancel, close, the high-risk gesture, expiry, the service being down, a resize, a click, a failed run;
  * (the real tmux side is in test_voice_dock.py, the real flow with the real service in the container checks.)

Run with: python3 -W error tests/test_voice_panel.py
"""
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402

from swarmbox_voice import panel  # noqa: E402
from swarmbox_voice.panel import KeyParser, LineEditor, Model, render, strip_ansi, text_width, wrap  # noqa: E402

LIB = os.path.join(voice_support.VOICE, "lib")


def risk(level, reasons=()):
    return {"level": level, "reasons": list(reasons), "needs_confirmation": True, "actions": [{"level": level, "reasons": list(reasons)}]}


def make_plan(pid="p1", text="pytest -x", level="low", enter=False, heard="run the tests", say="Typing it in the pane", reasons=(), expires=100):
    return {"id": pid, "text": heard, "say": say, "expires_in": expires, "risk": risk(level, reasons),
            "actions": [{"type": "send_text", "pane": "%2", "text": text, "enter": enter}]}


def model_with(plan, now=0.0):
    m = Model(now)
    m.set_plan(plan, now)
    m.ready_at = 0.0     # past the guard
    return m


def plain(frame):
    return [strip_ansi(l) for l in frame.lines]


# ------------------------------------------------------------------------------------------------------------------------ text helpers

class TextHelpers(unittest.TestCase):
    def test_wrap_breaks_at_spaces_and_in_long_words(self):
        self.assertEqual(wrap("aaa bbb ccc", 7), ["aaa bbb", "ccc"])
        self.assertEqual(wrap("x" * 25, 10), ["x" * 10, "x" * 10, "x" * 5])
        self.assertEqual(wrap("one\ntwo", 20), ["one", "two"])
        self.assertEqual(wrap("", 10), [""])
        for width in (1, 2, 5, 17):
            for line in wrap("the quick brown fox jumps over the lazy dog " * 3, width):
                self.assertLessEqual(text_width(line), width)

    def test_wrap_counts_wide_characters_as_two_cells(self):
        lines = wrap("日本語のテキストです", 6)
        self.assertTrue(all(text_width(l) <= 6 for l in lines), lines)
        self.assertEqual("".join(lines), "日本語のテキストです")

    def test_clean_removes_escape_sequences_and_bidi_marks(self):
        out = panel.clean("a\x1b[31mred\x1b]0;title\x07‮dcba​\x9b2Jz\r")
        for bad in ("\x1b", "\x07", "‮", "​", "\x9b", "\r"):
            self.assertNotIn(bad, out)
        self.assertEqual(panel.clean("one\ntwo"), "one\ntwo", "a line break is kept for wrapping")
        self.assertEqual(panel.clean(None), "")
        self.assertEqual(len(panel.clean("x" * 10000)), 4000)

    def test_clock(self):
        self.assertEqual([panel.clock(s) for s in (0, 5, 65, 120, -3)], ["0:00", "0:05", "1:05", "2:00", "0:00"])


# ------------------------------------------------------------------------------------------------------------------------ line editor

class Editor(unittest.TestCase):
    def feed(self, ed, *keys):
        for k in keys:
            ed.key(k)
        return ed

    def test_typing_and_moving(self):
        ed = self.feed(LineEditor("ls"), " ", "-", "l")
        self.assertEqual((ed.text, ed.pos), ("ls -l", 5))
        self.feed(ed, "left", "left", "X")
        self.assertEqual((ed.text, ed.pos), ("ls X-l", 4))
        self.feed(ed, "home", "A")
        self.assertEqual((ed.text, ed.pos), ("Als X-l", 1))
        self.feed(ed, "end", "Z")
        self.assertEqual(ed.text, "Als X-lZ")

    def test_backspace_and_delete(self):
        ed = self.feed(LineEditor("abcd"), "left", "backspace")
        self.assertEqual((ed.text, ed.pos), ("abd", 2))
        self.feed(ed, "delete")
        self.assertEqual((ed.text, ed.pos), ("ab", 2))
        self.feed(ed, "delete")
        self.assertEqual(ed.text, "ab", "delete at the end does nothing")
        self.feed(ed, "home", "backspace")
        self.assertEqual(ed.text, "ab", "backspace at the start does nothing")

    def test_the_edges_are_safe(self):
        ed = self.feed(LineEditor(""), "left", "right", "backspace", "delete", "home", "end")
        self.assertEqual((ed.text, ed.pos), ("", 0))
        ed = self.feed(LineEditor("x"), "right", "right", "right")
        self.assertEqual(ed.pos, 1)

    def test_unicode_and_control_keys(self):
        ed = self.feed(LineEditor(""), "é", "日", "ñ")
        self.assertEqual(ed.text, "é日ñ")
        self.assertFalse(ed.key("up"))
        self.assertFalse(ed.key("\x1b"))
        self.assertFalse(ed.key("tab"))
        self.assertEqual(ed.text, "é日ñ")
        self.feed(ed, "ctrl-a", "ctrl-e")
        self.assertEqual(ed.pos, 3)
        self.feed(ed, "left", "ctrl-u")
        self.assertEqual(ed.text, "ñ")

    def test_the_length_is_capped(self):
        ed = LineEditor("x" * panel.MAX_EDIT)
        ed.key("y")
        self.assertEqual(len(ed.text), panel.MAX_EDIT)

    def test_view_scrolls_horizontally_and_keeps_the_cursor_inside(self):
        ed = LineEditor("0123456789" * 6)
        shown, curw, left, right = ed.view(20)
        self.assertTrue(left and not right)
        self.assertLessEqual(curw, 19)
        self.assertLessEqual(text_width(shown), 20)
        ed.key("home")
        shown, curw, left, right = ed.view(20)
        self.assertEqual((curw, left, right), (0, False, True))
        self.assertEqual(shown, "01234567890123456789")
        for pos in range(0, 61, 7):
            ed.pos = pos
            shown, curw, left, right = ed.view(15)
            self.assertLessEqual(curw, 14, pos)


# ------------------------------------------------------------------------------------------------------------------------ keys

class Keys(unittest.TestCase):
    def parse(self, data, flush=False):
        p = KeyParser()
        keys = p.feed(data)
        if flush:
            keys += p.flush()
        return keys

    def test_plain_keys(self):
        self.assertEqual(self.parse(b"rec\r"), ["r", "e", "c", "enter"])
        self.assertEqual(self.parse(b"\x7f\x08"), ["backspace", "backspace"])
        self.assertEqual(self.parse("é日".encode()), ["é", "日"])
        self.assertEqual(self.parse(b"\x03\x01\x05\x15"), ["ctrl-c", "ctrl-a", "ctrl-e", "ctrl-u"])

    def test_arrows_home_end_delete_in_both_encodings(self):
        self.assertEqual(self.parse(b"\x1b[D\x1b[C\x1b[A\x1b[B"), ["left", "right", "up", "down"])
        self.assertEqual(self.parse(b"\x1b[H\x1b[F\x1bOH\x1bOF"), ["home", "end", "home", "end"])
        self.assertEqual(self.parse(b"\x1b[3~\x1b[1~\x1b[4~\x1b[5~\x1b[6~\x1b[7~\x1b[8~"),
                         ["delete", "home", "end", "pgup", "pgdn", "home", "end"])
        self.assertEqual(self.parse(b"\x1b[1;5D"), ["left"], "a modifier does not change the key")

    def test_a_lone_escape_is_a_key_only_after_the_wait(self):
        p = KeyParser()
        self.assertEqual(p.feed(b"\x1b"), [])
        self.assertTrue(p.pending())
        self.assertEqual(p.flush(), ["esc"])
        self.assertFalse(p.pending())

    def test_a_sequence_split_in_two_reads_is_one_key(self):
        p = KeyParser()
        self.assertEqual(p.feed(b"\x1b"), [])
        self.assertEqual(p.feed(b"[D"), ["left"])
        self.assertEqual(p.feed("é".encode()[:1]), [])
        self.assertEqual(p.feed("é".encode()[1:]), ["é"])

    def test_escape_followed_by_a_letter_is_two_keys(self):
        self.assertEqual(self.parse(b"\x1bx"), ["esc", "x"])

    def test_mouse_and_focus(self):
        self.assertEqual(self.parse(b"\x1b[<0;12;7M"), [("click", 12, 7)])
        self.assertEqual(self.parse(b"\x1b[<0;12;7m"), [], "a release is not a click")
        self.assertEqual(self.parse(b"\x1b[<2;12;7M"), [], "only the left button")
        self.assertEqual(self.parse(b"\x1b[<32;12;7M"), [], "a drag is not a click")
        self.assertEqual(self.parse(b"\x1b[<64;1;1M\x1b[<65;1;1M"), [("wheel", "up"), ("wheel", "down")])
        self.assertEqual(self.parse(b"\x1b[I\x1b[O"), ["focus-in", "focus-out"])

    def test_garbage_does_not_raise(self):
        for data in (b"\xff\xfe", b"\x1b[", b"\x1b[<x;y;zM", b"\x1b[99999999999~", bytes(range(256))):
            self.parse(data, flush=True)


# ------------------------------------------------------------------------------------------------------------------------ the model

class ModelKeys(unittest.TestCase):
    def test_r_runs_a_low_risk_plan_at_once(self):
        m = model_with(make_plan("a"))
        self.assertEqual(m.key("r", 1), ("run", "a"))
        self.assertEqual(model_with(make_plan("a", level="medium")).key("R", 1), ("run", "a"))

    def test_a_high_risk_plan_needs_the_word_run_and_enter(self):
        m = model_with(make_plan("h", "rm -rf build", "high", enter=True))
        self.assertIsNone(m.key("r", 1))
        self.assertEqual(m.mode, "word")
        for k in "run":
            self.assertIsNone(m.key(k, 1))
        self.assertEqual(m.key("enter", 1), ("run", "h"))

    def test_a_high_risk_plan_is_not_run_by_anything_else(self):
        for typed in ("", "r", "ru", "runn", "RUNNING", "yes", "y", "ok", "no", "run it", "rn"):
            m = model_with(make_plan("h", "rm x", "high", enter=True))
            m.key("r", 1)
            for k in typed:
                m.key(k, 1)
            cmd = m.key("enter", 1)
            if typed.strip().lower() == "run":
                self.assertEqual(cmd, ("run", "h"))
            else:
                self.assertIsNone(cmd, repr(typed))
                self.assertEqual(m.mode, "word", "it stays in the gesture, and the word is cleared")
                self.assertEqual(m.word, "")
                self.assertIn("type the word run", m.notice)
        # enter alone, r again, y: none of them runs
        m = model_with(make_plan("h", "rm x", "high"))
        for k in ("r", "enter", "r", "y", "enter", "c"):
            self.assertNotEqual((m.key(k, 1) or ("",))[0], "run", k)

    def test_escape_backs_out_of_the_high_risk_gesture_without_cancelling(self):
        m = model_with(make_plan("h", "rm x", "high"))
        m.key("r", 1)
        m.key("r", 1)
        self.assertIsNone(m.key("esc", 1))
        self.assertEqual((m.mode, m.word), ("view", ""))
        self.assertEqual(m.key("esc", 1), ("cancel", "h"), "in the plain view Esc cancels")

    def test_an_unknown_risk_level_is_treated_as_high(self):
        plan = make_plan("x")
        for bad in ({"level": "none"}, {}, None, "low"):
            plan["risk"] = bad
            m = model_with(dict(plan))
            self.assertEqual(m.level(), "high" if bad != "low" else "high")
            self.assertIsNone(m.key("r", 1))
            self.assertEqual(m.mode, "word")

    def test_c_and_esc_cancel_and_q_closes(self):
        for k in ("c", "C", "esc"):
            self.assertEqual(model_with(make_plan("a")).key(k, 1), ("cancel", "a"), k)
        for k in ("q", "Q", "ctrl-c"):
            self.assertEqual(model_with(make_plan("a")).key(k, 1), ("quit",), k)

    def test_other_keys_do_nothing(self):
        for k in ("x", "z", "tab", "enter", "left", "1", ("click", 1, 1), "focus-in"):
            m = model_with(make_plan("a"))
            self.assertIsNone(m.key(k, 1), k)
            self.assertEqual(m.mode, "view")

    def test_keys_are_ignored_while_a_plan_has_just_appeared(self):
        m = Model(10.0)
        m.set_plan(make_plan("a"), 10.0)
        self.assertIsNone(m.key("r", 10.1), "typing meant for another pane must not answer the plan")
        self.assertIsNone(m.key("c", 10.4))
        self.assertEqual(m.key("r", 10.0 + panel.GUARD + 0.01), ("run", "a"))
        # an edit made here does not start a new guard
        m.set_plan(make_plan("b"), 11.0, guard=False)
        self.assertEqual(m.key("r", 11.0), ("run", "b"))
        # the same plan arriving again is not a new plan
        m2 = model_with(make_plan("a"), 5.0)
        m2.set_plan(make_plan("a", expires=50), 6.0)
        self.assertEqual(m2.key("r", 6.0), ("run", "a"))

    def test_with_no_plan_only_q_and_esc_close(self):
        m = Model(0.0)
        self.assertEqual(m.key("q", 1), ("quit",))
        self.assertEqual(Model(0.0).key("esc", 1), ("quit",))
        for k in ("r", "e", "c", "enter"):
            self.assertIsNone(Model(0.0).key(k, 1), k)

    def test_a_plan_with_an_action_that_cannot_run_is_never_run(self):
        plan = make_plan("a")
        plan["actions"].append({"type": "run_shell", "cmd": "x"})
        m = model_with(plan)
        self.assertIsNone(m.key("r", 1))
        self.assertIn("cannot be run", m.notice)
        empty = make_plan("b")
        empty["actions"] = []
        m = model_with(empty)
        self.assertIsNone(m.key("r", 1))

    def test_a_plan_whose_end_was_never_shown_is_not_run(self):
        m = model_with(make_plan("a"))
        m.seen_end = False
        self.assertIsNone(m.key("r", 1))
        self.assertIn("Scroll down", m.notice)
        m.seen_end = True
        self.assertEqual(m.key("r", 1), ("run", "a"))

    def test_expiry_countdown(self):
        m = model_with(make_plan("a", expires=100), 50.0)
        self.assertEqual(m.remaining(50.0), 100)
        self.assertEqual(m.remaining(80.4), 70)
        self.assertEqual(m.remaining(500.0), 0)
        self.assertEqual(Model(0.0).remaining(1.0), 0)


class ModelEdit(unittest.TestCase):
    def plan2(self):
        plan = make_plan("m")
        plan["actions"].append({"type": "send_text", "pane": "%3", "text": "second", "enter": False})
        return plan

    def test_e_edits_the_only_text_and_enter_sends_it(self):
        m = model_with(make_plan("a", "ls"))
        self.assertIsNone(m.key("e", 1))
        self.assertEqual(m.mode, "edit")
        for k in (" ", "-", "l"):
            m.key(k, 1)
        self.assertEqual(m.key("enter", 1), ("edit", "a", {"0": "ls -l"}))
        self.assertEqual(m.mode, "view")

    def test_esc_aborts_the_edit(self):
        m = model_with(make_plan("a", "ls"))
        m.key("e", 1)
        m.key("x", 1)
        self.assertIsNone(m.key("esc", 1))
        self.assertEqual((m.mode, m.editor), ("view", None))
        self.assertEqual(m.plan["actions"][0]["text"], "ls", "the plan itself was not touched")
        self.assertEqual(m.key("esc", 1), ("cancel", "a"), "and a second Esc is a cancel, as in the plain view")

    def test_accepting_an_unchanged_text_sends_nothing(self):
        m = model_with(make_plan("a", "ls"))
        m.key("e", 1)
        self.assertIsNone(m.key("enter", 1))
        self.assertEqual(m.mode, "view")

    def test_the_keys_of_the_editor(self):
        m = model_with(make_plan("a", "abc"))
        m.key("e", 1)
        for k in ("left", "left", "X", "delete", "home", "Y", "end", "backspace"):
            m.key(k, 1)
        self.assertEqual(m.key("enter", 1), ("edit", "a", {"0": "YaX"}))

    def test_with_several_texts_e_asks_which(self):
        m = model_with(self.plan2())
        m.key("e", 1)
        self.assertEqual(m.mode, "pick")
        self.assertIsNone(m.key("9", 1))
        self.assertEqual(m.mode, "pick", "a number that is not an action changes nothing")
        m.key("2", 1)
        self.assertEqual((m.mode, m.edit_index), ("edit", 1))
        m.key("!", 1)
        self.assertEqual(m.key("enter", 1), ("edit", "m", {"1": "second!"}))
        m = model_with(self.plan2())
        m.key("e", 1)
        m.key("esc", 1)
        self.assertEqual(m.mode, "view")

    def test_actions_that_are_not_text_cannot_be_edited(self):
        plan = make_plan("a")
        plan["actions"] = [{"type": "select_pane", "pane": "%1"}]
        m = model_with(plan)
        self.assertIsNone(m.key("e", 1))
        self.assertEqual(m.mode, "view")
        self.assertIn("no text to edit", m.notice)

    def test_a_new_plan_resets_the_state(self):
        m = model_with(make_plan("a", "ls"))
        m.key("e", 1)
        m.set_plan(make_plan("b"), 1.0, guard=False)
        self.assertEqual((m.mode, m.editor, m.word), ("view", None, ""))

    def test_dead_plans_close_on_any_key(self):
        m = model_with(make_plan("a"))
        m.die("the plan expired")
        self.assertEqual(m.mode, "dead")
        self.assertEqual(m.key("x", 1), ("quit",))

    def test_the_end_of_the_plan_closes_the_panel(self):
        m = model_with(make_plan("a"))
        m.apply_poll(make_plan("a"), 1.0)
        self.assertFalse(m.finished)
        m.apply_poll(None, 2.0)
        self.assertTrue(m.finished, "run, cancelled or expired elsewhere: the pane closes")
        idle = Model(0.0)
        idle.apply_poll(None, 1.0)
        self.assertFalse(idle.finished, "a panel opened by hand with nothing pending waits")
        idle.apply_poll(make_plan("n"), 2.0)
        self.assertEqual(idle.plan["id"], "n")
        idle.apply_poll(None, 3.0)
        self.assertTrue(idle.finished)

    def test_a_dead_plan_message_survives_the_poll_that_says_it_is_gone(self):
        m = model_with(make_plan("a"))
        m.die("It did not run: tmux said no")
        m.apply_poll(None, 2.0)
        self.assertFalse(m.finished)
        self.assertEqual(m.mode, "dead")


# ------------------------------------------------------------------------------------------------------------------------ render

class Render(unittest.TestCase):
    def check_frame(self, frame, cols, rows):
        self.assertEqual(len(frame.lines), rows)
        for line in plain(frame):
            self.assertLessEqual(text_width(line), cols, line)

    def test_every_width_and_height_fits_and_shows_the_essentials(self):
        plan = make_plan("p", "pytest -x tests/test_shop.py --maxfail=2 " * 3, "medium", enter=True, reasons=["pushes to a remote"])
        for cols in (16, 20, 30, 40, 50, 60, 80, 120, 200):
            for rows in (8, 12, 24, 40):
                m = model_with(plan)
                f = render(m, cols, rows, 0.0)
                self.check_frame(f, cols, rows)
                text = "\n".join(plain(f))
                self.assertIn("[r] Run", text) if rows >= 12 or cols >= 40 else None
                self.assertIn("[q]", text, (cols, rows))

    def test_a_normal_pane_shows_everything_the_user_must_read(self):
        m = model_with(make_plan("p", "git status", "low", heard="show me the status", say="Showing the status"))
        text = "\n".join(plain(render(m, 50, 24, 0.0)))
        for needle in ("LOW RISK", 'heard: "show me the status"', "plan: Showing the status", "type into pane %2:", "git status",
                       "Enter is not pressed.", "[r] Run", "[e] Edit", "[c] Cancel", "[q] Close", "time left 1:40"):
            self.assertIn(needle, text)
        enter = "\n".join(plain(render(model_with(make_plan("p", "ls", enter=True)), 50, 24, 0.0)))
        self.assertIn("Enter is pressed: it runs.", enter)

    def test_risk_is_a_word_and_a_colour_never_colour_alone(self):
        for level, word, sgr in (("low", "LOW RISK", "74;222;128"), ("medium", "MEDIUM RISK", "251;191;36"), ("high", "HIGH RISK", "255;107;120")):
            m = model_with(make_plan("p", "x", level, reasons=["why not"] if level != "low" else []))
            colored = render(m, 60, 20, 0.0, color=True).lines[0]
            self.assertIn(word, strip_ansi(colored))
            self.assertIn(sgr, colored, "the badge has its colour")
            mono = render(m, 60, 20, 0.0, color=False)
            self.assertNotIn("\x1b", "".join(mono.lines), "NO_COLOR: no escape sequence at all")
            self.assertIn("[%s]" % word, mono.lines[0], "and the word is still there")

    def test_reasons_are_shown_for_medium_and_high_only(self):
        for level, shown in (("low", False), ("medium", True), ("high", True)):
            m = model_with(make_plan("p", "x", level, reasons=["pushes to a remote", "uses sudo"]))
            text = "\n".join(plain(render(m, 60, 20, 0.0)))
            self.assertEqual("why: pushes to a remote; uses sudo" in text, shown, level)

    def test_high_risk_mode_shows_the_gesture_and_the_word_typed_so_far(self):
        m = model_with(make_plan("h", "rm -rf build", "high", enter=True))
        m.key("r", 1)
        m.key("r", 1)
        m.key("u", 1)
        f = render(m, 50, 20, 0.0)
        text = "\n".join(plain(f))
        self.assertIn("type the word run, then Enter", " ".join(text.split()))
        self.assertIn("> ru", text)
        self.assertIsNotNone(f.cursor)
        self.assertNotIn("[r] Run", text, "the plain keys are not offered during the gesture")

    def test_the_edit_line_shows_the_text_and_places_the_cursor(self):
        m = model_with(make_plan("a", "ls -la"))
        m.key("e", 1)
        m.key("left", 1)
        f = render(m, 40, 16, 0.0)
        rows = plain(f)
        row, col = f.cursor
        self.assertEqual(rows[row - 1][1:], "ls -la")
        self.assertEqual(col, 2 + len("ls -l"), "the cursor sits on the character before the end")
        self.assertIn("Editing action 1. Enter accepts, Esc aborts.", " ".join("\n".join(rows).split()))

    def test_the_cursor_is_hidden_outside_the_input_modes(self):
        self.assertIsNone(render(model_with(make_plan("a")), 50, 20, 0.0).cursor)

    def test_hostile_text_cannot_inject_terminal_control(self):
        evil = "\x1b[2J\x1b]52;c;ZXZpbA==\x07‮evil\x9b31m"
        plan = make_plan("a", evil, "low", heard=evil, say=evil)
        plan["actions"][0]["pane"] = evil
        m = model_with(plan)
        out = "".join(render(m, 50, 20, 0.0, color=False).lines)
        for bad in ("\x1b", "\x07", "‮", "\x9b"):
            self.assertNotIn(bad, out)

    def test_the_key_line_stays_clear_of_the_microphone_button(self):
        for cols in (30, 40, 50, 80):
            f = render(model_with(make_plan("a")), cols, 20, 0.0)
            for row, c0, c1, key in f.hits:
                self.assertLessEqual(c1, cols - panel.MIC_RESERVE + 2, (cols, key))
        f = render(model_with(make_plan("a")), 40, 20, 0.0)
        self.assertEqual(sorted(k for *_, k in f.hits), ["c", "e", "q", "r"])
        for row, c0, c1, key in f.hits:
            self.assertIn("[%s]" % key, plain(f)[row - 1][c0 - 1:c1])

    def test_a_plan_taller_than_the_pane_scrolls_and_says_so(self):
        plan = make_plan("a", "line " * 200)
        m = model_with(plan)
        f = render(m, 40, 12, 0.0)
        self.check_frame(f, 40, 12)
        self.assertFalse(f.complete)
        text = "\n".join(plain(f))
        self.assertIn("more (Down)", text)
        self.assertIn("[r] Run", text, "the keys never scroll away")
        m.scroll = 10_000
        f = render(m, 40, 12, 0.0)
        self.assertTrue(f.complete, "the end is on screen after scrolling down")
        self.assertIn("end (Up: back)", "\n".join(plain(f)))
        self.assertGreater(m.scroll, 0)
        self.assertLess(m.scroll, 10_000, "the scroll is clamped")

    def test_a_short_plan_is_complete_in_a_normal_pane(self):
        self.assertTrue(render(model_with(make_plan("a")), 50, 24, 0.0).complete)

    def test_empty_and_down_states(self):
        m = Model(0.0)
        text = "\n".join(plain(render(m, 50, 12, 0.0)))
        self.assertIn("nothing is waiting for you", text)
        self.assertIn("Hold the microphone button", text)
        self.assertIn("[q] Close", text)
        self.assertNotIn("[r] Run", text)
        m.down = "The voice service is not answering (127.0.0.1:17682: refused). Trying again..."
        text = "\n".join(plain(render(m, 50, 12, 0.0)))
        self.assertIn("not answering", text)

    def test_a_plan_without_actions_says_so(self):
        plan = make_plan("a")
        plan["actions"] = []
        self.assertIn("no actions", "\n".join(plain(render(model_with(plan), 50, 20, 0.0))))

    def test_other_actions_are_described(self):
        plan = make_plan("a")
        plan["actions"] = [{"type": "new_window", "name": "build", "cwd": "~/shop"}, {"type": "select_pane", "pane": "%4"},
                           {"type": "weird"}]
        text = "\n".join(plain(render(model_with(plan), 60, 30, 0.0)))
        for needle in ("open a new window", "name: build", "folder: ~/shop", "switch to pane %4", "unknown action, it cannot be run"):
            self.assertIn(needle, text)

    def test_the_countdown_follows_the_clock(self):
        m = model_with(make_plan("a", expires=125), 0.0)
        self.assertIn("time left 2:05", plain(render(m, 50, 20, 0.0))[0])
        self.assertIn("time left 1:05", plain(render(m, 50, 20, 60.0))[0])
        self.assertIn("time left 0:00", plain(render(m, 50, 20, 999.0))[0])


# ------------------------------------------------------------------------------------------------------------------------ the fake service

class FakeService:
    """The service as the panel sees it: GET /voice/pending (long poll), POST /voice/run|edit|cancel. Records every call."""

    def __init__(self, plan=None):
        self.cond = threading.Condition()
        self.plan = plan
        self.calls = []                  # (method, path, body or None)
        self.run_answer = (200, {"ok": True, "results": [{"type": "send_text", "ok": True}]})
        self.edit_fn = lambda body, plan: dict(plan, id=plan["id"] + "'", actions=[dict(plan["actions"][0], text=list(body["edits"].values())[0])])
        self.httpd = None
        self.port = None

    def start(self, port=0):
        svc = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def reply(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlsplit(self.path)
                q = parse_qs(url.query)
                with svc.cond:
                    svc.calls.append(("GET", self.path, None))
                    wait = float(q.get("wait", ["0"])[0])
                    since = q.get("since", [""])[0]
                    end = time.time() + wait
                    while wait and (svc.plan["id"] if svc.plan else "") == since and time.time() < end:
                        svc.cond.wait(0.1)
                    self.reply(200, {"pending": svc.plan})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                with svc.cond:
                    svc.calls.append(("POST", self.path, body))
                    if self.path == "/voice/run":
                        status, out = svc.run_answer
                        if status == 200:
                            svc.plan = None
                            svc.cond.notify_all()
                        return self.reply(status, out)
                    if self.path == "/voice/cancel":
                        svc.plan = None
                        svc.cond.notify_all()
                        return self.reply(200, {"ok": True})
                    if self.path == "/voice/edit":
                        if svc.plan is None or body.get("id") != svc.plan["id"]:
                            return self.reply(409, {"error": "plan_cancelled", "message": "the plan was already cancelled"})
                        new = svc.edit_fn(body, svc.plan)
                        if isinstance(new, tuple):
                            return self.reply(*new)
                        svc.plan = new
                        svc.cond.notify_all()
                        return self.reply(200, new)
                self.reply(404, {"error": "no"})

        class Quiet(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):   # a panel that exits in the middle of a long poll is not an error
                pass

        self.httpd = Quiet(("127.0.0.1", port), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def set_plan(self, plan):
        with self.cond:
            self.plan = plan
            self.cond.notify_all()

    def posts(self, name=None):
        return [(p, b) for m, p, b in self.calls if m == "POST" and (name is None or p == "/voice/" + name)]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Terminal:
    """The panel program on a pty, as tmux runs it: bytes in, bytes out, a window size, signals."""

    def __init__(self, port, rows=30, cols=60, extra_env=None):
        self.rows, self.cols = rows, cols
        self.out = b""
        self.lock = threading.Lock()
        env = {"PATH": os.environ["PATH"], "PYTHONPATH": LIB, "TERM": "xterm-256color", "HOME": "/tmp", "LANG": "C.UTF-8"}
        env.update(extra_env or {})
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(sys.executable, [sys.executable, "-B", "-m", "swarmbox_voice", "panel", "--service", "127.0.0.1:%d" % port], env)
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

    def text(self, since=0):
        with self.lock:
            return strip_ansi(self.out[since:].decode("utf-8", "replace"))

    def mark(self):
        with self.lock:
            return len(self.out)

    def wait_text(self, needle, timeout=15.0, since=0):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text(since):
                return True
            if self.exited():
                break
            time.sleep(0.05)
        return needle in self.text(since)

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

    def wait_exit(self, timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.exited():
                return self.status
            time.sleep(0.05)
        return None

    def last_frame(self):
        """The rows of the last full redraw (each frame starts with a move to row 1)."""
        with self.lock:
            raw = self.out.decode("utf-8", "replace")
        i = raw.rfind("\x1b[1;1H")
        rows = {}
        for m in re.finditer(r"\x1b\[(\d+);1H(.*?)(?=\x1b\[\d+;1H|\x1b\[\?25|\Z)", raw[i:], re.S):
            rows[int(m.group(1))] = strip_ansi(m.group(2)).replace("\x1b[K", "").rstrip()
        return [rows.get(n, "") for n in range(1, max(rows) + 1)] if rows else []

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


class PanelProgram(unittest.TestCase):
    def setUp(self):
        self.svc = FakeService(make_plan("p1")).start()
        self.addCleanup(self.svc.stop)
        self.terms = []
        self.addCleanup(lambda: [t.close() for t in self.terms])

    def open(self, **kw):
        t = Terminal(self.svc.port, **kw)
        self.terms.append(t)
        return t

    def ready(self, t, needle="heard:"):
        self.assertTrue(t.wait_text(needle), t.text()[-400:])
        time.sleep(panel.GUARD + 0.15)       # past the guard against stray typing

    def test_it_shows_what_was_heard_the_plan_the_risk_and_the_action(self):
        self.svc.set_plan(make_plan("p1", "pytest -x", "medium", enter=True, heard="run the tests", say="Running pytest", reasons=["runs a program"]))
        t = self.open()
        self.ready(t)
        text = "\n".join(t.last_frame())
        for needle in ('heard: "run the tests"', "plan: Running pytest", "MEDIUM RISK", "why: runs a program", "type into pane %2:", "pytest -x",
                       "Enter is pressed: it runs.", "[r] Run", "time left"):
            self.assertIn(needle, text)
        self.assertEqual(self.svc.posts(), [], "showing a plan runs nothing")
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_r_runs_the_plan_with_its_id_and_the_pane_closes(self):
        t = self.open()
        self.ready(t)
        t.send("r")
        self.assertEqual(t.wait_exit(), 0, "it exits by itself so tmux closes the pane")
        self.assertEqual(self.svc.posts(), [("/voice/run", {"id": "p1"})])

    def test_c_and_a_lone_escape_cancel(self):
        for key in ("c", "\x1b"):
            self.svc.set_plan(make_plan("p1"))
            self.svc.calls.clear()
            t = self.open()
            self.ready(t)
            t.send(key)
            self.assertEqual(t.wait_exit(), 0, repr(key))
            self.assertEqual(self.svc.posts(), [("/voice/cancel", {"id": "p1"})], repr(key))

    def test_q_closes_and_leaves_the_plan_pending(self):
        t = self.open()
        self.ready(t)
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [])
        self.assertEqual(self.svc.plan["id"], "p1")

    def test_keys_in_the_first_moments_do_not_answer_the_plan(self):
        t = self.open()
        t.send("r")      # typed before the plan is even drawn
        self.assertTrue(t.wait_text("heard:"))
        t.send("rc")
        time.sleep(0.2)
        self.assertEqual(self.svc.posts(), [], "the guard dropped them")
        self.assertIsNone(t.wait_exit(0.3))

    def test_a_high_risk_plan_needs_run_and_enter(self):
        self.svc.set_plan(make_plan("h1", "rm -rf build", "high", enter=True, reasons=["deletes files recursively"]))
        t = self.open()
        self.ready(t)
        self.assertIn("HIGH RISK", "\n".join(t.last_frame()))
        t.send("r")
        self.assertTrue(t.wait_text("type the word run"))
        time.sleep(0.2)
        self.assertEqual(self.svc.posts(), [], "r alone does not run a high-risk plan")
        t.send("yes\r")
        self.assertTrue(t.wait_text("Not run."))
        self.assertEqual(self.svc.posts(), [])
        t.send("run\r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [("/voice/run", {"id": "h1"})])

    def test_edit_flow_with_the_line_editor_and_a_new_risk(self):
        t = self.open()
        self.ready(t)
        t.send("e")
        self.assertTrue(t.wait_text("Editing action 1"))
        # the text is "pytest -x": go home, add a word, left/right/delete/backspace on the way
        t.send("\x1b[H")                       # home
        t.send("sudo ")
        t.send("\x1b[C\x1b[D")                 # right, left
        t.send("\x1b[F")                       # end
        t.send("\x7f")                         # backspace removes the x
        t.send("y")
        t.send("\x1b[D\x1b[3~")                # left, then delete the y
        t.send("z")
        time.sleep(0.2)
        t.send("\r")
        end = time.time() + 5
        while time.time() < end and not self.svc.posts("edit"):
            time.sleep(0.05)
        self.assertEqual(self.svc.posts("edit"), [("/voice/edit", {"id": "p1", "edits": {"0": "sudo pytest -z"}})])
        mark = t.mark()
        self.assertTrue(t.wait_text("time left", since=mark), "the panel redrew with the new plan")
        time.sleep(0.3)
        # the service gave a new id: the panel now runs THAT plan
        t.send("r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts("run"), [("/voice/run", {"id": "p1'"})])

    def test_an_edit_that_makes_the_plan_high_risk_needs_the_gesture(self):
        self.svc.edit_fn = lambda body, plan: dict(plan, id="e1", risk=risk("high", ["deletes files"]),
                                                   actions=[dict(plan["actions"][0], text=list(body["edits"].values())[0], enter=True)])
        t = self.open()
        self.ready(t)
        t.send("e")
        self.assertTrue(t.wait_text("Editing action"))
        t.send("\x15rm -rf x\r")       # ctrl-u clears the line
        self.assertTrue(t.wait_text("HIGH RISK"))
        time.sleep(0.3)
        t.send("r")
        self.assertTrue(t.wait_text("type the word run"))
        self.assertEqual(self.svc.posts("run"), [])
        t.send("run\r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts("run"), [("/voice/run", {"id": "e1"})])

    def test_escape_aborts_the_edit_and_sends_nothing(self):
        t = self.open()
        self.ready(t)
        t.send("e")
        self.assertTrue(t.wait_text("Editing action 1"))
        t.send("zzz")
        t.send("\x1b")
        time.sleep(0.4)
        self.assertEqual(self.svc.posts(), [])
        self.assertIsNone(t.wait_exit(0.2), "Esc in the editor goes back to the plan; it does not close or cancel")
        t.send("r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [("/voice/run", {"id": "p1"})], "and the plan is the one it was")

    def test_a_refused_edit_keeps_the_plan_and_says_why(self):
        self.svc.edit_fn = lambda body, plan: (422, {"error": "plan_bad_text", "message": "control characters are not allowed"})
        t = self.open()
        self.ready(t)
        t.send("e")
        t.send("\x15bad\r")
        self.assertTrue(t.wait_text("The edit was refused: control characters are not allowed"))
        t.send("r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts("run"), [("/voice/run", {"id": "p1"})])

    def test_a_plan_that_expires_closes_the_panel_by_itself(self):
        self.svc.set_plan(make_plan("p1", expires=1))
        t = self.open()
        self.ready(t)
        self.svc.set_plan(None)        # the service dropped it: expiry
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [])

    def test_a_plan_run_or_cancelled_elsewhere_closes_the_panel(self):
        t = self.open()
        self.ready(t)
        self.svc.set_plan(None)
        self.assertEqual(t.wait_exit(), 0)

    def test_a_new_plan_replaces_the_one_shown_and_is_guarded_again(self):
        t = self.open()
        self.ready(t)
        self.svc.set_plan(make_plan("p2", "echo two", heard="second thing"))
        self.assertTrue(t.wait_text("second thing"))
        t.send("r")                       # a key right when the plan changed: dropped
        time.sleep(0.2)
        self.assertEqual(self.svc.posts(), [])
        time.sleep(panel.GUARD)
        t.send("r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [("/voice/run", {"id": "p2"})], "it ran the plan on screen, not the old one")

    def test_a_plan_that_was_replaced_while_the_key_was_pressed_is_not_run(self):
        t = self.open()
        self.ready(t)
        self.svc.run_answer = (409, {"error": "plan_cancelled", "message": "the plan was already cancelled"})
        t.send("r")
        self.assertTrue(t.wait_text("the plan was already cancelled"))
        self.assertIsNone(t.wait_exit(0.3), "the message waits for a key")
        t.send("x")
        self.assertEqual(t.wait_exit(), 0)

    def test_a_run_tmux_refused_is_shown_and_waits_for_a_key(self):
        self.svc.run_answer = (200, {"ok": False, "results": [{"type": "send_text", "ok": False, "error": "can't find pane: %2"}]})
        t = self.open()
        self.ready(t)
        t.send("r")
        self.assertTrue(t.wait_text("It did not run: can't find pane: %2"))
        self.assertIsNone(t.wait_exit(0.3))
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_a_run_blocked_because_a_pane_got_riskier_says_so(self):
        self.svc.run_answer = (409, {"error": "plan_risk_changed", "message": "a pane changed since the plan was made and it is now riskier; ask again"})
        t = self.open()
        self.ready(t)
        t.send("r")
        self.assertTrue(t.wait_text("now riskier; ask again"))
        t.send("\r")
        self.assertEqual(t.wait_exit(), 0)

    def test_with_no_plan_it_waits_and_shows_one_when_it_arrives(self):
        self.svc.set_plan(None)
        t = self.open()
        self.assertTrue(t.wait_text("nothing is waiting for you"))
        self.assertIsNone(t.wait_exit(0.5), "a panel opened by hand stays")
        self.svc.set_plan(make_plan("late", "echo late", heard="late plan"))
        self.assertTrue(t.wait_text("late plan"))
        time.sleep(panel.GUARD + 0.2)
        t.send("r")
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts("run"), [("/voice/run", {"id": "late"})])

    def test_with_no_plan_q_closes(self):
        self.svc.set_plan(None)
        t = self.open()
        self.assertTrue(t.wait_text("nothing is waiting for you"))
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_the_service_being_down_is_said_and_the_panel_recovers(self):
        free = FakeService().start()
        port = free.port
        free.stop()
        t = Terminal(port)
        self.terms.append(t)
        self.assertTrue(t.wait_text("The voice service is not answering"), t.text()[-300:])
        self.assertIn("127.0.0.1:%d" % port, t.text())
        self.assertIsNone(t.wait_exit(0.5), "it keeps trying")
        late = FakeService(make_plan("back", heard="back again")).start(port)
        self.addCleanup(late.stop)
        self.assertTrue(t.wait_text("back again", timeout=10), "it picked the plan up when the service came back")
        time.sleep(panel.GUARD + 0.2)
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_q_closes_while_the_service_is_down(self):
        free = FakeService().start()
        port = free.port
        free.stop()
        t = Terminal(port)
        self.terms.append(t)
        self.assertTrue(t.wait_text("not answering"))
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)

    def test_a_resize_redraws_to_the_new_width(self):
        self.svc.set_plan(make_plan("p1", "word " * 40))
        t = self.open(rows=30, cols=80)
        self.ready(t)
        wide = t.last_frame()
        self.assertTrue(max(len(l) for l in wide) > 45)
        t.resize(30, 40)
        time.sleep(0.6)
        narrow = t.last_frame()
        self.assertLessEqual(max(text_width(l) for l in narrow), 40, narrow)
        self.assertIn("[r] Run", "\n".join(narrow))
        self.assertGreater(len(narrow), 5)
        t.resize(12, 40)
        time.sleep(0.6)
        small = t.last_frame()
        self.assertLessEqual(len(small), 12)
        self.assertIn("[q] Close", "\n".join(small), "the keys are still on the last rows of a short pane")

    def test_a_click_on_run_runs_it_and_a_click_elsewhere_does_nothing(self):
        t = self.open(rows=30, cols=60)
        self.ready(t)
        f = render(model_with(make_plan("p1")), 60, 30, 0.0)
        hit = {k: (r, c0) for r, c0, c1, k in f.hits}
        r, c = hit["r"]
        t.send("\x1b[<0;3;3M")             # a click on the text
        t.send("\x1b[<0;%d;%dm" % (c, r))  # a release on the button is not a click
        time.sleep(0.3)
        self.assertEqual(self.svc.posts(), [])
        t.send("\x1b[<0;%d;%dM" % (c + 1, r))
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(self.svc.posts(), [("/voice/run", {"id": "p1"})])

    def test_a_click_that_just_gave_the_pane_the_focus_is_not_a_click_on_a_button(self):
        t = self.open(rows=30, cols=60)
        self.ready(t)
        f = render(model_with(make_plan("p1")), 60, 30, 0.0)
        r, c0 = {k: (r, c0) for r, c0, c1, k in f.hits}["r"]
        t.send("\x1b[I\x1b[<0;%d;%dM" % (c0 + 1, r))
        time.sleep(0.3)
        self.assertEqual(self.svc.posts(), [])
        time.sleep(0.5)
        t.send("\x1b[<0;%d;%dM" % (c0 + 1, r))
        self.assertEqual(t.wait_exit(), 0)
        self.assertEqual(len(self.svc.posts("run")), 1)

    def test_a_click_on_run_of_a_high_risk_plan_starts_the_gesture_only(self):
        self.svc.set_plan(make_plan("h", "rm -rf x", "high", enter=True))
        t = self.open(rows=30, cols=60)
        self.ready(t)
        f = render(model_with(make_plan("h", "rm -rf x", "high", enter=True)), 60, 30, 0.0)
        r, c0 = {k: (r, c0) for r, c0, c1, k in f.hits}["r"]
        t.send("\x1b[<0;%d;%dM" % (c0 + 1, r))
        self.assertTrue(t.wait_text("type the word run"))
        time.sleep(0.3)
        self.assertEqual(self.svc.posts(), [])

    def test_the_terminal_is_restored_on_exit(self):
        t = self.open()
        self.ready(t)
        t.send("q")
        self.assertEqual(t.wait_exit(), 0)
        out = t.out.decode("utf-8", "replace")
        self.assertIn("\x1b[?1049h", out)
        self.assertTrue(out.rstrip().endswith("\x1b[?1049l"), "the alternate screen is left last")
        for mode in ("\x1b[?25h", "\x1b[?1000l", "\x1b[?1006l", "\x1b[?1004l"):
            self.assertIn(mode, out)

    def test_sigterm_and_hangup_exit_cleanly(self):
        for sig in (signal.SIGTERM, signal.SIGHUP):
            t = self.open()
            self.ready(t)
            os.kill(t.pid, sig)
            self.assertEqual(t.wait_exit(), 0, sig)
            self.assertIn("\x1b[?1049l", t.out.decode("utf-8", "replace"))
        self.assertEqual(self.svc.posts(), [], "being closed does not answer the plan")

    def test_without_a_terminal_it_says_so_and_exits(self):
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "panel", "--service", "127.0.0.1:%d" % self.svc.port],
                           env={"PATH": os.environ["PATH"], "PYTHONPATH": LIB}, capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 2)
        self.assertIn("needs a terminal", p.stderr)

    def test_the_panel_only_calls_the_loopback_service_paths_it_should(self):
        t = self.open()
        self.ready(t)
        t.send("q")
        t.wait_exit()
        paths = {p.split("?")[0] for m, p, b in self.svc.calls}
        self.assertEqual(paths, {"/voice/pending"})

    def test_no_colour_when_the_environment_asks(self):
        t = self.open(extra_env={"NO_COLOR": "1"})
        self.assertTrue(t.wait_text("heard:"))
        out = t.out.decode("utf-8", "replace")
        self.assertNotIn("38;2;", out)
        self.assertIn("[LOW RISK]", strip_ansi(out))


if __name__ == "__main__":
    unittest.main()
