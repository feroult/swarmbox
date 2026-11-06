"""Tests for swarmbox-pubkey (container/scripts/ssh-key.sh): the persistent SSH key for git.

Run with: python3 tests/test_ssh_key.py   (needs ssh-keygen)
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

from helpers import ROOT

SCRIPT = os.path.join(ROOT, "container", "scripts", "ssh-key.sh")
SSH_CONF = os.path.join(ROOT, "container", "config", "ssh-swarmbox.conf")


def read(path):
    with open(path) as f:
        return f.read()


class SshKey(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.ssh = os.path.join(self.home, ".ssh")
        self.key = os.path.join(self.ssh, "id_ed25519")

    def run_script(self, *args):
        env = dict(os.environ, HOME=self.home)
        env.pop("SWARMBOX_SSH_DIR", None)
        return subprocess.run(["bash", SCRIPT, *args], env=env, capture_output=True, text=True)

    def fingerprint(self):
        out = subprocess.run(["ssh-keygen", "-lf", self.key + ".pub"], capture_output=True, text=True).stdout
        return out.split()[1]

    def test_creates_a_private_key_in_the_home_on_first_run(self):
        r = self.run_script("--ensure")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(self.key))
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.ssh).st_mode), 0o700)
        self.assertTrue(read(self.key + ".pub").startswith("ssh-ed25519 "))
        self.assertIn("created", r.stdout)

    def test_never_overwrites_an_existing_key(self):
        self.run_script("--ensure")
        before = (read(self.key), self.fingerprint())
        r = self.run_script("--ensure")
        self.assertEqual((read(self.key), self.fingerprint()), before)
        self.assertNotIn("created", r.stdout)
        self.assertIn(before[1], r.stdout, "the short line carries the fingerprint")

    def test_the_public_key_is_rebuilt_from_the_private_one(self):
        self.run_script("--ensure")
        pub = read(self.key + ".pub").split()[:2]
        os.remove(self.key + ".pub")
        self.run_script("--ensure")
        self.assertEqual(read(self.key + ".pub").split()[:2], pub)

    def test_without_flags_it_shows_the_public_key_and_where_to_add_it(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        pub = read(self.key + ".pub").strip()
        self.assertIn(pub, r.stdout)
        self.assertIn("github.com", r.stdout)
        self.assertIn("deploy key", r.stdout)
        self.assertNotIn("PRIVATE KEY", r.stdout, "the private key is never printed")
        self.assertNotIn(read(self.key).splitlines()[1], r.stdout)

    def test_git_hosts_are_trusted_on_first_use(self):
        with open(SSH_CONF) as f:
            text = f.read()
        self.assertIn("StrictHostKeyChecking accept-new", text)
        for host in ("github.com", "gitlab.com", "bitbucket.org"):
            self.assertIn(host, text)
        self.assertNotIn("StrictHostKeyChecking no", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
