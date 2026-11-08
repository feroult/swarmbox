"""Slice 1.6: static checks of .github/workflows/ci.yml (it cannot run here, so it is validated locally).

Parser: PyYAML if importable; else PyYAML installed into a mktemp venv with pip; else a documented minimal text check
(the structural tests that need a parsed tree are then skipped and the fallback class still runs). The parser used is
printed. actionlint is run too when it is on PATH or can be downloaded into a mktemp directory (see ACTIONLINT below);
its absence is reported, not hidden.
Run: python3 tests/test_ci_workflow.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")
# Test files that the push/pull_request jobs do not run; they run in the scheduled browser job only.
SCHEDULED_ONLY = {"test_clipboard_bridge.py", "test_web_style.py", "test_tmux_browser_keys.py"}
# Test files that are not meant to run in the macOS job (they need tmux, a browser or GNU tools).
NOT_ON_MACOS = SCHEDULED_ONLY | {"test_web_terminal.py", "test_start_attach.py", "test_spikes_common.py",
                                 "test_history_audit.py", "test_serve_steps.py", "test_serve_container.py",
                                 "test_attach_command.py", "test_attach_container.py",
                                 "test_bashrc_fragment.py", "test_bashrc_container.py", "test_entrypoint.py",
                                 "test_pubkey_ensure.py", "test_migration.py", "test_mcp_registry.py", "test_tool_stub.py", "test_tool_manifest.py", "test_tool_link.py", "test_tool_install.py", "test_tool_prepare.py", "test_tool_opencode.py", "test_tool_gemini_clasp_poetry.py", "test_tool_go_gcloud.py", "test_tool_use_remove.py", "test_tool_new.py", "test_tool_doctor.py", "test_tool_image_level.py", "test_image_with_tools.py", "test_record_checksums.py", "test_tool_shim.py", "test_tool_claude_real.py", "test_tool_real.py", "test_web_build.py", "test_web_container.py"}
PARSER = "none"


def _yaml_module():
    global PARSER
    try:
        import yaml  # noqa: F401
        PARSER = "PyYAML (importable)"
        return yaml
    except ImportError:
        pass
    venv = os.path.join(tempfile.gettempdir(), "swarmbox-test-ci-yaml-venv")
    py = os.path.join(venv, "bin", "python")
    try:
        if not os.path.exists(py):
            subprocess.run([sys.executable, "-m", "venv", venv], check=True, capture_output=True, timeout=120)
            subprocess.run([py, "-m", "pip", "install", "-q", "pyyaml"], check=True, capture_output=True, timeout=300)
        out = subprocess.run([py, "-c", "import yaml,sys;print(yaml.__file__)"], check=True, capture_output=True,
                             text=True).stdout.strip()
        sys.path.insert(0, os.path.dirname(os.path.dirname(out)))
        import yaml
        PARSER = "PyYAML (pip into a venv under the temp dir)"
        return yaml
    except Exception:
        PARSER = "fallback text check (no YAML parser available)"
        return None


YAML = _yaml_module()
print("ci.yml parser:", PARSER, file=sys.stderr)
TEXT = open(CI, encoding="utf-8").read() if os.path.exists(CI) else ""
DOC = YAML.safe_load(TEXT) if YAML and TEXT else None


def triggers(doc):
    return doc.get("on", doc.get(True))  # PyYAML (YAML 1.1) reads the key `on` as True


def steps(doc, job=None):
    for name, j in doc["jobs"].items():
        if job and name != job:
            continue
        for s in j.get("steps", []):
            yield name, s


def run_lines(doc, job=None):
    for name, s in steps(doc, job):
        for line in str(s.get("run", "")).splitlines():
            yield name, line.strip()


def tests_run(doc, job=None):
    found = set()
    for _, line in run_lines(doc, job):
        found.update(re.findall(r"python3 tests/(test_[A-Za-z0-9_]+\.py)\b", line))
    return found


class FileExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(os.path.exists(CI), ".github/workflows/ci.yml is missing")


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Structure(unittest.TestCase):
    def test_triggers(self):
        t = triggers(DOC)
        for k in ("push", "pull_request", "schedule"):
            self.assertIn(k, t)
        self.assertTrue(t["schedule"][0]["cron"])
        self.assertIn("workflow_dispatch", t)

    def test_permissions_read_only(self):
        self.assertEqual(DOC.get("permissions"), {"contents": "read"})
        for name, j in DOC["jobs"].items():
            p = j.get("permissions")
            self.assertTrue(p is None or all(v == "read" for v in p.values()), name)

    def test_concurrency_group(self):
        self.assertTrue(DOC.get("concurrency", {}).get("group"))

    def test_every_job_has_timeout(self):
        for name, j in DOC["jobs"].items():
            self.assertIn("timeout-minutes", j, name)

    def test_uses_are_pinned(self):
        n = 0
        for name, s in steps(DOC):
            u = s.get("uses")
            if not u:
                continue
            n += 1
            self.assertRegex(u, r"^[\w.-]+/[\w./-]+@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$", "%s: %s" % (name, u))
        self.assertGreaterEqual(n, 1)

    def test_run_commands_reference_existing_files(self):
        for name, line in run_lines(DOC):
            for path in re.findall(r"\btests/[A-Za-z0-9_./-]+\.py\b", line) + \
                    re.findall(r"\b(?:container|lib)/[A-Za-z0-9_./-]+\.sh\b", line):
                self.assertTrue(os.path.exists(os.path.join(ROOT, path)), "%s: %s" % (name, path))
        for name, line in run_lines(DOC):
            if "shellcheck" in line:
                for path in re.findall(r"\b[\w./-]+\.sh\b", line):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, path)), "%s: %s" % (name, path))

    def test_test_set_equals_disk_minus_scheduled(self):
        disk = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py"))}
        self.assertTrue(SCHEDULED_ONLY <= disk)
        self.assertEqual(tests_run(DOC, "linux"), disk - SCHEDULED_ONLY)
        self.assertEqual(tests_run(DOC, "browser"), SCHEDULED_ONLY)

    def test_macos_runs_a_subset_with_no_browser_tests(self):
        mac = tests_run(DOC, "macos")
        disk = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py"))}
        self.assertTrue(mac)
        self.assertEqual(mac & NOT_ON_MACOS, set())
        for core in ("test_dirs.py", "test_helpers.py", "test_start_fake_podman.py"):
            self.assertIn(core, mac)
        # every non-excluded test is on macOS: a new test file cannot be forgotten there either
        self.assertEqual(mac, disk - NOT_ON_MACOS)

    def test_linux_job_has_podman_guard(self):
        job = DOC["jobs"]["linux"]
        self.assertIn("ubuntu-24.04", str(job["runs-on"]))
        text = "\n".join(l for _, l in run_lines(DOC, "linux"))
        self.assertIn("podman --version", text)
        self.assertRegex(text, r"4\.3|4, *3|\(4, 3\)")

    def test_macos_probe_for_b30(self):
        job = DOC["jobs"]["macos"]
        self.assertIn("macos", str(job["runs-on"]))
        text = "\n".join(l for _, l in run_lines(DOC, "macos"))
        self.assertIn("/bin/bash --version", text)
        self.assertIn("command -v podman", text)
        self.assertIn("B30", TEXT)

    def test_real_tools_job_is_scheduled_and_runs_the_real_installer_tests(self):
        job = DOC["jobs"]["real-tools"]
        self.assertIn("schedule", job["if"])
        self.assertNotIn("push", job["if"])
        self.assertEqual(job["env"]["SWARMBOX_TEST_NETWORK"], "1")
        self.assertEqual(job["env"]["SWARMBOX_IMAGE_BUILD"], "1")
        self.assertTrue(job["env"]["SWARMBOX_IMAGE_TAG"].startswith("swarmbox-test-"))
        text = "\n".join(l for _, l in run_lines(DOC, "real-tools"))
        self.assertIn("python3 tests/test_tool_real.py", text)
        self.assertIn("python3 tests/test_tool_claude_real.py", text)
        self.assertIn("skipped", text)  # a skipped real test fails the job
        last = [s for s in job["steps"] if s.get("if") == "always()"]
        self.assertEqual(len(last), 1)
        self.assertIn('podman rmi "$SWARMBOX_IMAGE_TAG"', last[0]["run"])
        # the harness part runs on every push in the linux job
        self.assertIn("test_tool_real.py", tests_run(DOC, "linux"))

    def test_browser_job_is_scheduled_only(self):
        job = DOC["jobs"]["browser"]
        self.assertIn("schedule", job["if"])
        self.assertNotIn("push", job["if"])

    def test_no_secrets_exposure_or_publishing(self):
        self.assertNotIn("secrets.", TEXT)
        self.assertNotIn("0.0.0.0", TEXT)
        for bad in ("podman push", "docker push", "docker/login-action", "gh release", "npm publish", "twine upload",
                    "podman login", "api.cloudflare.com", "cloudflared"):
            self.assertNotIn(bad, TEXT.lower())

    def test_smoke_job_builds_the_image_and_runs_the_full_smoke_test(self):
        job = DOC["jobs"]["smoke"]
        self.assertIn("ubuntu-24.04", str(job["runs-on"]))
        self.assertEqual(job["env"]["SWARMBOX_IMAGE_TAG"], "swarmbox-test-img-ci")
        text = "\n".join(l for _, l in run_lines(DOC, "smoke"))
        self.assertIn("podman build", text)
        self.assertRegex(text, r"SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image\.py")
        self.assertIn("SKIP", text)  # a skipped step in the full run fails the job
        # cleanup removes the image by its exact name, even after a failure
        last = [s for s in job["steps"] if s.get("if") == "always()"]
        self.assertEqual(len(last), 1)
        self.assertIn('podman rmi "$SWARMBOX_IMAGE_TAG"', last[0]["run"])
        # the smoke job is not scheduled-only: it runs on push and pull request
        self.assertNotIn("if", job)

    def test_tools_validate_is_a_ci_step_without_a_container(self):
        """Phase 4a: the real `swarmbox-tool validate` runs on container/tools in the linux job (no container needed)."""
        lines = [l for _, l in run_lines(DOC, "linux")]
        hit = [l for l in "\n".join(lines).splitlines()
               if re.search(r"container/scripts/swarmbox-tool\.sh validate container/tools\b", l)]
        self.assertEqual(len(hit), 1, hit)
        self.assertNotIn("podman", hit[0])
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "container", "tools")))

    def test_smoke_job_uses_no_forbidden_podman_verb(self):
        for bad in ("system prune", "system reset", "volume prune", "image prune", "rmi -a", "rm -a", "stop -a", "kill -a",
                    "--all", "podman push"):
            self.assertNotIn(bad, TEXT)

    def test_comment_documents_smoke_job_and_b28(self):
        self.assertRegex(TEXT, r"(?i)smoke.*SWARMBOX_SMOKE_FULL=1")
        self.assertIn("B28", TEXT)


@unittest.skipUnless(DOC, "no YAML parser available (fallback class below still runs)")
class Phase3Jobs(unittest.TestCase):
    """Slice 3.7: the arm64 job (B31), the function tests in three shells, bash 3.2 on macOS, dash and busybox.

    None of these jobs can run in the development box (no arm64 runner, no macOS, a container as the host), so they are
    only validated here, by their shape. B31 stays [unverified] until the first real run of the arm64 job.
    """

    def text(self, job):
        return "\n".join(l for _, l in run_lines(DOC, job))

    def test_arm64_job_builds_natively_and_runs_the_full_smoke_test(self):
        job = DOC["jobs"]["arm64"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04-arm")
        self.assertNotIn("if", job)                       # runs on push and pull request like the smoke job
        self.assertEqual(job["env"]["SWARMBOX_IMAGE_TAG"], "swarmbox-test-img-ci-arm64")
        text = self.text("arm64")
        self.assertRegex(text, r"uname -m")
        self.assertIn("aarch64", text)                    # the job fails when the runner is not arm64
        self.assertRegex(text, r'dev/dev-build\.sh --tag "\$SWARMBOX_IMAGE_TAG"')
        self.assertRegex(text, r"SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image\.py")
        self.assertIn("SKIP", text)
        self.assertRegex(text, r"podman --version")
        last = [s for s in job["steps"] if s.get("if") == "always()"]
        self.assertEqual(len(last), 1)
        self.assertIn('podman rmi "$SWARMBOX_IMAGE_TAG"', last[0]["run"])

    def test_arm64_job_uses_no_emulation_no_registry_no_secret(self):
        job_text = str(DOC["jobs"]["arm64"]).lower()
        for bad in ("qemu", "binfmt", "--platform", "login", "podman push", "docker push", "secrets.", "registry", "-p ", "--publish", "0.0.0.0"):
            self.assertNotIn(bad, job_text)

    def test_arm64_is_unverified_until_it_runs(self):
        self.assertRegex(TEXT, r"(?s)arm64.*B31.*\[unverified\]|B31.*\[unverified\].*arm64")

    def test_the_linux_job_runs_the_function_tests_in_the_three_shells(self):
        job = DOC["jobs"]["linux"]
        text = self.text("linux")
        for shell in ("zsh", "fish"):
            self.assertRegex(text, r"apt-get install .*\b%s\b" % shell)
        for t in ("test_function_bash.py", "test_function_zsh.py", "test_function_fish.py"):
            self.assertIn("python3 tests/" + t, text)
        names = [s.get("name", "") for s in job["steps"]]
        probe = [s for s in job["steps"] if "command -v" in str(s.get("run", "")) and "zsh" in str(s.get("run", ""))
                 and "fish" in str(s.get("run", ""))]
        self.assertEqual(len(probe), 1, names)             # a missing shell fails the job instead of skipping tests

    def test_the_linux_job_runs_the_host_helper_under_dash_and_busybox(self):
        job = DOC["jobs"]["linux"]
        hit = [s for s in job["steps"] if "dash" in str(s.get("run", "")) and "busybox" in str(s.get("run", ""))
               and "test_host_shells.py" in str(s.get("run", ""))]
        self.assertEqual(len(hit), 1)
        run = hit[0]["run"]
        self.assertRegex(run, r"command -v dash")
        self.assertRegex(run, r"command -v busybox")
        self.assertIn("python3 tests/test_host_create_flags.py", run)   # compares the helper's output across the shells
        self.assertRegex(self.text("linux"), r"apt-get install .*\bbusybox\b")

    def test_macos_runs_the_function_test_in_bin_bash_3_2(self):
        job = DOC["jobs"]["macos"]
        self.assertIn("macos", str(job["runs-on"]))
        step = [s for s in job["steps"] if "test_function_bash.py" in str(s.get("run", ""))]
        self.assertEqual(len(step), 1)
        self.assertEqual(step[0].get("env", {}).get("SWARMBOX_TEST_BASH"), "/bin/bash")
        guard = [s for s in job["steps"] if "BASH_VERSINFO" in str(s.get("run", ""))]
        self.assertEqual(len(guard), 1)                   # the probe fails when /bin/bash is not a 3.x
        self.assertIn("/bin/bash", guard[0]["run"])
        order = [s.get("name", "") for s in job["steps"]]
        self.assertLess(job["steps"].index(guard[0]), job["steps"].index(step[0]), order)

    def test_the_bash_test_honors_swarmbox_test_bash(self):
        with open(os.path.join(ROOT, "tests", "test_function_bash.py"), encoding="utf-8") as f:
            self.assertIn('os.environ.get("SWARMBOX_TEST_BASH")', f.read())

    def test_no_job_publishes_a_port(self):
        for bad in ("--publish", " -p ", "ports:", "0.0.0.0"):
            self.assertNotIn(bad, TEXT)

    def test_the_regression_runner_is_a_ci_test(self):
        self.assertIn("python3 tests/test_run_all.py", self.text("linux"))
        self.assertIn("python3 tests/test_run_all.py", self.text("macos"))


class FallbackTextCheck(unittest.TestCase):
    """Documented minimal check that needs no YAML parser: runs always, so a missing parser cannot hide a hole."""

    def test_text_markers(self):
        for needle in ("push:", "pull_request:", "schedule:", "contents: read", "concurrency:", "ubuntu-24.04",
                       "macos-", "/bin/bash --version", "command -v podman", "B30"):
            self.assertIn(needle, TEXT)
        self.assertNotIn("secrets.", TEXT)
        self.assertNotIn("\t", TEXT)
        for u in re.findall(r"uses:\s*(\S+)", TEXT):
            self.assertRegex(u, r"@(v\d|[0-9a-f]{40})")


class Actionlint(unittest.TestCase):
    """Runs actionlint when it is on PATH or in $ACTIONLINT; the slice's run downloaded it into a mktemp dir."""

    def test_actionlint(self):
        exe = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
        if not exe:
            self.skipTest("actionlint not available (reduced: absence recorded in the status row)")
        r = subprocess.run([exe, "-shellcheck=" + (shutil.which("shellcheck") or ""), CI], capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
