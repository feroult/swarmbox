"""Release policy documents of Phase 7, slice 7.1: SECURITY.md, CODE_OF_CONDUCT.md, CHANGELOG.md.

Checks: the files exist and are not empty; SECURITY.md has the reporting section (with the one marked owner placeholder),
the supported versions, the no-telemetry statement word for word as the README's Privacy section, both log paths, the
sandbox limits of design 11 and the D26 trust sentence; CHANGELOG.md is in Keep a Changelog style with a 2.0.0 entry that
names every feature group, the deferred-to-2.1 items and the v0.1.0 migration note, and its relative links resolve; the
code of conduct is the Contributor Covenant with only the documented owner placeholder; no product code names an
analytics host (the policy of design 12.5).
Run: python3 tests/test_release_docs.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

PLACEHOLDER = re.compile(r"\[OWNER-TODO: [^\]]+\]")
ANALYTICS_HOSTS = ("google-analytics.com", "googletagmanager.com", "segment.io", "segment.com", "mixpanel.com", "amplitude.com",
                   "sentry.io", "datadoghq.com", "posthog.com", "plausible.io", "hotjar.com", "bugsnag.com", "newrelic.com",
                   "telemetry.", "stats.")


def read(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        raise AssertionError("%s does not exist" % name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def privacy_statement():
    """The README's Privacy paragraph up to the log paths, whitespace-normalised."""
    sec = re.search(r"^## Privacy\n(.*?)(?=^## )", read("README.md"), re.M | re.S).group(1)
    first = sec.strip().split("Logs stay on your machine")[0]
    return " ".join(first.split())


class FilesExistTest(unittest.TestCase):
    def test_non_empty(self):
        for name in ("SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md", "CONTRIBUTING.md"):
            self.assertGreater(len(read(name).strip()), 200, name)


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.t = read("SECURITY.md")

    def test_policy_and_paths(self):
        self.assertIn("telemetry", self.t)
        self.assertIn("<workspace>/.local/state/swarmbox", self.t)
        self.assertIn("host:~/.local/state/swarmbox", self.t)
        for name in ("serve.log", "health", "web-terminal.log", "notices"):
            self.assertIn(name, self.t)

    def test_statement_matches_readme(self):
        flat = " ".join(self.t.split())
        self.assertIn(privacy_statement(), flat)

    def test_sections(self):
        for h in ("Reporting a vulnerability", "Supported versions", "What the sandbox protects", "Trust in the signed image", "Logs and telemetry"):
            self.assertRegex(self.t, r"(?m)^## %s" % re.escape(h))
        self.assertRegex(self.t, r"2\.0\.x")
        self.assertIn("D26", self.t)
        self.assertRegex(self.t, r"(?i)does not protect")
        for limit in ("sudo", "workspace", "SSH key", "127.0.0.1", "token"):
            self.assertIn(limit, self.t)

    def test_one_marked_placeholder_and_no_invented_address(self):
        self.assertEqual(len(PLACEHOLDER.findall(self.t)), 1)
        rest = PLACEHOLDER.sub("", self.t)
        self.assertNotRegex(rest, r"[\w.+-]+@[\w-]+\.[\w.]+")


class ConductTest(unittest.TestCase):
    def test_covenant_and_placeholder(self):
        t = read("CODE_OF_CONDUCT.md")
        self.assertIn("Contributor Covenant", t)
        self.assertIn("Our Pledge", t)
        self.assertIn("Enforcement Guidelines", t)
        self.assertIn("https://www.contributor-covenant.org", t)
        self.assertEqual(len(PLACEHOLDER.findall(t)), 1)
        rest = PLACEHOLDER.sub("", t)
        self.assertNotIn("[INSERT", rest)
        self.assertNotRegex(rest, r"[\w.+-]+@[\w-]+\.[\w.]+")


class ChangelogTest(unittest.TestCase):
    def setUp(self):
        self.t = read("CHANGELOG.md")

    def test_keep_a_changelog_shape(self):
        self.assertIn("keepachangelog.com", self.t)
        self.assertRegex(self.t, r"(?m)^## \[2\.0\.0\] - Unreleased")
        sec = re.search(r"^## \[2\.0\.0\].*?(?=^## \[|\Z)", self.t, re.M | re.S).group(0)
        for h in ("### Added", "### Changed", "### Removed", "### Deferred to 2.1", "### Migrating from v0.1.0"):
            self.assertIn(h, sec)
        self.assertIn("v0.1.0", sec)
        self.assertIn(".swarmbox/", sec)
        self.assertIn("swarmbox init", sec)
        self.assertRegex(self.t, r"(?m)^\[2\.0\.0\]: ")

    def test_feature_groups(self):
        low = self.t.lower()
        for word in ("host helper", "nested podman", "swarmbox-tool", "mcp", "remote", "xdg", "signed", "shared session",
                     "web terminal", "migration", "no telemetry", "claude code", "opencode", "gemini", "gcloud"):
            self.assertIn(word, low, word)

    def test_links_resolve(self):
        for target in re.findall(r"\]\(([^)\s]+)\)", self.t):
            if re.match(r"[a-z]+:", target):
                continue
            self.assertTrue(os.path.exists(os.path.join(ROOT, target.split("#")[0])), target)


class NoAnalyticsTest(unittest.TestCase):
    def test_product_code_names_no_analytics_host(self):
        files = [os.path.join(ROOT, "cloudflare-setup.py"), os.path.join(ROOT, "Dockerfile")]
        for base, _, names in os.walk(os.path.join(ROOT, "container")):
            files += [os.path.join(base, n) for n in names]
        self.assertGreater(len(files), 20)
        bad = []
        for p in files:
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read().lower()
            except (UnicodeDecodeError, OSError):
                continue
            for h in ANALYTICS_HOSTS:
                if re.search(r"https?://[^\s'\"]*%s" % re.escape(h), text) or re.search(r"[\w.-]*%s[\w.-]*\.(com|io|net)" % re.escape(h.rstrip(".")), text) and h.endswith((".com", ".io")):
                    bad.append((os.path.relpath(p, ROOT), h))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
