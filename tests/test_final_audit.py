#!/usr/bin/env python3
"""Slice 6.7: dev/final-audit.sh, the end-of-phase audit of the repository (plan 9, design 13.2).

The script checks, read-only: the working tree has no uncommitted change, no retired path is tracked, the branch is the one
expected, the only tag is v0.1.0, and (when podman exists) no swarmbox-test- container, volume or image is left. It runs here
against throwaway git repositories (a fake podman is put first on PATH), never against the real one.
Run: python3 tests/test_final_audit.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "final-audit.sh")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-audit-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        os.mkdir(self.repo)
        self.git("init", "-q", "-b", "opensource")
        self.write("a.txt", "x\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "init")
        self.git("tag", "v0.1.0")
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        for tool in ("git", "grep", "sort", "tr", "wc", "cat", "head", "sed", "dirname", "basename", "uname"):
            real = shutil.which(tool)
            if real:
                os.symlink(real, os.path.join(self.bin, tool))

    def git(self, *a):
        env = dict(os.environ, **GIT_ENV)
        subprocess.run(["git", "-C", self.repo, *a], check=True, env=env, capture_output=True)

    def write(self, name, text):
        p = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def fake_podman(self, ps="", volume="", images=""):
        p = os.path.join(self.bin, "podman")
        with open(p, "w") as f:
            f.write("#!/bin/sh\ncase \"$1\" in ps) printf '%%s' '%s';; volume) printf '%%s' '%s';; images) printf '%%s' '%s';; esac\n" % (ps, volume, images))
        os.chmod(p, 0o755)

    def run_audit(self, *args):
        env = dict(os.environ, PATH=self.bin, SWARMBOX_AUDIT_REPO=self.repo)
        return subprocess.run(["/bin/sh", SCRIPT, *args], capture_output=True, text=True, env=env, timeout=60)

    def test_exists_and_is_posix_sh(self):
        with open(SCRIPT) as f:
            self.assertEqual(f.readline().rstrip("\n"), "#!/bin/sh")

    def test_clean_repo_passes(self):
        self.fake_podman()
        p = self.run_audit()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("AUDIT OK", p.stdout)

    def test_uncommitted_change_fails(self):
        self.fake_podman()
        self.write("a.txt", "changed\n")
        p = self.run_audit()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL tree", p.stdout)

    def test_untracked_file_fails(self):
        self.fake_podman()
        self.write("new.txt", "n\n")
        self.assertEqual(self.run_audit().returncode, 1)

    def test_retired_path_tracked_fails(self):
        self.fake_podman()
        self.write("lib/ui.sh", "x\n")
        self.git("add", "lib/ui.sh")
        self.git("commit", "-q", "-m", "back")
        p = self.run_audit()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL retired", p.stdout)

    def test_wrong_branch_fails(self):
        self.fake_podman()
        self.git("checkout", "-q", "-b", "other")
        p = self.run_audit()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL branch", p.stdout)

    def test_extra_tag_fails(self):
        self.fake_podman()
        self.git("tag", "v2.0.0")
        p = self.run_audit()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL tags", p.stdout)

    def test_leftover_test_container_fails(self):
        self.fake_podman(ps="swarmbox-test-x\n")
        p = self.run_audit()
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL podman", p.stdout)

    def test_missing_podman_is_skipped_not_failed(self):
        p = self.run_audit()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("SKIP podman", p.stdout)

    def test_script_changes_nothing(self):
        self.fake_podman()
        before = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.run_audit()
        after = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_no_podman_mutation_in_source(self):
        with open(SCRIPT) as f:
            src = f.read()
        for bad in ("podman rm", "podman stop", "podman kill", "prune", "podman rmi", "git reset", "git clean", "tmux"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
