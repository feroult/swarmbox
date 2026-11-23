"""swarmbox-tabs (container/scripts/swarmbox-tabs.py) against a FAKE tmux (tests/support/tabs_support.py): the active-tab rule, addressing, the
hidden panels, the screen pipeline (markers, last N lines, clip, secrets), the typing rules (pause, separate Enter, dialog, busy, queue, slash,
verify, copy mode, braces), errors, timeouts, the lock between sends, and the command line (JSON, exit codes, stdin). No tmux, network or model.
The same code against a real tmux is tests/slow/test_tabs_real.py (Podman). Run with: python3 tests/fast/test_tabs.py"""
import contextlib
import io
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from tabs_support import FakeTmux, claude_pane, load_module  # noqa: E402
from helpers import ROOT  # noqa: E402

mod = load_module()
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0"


class Base(unittest.TestCase):
    def setUp(self):
        self.ft = FakeTmux()
        self.addCleanup(self.ft.close)

    def code(self, fn, *a):
        with self.assertRaises(Exception) as cm:
            fn(*a)
        return cm.exception.code, cm.exception.message


class TestTabs(Base):
    def three(self):
        self.ft.window("@1", 0, "idle")
        self.ft.window("@2", 1, "build", cwd=os.path.expanduser("~") + "/proj", cmd="make")
        self.ft.window("@3", 2, "claude", **claude_pane())
        return self.ft

    def test_fields_and_the_active_tab_is_the_window_of_the_latest_client(self):
        ft = self.three()
        ft.client("@1", 100)
        ft.client("@3", 105)
        ft.client("@2", 103)
        ft.save()
        tabs = ft.driver().list_tabs()
        self.assertEqual([t["tab"] for t in tabs], ["@1", "@2", "@3"])
        self.assertEqual([t["active"] for t in tabs], [False, False, True])
        t = tabs[1]
        self.assertEqual((t["label"], t["index"], t["name"], t["dir"], t["cmd"], t["pane"]), ("1:build", 1, "build", "~/proj", "make", "%2"))

    def test_open_tab_is_a_new_window_of_the_session_with_the_allowlisted_agent(self):
        ft = self.three().save()
        d = ft.driver()
        res = d.open_tab(name="api", cwd=ft.dir, agent="claude")
        self.assertEqual(res, {"ok": True, "tab": "@4", "name": "api", "agent": "claude"})
        _, a = ft.calls("new-window")[-1]
        self.assertEqual(a, ["new-window", "-P", "-F", "#{window_id}", "-t", "=main", "-n", "api", "-c", ft.dir, "claude"])
        d.open_tab()
        self.assertEqual(ft.calls("new-window")[-1][1][-2:], ["-t", "=main"], "a shell: no program after the options")
        self.assertEqual(self.code(d.open_tab, None, None, "vim")[0], "usage")

    def test_focus_and_close_are_select_and_kill_window(self):
        ft = self.three().save()
        d = ft.driver()
        self.assertEqual(d.focus_tab("build")["tab"], "@2")
        self.assertEqual(ft.calls("select-window")[-1][1], ["select-window", "-t", "@2"])
        self.assertEqual(d.close_tab("2")["tab"], "@3")
        self.assertEqual(ft.calls("kill-window")[-1][1], ["kill-window", "-t", "@3"])
        self.assertEqual([t["tab"] for t in d.list_tabs()], ["@1", "@2"])

    def test_the_command_line_has_open_focus_and_close(self):
        ft = self.three().save()
        d = ft.driver()
        self.assertEqual(mod.run(["focus", "@1"], tabs=d)["tab"], "@1")
        self.assertEqual(mod.run(["open", "--agent", "shell", "--name", "x"], tabs=d)["tab"], "@4")
        self.assertEqual(mod.run(["close", "@4"], tabs=d)["tab"], "@4")
        for bad in (["focus"], ["close", "@1", "@2"], ["open", "extra"]):
            self.assertEqual(self.code(mod.run, bad, d)[0], "usage")

    def test_control_mode_clients_and_clients_on_other_windows_do_not_count(self):
        ft = self.three()
        ft.client("@1", 100)
        ft.client("@2", 999, control=True)
        ft.client("@99", 500)         # shows a window that is not a tab of the session
        ft.save()
        self.assertEqual([t["tab"] for t in ft.driver().list_tabs() if t["active"]], ["@1"])

    def test_without_clients_the_current_window_of_the_session(self):
        ft = self.three()
        ft.state["current"] = "@3"
        ft.save()
        self.assertEqual([t["tab"] for t in ft.driver().list_tabs() if t["active"]], ["@3"])

    def test_exactly_one_active_even_when_the_current_window_is_a_panel_window(self):
        ft = self.three()
        ft.window("@4", 3, "panel", sysop="1")
        ft.state["current"] = "@4"
        ft.save()
        tabs = ft.driver().list_tabs()
        self.assertEqual([t["tab"] for t in tabs], ["@1", "@2", "@3"])      # a window of only a panel is not a tab
        self.assertEqual(sum(t["active"] for t in tabs), 1)

    def test_panels_are_hidden_and_the_pane_of_a_tab_skips_them(self):
        ft = self.three()
        w = ft.state["windows"][0]
        w["panes"][0].update(active=False, last=True)
        w["panes"].append({"id": "%11", "active": True, "sysop": "1", "cmd": "swarmbox-sysop"})
        ft.save()
        d = ft.driver()
        t = d.list_tabs()[0]
        self.assertEqual((t["pane"], t["panes"]), ("%1", ["%1"]))       # the focus is in the panel: pane_last
        self.assertEqual(d.resolve("@1").pane, "%1")
        self.assertNotIn("sysop", d.screen("@1", None)["text"])

    def test_a_start_command_that_holds_the_separator_cannot_move_the_name(self):
        ft = self.three()
        ft.window("@4", 3, "real", start="sleep 99 # %s" % ("x" + mod.SEP + "y" + mod.SEP + "z"))
        d = ft.save().driver()
        t = [x for x in d.list_tabs() if x["tab"] == "@4"][0]
        self.assertEqual((t["name"], t["label"]), ("real", "3:real"))
        self.assertEqual(d.resolve("real").id, "@4")
        self.assertEqual(d.screen("real", None)["tab"], "@4")

    def test_a_panel_is_still_hidden_by_the_marker_in_its_start_command(self):
        ft = self.three()
        ft.window("@4", 3, "panel", start="SWARMBOX_SYSOP_PANEL=1 swarmbox-sysop panel")
        self.assertEqual([t["tab"] for t in ft.save().driver().list_tabs()], ["@1", "@2", "@3"])

    def test_addresses_id_label_index_name(self):
        d = self.three().save().driver()
        for a in ("@2", "1:build", "1", "build"):
            self.assertEqual(d.resolve(a).id, "@2", a)
        self.assertEqual(d.resolve("0:idle").id, "@1")

    def test_duplicate_names_are_an_error_that_lists_the_candidates(self):
        ft = self.three()
        ft.window("@4", 3, "build")
        d = ft.save().driver()
        code, msg = self.code(d.resolve, "build")
        self.assertEqual(code, "ambiguous_tab")
        self.assertIn("1:build (@2)", msg)
        self.assertIn("3:build (@4)", msg)
        self.assertEqual(d.resolve("@4").index, 3)                  # the id and the label still work
        self.assertEqual(d.resolve("3:build").id, "@4")
        self.assertEqual(self.code(d.screen, "build", None)[0], "ambiguous_tab")
        self.assertEqual(self.code(d.send_body, "build", {"run": "x"})[0], "ambiguous_tab")
        self.assertEqual(self.ft.sent(), [])

    def test_a_stale_id_is_no_such_tab_with_the_list(self):
        d = self.three().save().driver()
        code, msg = self.code(d.resolve, "@9")
        self.assertEqual(code, "no_such_tab")
        self.assertIn("0:idle (@1)", msg)


