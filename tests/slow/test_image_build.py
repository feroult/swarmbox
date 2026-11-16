"""Checks on the built image. Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works.

It builds swarmbox-test-img-<rand> with dev/dev-build.sh (slow, minutes), inspects it in throwaway containers (swarmbox-test-img-run-<rand>), records the
size, and removes the container and the image by their exact names (tests/support/image_support.py). What the Dockerfile says (entrypoint, command,
user, pins) is checked without a build in tests/fast/test_dockerfile.py; the whole image in use is tests/slow/smoke_image.py.
Environment: SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an existing image instead of building (it is then not removed).
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/slow/test_image_build.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import image_support as base  # noqa: E402
from image_support import ENABLED, rnd, podman, setUpModule, tearDownModule  # noqa: E402,F401  (the module hooks build and remove the image)

TARGET_BYTES = int(2.5 * 1000 ** 3)


def in_image(*cmd):
    name = "swarmbox-test-img-run-" + rnd()
    try:
        return podman("run", "--rm", "--name", name, "--entrypoint", cmd[0], base.TAG, *cmd[1:], text=True, timeout=600)
    finally:
        podman("rm", "-f", name)


@unittest.skipUnless(ENABLED, "image build tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class ImageTest(unittest.TestCase):
    def test_the_base_image_still_has_node_as_uid_1000(self):   # the Dockerfile renames that user to agent
        r = podman("run", "--rm", "--name", "swarmbox-test-img-run-" + rnd(), "node:24-trixie-slim", "id", "node", text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uid=1000(node) gid=1000(node)", r.stdout)

    def test_the_programs_of_the_box_are_in_the_image(self):
        for cmd in (["tmux", "-V"], ["ttyd", "--version"], ["starship", "--version"], ["git", "--version"],
                    ["podman", "--version"], ["chromium", "--version"], ["uv", "--version"], ["jq", "--version"]):
            r = in_image(*cmd)
            self.assertEqual(r.returncode, 0, "%s: %s" % (cmd[0], r.stderr))

    def test_the_size_is_inside_the_budget(self):
        size = int(podman("image", "inspect", base.TAG, "--format", "{{.Size}}", text=True).stdout.strip())
        history = podman("history", "--no-trunc=false", "--format", "{{.Size}}\t{{.CreatedBy}}", base.TAG, text=True).stdout
        sys.stderr.write("\nIMAGE SIZE %d bytes (%.2f GB); budget %.1f GB\n%s\n" % (size, size / 1e9, TARGET_BYTES / 1e9, history))
        self.assertGreater(size, 100 * 1000 ** 2)
        self.assertLess(size, TARGET_BYTES, "image is over the 2.5 GB budget")


if __name__ == "__main__":
    unittest.main(verbosity=2)
