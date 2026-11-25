"""The prepare.sh of the claude addon: it seeds the status line of the box in ~/.claude/settings.json, once, without overwriting the user.

A fake HOME in a temporary folder. Run: python3 tests/fast/test_addon_claude.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

ADDON = os.path.join(ROOT, "container", "addons", "claude")
PREPARE = os.path.join(ADDON, "prepare.sh")
LIB = os.path.join(ROOT, "container", "scripts")
STATUSLINE = {"type": "command", "command": "swarmbox-statusline"}


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="claude-prepare-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        os.makedirs(self.home)
        self.settings = os.path.join(self.home, ".claude", "settings.json")

    def run_prepare(self):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": LIB, "TMPDIR": self.base}
        return subprocess.run(["bash", PREPARE], env=e, capture_output=True, text=True, timeout=30, cwd=self.home)

    def read(self):
        with open(self.settings, encoding="utf-8") as f:
            return json.load(f)

    def write(self, doc):
        os.makedirs(os.path.dirname(self.settings), exist_ok=True)
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def test_seeds_the_status_line_with_mode_600(self):
        r = self.run_prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)
        self.assertEqual(self.read(), {"statusLine": STATUSLINE})

    def test_keeps_every_key_the_user_has_and_adds_the_status_line(self):
        self.write({"theme": "dark", "skipDangerousModePermissionPrompt": True})
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read(), {"theme": "dark", "skipDangerousModePermissionPrompt": True, "statusLine": STATUSLINE})

    def test_the_users_own_status_line_wins(self):
        mine = {"type": "command", "command": "/my/line.sh"}
        self.write({"statusLine": mine})
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read(), {"statusLine": mine})

    def test_seeds_only_once_so_a_removed_status_line_stays_removed(self):
        self.assertEqual(self.run_prepare().returncode, 0)
        self.write({"theme": "dark"})
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read(), {"theme": "dark"})
        os.unlink(self.settings)
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read(), {"statusLine": STATUSLINE})

    def test_a_broken_settings_file_is_left_untouched_and_reported(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write("{not json")
        r = self.run_prepare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a JSON object", r.stderr)
        with open(self.settings, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")


class StaticTest(unittest.TestCase):
    def test_the_script_is_executable_and_passes_bash_n_and_shellcheck(self):
        self.assertTrue(os.access(PREPARE, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", PREPARE]).returncode, 0)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", PREPARE], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
