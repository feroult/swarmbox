"""Guards for .github/workflows/release.yml (it cannot run here, so a few text checks keep the safety rules). No YAML parser.
Run: python3 tests/test_release_workflow.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

REL = os.path.join(ROOT, ".github", "workflows", "release.yml")
CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")
with open(REL, encoding="utf-8") as fh:
    TEXT = fh.read()
PUBLISH_RE = r"needs\.version\.outputs\.publish == 'true'"
PUSHERS = (r"\bpodman push\b", r"\blogin\b", r"imagetools create", r"cosign (sign|attest)", r"gh release", r"upload")


def jobs():
    """{name: text} of the top-level jobs."""
    body = TEXT[TEXT.index("\njobs:\n"):]
    parts = re.split(r"(?m)^  ([a-z0-9-]+):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


class Release(unittest.TestCase):
    def test_tag_trigger_and_a_dry_run_that_defaults_to_true(self):
        self.assertRegex(TEXT, r"push:\n\s+tags:\n\s+- ?\"?v\*\.\*\.\*")
        self.assertNotIn("pull_request", TEXT)
        self.assertRegex(TEXT, r"dry-run:(?:\n\s+\S.*)*?\n\s+default: ?(true|\"true\")")

    def test_publish_needs_a_tag_ref_and_dry_run_false(self):
        step = jobs()["version"]
        for needle in ("ref_type", "dry-run", "publish=false", "publish=true"):
            self.assertIn(needle, step)

    def test_every_pushing_signing_or_releasing_step_is_gated_on_publish(self):
        n = 0
        for name, body in jobs().items():
            head, _, steps = body.partition("    steps:")
            job_gated = bool(re.search(PUBLISH_RE, head))
            for step in re.split(r"(?m)^      - ", steps)[1:]:
                if "id: pub" in step:
                    continue
                if any(re.search(p, step) for p in PUSHERS):
                    n += 1
                    self.assertTrue(job_gated or re.search(PUBLISH_RE, step), "%s: %s" % (name, step[:60]))
        self.assertGreaterEqual(n, 6)

    def test_permissions_are_read_only_except_where_needed(self):
        self.assertRegex(TEXT, r"(?m)^permissions:\n  contents: read\n")
        holders = [n for n, b in jobs().items() if "id-token: write" in b]
        self.assertEqual(holders, ["sign"])

    def test_nothing_but_the_owner_registry_and_no_secrets(self):
        self.assertNotIn("secrets.", TEXT)
        for bad in ("docker.io", "quay.io", "docker/login-action", "0.0.0.0"):
            self.assertNotIn(bad, TEXT)
        for m in re.findall(r"ghcr\.io/[\w./-]+", TEXT):
            self.assertTrue(m.startswith("ghcr.io/feroult/"), m)

    def test_the_scan_fails_on_high_before_any_push(self):
        build = jobs()["build"]
        self.assertRegex(build, r"anchore/scan-action@")
        self.assertRegex(build, r"fail-build: ?\"?true")
        self.assertRegex(build, r"severity-cutoff: ?\"?high")
        self.assertLess(build.index("anchore/scan-action@"), build.index("podman push"))

    def test_sign_signs_the_digest_not_a_tag_and_verifies(self):
        sign = jobs()["sign"]
        self.assertRegex(sign, r'cosign sign --yes "?\$\{?REGISTRY_IMAGE\}?@\$\{?DIGEST\}?"?')
        self.assertRegex(sign, r"cosign attest --yes .*--type spdxjson")
        self.assertIn("cosign verify", sign)
        self.assertIn("--certificate-oidc-issuer https://token.actions.githubusercontent.com", sign)

    def test_actions_are_pinned_by_an_exact_version(self):
        uses = [u for u in re.findall(r"uses:\s*(\S+)", TEXT) if not u.startswith("./")]   # ./ is the ci.yml workflow call
        self.assertGreaterEqual(len(uses), 6)
        for u in uses:
            self.assertRegex(u, r"^[\w.-]+/[\w./-]+@v\d+\.\d+\.\d+$")

    def test_actionlint_when_available(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), REL, CI], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
