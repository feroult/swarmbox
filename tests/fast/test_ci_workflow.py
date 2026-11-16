"""Guards for .github/workflows/ci.yml (it cannot run here, so a few text checks keep it honest). No YAML parser needed.
Run: python3 tests/fast/test_ci_workflow.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
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

    def test_every_step_has_a_run_or_a_uses(self):
        """GitHub refuses the whole workflow (no job starts) for a step without either; a YAML parser would not notice."""
        for wf in ("ci.yml", "release.yml"):
            text = open(os.path.join(ROOT, ".github", "workflows", wf), encoding="utf-8").read()
            blocks = re.findall(r"(?ms)^    steps:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", text)
            steps = [st for b in blocks for st in re.split(r"(?m)^      - ", b)[1:]]
            self.assertTrue(steps, wf)
            for st in steps:
                head = st.split("\n", 1)[0]
                self.assertRegex(st, r"(?m)^(?:uses|run):|^        (?:uses|run):", "%s: step '%s' has no run or uses" % (wf, head))

    def test_a_step_name_is_a_valid_plain_scalar(self):
        """`name: a: b` is a YAML error that no job survives (GitHub shows no job at all); a plain scalar has no ': ' and no ' #'."""
        for wf in ("ci.yml", "release.yml"):
            text = open(os.path.join(ROOT, ".github", "workflows", wf), encoding="utf-8").read()
            for m in re.finditer(r"(?m)^\s*(?:- )?name: (?![\"'|>])(.*)$", text):
                self.assertNotRegex(m.group(1), r": | #", "%s: the name '%s' is not valid YAML" % (wf, m.group(1)))

    def test_every_job_has_a_timeout(self):
        for name in re.findall(r"(?m)^  ([a-z0-9-]+):\n    (?:name|if):", TEXT):
            self.assertIn("timeout-minutes:", job(name), name)

    def test_files_named_in_run_steps_exist(self):
        for path in set(re.findall(r"\b(?:tests|dev|container)/[A-Za-z0-9_./-]+\.(?:py|sh)\b", TEXT)):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)

    def test_linux_job_runs_fast_and_slow_through_the_one_runner(self):
        body = job("linux")
        self.assertIn("sh tests/run.sh fast", body)
        self.assertIn("sh tests/run.sh slow", body)
        self.assertNotIn("run_all", TEXT)

    def test_macos_runs_the_macos_list_in_the_system_sh_and_names_no_file(self):
        mac = job("macos")
        self.assertIn("BASH_VERSINFO[0]", mac)
        self.assertIn("sh tests/run.sh macos", mac)
        self.assertNotIn("tests/fast/", mac, "the list of files is tests/support/macos.list, in one place")

    def test_slow_jobs_run_only_on_schedule_or_by_hand(self):
        for name in ("browser", "real-addons"):
            self.assertIn("github.event_name == 'schedule'", job(name), name)

    def test_the_real_addons_job_installs_voice_for_real_and_rejects_a_skip(self):
        body = job("real-addons")
        self.assertIn('SWARMBOX_REAL_VOICE_INSTALL: "1"', body)
        self.assertIn("python3 tests/fast/test_addon_voice.py", body)
        self.assertIn("grep -q 'skipped'", body)

    def test_the_browser_job_runs_the_slow_suite_with_the_real_tmux_gate(self):
        self.assertIn("SWARMBOX_TEST_REAL_TMUX=1 sh tests/run.sh slow", job("browser"))
        self.assertNotIn("SWARMBOX_BROWSER_TESTS", TEXT)

    def test_smoke_jobs_run_the_full_smoke_test_and_reject_skips(self):
        for name in ("smoke", "arm64"):
            body = job(name)
            self.assertIn("SWARMBOX_SMOKE_FULL=1 python3 tests/slow/smoke_image.py", body)
            self.assertIn("grep -q ' SKIP '", body)

    def test_actionlint_when_available(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), CI], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
