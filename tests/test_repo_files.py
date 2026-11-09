"""Repository files of Phase 1, slice 1.1: LICENSE, THIRD_PARTY_NOTICES.md and CONTRIBUTING.md.

Checks: LICENSE is the Apache License 2.0 with its appendix; the notices name ttyd, starship and tmux (each with a license and
a URL) and every tool the Dockerfile installs from a pinned download or a package manager; CONTRIBUTING.md names the test
command, the build command, the swarmbox-test- rule and the never-touch-the-live-box rule, and every relative path it
mentions exists.
Run: python3 tests/test_repo_files.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402


def read(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        raise AssertionError("%s does not exist" % name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def notice_section(text, tool):
    """The part of the notices that starts at the heading of `tool` and ends at the next heading."""
    m = re.search(r"^#{2,3} .*\b%s\b.*$" % re.escape(tool), text, re.M | re.I)
    assert m, "no heading for %s" % tool
    rest = text[m.end():]
    n = re.search(r"^#{1,3} ", rest, re.M)
    return rest[:n.start()] if n else rest


class LicenseTest(unittest.TestCase):
    def test_apache_title_and_appendix(self):
        t = read("LICENSE")
        self.assertTrue(t.lstrip().startswith("Apache License"))
        self.assertIn("Version 2.0, January 2004", t[:300])
        self.assertIn("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", t)
        self.assertIn("APPENDIX: How to apply the Apache License to your work.", t)
        self.assertIn('Licensed under the Apache License, Version 2.0 (the "License");', t)
        self.assertIn("END OF TERMS AND CONDITIONS", t)


class NoticesTest(unittest.TestCase):
    def test_core_tools_have_license_and_url(self):
        t = read("THIRD_PARTY_NOTICES.md")
        for tool in ("ttyd", "starship", "tmux"):
            s = notice_section(t, tool)
            self.assertRegex(s, r"(?i)license:", "%s has no license line" % tool)
            self.assertRegex(s, r"https://\S+", "%s has no URL" % tool)

    def test_every_dockerfile_tool_is_listed(self):
        """The 2.0 Dockerfile and the manifests of container/tools/ (the v0.1.0 Dockerfile is retired, slice 6.2)."""
        t = read("THIRD_PARTY_NOTICES.md").lower()
        tools = set()
        with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
            d = f.read()
        for arg in re.findall(r"^ARG (\w+)_VERSION=", d, re.M):
            if arg not in ("CLAUDE_CODE", "OPENCODE"):
                tools.add(arg.lower().replace("_", "-"))
        tools.update(re.findall(r"npm install -g (@[\w-]+/[\w-]+)(?:@\$\{\w+\})?", d))
        for pkg in ("podman", "chromium", "tmux"):
            self.assertIn(pkg, d)
            tools.add(pkg)
        # the tools v0.1.0 baked into its image are manifests now (name in container/tools -> name in the notices)
        notice_name = {"gcloud": "google-cloud-cli"}
        for name in sorted(os.listdir(os.path.join(ROOT, "container", "tools"))):
            tools.add(notice_name.get(name, name))
        self.assertTrue({"google-cloud-cli", "poetry", "go", "clasp", "gemini"} <= tools, tools)
        tools.discard("node")  # the base image tag, not a download
        self.assertIn("ttyd", tools)
        self.assertIn("starship", tools)
        self.assertIn("chrome-devtools-mcp", tools)
        for tool in sorted(tools):
            self.assertIn(tool.lower(), t, "%s is installed by a Dockerfile but not in the notices" % tool)

    def test_unverified_is_tagged_not_guessed(self):
        t = read("THIRD_PARTY_NOTICES.md")
        self.assertIn("[owner-check:", t)
        self.assertIn("[verified:", t)


class ContributingTest(unittest.TestCase):
    def test_required_content(self):
        t = read("CONTRIBUTING.md")
        self.assertIn("python3 tests/test_", t)
        self.assertIn("podman build", t)
        self.assertIn("dev/dev-build.sh", t)
        self.assertIn("swarmbox-test-", t)
        self.assertRegex(t, r"(?i)never .*(live|running) (box|swarmbox)|(live|running) (box|swarmbox).* never|never touch")
        for prefix in ("feat:", "fix:", "test:", "docs:"):
            self.assertIn(prefix, t)

    def test_relative_paths_exist(self):
        t = read("CONTRIBUTING.md")
        paths = set(re.findall(r"`((?:tests|docs|container|lib|\.github)/[\w./-]+|[\w-]+\.(?:sh|md|py|yml))`", t))
        self.assertTrue(paths)
        for p in paths:
            if "*" in p or "<" in p or p.startswith("test_"):
                continue
            self.assertTrue(os.path.exists(os.path.join(ROOT, p)), "CONTRIBUTING.md mentions %s, which does not exist" % p)


class PolicyFilesTest(unittest.TestCase):
    """Slice 7.1: the policy files exist and CONTRIBUTING.md and the README point at them."""

    def test_present_and_linked(self):
        contributing = read("CONTRIBUTING.md")
        readme = read("README.md")
        for name in ("SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md"):
            self.assertTrue(read(name).strip(), name)
            self.assertIn(name, contributing, name)
            self.assertIn("(%s)" % name, readme, name)

    def test_new_files_have_balanced_fences_and_resolving_links(self):
        for name in ("SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md"):
            t = read(name)
            self.assertEqual(sum(1 for l in t.splitlines() if l.lstrip().startswith("```")) % 2, 0, name)
            for target in re.findall(r"\]\(([^)\s]+)\)", t):
                if not re.match(r"[a-z]+:", target):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, target.split("#")[0])), "%s -> %s" % (name, target))


if __name__ == "__main__":
    unittest.main()
