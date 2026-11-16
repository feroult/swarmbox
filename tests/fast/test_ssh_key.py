"""swarmbox-pubkey (container/scripts/ssh-key.sh): the persistent SSH key for git, as the serve step 5 runs it (`--ensure`) and as
`swarmbox-entrypoint pubkey` shows it. Created once, never overwritten, writes only under the test HOME. The serve step that calls it, and
its failure as a warning, are in test_serve_steps.py.

Run with: python3 tests/fast/test_ssh_key.py   (needs ssh-keygen)
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "container", "scripts", "ssh-key.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
SSH_CONF = os.path.join(ROOT, "container", "config", "ssh-swarmbox.conf")


def read(path):
    with open(path) as f:
        return f.read()


def tree(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            out[os.path.relpath(p, root)] = None if os.path.isdir(p) else read_bytes(p)
    return out


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class SshKey(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="pubkey-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        os.mkdir(self.home)
        self.bindir = os.path.join(self.base, "bin")
        os.mkdir(self.bindir)
        os.symlink(SCRIPT, os.path.join(self.bindir, "swarmbox-pubkey"))
        self.ssh = os.path.join(self.home, ".ssh")
        self.key = os.path.join(self.ssh, "id_ed25519")

    def env(self):
        return {"PATH": self.bindir + ":" + os.environ["PATH"], "HOME": self.home, "TMPDIR": self.base}

    def run_script(self, *args):
        return subprocess.run(["swarmbox-pubkey", *args], env=self.env(), capture_output=True, text=True, timeout=30)

    def test_creates_the_key_once_with_private_modes_and_changes_nothing_after(self):
        r = self.run_script("--ensure")
        self.assertEqual(r.returncode, 0, r.stderr)
        snap = tree(self.home)
        self.assertEqual(sorted(snap), [".ssh", ".ssh/id_ed25519", ".ssh/id_ed25519.pub"], "nothing outside the key and its folder")
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.ssh).st_mode), 0o700)
        self.assertTrue(read(self.key + ".pub").startswith("ssh-ed25519 "))
        self.assertIn("created", r.stdout)
        r = self.run_script("--ensure")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("created", r.stdout)
        self.assertEqual(tree(self.home), snap)

    def test_never_overwrites_a_key_that_is_there_and_derives_a_missing_public_half(self):
        os.makedirs(self.ssh, mode=0o700)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "mine", "-f", self.key], check=True)
        os.unlink(self.key + ".pub")   # only the private half exists
        before = read(self.key)
        r = self.run_script("--ensure")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(self.key), before)
        private_pub = subprocess.run(["ssh-keygen", "-y", "-f", self.key], capture_output=True, text=True).stdout.split()[:2]
        self.assertEqual(read(self.key + ".pub").split()[:2], private_pub, "derived, not regenerated")
        fp = subprocess.run(["ssh-keygen", "-lf", self.key + ".pub"], capture_output=True, text=True).stdout.split()[1]
        self.assertIn(fp, r.stdout, "the short line carries the fingerprint")

    def test_ensure_fails_when_the_key_cannot_be_created(self):
        os.chmod(self.home, 0o500)
        self.addCleanup(os.chmod, self.home, 0o700)
        if os.access(self.home, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        self.assertNotEqual(self.run_script("--ensure").returncode, 0)

    def test_without_flags_it_shows_the_public_key_and_where_to_add_it_and_never_the_private_one(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(read(self.key + ".pub").strip(), r.stdout)
        self.assertIn("github.com", r.stdout)
        self.assertIn("deploy key", r.stdout)
        self.assertNotIn("PRIVATE KEY", r.stdout)
        self.assertNotIn(read(self.key).splitlines()[1], r.stdout)

    def test_the_entrypoint_pubkey_command_prints_the_public_key(self):
        self.run_script("--ensure")
        r = subprocess.run(["bash", ENTRYPOINT, "pubkey"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(read(self.key + ".pub").strip(), r.stdout)
        self.assertIn("deploy key", r.stdout)


class GitHostsTest(unittest.TestCase):
    def test_git_hosts_are_trusted_on_first_use(self):
        text = read(SSH_CONF)
        self.assertIn("StrictHostKeyChecking accept-new", text)
        for host in ("github.com", "gitlab.com", "bitbucket.org"):
            self.assertIn(host, text)
        self.assertNotIn("StrictHostKeyChecking no", text)


if __name__ == "__main__":
    unittest.main()
