"""The nested Podman of a box that has no /dev/fuse, on the REAL image (tag: image build, third nesting level). Skipped unless
SWARMBOX_IMAGE_BUILD=1, SWARMBOX_TEST_NESTED=1, SWARMBOX_TEST_NETWORK=1 and SWARMBOX_IMAGE_TAG=<swarmbox-test-...> (an image that exists) and podman works.

What it proves (the defect found in a real box): fuse-overlayfs is on the PATH of the image, the box is created without /dev/fuse, and one Podman
probe of native overlay that fails on ANOTHER graph root (the answer is cached in the runtime folder, which every graph root of the user shares)
makes Podman fall back to fuse-overlayfs and leave `overlay/.has-mount-program` = true in the real graph root for good: every later run
fails with "fuse: device not found". The test
  1. starts a box like `swarmbox up` does (the flags of container/host/swarmbox-host: keep-id, /dev/net/tun, unmasked /proc, a volume for the
     storage, no /dev/fuse), checks that it is ready with `ok` and that a nested container runs on native overlay;
  2. poisons it as the real box was (the runtime folder removed, then one `podman --root /tmp/x` on the container's own overlay file system), and
     checks that the poison is real: the marker is `true` and a nested run fails with the fuse message;
  3. restarts the box and checks that serve step 8 removed the marker, native overlay is back, the same image runs again, and the log says so.

SWARMBOX_TEST_SUBID_FIX=1 is for a development box that is itself a container (this test then runs at the third level): the second level has
fewer than 64535 sub-IDs left, so newuidmap of the box fails ("write to uid_map failed") whatever the image does. With it the box first lowers
/etc/subuid and /etc/subgid inside itself (a property of the development box, never of the product), then runs the real entrypoint.
Containers and volumes are swarmbox-test-nfuse-<random>, removed by exact name.

Run: SWARMBOX_IMAGE_BUILD=1 SWARMBOX_TEST_NESTED=1 SWARMBOX_TEST_NETWORK=1 SWARMBOX_IMAGE_TAG=swarmbox-test-img python3 tests/slow/test_nested_fuse_real.py
"""
import os
import random
import shutil
import string
import subprocess
import tempfile
import time
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from waiting import wait_until  # noqa: E402

TAG = os.environ.get("SWARMBOX_IMAGE_TAG", "")
ENABLED = bool(os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and os.environ.get("SWARMBOX_TEST_NESTED") == "1"
               and os.environ.get("SWARMBOX_TEST_NETWORK") == "1" and TAG.startswith("swarmbox-test-") and shutil.which("podman"))
SUBID_FIX = os.environ.get("SWARMBOX_TEST_SUBID_FIX") == "1"
NESTED_IMAGE = "docker.io/library/debian:bookworm-slim"
MARKER = "/home/agent/.local/share/containers/storage/overlay/.has-mount-program"


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=300):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout)


def wait_for(fn, seconds):
    return wait_until(fn, seconds, 0.5)


@unittest.skipUnless(ENABLED, "needs SWARMBOX_IMAGE_BUILD=1, SWARMBOX_TEST_NESTED=1, SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_TAG and podman")
class NestedWithoutFuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name = "swarmbox-test-nfuse-" + rnd()
        cls.vol = cls.name + "-containers"
        cls.ws = tempfile.mkdtemp(prefix="nfuse-ws-")
        os.makedirs(os.path.join(cls.ws, ".local", "share", "containers"))
        # class cleanups run last in, first out: the box goes first, then the volume, then the workspace
        cls.addClassCleanup(shutil.rmtree, cls.ws, ignore_errors=True)
        cls.addClassCleanup(podman, "volume", "rm", "-f", cls.vol)
        cls.addClassCleanup(podman, "rm", "-f", "-t", "0", cls.name)
        assert podman("volume", "create", cls.vol).returncode == 0
        args = ["run", "-d", "--name", cls.name, "--userns=keep-id:uid=1000,gid=1000", "--pids-limit=16384", "--init",
                "-v", cls.ws + ":/home/agent", "--tmpfs", "/tmp/swarmbox", "--device", "/dev/net/tun", "--security-opt", "unmask=/proc/*",
                "-v", cls.vol + ":/home/agent/.local/share/containers", "-e", "SWARMBOX_WEB=0"]
        if SUBID_FIX:
            args += ["--entrypoint", "bash", TAG, "-c",
                     "sudo sh -c 'echo agent:1001:60000 > /etc/subuid; echo agent:1001:60000 > /etc/subgid'; exec swarmbox-entrypoint serve"]
        else:
            args += [TAG, "serve"]
        r = podman(*args)
        assert r.returncode == 0, r.stderr

    def sh(self, cmd, timeout=300):
        return podman("exec", self.name, "bash", "-c", cmd, timeout=timeout)

    def ready(self, seconds=90):
        return wait_for(lambda: self.sh("cat /tmp/swarmbox/ready 2>/dev/null").stdout.strip(), seconds)

    def run_nested(self):
        r = self.sh("podman run --rm %s echo nested-ok" % NESTED_IMAGE, timeout=600)
        return r.returncode, r.stdout + r.stderr

    def test_poisoned_storage_is_repaired_by_the_next_start(self):
        # 1. a fresh box: no /dev/fuse, ready with ok, a nested container on native overlay
        self.assertEqual(self.sh("test -e /dev/fuse").returncode, 1, "this test needs a box without /dev/fuse")
        self.assertEqual(self.ready(), "ok", self.sh("tail -30 ~/.local/state/swarmbox/serve.log; cat ~/.local/state/swarmbox/podman-service.log").stdout)
        rc, out = self.run_nested()
        self.assertEqual(rc, 0, out)
        self.assertIn("nested-ok", out)
        self.assertEqual(self.sh("podman info --format '{{index .Store.GraphStatus \"Native Overlay Diff\"}}'").stdout.strip(), "true")
        self.assertEqual(self.sh("cat " + MARKER).stdout.strip(), "false")

        # 2. the poison of the real box: the runtime folder is gone, then one probe on a graph root that cannot do native overlay (the container's own
        #    overlay file system) caches "no"; the next command on the real graph root falls back to fuse-overlayfs and writes the marker
        self.sh("rm -rf /tmp/storage-run-$(id -u); podman --root /tmp/poison-root info > /dev/null 2>&1; podman info > /dev/null 2>&1; true")
        self.assertEqual(self.sh("cat " + MARKER).stdout.strip(), "true")
        rc, out = self.run_nested()
        self.assertNotEqual(rc, 0, "the poison did not take: " + out)
        self.assertIn("fuse", out, out)

        # 3. the next start of the box repairs it
        self.assertEqual(podman("restart", "-t", "10", self.name, timeout=120).returncode, 0)
        self.assertEqual(self.ready(), "ok", self.sh("tail -30 ~/.local/state/swarmbox/serve.log").stdout)
        self.assertIn("removed the stale marker", self.sh("cat ~/.local/state/swarmbox/serve.log").stdout)
        self.assertEqual(self.sh("cat " + MARKER).stdout.strip(), "false")
        rc, out = self.run_nested()
        self.assertEqual(rc, 0, out)
        self.assertIn("nested-ok", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
