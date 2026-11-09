"""Slice 4b.6: tools installed at the image level (design 6.8, 6.11, 10.2): `swarmbox-tool install --image` and the run-time lookup.

`install NAME --image` (what the Dockerfile's WITH_TOOLS loop runs, as the owner of /opt/swarmbox/tools) installs into the image
state folder (test override SWARMBOX_TEST_IMAGE_STATE) instead of the workspace, records the fingerprint, and for an UPDATE=self tool
runs the installer with HOME=<image state>/<name>/home (the workspace home is a bind mount at run time, so it cannot hold an
image-level install). At run time `run`, `list`, `doctor` and the shim find the workspace install first and the image install
second; a workspace install that is incomplete never shadows a complete image install. All installers are fakes.
Run: python3 tests/test_tool_image_level.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tool_install import Base, MANAGED, SELF  # noqa: E402


class ImageLevel(Base):
    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.base, "optstate")  # stands for /opt/swarmbox/tools (does not exist yet)

    def env(self, **extra):
        e = super().env(**extra)
        e["SWARMBOX_TEST_IMAGE_STATE"] = self.state
        return e

    def run_demo(self, *args):
        return self.tool("run", "demo", "demo", "--", *args)

    def test_managed_image_install_goes_to_the_image_state_not_the_workspace(self):
        self.managed()
        r = self.tool("install", "demo", "--image")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.state, "demo", "1.2.3", "bin", "demo")))
        self.assertEqual(os.readlink(os.path.join(self.state, "demo", "current")), "1.2.3")
        self.assertFalse(os.path.exists(self.tools), "the workspace tools folder was created")
        (rec,) = self.records()
        self.assertEqual(rec[0], os.path.join(self.state, "demo", "1.2.3"))

    def test_run_uses_the_image_install_without_the_installer_and_without_network(self):
        self.managed()
        self.assertEqual(self.tool("install", "demo", "--image").returncode, 0)
        n = self.installs()
        r = self.run_demo("a b", "c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["[a b]", "[c]"])
        self.assertEqual(self.installs(), n, "run installed again")
        self.assertFalse(os.path.exists(self.tools), "run created a workspace install")

    def test_a_complete_workspace_install_wins_over_the_image_one(self):
        self.managed()
        self.tool("install", "demo", "--image")
        self.managed(VERSION="2.0.0")
        self.assertEqual(self.tool("install", "demo").returncode, 0)
        with open(os.path.join(self.tools, "demo", "2.0.0", "bin", "demo"), "w") as f:
            f.write("#!/bin/sh\necho WORKSPACE\n")
        r = self.run_demo()
        self.assertEqual(r.stdout.strip(), "WORKSPACE")

    def test_self_tool_image_install_uses_its_own_home_and_runs_from_it(self):
        self.selfy()
        r = self.tool("install", "selfy", "--image")
        self.assertEqual(r.returncode, 0, r.stderr)
        home = os.path.join(self.state, "selfy", "home")
        self.assertTrue(os.access(os.path.join(home, ".local", "bin", "selfy"), os.X_OK))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "selfy")), "wrote the workspace home")
        self.assertEqual(self.records()[0][5], home)
        self.assertTrue(os.path.isfile(os.path.join(self.state, "selfy", "self", ".swarmbox-env")))
        n = self.installs()
        out = self.tool("run", "selfy", "selfy", "--", "hi")
        self.assertEqual(out.stdout.strip(), "[hi]", out.stderr)
        self.assertEqual(self.installs(), n)
        self.assertIn("installed (self)", [x for x in self.tool("list").stdout.splitlines() if x.startswith("selfy")][0])

    def test_failed_image_install_leaves_nothing(self):
        self.managed()
        r = self.tool("install", "demo", "--image", FAKE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "demo", "1.2.3")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "demo", "current")))

if __name__ == "__main__":
    unittest.main()
