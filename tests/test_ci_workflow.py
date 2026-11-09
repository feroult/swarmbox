"""Guards for .github/workflows/ci.yml (it cannot run here, so a few text checks keep it honest). No YAML parser needed.
Run: python3 tests/test_ci_workflow.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")
TEXT = open(CI, encoding="utf-8").read()


def job(name):
    """The text of one top-level job (from `  name:` to the next job)."""
    m = re.search(r"(?ms)^  %s:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)" % re.escape(name), TEXT)
    assert m, name
    return m.group(1)


class Ci(unittest.TestCase):
    def test_triggers_and_read_only_permissions(self):
        for needle in ("push:", "pull_request:", "schedule:", "workflow_dispatch:", "permissions:\n  contents: read"):
            self.assertIn(needle, TEXT)
        self.assertNotIn("\t", TEXT)

    def test_nothing_is_published_and_no_secret_or_port_is_used(self):
        self.assertNotIn("secrets.", TEXT)
        for bad in ("podman push", "docker push", "podman login", "gh release", "--publish", "ports:", "0.0.0.0"):
            self.assertNotIn(bad, TEXT.lower())

    def test_actions_are_pinned(self):
        uses = re.findall(r"uses:\s*(\S+)", TEXT)
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$")

    def test_every_job_has_a_timeout(self):
        for name in re.findall(r"(?m)^  ([a-z0-9-]+):\n    (?:name|if):", TEXT):
            self.assertIn("timeout-minutes:", job(name), name)

    def test_files_named_in_run_steps_exist(self):
        for path in set(re.findall(r"\b(?:tests|dev|container)/[A-Za-z0-9_./-]+\.(?:py|sh)\b", TEXT)):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)

    def test_linux_job_runs_the_whole_suite_through_run_all(self):
        self.assertIn("sh tests/run_all.sh", job("linux"))

    def test_macos_runs_the_script_and_installer_tests_in_the_system_sh(self):
        mac = job("macos")
        self.assertIn("/bin/sh -c", mac)
        self.assertIn("BASH_VERSINFO[0]", mac)
        self.assertIn("tests/test_swarmbox_command.py", mac)
        self.assertIn("tests/test_install.py", mac)

    def test_slow_jobs_run_only_on_schedule_or_by_hand(self):
        for name in ("browser", "real-tools"):
            self.assertIn("github.event_name == 'schedule'", job(name), name)

    def test_smoke_jobs_run_the_full_smoke_test_and_reject_skips(self):
        for name in ("smoke", "arm64"):
            body = job(name)
            self.assertIn("SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py", body)
            self.assertIn("grep -q ' SKIP '", body)

    def test_actionlint_when_available(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), CI], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
