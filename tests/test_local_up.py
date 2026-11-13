"""dev/local-up.sh: build the image from the checkout and switch the box to it.

Podman is a FakePodman and the swarmbox script is a fake that records its calls, so nothing is built or reset.
Run: python3 tests/test_local_up.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "local-up.sh")
TAG = "localhost/swarmbox:local"


def read(path):
    with open(path) as f:
        return f.read().strip()


class LocalUp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="local-up-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = os.path.join(self.tmp, "bin")
        self.log = os.path.join(self.tmp, "swarmbox.calls")
        # what `podman run IMAGE install` prints: an installer that writes a fake swarmbox which records what it is asked
        self.installer = ('mkdir -p "$SWARMBOX_BIN_DIR"\n'
                          'printf \'#!/bin/sh\\necho "$*" >> %s\\n\' > "$SWARMBOX_BIN_DIR/swarmbox"\n'
                          'chmod 755 "$SWARMBOX_BIN_DIR/swarmbox"\n' % self.log)
        self.version = read(os.path.join(ROOT, "container", "host", "VERSION"))
        self.series = self.version.rsplit(".", 1)[0]

    def podman(self):
        return FakePodman({"run": {"stdout": self.installer}})

    def run_script(self, fp, *args, containerenv=None, stdin=subprocess.DEVNULL):
        env = fp.env(SWARMBOX_BIN_DIR=self.bin,
                     SWARMBOX_TEST_CONTAINERENV=containerenv or os.path.join(self.tmp, "no-containerenv"))
        env.pop("SWARMBOX_LOCAL_TAG", None)
        return subprocess.run(["sh", SCRIPT] + list(args), env=env, capture_output=True, text=True, stdin=stdin)

    def swarmbox_calls(self):
        return read(self.log).splitlines() if os.path.exists(self.log) else []

    def test_it_is_posix_sh(self):
        with open(SCRIPT) as f:
            self.assertTrue(f.readline().startswith("#!/bin/sh"))

    def test_it_builds_installs_the_script_of_the_image_records_the_image_and_resets(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--yes")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            calls = fp.calls()
            build = [c for c in calls if c[0] == "build"]
            self.assertEqual(len(build), 1)
            self.assertEqual(build[0][build[0].index("-t") + 1], TAG)
            self.assertEqual(build[0][-1], ROOT, "the build context is the checkout")
            self.assertNotIn("--no-cache", build[0])
            run = [c for c in calls if c[0] == "run"]
            self.assertEqual(run, [["run", "--rm", TAG, "install", "--image", TAG]])
            # build first, then the installer
            self.assertLess(calls.index(build[0]), calls.index(run[0]))
        self.assertEqual(self.swarmbox_calls(), ["config set IMAGE " + TAG, "reset"])

    def test_the_options_reach_podman(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--yes", "--no-cache", "--with", "claude,go")
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = fp.calls()
            self.assertIn("--no-cache", [c for c in calls if c[0] == "build"][0])
            self.assertEqual([c for c in calls if c[0] == "run"],
                             [["run", "--rm", TAG, "install", "--image", TAG, "--with", "claude,go"]])

    def test_no_reset_stops_before_the_reset_and_says_how(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--no-reset")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.swarmbox_calls(), ["config set IMAGE " + TAG])
        self.assertIn("swarmbox reset", r.stdout)

    def test_without_a_terminal_and_without_yes_it_does_not_reset(self):
        with self.podman() as fp:
            r = self.run_script(fp)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.swarmbox_calls(), ["config set IMAGE " + TAG])
        self.assertIn("--yes", r.stdout)

    def test_inside_a_box_it_refuses_and_calls_nothing(self):
        marker = os.path.join(self.tmp, "containerenv")
        open(marker, "w").close()
        with self.podman() as fp:
            r = self.run_script(fp, "--yes", containerenv=marker)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(fp.calls(), [])
        self.assertIn("host", r.stderr)

    def test_a_failed_build_stops_everything(self):
        with FakePodman({"build": {"exit": 1, "stderr": "boom\n"}, "run": {"stdout": self.installer}}) as fp:
            r = self.run_script(fp, "--yes")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual([c for c in fp.calls() if c[0] == "run"], [], "no installer after a failed build")
        self.assertEqual(self.swarmbox_calls(), [])

    def test_dry_run_prints_the_commands_and_runs_none(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--dry-run", "--yes")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(fp.calls(), [])
        self.assertIn("podman build -t " + TAG, r.stdout)
        self.assertIn("config set IMAGE " + TAG, r.stdout)
        self.assertFalse(os.path.exists(self.bin))

    def test_release_goes_back_to_the_published_image_of_the_series(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--release", "--yes")
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            calls = fp.calls()
            ref = [c for c in calls if c[0] == "pull"][0][-1]
            self.assertRegex(ref, r"^[a-z0-9./-]+/swarmbox:" + self.series.replace(".", r"\.") + "$")
            self.assertEqual([c for c in calls if c[0] == "build"], [], "no build when going back")
            self.assertEqual([c for c in calls if c[0] == "run"], [["run", "--rm", ref, "install", "--image", ref]])
        self.assertEqual(self.swarmbox_calls(), ["config set IMAGE " + ref, "reset"])

    def test_an_unknown_option_is_refused(self):
        with self.podman() as fp:
            r = self.run_script(fp, "--nope")
            self.assertEqual(r.returncode, 2)
            self.assertEqual(fp.calls(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
