"""Checks on the built image (tag: image build). Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works.

It builds swarmbox-test-img-<rand> with dev/dev-build.sh (slow, minutes), inspects it in throwaway containers
(swarmbox-test-img-run-<rand>), records the size, and removes the container and the image by their exact names.
Environment: SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an existing image instead of building (it is then not removed).
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_image_build.py
"""
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TARGET_BYTES = int(2.5 * 1000 ** 3)
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=600):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout)


def in_image(*cmd):
    name = "swarmbox-test-img-run-" + rnd()
    try:
        return podman("run", "--rm", "--name", name, "--entrypoint", cmd[0], TAG, *cmd[1:])
    finally:
        podman("rm", "-f", name)


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
    if r.returncode != 0:
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


@unittest.skipUnless(ENABLED, "image build tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class ImageTest(unittest.TestCase):
    def test_base_image_has_node_1000_b26(self):
        r = podman("run", "--rm", "--name", "swarmbox-test-img-run-" + rnd(), "node:24-slim", "id", "node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uid=1000(node) gid=1000(node)", r.stdout)

    def test_tools_present(self):
        for cmd in (["tmux", "-V"], ["ttyd", "--version"], ["starship", "--version"], ["git", "--version"],
                    ["podman", "--version"], ["chromium", "--version"], ["uv", "--version"], ["jq", "--version"]):
            r = in_image(*cmd)
            self.assertEqual(r.returncode, 0, "%s: %s" % (cmd[0], r.stderr))

    def test_cmd_and_entrypoint(self):
        r = podman("image", "inspect", TAG, "--format", "{{json .Config.Cmd}} {{json .Config.Entrypoint}} {{.Config.User}}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '["serve"] ["/usr/local/bin/swarmbox-entrypoint"] agent')

    def test_size_is_recorded_against_the_budget_b27(self):
        r = podman("image", "inspect", TAG, "--format", "{{.Size}}")
        size = int(r.stdout.strip())
        h = podman("history", "--no-trunc=false", "--format", "{{.Size}}\t{{.CreatedBy}}", TAG)
        sys.stderr.write("\nIMAGE SIZE %d bytes (%.2f GB); budget %.1f GB\n%s\n" % (size, size / 1e9, TARGET_BYTES / 1e9, h.stdout))
        self.assertGreater(size, 100 * 1000 ** 2)
        # the image size is a budget: report, and fail only when it is exceeded so the owner sees it
        self.assertLess(size, TARGET_BYTES, "image is over the 2.5 GB budget")


if __name__ == "__main__":
    unittest.main(verbosity=2)
