#!/usr/bin/env python3
"""start.sh against the shared FakePodman of helpers.py (the first user of it outside test_helpers.py).

Run:  python3 tests/test_start_fake_podman.py

Only paths that need no container: a fresh create (image present, no container) and a rebuild when the image is
missing. HOME and the workspace are temp folders; a real podman is never reached.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

from helpers import ROOT, FakePodman

START = os.path.join(ROOT, "start.sh")


class StartWithFakePodman(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sbfp")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        os.makedirs(os.path.join(self.work, ".work", ".swarmbox"))
        open(os.path.join(self.work, ".work", ".swarmbox", "podman.sock"), "w").close()

    def start(self, fp, *args):
        env = fp.env(HOME=self.work, SWARMBOX_INIT="0")
        r = subprocess.run(["bash", START, "--no-shell", *args], cwd=self.work, env=env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_creates_a_container_when_none_exists(self):
        with FakePodman({"images": {"stdout": "img1\n"}}) as fp:
            self.start(fp, "--name", "swarmbox-test-fp", "--hostname", "h h")
            runs = [c for c in fp.calls() if c[0] == "run"]
            self.assertEqual(len(runs), 1, fp.calls())
            run = runs[0]
            self.assertIn("swarmbox-test-fp", run)
            self.assertEqual(run[run.index("--hostname") + 1], "h h")  # a space survives intact
            self.assertNotIn("build", [c[0] for c in fp.calls()])

    def test_builds_the_image_when_it_is_missing(self):
        with FakePodman() as fp:  # "images -q" prints nothing: the image is missing
            self.start(fp)
            builds = [c for c in fp.calls() if c[0] == "build"]
            self.assertEqual(len(builds), 1, fp.calls())
            self.assertIn("-t", builds[0])

    def test_an_existing_container_is_started_not_recreated(self):
        with FakePodman({"images": {"stdout": "img1\n"}, "ps": {"stdout": "cid1\n"}}) as fp:
            self.start(fp)
            names = [c[0] for c in fp.calls()]
            self.assertIn("start", names)
            self.assertNotIn("run", [c[0] for c in fp.calls() if "--rm" not in c])


if __name__ == "__main__":
    unittest.main()
