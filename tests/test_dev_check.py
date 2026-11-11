"""The local gate: dev/check.sh (the checks of ci.yml that run on this machine) and the pre-push hook that calls it.

The hook is run with a stub in place of check.sh (SWARMBOX_CHECK_CMD), fed the lines Git gives a pre-push hook on standard input. The
real check.sh is only asked what it would run (--print-shellcheck) and run with nothing to do: its shellcheck and test parts are the
very things CI runs, and run_all.sh must not run itself from inside a test.
Run with: python3 tests/test_dev_check.py
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

CHECK = os.path.join(ROOT, "dev", "check.sh")
HOOK = os.path.join(ROOT, "dev", "hooks", "pre-push")
CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")
ZERO = "0" * 40
SHA = "1" * 40


class CheckScriptTest(unittest.TestCase):
    def test_both_scripts_parse_and_the_hook_is_executable(self):
        for p in (CHECK, HOOK):
            self.assertEqual(subprocess.run(["sh", "-n", p], capture_output=True, text=True).returncode, 0, p)
        self.assertTrue(os.stat(HOOK).st_mode & stat.S_IXUSR, "git runs the hook as a program")

    def test_the_shellcheck_lines_are_the_ones_of_ci_yml_and_every_file_exists(self):
        r = subprocess.run(["sh", CHECK, "--print-shellcheck"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        with open(CI) as f:
            ci = [ln.strip() for ln in f if re.match(r"\s+shellcheck -s (sh|bash) ", ln)]
        self.assertEqual(lines, ci)
        self.assertEqual(len(lines), 2, "one line for sh and one for bash")
        for line in lines:
            for name in line.split()[3:]:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, name)), "%s is in ci.yml but missing" % name)

    def test_the_gate_and_its_hook_are_linted_by_ci_too(self):
        r = subprocess.run(["sh", CHECK, "--print-shellcheck"], capture_output=True, text=True)
        files = " ".join(r.stdout.splitlines())
        for name in ("dev/check.sh", "dev/hooks/pre-push"):
            self.assertIn(name, files)

    def test_with_nothing_to_do_it_is_ok_and_a_bad_option_is_refused(self):
        r = subprocess.run(["sh", CHECK, "--no-tests", "--no-shellcheck"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip().splitlines()[-1]), (0, "CHECK OK"), r.stdout + r.stderr)
        r = subprocess.run(["sh", CHECK, "--nonsense"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-hook.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "calls")
        self.stub = os.path.join(self.tmp, "stub")
        with open(self.stub, "w") as f:
            f.write('#!/bin/sh\necho "ran${1:+ $*}" >> "%s"\nexit "${STUB_RC:-0}"\n' % self.log)
        os.chmod(self.stub, 0o755)

    def push(self, *refs, **env):
        """The hook as Git runs it: one line per ref on standard input. refs are (local sha, remote ref) pairs."""
        stdin = "".join("refs/heads/x %s %s %s\n" % (sha, rref, ZERO) for sha, rref in refs)
        e = dict(os.environ, SWARMBOX_CHECK_CMD=self.stub)
        e.pop("SWARMBOX_SKIP_CHECK", None)
        e.update(env)
        r = subprocess.run(["sh", HOOK, "origin", "git@example.com:x/y.git"], input=stdin, env=e, capture_output=True, text=True, cwd=ROOT)
        calls = open(self.log).read().splitlines() if os.path.exists(self.log) else []
        return r, calls

    def test_a_push_of_main_runs_the_check_without_the_release_part(self):
        r, calls = self.push((SHA, "refs/heads/main"))
        self.assertEqual((r.returncode, calls), (0, ["ran"]), r.stderr)

    def test_a_push_of_a_release_tag_runs_the_check_with_the_release_part(self):
        r, calls = self.push((SHA, "refs/tags/v2.0.6"))
        self.assertEqual((r.returncode, calls), (0, ["ran --release"]), r.stderr)

    def test_a_branch_other_than_main_a_tag_that_is_not_a_release_and_a_deletion_run_nothing(self):
        for refs in ([(SHA, "refs/heads/feature")], [(SHA, "refs/tags/notes")], [(ZERO, "refs/heads/main")], [(ZERO, "refs/tags/v1.0.0")]):
            r, calls = self.push(*refs)
            self.assertEqual((r.returncode, calls), (0, []), refs)

    def test_a_failing_check_stops_the_push_and_says_how_to_skip_once(self):
        r, calls = self.push((SHA, "refs/heads/main"), STUB_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(calls, ["ran"])
        self.assertIn("--no-verify", r.stderr)

    def test_skip_check_runs_nothing_and_says_so(self):
        r, calls = self.push((SHA, "refs/heads/main"), SWARMBOX_SKIP_CHECK="1")
        self.assertEqual((r.returncode, calls), (0, []))
        self.assertIn("skipped", r.stderr)

    def test_a_push_with_main_and_a_tag_together_runs_the_check_once_with_the_release_part(self):
        r, calls = self.push((SHA, "refs/heads/main"), (SHA, "refs/tags/v2.0.6"))
        self.assertEqual(calls, ["ran --release"], r.stderr)


class ContributingTest(unittest.TestCase):
    def test_contributing_tells_how_to_turn_the_gate_on(self):
        with open(os.path.join(ROOT, "CONTRIBUTING.md")) as f:
            text = f.read()
        self.assertIn("git config core.hooksPath dev/hooks", text)
        self.assertIn("dev/check.sh", text)


if __name__ == "__main__":
    unittest.main()
