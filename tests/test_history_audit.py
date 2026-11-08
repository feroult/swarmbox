"""History audit of Phase 1, slice 1.5: the fallback scanner tests/audit_history.py and the report docs/history-audit.md.

The scanner is tested against a throwaway git repository built in a mktemp directory. All fake secrets are assembled at run
time so that this file itself holds no secret-shaped string.
Run: python3 tests/test_history_audit.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers import ROOT  # noqa: E402

SCANNER = os.path.join(HERE, "audit_history.py")

PRIVATE_KEY = "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA " + "PRIVATE KEY-----\n"
GH_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
OLD_SECRET = "sk-" + "ant-api03-" + "Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lm"
BRANCH_SECRET = "gh" + "s_" + "Q9w8E7r6T5y4U3i2O1p0A9s8D7f6G5h4J3k2"
TAG_SECRET = "AI" + "za" + "SyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q"
EMAIL = "someone.private@example.org"


def git(repo, *args, env=None):
    e = dict(os.environ, GIT_AUTHOR_NAME="A B", GIT_AUTHOR_EMAIL=EMAIL, GIT_COMMITTER_NAME="A B",
             GIT_COMMITTER_EMAIL=EMAIL, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    e.update(env or {})
    return subprocess.run(["git", "-C", repo] + list(args), check=True, capture_output=True, text=True, env=e).stdout


def commit(repo, files, msg):
    for name, content in files.items():
        p = os.path.join(repo, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(content)
    git(repo, "add", "--", *files)
    git(repo, "commit", "-q", "-m", msg)


def scan(repo, *extra):
    return subprocess.run([sys.executable, "-I", SCANNER, repo, "--json"] + list(extra), capture_output=True, text=True)


def snapshot(repo):
    out = []
    for d, _, fs in os.walk(repo):
        for n in fs:
            p = os.path.join(d, n)
            st = os.stat(p)
            out.append((p, st.st_size, st.st_mtime_ns))
    return sorted(out)


class ScannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sb-audit-test-")
        cls.repo = os.path.join(cls.tmp, "r")
        os.makedirs(cls.repo)
        git(cls.repo, "init", "-q", "-b", "main")
        commit(cls.repo, {"README.md": "hello\n"}, "init")
        commit(cls.repo, {"keys/deploy.txt": PRIVATE_KEY}, "add key")
        commit(cls.repo, {"conf.py": 'GITHUB_TOKEN = "%s"\nowner = "%s"\n' % (GH_TOKEN, EMAIL)}, "add token and email")
        commit(cls.repo, {"old/creds.txt": 'api_key = "%s"\n' % OLD_SECRET}, "add old secret")
        git(cls.repo, "rm", "-q", "-r", "old")
        git(cls.repo, "commit", "-q", "-m", "delete old")
        git(cls.repo, "checkout", "-q", "-b", "side")
        commit(cls.repo, {"side.txt": "token = %s\n" % BRANCH_SECRET}, "secret on side branch")
        git(cls.repo, "checkout", "-q", "-b", "tagonly")
        commit(cls.repo, {"tag.txt": "key: %s\n" % TAG_SECRET}, "secret reachable by tag only")
        git(cls.repo, "tag", "t1")
        git(cls.repo, "checkout", "-q", "main")
        git(cls.repo, "branch", "-D", "tagonly")
        commit(cls.repo, {".env": "A=1\n"}, "add env file")
        commit(cls.repo, {"aws.txt": "id = %s\n" % AWS_KEY}, "aws")
        before = snapshot(cls.repo)
        cls.proc = scan(cls.repo)
        cls.after = snapshot(cls.repo)
        cls.before = before
        cls.out = cls.proc.stdout
        cls.data = json.loads(cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def classes_in(self, path):
        return {f["class"] for f in self.data["findings"] if f["path"] == path}

    def test_exit_status_one_when_secrets_found(self):
        self.assertEqual(self.proc.returncode, 1, self.proc.stderr)

    def test_private_key_found(self):
        self.assertIn("private-key", self.classes_in("keys/deploy.txt"))

    def test_token_and_email_found(self):
        self.assertIn("github-token", self.classes_in("conf.py"))
        self.assertIn("email", self.classes_in("conf.py"))

    def test_deleted_file_secret_found_with_commit(self):
        hits = [f for f in self.data["findings"] if f["path"] == "old/creds.txt"]
        self.assertTrue(hits)
        self.assertRegex(hits[0]["commit"], r"^[0-9a-f]{40}$")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "old")))

    def test_other_branch_and_tag_only_found(self):
        self.assertIn("github-token", self.classes_in("side.txt"))
        self.assertIn("gcp-api-key", self.classes_in("tag.txt"))

    def test_aws_and_env_file_name(self):
        self.assertIn("aws-access-key", self.classes_in("aws.txt"))
        self.assertIn("sensitive-filename", self.classes_in(".env"))

    def test_report_never_contains_full_secret(self):
        blob = self.out + self.proc.stderr
        for s in (GH_TOKEN, AWS_KEY, OLD_SECRET, BRANCH_SECRET, TAG_SECRET, "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu"):
            self.assertNotIn(s, blob)
            self.assertNotIn(s[8:], blob)
        tok = [f for f in self.data["findings"] if f["class"] == "github-token" and f["path"] == "conf.py"][0]
        self.assertTrue(tok["redacted"].startswith(GH_TOKEN[:4]))

    def test_text_mode_also_redacts(self):
        p = subprocess.run([sys.executable, "-I", SCANNER, self.repo], capture_output=True, text=True)
        self.assertNotIn(GH_TOKEN, p.stdout + p.stderr)
        self.assertIn("github-token", p.stdout)

    def test_identities_listed(self):
        self.assertIn("A B <%s>" % EMAIL, self.data["identities"])

    def test_does_not_write_into_scanned_repo(self):
        self.assertEqual(self.before, self.after)

    def test_scope_counts(self):
        self.assertEqual(self.data["scope"]["head"], git(self.repo, "rev-parse", "HEAD").strip())
        self.assertEqual(self.data["scope"]["commits"], int(git(self.repo, "rev-list", "--all", "--count")))


class CleanRepoTest(unittest.TestCase):
    def test_clean_repo_no_secret_findings(self):
        tmp = tempfile.mkdtemp(prefix="sb-audit-test-")
        try:
            git(tmp, "init", "-q", "-b", "main")
            commit(tmp, {"a.txt": "nothing to see\n", "b.py": "print('hi')\n"}, "one")
            p = scan(tmp)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertEqual([f for f in data["findings"] if f["severity"] == "secret"], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "docs", "history-audit.md")
        if not os.path.isfile(path):
            raise AssertionError("docs/history-audit.md does not exist")
        with open(path, encoding="utf-8") as f:
            cls.text = f.read()

    def heading(self, word):
        self.assertRegex(self.text, r"(?im)^#{2,3} .*\b%s\b" % word, "no section about %s" % word)

    def test_sections(self):
        for w in ("method", "tool", "scope", "findings", "identities", "recommendation", "limitations"):
            self.heading(w)

    def test_states_tool_version_head_and_count(self):
        self.assertRegex(self.text, r"gitleaks.{0,40}\d+\.\d+\.\d+")
        self.assertRegex(self.text, r"\b[0-9a-f]{40}\b")
        self.assertRegex(self.text, r"\b\d{3} commits\b")

    def test_states_owner_action_and_no_rewrite(self):
        self.assertRegex(self.text, r"(?i)owner")
        self.assertRegex(self.text, r"(?i)manual")
        self.assertIn("Phase 7", self.text)

    def test_report_holds_no_secret_shaped_string(self):
        import audit_history
        for line_no, line in enumerate(self.text.splitlines(), 1):
            for cls, rx in audit_history.SECRET_PATTERNS:
                self.assertIsNone(rx.search(line), "line %d matches %s" % (line_no, cls))


if __name__ == "__main__":
    unittest.main()
