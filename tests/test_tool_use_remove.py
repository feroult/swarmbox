"""Slice 4b.5: `swarmbox-tool use` and `remove` (design 6.9, 6.11, 6.5; decision D3).

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

    def test_use_the_active_version_is_a_noop_success(self):
        self.two_versions()
        r = self.tool("use", "demo", "2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cur(), "2.0.0")

    def test_uninstalled_version_fails_cleanly_and_changes_nothing(self):
        self.two_versions()
        before = tree_hash(self.tools)
        r = self.tool("use", "demo", "9.9.9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed", r.stderr)
        self.assertIn("install demo --version 9.9.9", r.stderr)
        self.assertEqual(tree_hash(self.tools), before)

    def test_incomplete_version_folder_is_refused(self):
        self.two_versions()
        os.remove(os.path.join(self.tools, "demo", "1.2.3", "bin", "demo"))
        r = self.tool("use", "demo", "1.2.3")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.cur(), "2.0.0")

    def test_unknown_tool_never_installed_tool_and_bad_arguments(self):
        r = self.tool("use", "nope", "1.0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no tool named", r.stderr)
        self.managed()
        r = self.tool("use", "demo", "1.2.3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed", r.stderr)
        for args in (("use",), ("use", "demo"), ("use", "demo", "1", "2")):
            self.assertEqual(self.tool(*args).returncode, 64, args)
        self.assertEqual(self.tool("use", "Bad_Name", "1").returncode, 64)
        self.assertEqual(self.tool("use", "demo", "../x").returncode, 64)
        self.assertEqual(self.tool("use", "demo", "-v").returncode, 64)

    def test_self_updating_tool_is_refused(self):
        make_tool(self.image, "selfy", install=SELF, KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"selfy update"',
                  PROVIDES='"selfy"')
        self.assertEqual(self.tool("install", "selfy").returncode, 0)
        r = self.tool("use", "selfy", "latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("updates itself", r.stderr)

    def test_lock_held_by_someone_else_is_respected(self):
        self.two_versions()
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            r = self.tool("use", "demo", "1.2.3", SWARMBOX_TEST_LOCK_WAIT="1")
        self.assertEqual(r.returncode, 69)
        self.assertIn("another install is running", r.stderr)
        self.assertEqual(self.cur(), "2.0.0")


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

    def test_remove_keeps_other_tools_and_all_versions_go(self):
        self.managed()
        self.managed("other")
        for v in ("1.2.3", "2.0.0"):
            self.tool("install", "demo", "--version", v)
        self.tool("install", "other")
        self.assertEqual(self.tool("remove", "demo").returncode, 0)
        self.assertEqual(os.listdir(self.tools), ["other"])

    def test_remove_a_tool_that_is_not_installed_is_a_clean_noop(self):
        self.managed()
        r = self.tool("remove", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not installed", r.stderr)
        self.assertEqual(self.tool("remove", "nope").returncode, 1)
        for args in (("remove",), ("remove", "demo", "--bogus"), ("remove", "a", "b")):
            self.assertEqual(self.tool(*args).returncode, 64, args)
        self.assertEqual(self.tool("remove", "../x").returncode, 64)

    def test_leftover_folder_of_a_tool_with_no_manifest_is_removable(self):
        os.makedirs(os.path.join(self.tools, "gone", "1.0", "bin"))
        r = self.tool("remove", "gone")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tools, "gone")))

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

    def test_lock_held_by_someone_else_is_respected(self):
        self.managed()
        self.tool("install", "demo")
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            r = self.tool("remove", "demo", SWARMBOX_TEST_LOCK_WAIT="1")
        self.assertEqual(r.returncode, 69)
        self.assertTrue(os.path.isdir(os.path.join(self.tools, "demo")))

    def test_purge_of_an_image_level_manifest_is_refused(self):
        self.managed()
        self.tool("install", "demo")
        r = self.tool("remove", "demo", "--purge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("part of the image", r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.tools, "demo")))
        self.assertTrue(os.path.isfile(os.path.join(self.image, "demo", "tool.conf")))

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

    def test_plain_remove_of_a_user_level_tool_keeps_manifest_and_shims(self):
        self.managed(level=self.user)
        self.tool("link", "--user")
        self.tool("install", "demo")
        self.assertEqual(self.tool("remove", "demo").returncode, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.user, "demo", "tool.conf")))
        shims = os.path.join(self.home, ".local", "share", "swarmbox", "shims")
        self.assertTrue(os.path.lexists(os.path.join(shims, "demo")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
