"""Slice 7.5: static checks of .github/workflows/release.yml (it cannot run here, so it is validated locally).

Same approach as tests/test_ci_workflow.py: PyYAML (importable or in a mktemp venv), a text fallback class that always runs,
and actionlint when it is on PATH or in $ACTIONLINT (else a skip that names the reduced check).
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
import test_ci_workflow as ci  # noqa: E402  (its YAML loader and helpers are reused)

REL = os.path.join(ROOT, ".github", "workflows", "release.yml")
TEXT = open(REL, encoding="utf-8").read() if os.path.exists(REL) else ""
DOC = ci.YAML.safe_load(TEXT) if ci.YAML and TEXT else None
IMAGE = "ghcr.io/feroult/swarmbox"
PUBLISH_RE = r"needs\.version\.outputs\.publish == 'true'"


def jobs():
    return DOC["jobs"]


def step_text(s):
    return str(s.get("run", "")) + " " + str(s.get("with", ""))


class FileExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(os.path.exists(REL), ".github/workflows/release.yml is missing")


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Triggers(unittest.TestCase):
    def test_tag_trigger_and_dispatch_with_dry_run(self):
        t = ci.triggers(DOC)
        self.assertEqual(t["push"], {"tags": ["v*.*.*"]})
        self.assertNotIn("branches", t["push"])
        self.assertNotIn("pull_request", t)
        d = t["workflow_dispatch"]["inputs"]
        self.assertEqual(d["dry-run"]["type"], "boolean")
        self.assertIn(d["dry-run"]["default"], (True, "true"))      # the safe default
        self.assertIn("tag", d)

    def test_publish_is_a_computed_output_of_the_version_job(self):
        out = jobs()["version"]["outputs"]
        self.assertIn("publish", out)
        run = "\n".join(l for _, l in ci.run_lines(DOC, "version"))
        self.assertIn("dev/release-version.sh", run)

    def test_publish_rule_needs_tag_ref_and_dry_run_false(self):
        step = [s for s in jobs()["version"]["steps"] if s.get("id") == "pub"]
        self.assertEqual(len(step), 1)
        txt = step[0]["run"] + str(step[0].get("env", ""))
        self.assertIn("ref_type", txt)
        self.assertIn("tag", txt)
        self.assertIn("dry-run", txt)
        self.assertIn("publish=false", txt)
        self.assertIn("publish=true", txt)


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Publishing(unittest.TestCase):
    PUSHERS = (r"\bpush\b", r"\blogin\b", r"imagetools create", r"cosign (sign|attest)", r"gh release", r"upload")

    def gated(self, name, job, s):
        if re.search(PUBLISH_RE, str(job.get("if", ""))):
            return True
        return bool(re.search(PUBLISH_RE, str(s.get("if", ""))))

    def test_every_publishing_step_is_gated_on_publish(self):
        n = 0
        for name, job in jobs().items():
            for s in job.get("steps", []):
                txt = step_text(s)
                if s.get("id") == "pub":    # the decision step itself compares with the word push, it pushes nothing
                    continue
                if any(re.search(p, txt) for p in self.PUSHERS):
                    n += 1
                    self.assertTrue(self.gated(name, job, s), "%s: %s" % (name, s.get("name")))
        self.assertGreaterEqual(n, 6)

    def test_jobs_after_the_build_are_skipped_unless_publish(self):
        for name in ("manifest", "sign", "notes"):
            self.assertRegex(str(jobs()[name]["if"]), PUBLISH_RE, name)

    def test_the_publish_output_is_never_true_off_a_tag(self):
        # the rule is also exercised: run the step's script with fake GITHUB_* values
        step = [s for s in jobs()["version"]["steps"] if s.get("id") == "pub"][0]
        def go(ref_type, event, dry):
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "out")
                env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": out, "REF_TYPE": ref_type, "EVENT": event,
                       "DRY_RUN": dry, "GITHUB_REF_TYPE": ref_type, "GITHUB_EVENT_NAME": event,
                       "INPUT_DRY_RUN": dry}
                subprocess.run(["bash", "-c", step["run"]], env=env, cwd=ROOT, check=True, capture_output=True)
                with open(out) as fh:
                    return fh.read()
        self.assertIn("publish=true", go("tag", "push", ""))
        self.assertIn("publish=false", go("branch", "push", ""))
        self.assertIn("publish=false", go("branch", "workflow_dispatch", "false"))
        self.assertIn("publish=false", go("tag", "workflow_dispatch", "true"))
        self.assertIn("publish=true", go("tag", "workflow_dispatch", "false"))

    def test_registry_is_exactly_the_owner_image(self):
        self.assertEqual(DOC["env"]["REGISTRY_IMAGE"], IMAGE)
        hosts = set(re.findall(r"\b([a-z0-9.-]+\.(?:io|com|dev|org))/[\w./-]+", TEXT.replace("github.com/", "")))
        for h in hosts:
            self.assertIn(h, ("ghcr.io", "claude.com", "sigstore.dev", "docs.github.com", "githubusercontent.com"), h)
        for m in re.findall(r"ghcr\.io/[\w./-]+", TEXT):
            self.assertTrue(m.startswith(IMAGE), m)
        for bad in ("docker.io", "quay.io", "index.docker", "registry.example", "docker/login-action", "secrets."):
            self.assertNotIn(bad, TEXT)
        self.assertNotIn("0.0.0.0", TEXT)

    def test_login_uses_the_workflow_token_only(self):
        self.assertIn("github.token", TEXT)
        self.assertRegex(TEXT, r"--password-stdin")
        self.assertNotRegex(TEXT, r"--password[ =](?!-stdin)")


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Permissions(unittest.TestCase):
    def test_top_level_read_only(self):
        self.assertEqual(DOC["permissions"], {"contents": "read"})

    def test_no_write_all_and_every_job_declares_its_own(self):
        self.assertNotIn("write-all", TEXT)
        for name, j in jobs().items():
            if "uses" in j:        # the reusable ci call takes the caller's permissions
                continue
            self.assertIn("permissions", j, name)

    def test_id_token_write_only_in_the_signing_job(self):
        holders = [n for n, j in jobs().items() if "id-token" in (j.get("permissions") or {})]
        self.assertEqual(holders, ["sign"])
        self.assertEqual(jobs()["sign"]["permissions"]["id-token"], "write")

    def test_packages_write_only_where_an_image_is_pushed(self):
        holders = sorted(n for n, j in jobs().items() if (j.get("permissions") or {}).get("packages") == "write")
        self.assertEqual(holders, ["build", "manifest", "sign"])

    def test_contents_write_only_in_notes(self):
        holders = [n for n, j in jobs().items() if (j.get("permissions") or {}).get("contents") == "write"]
        self.assertEqual(holders, ["notes"])

    def test_every_job_has_a_timeout(self):
        for name, j in jobs().items():
            if "uses" not in j:
                self.assertIn("timeout-minutes", j, name)


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Pipeline(unittest.TestCase):
    def test_tests_job_is_the_ci_workflow(self):
        j = jobs()["tests"]
        self.assertEqual(j["uses"], "./.github/workflows/ci.yml")
        self.assertIn("workflow_call", ci.triggers(ci.DOC))
        def closure(n, seen=()):
            out = set()
            for d in jobs()[n].get("needs", []):
                out |= {d} | closure(d)
            return out
        for name in jobs():
            if name not in ("version", "tests"):
                self.assertIn("tests", closure(name), name)   # directly or through the build job

    def test_both_architectures_build_natively(self):
        m = jobs()["build"]["strategy"]["matrix"]["include"]
        got = {(i["arch"], i["runner"]) for i in m}
        self.assertEqual(got, {("amd64", "ubuntu-24.04"), ("arm64", "ubuntu-24.04-arm")})
        self.assertEqual(jobs()["build"]["runs-on"], "${{ matrix.runner }}")
        self.assertNotRegex(TEXT.lower(), r"qemu|binfmt")

    def test_build_extracts_the_helper_and_compares_its_version_with_the_tag(self):
        text = "\n".join(l for _, l in ci.run_lines(DOC, "build"))
        self.assertIn("swarmbox-entrypoint host-helper", text)
        self.assertRegex(text, r"swarmbox-host\" version")
        self.assertRegex(text, r'\[ "\$helper_version" = "\$VERSION" \]|"\$helper_version" != "\$VERSION"')
        names = [s.get("name", "") for s in jobs()["build"]["steps"]]
        extract = [i for i, s in enumerate(jobs()["build"]["steps"]) if "swarmbox-entrypoint host-helper" in s.get("run", "")]
        push = [i for i, s in enumerate(jobs()["build"]["steps"]) if "podman push" in s.get("run", "")]
        self.assertTrue(extract and push and extract[0] < push[0], names)   # a wrong version never reaches the registry

    def test_scan_fails_on_high_and_critical_before_any_push(self):
        steps = jobs()["build"]["steps"]
        scan = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("anchore/scan-action@")]
        self.assertEqual(len(scan), 1)
        w = steps[scan[0]]["with"]
        self.assertEqual(str(w["fail-build"]).lower(), "true")
        self.assertEqual(w["severity-cutoff"], "high")
        self.assertTrue(str(w["image"]).startswith("docker-archive:"))
        push = [i for i, s in enumerate(steps) if "podman push" in s.get("run", "")]
        self.assertLess(scan[0], push[0])
        ign = os.path.join(ROOT, ".grype.yaml")
        self.assertTrue(os.path.exists(ign), "documented ignore file .grype.yaml is missing")
        t = open(ign, encoding="utf-8").read()
        self.assertIn("ignore", t)
        self.assertRegex(t, r"(?i)every entry|each entry")
        self.assertEqual(re.findall(r"^\s+- vulnerability:", t, re.M), [])   # ships with no ignored finding

    def test_manifest_tags_come_from_the_version_script(self):
        text = "\n".join(l for _, l in ci.run_lines(DOC, "manifest"))
        self.assertIn("imagetools create", text)
        self.assertIn("tags", str(jobs()["version"]["outputs"]))
        self.assertRegex(text, r"\$\{?REGISTRY_IMAGE\}?")
        self.assertIn("digest", text)
        self.assertIn("digest", jobs()["manifest"]["outputs"])

    def test_sign_signs_the_digest_not_a_tag_and_makes_the_sbom_and_attestation(self):
        text = "\n".join(l for _, l in ci.run_lines(DOC, "sign"))
        self.assertRegex(text, r'cosign sign --yes "?\$\{?REGISTRY_IMAGE\}?@\$\{?DIGEST\}?"?')
        self.assertRegex(text, r'cosign attest --yes .*--type spdxjson')
        self.assertRegex(text, r"cosign verify")
        self.assertRegex(text, r"--certificate-identity")
        self.assertRegex(text, r"--certificate-oidc-issuer https://token\.actions\.githubusercontent\.com")
        uses = [s.get("uses", "") for s in jobs()["sign"]["steps"]]
        self.assertTrue(any(u.startswith("sigstore/cosign-installer@") for u in uses))
        sb = [s for s in jobs()["sign"]["steps"] if str(s.get("uses", "")).startswith("anchore/sbom-action@")]
        self.assertEqual(len(sb), 1)
        self.assertEqual(sb[0]["with"]["format"], "spdx-json")
        self.assertRegex(str(sb[0]["with"]["image"]), r"@")

    def test_release_notes_carry_the_digest_and_the_sbom_asset(self):
        text = "\n".join(l for _, l in ci.run_lines(DOC, "notes"))
        self.assertIn("gh release", text)
        self.assertIn("digest", text.lower())
        self.assertIn("sbom", text.lower())
        self.assertIn("--verify-tag", text)
        self.assertTrue(any(str(s.get("uses", "")).startswith("actions/download-artifact@") for s in jobs()["notes"]["steps"]))

    def test_checkout_does_not_persist_credentials_in_jobs_that_write(self):
        for name, j in jobs().items():
            for s in j.get("steps", []):
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    self.assertEqual(str(s.get("with", {}).get("persist-credentials")).lower(), "false", name)


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Pins(unittest.TestCase):
    def test_every_uses_is_pinned_by_an_exact_version(self):
        n = 0
        for name, j in jobs().items():
            for s in j.get("steps", []):
                u = s.get("uses")
                if u:
                    n += 1
                    self.assertRegex(u, r"^[\w.-]+/[\w./-]+@v\d+\.\d+\.\d+$", "%s: %s" % (name, u))
        self.assertGreaterEqual(n, 6)

    def test_run_steps_reference_existing_files(self):
        for name, line in ci.run_lines(DOC):
            for path in re.findall(r"\b(?:dev|container|tests)/[A-Za-z0-9_./-]+\.(?:sh|py)\b", line):
                self.assertTrue(os.path.exists(os.path.join(ROOT, path)), "%s: %s" % (name, path))

    def test_no_forbidden_podman_verb(self):
        for bad in ("system prune", "system reset", "volume prune", "image prune", "rmi -a", "rm -a", "stop -a", "kill -a", "--all "):
            self.assertNotIn(bad, TEXT)

    def test_the_first_run_checks_are_written_in_the_file(self):
        for needle in ("[unverified]", "cosign", "ubuntu-24.04-arm", "packages: write", "grype"):
            self.assertIn(needle, TEXT)


class FallbackTextCheck(unittest.TestCase):
    def test_text_markers(self):
        for needle in ("v*.*.*", "workflow_dispatch", "dry-run", "ghcr.io/feroult/swarmbox", "id-token: write",
                       "cosign sign", "anchore/sbom-action", "anchore/scan-action", "ubuntu-24.04-arm", "contents: read"):
            self.assertIn(needle, TEXT)
        self.assertEqual(TEXT.count("id-token: write"), 1)
        self.assertNotIn("write-all", TEXT)
        self.assertNotIn("secrets.", TEXT)
        self.assertNotIn("\t", TEXT)
        for u in re.findall(r"uses:\s*(\S+)", TEXT):
            if not u.startswith("./"):
                self.assertRegex(u, r"@v\d+\.\d+\.\d+$")


class Actionlint(unittest.TestCase):
    def test_actionlint(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available (reduced: absence recorded in the status row)")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), REL, ci.CI],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
