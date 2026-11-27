"""What the soak test (tests/e2e/soak_v1.py) asks of the voice service: a burst of recordings must not start a recognizer process for each (each loads the model);
at most MAX_PARALLEL run, the others wait their turn and, when no place frees in QUEUE_WAIT seconds, get a short fixed "busy" answer.
No Whisper, no network. Run with: python3 -W error tests/fast/test_voice_soak.py
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import voice_support  # noqa: E402,F401  (puts the library on the path)
from voice_support import wav_with  # noqa: E402

from swarmbox_voice import config as vconfig  # noqa: E402
from swarmbox_voice import server  # noqa: E402


class Burst(unittest.TestCase):
    def service(self, transcribe, published):
        return server.Service(vconfig.load({}), transcribe=transcribe, publish=lambda text: published.append(text) or "sent", log=lambda m: None)

    def test_at_most_max_parallel_recognizers_run_at_once_and_every_recording_is_served(self):
        running, peak, lock, published = [0], [0], threading.Lock(), []

        def transcribe(path, language, model, vocabulary):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.01)
            with lock:
                running[0] -= 1
            return "heard it"
        svc = self.service(transcribe, published)
        out = []
        threads = [threading.Thread(target=lambda: out.append(svc.audio(wav_with("hello there")))) for _ in range(9)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(out), 9)
        self.assertEqual(peak[0], server.MAX_PARALLEL, "never more recognizers than places")
        self.assertTrue(all(st == 200 and body["state"] == "sent" for st, body in out), out)
        self.assertEqual(len(published), 9)

    def test_a_recording_that_waits_too_long_gets_a_fixed_busy_answer_and_the_places_come_back(self):
        old = server.QUEUE_WAIT
        server.QUEUE_WAIT = 0.05
        self.addCleanup(setattr, server, "QUEUE_WAIT", old)
        release = threading.Event()
        all_entered = threading.Event()
        entered, lock = [0], threading.Lock()
        published = []

        def transcribe(path, language, model, vocabulary):
            with lock:
                entered[0] += 1
                if entered[0] >= server.MAX_PARALLEL:
                    all_entered.set()
            release.wait(20)
            return "late"
        svc = self.service(transcribe, published)
        holders = [threading.Thread(target=lambda: svc.audio(wav_with("hello there")), daemon=True) for _ in range(server.MAX_PARALLEL)]
        for t in holders:
            t.start()
        self.assertTrue(all_entered.wait(10))
        with self.assertRaises(server.HttpError) as cm:
            svc.audio(wav_with("one more"))
        e = cm.exception
        self.assertEqual((e.status, e.code), (503, "stt_busy"))
        self.assertEqual(e.message, "The speech recognizer is busy: try again in a moment.")
        self.assertNotIn("one more", e.message)
        release.set()
        for t in holders:
            t.join(10)
        status, body = svc.audio(wav_with("after it freed"))
        self.assertEqual((status, body["state"]), (200, "sent"), "the places were given back")
        self.assertEqual(published, ["late", "late", "late"])

    def test_a_recognizer_that_fails_gives_its_place_back(self):
        calls = []

        def transcribe(path, language, model, vocabulary):
            calls.append(1)
            raise server.stt.SttError("failed", "boom")
        svc = self.service(transcribe, [])
        for _ in range(server.MAX_PARALLEL * 3):
            with self.assertRaises(server.HttpError):
                svc.audio(wav_with("hello there"))
        self.assertEqual(len(calls), server.MAX_PARALLEL * 3, "no place was lost to a failure")


class TwoSigterms(unittest.TestCase):
    """found by the soak test: the front sends SIGTERM and the kernel sends another when the front exits (--die-with-parent); the second one raised
    KeyboardInterrupt in the middle of the shutdown, a traceback in web-terminal.log"""

    def test_the_handler_ends_the_service_once_and_ignores_the_next_sigterm(self):
        import signal
        from unittest import mock
        from swarmbox_voice import __main__ as vmain
        with mock.patch.object(vmain.signal, "signal") as sig:
            with self.assertRaises(KeyboardInterrupt):
                vmain._on_term()
        sig.assert_called_once_with(signal.SIGTERM, signal.SIG_IGN)

    def test_two_sigterms_in_a_row_leave_no_traceback(self):
        import concurrent.futures
        import signal
        import socket
        import subprocess

        def one(i):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()
            env = dict(os.environ, PYTHONPATH=os.path.join(voice_support.VOICE, "lib"), SWARMBOX_VOICE_LANGUAGE="en")
            p = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_voice", "serve", "--listen", "127.0.0.1:%d" % port], env=env, stderr=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)
            try:
                for _ in range(2000):
                    try:
                        socket.create_connection(("127.0.0.1", port), 0.1).close()
                        break
                    except OSError:
                        time.sleep(0.005)
                time.sleep(0.02)                     # the handler is installed right after make_server() binds the port
                p.send_signal(signal.SIGTERM)
                time.sleep(0.001 * i)
                try:
                    p.send_signal(signal.SIGTERM)
                except OSError:
                    pass
                _, err = p.communicate(timeout=20)
                rc = p.returncode
            finally:
                if p.poll() is None:
                    p.kill()
                    p.communicate()
            return i, rc, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(one, range(4)))    # a few races between the two signals (the handler itself is tested above)
        for i, rc, err in results:
            self.assertNotIn("Traceback", err, "run %d: %s" % (i, err))
            self.assertEqual(rc, 0, "run %d: exit %s" % (i, rc))


if __name__ == "__main__":
    unittest.main()
