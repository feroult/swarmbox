"""`swarmbox-tool new`. The skeleton must pass `validate` at once.
Run with: python3 -W error tests/test_tool_new.py
"""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tool_install import Base  # noqa: E402


class New(Base):
    def test_skeleton_under_the_user_level_validates_and_is_executable(self):
        r = self.tool("new", "mytool")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.user, "mytool")
        self.assertEqual(sorted(os.listdir(d)), ["install.sh", "tool.conf"])
        self.assertTrue(os.access(os.path.join(d, "install.sh"), os.X_OK))
        self.assertIn(d, r.stdout)
        v = self.tool("validate")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertIn("mytool", v.stdout)
        # and the manifest is readable by the other commands
        listing = self.tool("list")
        self.assertIn("mytool", listing.stdout)

    def test_skeleton_installer_stops_with_a_clear_message_until_edited(self):
        self.tool("new", "mytool")
        r = self.tool("install", "mytool")
        self.assertEqual(r.returncode, 69)
        self.assertIn("edit", r.stderr.lower())
        self.assertFalse(os.path.exists(os.path.join(self.tools, "mytool")))

    def test_refuses_an_existing_name_at_either_level_and_a_taken_command(self):
        self.managed()                                   # image level 'demo' provides demo
        r = self.tool("new", "demo")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already exists", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.user, "demo")))
        self.tool("new", "mytool")
        conf = os.path.join(self.user, "mytool", "tool.conf")
        with open(conf) as f:
            before = f.read()
        r = self.tool("new", "mytool")
        self.assertEqual(r.returncode, 1)
        with open(conf) as f:
            self.assertEqual(f.read(), before)
        # a name that is a command of another tool
        from test_tool_manifest import make_tool
        make_tool(self.image, "multi", PROVIDES='"multi demo2"')
        r = self.tool("new", "demo2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already provided by", r.stderr)

    def test_bad_names_and_usage(self):
        for bad in ("Upper", "-x", "a/b", "../x", "", "a b", ".hidden"):
            with self.subTest(name=bad):
                self.assertEqual(self.tool("new", bad).returncode, 64)
        for args in (("new",), ("new", "a", "b"), ("new", "a", "--bogus"), ("new", "a", "--dir")):
            self.assertEqual(self.tool(*args).returncode, 64, args)
        self.assertEqual(os.listdir(self.user), [])

    def test_dir_option_and_repo_option(self):
        out = os.path.join(self.base, "elsewhere")
        r = self.tool("new", "mytool", "--dir", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.access(os.path.join(out, "mytool", "install.sh"), os.X_OK))
        self.assertEqual(self.tool("validate", out).returncode, 0)
        repo = os.path.join(self.base, "repo")
        os.makedirs(os.path.join(repo, "container", "tools"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "container", "scripts",
                                                 "swarmbox-tool.sh"), "new", "repotool", "--repo"],
                           env=self.env(), capture_output=True, text=True, cwd=repo, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(repo, "container", "tools", "repotool", "tool.conf")))
        self.assertEqual(self.tool("validate", os.path.join(repo, "container", "tools")).returncode, 0)
        # --repo outside a repository that has container/tools
        r = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "container", "scripts",
                                                 "swarmbox-tool.sh"), "new", "x", "--repo"],
                           env=self.env(), capture_output=True, text=True, cwd=self.base, timeout=30)
        self.assertEqual(r.returncode, 1)
        self.assertIn("container/tools", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