class TestScreen(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "t", screen="plain\n\x1b[7m selected \x1b[27m x\n\x1b[48;5;237mhighlighted\x1b[49m\n\x1b[31mfailed\x1b[39m",
                       cx=3, cy=2, w=100, h=30)
        self.d = self.ft.save().driver()

    def test_markers_cursor_and_size(self):
        s = self.d.screen("@1", None)
        self.assertEqual(s["text"], "plain\n [sel]selected[/sel]  x\n[bg]highlighted[/bg]\n[err]failed[/err]")
        self.assertEqual((s["tab"], s["pane"], s["cursor"], s["size"], s["alternate"], s["in_mode"]), ("@1", "%1", [3, 2], [100, 30], False, False))

    def test_the_command_is_capture_pane_with_J_and_e_and_the_lines_ask_for_scrollback(self):
        self.d.screen("@1", 5)
        cap = self.ft.calls("capture-pane")[-1][1]
        self.assertEqual(cap, ["capture-pane", "-p", "-J", "-e", "-t", "%1", "-S", "-5"])

    def test_last_n_lines_after_the_conversion(self):
        s = self.d.screen("@1", 2)
        self.assertEqual(s["text"], "[bg]highlighted[/bg]\n[err]failed[/err]")

    def test_the_secret_is_removed_after_the_markers_and_never_on_raw_escape_text(self):
        # the escape code splits the key: a filter on the raw text would not see it
        self.ft.state["windows"][0]["panes"][0]["screen"] = "token sk-\x1b[1m" + KEY[3:] + "\x1b[0m end\nAPI_TOKEN=\x1b[7mhunter2\x1b[27m\nok \x1b[7mfine\x1b[27m"
        self.ft.save()
        text = self.d.screen("@1", None)["text"]
        self.assertNotIn(KEY[3:], text)
        self.assertNotIn("hunter2", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("[sel]fine[/sel]", text)

    def test_a_private_key_block_is_removed_even_with_markers_inside(self):
        self.ft.state["windows"][0]["panes"][0]["screen"] = "-----BEGIN RSA PRIVATE KEY-----\n\x1b[7mMIIEowIBAAKCAQEA\x1b[27m\n-----END RSA PRIVATE KEY-----\nafter"
        self.ft.save()
        self.assertEqual(self.d.screen("@1", None)["text"], "[REDACTED]\nafter")

    def test_a_huge_line_is_clipped_and_the_filter_is_fast(self):
        self.ft.state["windows"][0]["panes"][0]["screen"] = "-" * 100000 + "\nnext"
        self.ft.save()
        t = time.time()
        text = self.d.screen("@1", None)["text"]
        self.assertLess(time.time() - t, 2.0)
        first = text.split("\n")[0]
        self.assertTrue(first.endswith("[... 99000 more characters]"), first[-40:])
        self.assertEqual(text.split("\n")[1], "next")

    def test_a_full_screen_program_offers_no_lines(self):
        self.ft.state["windows"][0]["panes"][0]["alt"] = True
        self.ft.save()
        s = self.d.screen("@1", 3)
        self.assertTrue(s["alternate"])
        self.assertIsNone(s["lines"])
        self.assertNotIn("-S", self.ft.calls("capture-pane")[-1][1])
        self.assertEqual(len(s["text"].split("\n")), 4)             # the visible screen, not the last 3 lines

    def test_tabs_keeps_no_cache(self):
        self.d.screen("@1", None)
        self.ft.load()
        self.ft.state["windows"][0]["panes"][0]["screen"] = "changed"
        self.ft.save()
        self.assertEqual(self.d.screen("@1", None)["text"], "changed")


class TestSend(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "sh")
        self.ft.window("@2", 1, "agent", **claude_pane())
        self.ft.save()

    def typed(self, pane):
        return self.ft.pane(pane)["typed"]

    def test_run_is_text_then_a_separate_enter_after_the_pause(self):
        d = self.ft.driver(pause=0.15)
        d.send_body("@1", {"run": "ls -la"})
        sent = self.ft.sent()
        self.assertEqual([a for _, a in sent], [["-l", "--", "ls -la"], ["Enter"]])        # two tmux processes, the text is literal
        self.assertGreaterEqual(sent[1][0] - sent[0][0], 0.15)
        self.assertEqual(self.ft.calls("send-keys")[0][1][:3], ["send-keys", "-t", "%1"])  # the target is the pane id

    def test_run_is_literal_text_and_braces_in_it_are_not_keys(self):
        d = self.ft.driver()
        d.send_body("@1", {"run": "echo {Esc} ${HOME} {"})
        self.assertEqual(self.typed("%1"), ["echo {Esc} ${HOME} {", "<Enter>"])

    def test_input_braces_are_keys_exactly_as_parse_keys(self):
        d = self.ft.driver()
        d.send_body("@1", {"input": "ab{C-c}{Esc}cd{{x}}{Up}{foo}${HOME}{HOME}{ {\"a\": 1}"})
        self.assertEqual(self.typed("%1"), ["ab", "<C-c>", "<Escape>", "cd{x}", "<Up>", "{foo}${HOME}{HOME}{ {\"a\": 1}"])
        self.assertEqual(mod.parse_keys("{F12}{F13}{M-x}{M-xy}{c-c}"), [("key", "F12"), ("text", "{F13}"), ("key", "M-x"), ("text", "{M-xy}{c-c}")])
        self.assertEqual(mod.parse_keys("{PgUp}{PgDn}{Delete}{BTab}"), [("key", "PageUp"), ("key", "PageDown"), ("key", "DC"), ("key", "BTab")])

    def test_each_key_is_its_own_call_with_the_pause_between(self):
        d = self.ft.driver(pause=0.1)
        d.send_body("@1", {"input": "{Esc}{Esc}"})
        s = self.ft.sent()
        self.assertEqual([a for _, a in s], [["Escape"], ["Escape"]])
        self.assertGreaterEqual(s[1][0] - s[0][0], 0.1)

    def test_multi_line_text_is_one_literal_call(self):
        d = self.ft.driver()
        d.send_body("@1", {"run": "line one\nline two \"q\" 'q' `bt` $(id) é"})
        self.assertEqual(self.typed("%1")[0], "line one\nline two \"q\" 'q' `bt` $(id) é")

    def test_a_pane_in_copy_mode_is_cancelled_first(self):
        self.ft.load()
        self.ft.state["windows"][0]["panes"][0]["in_mode"] = True
        self.ft.save()
        self.ft.driver().send_body("@1", {"run": "x"})
        self.assertEqual(self.typed("%1"), ["<cancel>", "x", "<Enter>"])
        self.assertEqual(self.ft.sent()[0][1], ["-X", "cancel"])

    def test_bad_bodies_type_nothing(self):
        d = self.ft.driver()
        for body in ("text", None, 5, [], {}, {"run": 5}, {"run": ""}, {"input": ""}, {"run": "a", "input": "b"}, {"x": "a"}, {"run": "a", "queue": "yes"},
                     {"run": "a", "extra": True}, {"run": "a\x00b"}, {"input": "{{"[:0]}):
            self.assertEqual(self.code(d.send_body, "@1", body)[0], "bad_body", repr(body))
        self.assertEqual(self.ft.sent(), [])

    def test_a_dialog_is_refused_and_nothing_is_typed(self):
        self.ft.window("@3", 2, "dlg", **claude_pane("dialog"))
        self.ft.save()
        d = self.ft.driver()
        self.assertEqual(self.code(d.send_body, "@3", {"run": "hello"})[0], "dialog_open")
        self.assertEqual(self.code(d.send_body, "@3", {"run": "hello", "queue": True})[0], "dialog_open")      # queueing does not help
        self.assertEqual(self.ft.sent(), [])
        d.send_body("@3", {"input": "1"})                              # an answer is typed: input is not judged
        d.send_body("@3", {"input": "{Enter}"})
        self.assertEqual(self.typed("%3"), ["1", "<Enter>"])

    def test_a_busy_agent_is_refused_unless_queue(self):
        self.ft.window("@3", 2, "busy", **claude_pane("busy"))
        self.ft.save()
        d = self.ft.driver()
        code, msg = self.code(d.send_body, "@3", {"run": "next"})
        self.assertEqual(code, "busy_tab")
        self.assertIn("queue", msg)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("@3", {"run": "next", "queue": True})
        self.assertEqual(self.typed("%3"), ["next", "<Enter>"])
        d.send_body("@3", {"input": "{Esc}"})                         # the interrupt is allowed: it is not a submission
        self.assertEqual(self.ft.pane("%3")["claude"]["mode"], "idle")

    def test_slash_and_bang_are_refused_for_an_agent_not_for_a_shell(self):
        d = self.ft.driver()
        for text in ("/help", "!ls"):
            self.assertEqual(self.code(d.send_body, "@2", {"run": text})[0], "slash_refused")
        self.assertEqual(self.ft.sent(), [])
        d.send_body("@1", {"run": "/bin/ls"})                         # a shell: it is a path
        d.send_body("@2", {"run": "/clear", "slash": True})           # explicit opt-in
        self.assertEqual(self.typed("%1"), ["/bin/ls", "<Enter>"])
        self.assertEqual(self.typed("%2"), ["/clear", "<Enter>"])

    def test_input_text_without_enter_is_raw(self):
        d = self.ft.driver()
        d.send_body("@2", {"input": "/not-judged"})
        self.assertEqual(self.typed("%2"), ["/not-judged"])

    def test_agent_prompt_is_submitted_and_checked(self):
        d = self.ft.driver()
        d.send_body("@2", {"run": "reply with exactly PONG"})
        self.assertEqual(self.typed("%2"), ["reply with exactly PONG", "<Enter>"])
        c = self.ft.pane("%2")["claude"]
        self.assertEqual(c["box"], "")
        self.assertIn("❯ reply with exactly PONG", c["history"])

    def test_a_swallowed_enter_is_pressed_once_more_and_the_text_is_not_typed_again(self):
        self.ft.window("@3", 2, "flaky", **claude_pane(swallow=1))
        self.ft.save()
        self.ft.driver(verify_timeout=0.3).send_body("@3", {"run": "a prompt that stays"})
        self.assertEqual(self.typed("%3"), ["a prompt that stays", "<Enter>", "<Enter>"])

    def test_an_enter_that_never_submits_is_not_submitted(self):
        self.ft.window("@3", 2, "stuck", **claude_pane(swallow=99))
        self.ft.save()
        code, msg = self.code(self.ft.driver(verify_timeout=0.3).send_body, "@3", {"run": "x prompt"})
        self.assertEqual(code, "not_submitted")
        self.assertEqual(self.typed("%3"), ["x prompt", "<Enter>", "<Enter>"])               # two Enters, never more

    def test_a_pasted_text_placeholder_in_the_box_counts_as_not_submitted(self):
        self.ft.window("@3", 2, "paste", **claude_pane(swallow=99))
        self.ft.state["windows"][2]["panes"][0]["claude"]["box"] = ""
        self.ft.save()
        d = self.ft.driver(verify_timeout=0.2)
        self.assertEqual(self.code(d.send_body, "@3", {"run": "long " * 200})[0], "not_submitted")

    def test_a_queued_message_while_busy_counts_as_submitted(self):
        self.ft.window("@3", 2, "busy", **claude_pane("busy"))
        self.ft.save()
        self.ft.driver(verify_timeout=0.3).send_body("@3", {"run": "queued one", "queue": True})
        self.assertEqual(self.typed("%3"), ["queued one", "<Enter>"])

    def test_the_agent_is_known_by_its_screen_when_the_command_is_a_shell(self):
        p = claude_pane("dialog")
        p["cmd"] = "sh"                                           # claude started as the command of new-session
        self.ft.window("@3", 2, "viasn", **p)
        self.ft.save()
        self.assertEqual(self.code(self.ft.driver().send_body, "@3", {"run": "x"})[0], "dialog_open")

    def test_a_shell_screen_that_says_do_you_want_to_is_no_dialog(self):
        self.ft.state["windows"][0]["panes"][0]["screen"] = "Do you want to continue? [Y/n]"
        self.ft.save()
        self.ft.driver().send_body("@1", {"run": "y"})
        self.assertEqual(self.typed("%1"), ["y", "<Enter>"])

    def test_sends_to_one_pane_never_interleave(self):
        d = self.ft.driver(pause=0.05)
        ts = [threading.Thread(target=d.send_body, args=("@1", {"run": "msg%d" % i})) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        typed = self.typed("%1")
        self.assertEqual(len(typed), 8)
        for i in range(0, 8, 2):
            self.assertTrue(typed[i].startswith("msg") and typed[i + 1] == "<Enter>", typed)


class TestScreenSecretsAndMarkers(Base):
    """The secrets are found in the plain text of the pane, whatever the colours, and the markers are written afterwards."""

    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "t")
        self.pane = self.ft.state["windows"][0]["panes"][0]
        self.d = self.ft.save().driver()

    def screen(self, raw, lines=None):
        self.pane["screen"] = raw
        self.ft.save()
        return self.d.screen("@1", lines)["text"]

    def test_a_secret_wrapped_by_hard_line_breaks_is_removed_on_every_row(self):
        # a TUI at a narrow width wraps a token over rows that have no keyword and no prefix; `-` and `_` are token characters
        tok = "sk-" + "ant-oat01-" + ("Y4rUmer_BH3M1XS0DRdJuPnBIKpi99lSi0tcL21p" * 3)[:95]
        rows = [tok[:40], tok[40:80], tok[80:]]
        for raw in ("The login token is:\n" + "\n".join(rows) + "\n$ ready", "login " + rows[0] + "\n" + "\n".join(rows[1:]), "\n".join(rows)):
            out = self.screen(raw)
            for i in range(0, len(tok) - 15, 8):
                self.assertNotIn(tok[i:i + 16], out, raw[:20])
            self.assertIn("[REDACTED]", out)
        self.assertTrue(self.screen("The login token is:\n" + "\n".join(rows) + "\n$ ready").endswith("\n$ ready"))

    def test_rows_of_plain_words_are_not_taken_for_a_wrapped_secret(self):
        text = "installation-directory-listing\nREADME-with-a-long-name-here\nshort"
        self.assertEqual(self.screen(text), text)

    def test_a_colour_inside_a_name_does_not_hide_the_value(self):
        # `grep --color=always KEY .env` paints the matched word red, in the middle of the name
        self.assertEqual(self.screen("API_\x1b[01;31m\x1b[KKEY\x1b[m\x1b[K=supersecretvalue1234"), "API_[err]KEY[/err]=[REDACTED]")
        self.assertEqual(self.screen("\x1b[01;31m\x1b[Kpassword\x1b[m\x1b[K=hunter2hunter2\n\x1b[01;31m\x1b[Kapi_key\x1b[m\x1b[K: abcdef123456"),
                         "[err]password[/err]=[REDACTED]\n[err]api_key[/err]: [REDACTED]")
        self.assertEqual(self.screen("DB_\x1b[01;31m\x1b[KPASSWORD\x1b[m\x1b[K=correct-horse-battery"), "DB_[err]PASSWORD[/err]=[REDACTED]")

    def test_a_colour_inside_a_token_does_not_hide_it(self):
        for raw in ("sk-ant-api03-\x1b[31mAbCdEfGhIjKlMnOpQrStUv\x1b[0m", "sk-abc\x1b[31mdefghijklmnopqrstuv\x1b[0mwxyz",
                    "ghp_abcdefghij\x1b[7mklmnopqrstuvwxyz0123", "xoxb-12345\x1b[44m67890-abcdef\x1b[0m"):
            text = self.screen(raw)
            self.assertEqual(text, "[REDACTED]", raw)

    def test_a_secret_inside_a_span_leaves_balanced_spans(self):
        # the closing tag used to be swallowed by the value of the secret
        self.assertEqual(self.screen("\x1b[7mAPI_KEY=abc123def\x1b[0m"), "[sel]API_KEY=[REDACTED][/sel]")
        self.assertEqual(self.screen("\x1b[44mAuthorization: Bearer abcdefgh12345\x1b[0m"), "[bg]Authorization: [REDACTED][/bg]")
        self.assertEqual(self.screen("\x1b[31mtoken=abc\x1b[0m and \x1b[7mok\x1b[0m"), "[err]token=[REDACTED][/err] and [sel]ok[/sel]")

    def test_the_colours_of_what_is_kept_follow_the_text(self):
        self.assertEqual(self.screen("\x1b[7mone\x1b[0m KEY=\x1b[31msecretvalue\x1b[0m \x1b[7mtwo\x1b[0m"),
                         "[sel]one[/sel] KEY=[err][REDACTED][/err] [sel]two[/sel]")

    def test_a_secret_across_the_cut_of_a_long_line_is_removed_whole(self):
        text = self.screen("x " * 495 + " sk-abcdefghijklmnopqrstuvwxyz0123456789")      # blanks: a single run of 120 base64 characters is redacted on its own
        self.assertNotIn("sk-abc", text)
        self.assertNotIn("abcdef", text)
        self.assertIn("[REDACTED", text)
        self.assertTrue(text.endswith("more characters]"), text[-30:])

    def test_one_long_base64_run_on_a_single_line_is_removed(self):
        body = "LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0K" * 6          # `base64 -w0 ~/.ssh/id_rsa` on a wide pane
        self.assertEqual(self.screen("$ base64 -w0 key\n" + body + "\n$ "), "$ base64 -w0 key\n[REDACTED]\n$")
        self.assertEqual(self.screen("sha256 " + "a" * 64), "sha256 " + "a" * 64)

    def test_a_private_key_with_colours_in_it(self):
        self.assertEqual(self.screen("-----BEGIN PRIVATE KEY-----\n\x1b[31mMIIE\x1b[0m\nxx\n-----END PRIVATE KEY-----\nafter"), "[REDACTED]\nafter")

    def test_last_n_lines_are_cut_before_the_filter_as_before(self):
        self.assertEqual(self.screen("one\n\x1b[7mtwo\x1b[0m\nthree", 2), "[sel]two[/sel]\nthree")

    def test_text_that_looks_like_a_marker_cannot_forge_one(self):
        # program output `[sel]Yes, delete everything[/sel]` is not a reverse-video selection
        text = self.screen("[sel]Yes, delete everything[/sel] [bg]a[/bg] [err]b[/err] [REDACTED] [/sel]")
        self.assertEqual(text, "[[sel]Yes, delete everything[[/sel] [[bg]a[[/bg] [[err]b[[/err] [[REDACTED] [[/sel]")
        real = self.screen("\x1b[7m[sel]x[/sel]\x1b[0m")
        self.assertEqual(real, "[sel][[sel]x[[/sel][/sel]")
        self.assertEqual(self.screen("[[sel]"), "[[[sel]")          # an already doubled one is doubled again: a tag is a single [
        self.assertEqual(self.screen("[0] [ -f x ] [sel [seL] [x]"), "[0] [ -f x ] [sel [seL] [x]")     # other brackets are left alone
        self.assertEqual(mod.to_marked("[sel]x"), "[[sel]x")

    def test_the_underline_colour_is_not_read_as_reverse_video(self):
        # tmux writes 58;5;7 after the underline; 7 is reverse video if it is read as an SGR code
        self.assertEqual(mod.to_marked("\x1b[4m\x1b[58;5;7mUNDER\x1b[0m"), "UNDER")
        self.assertEqual(mod.to_marked("\x1b[4;58;2;255;0;0mU\x1b[0m"), "U")
        self.assertEqual(mod.to_marked("\x1b[58:2::255:0:0mU\x1b[0m"), "U")
        self.assertEqual(mod.to_marked("\x1b[58;5;7;7mU\x1b[0m"), "[sel]U[/sel]")          # a 7 after the colour is a real one
        # the colon forms of the foreground colour, with and without the empty colour-space id
        self.assertEqual(mod.to_marked("\x1b[38:2::255:0:0mR\x1b[0m \x1b[38:2:255:0:0mR\x1b[0m \x1b[38;2;255;0;0mR"), "[err]R[/err] [err]R[/err] [err]R[/err]")


class TestSendLimits(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "sh")
        self.ft.window("@2", 1, "agent", **claude_pane())
        self.ft.save()

    def typed(self, pane):
        return self.ft.pane(pane)["typed"]

    def test_a_long_text_goes_in_small_words_and_is_typed_whole(self):
        d = self.ft.driver()
        text = "echo " + "é" * 2600 + "\n" + "a" * 3000          # a few pieces: the rule is the size of a piece, not the number of them
        d.send_body("@1", {"run": text})
        calls = [a for _, a in self.ft.sent() if a[0] == "-l"]
        self.assertGreater(len(calls), 4)
        self.assertLessEqual(max(len(a[-1].encode()) for a in calls), 4096)           # far below the 16 KB of tmux and the 128 KB of an argv word
        self.assertEqual("".join(self.typed("%1")[:-1]), text)
        self.assertEqual(self.typed("%1")[-1], "<Enter>")

    def test_a_semicolon_at_the_end_of_a_word_is_typed_as_a_key_not_taken_for_the_end_of_the_command(self):
        # tmux drops a trailing `;` of a word, and turns a trailing `\\;` into `;`
        d = self.ft.driver()
        done = 0
        for text in ("echo SEMI;", "echo B ;", "echo A\\;", ";", ";;;", "a;b;"):
            d.send_body("@1", {"input": text})
            self.assertEqual("".join(self.typed("%1")[done:]), text, text)
            done = len(self.typed("%1"))
        for _, a in self.ft.sent():
            if a[0] == "-l":
                self.assertFalse(a[-1].endswith(";"), a)
        # also where a long text is cut: no word ends with ;
        text = "x" * (mod.CHUNK - 1) + ";" + "y" * 10
        d.send_body("@1", {"input": text})
        self.assertEqual("".join(self.typed("%1")[done:]), text)
        for _, a in self.ft.sent()[-5:]:
            if a[0] == "-l":
                self.assertFalse(a[-1].endswith(";"), a[-1][-5:])

    def test_too_many_steps_are_refused_before_anything_is_typed(self):
        d = self.ft.driver()
        with mock.patch.dict(d.send_body.__globals__, {"MAX_STEPS": 6}):      # the real limit (100) costs a tmux process per step (the driver has its own copy of the module)
            code, msg = self.code(d.send_body, "@1", {"input": "{Down}" * 7})
            self.assertEqual(code, "bad_body")
            self.assertIn("several messages", msg)
            self.assertEqual(self.ft.sent(), [])
            d.send_body("@1", {"input": "{Down}" * 6})
            self.assertEqual(len(self.typed("%1")), 6)

    def test_a_lone_surrogate_is_a_bad_body(self):
        d = self.ft.driver()
        self.assertEqual(self.code(d.send_body, "@1", {"run": "a\ud800b"})[0], "bad_body")
        self.assertEqual(self.ft.sent(), [])

    def test_every_submitted_text_is_checked_for_slash_and_bang_not_only_the_first(self):
        d = self.ft.driver()
        for body in ("hi{Enter}/exit{Enter}", "hi{Enter}!rm -rf x{Enter}", "a{Enter}b{Down}/c{Enter}"):
            self.assertEqual(self.code(d.send_body, "@2", {"input": body, "queue": True})[0], "slash_refused", body)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("@2", {"input": "/ok{Enter}", "slash": True})                 # still allowed, explicitly
        self.assertEqual(self.typed("%2"), ["/ok", "<Enter>"])

    def test_a_text_that_is_not_submitted_may_start_with_a_slash(self):
        d = self.ft.driver()
        d.send_body("@2", {"input": "hi{Enter}x{Down}/y"})            # /y is typed and not submitted
        self.assertEqual(self.typed("%2")[-3:], ["x", "<Down>", "/y"])

    def test_two_submits_to_an_agent_need_queue_because_it_is_busy_after_the_first(self):
        d = self.ft.driver()
        code, msg = self.code(d.send_body, "@2", {"input": "one{Enter}two{Enter}"})
        self.assertEqual(code, "busy_tab")
        self.assertIn("queue", msg)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("@1", {"input": "one{Enter}two{Enter}"})            # a shell: no agent, no rule


class TestHostileWindowText(Base):
    """Names, paths and commands are chosen by programs: whatever they hold, the other fields stay where they are."""

    def test_a_window_name_with_the_separator_does_not_hide_the_tab(self):
        self.ft.window("@1", 0, "bash")
        self.ft.window("@2", 1, "a" + mod.SEP + "b")
        self.ft.window("@3", 2, "x")
        d = self.ft.save().driver()
        tabs = d.list_tabs()
        self.assertEqual([(t["tab"], t["name"]) for t in tabs], [("@1", "bash"), ("@2", "a" + mod.SEP + "b"), ("@3", "x")])
        self.assertEqual(d.resolve("@2").name, "a" + mod.SEP + "b")
        self.assertEqual(d.resolve("1:a" + mod.SEP + "b").id, "@2")

    def test_a_path_or_a_command_with_the_separator_is_kept_whole(self):
        self.ft.window("@1", 0, "w", cwd="/tmp/a" + mod.SEP + "b" + mod.SEP, cmd="c" + mod.SEP + "d")
        d = self.ft.save().driver()
        t = d.list_tabs()[0]
        self.assertEqual((t["dir"], t["cmd"], t["pane"], t["name"]), ("/tmp/a" + mod.SEP + "b" + mod.SEP, "c" + mod.SEP + "d", "%1", "w"))

    def test_a_path_with_a_newline_cannot_forge_the_row_of_another_pane(self):
        self.ft.window("@1", 0, "one", cwd="/x\n%2" + mod.SEP + "/forged", cmd="sh")
        self.ft.window("@2", 1, "two", cwd="/real", cmd="vim")
        d = self.ft.save().driver()
        tabs = d.list_tabs()
        self.assertEqual([t["name"] for t in tabs], ["one", "two"])       # the tabs are still there
        self.assertNotIn("/forged", [t["dir"] for t in tabs])
        self.assertNotIn("/forged", repr(tabs))


class TestErrors(Base):
    def test_a_tab_closed_between_the_list_and_the_send_is_no_such_tab(self):
        self.ft.window("@1", 0, "gone")
        self.ft.state["fail"] = {"send-keys": "can't find pane: %1"}
        d = self.ft.save().driver()
        self.assertEqual([t["tab"] for t in d.list_tabs()], ["@1"])
        self.assertEqual(self.code(d.send_body, "@1", {"run": "x"})[0], "no_such_tab")
        self.ft.load()
        self.ft.state["fail"] = {"capture-pane": "can't find pane: %1"}
        self.ft.save()
        self.assertEqual(self.code(d.screen, "@1", None)[0], "no_such_tab")

    def test_no_session_and_no_server(self):
        self.ft.window("@1", 0, "x")
        d = self.ft.save().driver(session="other")
        self.assertEqual(self.code(d.list_tabs)[0], "no_session")
        self.ft.load()
        self.ft.state["fail"] = {"list-panes": "no server running on /tmp/tmux-1000/default"}
        self.ft.save()
        self.assertEqual(self.code(self.ft.driver().list_tabs)[0], "no_session")

    def test_tmux_missing(self):
        d = self.ft.driver()
        d.binary = "/nonexistent/tmux"
        self.assertEqual(self.code(d.list_tabs)[0], "no_tmux")

    def test_other_failures_are_tmux_error_with_the_message(self):
        self.ft.window("@1", 0, "x")
        self.ft.state["fail"] = {"list-panes": "something odd"}
        code, msg = self.code(self.ft.save().driver().list_tabs)
        self.assertEqual((code, msg), ("tmux_error", "something odd"))

    def test_every_tmux_call_has_a_timeout(self):
        self.ft.window("@1", 0, "x")
        self.ft.state["sleep"] = {"list-panes": 5}
        d = self.ft.save().driver(timeout=0.4)
        t = time.time()
        self.assertEqual(self.code(d.list_tabs)[0], "timeout")
        self.assertLess(time.time() - t, 3)

    def test_tmux_is_called_with_the_socket_and_without_TMUX(self):
        self.ft.window("@1", 0, "x")
        self.ft.state["env_check"] = 1
        self.ft.save()
        os.environ["TMUX"] = "/tmp/master-socket,1,0"
        self.addCleanup(os.environ.pop, "TMUX", None)
        self.ft.driver(socket="spike").list_tabs()
        self.ft.load()
        self.assertEqual(self.ft.state["socket_seen"], "spike")
        self.assertIsNone(self.ft.state["env_seen"]["TMUX"])

    def test_defaults_come_from_the_environment(self):
        names = ("SB_TABS_SESSION", "SB_TABS_SOCKET", "SB_TABS_BIN", "SB_RUN_DIR")
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in names])
        os.environ.update(SB_TABS_SESSION="s2", SB_TABS_SOCKET="sock2", SB_TABS_BIN="/x/tmux", SB_RUN_DIR="/x/run")
        d = mod.Tabs()
        self.assertEqual((d.session, d.socket, d.binary, d.run_dir), ("s2", "sock2", "/x/tmux", "/x/run"))
        for k in names:
            os.environ.pop(k)
        d = mod.Tabs()
        self.assertEqual((d.session, d.socket, d.binary, d.run_dir, d.pause), ("main", None, "tmux", "/tmp/swarmbox", 0.15))


