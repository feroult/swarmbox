"""`swarmbox-addon use` and `remove`.

Fake installers only (the fixtures of test_addon_install.py); HOME, both manifest levels and the lock are temp paths.
Run with: python3 -W error tests/fast/test_addon_use_remove.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from addon_support import Base, MANAGED, SELF, make_addon, tree_hash  # noqa: E402


class UseBase(Base):
    def env(self, **extra):
        e = super().env(**extra)
        e.setdefault("SWARMBOX_TEST_NODE_MAJOR", "24")
        e.setdefault("SWARMBOX_TEST_LIBC", "glibc")
        return e

    def cur(self, name="demo"):
        try:
            return os.readlink(os.path.join(self.addons, name, "current"))
        except OSError:
            return None


class Use(UseBase):
    def two_versions(self):
        self.managed()
        for v in ("1.2.3", "2.0.0"):
            self.assertEqual(self.addon("install", "demo", "--version", v).returncode, 0)
        self.assertEqual(self.cur(), "2.0.0")

    def test_use_switches_the_current_link(self):
        self.two_versions()
        r = self.addon("use", "demo", "1.2.3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cur(), "1.2.3")
        self.assertEqual(os.path.islink(os.path.join(self.addons, "demo", "current")), True)
        self.assertEqual(self.addon("use", "demo", "2.0.0").returncode, 0)
        self.assertEqual(self.cur(), "2.0.0")
        self.assertEqual(self.installs(), 2)  # no installer ran for the switches

    def test_uninstalled_version_fails_cleanly_and_changes_nothing(self):
        self.two_versions()
        before = tree_hash(self.addons)
        r = self.addon("use", "demo", "9.9.9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed", r.stderr)
        self.assertIn("install demo --version 9.9.9", r.stderr)
        self.assertEqual(tree_hash(self.addons), before)

    def test_self_updating_addon_is_refused(self):
        make_addon(self.image, "selfy", install=SELF, VERSION="latest", UPDATE="self", UPDATE_CMD='"selfy update"',
                  COMMANDS='"selfy"')
        self.assertEqual(self.addon("install", "selfy").returncode, 0)
        r = self.addon("use", "selfy", "latest")
        self.assertEqual(r.returncode, 1)
        self.assertIn("updates itself", r.stderr)

class Remove(UseBase):
    def test_remove_then_run_is_a_fresh_first_use_install(self):
        self.managed()
        self.assertEqual(self.addon("install", "demo").returncode, 0)
        r = self.addon("remove", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.addons, "demo")))
        self.assertEqual(self.installs(), 1)
        r = self.addon("run", "demo", "demo", "--", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Installing demo (first use)...", r.stderr)
        self.assertEqual(r.stdout, "[hi]\n")
        self.assertEqual(self.installs(), 2)

    def test_remove_a_self_addon_deletes_its_own_paths_and_nothing_else(self):
        make_addon(self.image, "selfy", install=SELF, VERSION="latest", UPDATE="self", UPDATE_CMD='"selfy update"',
                  COMMANDS='"selfy"')
        self.assertEqual(self.addon("install", "selfy").returncode, 0)
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
        r = self.addon("remove", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        for p in (".local/bin/selfy", ".local/share/selfy", ".local/state/selfy", ".cache/selfy", ".local/share/swarmbox/addons/selfy"):
            self.assertFalse(os.path.lexists(os.path.join(h, p)), p)
        for full in keep:
            self.assertTrue(os.path.lexists(full), full)
        r = self.addon("run", "selfy", "selfy", "--", "x")
        self.assertIn("Installing selfy (first use)...", r.stderr)

    def test_an_addon_named_like_swarmbox_never_deletes_the_swarmbox_folders(self):
        make_addon(self.image, "swarmbox", install=SELF, VERSION="latest", UPDATE="self", UPDATE_CMD='"x update"',
                  COMMANDS='"selfy"')
        os.makedirs(os.path.join(self.addons, "swarmbox", "self"))
        with open(os.path.join(self.addons, "swarmbox", "self", ".swarmbox-env"), "w") as f:
            f.write("ARCH=amd64\n")
        marker = os.path.join(self.home, ".local", "share", "swarmbox", "shims")
        os.makedirs(marker, exist_ok=True)
        r = self.addon("remove", "swarmbox")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(marker))
        self.assertFalse(os.path.exists(os.path.join(self.addons, "swarmbox")))

    def test_purge_of_a_user_level_addon_removes_install_manifest_shim_and_index_entry(self):
        self.managed(level=self.user)
        make_addon(self.user, "keeper", install=MANAGED, COMMANDS='"keeper"')
        self.assertEqual(self.addon("link", "--user").returncode, 0)
        self.addon("install", "demo")
        shims = os.path.join(self.home, ".local", "share", "swarmbox", "shims")
        index = os.path.join(self.home, ".local", "share", "swarmbox", "index")
        self.assertTrue(os.path.lexists(os.path.join(shims, "demo")))
        r = self.addon("remove", "demo", "--purge")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.user, "demo")))
        self.assertFalse(os.path.exists(os.path.join(self.addons, "demo")))
        self.assertFalse(os.path.lexists(os.path.join(shims, "demo")))
        self.assertTrue(os.path.lexists(os.path.join(shims, "keeper")))
        with open(index) as f:
            text = f.read()
        self.assertNotIn("demo demo", text)
        self.assertIn("keeper keeper", text)

class HostileManifests(UseBase):
    """A manifest whose values are paths or globs is refused before anything is removed, created or linked."""

    def test_a_version_that_is_a_path_never_touches_another_install(self):
        self.managed("trav", level=self.user, VERSION="../other")
        precious = os.path.join(self.addons, "other", "1.0", "precious")
        os.makedirs(os.path.dirname(precious))
        with open(precious, "w") as f:
            f.write("keep")
        self.assertNotEqual(self.addon("validate").returncode, 0)
        r = self.addon("install", "trav")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(precious))
        self.assertEqual(self.installs(), 0)

    def test_a_version_of_two_dots_is_refused(self):
        self.managed("trav", level=self.user, VERSION="..")
        r = self.addon("install", "trav")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.addons, ".swarmbox-env")))
        self.assertFalse(os.path.exists(os.path.join(self.addons, "bin")))

    def test_a_command_that_is_a_path_never_deletes_a_file_on_remove(self):
        key = os.path.join(self.home, ".ssh", "id_key")
        os.makedirs(os.path.dirname(key))
        os.makedirs(os.path.join(self.home, ".local", "bin"))
        with open(key, "w") as f:
            f.write("secret")
        make_addon(self.user, "evil", install=SELF, VERSION="latest", UPDATE="self", UPDATE_CMD='"true"',
                  COMMANDS='"../../.ssh/id_key"')
        self.assertNotEqual(self.addon("validate").returncode, 0)
        self.addon("remove", "evil")
        self.assertTrue(os.path.exists(key))

    def test_a_glob_in_commands_is_not_expanded_against_the_folder(self):
        for n in ("ls", "bash", "sudo"):
            with open(os.path.join(self.base, n), "w") as f:
                f.write("x")
        make_addon(self.image, "globby", COMMANDS='"*"')
        r = self.addon("validate")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.addon("link", "--user")
        for d, _, files in os.walk(self.home):
            for n in files:
                self.assertNotIn(n, ("ls", "bash", "sudo"), d)

    def test_current_and_self_are_not_version_names(self):
        self.managed()
        self.assertEqual(self.addon("install", "demo").returncode, 0)
        link = os.readlink(os.path.join(self.addons, "demo", "current"))
        for v in ("current", "self"):
            r = self.addon("install", "demo", "--version", v)
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(os.readlink(os.path.join(self.addons, "demo", "current")), link)
        self.assertEqual(self.addon("list").returncode, 0)
        self.assertNotIn("incomplete", self.addon("list").stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
