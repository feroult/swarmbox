"""`swarmbox-tool use` and `remove`.

Fake installers only (the fixtures of test_tool_install.py); HOME, both manifest levels and the lock are temp paths.
Run with: python3 -W error tests/test_tool_use_remove.py
"""
import fcntl
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tool_install import MANAGED as MANAGED_INSTALL, Base, SELF  # noqa: E402
from test_tool_link import tree_hash  # noqa: E402
from test_tool_manifest import make_tool  # noqa: E402


class UseBase(Base):
    def env(self, **extra):
        e = super().env(**extra)
        e.setdefault("SWARMBOX_TEST_NODE_MAJOR", "24")
        e.setdefault("SWARMBOX_TEST_LIBC", "glibc")
        return e

    def cur(self, name="demo"):
        try:
            return os.readlink(os.path.join(self.tools, name, "current"))
        except OSError:
            return None


class Use(UseBase):
    def two_versions(self):
        self.managed()
        for v in ("1.2.3", "2.0.0"):
            self.assertEqual(self.tool("install", "demo", "--version", v).returncode, 0)
        self.assertEqual(self.cur(), "2.0.0")

    def test_use_switches_the_current_link(self):
        self.two_versions()
        r = self.tool("use", "demo", "1.2.3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cur(), "1.2.3")
        self.assertEqual(os.path.islink(os.path.join(self.tools, "demo", "current")), True)
        self.assertEqual(self.tool("use", "demo", "2.0.0").returncode, 0)
        self.assertEqual(self.cur(), "2.0.0")
        self.assertEqual(self.installs(), 2)  # no installer ran for the switches

    def test_uninstalled_version_fails_cleanly_and_changes_nothing(self):
        self.two_versions()
        before = tree_hash(self.tools)
        r = self.tool("use", "demo", "9.9.9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed", r.stderr)
        self.assertIn("install demo --version 9.9.9", r.stderr)
        self.assertEqual(tree_hash(self.tools), before)

    def test_self_updating_tool_is_refused(self):
        make_tool(self.image, "selfy", install=SELF, KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"selfy update"',
                  PROVIDES='"selfy"')
        self.assertEqual(self.tool("install", "selfy").returncode, 0)
        r = self.tool("use", "selfy", "latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("updates itself", r.stderr)

class Remove(UseBase):
    def test_remove_then_run_is_a_fresh_first_use_install(self):
        self.managed()
        self.assertEqual(self.tool("install", "demo").returncode, 0)
        r = self.tool("remove", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tools, "demo")))
        self.assertEqual(self.installs(), 1)
        r = self.tool("run", "demo", "demo", "--", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Installing demo (first use)...", r.stderr)
        self.assertEqual(r.stdout, "[hi]\n")
        self.assertEqual(self.installs(), 2)

    def test_remove_a_self_tool_deletes_its_own_paths_and_nothing_else(self):
        make_tool(self.image, "selfy", install=SELF, KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"selfy update"',
                  PROVIDES='"selfy"')
        self.assertEqual(self.tool("install", "selfy").returncode, 0)
        h = self.home
        keep = []
        for p in (".local/share/other", ".local/state/other", ".cache/other", ".claude", ".local/bin/unrelated"):
            full = os.path.join(h, p)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if p.endswith("unrelated"):
                with open(full, "w") as f:
                    f.write("k")
            else:
                os.makedirs(full, exist_ok=True)
            keep.append(full)
        for p in (".local/state/selfy", ".cache/selfy"):
            os.makedirs(os.path.join(h, p), exist_ok=True)
        r = self.tool("remove", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in (".local/bin/selfy", ".local/share/selfy", ".local/state/selfy", ".cache/selfy", ".local/share/swarmbox/tools/selfy"):
            self.assertFalse(os.path.lexists(os.path.join(h, p)), p)
        for full in keep:
            self.assertTrue(os.path.lexists(full), full)
        r = self.tool("run", "selfy", "selfy", "--", "x")
        self.assertIn("Installing selfy (first use)...", r.stderr)

    def test_a_tool_named_like_swarmbox_never_deletes_the_swarmbox_folders(self):
        make_tool(self.image, "swarmbox", install=SELF, KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"x update"',
                  PROVIDES='"selfy"')
        os.makedirs(os.path.join(self.tools, "swarmbox", "self"))
        with open(os.path.join(self.tools, "swarmbox", "self", ".swarmbox-env"), "w") as f:
            f.write("ARCH=amd64\n")
        marker = os.path.join(self.home, ".local", "share", "swarmbox", "shims")
        os.makedirs(marker, exist_ok=True)
        r = self.tool("remove", "swarmbox")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(marker))
        self.assertFalse(os.path.exists(os.path.join(self.tools, "swarmbox")))

    def test_purge_of_a_user_level_tool_removes_install_manifest_shim_and_index_entry(self):
        self.managed(level=self.user)
        make_tool(self.user, "keeper", install=MANAGED_INSTALL, PROVIDES='"keeper"')
        self.assertEqual(self.tool("link", "--user").returncode, 0)
        self.tool("install", "demo")
        shims = os.path.join(self.home, ".local", "share", "swarmbox", "shims")
        index = os.path.join(self.home, ".local", "share", "swarmbox", "index")
        self.assertTrue(os.path.lexists(os.path.join(shims, "demo")))
        r = self.tool("remove", "demo", "--purge")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.user, "demo")))
        self.assertFalse(os.path.exists(os.path.join(self.tools, "demo")))
        self.assertFalse(os.path.lexists(os.path.join(shims, "demo")))
        self.assertTrue(os.path.lexists(os.path.join(shims, "keeper")))
        with open(index) as f:
            text = f.read()
        self.assertNotIn("demo demo", text)
        self.assertIn("keeper keeper", text)

if __name__ == "__main__":
    unittest.main(verbosity=2)
