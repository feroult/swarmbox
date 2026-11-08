"""Slice 3.7: tests/run_all.sh, the full-regression runner (design 13.4, plan 1.3).

The runner runs every tests/test_*.py as `python3 [-W error] tests/test_x.py`, reads the count of tests from the unittest
summary and prints one line per file ("<file> <status> <ran> tests, <skipped> skipped") and a total. The browser tests
(the scheduled-only files) are left out unless --browser is given. These tests run it on a few small files only; they never run
the whole suite from inside the suite.
Run: python3 tests/test_run_all.py
"""
import os
import re
import subprocess
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

RUNNER = os.path.join(ROOT, "tests", "run_all.sh")


def run(*args, env=None):
    return subprocess.run(["sh", RUNNER, *args], capture_output=True, text=True, cwd=ROOT, timeout=300, env=env)


class RunAll(unittest.TestCase):
    def test_exists_and_is_posix_sh(self):
        self.assertTrue(os.path.isfile(RUNNER))
        with open(RUNNER) as f:
            first = f.readline().rstrip("\n")
        self.assertEqual(first, "#!/bin/sh")

    def test_list_names_every_test_file_but_not_the_browser_ones(self):
        p = run("--list")
        self.assertEqual(p.returncode, 0, p.stderr)
        listed = p.stdout.split()
        disk = sorted(f for f in os.listdir(os.path.join(ROOT, "tests")) if re.match(r"test_.*\.py$", f))
        browser = {"test_clipboard_bridge.py", "test_web_style.py", "test_tmux_browser_keys.py"}
        self.assertEqual(listed, [f for f in disk if f not in browser])
        p = run("--list", "--browser")
        self.assertEqual(p.stdout.split(), disk)

    def test_runs_selected_files_and_prints_counts(self):
        p = run("--only", "test_dirs.py,test_run_all_probe_missing.py")
        # the missing name is an error, not a silent skip
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("test_run_all_probe_missing.py", p.stderr + p.stdout)
        p = run("--only", "test_dirs.py", "--werror")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        m = re.search(r"^test_dirs\.py\s+OK\s+(\d+) tests, (\d+) skipped$", p.stdout, re.M)
        self.assertTrue(m, p.stdout)
        self.assertGreaterEqual(int(m.group(1)), 13)
        self.assertRegex(p.stdout, r"(?m)^TOTAL 1 files, (\d+) tests, 0 failed files")

    def test_repeat_runs_each_file_n_times(self):
        p = run("--only", "test_dirs.py", "--repeat", "2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(re.findall(r"(?m)^test_dirs\.py\s+OK", p.stdout)), 2)
        self.assertRegex(p.stdout, r"TOTAL 2 runs")

    def test_a_failing_file_makes_the_runner_fail(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-runall.")
        self.addCleanup(shutil.rmtree, tmp, True)
        d = os.path.join(tmp, "tests")
        os.mkdir(d)
        with open(os.path.join(d, "test_bad.py"), "w") as f:
            f.write("import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\nunittest.main()\n")
        with open(os.path.join(d, "test_good.py"), "w") as f:
            f.write("import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\nunittest.main()\n")
        env = dict(os.environ, SWARMBOX_TESTS_DIR=d)
        p = run("--only", "test_bad.py,test_good.py", env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_bad\.py\s+FAIL")
        self.assertRegex(p.stdout, r"(?m)^test_good\.py\s+OK\s+1 tests")
        self.assertRegex(p.stdout, r"TOTAL 2 files, 2 tests, 1 failed files")

    def test_does_not_start_anything_dangerous(self):
        with open(RUNNER) as f:
            src = f.read()
        for bad in ("pkill", "killall", "kill-server", "podman system", "rm -rf /", "--all"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
