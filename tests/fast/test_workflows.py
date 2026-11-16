"""Guards for .github/workflows/ci.yml and release.yml. They cannot run here, so text checks keep them honest (no YAML parser; actionlint when installed).

The mistakes that cost a run on GitHub: a step with neither `run` nor `uses` or a step name with ': ' in it makes GitHub refuse the whole file (no job
starts); a file named in a step that does not exist; a job without a timeout. And the safety rules of the release: nothing is pushed, signed or released
unless the run is a real release (a tag, dry-run false); the permissions are read-only except where signing needs them; no secrets.
Run: python3 tests/fast/test_workflows.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, DEFAULT_IMAGE_REPO  # noqa: E402

WORKFLOWS = os.path.join(ROOT, ".github", "workflows")
OWNER_PREFIX = DEFAULT_IMAGE_REPO.rsplit("/", 1)[0] + "/"


def read(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return f.read()


CI, REL = read("ci.yml"), read("release.yml")
PUBLISH_RE = r"needs\.version\.outputs\.publish == 'true'"
PUSHERS = (r"\bpodman push\b", r"\blogin\b", r"imagetools create", r"cosign (sign|attest)", r"gh release", r"upload")


def jobs(text):
    """{name: text} of the top-level jobs."""
    body = text[text.index("\njobs:\n"):]
    parts = re.split(r"(?m)^  ([a-z0-9-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


class BothWorkflows(unittest.TestCase):
    def test_every_step_has_a_run_or_a_uses_and_a_name_that_is_a_valid_plain_scalar(self):
        for wf, text in (("ci.yml", CI), ("release.yml", REL)):
            blocks = re.findall(r"(?ms)^    steps:\n(.*?)(?=^  [a-z0-9-]+:\n|\Z)", text)
            steps = [st for b in blocks for st in re.split(r"(?m)^      - ", b)[1:]]
            self.assertTrue(steps, wf)
            for st in steps:
                self.assertRegex(st, r"(?m)^(?:uses|run):|^        (?:uses|run):", "%s: step '%s' has no run or uses" % (wf, st.split("\n", 1)[0]))
            # a plain scalar has no ': ' and no ' #'
            for m in re.finditer(r"(?m)^\s*(?:- )?name: (?![\"'|>])(.*)$", text):
                self.assertNotRegex(m.group(1), r": | #", "%s: the name '%s' is not valid YAML" % (wf, m.group(1)))

    def test_actions_are_pinned_and_no_secret_or_foreign_registry_is_used(self):
        for wf, text, pin in (("ci.yml", CI, r"@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$"), ("release.yml", REL, r"^[\w.-]+/[\w./-]+@v\d+\.\d+\.\d+$")):
            uses = [u for u in re.findall(r"uses:\s*(\S+)", text) if not u.startswith("./")]   # ./ is the ci.yml workflow call
            self.assertTrue(uses, wf)
            for u in uses:
                self.assertRegex(u, pin, wf)
            self.assertNotIn("secrets.", text, wf)
            self.assertNotIn("0.0.0.0", text, wf)
        for bad in ("docker.io", "quay.io", "docker/login-action"):
            self.assertNotIn(bad, REL)
        for m in re.findall(r"ghcr\.io/[\w./-]+", REL):
            self.assertTrue(m.startswith(OWNER_PREFIX), m)

    def test_actionlint_when_available(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), os.path.join(WORKFLOWS, "release.yml"), os.path.join(WORKFLOWS, "ci.yml")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Ci(unittest.TestCase):
    def job(self, name):
        return jobs(CI)[name]

    def test_triggers_read_only_permissions_and_a_timeout_on_every_job(self):
        for needle in ("push:", "pull_request:", "schedule:", "workflow_dispatch:", "permissions:\n  contents: read"):
            self.assertIn(needle, CI)
        self.assertNotIn("\t", CI)
        for name in re.findall(r"(?m)^  ([a-z0-9-]+):\n    (?:name|if):", CI):
            self.assertIn("timeout-minutes:", self.job(name), name)

    def test_nothing_is_published_and_no_port_is_opened(self):
        for bad in ("podman push", "docker push", "podman login", "gh release", "--publish", "ports:"):
            self.assertNotIn(bad, CI.lower())

    def test_files_named_in_run_steps_exist(self):
        for path in set(re.findall(r"\b(?:tests|dev|container)/[A-Za-z0-9_./-]+\.(?:py|sh)\b", CI)):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)

    def test_linux_runs_fast_and_slow_and_macos_runs_the_list_in_one_place(self):
        body = self.job("linux")
        self.assertIn("sh tests/run.sh fast", body)
        self.assertIn("sh tests/run.sh slow", body)
        mac = self.job("macos")
        self.assertIn("BASH_VERSINFO[0]", mac)
        self.assertIn("sh tests/run.sh macos", mac)
        self.assertNotIn("tests/fast/", mac, "the list of files is tests/support/macos.list, in one place")
        self.assertNotIn("run_all", CI)

    def test_the_scheduled_jobs_run_only_on_schedule_or_by_hand_and_check_what_they_exist_for(self):
        for name in ("browser", "real-addons"):
            self.assertIn("github.event_name == 'schedule'", self.job(name), name)
        body = self.job("real-addons")
        self.assertIn('SWARMBOX_REAL_VOICE_INSTALL: "1"', body)
        self.assertIn("python3 tests/fast/test_addon_voice.py", body)
        self.assertIn("grep -q 'skipped'", body, "a skipped real install is a failure")
        self.assertIn("SWARMBOX_TEST_REAL_TMUX=1 sh tests/run.sh slow", self.job("browser"))
        for name in ("smoke", "arm64"):
            body = self.job(name)
            self.assertIn("SWARMBOX_SMOKE_FULL=1 python3 tests/slow/smoke_image.py", body)
            self.assertIn("grep -q ' SKIP '", body)


class Release(unittest.TestCase):
    def test_a_tag_triggers_it_and_a_manual_run_is_a_dry_run_unless_told_otherwise(self):
        self.assertRegex(REL, r"push:\n\s+tags:\n\s+- ?\"?v\*\.\*\.\*")
        self.assertNotIn("pull_request", REL)
        self.assertRegex(REL, r"dry-run:(?:\n\s+\S.*)*?\n\s+default: ?(true|\"true\")")
        for needle in ("ref_type", "dry-run", "publish=false", "publish=true"):
            self.assertIn(needle, jobs(REL)["version"])

    def test_every_pushing_signing_or_releasing_step_is_gated_on_publish(self):
        n = 0
        for name, body in jobs(REL).items():
            head, _, steps = body.partition("    steps:")
            job_gated = bool(re.search(PUBLISH_RE, head))
            for step in re.split(r"(?m)^      - ", steps)[1:]:
                if "id: pub" in step:
                    continue
                if any(re.search(p, step) for p in PUSHERS):
                    n += 1
                    self.assertTrue(job_gated or re.search(PUBLISH_RE, step), "%s: %s" % (name, step[:60]))
        self.assertGreaterEqual(n, 6)

    def test_permissions_are_read_only_except_for_the_signing_job(self):
        self.assertRegex(REL, r"(?m)^permissions:\n  contents: read\n")
        self.assertEqual([n for n, b in jobs(REL).items() if "id-token: write" in b], ["sign"])

    def test_the_scan_fails_on_high_before_any_push_and_the_digest_is_signed_and_verified(self):
        build = jobs(REL)["build"]
        self.assertRegex(build, r"anchore/scan-action@")
        self.assertRegex(build, r"fail-build: ?\"?true")
        self.assertRegex(build, r"severity-cutoff: ?\"?high")
        self.assertLess(build.index("anchore/scan-action@"), build.index("podman push"))
        sign = jobs(REL)["sign"]
        self.assertRegex(sign, r'cosign sign --yes "?\$\{?REGISTRY_IMAGE\}?@\$\{?DIGEST\}?"?')   # the digest, not a tag
        self.assertRegex(sign, r"cosign attest --yes .*--type spdxjson")
        self.assertIn("cosign verify", sign)
        self.assertIn("--certificate-oidc-issuer https://token.actions.githubusercontent.com", sign)


if __name__ == "__main__":
    unittest.main()
