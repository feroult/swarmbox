"""`swarmbox-web`, the command the web supervisor of `serve` runs: `run` execs the herdr Web Studio through the backend with a UTF-8 locale,
`restart` signals the supervisor whose PID is in the run folder and refuses anything else. The voice front is test_voice_web.py.

Real programs: container/scripts/swarmbox-web.sh and the real herdr backend over a fake hc and a fake web server (the world of
test_voice_web.Base). Run with: python3 -W error tests/fast/test_web_server.py
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import test_voice_web as vw  # noqa: E402  (only its helpers: its test classes are not imported by name)


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class Run(vw.Base):
    def test_the_server_always_gets_a_utf8_locale_so_an_accent_typed_alone_is_not_dropped(self):
        vw.write_exec(self.server, '#!/bin/sh\nprintf "%s\\n" "$LANG" > "$FAKE_DIR/server.lang"\n')
        r = self.web("run", LANG="C", LC_ALL="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(vw.read(os.path.join(self.tmp, "server.lang")).strip(), "C.UTF-8")

    def test_a_herdr_core_that_does_not_answer_is_a_failure_and_no_server_starts(self):
        vw.write_exec(os.path.join(self.fake, "hc"), "#!/bin/sh\nexit 1\n")
        r = self.web("run", SWARMBOX_TEST_HC_WAIT_SLEEP="0.01")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("herdr-core server is not answering", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "server.argv")))

    def test_usage(self):
        for args in ([], ["render"], ["run", "x"]):
            r = subprocess.run(["bash", vw.WEB] + args, env=self.env(), capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 64, args)


class Restart(vw.Base):
    def start_listener(self):
        """A process of this test that records USR1; the only PID this test ever signals."""
        marker = os.path.join(self.tmp, "usr1")
        p = subprocess.Popen(["bash", "-c", 'trap "echo got >> %s" USR1; echo ready; while :; do sleep 0.05; done' % marker],
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        p.stdout.readline()
        return p, marker

    def test_restart_sends_usr1_to_the_pid_in_the_file(self):
        p, marker = self.start_listener()
        put(os.path.join(self.run_dir, "web-supervisor.pid"), "%d\n" % p.pid)
        r = self.web("restart")
        self.assertEqual(r.returncode, 0, r.stderr)
        end = time.time() + 5
        while time.time() < end and not os.path.exists(marker):
            time.sleep(0.05)
        self.assertEqual(vw.read(marker).split(), ["got"])
        self.assertIsNone(p.poll())

    def test_a_stale_garbage_or_unsafe_pid_is_refused_and_nothing_is_signalled(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        r = self.web("restart")   # no pid file at all: the supervisor is not running
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("no web terminal supervisor is running", r.stderr)
        for content in ("%d\n" % dead.pid, "abc\n", "", "0\n", "1\n", "-1\n", "12 34\n"):
            with self.subTest(content=content):
                put(os.path.join(self.run_dir, "web-supervisor.pid"), content)
                r = self.web("restart")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertTrue(r.stderr)


if __name__ == "__main__":
    unittest.main()
