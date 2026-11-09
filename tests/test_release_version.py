"""Dev/release-version.sh maps a release tag to the image tags.

v2.0.0 gives version 2.0.0, minor 2.0 and the tags "2.0.0 2.0 latest". Anything else is refused with exit 1: no leading v,
a prerelease or build suffix, leading zeros, a missing or extra component, an empty value, option-like input. No network.
Run: python3 tests/test_release_version.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "release-version.sh")


def run(*args, shell="sh"):
    return subprocess.run([shell, SCRIPT, *args], capture_output=True, text=True, timeout=20)


def parse(out):
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


class Accepts(unittest.TestCase):
    def test_v2_0_0(self):
        r = run("v2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(parse(r.stdout), {"version": "2.0.0", "minor": "2.0", "tags": "2.0.0 2.0 latest"})

    def test_other_valid_tags(self):
        for tag, ver, minor in (("v0.0.1", "0.0.1", "0.0"), ("v10.20.30", "10.20.30", "10.20"), ("v2.10.0", "2.10.0", "2.10")):
            r = run(tag)
            self.assertEqual(r.returncode, 0, tag + r.stderr)
            d = parse(r.stdout)
            self.assertEqual((d["version"], d["minor"], d["tags"]), (ver, minor, "%s %s latest" % (ver, minor)))

    def test_same_output_in_dash_and_bash(self):
        outs = {sh: run("v2.0.0", shell=sh).stdout for sh in ("sh", "bash", "dash")}
        self.assertEqual(len(set(outs.values())), 1, outs)

    def test_stdout_is_only_key_value_lines(self):
        for line in run("v2.0.0").stdout.splitlines():
            self.assertRegex(line, r"^[a-z]+=[0-9a-z. ]+$")


class Rejects(unittest.TestCase):
    BAD = ["2.0.0", "v2.0", "v2", "v2.0.0.1", "v2.0.0-rc.1", "v2.0.0-rc1", "v2.0.0+build", "v02.0.0", "v2.00.0", "v2.0.00",
           "V2.0.0", "v2.0.x", "v-1.0.0", "v2.0.0 ", " v2.0.0", "", "refs/tags/v2.0.0", "v2.0.0\nv3.0.0", "vv2.0.0",
           "-v2.0.0", "--help", "v2.0.0;echo", "v2.0.$(id)"]

    def test_each_is_refused_with_exit_1_and_no_output_on_stdout(self):
        for tag in self.BAD:
            r = run(tag)
            self.assertEqual(r.returncode, 1, repr(tag))
            self.assertEqual(r.stdout, "", repr(tag))
            self.assertIn("release-version:", r.stderr, repr(tag))

    def test_prerelease_message_says_why(self):
        self.assertIn("prerelease", run("v2.0.0-rc.1").stderr)

    def test_usage_errors_exit_64(self):
        self.assertEqual(run().returncode, 64)
        self.assertEqual(run("v2.0.0", "v2.0.1").returncode, 64)


if __name__ == "__main__":
    unittest.main()
