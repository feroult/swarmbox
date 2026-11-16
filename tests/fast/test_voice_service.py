"""Voice addon, the service: audio -> text (Whisper) -> a goal on the bus. Voice is an input: nothing is planned, shown or executed here.

The recognizer is a fake whisper-cli (tests/support/fixtures/voice/whisper-fake: no model, no network, no microphone). The bus is the REAL broker
(swarmbox-bus.py in a thread, tests/support/bus_support.py) for the goals that arrive and for the answers a missing
or busy subscriber gives; a fake broker (a few lines of unix socket) gives the answers the real one hardly can (busy, garbage, closed). The HTTP
tests talk to the real server on 127.0.0.1:0 in a thread. No tmux. Run with: python3 -W error tests/fast/test_voice_service.py

The design: POST /voice/audio does transcribe + publish in one call and its answer is only a state with a fixed text ({"ok": true, "state":
"sent"} or {"ok": false, "state": nothing_heard | no_listener | busy | bus_down}), never the transcript; /voice/health and /voice/audio are
all the service has (the plan, pending, edit, run and cancel calls went with the planners).
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import voice_support  # noqa: E402
from helpers import close_listener  # noqa: E402
from bus_support import Harness, short_tmp  # noqa: E402
from voice_support import wav_samples, wav_with  # noqa: E402

from swarmbox_voice import busclient, config, server, stt  # noqa: E402
from swarmbox_voice.server import HttpError, Service  # noqa: E402

SECRET = "the secret transcript 8d1f"


class FakeBroker:
    """One unix socket that answers every request with `reply` (a dict, raw bytes, or None to close without a word) and keeps the requests."""

    def __init__(self, reply):
        self.dir = short_tmp("sbvoice-")
        self.path = os.path.join(self.dir, "bus.sock")
        self.reply, self.requests = reply, []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(8)
        self.thread = threading.Thread(target=self.loop, args=(self.srv,), daemon=True)
        self.thread.start()

    def loop(self, srv):
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with c, c.makefile("rb") as f:
                self.requests.append(json.loads(f.readline()))
                if self.reply is not None:
                    c.sendall(self.reply if isinstance(self.reply, bytes) else (json.dumps(self.reply) + "\n").encode())

    def close(self):
        close_listener(self.srv, self.thread)
        shutil.rmtree(self.dir, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-voice.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "whisper.log")
        self.old = {k: os.environ.get(k) for k in ("SWARMBOX_TEST_WHISPER", "SWARMBOX_TEST_MODELS", "SWARMBOX_TEST_WHISPER_LOG", "SB_BUS_SOCKET", "SB_RUN_DIR")}
        os.environ["SWARMBOX_TEST_WHISPER"] = voice_support.WHISPER_FAKE
        os.environ["SWARMBOX_TEST_MODELS"] = self.tmp
        os.environ["SWARMBOX_TEST_WHISPER_LOG"] = self.log
        os.environ.pop("SB_BUS_SOCKET", None)
        os.environ.pop("SB_RUN_DIR", None)
        self.addCleanup(self.restore_env)
        open(os.path.join(self.tmp, "ggml-small.bin"), "w").close()
        open(os.path.join(self.tmp, "ggml-medium.bin"), "w").close()

    def restore_env(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def bus(self):
        h = Harness()
        self.addCleanup(h.close)
        return h

    def service(self, env=None, bus_path=None):
        self.logged = []
        path = bus_path or os.path.join(self.tmp, "no-bus.sock")
        return Service(config.load(env or {}), publish=lambda text: busclient.publish(config.load(env or {}).topic, text, path), log=self.logged.append)

    def whisper_calls(self):
        with open(self.log) as f:
            return [json.loads(x) for x in f.read().splitlines()]


class GoalOnTheBus(Base):
    def test_audio_becomes_a_goal_with_source_voice_and_only_the_text(self):
        h = self.bus()
        sub = h.sub("goal")
        status, out = self.service(bus_path=h.path).audio(wav_with("run the tests"))
        self.assertEqual((status, out), (200, {"ok": True, "state": "sent"}))
        env = sub.line()
        self.assertEqual((env["topic"], env["source"], env["body"]), ("goal", "voice", {"text": "run the tests"}))
        self.assertEqual(env["peer"]["uid"], os.getuid(), "who published is the broker's word, not a field we add")
        self.assertEqual(sorted(env["body"]), ["text"])

    def test_the_topic_is_the_setting_and_not_a_fixed_name(self):
        h = self.bus()
        other, goal = h.sub("tasks.one"), h.sub("goal")
        svc = self.service({"SWARMBOX_VOICE_TOPIC": "tasks.one"}, bus_path=h.path)
        self.assertEqual(svc.audio(wav_with("hello"))[1], {"ok": True, "state": "sent"})
        env = other.line()
        self.assertEqual((env["topic"], env["body"]), ("tasks.one", {"text": "hello"}))
        goal.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            goal.line()
        self.assertEqual(self.service({"SWARMBOX_VOICE_TOPIC": "nobody.here"}, bus_path=h.path).audio(wav_with("x"))[1]["state"], "no_listener")

    def test_every_subscriber_of_the_topic_gets_the_goal(self):
        h = self.bus()
        a, b = h.sub("goal"), h.sub("goal")
        self.assertEqual(self.service(bus_path=h.path).goal("both"), "sent")
        self.assertEqual((a.line()["body"], b.line()["body"]), ({"text": "both"},) * 2)

    def test_the_answer_never_holds_the_transcript(self):
        h = self.bus()
        h.sub("goal")
        svc = self.service(bus_path=h.path)
        for wav in (wav_with(SECRET), wav_with("SILENCE " + SECRET)):
            status, out = svc.audio(wav)
            self.assertNotIn(SECRET, json.dumps(out))
        status, out = self.service().audio(wav_with(SECRET))          # no bus at all
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertEqual([m for m in self.logged if SECRET in m], [], "and it is not logged either")

    def test_no_subscriber_is_no_listener(self):
        h = self.bus()
        status, out = self.service(bus_path=h.path).audio(wav_with("hello"))
        self.assertEqual((status, out["ok"], out["state"]), (503, False, "no_listener"))
        self.assertEqual(out["message"], "Nobody is listening.")

    def test_no_bus_is_bus_down(self):
        status, out = self.service().audio(wav_with("hello"))
        self.assertEqual((status, out["ok"], out["state"]), (503, False, "bus_down"))
        self.assertEqual(out["message"], "The bus of the box is not answering.")

    def test_silence_is_nothing_heard_and_nothing_is_published(self):
        h = self.bus()
        sub = h.sub("goal")
        status, out = self.service(bus_path=h.path).audio(wav_with("SILENCE"))
        self.assertEqual((status, out), (200, {"ok": False, "state": "nothing_heard", "message": "Nothing heard."}))
        sub.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            sub.line()

    def test_a_recording_with_no_sound_never_reaches_whisper_and_nothing_is_published(self):
        """found by tests/e2e/e2e_voice.py with the real Whisper small: a second of digital silence came back as the word 'you', a little noise as 'ლლლლ',
        '[MÚSICA DE FUNDO]' or '(water running)', and each of them became a goal on the bus, handled by the sysop"""
        import math
        import random
        random.seed(7)
        h = self.bus()
        sub = h.sub("goal")
        svc = self.service(bus_path=h.path)
        quiet = {"silence": [0] * 32000, "noise of a muted microphone": [int(random.gauss(0, 30)) for _ in range(32000)],
                 "a very quiet hum": [int(60 * math.sin(2 * math.pi * 100 * i / 16000)) for i in range(32000)]}
        for name, samples in quiet.items():
            self.assertEqual(svc.audio(wav_samples(samples))[1]["state"], "nothing_heard", name)
        self.assertFalse(os.path.exists(self.log), "the recognizer was not asked (the fake writes its log when it runs)")
        sub.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            sub.line()

    def test_the_loudness_of_speech_is_far_above_the_gate_and_a_short_click_is_judged_whole(self):
        import math
        speech = [int(2500 * math.sin(2 * math.pi * 180 * i / 16000) * (1 + math.sin(i / 900.0)) / 2) for i in range(48000)]
        self.assertGreater(stt.loudest(wav_samples(speech)), 5 * stt.MIN_RMS)
        stt.check_speech(wav_samples(speech))
        self.assertGreater(stt.loudest(wav_samples([0] * 40000 + speech[:1600])), stt.MIN_RMS, "a word after a long silence counts: the loudest 100 ms")
        self.assertGreater(stt.loudest(wav_samples([20000] * 40)), stt.MIN_RMS, "shorter than 100 ms: the whole clip")
        with self.assertRaises(stt.SttError) as c:
            stt.check_speech(wav_samples([0] * 16000))
        self.assertEqual(c.exception.code, "no_speech")

    def test_loudest_gives_the_same_answer_as_the_prefix_sum_and_keeps_no_list_of_samples(self):
        import math
        import random
        import tracemalloc
        random.seed(3)
        for n in (10, 799, 800, 1599, 1600, 1601, 2401, 48123):
            samples = [int(random.gauss(0, 3000)) for _ in range(n)]
            win = min(1600, n)
            sq = [x * x for x in samples]
            want = math.sqrt(max(sum(sq[i:i + win]) for i in range(0, n - win + 1, 800)) / win)
            self.assertAlmostEqual(stt.loudest(wav_samples(samples)), want, places=6, msg=n)
        big = wav_samples([int(random.gauss(0, 3000)) for _ in range(2_000_000)])
        tracemalloc.start()
        stt.loudest(big)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        self.assertLess(peak, 2_000_000, "a list of 2 million ints would be 16 MB or more (peak %d)" % peak)

    def test_a_note_of_the_recognizer_about_a_sound_is_not_a_transcript(self):
        for note in ("[BLANK_AUDIO]", "[MÚSICA DE FUNDO]", "[Som de fio]", "(water running)", "(música)", "[MUSIC] [NOISE]", " [Silêncio] "):
            self.assertEqual(stt.clean(note), "", note)
        self.assertEqual(stt.clean("rode os testes [MUSIC]"), "rode os testes")
        self.assertEqual(stt.clean("run the tests (now)"), "run the tests", "a short parenthesized note goes too: speech has no brackets")
        self.assertEqual(stt.clean("a" * 70 + " " + "[" + "x" * 70 + "]"), "a" * 70 + " [" + "x" * 70 + "]", "only short notes")

    def test_a_transcript_of_invisible_characters_only_is_nothing_heard(self):
        h = self.bus()
        h.sub("goal")
        self.assertEqual(self.service(bus_path=h.path).audio(wav_with("\u200b \u200f\u2060  "))[1]["state"], "nothing_heard")

    def test_the_text_is_cleaned_and_bounded(self):
        h = self.bus()
        sub = h.sub("goal")
        svc = self.service(bus_path=h.path)
        self.assertEqual(svc.goal("  run\u200b the\ttests \n now\x00 "), "sent")
        self.assertEqual(sub.line()["body"]["text"], "run the tests now")
        self.assertEqual(svc.goal("x" * (server.MAX_GOAL + 500)), "sent")
        self.assertEqual(len(sub.line()["body"]["text"]), server.MAX_GOAL)

    def test_a_recognizer_error_keeps_its_fixed_text_and_publishes_nothing(self):
        h = self.bus()
        sub = h.sub("goal")
        svc = self.service(bus_path=h.path)
        for wav, status, code in ((b"not a wav at all, just text" * 3, 400, "stt_bad_audio"), (wav_with("FAIL"), 422, "stt_failed")):
            with self.assertRaises(HttpError) as cm:
                svc.audio(wav)
            self.assertEqual((cm.exception.status, cm.exception.code), (status, code))
            self.assertEqual(cm.exception.message, server.AUDIO_MESSAGES[code])
        sub.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            sub.line()


class BusClientAnswers(Base):
    def publish(self, reply):
        fb = FakeBroker(reply)
        self.addCleanup(fb.close)
        return busclient.publish("goal", "go", fb.path, timeout=2), fb

    def test_the_request_is_the_documented_one(self):
        state, fb = self.publish({"ok": True, "id": "b-1", "delivered": 1})
        self.assertEqual(state, "sent")
        self.assertEqual(fb.requests, [{"op": "pub", "topic": "goal", "source": "voice", "body": {"text": "go"}}])

    def test_every_answer_maps_to_a_fixed_state(self):
        cases = [({"ok": False, "err": "no_subscriber"}, "no_listener"), ({"ok": False, "err": "busy"}, "busy"),
                 ({"ok": False, "err": "too_large"}, "bus_down"), ({"ok": False, "err": "forbidden", "msg": SECRET}, "bus_down"),
                 ({"ok": False}, "bus_down"), ({"ok": "yes"}, "bus_down"), (b"[1]\n", "bus_down"), (b"not json\n", "bus_down"), (b"", "bus_down"),
                 (None, "bus_down")]
        for reply, want in cases:
            with self.subTest(reply=reply):
                self.assertEqual(self.publish(reply)[0], want)

    def test_a_bus_that_never_answers_is_bus_down_after_the_timeout(self):
        fb = FakeBroker(None)
        self.addCleanup(fb.close)
        fb.reply = None
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        path = os.path.join(fb.dir, "mute.sock")
        srv.bind(path)
        srv.listen(1)
        self.addCleanup(srv.close)
        t = time.time()
        self.assertEqual(busclient.publish("goal", "go", path, timeout=0.4), "bus_down")
        self.assertLess(time.time() - t, 3)

    def test_the_socket_path_follows_the_run_folder_rules_of_the_box(self):
        self.assertEqual(busclient.socket_path({}), "/tmp/swarmbox/bus.sock")
        self.assertEqual(busclient.socket_path({"SB_RUN_DIR": "/r"}), "/r/bus.sock")
        self.assertEqual(busclient.socket_path({"SB_RUN_DIR": "/r", "SB_BUS_SOCKET": "/s.sock"}), "/s.sock")

    def test_it_speaks_to_the_real_broker_like_the_sysop_client(self):
        h = self.bus()
        sub = h.sub("goal")
        self.assertEqual(busclient.publish("goal", "one", h.path), "sent")
        self.assertEqual(sub.line()["body"], {"text": "one"})
        self.assertEqual(busclient.publish("goal", "x" * (1 << 20), h.path), "bus_down", "too large for the bus: no state of its own")


class SttWiringTests(Base):
    def test_defaults_ask_for_auto_detection_and_pass_no_prompt(self):
        self.service().transcribe(wav_with("hello"))
        argv = self.whisper_calls()[0]
        self.assertEqual(argv[argv.index("-l") + 1], "auto")
        self.assertNotIn("--prompt", argv)
        self.assertEqual(argv[argv.index("-m") + 1], os.path.join(self.tmp, "ggml-small.bin"))

    def test_language_model_and_vocabulary_reach_whisper(self):
        svc = self.service({"SWARMBOX_VOICE_LANGUAGE": "pt", "SWARMBOX_VOICE_STT_MODEL": "medium",
                            "SWARMBOX_VOICE_STT_VOCABULARY": "kubectl, Podman"})
        self.assertEqual(svc.transcribe(wav_with("rode os testes")), "rode os testes")
        argv = self.whisper_calls()[0]
        self.assertEqual(argv[argv.index("-l") + 1], "pt")
        self.assertEqual(argv[argv.index("--prompt") + 1], "kubectl, Podman")
        self.assertTrue(argv[argv.index("-m") + 1].endswith("ggml-medium.bin"))

    def test_the_audio_file_is_removed_after_the_call(self):
        self.service().transcribe(wav_with("hello"))
        wav = self.whisper_calls()[0][self.whisper_calls()[0].index("-f") + 1]
        self.assertFalse(os.path.exists(wav))
        self.assertFalse(os.path.exists(os.path.dirname(wav)))

    def test_failures_become_clear_errors(self):
        svc = self.service()
        cases = [(b"not a wav at all, just text" * 3, 400, "stt_bad_audio"), (wav_with("FAIL"), 422, "stt_failed"),
                 (wav_with("SILENCE"), 422, "stt_no_speech")]
        for wav, status, code in cases:
            with self.assertRaises(HttpError) as cm:
                svc.transcribe(wav)
            self.assertEqual((cm.exception.status, cm.exception.code), (status, code))
        os.unlink(os.path.join(self.tmp, "ggml-small.bin"))
        with self.assertRaises(HttpError) as cm:
            svc.transcribe(wav_with("hello"))
        self.assertEqual((cm.exception.status, cm.exception.code), (502, "stt_no_model"))

    def test_wrong_audio_formats_are_refused_before_whisper(self):
        import struct
        good = bytearray(wav_with("hello"))
        for offset, packed in ((22, struct.pack("<H", 2)), (24, struct.pack("<I", 44100)), (34, struct.pack("<H", 8))):
            bad = bytearray(good)
            bad[offset:offset + len(packed)] = packed
            with self.assertRaises(stt.SttError):
                stt.check_wav(bytes(bad))
        with self.assertRaises(stt.SttError):
            stt.check_wav(bytes(good[:44]))   # no samples
        self.assertFalse(os.path.exists(self.log), "whisper was never started")

    def test_en_models_are_never_used(self):
        for bad in ("small.en", "../small", "Small", ""):
            with self.assertRaises(stt.SttError):
                stt.model_path(bad)


class HttpTests(Base):
    def setUp(self):
        super().setUp()
        self.h = self.bus()
        self.sub = self.h.sub("goal")
        self.svc = self.service(bus_path=self.h.path)
        self.httpd = server.make_server(self.svc, "127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)

    def call(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            h = dict(headers or {})
            if host is not None:
                h["Host"] = host
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
                h.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            raw = r.read()
            return r.status, json.loads(raw) if raw else None, r
        finally:
            conn.close()

    def test_health(self):
        status, body, resp = self.call("GET", "/voice/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "language": "auto", "model": "small"})
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_audio_over_http_publishes_the_goal_and_answers_sent(self):
        status, out, _ = self.call("POST", "/voice/audio", wav_with("via http"), {"Content-Type": "audio/wav"})
        self.assertEqual((status, out), (200, {"ok": True, "state": "sent"}))
        self.assertNotIn("via http", json.dumps(out), "the answer to the audio upload holds no transcript")
        env = self.sub.line()
        self.assertEqual((env["source"], env["body"]), ("voice", {"text": "via http"}))

    def test_audio_states_and_errors_over_http(self):
        self.assertEqual(self.call("POST", "/voice/audio", wav_with("SILENCE"), {"Content-Type": "audio/wav"})[1]["state"], "nothing_heard")
        status, out, _ = self.call("POST", "/voice/audio", wav_with("FAIL"), {"Content-Type": "audio/wav"})
        self.assertEqual((status, out["error"]), (422, "stt_failed"))
        self.assertEqual(self.call("POST", "/voice/audio", b"x" * 100, {"Content-Type": "audio/wav"})[0], 400)
        self.assertEqual(self.call("POST", "/voice/audio", b"x", {"Content-Type": "audio/wav", "Content-Length": str(stt.MAX_WAV_BYTES + 1)})[0], 413)
        self.assertEqual(self.call("POST", "/voice/audio", b"{}", {"Content-Type": "application/json"})[0], 415)
        self.assertEqual(self.call("GET", "/voice/audio")[0], 405)
        self.assertEqual(self.call("POST", "/voice/health", b"{}", {"Content-Type": "audio/wav"})[0], 405)

    def test_no_listener_over_http_is_a_503_with_a_state(self):
        self.sub.close()
        time.sleep(0.2)
        status, out, _ = self.call("POST", "/voice/audio", wav_with("hello"), {"Content-Type": "audio/wav"})
        self.assertEqual((status, out["ok"], out["state"]), (503, False, "no_listener"))

    def test_the_service_has_only_health_and_audio(self):
        """The calls of the plan (and the old transcribe) are gone: not 405, not 200, a 404."""
        for method, path in (("GET", "/voice/pending"), ("POST", "/voice/plan"), ("POST", "/voice/run"), ("POST", "/voice/edit"),
                             ("POST", "/voice/cancel"), ("POST", "/voice/transcribe"), ("POST", "/voice/confirm"), ("GET", "/voice/nothing"),
                             ("GET", "/"), ("GET", "/voice/page.js")):
            body = {"id": "x", "utterance": "x"} if method == "POST" else None
            self.assertEqual(self.call(method, path, body)[0], 404, path)

    def test_host_and_origin_are_checked(self):
        self.assertEqual(self.call("GET", "/voice/health", host="evil.example")[0], 403)
        self.assertEqual(self.call("GET", "/voice/health", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.call("GET", "/voice/health", host="localhost:%d" % self.port)[0], 200)
        for origin in ("http://evil.example", "null", "http://127.0.0.1:1"):
            self.assertEqual(self.call("GET", "/voice/health", headers={"Origin": origin})[0], 403, origin)
        same = "http://127.0.0.1:%d" % self.port
        self.assertEqual(self.call("GET", "/voice/health", headers={"Origin": same})[0], 200)
        self.assertEqual(self.call("OPTIONS", "/voice/audio", headers={"Origin": "http://evil.example"})[0], 405)
        status, _, resp = self.call("POST", "/voice/audio", wav_with("x"), {"Origin": "http://evil.example", "Content-Type": "audio/wav"})
        self.assertEqual(status, 403)
        self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
        env_none = self.sub
        env_none.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            env_none.line()

    def test_only_loopback_addresses_are_accepted_for_listening(self):
        for host in ("0.0.0.0", "", "192.168.1.5", "example.com", "::"):
            with self.assertRaises(ValueError):
                server.make_server(self.svc, host, 0)

    def test_an_internal_error_does_not_leak_a_traceback(self):
        self.svc.audio = lambda *a: 1 / 0
        status, body, _ = self.call("POST", "/voice/audio", wav_with("x"), {"Content-Type": "audio/wav"})
        self.assertEqual((status, body["error"]), (500, "internal"))
        self.assertNotIn("Traceback", json.dumps(body))


class SayCommand(Base):
    """`swarmbox-voice say TEXT`: the same goal without a microphone, through the real command."""

    def say(self, h_path, *text):
        env = dict(os.environ, PYTHONPATH=os.path.join(voice_support.VOICE, "lib"), SB_BUS_SOCKET=h_path)
        return subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "say", *text], env=env, capture_output=True, text=True, timeout=30)

    def test_say_publishes_a_goal_and_exits_0(self):
        h = self.bus()
        sub = h.sub("goal")
        p = self.say(h.path, "run", "the tests")
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)
        env = sub.line()
        self.assertEqual((env["source"], env["body"]), ("voice", {"text": "run the tests"}))

    def test_say_follows_the_topic_setting(self):
        h = self.bus()
        sub = h.sub("tasks")
        env = dict(os.environ, PYTHONPATH=os.path.join(voice_support.VOICE, "lib"), SB_BUS_SOCKET=h.path, SWARMBOX_VOICE_TOPIC="tasks")
        p = subprocess.run([sys.executable, "-B", "-m", "swarmbox_voice", "say", "hi"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(sub.line()["topic"], "tasks")

    def test_say_exit_codes_tell_the_state(self):
        h = self.bus()
        self.assertEqual(self.say(h.path, "x").returncode, 3, "no subscriber")
        self.assertIn("Nobody is listening", self.say(h.path, "x").stderr)
        self.assertEqual(self.say(os.path.join(self.tmp, "none.sock"), "x").returncode, 4, "no bus")
        h.sub("goal")
        self.assertEqual(self.say(h.path, "\u200b").returncode, 2, "nothing to say")


if __name__ == "__main__":
    unittest.main()
