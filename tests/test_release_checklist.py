"""Slice 7.6: docs/release-checklist.md, the README pitch, the B20 recheck kit and the name-check record.

Checks: the checklist exists and lists every owner action, each with a command or a place to look; it never tells the owner
to run history-rewriting commands without saying they are owner-run and unverified; the README gives the install line within
the first screen; the B20 kit in docs/owner-checks.md has the exact commands and B20 stays open in the design.
Run: python3 tests/test_release_checklist.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


ACTIONS = [
    ("visibility", r"visibility"),
    ("copyright holder", r"copyright holder"),
    ("contacts", r"contacts?"),
    ("author identities", r"author identit"),
    ("history", r"history"),
    ("name decision", r"name decision"),
    ("push", r"\bpush\b"),
    ("first CI run", r"first CI run"),
    ("B30", r"B30"),
    ("B31", r"B31"),
    ("B28", r"B28"),
    ("registry visibility", r"registry visibility|package visibility"),
    ("tag", r"v2\.0\.0"),
    ("B20 recheck", r"B20"),
]


class ChecklistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "docs", "release-checklist.md")
        if not os.path.isfile(path):
            raise AssertionError("docs/release-checklist.md does not exist")
        cls.text = read("docs", "release-checklist.md")

    def test_every_owner_action_is_listed(self):
        for label, rx in ACTIONS:
            self.assertRegex(self.text, r"(?i)" + rx, label)

    def test_numbered_items_each_have_a_command_or_a_place_to_look(self):
        items = re.split(r"(?m)^### ", self.text)[1:]
        self.assertGreaterEqual(len(items), 10)
        for item in items:
            title = item.splitlines()[0]
            has_cmd = "```" in item or re.search(r"`[^`]+`", item)
            has_place = re.search(r"(?i)where to look|look at|see |\.md|settings", item)
            self.assertTrue(has_cmd and has_place, "no command or place in: " + title)

    def test_fences_balanced(self):
        self.assertEqual(self.text.count("```") % 2, 0)

    def test_name_check_result_is_dated_and_honest(self):
        self.assertRegex(self.text, r"2026-11-0\d")
        self.assertIn("not legal advice", self.text)
        for word in ("npm", "PyPI", "GitHub", "trademark"):
            self.assertIn(word, self.text)
        self.assertIn("dev/name-check.sh", self.text)

    def test_history_commands_are_marked_owner_run_and_unverified(self):
        sec = self.text.split("History", 1)[1]
        self.assertIn("owner", sec.lower())
        self.assertIn("[unverified", sec)
        self.assertIn("never `git push --all`", sec.replace("**", "").lower())

    def test_release_check_is_referenced_and_exists(self):
        self.assertIn("dev/release-check.sh", self.text)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "dev", "release-check.sh")))

    def test_no_org_replacement_before_the_name_decision(self):
        # The README no longer uses the placeholder (it gives local-build commands); the name decision stays open in the docs.
        self.assertNotIn("<org>", read("README.md"))
        self.assertIn("<org>", read("docs", "uninstall.md"))


class ReadmePitchTest(unittest.TestCase):
    def test_pitch_names_podman_and_the_limit_is_stated(self):
        lines = read("README.md").splitlines()
        self.assertTrue(lines[0].startswith("# SwarmBox"))
        self.assertIn("Podman", "\n".join(lines[:4]))
        self.assertIn("shares the kernel", read("README.md"))

    def test_quick_start_is_in_the_readme(self):
        self.assertRegex(read("README.md"), r"(?m)^## Quick start")


class B20KitTest(unittest.TestCase):
    def test_owner_checks_has_the_registry_recheck_and_the_clean_machine_walkthrough(self):
        t = read("docs", "owner-checks.md")
        self.assertRegex(t, r"(?m)^## .*B20")
        sec = t.split("B20", 1)[1]
        for needle in ("swarmbox update", "swarmbox update --to", "podman manifest inspect", "cosign verify",
                       "ghcr.io/feroult/swarmbox", "swarmbox reset"):
            self.assertIn(needle, sec, needle)
        self.assertRegex(t, r"(?m)^## Clean machine")
        self.assertRegex(t, r"(?i)README only")

    def test_b20_stays_open_in_the_design(self):
        d = read("docs", "design.md")
        rows = [ln for ln in d.splitlines() if re.match(r"\| B20 \|", ln)]
        self.assertTrue(rows)
        self.assertIn("[unverified", rows[0])


if __name__ == "__main__":
    unittest.main()
