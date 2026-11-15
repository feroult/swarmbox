"""The data of the image smoke test (tests/smoke_image.py, CI only: it builds the image) must follow the tools of the repository: dev/check.sh never builds
the image, so a tool added without its line there fails only on the first image build. Run with: python3 tests/test_smoke_image_data.py"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402


def smoke_commands():
    with open(os.path.join(ROOT, "tests", "smoke_image.py")) as f:
        src = f.read()
    ns = {}
    exec(re.search(r"TOOL_COMMANDS = \{.*?\}\n", src, re.S).group(0), ns)
    return ns["TOOL_COMMANDS"], src


class TestSmokeData(unittest.TestCase):
    def test_every_tool_of_the_repository_has_its_commands_in_the_smoke_test(self):
        commands, _ = smoke_commands()
        found = {}
        for conf in glob.glob(os.path.join(ROOT, "container", "tools", "*", "tool.conf")):
            with open(conf) as f:
                text = f.read()
            name = re.search(r"^NAME=(\S+)", text, re.M).group(1)
            m = re.search(r'^PROVIDES="([^"]*)"', text, re.M)
            found[name] = (m.group(1).split() if m else [name])
        self.assertEqual(sorted(commands), sorted(found))
        for name, provides in found.items():
            if name in ("claude", "gemini", "opencode", "gcloud", "clasp", "go", "poetry"):
                continue          # their commands come from the manifest in other forms (PROVIDES may be a function of the version)
            self.assertEqual(commands[name], provides, name)

    def test_the_wording_counts_the_tools(self):
        commands, src = smoke_commands()
        words = {8: "eight", 9: "nine", 10: "ten"}
        self.assertNotIn(" eight tools" if len(commands) != 8 else " nine tools", src)
        self.assertIn("%s tools" % words[len(commands)], src)

    def test_the_bus_and_the_tabs_are_checked_in_the_image(self):
        _, src = smoke_commands()
        self.assertIn("swarmbox-bus", src.split("def step_box_commands")[1].split("def step_tool_shim")[0])
        self.assertIn("swarmbox-tabs", src.split("def step_box_commands")[1].split("def step_tool_shim")[0])
        self.assertIn("step_box_commands", src.split("STEPS = [")[1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
