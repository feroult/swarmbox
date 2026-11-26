"""swarmbox-tabs (container/scripts/swarmbox-tabs.py) against a FAKE herdr-core hc (tests/support/tabs_support.py): the tab fields, the active tab,
addressing, the hidden sysop terminals, the screen pipeline (markers, last N lines, clip, secrets), the typing rules (pause, separate Enter, dialog,
busy, queue, slash, verify, braces), errors, timeouts, the lock between sends, open/focus/close, and the command line (JSON, exit codes, stdin,
the framed text of `hc connect`). No herdr-core, network or model. Run with: python3 tests/fast/test_tabs.py"""
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
from tabs_support import FakeHc, claude_term, load_module  # noqa: E402
from helpers import ROOT  # noqa: E402

mod = load_module()
KEY = "sk-" + "a1B2c3D4e5F6g7H8i9J0"


class Base(unittest.TestCase):
    def setUp(self):
        self.ft = FakeHc()
        self.addCleanup(self.ft.close)

    def code(self, fn, *a):
        with self.assertRaises(Exception) as cm:
            fn(*a)
        return cm.exception.code, cm.exception.message


class TestTabs(Base):
    def three(self):
        self.ft.term("t1", "idle")
        self.ft.term("t2", "build", cwd=os.path.expanduser("~") + "/proj", foreground={"name": "/usr/bin/make"})
        self.ft.term("t3", "claude", **claude_term())
        return self.ft

    def test_fields_in_the_order_the_terminals_were_created(self):
        ft = self.three()
        ft.state["terminals"].reverse()
        tabs = ft.save().active("t3").driver().list_tabs()
        self.assertEqual([t["tab"] for t in tabs], ["t1", "t2", "t3"])
        self.assertEqual([t["active"] for t in tabs], [False, False, True])
        t = tabs[1]
        self.assertEqual((t["label"], t["index"], t["name"], t["dir"], t["cmd"], t["pane"], t["panes"]), ("2:build", 2, "build", "~/proj", "make", "t2", ["t2"]))
        self.assertEqual(tabs[2]["cmd"], "claude")
        self.assertNotIn("status", t)

    def test_the_active_tab_is_the_marker_or_the_first_tab(self):
        ft = self.three().save()
        self.assertEqual([t["tab"] for t in ft.driver().list_tabs() if t["active"]], ["t1"], "no marker: the first tab")
        ft.active("t2")
        self.assertEqual(ft.driver().active()["tab"], "t2")
        ft.active("t9")                     # a tab that is gone
        self.assertEqual(ft.driver().active()["tab"], "t1")

    def test_the_status_a_program_reported_is_listed_cut(self):
        ft = self.three()
        ft.state["terminals"][2].update(reported=True, status={"state": "working", "progress": 40.7, "msg": "m" * 300, "app": "a" * 50})
        st = ft.save().driver().list_tabs()[2]["status"]
        self.assertEqual(st, {"state": "working", "progress": 40, "msg": "m" * 160, "app": "a" * 32})

    def test_sysop_terminals_are_hidden_and_never_a_target_and_never_active(self):
        ft = self.three()
        ft.term("t4", "sysop", labels={"swarmbox.role": "sysop"})
        d = ft.save().active("t4").driver()
        tabs = d.list_tabs()
        self.assertEqual([t["tab"] for t in tabs], ["t1", "t2", "t3"])
        self.assertEqual(sum(t["active"] for t in tabs), 1)
        self.assertEqual(self.code(d.resolve, "t4")[0], "no_such_tab")
        self.assertEqual(self.code(d.send_body, "sysop", {"run": "x"})[0], "no_such_tab")

    def test_a_finished_terminal_is_no_tab(self):
        ft = self.three()
        ft.state["terminals"][1]["state"] = "finished"
        self.assertEqual([t["tab"] for t in ft.save().driver().list_tabs()], ["t1", "t3"])

    def test_open_tab_runs_a_kept_terminal_with_the_allowlisted_agent_and_makes_it_active(self):
        ft = self.three().save()
        d = ft.driver()
        res = d.open_tab(name="My API!", cwd=ft.dir, agent="claude")
        self.assertEqual(res, {"ok": True, "tab": "t4", "name": "my-api", "agent": "claude"})
        _, a = ft.calls("run")[-1]
        self.assertEqual(a, ["run", "--bg", "--keep", "--no-parent", "--json", "--name", "my-api", "--cwd", ft.dir, "--label", "swarmbox.agent=claude", "--", "/bin/bash", "-lic",
                             "SWARMBOX_WORKTREE_GUARD=0 claude; exec /bin/bash -l"], "an interactive shell, so the function of the agent runs")
        self.assertEqual(d.active()["tab"], "t4")
        self.assertEqual(d.open_tab()["tab"], "t5")
        self.assertEqual(ft.calls("run")[-1][1][-3:], ["--", "bash", "-l"], "a shell: a login bash")
        self.assertEqual(self.code(d.open_tab, None, None, "vim")[0], "usage")
        self.assertEqual(self.code(d.open_tab, None, "/nonexistent/dir", None)[0], "bad_body")

    def test_focus_moves_the_marker_and_close_kills_and_removes(self):
        ft = self.three().save()
        d = ft.driver()
        self.assertEqual(d.focus_tab("build")["tab"], "t2")
        self.assertEqual(d.active()["tab"], "t2")
        self.assertEqual(d.close_tab("3")["tab"], "t3")
        self.assertEqual([a for _, a in ft.calls() if a[:1] in (["kill"], ["rm"])], [["kill", "t3"], ["rm", "t3"]])
        self.assertEqual([t["tab"] for t in d.list_tabs()], ["t1", "t2"])
        self.assertEqual(self.code(d.close_tab, "t3")[0], "no_such_tab")

    def test_the_command_line_has_open_focus_and_close(self):
        ft = self.three().save()
        d = ft.driver()
        self.assertEqual(mod.run(["focus", "t1"], tabs=d)["tab"], "t1")
        self.assertEqual(mod.run(["open", "--agent", "shell", "--name", "x"], tabs=d)["tab"], "t4")
        self.assertEqual(mod.run(["close", "t4"], tabs=d)["tab"], "t4")
        for bad in (["focus"], ["close", "t1", "t2"], ["open", "extra"], ["open", "--agent", "vim"]):
            self.assertEqual(self.code(mod.run, bad, d)[0], "usage")

    def test_addresses_id_label_index_name(self):
        d = self.three().save().driver()
        for a in ("t2", "2:build", "2", "build"):
            self.assertEqual(d.resolve(a).id, "t2", a)
        self.assertEqual(d.resolve("1:idle").id, "t1")

    def test_duplicate_names_are_an_error_that_lists_the_candidates(self):
        ft = self.three()
        ft.term("t4", "build")
        d = ft.save().driver()
        code, msg = self.code(d.resolve, "build")
        self.assertEqual(code, "ambiguous_tab")
        self.assertIn("2:build (t2)", msg)
        self.assertIn("4:build (t4)", msg)
        self.assertEqual(d.resolve("t4").index, 4)                   # the address and the label still work
        self.assertEqual(d.resolve("4:build").id, "t4")
        self.assertEqual(self.code(d.screen, "build", None)[0], "ambiguous_tab")
        self.assertEqual(self.code(d.send_body, "build", {"run": "x"})[0], "ambiguous_tab")
        self.assertEqual(self.ft.sent(), [])

    def test_a_stale_address_is_no_such_tab_with_the_list(self):
        d = self.three().save().driver()
        code, msg = self.code(d.resolve, "t9")
        self.assertEqual(code, "no_such_tab")
        self.assertIn("1:idle (t1)", msg)

    def test_names_paths_and_commands_are_kept_whole(self):
        """they are text a program chooses; JSON carries them, so nothing in them can move another field"""
        odd = 'a:b "c"\n2:x\x07'
        self.ft.term("t1", odd, cwd="/tmp/a\nb", foreground={"name": "c d"})
        self.ft.term("t2", "two")
        d = self.ft.save().driver()
        t = d.list_tabs()[0]
        self.assertEqual((t["name"], t["dir"], t["cmd"], t["label"]), (odd, "/tmp/a\nb", "c d", "1:" + odd))
        self.assertEqual(d.resolve("1:" + odd).id, "t1")
        self.assertEqual(d.resolve("two").id, "t2")
        self.assertEqual(self.code(d.resolve, "2:x")[0], "no_such_tab", "a forged label in a name is no label")


