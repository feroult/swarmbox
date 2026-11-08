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

    def test_the_fingerprint_is_recorded_at_build(self):
        self.managed()
        self.assertEqual(self.tool("install", "demo", "--image", SWARMBOX_TEST_NODE_MAJOR="24", SWARMBOX_TEST_LIBC="glibc").returncode, 0)
        with open(os.path.join(self.state, "demo", "1.2.3", ".swarmbox-env")) as f:
            text = f.read()
        for line in ("ARCH=amd64", "NODE_MAJOR=24", "LIBC=glibc", "VERSION=1.2.3"):
            self.assertIn(line, text.splitlines())

    def test_run_uses_the_image_install_without_the_installer_and_without_network(self):
        self.managed()
        self.assertEqual(self.tool("install", "demo", "--image").returncode, 0)
        n = self.installs()
        r = self.run_demo("a b", "c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["[a b]", "[c]"])
        self.assertEqual(self.installs(), n, "run installed again")
        self.assertFalse(os.path.exists(self.tools), "run created a workspace install")

    def test_list_and_doctor_see_the_image_install(self):
        self.managed()
        self.tool("install", "demo", "--image")
        out = self.tool("list").stdout
        row = [x for x in out.splitlines() if x.startswith("demo")][0]
        self.assertIn("installed (1.2.3)", row)
        d = self.tool("doctor")
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        self.assertRegex(d.stdout, r"demo\s+ok")

    def test_a_complete_workspace_install_wins_over_the_image_one(self):
        self.managed()
        self.tool("install", "demo", "--image")
        self.managed(VERSION="2.0.0")
        self.assertEqual(self.tool("install", "demo").returncode, 0)
        with open(os.path.join(self.tools, "demo", "2.0.0", "bin", "demo"), "w") as f:
            f.write("#!/bin/sh\necho WORKSPACE\n")
        r = self.run_demo()
        self.assertEqual(r.stdout.strip(), "WORKSPACE")

    def test_an_incomplete_workspace_install_does_not_shadow_the_image_one(self):
        self.managed()
        self.tool("install", "demo", "--image")
        self.assertEqual(self.tool("install", "demo", "--force").returncode, 0)
        os.remove(os.path.join(self.tools, "demo", "1.2.3", "bin", "demo"))
        r = self.run_demo("x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[x]")
        self.assertIn(self.state, self.records()[0][0])

    def test_removing_the_workspace_install_falls_back_to_the_image_one(self):
        self.managed()
        self.tool("install", "demo", "--image")
        self.tool("install", "demo", "--force")
        self.assertEqual(self.tool("remove", "demo").returncode, 0)
        n = self.installs()
        r = self.run_demo()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.installs(), n)

    def test_install_without_image_flag_is_not_skipped_by_an_image_install_when_forced(self):
        self.managed()
        self.tool("install", "demo", "--image")
        n = self.installs()
        self.assertEqual(self.tool("install", "demo", "--force").returncode, 0)
        self.assertEqual(self.installs(), n + 1)
        self.assertTrue(os.path.isdir(os.path.join(self.tools, "demo", "1.2.3")))

    def test_survives_recreation_the_image_state_is_not_in_the_workspace(self):
        # a reset replaces the container and keeps the workspace: with the same image state and a new, empty workspace the tool still runs
        self.managed()
        self.tool("install", "demo", "--image")
        fresh = os.path.join(self.base, "home2")
        os.makedirs(fresh)
        env = self.env(HOME=fresh)
        r = self.tool("run", "demo", "demo", "--", "ok", env=env)
        self.assertEqual(r.stdout.strip(), "[ok]", r.stderr)

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

    def test_failed_self_image_install_leaves_nothing(self):
        self.selfy()
        r = self.tool("install", "selfy", "--image", FAKE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "selfy")))

    def test_unknown_name_fails_with_a_nonzero_status(self):
        r = self.tool("install", "nonesuch", "--image")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no tool named", r.stderr)

    def test_image_install_does_not_run_prepare(self):
        d = self.managed()
        marker = os.path.join(self.base, "prepared")
        with open(os.path.join(d, "prepare.sh"), "w") as f:
            f.write("echo x >> %s\n" % marker)
        self.assertEqual(self.tool("install", "demo", "--image").returncode, 0)
        self.assertFalse(os.path.exists(marker), "prepare.sh ran at build")
        self.assertEqual(self.tool("prepare").returncode, 0)
        self.assertTrue(os.path.exists(marker), "serve step 7 (prepare) does not see the image install")

    def test_usage_lists_the_image_option(self):
        r = self.tool()
        self.assertEqual(r.returncode, 64)
        self.assertIn("--image", r.stderr)

    def test_shim_dispatch_reaches_the_image_install(self):
        scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "container", "scripts")
        tool_sh, shim_sh = os.path.abspath(os.path.join(scripts, "swarmbox-tool.sh")), os.path.abspath(os.path.join(scripts, "swarmbox-shim.sh"))
        self.managed()
        shims = os.path.join(self.base, "shims")
        mgr = os.path.join(self.base, "mgr")
        with open(mgr, "w") as f:
            f.write('#!/bin/sh\nexec bash %s "$@"\n' % tool_sh)
        os.chmod(mgr, 0o755)
        env = self.env(SWARMBOX_TEST_IMAGE_SHIMS=shims, SWARMBOX_TEST_USER_SHIMS=os.path.join(self.base, "ushims"), SWARMBOX_TEST_TOOL=mgr)
        subprocess.run(["bash", tool_sh, "install", "demo", "--image"], env=env, check=True, capture_output=True)
        subprocess.run(["bash", tool_sh, "link", "--system"], env=env, check=True, capture_output=True)
        self.assertTrue(os.path.islink(os.path.join(shims, "demo")))
        os.remove(os.path.join(shims, "demo"))
        os.symlink(shim_sh, os.path.join(shims, "demo"))
        r = subprocess.run([os.path.join(shims, "demo"), "z"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "[z]", r.stderr)


if __name__ == "__main__":
    unittest.main()
