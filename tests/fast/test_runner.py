"""The test runner tests/run.sh (a front end of tests/support/runner.py).

The runner runs every selected test file as `python3 [-W error] file` under tests/support/reap_run.py, reads the count of tests from the
unittest summary and prints one line per file ("<file> <status> <ran> tests, <skipped> skipped, <s> s") and a total. The selectors
are the folders tests/fast, tests/slow and tests/e2e, and the macos list. These tests run it on a few small files only; they never run
a whole suite from inside the suite.
Run: python3 tests/fast/test_runner.py
"""
import os
import re
import subprocess
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

RUNNER = os.path.join(ROOT, "tests", "run.sh")
TESTS = os.path.join(ROOT, "tests")


def run(*args, env=None):
    return subprocess.run(["sh", RUNNER, *args], capture_output=True, text=True, cwd=ROOT, timeout=300, env=env)


def on_disk(layer):
    return sorted("%s/%s" % (layer, f) for f in os.listdir(os.path.join(TESTS, layer)) if re.match(r"test_.*\.py$", f))


def fake_tests(files):
    """A tests folder of its own (SWARMBOX_TESTS_DIR) with the given fast files; returns (folder, env)."""
    tmp = tempfile.mkdtemp(prefix="swarmbox-test-runner.")
    os.mkdir(os.path.join(tmp, "fast"))
    for name, body in files.items():
        with open(os.path.join(tmp, "fast", name), "w") as f:
            f.write(body)
    return tmp, dict(os.environ, SWARMBOX_TESTS_DIR=tmp)


GOOD = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\nunittest.main()\n"
BAD = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\nunittest.main()\n"


class Runner(unittest.TestCase):
    def test_is_posix_sh_and_selectors_list_their_folders(self):
        with open(RUNNER) as f:
            self.assertEqual(f.readline().rstrip("\n"), "#!/bin/sh")
        for sel, want in (("fast", on_disk("fast")), ("slow", on_disk("slow")), ("all", on_disk("fast") + on_disk("slow"))):
            p = run(sel, "--list")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout.split(), want, sel)
        self.assertEqual(run("--list").stdout.split(), on_disk("fast"), "fast is the default")
        e2e = run("e2e", "--list").stdout.split()
        self.assertTrue(e2e and all(x.startswith("e2e/") for x in e2e), e2e)
        self.assertFalse([x for x in run("all", "--list").stdout.split() if x.startswith("e2e/")], "the e2e harnesses are never part of all")

    def test_the_macos_list_names_fast_files_only(self):
        p = run("macos", "--list")
        self.assertEqual(p.returncode, 0, p.stderr)
        listed = p.stdout.split()
        self.assertGreater(len(listed), 10)
        self.assertTrue(set(listed) <= set(on_disk("fast")), set(listed) - set(on_disk("fast")))

    def test_only_runs_the_named_files_an_unknown_name_is_an_error_and_repeat_runs_each_n_times(self):
        tmp, env = fake_tests({"test_good.py": GOOD, "test_other.py": GOOD})
        self.addCleanup(shutil.rmtree, tmp, True)
        p = run("--only", "test_good.py,test_probe_missing.py", env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("test_probe_missing.py", p.stderr)
        p = run("--only", "test_good.py", "--werror", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_good\.py OK \d+ tests, \d+ skipped, [\d.]+ s$")
        self.assertRegex(p.stdout, r"(?m)^TOTAL 1 files, (\d+) tests, 0 failed files")
        self.assertIn("slowest files:", p.stdout)
        self.assertNotIn("test_other.py", p.stdout)
        self.assertEqual(run("slow", "--only", "test_good.py", env=env).returncode, 2, "test_good.py is not a slow test")
        p = run("--only", "test_good.py", "--repeat", "2", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(re.findall(r"(?m)^test_good\.py OK", p.stdout)), 2)
        self.assertIn("TOTAL 2 runs", p.stdout)

    def test_a_failing_file_makes_the_runner_fail_and_files_run_in_parallel(self):
        tmp, env = fake_tests({"test_bad.py": BAD, "test_good.py": GOOD})
        self.addCleanup(shutil.rmtree, tmp, True)
        for j in ("1", "2"):
            p = run("-j", j, env=env)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertRegex(p.stdout, r"(?m)^test_bad\.py FAIL")
            self.assertRegex(p.stdout, r"(?m)^test_good\.py OK 1 tests")
            self.assertRegex(p.stdout, r"TOTAL 2 files, 2 tests, 1 failed files")
        p = run("--github", env=env)
        self.assertIn("::error title=test_bad.py failed::", p.stdout)

    def test_a_file_over_its_time_limit_is_killed_and_reported(self):
        tmp, env = fake_tests({"test_hang.py": "import time\ntime.sleep(60)\n"})
        self.addCleanup(shutil.rmtree, tmp, True)
        p = run("--timeout", "1", env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_hang\.py FAIL")
        self.assertIn("time limit", p.stdout)

    @unittest.skipUnless(sys.platform.startswith("linux"), "reap_run adopts orphans with a Linux child subreaper (prctl)")
    def test_orphans_left_by_a_file_are_killed_and_counted(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-runner.")
        self.addCleanup(shutil.rmtree, tmp, True)
        pidfile = os.path.join(tmp, "pid")
        leak = ("import subprocess, unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                "        p = subprocess.Popen(['sleep', '60'], start_new_session=True)\n"
                "        open(%r, 'w').write(str(p.pid))\nunittest.main()\n" % pidfile)
        folder, env = fake_tests({"test_leak.py": leak})
        self.addCleanup(shutil.rmtree, folder, True)
        p = run(env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_leak\.py OK 1 tests, 0 skipped, [\d.]+ s, reaped 1$")
        with open(pidfile) as f:
            pid = int(f.read())
        self.addCleanup(lambda: os.path.exists("/proc/%d" % pid) and os.kill(pid, 9))
        self.assertFalse(os.path.exists("/proc/%d" % pid) and "sleep" in open("/proc/%d/cmdline" % pid).read())

    def test_usage_errors_exit_2_and_the_runner_starts_nothing_dangerous(self):
        for args in (["--nonsense"], ["--repeat", "0"], ["-j", "x"], ["--only"]):
            self.assertEqual(run(*args).returncode, 2, args)
        with open(os.path.join(TESTS, "support", "runner.py")) as f:
            src = f.read()
        for bad in ("pkill", "killall", "kill-server", "podman system", "rm -rf /", "--all"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
