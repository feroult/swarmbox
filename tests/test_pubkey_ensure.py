"""Slice 2.5: `swarmbox-pubkey --ensure` as step 5 of `serve` and `swarmbox-entrypoint pubkey` (design 4.1, 3.7, 9.3).
The program is container/scripts/ssh-key.sh (v0.1.0's script, installed as swarmbox-pubkey). tests/test_ssh_key.py keeps
covering its details; this file covers the 2.0 contract: created once, idempotent, never overwritten, writes only under
the test HOME, output that fits serve.log, and the entrypoint path.
Run with: python3 tests/test_pubkey_ensure.py   (needs ssh-keygen)
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "container", "scripts", "ssh-key.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")


def read(path):
    with open(path) as f:
        return f.read()


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tree(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            out[os.path.relpath(p, root)] = None if os.path.isdir(p) else sha(p)
    return out


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class PubkeyEnsure(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="pubkey-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        os.mkdir(self.home)
        self.bindir = os.path.join(self.base, "bin")
        os.mkdir(self.bindir)
        os.symlink(SCRIPT, os.path.join(self.bindir, "swarmbox-pubkey"))
        self.key = os.path.join(self.home, ".ssh", "id_ed25519")

    def env(self):
        return {"PATH": self.bindir + ":" + os.environ["PATH"], "HOME": self.home, "TMPDIR": self.base}

    def ensure(self):
        return subprocess.run(["swarmbox-pubkey", "--ensure"], env=self.env(), capture_output=True, text=True, timeout=30)

    def test_creates_the_key_once_and_is_idempotent(self):
        r1 = self.ensure()
        self.assertEqual(r1.returncode, 0, r1.stderr)
        snap = tree(self.home)
        self.assertEqual(sorted(snap), [".ssh", ".ssh/id_ed25519", ".ssh/id_ed25519.pub"])
        self.assertIn("created", r1.stdout)
        for _ in range(3):
            r = self.ensure()
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("created", r.stdout)
            self.assertEqual(tree(self.home), snap)

    def test_never_overwrites_a_key_that_is_there(self):
        os.makedirs(os.path.join(self.home, ".ssh"), mode=0o700)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mine", "-f", self.key], check=True)
        os.unlink(self.key + ".pub")   # only the private half exists
        before = read(self.key)
        r = self.ensure()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(self.key), before)
        self.assertTrue(read(self.key + ".pub").startswith("ssh-ed25519 "))   # derived, not regenerated
        private_pub = subprocess.run(["ssh-keygen", "-y", "-f", self.key], capture_output=True, text=True).stdout.split()[:2]
        self.assertEqual(read(self.key + ".pub").split()[:2], private_pub)

    def test_writes_only_under_the_test_home_and_with_the_right_modes(self):
        outside = os.path.join(self.base, "outside")
        os.mkdir(outside)
        before = tree(self.base)
        self.ensure()
        after = tree(self.base)
        new = sorted(set(after) - set(before))
        self.assertTrue(all(p.startswith("home" + os.sep) for p in new), new)
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.key)).st_mode), 0o700)

    def test_ensure_output_is_short_and_has_no_private_material(self):
        r = self.ensure()
        self.assertLessEqual(len(r.stdout.splitlines()), 3)
        self.assertNotIn("PRIVATE KEY", r.stdout + r.stderr)
        self.assertIn("SHA256:", r.stdout)

    def test_ensure_fails_with_1_when_the_key_cannot_be_created(self):
        os.chmod(self.home, 0o500)
        self.addCleanup(os.chmod, self.home, 0o700)
        if os.access(self.home, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        r = self.ensure()
        self.assertNotEqual(r.returncode, 0)

    def test_entrypoint_pubkey_prints_the_public_key(self):
        self.ensure()
        r = subprocess.run(["bash", ENTRYPOINT, "pubkey"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        pub = read(self.key + ".pub").strip()
        self.assertIn(pub, r.stdout)
        self.assertIn("deploy key", r.stdout)

    def test_entrypoint_pubkey_creates_the_key_when_missing(self):
        r = subprocess.run(["bash", ENTRYPOINT, "pubkey"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(read(self.key + ".pub").strip() in r.stdout)

    def test_serve_step_5_calls_ensure_and_a_failure_is_a_warning(self):
        with open(ENTRYPOINT) as f:
            text = f.read()
        self.assertIn("swarmbox-pubkey --ensure", text)
        self.assertIn("could not create the Git SSH key", text)

    def test_dockerfile_installs_it_as_swarmbox_pubkey(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("COPY container/scripts/ssh-key.sh /usr/local/bin/swarmbox-pubkey", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
