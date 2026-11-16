"""`swarmbox-addon new`. The skeleton must pass `validate` at once.
Run with: python3 -W error tests/test_addon_new.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_addon_install import Base  # noqa: E402


class New(Base):
    def test_skeleton_under_the_user_level_validates_and_is_executable(self):
        r = self.addon("new", "myaddon")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.user, "myaddon")
        self.assertEqual(sorted(os.listdir(d)), ["addon.conf", "install.sh"])
        self.assertTrue(os.access(os.path.join(d, "install.sh"), os.X_OK))
        self.assertIn(d, r.stdout)
        with open(os.path.join(d, "addon.conf")) as f:
            conf = f.read()
        for key in ("SCHEMA=", "NAME=myaddon", "DESCRIPTION=", "VERSION=", "COMMANDS="):
            self.assertIn(key, conf)
        v = self.addon("validate")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertIn("myaddon", v.stdout)
        # and the manifest is readable by the other commands
        listing = self.addon("list")
        self.assertIn("myaddon", listing.stdout)

    def test_skeleton_installer_stops_with_a_clear_message_until_edited(self):
        self.addon("new", "myaddon")
        r = self.addon("install", "myaddon")
        self.assertEqual(r.returncode, 69)
        self.assertIn("edit", r.stderr.lower())
        self.assertFalse(os.path.exists(os.path.join(self.addons, "myaddon")))

    def test_refuses_an_existing_name_at_either_level_and_a_taken_command(self):
        self.managed()                                   # image level 'demo' provides demo
        r = self.addon("new", "demo")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already exists", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.user, "demo")))
        self.addon("new", "myaddon")
        conf = os.path.join(self.user, "myaddon", "addon.conf")
        with open(conf) as f:
            before = f.read()
        r = self.addon("new", "myaddon")
        self.assertEqual(r.returncode, 1)
        with open(conf) as f:
            self.assertEqual(f.read(), before)
        # a name that is a command of another addon
        from test_addon_manifest import make_addon
        make_addon(self.image, "multi", COMMANDS='"multi demo2"')
        r = self.addon("new", "demo2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already provided by", r.stderr)

    def test_bad_names_and_usage(self):
        for bad in ("Upper", "-x", "a/b", "../x", "", "a b", ".hidden"):
            with self.subTest(name=bad):
                self.assertEqual(self.addon("new", bad).returncode, 64)
        for args in (("new",), ("new", "a", "b"), ("new", "a", "--bogus"), ("new", "a", "--dir")):
            self.assertEqual(self.addon(*args).returncode, 64, args)
        self.assertEqual(os.listdir(self.user), [])

    def test_dir_option_and_repo_option(self):
        out = os.path.join(self.base, "elsewhere")
        r = self.addon("new", "myaddon", "--dir", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.access(os.path.join(out, "myaddon", "install.sh"), os.X_OK))
        self.assertEqual(self.addon("validate", out).returncode, 0)
        repo = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(repo, "container", "addons"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "container", "scripts",
                                                 "swarmbox-addon.sh"), "new", "repoaddon", "--repo"],
                           env=self.env(), capture_output=True, text=True, cwd=repo, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(repo, "container", "addons", "repoaddon", "addon.conf")))
        self.assertEqual(self.addon("validate", os.path.join(repo, "container", "addons")).returncode, 0)
        # --repo outside a repository that has container/addons
        r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "container", "scripts",
                                                 "swarmbox-addon.sh"), "new", "x", "--repo"],
                           env=self.env(), capture_output=True, text=True, cwd=self.base, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("container/addons", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
