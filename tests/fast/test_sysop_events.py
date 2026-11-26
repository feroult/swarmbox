"""Fast tests of the live log of a goal (events.py): the adapter of Claude Code's stream-json (partial messages, the text of say and done
decoded while it is typed, actions, thinking, usage, denials, the session), the text adapter, the partial-JSON reader, the single writer
(seq, order across threads, the cap on deltas) and the filter of the MCP server's events. No brain, no model.

Run: python3 tests/fast/test_sysop_events.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402,F401  (puts the sysop library on the path)

from swarmbox_sysop import events  # noqa: E402


def se(event):
    return json.dumps({"type": "stream_event", "event": event})


def start(i, block):
    return se({"type": "content_block_start", "index": i, "content_block": block})


def delta(i, d):
    return se({"type": "content_block_delta", "index": i, "delta": d})


def stop(i):
    return se({"type": "content_block_stop", "index": i})


def feed(adapter, lines):
    out = []
    for line in lines:
        out += adapter.feed(line)
    return out


class PartialJson(unittest.TestCase):
    def test_reads_the_value_so_far_and_waits_for_a_cut_escape(self):
        p = events.partial_json_string
        self.assertEqual(p('{"te', "text"), "")
        self.assertEqual(p('{"text": "Abrin', "text"), "Abrin")
        self.assertEqual(p('{"text":"a\\nb \\"c\\""}', "text"), 'a\nb "c"')
        self.assertEqual(p('{"text":"linha\\', "text"), "linha")
        self.assertEqual(p('{"text":"a\\u00e', "text"), "a")
        self.assertEqual(p('{"text":"a\\u00e7\\u00e3o"}', "text"), "ação")
        self.assertEqual(p('{"text":"x \\ud83d', "text"), "x ")
        self.assertEqual(p('{"text":"x \\ud83d\\ude80"}', "text"), "x \U0001F680")
        self.assertEqual(p('{"summary":"fim","text":"n"}', "summary"), "fim")


class ClaudeAdapter(unittest.TestCase):
    def test_a_say_streams_its_text_and_an_action_its_choice_then_its_arguments(self):
        a = events.ClaudeStreamAdapter()
        out = feed(a, [
            json.dumps({"type": "system", "subtype": "init", "session_id": "s-1"}),
            se({"type": "message_start", "message": {}}),
            start(0, {"type": "tool_use", "id": "toolu_A", "name": "mcp__sysop__say", "input": {}}),
            delta(0, {"type": "input_json_delta", "partial_json": '{"text": "Olhando'}),
            delta(0, {"type": "input_json_delta", "partial_json": ' as abas\\'}),
            delta(0, {"type": "input_json_delta", "partial_json": 'n- t2"}'}),
            stop(0),
            se({"type": "message_start", "message": {}}),
            start(0, {"type": "tool_use", "id": "toolu_B", "name": "mcp__sysop__run", "input": {}}),
            delta(0, {"type": "input_json_delta", "partial_json": '{"tab": "t1", "comm'}),
            delta(0, {"type": "input_json_delta", "partial_json": 'and": "pytest -q"}'}),
            stop(0),
            start(1, {"type": "tool_use", "id": "toolu_X", "name": "Bash", "input": {}}),
            stop(1),
        ])
        self.assertEqual(out, [
            ("session", {"id": "s-1"}),
            ("action.start", {"block": "toolu_A", "fn": "say"}),
            ("say.delta", {"block": "toolu_A", "text": "Olhando"}),
            ("say.delta", {"block": "toolu_A", "text": " as abas"}),
            ("say.delta", {"block": "toolu_A", "text": "\n- t2"}),
            ("action.args", {"block": "toolu_A", "fn": "say", "args": {"text": "Olhando as abas\n- t2"}}),
            ("action.start", {"block": "toolu_B", "fn": "run"}),
            ("action.args", {"block": "toolu_B", "fn": "run", "args": {"tab": "t1", "command": "pytest -q"}}),
        ], "a tool that is not the sysop's is not shown")

    def test_free_text_thinking_and_a_done_summary(self):
        a = events.ClaudeStreamAdapter()
        out = feed(a, [
            se({"type": "message_start", "message": {}}),
            start(0, {"type": "thinking", "thinking": ""}),
            delta(0, {"type": "signature_delta", "signature": "abc"}),
            stop(0),
            start(1, {"type": "text", "text": ""}),
            delta(1, {"type": "text_delta", "text": "Vou "}),
            delta(1, {"type": "text_delta", "text": "ver."}),
            stop(1),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Vou ver."}]}}),
            start(2, {"type": "tool_use", "id": "toolu_D", "name": "mcp__sysop__done", "input": {}}),
            delta(2, {"type": "input_json_delta", "partial_json": '{"summary": "Pron'}),
            delta(2, {"type": "input_json_delta", "partial_json": 'to"}'}),
            stop(2),
        ])
        self.assertEqual(out, [
            ("thinking", {"block": "m1.0", "state": "started"}),
            ("thinking", {"block": "m1.0", "state": "ended"}),
            ("text.delta", {"block": "m1.1", "text": "Vou "}),
            ("text.delta", {"block": "m1.1", "text": "ver."}),
            ("text", {"block": "m1.1", "text": "Vou ver."}),
            ("action.start", {"block": "toolu_D", "fn": "done"}),
            ("reply.delta", {"block": "toolu_D", "text": "Pron"}),
            ("reply.delta", {"block": "toolu_D", "text": "to"}),
            ("action.args", {"block": "toolu_D", "fn": "done", "args": {"summary": "Pronto"}}),
        ], "the complete message repeats what the partial messages showed: it adds nothing")
        self.assertEqual(a.assistant_text, "Vou ver.")

    def test_a_stream_without_partial_messages_still_shows_actions_and_text(self):
        a = events.ClaudeStreamAdapter()
        out = feed(a, [json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "ok"}, {"type": "tool_use", "id": "t1", "name": "mcp__sysop__box_state", "input": {"section": "system"}}]}})])
        self.assertEqual(out, [("action.start", {"block": "t1", "fn": "box_state"}),
                               ("action.args", {"block": "t1", "fn": "box_state", "args": {"section": "system"}}),
                               ("text", {"block": "m0.full", "text": "ok"})])

    def test_the_result_gives_usage_denials_and_the_reply(self):
        a = events.ClaudeStreamAdapter()
        out = feed(a, ["Not logged in · Please run /login", json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.01, "result": "feito",
             "session_id": "s-2", "permission_denials": [{"tool_name": "Bash", "tool_use_id": "x"}]})])
        self.assertEqual(out, [("session", {"id": "s-2"}), ("usage", {"turns": 3, "cost": 0.01}), ("denied", {"fn": "Bash"})])
        self.assertEqual((a.assistant_text, a.session_id, a.result["num_turns"]), ("feito", "s-2", 3))
        self.assertIn("Not logged in", "\n".join(a.tail), "a line that is not an event is kept for the login check")

    def test_garbage_is_kept_never_raised(self):
        a = events.ClaudeStreamAdapter()
        self.assertEqual(feed(a, ["{not json", "[1,2]", "", se({"type": "content_block_delta", "index": 9, "delta": {}})]), [])


class TextAdapter(unittest.TestCase):
    def test_every_line_is_text_and_the_reply_is_the_whole_output(self):
        a = events.adapter("text")
        self.assertEqual(feed(a, ["hello", "world"]), [("text.delta", {"block": "out", "text": "hello\n"}),
                                                       ("text.delta", {"block": "out", "text": "world\n"})])
        self.assertEqual(a.assistant_text, "hello\nworld")
        self.assertIsInstance(events.adapter("no-such-format"), events.TextAdapter)


class Log(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="swarmbox-test-events.")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "events.jsonl")

    def test_one_writer_gives_one_order_across_threads(self):
        log = events.EventLog(self.path, clock=lambda: 5.0)
        seen = []
        log.listeners.append(seen.append)

        def burst(n):
            for i in range(200):
                log.emit("text.delta", block=n, text="x")
        ts = [threading.Thread(target=burst, args=(n,)) for n in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        log.close()
        got = events.read(self.path)
        self.assertEqual([e["seq"] for e in got], list(range(1, 801)))
        self.assertEqual(len(seen), 800)
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")
        self.assertEqual([e["seq"] for e in events.read(self.path, since=798)], [799, 800])

    def test_past_the_cap_deltas_are_dropped_and_the_rest_is_kept(self):
        log = events.EventLog(self.path)
        log.MAX_BYTES = 300
        for _ in range(10):
            log.emit("text.delta", block="b", text="y" * 50)
        log.emit("state", state="done")
        log.close()
        got = events.read(self.path)
        self.assertLess(len([e for e in got if e["type"] == "text.delta"]), 10)
        self.assertEqual(got[-1]["type"], "state")


class McpEvents(unittest.TestCase):
    def test_only_known_types_and_fields_pass(self):
        self.assertEqual(events.mcp_event(json.dumps({"type": "call", "id": "toolu_1", "fn": "run", "args": {"command": "ls"}, "evil": 1})),
                         ("call", {"id": "toolu_1", "fn": "run", "args": {"command": "ls"}}))
        self.assertIsNone(events.mcp_event(json.dumps({"type": "state", "state": "done"})), "only the service writes states")
        self.assertIsNone(events.mcp_event("not json"))


if __name__ == "__main__":
    unittest.main()
