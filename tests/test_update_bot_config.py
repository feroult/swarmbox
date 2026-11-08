"""Slice 7.4: the dependency update bot (Dependabot) and the inventory of every pinned version.

Nothing here touches the network. The config is parsed with the same PyYAML approach as tests/test_ci_workflow.py
(importable, else a venv under the temp dir; without a parser the parse tests are skipped and the text tests still run).

The inventory scans the repository for every pin: Dockerfile FROM and ARG *_VERSION lines, the VERSION line of each
container/tools/*/tool.conf, the pinned connector image (host helper and cloudflare-setup.py) and every `uses:` of
.github/workflows. Each pin must be covered by a Dependabot entry (a `uses:` by github-actions, a literal FROM by docker)
or be named in the "Bumping pinned versions" section of CONTRIBUTING.md (the manual-bump list). Whether the Dependabot
entries really open pull requests is [unverified]: it can only be seen on GitHub.
Run: python3 tests/test_update_bot_config.py
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
import test_ci_workflow as _ci  # noqa: E402  (only for its YAML loader)

YAML = _ci.YAML
CONFIG = os.path.join(ROOT, ".github", "dependabot.yml")
TEMPLATE = os.path.join(ROOT, ".github", "pull_request_template.md")
CONTRIB = os.path.join(ROOT, "CONTRIBUTING.md")
SECTION_TITLE = "## Bumping pinned versions"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def contributing_section():
    text = read(CONTRIB)
    i = text.find(SECTION_TITLE)
    if i < 0:
        return ""
    j = text.find("\n## ", i + 5)
    return text[i:j if j > 0 else len(text)]


def inventory():
    """Return a list of (kind, id, where, detail). kind: uses, from, arg, tool, image."""
    pins = []
    for wf in sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.y*ml"))):
        for n, line in enumerate(read(wf).splitlines(), 1):
            m = re.match(r"\s*(?:-\s*)?uses:\s*([^\s#]+)", line)
            if m and not m.group(1).startswith("./"):   # a local reusable workflow has no version to pin
                pins.append(("uses", m.group(1), "%s:%d" % (os.path.relpath(wf, ROOT), n), m.group(1)))
    for n, line in enumerate(read(os.path.join(ROOT, "Dockerfile")).splitlines(), 1):
        m = re.match(r"FROM\s+(\S+)", line)
        if m:
            pins.append(("from", m.group(1), "Dockerfile:%d" % n, m.group(1)))
        m = re.match(r"ARG\s+([A-Z0-9_]+_VERSION)=(\S+)", line)
        if m:
            pins.append(("arg", m.group(1), "Dockerfile:%d" % n, m.group(2)))
    for conf in sorted(glob.glob(os.path.join(ROOT, "container", "tools", "*", "tool.conf"))):
        for n, line in enumerate(read(conf).splitlines(), 1):
            m = re.match(r"VERSION=(\S+)", line)
            if m:
                tool = os.path.basename(os.path.dirname(conf))
                pins.append(("tool", "container/tools/%s/tool.conf" % tool, "%s:%d" % (os.path.relpath(conf, ROOT), n),
                             m.group(1)))
    for rel in ("container/host/swarmbox-host", "cloudflare-setup.py"):
        for n, line in enumerate(read(os.path.join(ROOT, rel)).splitlines(), 1):
            m = re.search(r"((?:docker\.io/)?cloudflare/cloudflared:[A-Za-z0-9._-]+)", line)
            if m and ("DEFAULT" in line):
                pins.append(("image", "cloudflared image", "%s:%d" % (rel, n), m.group(1)))
    return pins


def dependabot_ecosystems(doc):
    return {u["package-ecosystem"]: u for u in doc.get("updates", [])}


class InventoryFindsEverything(unittest.TestCase):
    """The scanner itself: if it found nothing for a category, the coverage test below would pass for nothing."""

    def test_each_category_is_found(self):
        kinds = {}
        for k, i, w, d in inventory():
            kinds.setdefault(k, []).append(i)
        self.assertGreaterEqual(len(kinds.get("uses", [])), 1)
        self.assertIn("node:${NODE_VERSION}-slim", kinds.get("from", []))
        for arg in ("TTYD_VERSION", "STARSHIP_VERSION", "UV_VERSION", "CHROME_DEVTOOLS_MCP_VERSION", "NODE_VERSION"):
            self.assertIn(arg, kinds.get("arg", []))
        for t in ("go", "gcloud", "claude", "poetry", "clasp", "gemini", "opencode"):
            self.assertIn("container/tools/%s/tool.conf" % t, kinds.get("tool", []))
        # the connector image is pinned in two places
        self.assertEqual(len(kinds.get("image", [])), 2)


@unittest.skipUnless(YAML, "no YAML parser available")
class DependabotConfig(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.exists(CONFIG), ".github/dependabot.yml is missing")
        self.doc = YAML.safe_load(read(CONFIG))

    def test_version_2(self):
        self.assertEqual(self.doc.get("version"), 2)

    def test_github_actions_and_docker_ecosystems(self):
        eco = dependabot_ecosystems(self.doc)
        self.assertIn("github-actions", eco)
        self.assertIn("docker", eco)

    def test_every_entry_is_weekly_with_a_directory(self):
        for u in self.doc["updates"]:
            self.assertEqual(u.get("schedule", {}).get("interval"), "weekly", u["package-ecosystem"])
            self.assertTrue(u.get("directory", "").startswith("/"), u["package-ecosystem"])

    def test_no_ecosystem_without_a_manifest(self):
        # an ecosystem with nothing to read is a silent no-op; only list what the repository has
        known = {"github-actions", "docker"}
        self.assertEqual(set(dependabot_ecosystems(self.doc)), known)
        self.assertFalse(glob.glob(os.path.join(ROOT, "package.json")))
        self.assertFalse(glob.glob(os.path.join(ROOT, "requirements*.txt")))

    def test_commit_messages_follow_the_repo_style(self):
        for u in self.doc["updates"]:
            self.assertEqual(u.get("commit-message", {}).get("prefix"), "build", u["package-ecosystem"])

    def test_docker_entry_points_at_the_dockerfile_folder(self):
        self.assertEqual(dependabot_ecosystems(self.doc)["docker"]["directory"], "/")
        self.assertTrue(os.path.exists(os.path.join(ROOT, "Dockerfile")))

    def test_no_secrets_registries_or_remote_settings(self):
        for key in ("registries", "enable-beta-ecosystems"):
            self.assertNotIn(key, self.doc)
        self.assertNotRegex(read(CONFIG), r"(?i)token|password|secret")


class ConfigText(unittest.TestCase):
    """Text checks that run even without a YAML parser."""

    def test_comments_say_gcloud_and_go_bumps_need_the_checksum_script(self):
        t = read(CONFIG)
        self.assertIn("dev/record-checksums.sh", t)
        self.assertIn("gcloud", t)

    def test_comments_say_what_it_cannot_bump(self):
        t = read(CONFIG)
        for word in ("tool.conf", "cloudflared", "CONTRIBUTING.md"):
            self.assertIn(word, t)


class Coverage(unittest.TestCase):
    def setUp(self):
        self.section = contributing_section()

    def covered_by_dependabot(self, kind, ident):
        if kind == "uses":
            return True  # github-actions entry (checked to exist in DependabotConfig)
        if kind == "from":
            return "${" not in ident  # docker reads a literal FROM only, not one built from an ARG
        return False

    def test_every_pin_is_covered_or_in_the_manual_list(self):
        self.assertTrue(self.section, "CONTRIBUTING.md has no '%s' section" % SECTION_TITLE)
        missing = []
        for kind, ident, where, _ in inventory():
            if self.covered_by_dependabot(kind, ident):
                continue
            if "`%s`" % ident not in self.section:
                missing.append("%s (%s)" % (ident, where))
        self.assertEqual(missing, [], "pins neither covered by dependabot.yml nor in the manual-bump list")

    def test_manual_list_names_only_real_pins(self):
        real = {i for _, i, _, _ in inventory()}
        listed = set(re.findall(r"^\| `([^`]+)` \|", self.section, re.M))
        self.assertTrue(listed)
        self.assertEqual(sorted(listed - real), [])

    def test_every_workflow_uses_is_a_version_pin(self):
        for kind, ident, where, _ in inventory():
            if kind == "uses":
                self.assertRegex(ident, r"@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$", where)

    def test_floating_tools_are_declared_floating(self):
        for kind, ident, where, detail in inventory():
            if kind == "tool" and detail == "latest":
                row = [l for l in self.section.splitlines() if l.startswith("| `%s`" % ident)]
                self.assertTrue(row, ident)
                self.assertIn("floating", row[0], ident)

    def test_sha_pinning_decision_is_written_down(self):
        self.assertIn("SHA", self.section)
        self.assertIn("[unverified", self.section)


class ChecksumStepDocumented(unittest.TestCase):
    def test_contributing_mentions_checksum_recording_for_go_and_gcloud(self):
        s = contributing_section()
        self.assertIn("dev/record-checksums.sh go", s)
        self.assertIn("dev/record-checksums.sh gcloud", s)
        self.assertIn("SHA256_amd64", s)

    def test_pull_request_template_reminds_about_the_checksums(self):
        self.assertTrue(os.path.exists(TEMPLATE), ".github/pull_request_template.md is missing")
        t = read(TEMPLATE)
        self.assertIn("dev/record-checksums.sh", t)
        self.assertIn("tool.conf", t)

    def test_dev_script_exists(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "dev", "record-checksums.sh")))


if __name__ == "__main__":
    unittest.main()