class TestAgentState(unittest.TestCase):
    def rows(self, name):
        with open(os.path.join(ROOT, "dev", "spikes", "enter", "screens", name), encoding="utf-8") as f:
            return [x.rstrip() for x in f.read().split("\n")]

    def test_the_real_screens_of_the_spike(self):
        cases = {"dialog-permission.txt": "dialog", "dialog-bypass.txt": "dialog", "dialog-folder-trust.txt": "dialog",
                 "dialog-managed-settings.txt": "dialog", "busy-streaming.txt": "busy", "busy-with-queued-message.txt": "busy",
                 "idle-after-answer.txt": "idle", "idle-manual-mode.txt": "idle", "idle-bypass.txt": "idle",
                 "idle-with-typed-multiline-text.txt": "idle", "failed-burst-long-newline-in-box.txt": "unknown"}
        for name, want in cases.items():
            self.assertEqual(mod.agent_state(self.rows(name), "claude"), (True, want), name)

    def test_the_input_box_text(self):
        rows = self.rows("idle-with-typed-multiline-text.txt")
        box = mod.input_box(rows)
        self.assertIn("multi", box)
        self.assertEqual(mod.input_box(self.rows("idle-bypass.txt")), 'Try "create a util logging.py that..."')   # a ghost suggestion: text alone cannot tell
        self.assertIsNone(mod.input_box(self.rows("dialog-permission.txt")))
        self.assertIn("PONG-burst-1", mod.input_box(self.rows("failed-burst-long-newline-in-box.txt"), lenient=True))   # the top rule scrolled off

    def test_a_plain_shell_is_no_agent(self):
        self.assertEqual(mod.agent_state(["user@box:~$ ls", "a b c", "user@box:~$ "], "bash"), (False, "unknown"))
        self.assertEqual(mod.agent_state(["Do you want to continue? [Y/n]"], "apt"), (False, "unknown"))
        self.assertEqual(mod.agent_state(["booting"], "claude"), (True, "unknown"))

    def test_busy_in_a_narrow_pane_where_the_footer_is_cut(self):
        """Real footers of Claude Code 2.1 in panes of 37, 45 and 52 columns while it worked, and the same panes idle (captured in Podman, tmux 3.7c). The words
        `esc to interrupt` are not whole on the screen there, so a phone held sideways (about 60 columns) looked idle while Claude was busy and swarmbox-tabs
        typed into it. The idle footers have no `·` after the hint."""
        def screen(w, footer):
            return ["  history of lighthouses", "", "─" * w, "❯ ", "─" * w, footer]
        busy = {37: "  ⏵⏵ bypass permissions on  · esc …", 45: "  ⏵⏵ bypass permissions on (shift+tab to  ·",
                52: "  ⏵⏵ bypass permissions on (shift+tab to cycle) ·", 62: "  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to in…",
                50: "  ⏵⏵ bypass permissions on (shift+tab to cycle) · e", 80: "  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt"}
        idle = {37: "  ⏵⏵ bypass permissions on", 52: "  ⏵⏵ bypass permissions on (shift+tab to cycle)", 62: "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
                80: "  ⏵⏵ bypass permissions on (shift+tab to cycle)", 29: "  ⏵⏵ bypass permissions on"}
        for w, footer in busy.items():
            self.assertEqual(mod.agent_state(screen(w, footer), "claude"), (True, "busy"), footer)
        for w, footer in idle.items():
            self.assertEqual(mod.agent_state(screen(w, footer), "claude"), (True, "idle"), footer)
        for footer in ("  7:19 PM · 1 shell still running", "  ◐ medium · /effort", "  ⏵⏵ auto mode on (shift+tab to cycle) · ctrl+t to hide tasks", "  ? for shortcuts"):
            self.assertEqual(mod.agent_state(screen(40, footer), "claude"), (True, "idle"), footer)

    def test_an_old_answer_that_says_do_you_want_to_is_no_dialog(self):
        rows = ["● Do you want to see more?", ""] + ["x"] * 20 + ["─" * 40, "❯ ", "─" * 40, "  auto mode on"]
        self.assertEqual(mod.agent_state(rows, "claude"), (True, "idle"))


