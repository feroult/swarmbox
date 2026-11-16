"""Dev/dev-build.sh, the local image build for the development box (nested Podman).

The APT sandbox override exists only in a scratch copy of the Dockerfile in a mktemp directory; the product Dockerfile
never contains it. Podman is a FakePodman here, so nothing is built. Run: python3 tests/fast/test_dev_build.py
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, FakePodman  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "dev-build.sh")


def run(fp, *args, extra_env=None):
    env = fp.env()
    env.update(extra_env or {})
    return subprocess.run(["sh", SCRIPT] + list(args), env=env, capture_output=True, text=True, cwd="/")


def scratch_dir(r):
    m = re.search(r"^scratch: (\S+)$", r.stderr, re.M)
    return m.group(1) if m else None


def build_call(fp):
    return [c for c in fp.calls() if c[0] == "build"][0]


class DevBuild(unittest.TestCase):
    def test_the_tag_is_always_in_the_test_namespace(self):
        with FakePodman() as fp:
            r = run(fp)
            self.assertEqual(r.returncode, 0, r.stderr)
            tag = build_call(fp)[build_call(fp).index("-t") + 1]
            self.assertRegex(tag, r"^swarmbox-test-img-[a-z0-9]{4,}$")
            self.assertIn(tag, r.stdout)
        with FakePodman() as fp:
            self.assertEqual(run(fp, "--tag", "swarmbox-test-img-abc123").returncode, 0)
            b = build_call(fp)
            self.assertEqual(b[b.index("-t") + 1], "swarmbox-test-img-abc123")
        for bad in ("swarmbox", "swarmbox:latest", "myimage", "swarmbox-test", "docker.io/x/swarmbox-test-a"):
            with FakePodman() as fp:
                r = run(fp, "--tag", bad)
                self.assertNotEqual(r.returncode, 0, bad)
                self.assertEqual(fp.calls(), [], bad)
                self.assertIn("swarmbox-test-", r.stderr)

    def test_the_apt_override_is_only_in_a_scratch_copy_which_is_removed_and_the_product_dockerfile_is_never_touched(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            product = f.read()
        self.assertNotIn("Sandbox", product)
        with FakePodman() as fp:
            r = run(fp, "--keep-scratch")
            self.assertEqual(r.returncode, 0, r.stderr)
            sd = scratch_dir(r)
            self.assertTrue(sd and os.path.isdir(sd), r.stderr)
            try:
                self.assertFalse(os.path.realpath(sd).startswith(os.path.realpath(ROOT) + os.sep))
                with open(os.path.join(sd, "Dockerfile")) as f:
                    scratch = f.read()
                self.assertIn('APT::Sandbox::User "root";', scratch)
                # the copy is the product file plus the override, right after the FROM, nothing else
                self.assertEqual("\n".join(l for l in scratch.splitlines() if "Sandbox" not in l and "99swarmbox-dev" not in l).strip(), product.strip())
                code = [l for l in scratch.splitlines() if l.strip() and not l.startswith("#")]
                self.assertIn("Sandbox", code[code.index([l for l in code if l.startswith("FROM ")][0]) + 1])
                b = build_call(fp)   # the build uses the scratch file and the repository as its context
                self.assertEqual(b[b.index("-f") + 1], os.path.join(sd, "Dockerfile"))
                self.assertEqual(os.path.realpath(b[-1]), os.path.realpath(ROOT))
            finally:
                shutil.rmtree(sd, ignore_errors=True)
        with FakePodman() as fp:   # by default the scratch copy is removed
            r = run(fp, "--dry-run")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([c for c in fp.calls() if c[0] == "build"], [])
            sd = scratch_dir(r)
            self.assertTrue(sd is None or not os.path.exists(sd))
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            self.assertEqual(f.read(), product)

    def test_a_failed_build_fails_and_nothing_but_build_is_called_on_podman(self):
        with FakePodman(subcommands={"build": {"exit": 125, "stderr": "boom"}}) as fp:
            self.assertNotEqual(run(fp).returncode, 0)
        with FakePodman() as fp:
            run(fp)
            self.assertEqual({c[0] for c in fp.calls()}, {"build"})

    def test_build_args_pass_through_in_their_order_and_none_is_added(self):
        with FakePodman() as fp:
            run(fp)
            self.assertFalse(any(a.startswith("WITH_ADDONS") for a in build_call(fp)))
        with FakePodman() as fp:
            r = run(fp, "--build-arg", "WITH_ADDONS=claude,gcloud", "--build-arg", "NODE_VERSION=22")
            self.assertEqual(r.returncode, 0, r.stderr)
            b = build_call(fp)
            i = b.index("WITH_ADDONS=claude,gcloud")
            self.assertEqual(b[i - 1], "--build-arg")
            self.assertEqual(sum(1 for a in b if a.startswith("WITH_ADDONS")), 1)
            self.assertLess(i, b.index("NODE_VERSION=22"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
