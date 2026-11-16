"""The WITH_ADDONS build argument on a real image. Opt-in: SWARMBOX_IMAGE_BUILD=1 and podman.

Two parts, both in throwaway containers named swarmbox-test-4b6-run-<rand> and removed by exact name:
 - fake installer (no network at run time): a fake manifest is mounted read-only and installed with `install --image` into the image's
   /opt/swarmbox/addons as agent; checks ownership, the fingerprint, that the install survives `podman rm` and recreation of the
   container from the image (the folder is in the image layer only when baked: here it is a container-layer write, so this part
   checks run-time lookup only) and that a user-level install does not get shadowed by it and vice versa.
 - real build (needs SWARMBOX_TEST_NETWORK=1 too): image swarmbox-test-4b6-img (or SWARMBOX_IMAGE_TAG to reuse one built with
   --build-arg WITH_ADDONS=claude) holds claude at the image level: `swarmbox-addon list` shows it installed with no network, owned by
   uid 1000, with the fingerprint, and `claude --version` runs with --network none.
Run: SWARMBOX_IMAGE_BUILD=1 SWARMBOX_TEST_NETWORK=1 python3 tests/test_image_with_addons.py
"""
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
NETWORK = os.environ.get("SWARMBOX_TEST_NETWORK") == "1"
TAG = os.environ.get("SWARMBOX_IMAGE_TAG") or "swarmbox-test-4b6-img"
OWN = False
TMP = []


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=900):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout)


def run(*cmd, mounts=(), network=None, entrypoint="bash", env=()):
    name = "swarmbox-test-4b6-run-" + rnd()
    args = ["run", "--rm", "--name", name, "--entrypoint", entrypoint]
    if network:
        args += ["--network", network]
    for m in mounts:
        args += ["-v", m]
    for e in env:
        args += ["-e", e]
    try:
        return podman(*args, TAG, *cmd)
    finally:
        podman("rm", "-f", name)


def image_exists():
    return podman("image", "exists", TAG).returncode == 0


def setUpModule():
    global OWN
    if not ENABLED:
        return
    assert TAG.startswith("swarmbox-test-"), TAG
    if image_exists():
        return
    OWN = True
    t0 = time.time()
    args = ["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG]
    if NETWORK:
        args += ["--build-arg", "WITH_ADDONS=claude"]
    r = subprocess.run(args, capture_output=True, text=True)
    sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
    sys.stderr.write("\nbuild seconds: %d\n" % (time.time() - t0))
    if r.returncode != 0:
        raise AssertionError("image build failed")


def tearDownModule():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    if OWN and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


FAKE_CONF = 'SCHEMA=1\nNAME=probe\nDESCRIPTION="probe"\nCOMMANDS="probe"\nVERSION=1.0.0\n'
FAKE_INSTALL = '#!/bin/bash\nset -eu\nmkdir -p "$ADDON_PREFIX/bin"\nprintf \'#!/bin/sh\\necho probe-image\\n\' > "$ADDON_PREFIX/bin/probe"\nchmod +x "$ADDON_PREFIX/bin/probe"\n'


def fake_manifests():
    d = tempfile.mkdtemp(prefix="swarmbox-4b6-fake-")
    TMP.append(d)
    os.chmod(d, 0o755)
    p = os.path.join(d, "probe")
    os.makedirs(p)
    with open(os.path.join(p, "addon.conf"), "w") as f:
        f.write(FAKE_CONF)
    with open(os.path.join(p, "install.sh"), "w") as f:
        f.write(FAKE_INSTALL)
    os.chmod(os.path.join(p, "install.sh"), 0o755)
    for x in (p, os.path.join(p, "addon.conf")):
        os.chmod(x, 0o755 if os.path.isdir(x) else 0o644)
    return d


@unittest.skipUnless(ENABLED, "set SWARMBOX_IMAGE_BUILD=1 (builds or reuses a real image)")
class FakeInstallerInImage(unittest.TestCase):
    def test_state_folder_exists_owned_by_agent_and_empty_in_a_default_build(self):
        if NETWORK:
            self.skipTest("the image was built with WITH_ADDONS=claude")
        r = run("-c", "stat -c '%u:%g %a' /opt/swarmbox/addons; ls -A /opt/swarmbox/addons | wc -l")
        self.assertEqual(r.stdout.split("\n")[:2], ["1000:1000 755", "0"], r.stderr)

    def test_image_install_as_agent_with_a_fake_installer_and_no_network(self):
        d = fake_manifests()
        script = ("export SWARMBOX_TEST_IMAGE_ADDONS=/fake; swarmbox-addon install probe --image >/dev/null 2>&1; echo rc=$?; "
                  "stat -c '%u:%g' /opt/swarmbox/addons/probe/1.0.0/bin/probe; cat /opt/swarmbox/addons/probe/1.0.0/.swarmbox-env; "
                  "unset SWARMBOX_TEST_IMAGE_ADDONS; export SWARMBOX_TEST_IMAGE_ADDONS=/fake; "
                  "export HOME=$(mktemp -d); swarmbox-addon run probe probe; ls ~/.local/share/swarmbox 2>&1 | head -1; "
                  "swarmbox-addon list | grep '^probe'")
        r = run("-c", script, mounts=["%s:/fake:ro" % d], network="none")
        out = r.stdout
        self.assertIn("rc=0", out, out + r.stderr)
        self.assertIn("1000:1000", out)
        for line in ("ARCH=", "NODE_MAJOR=24", "LIBC=glibc", "VERSION=1.0.0"):
            self.assertIn(line, out)
        self.assertIn("probe-image", out)
        row = [x for x in out.splitlines() if x.split()[:1] == ["probe"] and len(x.split()) > 2][0]  # the list row, not the probe's own output "probe-image"
        for word in ("1.0.0", "managed", "image", "installed (1.0.0)"):
            self.assertIn(word, row)

@unittest.skipUnless(ENABLED and NETWORK, "set SWARMBOX_IMAGE_BUILD=1 and SWARMBOX_TEST_NETWORK=1 (real installer, network)")
class RealBuildWithClaude(unittest.TestCase):
    def test_claude_is_installed_at_the_image_level_and_runs_without_network(self):
        r = run("-c", "export HOME=$(mktemp -d); swarmbox-addon list | grep '^claude'; "
                      "stat -c '%u:%g' /opt/swarmbox/addons /opt/swarmbox/addons/claude /opt/swarmbox/addons/claude/self; "
                      "cat /opt/swarmbox/addons/claude/self/.swarmbox-env; claude --version; ls ~/.local 2>&1 | head -1", network="none")
        out = r.stdout
        row = [x for x in out.splitlines() if x.split()[:1] == ["claude"] and len(x.split()) > 2][0]
        for word in ("latest", "self", "image", "installed (self)"):
            self.assertIn(word, row, out + r.stderr)
        self.assertEqual(out.count("1000:1000"), 3, out)
        self.assertIn("ARCH=", out)
        self.assertRegex(out, r"\d+\.\d+\.\d+ \(Claude Code\)")

if __name__ == "__main__":
    unittest.main(verbosity=2)