class TestRedactionKeepsWhatItMustAndLeavesText(Base):
    """The filter of swarmbox-tabs is the only one of the box (it moved here from the voice addon, whose tests were ported:
    tests/fast/test_tabs_redact_dos.py has the linear-time and behaviour tests)."""

    def test_known_secret_shapes(self):
        corpus = {"token=abc123def": "abc123def", "curl --token 'x y' https://u:pw@host/": "pw@", "Authorization: Bearer abcdefgh12345": "abcdefgh12345",
                  KEY: KEY, "ghp_" + "A" * 24: "A" * 24, "-----BEGIN PRIVATE KEY-----\nxx\n-----END PRIVATE KEY-----": "xx",
                  "ssh -u admin:pw box": "admin:pw", "eyJabcdefgh.eyJabcdefgh.abcdefghij": "abcdefghij"}
        for text, secret in corpus.items():
            with self.subTest(text[:30]):
                out = mod.redact(text)
                self.assertNotIn(secret, out)
                self.assertIn(mod.REDACTED, out)

    def test_tabs_does_not_import_an_addon(self):
        with open(os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")) as f:
            src = f.read()
        for name in ("swarmbox_voice", "swarmbox_sysop"):
            self.assertNotIn("import " + name, src)
            self.assertNotIn("from " + name, src)


class TestApi(Base):
    """the keyword form of the library (send_body, with a dict, is what the tests above use)"""

    def test_send_keywords_and_the_result(self):
        self.ft.window("@1", 0, "sh")
        self.ft.window("@2", 1, "agent", **claude_pane("busy"))
        d = self.ft.save().driver()
        self.assertEqual(d.send("@1", run="ls"), {"ok": True, "tab": "@1", "pane": "%1", "submitted": True})
        self.assertEqual(d.send("@1", input="ab")["submitted"], False)
        self.assertEqual(self.ft.pane("%1")["typed"], ["ls", "<Enter>", "ab"])
        self.assertEqual(self.code(lambda: d.send("@2", run="next"))[0], "busy_tab")
        self.assertEqual(d.send("@2", run="next", queue=True)["tab"], "@2")
        self.assertEqual(self.code(lambda: d.send("@1"))[0], "bad_body")
        self.assertEqual(self.code(lambda: d.send("@1", run="a", input="b"))[0], "bad_body")

    def test_active(self):
        self.ft.window("@1", 0, "a")
        self.ft.window("@2", 1, "b")
        self.ft.client("@2", 50)
        d = self.ft.save().driver()
        self.assertEqual(d.active()["tab"], "@2")
        self.assertEqual(self.code(self.ft.driver(session="other").active)[0], "no_session")


class TestLock(Base):
    """a lock per tab (flock in the run folder): two sends to one tab never interleave, whoever sends"""

    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "one")
        self.ft.window("@2", 1, "two")
        self.ft.save()

    def test_the_lock_is_a_file_in_the_run_folder_and_is_kept_between_sends(self):
        self.ft.driver().send("@1", run="x")
        self.assertEqual(sorted(os.listdir(os.path.join(self.ft.dir, "tabs"))), ["tab-1.lock"])
        self.assertEqual(oct(os.stat(os.path.join(self.ft.dir, "tabs", "tab-1.lock")).st_mode & 0o777), "0o600")
        self.ft.driver().send("@2", run="y")
        self.assertEqual(sorted(os.listdir(os.path.join(self.ft.dir, "tabs"))), ["tab-1.lock", "tab-2.lock"])

    def test_a_held_lock_makes_the_send_wait_and_then_time_out_with_nothing_typed(self):
        import fcntl
        d = self.ft.driver(lock_timeout=0.4)
        d.send("@1", run="warm")
        self.ft.load()
        before = len(self.ft.sent())
        fd = os.open(os.path.join(self.ft.dir, "tabs", "tab-1.lock"), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t = time.time()
            code, msg = self.code(lambda: d.send("@1", run="late"))
            self.assertEqual(code, "timeout")
            self.assertGreaterEqual(time.time() - t, 0.4)
            self.assertIn("nothing was typed", msg)
            d.send("@2", run="other tab is free")        # another tab is not blocked
        finally:
            os.close(fd)
        self.assertNotIn("late", self.ft.pane("%1")["typed"])
        self.assertEqual(len(self.ft.sent()), before + 2)
        d.send("@1", run="after")                         # released: it works again
        self.assertEqual(self.ft.pane("%1")["typed"][-2:], ["after", "<Enter>"])

    def test_two_processes_sending_to_one_tab_never_interleave(self):
        import subprocess
        import tabs_support
        procs = []
        for i in range(4):
            procs.append(subprocess.Popen([sys.executable, "-S", tabs_support.TABS_PATH, "send", "@1", "--run", "msg%d one two three" % i],
                                          env=self.ft.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, (out, err))
        typed = self.ft.pane("%1")["typed"]
        self.assertEqual(len(typed), 8)
        for i in range(0, 8, 2):
            self.assertTrue(typed[i].startswith("msg") and typed[i + 1] == "<Enter>", typed)

    def test_a_run_folder_that_cannot_be_used_is_lock_error_and_nothing_is_typed(self):
        open(os.path.join(self.ft.dir, "tabs"), "w").close()         # a file where the folder should be
        d = self.ft.driver()
        self.assertEqual(self.code(lambda: d.send("@1", run="x"))[0], "lock_error")
        self.assertEqual(self.ft.sent(), [])


class TestCommand(Base):
    """the command line: JSON on stdout, the exit codes, stdin, the environment"""

    def setUp(self):
        Base.setUp(self)
        self.ft.window("@1", 0, "sh", screen="hello \x1b[7mworld\x1b[27m  token=abc12345\nsecond")
        self.ft.window("@2", 1, "agent", **claude_pane())
        self.ft.client("@2", 10)
        self.ft.save()

    def test_list_active_screen(self):
        rc, out, err = self.ft.cli("list")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual([t["tab"] for t in out], ["@1", "@2"])
        self.assertEqual([t["active"] for t in out], [False, True])
        rc, out, _ = self.ft.cli("active")
        self.assertEqual((rc, out["tab"], out["label"]), (0, "@2", "1:agent"))
        rc, out, _ = self.ft.cli("screen", "sh")
        self.assertEqual((rc, out["text"]), (0, "hello [sel]world[/sel]  token=[REDACTED]\nsecond"))
        rc, out, _ = self.ft.cli("screen", "@1", "--lines", "1")
        self.assertEqual((rc, out["text"], out["lines"]), (0, "second", 1))

    def test_send_run_and_input_and_queue_and_slash(self):
        rc, out, _ = self.ft.cli("send", "@1", "--run", "echo hi")
        self.assertEqual((rc, out), (0, {"ok": True, "tab": "@1", "pane": "%1", "submitted": True}))
        rc, out, _ = self.ft.cli("send", "1:agent", "--input", "ab{Esc}")
        self.assertEqual((rc, out["submitted"]), (0, False))
        self.assertEqual(self.ft.pane("%1")["typed"], ["echo hi", "<Enter>"])
        self.assertEqual(self.ft.pane("%2")["typed"], ["ab", "<Escape>"])
        rc, out, _ = self.ft.cli("send", "agent", "--run", "/help")
        self.assertEqual((rc, out["err"]), (1, "slash_refused"))
        rc, out, _ = self.ft.cli("send", "agent", "--run", "/clear", "--slash")
        self.assertEqual(rc, 0)
        self.ft.load()
        self.ft.state["windows"][1]["panes"][0]["claude"]["mode"] = "busy"
        self.ft.save()
        rc, out, _ = self.ft.cli("send", "agent", "--run", "next")
        self.assertEqual((rc, out["err"]), (1, "busy_tab"))
        rc, out, _ = self.ft.cli("send", "agent", "--run", "next", "--queue")
        self.assertEqual(rc, 0)

    def test_the_text_may_come_from_stdin(self):
        rc, out, _ = self.ft.cli("send", "@1", "--run", "-", stdin=b"line one\nline two\n")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ft.pane("%1")["typed"], ["line one\nline two", "<Enter>"])
        rc, out, _ = self.ft.cli("send", "@1", "--input", "-", stdin=b"{C-c}")
        self.assertEqual(rc, 0)
        self.assertEqual(self.ft.pane("%1")["typed"][-1], "<C-c>")
        rc, out, _ = self.ft.cli("send", "@1", "--run", "-", stdin=b"\xff\xfe")
        self.assertEqual((rc, out["err"]), (2, "bad_body"))
        rc, out, _ = self.ft.cli("send", "@1", "--run", "-", stdin=b"a\x00b")
        self.assertEqual((rc, out["err"]), (2, "bad_body"))
        rc, out, _ = self.ft.cli("send", "@1", "--run", "-", stdin=b"")
        self.assertEqual((rc, out["err"]), (2, "bad_body"))

    def test_errors_are_json_on_stdout_with_the_exit_codes(self):
        cases = [(("screen", "@9"), 1, "no_such_tab"), (("send", "@9", "--run", "x"), 1, "no_such_tab"), (("list", "x"), 2, "usage"),
                 (("nope",), 2, "usage"), ((), 2, "usage"), (("screen",), 2, "usage"), (("screen", "@1", "--lines", "x"), 2, "usage"),
                 (("screen", "@1", "--lines", "0"), 2, "usage"), (("send", "@1"), 2, "usage"), (("send", "@1", "--run", "a", "--input", "b"), 2, "usage"),
                 (("send", "@1", "--run"), 2, "usage"), (("send", "@1", "--bogus", "a"), 2, "usage")]
        for args, rc, code in cases:
            with self.subTest(args=args):
                got, out, _ = self.ft.cli(*args)
                self.assertEqual((got, out["err"]), (rc, code))
                self.assertTrue(out["msg"])
        self.assertEqual(self.ft.sent(), [])
        ft2 = self.ft
        ft2.window("@3", 2, "sh")
        ft2.save()
        rc, out, _ = ft2.cli("screen", "sh")
        self.assertEqual((rc, out["err"]), (1, "ambiguous_tab"))

    def test_no_tmux_and_no_session_are_4_and_a_timeout_is_5(self):
        rc, out, _ = self.ft.cli("list", SB_TABS_BIN="/nonexistent/tmux")
        self.assertEqual((rc, out["err"]), (4, "no_tmux"))
        rc, out, _ = self.ft.cli("list", SB_TABS_SESSION="other")
        self.assertEqual((rc, out["err"]), (4, "no_session"))

    def test_every_error_code_has_its_exit_code(self):
        """the exit codes of the documented contract (usage, bad_body 2; no_tmux, no_session 4; timeout 5; the others 1), in process: the real 5 s timeout of a tmux call
        is tested at the driver (test_every_tmux_call_has_a_timeout)"""
        want = {"usage": 2, "bad_body": 2, "no_tmux": 4, "no_session": 4, "timeout": 5, "no_such_tab": 1, "ambiguous_tab": 1, "busy_tab": 1, "tmux_error": 1}
        for code, rc in want.items():
            with self.subTest(code=code), mock.patch.object(mod, "run", side_effect=mod.TabsError(code, "m")), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.main(["list"]), rc)
                self.assertEqual(json.loads(out.getvalue()), {"err": code, "msg": "m"})

    def test_the_environment_chooses_the_socket_and_TMUX_is_dropped(self):
        self.ft.load()
        self.ft.state["env_check"] = 1
        self.ft.save()
        rc, _, _ = self.ft.cli("list", SB_TABS_SOCKET="spike", TMUX="/tmp/master,1,0", TMUX_TMPDIR="/x/tmp")
        self.assertEqual(rc, 0)
        self.ft.load()
        self.assertEqual(self.ft.state["socket_seen"], "spike")
        self.assertEqual(self.ft.state["env_seen"], {"TMUX": None, "TMUX_TMPDIR": "/x/tmp"})

    def test_help(self):
        import subprocess
        import tabs_support
        r = subprocess.run([sys.executable, "-S", tabs_support.TABS_PATH, "--help"], capture_output=True, env=self.ft.env())
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"swarmbox-tabs list", r.stdout)


class TestImage(unittest.TestCase):
    def test_the_dockerfile_installs_the_command_and_no_driver_module(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("COPY container/scripts/swarmbox-tabs.py /usr/local/bin/swarmbox-tabs\n", d)
        self.assertRegex(d, r"chmod 755 [^\n]*(\\\n[^\n]*)*/usr/local/bin/swarmbox-tabs ")
        self.assertNotIn("swarmbox-bus-tmux", d)

    def test_the_bus_knows_nothing_of_tmux_or_tabs(self):
        with open(os.path.join(ROOT, "container", "scripts", "swarmbox-bus.py")) as f:
            src = f.read()
        code = src.split('"""', 2)[2]
        for word in ("tmux", "tab/", "Driver", "driver", "no_screen"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