class TestScreen(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.term("t1", "t", screen="plain\n\x1b[7m selected \x1b[27m x\n\x1b[48;5;237mhighlighted\x1b[49m\n\x1b[31mfailed\x1b[39m",
                     cols=100, rows=30, history_raw=["old one", "old two"])
        self.d = self.ft.save().driver()

    def set(self, **kw):
        self.ft.load()
        self.ft.state["terminals"][0].update(kw)
        self.ft.save()

    def test_markers_and_size(self):
        s = self.d.screen("t1", None)
        self.assertEqual(s["text"], "plain\n [sel]selected[/sel]  x\n[bg]highlighted[/bg]\n[err]failed[/err]")
        self.assertEqual((s["tab"], s["pane"], s["size"], s["alternate"], s["in_mode"], s["lines"]), ("t1", "t1", [100, 30], False, False, None))

    def test_the_lines_ask_for_history_and_the_last_n_are_kept(self):
        s = self.d.screen("t1", 2)
        self.assertEqual(self.ft.calls("read")[-1][1], ["read", "--json", "--lines", "2", "t1"])
        self.assertEqual((s["text"], s["lines"]), ("[bg]highlighted[/bg]\n[err]failed[/err]", 2))
        self.assertEqual(self.d.screen("t1", 5)["text"].split("\n")[:2], ["old two", "plain"])

    def test_the_secret_is_removed_after_the_markers_and_never_on_raw_escape_text(self):
        # the escape code splits the key: a filter on the raw text would not see it
        self.set(screen="token sk-\x1b[1m" + KEY[3:] + "\x1b[0m end\nAPI_TOKEN=\x1b[7mhunter2\x1b[27m\nok \x1b[7mfine\x1b[27m")
        text = self.d.screen("t1", None)["text"]
        self.assertNotIn(KEY[3:], text)
        self.assertNotIn("hunter2", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("[sel]fine[/sel]", text)

    def test_a_private_key_block_is_removed_even_with_markers_inside(self):
        self.set(screen="-----BEGIN RSA PRIVATE KEY-----\n\x1b[7mMIIEowIBAAKCAQEA\x1b[27m\n-----END RSA PRIVATE KEY-----\nafter")
        self.assertEqual(self.d.screen("t1", None)["text"], "[REDACTED]\nafter")

    def test_a_huge_line_is_clipped_and_the_filter_is_fast(self):
        self.set(screen="-" * 100000 + "\nnext")
        t = time.time()
        text = self.d.screen("t1", None)["text"]
        self.assertLess(time.time() - t, 2.0)
        first = text.split("\n")[0]
        self.assertTrue(first.endswith("[... 99000 more characters]"), first[-40:])
        self.assertEqual(text.split("\n")[1], "next")

    def test_a_full_screen_program_offers_no_lines(self):
        self.set(alt=True)
        s = self.d.screen("t1", 3)
        self.assertTrue(s["alternate"])
        self.assertIsNone(s["lines"])
        self.assertEqual(len(s["text"].split("\n")), 4)             # the visible screen, not the last 3 lines

    def test_tabs_keeps_no_cache(self):
        self.d.screen("t1", None)
        self.set(screen="changed")
        self.assertEqual(self.d.screen("t1", None)["text"], "changed")


class TestSend(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.term("t1", "sh")
        self.ft.term("t2", "agent", **claude_term())
        self.ft.save()

    def typed(self, addr):
        return self.ft.typed(addr)

    def add(self, addr, name, **kw):
        self.ft.load()
        self.ft.term(addr, name, **kw)
        self.ft.save()

    def test_run_is_text_then_a_separate_enter_after_the_pause(self):
        d = self.ft.driver(pause=0.15)
        d.send_body("t1", {"run": "ls -la"})
        sent = self.ft.sent()
        self.assertEqual([e[1:] for e in sent], [("t1", "text", "ls -la"), ("t1", "key", "enter")])
        self.assertGreaterEqual(sent[1][0] - sent[0][0], 0.15)
        self.assertEqual(self.ft.calls("keys")[-1][1], ["keys", "--json", "t1", "enter"])

    def test_run_is_literal_text_and_braces_in_it_are_not_keys(self):
        d = self.ft.driver()
        d.send_body("t1", {"run": "echo {Esc} ${HOME} {"})
        self.assertEqual(self.typed("t1"), ["echo {Esc} ${HOME} {", "<enter>"])

    def test_input_braces_are_keys_in_the_spelling_of_hc(self):
        d = self.ft.driver()
        d.send_body("t1", {"input": "ab{C-c}{Esc}cd{{x}}{Up}{foo}${HOME}{HOME}{ {\"a\": 1}"})
        self.assertEqual(self.typed("t1"), ["ab", "<ctrl+c>", "<esc>", "cd{x}", "<up>", "{foo}${HOME}{HOME}{ {\"a\": 1}"])
        d.send_body("t1", {"input": "{BTab}{BSpace}{PgUp}{PgDn}{Delete}{Insert}{M-x}{F12}{Space}{Tab}{Home}{End}"})
        self.assertEqual(self.typed("t1")[6:], ["<shift+tab>", "<backspace>", "<pageup>", "<pagedown>", "<delete>", "<insert>", "<alt+x>", "<f12>",
                                                 "<space>", "<tab>", "<home>", "<end>"])
        self.assertEqual(mod.parse_keys("{F12}{F13}{M-x}{M-xy}{c-c}"), [("key", "F12"), ("text", "{F13}"), ("key", "M-x"), ("text", "{M-xy}{c-c}")])
        self.assertEqual(mod.parse_keys("{PgUp}{PgDn}{Delete}{BTab}"), [("key", "PageUp"), ("key", "PageDown"), ("key", "DC"), ("key", "BTab")])

    def test_each_key_is_its_own_call_with_the_pause_between(self):
        d = self.ft.driver(pause=0.1)
        d.send_body("t1", {"input": "{Esc}{Esc}"})
        s = self.ft.sent()
        self.assertEqual([e[3] for e in s], ["esc", "esc"])
        self.assertEqual(len(self.ft.calls("keys")), 2)
        self.assertGreaterEqual(s[1][0] - s[0][0], 0.1)

    def test_multi_line_text_is_one_literal_write(self):
        d = self.ft.driver()
        d.send_body("t1", {"run": "line one\nline two \"q\" 'q' `bt` $(id) é"})
        self.assertEqual(self.typed("t1")[0], "line one\nline two \"q\" 'q' `bt` $(id) é")

    def test_bad_bodies_type_nothing(self):
        d = self.ft.driver()
        for body in ("text", None, 5, [], {}, {"run": 5}, {"run": ""}, {"input": ""}, {"run": "a", "input": "b"}, {"x": "a"}, {"run": "a", "queue": "yes"},
                     {"run": "a", "extra": True}, {"run": "a\x00b"}, {"input": "{{"[:0]}, {"run": "a\ud800b"}):
            self.assertEqual(self.code(d.send_body, "t1", body)[0], "bad_body", repr(body))
        self.assertEqual(self.ft.sent(), [])

    def test_a_dialog_is_refused_and_nothing_is_typed(self):
        self.add("t3", "dlg", **claude_term("dialog"))
        d = self.ft.driver()
        self.assertEqual(self.code(d.send_body, "t3", {"run": "hello"})[0], "dialog_open")
        self.assertEqual(self.code(d.send_body, "t3", {"run": "hello", "queue": True})[0], "dialog_open")      # queueing does not help
        self.assertEqual(self.ft.sent(), [])
        d.send_body("t3", {"input": "1"})                              # an answer is typed: input is not judged
        d.send_body("t3", {"input": "{Enter}"})
        self.assertEqual(self.typed("t3"), ["1", "<enter>"])

    def test_a_busy_agent_is_refused_unless_queue(self):
        self.add("t3", "busy", **claude_term("busy"))
        d = self.ft.driver()
        code, msg = self.code(d.send_body, "t3", {"run": "next"})
        self.assertEqual(code, "busy_tab")
        self.assertIn("queue", msg)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("t3", {"run": "next", "queue": True})
        self.assertEqual(self.typed("t3"), ["next", "<enter>"])
        d.send_body("t3", {"input": "{Esc}"})                         # the interrupt is allowed: it is not a submission
        self.assertEqual(self.ft.t("t3")["claude"]["mode"], "idle")

    def test_the_state_the_program_reports_comes_before_the_screen(self):
        """OSC 7501: a terminal that reports `blocked` is a dialog and `working` is busy, whatever its screen shows"""
        self.add("t3", "osc", reported=True, status={"state": "blocked"}, **claude_term())
        self.add("t4", "osc2", reported=True, status={"state": "working"}, **claude_term())
        d = self.ft.driver()
        self.assertEqual(self.code(d.send_body, "t3", {"run": "x"})[0], "dialog_open")
        self.assertEqual(self.code(d.send_body, "t4", {"run": "x"})[0], "busy_tab")
        self.assertEqual(self.ft.sent(), [])

    def test_slash_and_bang_are_refused_for_an_agent_not_for_a_shell(self):
        d = self.ft.driver()
        for text in ("/help", "!ls"):
            self.assertEqual(self.code(d.send_body, "t2", {"run": text})[0], "slash_refused")
        self.assertEqual(self.ft.sent(), [])
        d.send_body("t1", {"run": "/bin/ls"})                         # a shell: it is a path
        d.send_body("t2", {"run": "/clear", "slash": True})           # explicit opt-in
        self.assertEqual(self.typed("t1"), ["/bin/ls", "<enter>"])
        self.assertEqual(self.typed("t2"), ["/clear", "<enter>"])

    def test_input_text_without_enter_is_raw(self):
        d = self.ft.driver()
        d.send_body("t2", {"input": "/not-judged"})
        self.assertEqual(self.typed("t2"), ["/not-judged"])

    def test_agent_prompt_is_submitted_and_checked(self):
        d = self.ft.driver()
        self.assertIs(d.send_body("t2", {"run": "reply with exactly PONG"})["verified"], True)
        self.assertEqual(self.typed("t2"), ["reply with exactly PONG", "<enter>"])
        c = self.ft.t("t2")["claude"]
        self.assertEqual(c["box"], "")
        self.assertIn("❯ reply with exactly PONG", c["history"])

    def test_a_swallowed_enter_is_pressed_once_more_and_the_text_is_not_typed_again(self):
        self.add("t3", "flaky", **claude_term(swallow=1))
        self.ft.driver(verify_timeout=0.3).send_body("t3", {"run": "a prompt that stays"})
        self.assertEqual(self.typed("t3"), ["a prompt that stays", "<enter>", "<enter>"])

    def test_an_enter_that_never_submits_is_not_submitted(self):
        self.add("t3", "stuck", **claude_term(swallow=99))
        code, msg = self.code(self.ft.driver(verify_timeout=0.3).send_body, "t3", {"run": "x prompt"})
        self.assertEqual(code, "not_submitted")
        self.assertEqual(self.typed("t3"), ["x prompt", "<enter>", "<enter>"])               # two Enters, never more

    def test_a_pasted_text_placeholder_in_the_box_counts_as_not_submitted(self):
        self.add("t3", "paste", **claude_term(swallow=99))
        d = self.ft.driver(verify_timeout=0.2)
        self.assertEqual(self.code(d.send_body, "t3", {"run": "long " * 200})[0], "not_submitted")

    def test_a_queued_message_while_busy_counts_as_submitted(self):
        self.add("t3", "busy", **claude_term("busy"))
        self.ft.driver(verify_timeout=0.3).send_body("t3", {"run": "queued one", "queue": True})
        self.assertEqual(self.typed("t3"), ["queued one", "<enter>"])

    def test_the_agent_is_known_by_its_screen_when_the_command_is_a_shell(self):
        p = claude_term("dialog")
        p["argv"] = ["sh"]                                         # claude started from a shell
        self.add("t3", "viash", **p)
        self.assertEqual(self.code(self.ft.driver().send_body, "t3", {"run": "x"})[0], "dialog_open")

    def test_a_shell_screen_that_says_do_you_want_to_is_no_dialog(self):
        self.ft.load()
        self.ft.state["terminals"][0]["screen"] = "Do you want to continue? [Y/n]"
        self.ft.save()
        self.ft.driver().send_body("t1", {"run": "y"})
        self.assertEqual(self.typed("t1"), ["y", "<enter>"])

    def test_sends_to_one_tab_never_interleave(self):
        d = self.ft.driver(pause=0.05)
        ts = [threading.Thread(target=d.send_body, args=("t1", {"run": "msg%d" % i})) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(20)
        typed = self.typed("t1")
        self.assertEqual(len(typed), 8)
        for i in range(0, 8, 2):
            self.assertTrue(typed[i].startswith("msg") and typed[i + 1] == "<enter>", typed)


class TestSendLimits(Base):
    def setUp(self):
        Base.setUp(self)
        self.ft.term("t1", "sh")
        self.ft.term("t2", "agent", **claude_term())
        self.ft.save()

    def typed(self, addr):
        return self.ft.typed(addr)

    def test_too_many_steps_are_refused_before_anything_is_typed(self):
        d = self.ft.driver()
        with mock.patch.dict(d.send_body.__globals__, {"MAX_STEPS": 6}):      # the real limit (100) costs an hc process per step (the driver has its own copy of the module)
            code, msg = self.code(d.send_body, "t1", {"input": "{Down}" * 7})
            self.assertEqual(code, "bad_body")
            self.assertIn("several messages", msg)
            self.assertEqual(self.ft.sent(), [])
            d.send_body("t1", {"input": "{Down}" * 6})
            self.assertEqual(len(self.typed("t1")), 6)

    def test_every_submitted_text_is_checked_for_slash_and_bang_not_only_the_first(self):
        d = self.ft.driver()
        for body in ("hi{Enter}/exit{Enter}", "hi{Enter}!rm -rf x{Enter}", "a{Enter}b{Down}/c{Enter}"):
            self.assertEqual(self.code(d.send_body, "t2", {"input": body, "queue": True})[0], "slash_refused", body)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("t2", {"input": "/ok{Enter}", "slash": True})                 # still allowed, explicitly
        self.assertEqual(self.typed("t2"), ["/ok", "<enter>"])

    def test_a_text_that_is_not_submitted_may_start_with_a_slash(self):
        d = self.ft.driver()
        d.send_body("t2", {"input": "hi{Enter}x{Down}/y"})            # /y is typed and not submitted
        self.assertEqual(self.typed("t2")[-3:], ["x", "<down>", "/y"])

    def test_two_submits_to_an_agent_need_queue_because_it_is_busy_after_the_first(self):
        d = self.ft.driver()
        code, msg = self.code(d.send_body, "t2", {"input": "one{Enter}two{Enter}"})
        self.assertEqual(code, "busy_tab")
        self.assertIn("queue", msg)
        self.assertEqual(self.ft.sent(), [])
        d.send_body("t1", {"input": "one{Enter}two{Enter}"})            # a shell: no agent, no rule
        self.assertEqual(self.typed("t1"), ["one", "<enter>", "two", "<enter>"])


class TestScreenSecretsAndMarkers(Base):
    """The secrets are found in the plain text of the terminal, whatever the colours, and the markers are written afterwards."""

    def setUp(self):
        Base.setUp(self)
        self.term = self.ft.term("t1", "t")
        self.d = self.ft.save().driver()

    def screen(self, raw, lines=None):
        self.term["screen"] = raw
        self.ft.save()
        return self.d.screen("t1", lines)["text"]

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
        # a terminal writes 58;5;7 after the underline; 7 is reverse video if it is read as an SGR code
        self.assertEqual(mod.to_marked("\x1b[4m\x1b[58;5;7mUNDER\x1b[0m"), "UNDER")
        self.assertEqual(mod.to_marked("\x1b[4;58;2;255;0;0mU\x1b[0m"), "U")
        self.assertEqual(mod.to_marked("\x1b[58:2::255:0:0mU\x1b[0m"), "U")
        self.assertEqual(mod.to_marked("\x1b[58;5;7;7mU\x1b[0m"), "[sel]U[/sel]")          # a 7 after the colour is a real one
        # the colon forms of the foreground colour, with and without the empty colour-space id
        self.assertEqual(mod.to_marked("\x1b[38:2::255:0:0mR\x1b[0m \x1b[38:2:255:0:0mR\x1b[0m \x1b[38;2;255;0;0mR"), "[err]R[/err] [err]R[/err] [err]R[/err]")


class TestErrors(Base):
    def test_a_tab_closed_between_the_list_and_the_send_is_no_such_tab(self):
        self.ft.term("t1", "gone")
        self.ft.state["fail"] = {"keys": {"kind": "not_found", "message": 'no terminal "t1"'}}
        d = self.ft.save().driver()
        self.assertEqual([t["tab"] for t in d.list_tabs()], ["t1"])
        self.assertEqual(self.code(d.send_body, "t1", {"input": "{Enter}"})[0], "no_such_tab")
        self.ft.load()
        self.ft.state["fail"] = {"read": {"kind": "finished", "message": "terminal t1 has finished"}}
        self.ft.save()
        self.assertEqual(self.code(d.screen, "t1", None)[0], "no_such_tab")

    def test_a_server_that_is_not_running_is_no_session(self):
        self.ft.term("t1", "x")
        self.ft.state["down"] = True
        code, msg = self.code(self.ft.save().driver().list_tabs)
        self.assertEqual(code, "no_session")
        self.assertIn("hc server start", msg)

    def test_hc_missing_is_no_backend(self):
        d = self.ft.driver()
        d.backend.binary = "/nonexistent/hc"
        self.assertEqual(self.code(d.list_tabs)[0], "no_backend")

    def test_an_unknown_backend_is_no_backend(self):
        self.assertEqual(self.code(lambda: mod.Tabs(backend="tmux"))[0], "no_backend")
        with mock.patch.dict(os.environ, {"SB_TABS_BACKEND": "screen"}):
            self.assertEqual(self.code(mod.Tabs)[0], "no_backend")

    def test_other_failures_are_backend_error_with_the_message(self):
        self.ft.term("t1", "x")
        self.ft.state["fail"] = {"ls": {"kind": "weird", "message": "something odd"}}
        code, msg = self.code(self.ft.save().driver().list_tabs)
        self.assertEqual((code, msg), ("backend_error", "something odd"))

    def test_every_hc_call_has_a_timeout(self):
        self.ft.term("t1", "x")
        self.ft.state["sleep"] = {"ls": 5}
        d = self.ft.save().driver(timeout=0.4)
        t = time.time()
        self.assertEqual(self.code(d.list_tabs)[0], "timeout")
        self.assertLess(time.time() - t, 3)

    def test_defaults_come_from_the_environment(self):
        names = ("SB_TABS_HC_BIN", "SB_TABS_BIN", "SB_RUN_DIR", "SB_TABS_BACKEND")
        with mock.patch.dict(os.environ, {"SB_TABS_BIN": "/x/hc", "SB_RUN_DIR": "/x/run"}):
            for k in ("SB_TABS_HC_BIN", "SB_TABS_BACKEND"):
                os.environ.pop(k, None)
            d = mod.Tabs()
            self.assertEqual((d.binary, d.run_dir, d.backend.run_dir), ("/x/hc", "/x/run", "/x/run"))
            os.environ["SB_TABS_HC_BIN"] = "/y/hc"
            self.assertEqual(mod.Tabs().binary, "/y/hc")
            for k in names:
                os.environ.pop(k, None)
            d = mod.Tabs()
            self.assertEqual((d.binary, d.run_dir, d.pause, d.backend.name), ("hc", "/tmp/swarmbox", 0.15, "herdr"))


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
        # the top rule scrolled off: a screen no adapter recognises alone (one rule), read as the agent the tab is known to run
        self.assertIn("PONG-burst-1", mod.input_box(self.rows("failed-burst-long-newline-in-box.txt"), lenient=True, command="claude"))
        self.assertIsNone(mod.input_box(self.rows("failed-burst-long-newline-in-box.txt"), lenient=True, command="agy"), "agy has no screen adapter")

    def test_a_plain_shell_is_no_agent(self):
        self.assertEqual(mod.agent_state(["user@box:~$ ls", "a b c", "user@box:~$ "], "bash"), (False, "unknown"))
        self.assertEqual(mod.agent_state(["Do you want to continue? [Y/n]"], "apt"), (False, "unknown"))
        self.assertEqual(mod.agent_state(["booting"], "claude"), (True, "unknown"))

    def test_the_state_is_the_agents_adapter_reading_or_unknown(self):
        """the screen rules are the claude addon's (agent/screen.py); an agent without an adapter is an agent in state unknown, never
        read with another agent's rules; an agent under another process name is recognised by its adapter"""
        busy = self.rows("busy-streaming.txt")
        self.assertEqual(mod.agent_state(busy, "claude-code"), (True, "busy"))
        self.assertEqual(mod.agent_state(busy, "agy"), (True, "unknown"))
        self.assertEqual(mod.agent_state(busy, "opencode"), (True, "unknown"))
        self.assertEqual(mod.agent_state(busy, "node"), (True, "busy"))
        self.assertEqual(mod.agent_state(busy, "no-such-cli"), (True, "busy"), "a program that is no agent of the registry: the screen is Claude Code's")

    def test_busy_in_a_narrow_pane_where_the_footer_is_cut(self):
        """Real footers of Claude Code 2.1 in panes of 37, 45 and 52 columns while it worked, and the same panes idle (captured in Podman). The words
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
        self.ft.term("t1", "sh")
        self.ft.term("t2", "agent", **claude_term("busy"))
        d = self.ft.save().driver()
        self.assertEqual(d.send("t1", run="ls"), {"ok": True, "tab": "t1", "pane": "t1", "submitted": True})
        self.assertEqual(d.send("t1", input="ab")["submitted"], False)
        self.assertEqual(self.ft.typed("t1"), ["ls", "<enter>", "ab"])
        self.assertEqual(self.code(lambda: d.send("t2", run="next"))[0], "busy_tab")
        self.assertEqual(d.send("t2", run="next", queue=True)["tab"], "t2")
        self.assertEqual(self.code(lambda: d.send("t1"))[0], "bad_body")
        self.assertEqual(self.code(lambda: d.send("t1", run="a", input="b"))[0], "bad_body")

    def test_active(self):
        self.ft.term("t1", "a")
        self.ft.term("t2", "b")
        d = self.ft.save().active("t2").driver()
        self.assertEqual(d.active()["tab"], "t2")
        self.ft.state["terminals"] = []
        self.ft.save()
        self.assertEqual(self.code(d.active)[0], "no_such_tab")

    def test_an_agent_without_a_readable_input_box_is_verified_by_the_state_it_reports(self):
        """agy and OpenCode draw no input box SwarmBox reads: the submission shows as the reported state turning busy, or not at all"""
        class Agy(mod.TabsBackend):
            name = "mem"

            def __init__(self, starts_working):
                self.typed, self.starts_working = [], starts_working

            def list_tabs_raw(self):
                return [mod.Tab("m1", 1, "agy", "/", "agy", "m1", ["m1"], False, "1:agy")]

            def active_tab_id(self, ids):
                return ids[0]

            def capture_plain_rows(self, tab):
                return ["╭──────╮", "│ > " + "".join(self.typed[-2:-1]) + " │", "╰──────╯"]

            def tab_state(self, tab):
                return True, ("busy" if self.starts_working and "Enter" in self.typed else "idle")

            def send_text(self, tab, text):
                self.typed.append(text)

            def send_key(self, tab, key):
                self.typed.append(key)
        works = Agy(starts_working=True)
        out = mod.Tabs(backend=works, pause=0, verify_timeout=0.3, run_dir=self.ft.dir).send_body("agy", {"run": "fix the build"})
        self.assertIs(out["verified"], True)
        stays = Agy(starts_working=False)
        out = mod.Tabs(backend=stays, pause=0, verify_timeout=0.3, run_dir=self.ft.dir).send_body("agy", {"run": "fix the build"})
        self.assertIs(out["verified"], False, "no box to read and no busy state: unverified, not a success")
        self.assertEqual(stays.typed, ["fix the build", "Enter"], "never a second Enter when nothing says the text is still there")

    def test_any_tabs_backend_can_be_given(self):
        """Tabs(backend=...) is the contract between the facade and the multiplexer: a backend in memory gets the same rules"""
        class Mem(mod.TabsBackend):
            name = "mem"

            def __init__(self):
                self.typed = []

            def list_tabs_raw(self):
                return [mod.Tab("m1", 1, "one", "/", "claude", "m1", ["m1"], False, "1:one")]

            def active_tab_id(self, ids):
                return ids[0]

            def capture_plain_rows(self, tab):
                return ["─" * 20, "❯ ", "─" * 20, "  · esc to interrupt"]

            def send_text(self, tab, text):
                self.typed.append(text)

            def send_key(self, tab, key):
                self.typed.append(key)
        be = Mem()
        d = mod.Tabs(backend=be, pause=0, run_dir=self.ft.dir)
        self.assertEqual(d.active()["tab"], "m1")
        self.assertEqual(self.code(d.send_body, "one", {"run": "x"})[0], "busy_tab")
        d.send_body("one", {"input": "{Esc}"})
        self.assertEqual(be.typed, ["Escape"])
        self.assertEqual(self.code(d.focus_tab, "one")[0], "unsupported")


class TestLock(Base):
    """a lock per tab (flock in the run folder): two sends to one tab never interleave, whoever sends"""

    def setUp(self):
        Base.setUp(self)
        self.ft.term("t1", "one")
        self.ft.term("t2", "two")
        self.ft.save()

    def test_the_lock_is_a_file_in_the_run_folder_and_is_kept_between_sends(self):
        self.ft.driver().send("t1", run="x")
        self.assertEqual(sorted(os.listdir(os.path.join(self.ft.dir, "tabs"))), ["tab-t1.lock"])
        self.assertEqual(oct(os.stat(os.path.join(self.ft.dir, "tabs", "tab-t1.lock")).st_mode & 0o777), "0o600")
        self.ft.driver().send("t2", run="y")
        self.assertEqual(sorted(os.listdir(os.path.join(self.ft.dir, "tabs"))), ["tab-t1.lock", "tab-t2.lock"])

    def test_a_held_lock_makes_the_send_wait_and_then_time_out_with_nothing_typed(self):
        import fcntl
        d = self.ft.driver(lock_timeout=0.4)
        d.send("t1", run="warm")
        before = len(self.ft.sent())
        fd = os.open(os.path.join(self.ft.dir, "tabs", "tab-t1.lock"), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t = time.time()
            code, msg = self.code(lambda: d.send("t1", run="late"))
            self.assertEqual(code, "timeout")
            self.assertGreaterEqual(time.time() - t, 0.4)
            self.assertIn("nothing was typed", msg)
            d.send("t2", run="other tab is free")        # another tab is not blocked
        finally:
            os.close(fd)
        self.assertNotIn("late", self.ft.typed("t1"))
        self.assertEqual(len(self.ft.sent()), before + 2)
        d.send("t1", run="after")                         # released: it works again
        self.assertEqual(self.ft.typed("t1")[-2:], ["after", "<enter>"])

    def test_two_processes_sending_to_one_tab_never_interleave(self):
        import subprocess
        import tabs_support
        procs = []
        for i in range(4):
            procs.append(subprocess.Popen([sys.executable, "-S", tabs_support.TABS_PATH, "send", "t1", "--run", "msg%d one two three" % i],
                                          env=self.ft.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, (out, err))
        typed = self.ft.typed("t1")
        self.assertEqual(len(typed), 8)
        for i in range(0, 8, 2):
            self.assertTrue(typed[i].startswith("msg") and typed[i + 1] == "<enter>", typed)

    def test_a_run_folder_that_cannot_be_used_is_lock_error_and_nothing_is_typed(self):
        open(os.path.join(self.ft.dir, "tabs"), "w").close()         # a file where the folder should be
        d = self.ft.driver()
        self.assertEqual(self.code(lambda: d.send("t1", run="x"))[0], "lock_error")
        self.assertEqual(self.ft.sent(), [])


class TestCommand(Base):
    """the command line: JSON on stdout, the exit codes, stdin, the environment, the text over the framed `hc connect`"""

    def setUp(self):
        Base.setUp(self)
        self.ft.term("t1", "sh", screen="hello \x1b[7mworld\x1b[27m  token=abc12345\nsecond")
        self.ft.term("t2", "agent", **claude_term())
        self.ft.save().active("t2")

    def test_list_active_screen(self):
        rc, out, err = self.ft.cli("list")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual([t["tab"] for t in out], ["t1", "t2"])
        self.assertEqual([t["active"] for t in out], [False, True])
        rc, out, _ = self.ft.cli("active")
        self.assertEqual((rc, out["tab"], out["label"]), (0, "t2", "2:agent"))
        rc, out, _ = self.ft.cli("screen", "sh")
        self.assertEqual((rc, out["text"]), (0, "hello [sel]world[/sel]  token=[REDACTED]\nsecond"))
        rc, out, _ = self.ft.cli("screen", "t1", "--lines", "1")
        self.assertEqual((rc, out["text"], out["lines"]), (0, "second", 1))

    def test_send_run_and_input_and_queue_and_slash(self):
        rc, out, _ = self.ft.cli("send", "t1", "--run", "echo hi")
        self.assertEqual((rc, out), (0, {"ok": True, "tab": "t1", "pane": "t1", "submitted": True}))
        rc, out, _ = self.ft.cli("send", "2:agent", "--input", "ab{Esc}")
        self.assertEqual((rc, out["submitted"]), (0, False))
        self.assertEqual(self.ft.typed("t1"), ["echo hi", "<enter>"])
        self.assertEqual(self.ft.typed("t2"), ["ab", "<esc>"])
        rc, out, _ = self.ft.cli("send", "agent", "--run", "/help")
        self.assertEqual((rc, out["err"]), (1, "slash_refused"))
        rc, out, _ = self.ft.cli("send", "agent", "--run", "/clear", "--slash")
        self.assertEqual(rc, 0)
        self.ft.load()
        self.ft.state["terminals"][1]["claude"]["mode"] = "busy"
        self.ft.save()
        rc, out, _ = self.ft.cli("send", "agent", "--run", "next")
        self.assertEqual((rc, out["err"]), (1, "busy_tab"))
        rc, out, _ = self.ft.cli("send", "agent", "--run", "next", "--queue")
        self.assertEqual(rc, 0)

    def test_a_long_text_goes_in_small_frames_and_is_typed_whole(self):
        text = "echo " + "é" * 2600 + "\n" + "a" * 3000
        rc, out, err = self.ft.cli("send", "t1", "--run", text)
        self.assertEqual(rc, 0, (out, err))
        frames = self.ft.load()["frames"]
        self.assertGreater(len(frames), 4)
        self.assertLessEqual(max(frames), mod.CHUNK)
        self.assertEqual(self.ft.typed("t1"), [text, "<enter>"])

    def test_the_text_may_come_from_stdin(self):
        rc, out, _ = self.ft.cli("send", "t1", "--run", "-", stdin=b"line one\nline two\n")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ft.typed("t1"), ["line one\nline two", "<enter>"])
        rc, out, _ = self.ft.cli("send", "t1", "--input", "-", stdin=b"{C-c}")
        self.assertEqual(rc, 0)
        self.assertEqual(self.ft.typed("t1")[-1], "<ctrl+c>")
        for data in (b"\xff\xfe", b"a\x00b", b""):
            rc, out, _ = self.ft.cli("send", "t1", "--run", "-", stdin=data)
            self.assertEqual((rc, out["err"]), (2, "bad_body"), data)

    def test_open_focus_close(self):
        rc, out, _ = self.ft.cli("open", "--name", "api", "--agent", "antigravity", "--cwd", self.ft.dir)
        self.assertEqual((rc, out), (0, {"ok": True, "tab": "t3", "name": "api", "agent": "agy"}))
        rc, out, _ = self.ft.cli("open", "--agent", "no-such-cli")      # no addon declares it: a program, not an agent
        self.assertEqual((rc, out["err"]), (2, "usage"))
        self.assertEqual(self.ft.cli("active")[1]["tab"], "t3")
        rc, out, _ = self.ft.cli("focus", "sh")
        self.assertEqual((rc, out["tab"]), (0, "t1"))
        self.assertEqual(self.ft.cli("active")[1]["tab"], "t1")
        rc, out, _ = self.ft.cli("close", "api")
        self.assertEqual((rc, out["tab"]), (0, "t3"))
        self.assertEqual([t["tab"] for t in self.ft.cli("list")[1]], ["t1", "t2"])

    def test_errors_are_json_on_stdout_with_the_exit_codes(self):
        cases = [(("screen", "t9"), 1, "no_such_tab"), (("send", "t9", "--run", "x"), 1, "no_such_tab"), (("list", "x"), 2, "usage"),
                 (("nope",), 2, "usage"), ((), 2, "usage"), (("screen",), 2, "usage"), (("screen", "t1", "--lines", "x"), 2, "usage"),
                 (("screen", "t1", "--lines", "0"), 2, "usage"), (("send", "t1"), 2, "usage"), (("send", "t1", "--run", "a", "--input", "b"), 2, "usage"),
                 (("send", "t1", "--run"), 2, "usage"), (("send", "t1", "--bogus", "a"), 2, "usage"), (("open", "--agent", "vim"), 2, "usage"),
                 (("open", "--cwd", "/nonexistent/x"), 2, "bad_body")]
        for args, rc, code in cases:
            with self.subTest(args=args):
                got, out, _ = self.ft.cli(*args)
                self.assertEqual((got, out["err"]), (rc, code))
                self.assertTrue(out["msg"])
        self.assertEqual(self.ft.sent(), [])
        self.ft.load()
        self.ft.term("t3", "sh")
        self.ft.save()
        rc, out, _ = self.ft.cli("screen", "sh")
        self.assertEqual((rc, out["err"]), (1, "ambiguous_tab"))

    def test_no_hc_and_no_server_are_4(self):
        rc, out, _ = self.ft.cli("list", SB_TABS_BIN="/nonexistent/hc")
        self.assertEqual((rc, out["err"]), (4, "no_backend"))
        rc, out, _ = self.ft.cli("list", SB_TABS_BACKEND="tmux")
        self.assertEqual((rc, out["err"]), (4, "no_backend"))
        self.ft.load()
        self.ft.state["down"] = True
        self.ft.save()
        rc, out, _ = self.ft.cli("list")
        self.assertEqual((rc, out["err"]), (4, "no_session"))

    def test_every_error_code_has_its_exit_code(self):
        """the exit codes of the documented contract (usage, bad_body 2; no_backend, no_session 4; timeout 5; the others 1), in process: the real
        timeout of an hc call is tested at the driver (test_every_hc_call_has_a_timeout)"""
        want = {"usage": 2, "bad_body": 2, "no_backend": 4, "no_session": 4, "timeout": 5, "no_such_tab": 1, "ambiguous_tab": 1, "busy_tab": 1,
                "backend_error": 1, "unsupported": 1}
        for code, rc in want.items():
            with self.subTest(code=code), mock.patch.object(mod, "run", side_effect=mod.TabsError(code, "m")), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(mod.main(["list"]), rc)
                self.assertEqual(json.loads(out.getvalue()), {"err": code, "msg": "m"})

    def test_help(self):
        import subprocess
        import tabs_support
        r = subprocess.run([sys.executable, "-S", tabs_support.TABS_PATH, "--help"], capture_output=True, env=self.ft.env())
        self.assertEqual(r.returncode, 0)
        for word in (b"swarmbox-tabs list", b"swarmbox-tabs open", b"swarmbox-tabs focus", b"swarmbox-tabs close"):
            self.assertIn(word, r.stdout)
        self.assertNotIn(b"tmux", r.stdout)


class TestImage(unittest.TestCase):
    def test_the_dockerfile_installs_the_command_and_no_driver_module(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("COPY container/scripts/swarmbox-tabs.py /usr/local/bin/swarmbox-tabs\n", d)
        self.assertRegex(d, r"chmod 755 [^\n]*(\\\n[^\n]*)*/usr/local/bin/swarmbox-tabs ")
        self.assertNotIn("swarmbox-bus-tmux", d)

    def test_the_bus_knows_nothing_of_the_multiplexer_or_tabs(self):
        with open(os.path.join(ROOT, "container", "scripts", "swarmbox-bus.py")) as f:
            src = f.read()
        code = src.split('"""', 2)[2]
        for word in ("tmux", "herdr", "tab/", "Driver", "driver", "no_screen"):
            self.assertNotIn(word, code)

    def test_tabs_has_no_trace_of_tmux(self):
        with open(os.path.join(ROOT, "container", "scripts", "swarmbox-tabs.py")) as f:
            self.assertNotIn("tmux", f.read().lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
