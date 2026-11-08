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
        t = read("THIRD_PARTY_NOTICES.md").lower()
        with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
            d = f.read()
        tools = set()
        for arg in re.findall(r"^ARG (\w+)_VERSION=", d, re.M):
            if arg not in ("CLAUDE_CODE", "OPENCODE"):
                tools.add(arg.lower())
        tools.update(re.findall(r"npm install -g (@[\w-]+/[\w-]+)(?:@\$\{\w+\})?", d))
        for pkg in ("podman", "chromium", "google-cloud-cli", "tmux"):
            self.assertIn(pkg, d)
            tools.add(pkg)
        for marker, name in (("install.python-poetry.org", "poetry"), ("astral.sh/uv", "uv"), ("go.dev/dl", "go")):
            self.assertIn(marker, d)
            tools.add(name)
        self.assertIn("ttyd", tools)
        self.assertIn("starship", tools)
        for tool in sorted(tools):
            self.assertIn(tool.lower(), t, "%s is installed by the Dockerfile but not in the notices" % tool)

    def test_unverified_is_tagged_not_guessed(self):
        t = read("THIRD_PARTY_NOTICES.md")
        self.assertIn("[unverified]", t)
        self.assertIn("[verified:", t)


class ContributingTest(unittest.TestCase):
    def test_required_content(self):
        t = read("CONTRIBUTING.md")
        self.assertIn("python3 tests/test_", t)
        self.assertIn("podman build", t)
        self.assertIn("build.sh", t)
        self.assertIn("swarmbox-test-", t)
        self.assertRegex(t, r"(?i)never .*(live|running) (box|swarmbox)|(live|running) (box|swarmbox).* never|never touch")
        for prefix in ("feat:", "fix:", "test:", "docs:"):
            self.assertIn(prefix, t)

    def test_every_test_file_is_listed(self):
        t = read("CONTRIBUTING.md")
        for name in os.listdir(os.path.join(ROOT, "tests")):
            if re.match(r"test_\w+\.py$", name):
                self.assertIn(name, t, "%s is not described in CONTRIBUTING.md" % name)

    def test_relative_paths_exist(self):
        t = read("CONTRIBUTING.md")
        paths = set(re.findall(r"`((?:tests|docs|container|lib|\.github)/[\w./-]+|[\w-]+\.(?:sh|md|py|yml))`", t))
        self.assertTrue(paths)
        for p in paths:
            if "*" in p or "<" in p or p.startswith("test_"):
                continue
            self.assertTrue(os.path.exists(os.path.join(ROOT, p)), "CONTRIBUTING.md mentions %s, which does not exist" % p)


if __name__ == "__main__":
    unittest.main()
