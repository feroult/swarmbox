"""Slice 2.1: dev/dev-build.sh, the local image build for the development box (nested Podman).

The APT sandbox override exists only in a scratch copy of the Dockerfile in a mktemp directory; the product Dockerfile
never contains it. Podman is a FakePodman here, so nothing is built. Run: python3 tests/test_dev_build.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "dev-build.sh")


def run(fp, *args, extra_env=None):
    env = fp.env()
    env.update(extra_env or {})
    return subprocess.run(["sh", SCRIPT] + list(args), env=env, capture_output=True, text=True, cwd="/")


def scratch_dir(r):
    m = re.search(r"^scratch: (\S+)$", r.stderr, re.M)
    return m.group(1) if m else None


class DevBuild(unittest.TestCase):
    def test_script_exists_and_is_posix_sh(self):
        self.assertTrue(os.path.isfile(SCRIPT))
        with open(SCRIPT) as f:
            self.assertTrue(f.readline().startswith("#!/bin/sh"))

    def test_product_dockerfile_never_has_the_override(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            self.assertNotIn("Sandbox", f.read())

    def test_default_tag_starts_with_swarmbox_test(self):
        with FakePodman() as fp:
            r = run(fp)
            self.assertEqual(r.returncode, 0, r.stderr)
            build = [c for c in fp.calls() if c[0] == "build"]
            self.assertEqual(len(build), 1)
            tag = build[0][build[0].index("-t") + 1]
            self.assertRegex(tag, r"^swarmbox-test-img-[a-z0-9]{4,}$")
            self.assertIn(tag, r.stdout)

    def test_a_tag_outside_the_test_namespace_is_refused(self):
        for bad in ("swarmbox", "swarmbox:latest", "myimage", "swarmbox-test", "docker.io/x/swarmbox-test-a"):
            with FakePodman() as fp:
                r = run(fp, "--tag", bad)
                self.assertNotEqual(r.returncode, 0, bad)
                self.assertEqual(fp.calls(), [], bad)
                self.assertIn("swarmbox-test-", r.stderr)

    def test_explicit_valid_tag_is_used(self):
        with FakePodman() as fp:
            r = run(fp, "--tag", "swarmbox-test-img-abc123")
            self.assertEqual(r.returncode, 0, r.stderr)
            b = [c for c in fp.calls() if c[0] == "build"][0]
            self.assertEqual(b[b.index("-t") + 1], "swarmbox-test-img-abc123")

    def test_override_only_in_a_scratch_copy(self):
        with FakePodman() as fp:
            r = run(fp, "--keep-scratch")
            self.assertEqual(r.returncode, 0, r.stderr)
            sd = scratch_dir(r)
            self.assertTrue(sd and os.path.isdir(sd), r.stderr)
            try:
                self.assertNotEqual(os.path.realpath(sd), os.path.realpath(ROOT))
                self.assertFalse(os.path.realpath(sd).startswith(os.path.realpath(ROOT) + os.sep))
                with open(os.path.join(sd, "Dockerfile")) as f:
                    scratch = f.read()
                with open(os.path.join(ROOT, "Dockerfile")) as f:
                    product = f.read()
                self.assertIn('APT::Sandbox::User "root";', scratch)
                self.assertNotIn("Sandbox", product)
                # the copy is the product file plus the override, nothing else
                lines = [l for l in scratch.splitlines() if "Sandbox" not in l and "99swarmbox-dev" not in l]
                self.assertEqual("\n".join(lines).strip(), product.strip())
                # first line of the scratch copy is still the FROM (after any ARG): the override comes right after it
                code = [l for l in scratch.splitlines() if l.strip() and not l.startswith("#")]
                self.assertTrue(code[0].startswith("ARG ") or code[0].startswith("FROM "))
                self.assertIn("Sandbox", code[code.index([l for l in code if l.startswith("FROM ")][0]) + 1])
                # build call: -f the scratch file, context = the repository
                b = [c for c in fp.calls() if c[0] == "build"][0]
                self.assertEqual(b[b.index("-f") + 1], os.path.join(sd, "Dockerfile"))
                self.assertEqual(os.path.realpath(b[-1]), os.path.realpath(ROOT))
            finally:
                shutil.rmtree(sd, ignore_errors=True)

    def test_scratch_is_removed_by_default_and_the_product_file_is_unchanged(self):
        with open(os.path.join(ROOT, "Dockerfile"), "rb") as f:
            before = f.read()
        with FakePodman() as fp:
            r = run(fp, "--dry-run")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([c for c in fp.calls() if c[0] == "build"], [])
            sd = scratch_dir(r)
            self.assertTrue(sd is None or not os.path.exists(sd))
        with open(os.path.join(ROOT, "Dockerfile"), "rb") as f:
            self.assertEqual(f.read(), before)

    def test_build_failure_is_reported(self):
        with FakePodman(subcommands={"build": {"exit": 125, "stderr": "boom"}}) as fp:
            r = run(fp)
            self.assertNotEqual(r.returncode, 0)

    def test_only_build_is_called_on_podman(self):
        with FakePodman() as fp:
            run(fp)
            self.assertEqual({c[0] for c in fp.calls()}, {"build"})

    def test_a_dockerfile_option_and_build_args_pass_through(self):
        with FakePodman() as fp:
            r = run(fp, "--build-arg", "CHROME_DEVTOOLS_MCP_VERSION=1.0.0")
            self.assertEqual(r.returncode, 0, r.stderr)
            b = [c for c in fp.calls() if c[0] == "build"][0]
            self.assertIn("--build-arg", b)
            self.assertIn("CHROME_DEVTOOLS_MCP_VERSION=1.0.0", b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
