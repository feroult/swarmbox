"""dev/local-watch.sh: host watchdog that triggers dev/local-up.sh --yes when a token file appears.

Uses a fake local-up.sh in a temporary directory, so nothing is built or reset.
Run: python3 tests/fast/test_local_watch.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "local-watch.sh")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class LocalWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="local-watch-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.trigger = os.path.join(self.tmp, "work", "local-reload")
        self.calls_log = os.path.join(self.tmp, "calls.log")
        self.fake_local_up = os.path.join(self.tmp, "fake-local-up.sh")
        self.write_fake_local_up(exit_code=0, body='echo "fake-out: $*"')

    def write_fake_local_up(self, exit_code=0, body=""):
        script = (
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> "{self.calls_log}"\n'
            f"{body}\n"
            f"exit {exit_code}\n"
        )
        with open(self.fake_local_up, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(self.fake_local_up, stat.S_IRWXU)

    def run_script(self, *args, containerenv=None, extra_env=None):
        env = os.environ.copy()
        env["SWARMBOX_LOCAL_UP"] = self.fake_local_up
        env["SWARMBOX_WATCH_FILE"] = self.trigger
        env["SWARMBOX_TEST_CONTAINERENV"] = containerenv or os.path.join(self.tmp, "no-containerenv")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["sh", SCRIPT] + list(args),
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=15,
        )

    def calls(self):
        if not os.path.exists(self.calls_log):
            return []
        return read(self.calls_log).splitlines()

    def test_it_is_posix_sh(self):
        with open(SCRIPT, encoding="utf-8") as f:
            self.assertTrue(f.readline().startswith("#!/bin/sh"))

    def test_trigger_and_watch_once_runs_local_up_yes_and_consumes_file(self):
        # Trigger works even inside a box
        marker = os.path.join(self.tmp, "containerenv")
        open(marker, "w", encoding="utf-8").close()

        t = self.run_script("--trigger", containerenv=marker)
        self.assertEqual(t.returncode, 0, t.stderr + t.stdout)
        self.assertTrue(os.path.exists(self.trigger))

        # Watchdog runs on the host and consumes the trigger file
        w = self.run_script("--once", "--interval", "0.1")
        self.assertEqual(w.returncode, 0, w.stderr + w.stdout)
        self.assertFalse(os.path.exists(self.trigger))
        self.assertEqual(self.calls(), ["--yes"])
        self.assertIn("status: ok", read(self.trigger + ".status"))
        self.assertIn("fake-out: --yes", read(self.trigger + ".log"))

    def test_trigger_forwards_only_allowlisted_flags(self):
        os.makedirs(os.path.dirname(self.trigger), exist_ok=True)
        with open(self.trigger, "w", encoding="utf-8") as f:
            f.write("--no-cache\n--evil-flag $(rm -rf /)\n# comment\n--dry-run\n")

        w = self.run_script("--once", "--interval", "0.1")
        self.assertEqual(w.returncode, 0, w.stderr + w.stdout)
        self.assertEqual(self.calls(), ["--yes --no-cache --dry-run"])
        self.assertIn("ignoring disallowed trigger token", w.stderr)

    def test_failed_build_removes_trigger_and_records_failure(self):
        self.write_fake_local_up(exit_code=1, body='echo "build broke" >&2')
        self.run_script("--trigger")
        w = self.run_script("--once", "--interval", "0.1")
        self.assertEqual(w.returncode, 1)
        self.assertFalse(os.path.exists(self.trigger), "trigger must be removed even on failure")
        status = read(self.trigger + ".status")
        self.assertIn("status: failed", status)
        self.assertIn("exit: 1", status)
        self.assertIn("build broke", read(self.trigger + ".log"))

    def test_watch_refuses_to_run_inside_a_box(self):
        marker = os.path.join(self.tmp, "containerenv")
        open(marker, "w", encoding="utf-8").close()
        r = self.run_script("--once", containerenv=marker)
        self.assertEqual(r.returncode, 2)
        self.assertIn("host", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_status_reports_pending_and_last_result(self):
        s0 = self.run_script("--status")
        self.assertEqual(s0.returncode, 0, s0.stderr)
        self.assertIn("pending: no", s0.stdout)
        self.assertIn("last: none", s0.stdout)

        self.run_script("--trigger", "--no-cache")
        s1 = self.run_script("--status")
        self.assertIn("pending: yes", s1.stdout)

        self.run_script("--once", "--interval", "0.1")
        self.assertEqual(self.calls(), ["--yes --no-cache"])
        s2 = self.run_script("--status")
        self.assertIn("pending: no", s2.stdout)
        self.assertIn("status: ok", s2.stdout)

    def test_unknown_option_and_bad_interval_are_refused(self):
        r1 = self.run_script("--nope")
        self.assertEqual(r1.returncode, 2)
        r2 = self.run_script("--interval", "abc")
        self.assertEqual(r2.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
