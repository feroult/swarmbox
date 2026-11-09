"""Slice 7.6: dev/release-check.sh, the read-only check the owner runs before tagging v2.0.0 (design 10.4, plan section 10).

A fixture repository (a mktemp folder, its own git repository on branch opensource) satisfies every condition; the script
passes on it. Each violated condition is then made in a fresh copy and the script must exit 1 with a FAIL line that names
the condition. The script must never change anything: the fixture (files and .git) is hashed before and after every run.
Run: python3 tests/test_release_check.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_IMAGE_REPO  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "release-check.sh")

REQUIRED = ["README.md", "LICENSE", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md", "CONTRIBUTING.md",
            "THIRD_PARTY_NOTICES.md", "docs/security-review.md", "docs/release-checklist.md", "docs/design.md",
            ".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/dependabot.yml", ".grype.yaml"]

DESIGN = "# Design\n\n- The first public version is `2.0.0`; `<org>` is a placeholder.\n"
CHANGELOG = "# Changelog\n\n## [2.0.0] - Unreleased\n\n### Added\n\n- things\n"
REVIEW = ("# Security review\n\n| ID | Severity | Location | Finding | Status | Test |\n|---|---|---|---|---|---|\n"
          "| SR-01 | low | `a` | x | fixed | t |\n| SR-02 | info | `b` | y | documented | t |\n")
WORKFLOW = "name: x\non:\n  push:\n    tags: ['v*.*.*']\njobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo hi\n"


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return subprocess.run(["git", "-C", repo] + list(args), env=env, check=True, capture_output=True, text=True).stdout


def write(repo, name, text):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_repo(parent):
    repo = tempfile.mkdtemp(prefix="relcheck-", dir=parent)
    git(repo, "init", "-q", "-b", "opensource")
    for name in REQUIRED:
        write(repo, name, "text\n")
    write(repo, "docs/design.md", DESIGN)
    write(repo, "CHANGELOG.md", CHANGELOG)
    write(repo, "docs/security-review.md", REVIEW)
    write(repo, "THIRD_PARTY_NOTICES.md", "# Notices\n\nAll packages listed.\n")
    for wf in (".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/dependabot.yml"):
        write(repo, wf, WORKFLOW)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    return repo


def tree_hash(repo):
    h = hashlib.sha256()
    for base, dirs, files in os.walk(repo):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(base, f)
            h.update(os.path.relpath(p, repo).encode())
            if os.path.islink(p):
                h.update(os.readlink(p).encode())
            else:
                with open(p, "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def run(repo, **extra):
    env = dict(os.environ, SWARMBOX_RELEASE_REPO=repo, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    env.update(extra)
    return subprocess.run(["sh", SCRIPT], env=env, capture_output=True, text=True)


class ReleaseCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="swarmbox-test-relcheck-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self):
        return make_repo(self.tmp)

    def commit(self, repo, msg="change"):
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg)

    def assertFails(self, r, name):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"(?m)^FAIL %s " % name, r.stdout)
        self.assertIn("RELEASE CHECK FAILED", r.stdout)

    def test_script_exists_and_is_posix_sh(self):
        self.assertTrue(os.path.isfile(SCRIPT), "dev/release-check.sh is missing")
        with open(SCRIPT, encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), "#!/bin/sh")

    def test_passes_on_a_good_fixture_and_prints_one_line_per_condition(self):
        repo = self.fresh()
        r = run(repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RELEASE CHECK OK", r.stdout)
        for name in ("tree", "branch", "version", "changelog", "notices", "security-review", "files", "workflows", "tag", "owner-todo"):
            self.assertRegex(r.stdout, r"(?m)^OK %s " % name, name)
        self.assertNotRegex(r.stdout, r"(?m)^FAIL")

    def test_never_modifies_anything(self):
        for mutate in (lambda repo: None, lambda repo: write(repo, "dirty.txt", "x")):
            repo = self.fresh()
            mutate(repo)
            before = tree_hash(repo)
            run(repo)
            self.assertEqual(tree_hash(repo), before)

    def test_dirty_tree(self):
        repo = self.fresh()
        write(repo, "README.md", "changed\n")
        self.assertFails(run(repo), "tree")
        repo = self.fresh()
        write(repo, "untracked.txt", "x")
        self.assertFails(run(repo), "tree")

    def test_wrong_branch(self):
        repo = self.fresh()
        git(repo, "checkout", "-q", "-b", "feature")
        r = run(repo)
        self.assertFails(r, "branch")
        self.assertIn("feature", r.stdout)
        self.assertEqual(run(repo, SWARMBOX_RELEASE_BRANCH="feature").returncode, 0)

    def test_missing_changelog_entry(self):
        repo = self.fresh()
        write(repo, "CHANGELOG.md", "# Changelog\n\n## [1.9.0] - 2020-01-01\n")
        self.commit(repo)
        r = run(repo)
        self.assertFails(r, "changelog")
        self.assertIn("2.0.0", r.stdout)

    def test_design_and_changelog_versions_differ(self):
        repo = self.fresh()
        write(repo, "CHANGELOG.md", "# Changelog\n\n## [2.1.0] - Unreleased\n\n## [2.0.0] - 2020-01-01\n")
        self.commit(repo)
        self.assertFails(run(repo), "version")

    def test_design_without_a_version(self):
        repo = self.fresh()
        write(repo, "docs/design.md", "# Design\n")
        self.commit(repo)
        self.assertFails(run(repo), "version")

    def test_unverified_left_in_the_notices(self):
        repo = self.fresh()
        write(repo, "THIRD_PARTY_NOTICES.md", "# Notices\n\nlicense of foo [unverified]\n")
        self.commit(repo)
        self.assertFails(run(repo), "notices")

    def test_open_finding_in_the_security_review(self):
        repo = self.fresh()
        write(repo, "docs/security-review.md", REVIEW + "| SR-03 | high | `c` | z | open | none |\n")
        self.commit(repo)
        r = run(repo)
        self.assertFails(r, "security-review")
        self.assertIn("SR-03", r.stdout)

    def test_security_review_without_a_table(self):
        repo = self.fresh()
        write(repo, "docs/security-review.md", "# Security review\n\nall fine\n")
        self.commit(repo)
        self.assertFails(run(repo), "security-review")

    def test_every_missing_release_file_is_named(self):
        for name in REQUIRED:
            if name in ("docs/design.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md", "docs/security-review.md") or name.endswith(".yml"):
                continue          # these have their own checks; a missing one fails those too
            repo = self.fresh()
            git(repo, "rm", "-q", name)
            git(repo, "commit", "-q", "-m", "rm")
            r = run(repo)
            self.assertFails(r, "files")
            self.assertIn(name, r.stdout)

    def test_missing_workflow_is_a_files_failure(self):
        repo = self.fresh()
        git(repo, "rm", "-q", ".github/workflows/release.yml")
        git(repo, "commit", "-q", "-m", "rm")
        r = run(repo)
        self.assertFails(r, "files")
        self.assertIn("release.yml", r.stdout)

    def test_workflow_that_does_not_parse(self):
        repo = self.fresh()
        write(repo, ".github/workflows/release.yml", "name: x\njobs:\n  a: [unclosed\n")
        self.commit(repo)
        self.assertFails(run(repo), "workflows")

    def test_tag_already_exists(self):
        repo = self.fresh()
        git(repo, "tag", "v2.0.0")
        r = run(repo)
        self.assertFails(r, "tag")
        self.assertIn("v2.0.0", r.stdout)

    def test_owner_placeholders_fail_and_the_org_placeholder_only_warns(self):
        repo = self.fresh()
        write(repo, "SECURITY.md", "Contact [OWNER-TODO: address]\n")
        self.commit(repo)
        r = run(repo)
        self.assertFails(r, "owner-todo")
        self.assertIn("SECURITY.md", r.stdout)
        repo = self.fresh()
        write(repo, "README.md", ("podman run " + DEFAULT_IMAGE_REPO + ":2.0.0 init\n"))
        self.commit(repo)
        r = run(repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"(?m)^WARN org-placeholder ")

    def test_several_failures_are_all_reported(self):
        repo = self.fresh()
        git(repo, "checkout", "-q", "-b", "feature")
        git(repo, "tag", "v2.0.0")
        write(repo, "x.txt", "x")
        r = run(repo)
        self.assertEqual(r.returncode, 1)
        for name in ("tree", "branch", "tag"):
            self.assertRegex(r.stdout, r"(?m)^FAIL %s " % name)
        self.assertIn("RELEASE CHECK FAILED 3", r.stdout)

    def test_not_a_git_repository(self):
        d = tempfile.mkdtemp(prefix="relcheck-nogit-", dir=self.tmp)
        r = run(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL", r.stdout)

    def test_the_real_repository_is_not_modified_by_a_run(self):
        # Read-only on the real repository too: the tracked-file listing and the index are unchanged.
        before = subprocess.run(["git", "-C", ROOT, "ls-files", "-s"], capture_output=True, text=True).stdout
        index = os.path.join(ROOT, ".git", "index")
        mtime = os.stat(index).st_mtime_ns if os.path.isfile(index) else None
        subprocess.run(["sh", SCRIPT], env=dict(os.environ, SWARMBOX_RELEASE_REPO=ROOT), capture_output=True, text=True)
        after = subprocess.run(["git", "-C", ROOT, "ls-files", "-s"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)
        if mtime is not None:
            self.assertEqual(os.stat(index).st_mtime_ns, mtime)


if __name__ == "__main__":
    unittest.main()
