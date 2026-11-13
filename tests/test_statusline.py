"""The status line of Claude Code (container/scripts/swarmbox-statusline.sh): what it prints for the JSON that Claude Code hands it.

A real git repository in a temporary folder, a fake HOME so the paths are the same everywhere. Run: python3 tests/test_statusline.py
"""
import colorsys
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "container", "scripts", "swarmbox-statusline.sh")
SGR = re.compile(r"\x1b\[[0-9;]*m")
VIOLET, LAVENDER, FUCHSIA, ROSE, DIM = 147, 189, 177, 204, 245


def plain(text):
    return SGR.sub("", text)


def rgb256(n):
    if n >= 232:
        v = 8 + 10 * (n - 232)
        return (v, v, v)
    n -= 16
    lv = (0, 95, 135, 175, 215, 255)
    return (lv[n // 36], lv[n // 6 % 6], lv[n % 6])


@unittest.skipUnless(shutil.which("jq") and shutil.which("git"), "needs jq and git")
class Statusline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="statusline-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "work", "a", "swarmbox")
        os.makedirs(self.repo)
        git = lambda *a: subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t") + a, cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main", ".")
        with open(os.path.join(self.repo, "f"), "w") as f:
            f.write("x\n")
        git("add", "f")
        git("commit", "-q", "-m", "first")

    def run_line(self, doc, raw=None, **env):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "LANG": "C.UTF-8"}
        e.update(env)
        r = subprocess.run(["bash", SCRIPT], input=raw if raw is not None else json.dumps(doc), env=e, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout.rstrip("\n")

    def doc(self, ctx=34, five=None, week=None, cwd=None, model="Sonnet 5.5"):
        d = {"workspace": {"current_dir": cwd or self.repo}, "model": {"display_name": model}, "context_window": {"used_percentage": ctx}}
        if five is not None or week is not None:
            d["rate_limits"] = {}
            if five is not None:
                d["rate_limits"]["five_hour"] = {"used_percentage": five}
            if week is not None:
                d["rate_limits"]["seven_day"] = {"used_percentage": week}
        return d

    def test_the_line_in_a_repository_with_the_last_two_folders_the_branch_the_model_and_a_bar(self):
        out = plain(self.run_line(self.doc(34.4)))
        self.assertEqual(out, "╶─ …/a/swarmbox ─ main ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34%")

    def test_a_tracked_file_with_changes_adds_the_mark_and_an_untracked_one_does_not(self):
        with open(os.path.join(self.repo, "new"), "w") as f:
            f.write("untracked\n")
        self.assertNotIn(" !", plain(self.run_line(self.doc())))
        with open(os.path.join(self.repo, "f"), "a") as f:
            f.write("changed\n")
        self.assertIn("main ! ─", plain(self.run_line(self.doc())))

    def test_the_home_is_a_tilde_and_a_folder_outside_a_repository_has_no_branch(self):
        self.assertEqual(plain(self.run_line(self.doc(cwd=self.home))), "╶─ ~ ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34%")
        sub = os.path.join(self.home, "notes")
        os.makedirs(sub)
        self.assertEqual(plain(self.run_line(self.doc(cwd=sub))), "╶─ ~/notes ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34%")

    def test_the_limits_appear_only_when_claude_code_reports_them(self):
        self.assertNotIn("5h", plain(self.run_line(self.doc())))
        out = plain(self.run_line(self.doc(82, five=71, week=38)))
        self.assertTrue(out.endswith("▰▰▰▰▰▰▰▰▱▱ 82% ─ 5h 71% ─ 7d 38%"), out)
        self.assertTrue(plain(self.run_line(self.doc(10, five=5))).endswith("▰▱▱▱▱▱▱▱▱▱ 10% ─ 5h 5%"))

    def test_the_color_rises_from_violet_to_fuchsia_at_70_and_to_rose_at_90(self):
        def used(doc):
            return set(int(n) for n in re.findall(r"\x1b\[38;5;(\d+)m", self.run_line(doc)))
        self.assertIn(VIOLET, used(self.doc(69)))
        self.assertNotIn(FUCHSIA, used(self.doc(69)))
        self.assertIn(FUCHSIA, used(self.doc(70)))
        self.assertNotIn(ROSE, used(self.doc(89)))
        self.assertIn(ROSE, used(self.doc(90)))
        # a limit is dim until 70 too, and then it is not
        self.assertNotIn(FUCHSIA, used(self.doc(10, five=69)))
        self.assertIn(FUCHSIA, used(self.doc(10, five=70)))
        self.assertIn(ROSE, used(self.doc(10, week=95)))

    def test_there_is_no_orange_anywhere_in_any_state(self):
        # orange and amber would not be of the box (hue 15 to 50 degrees, with some saturation)
        for ctx, five, week in ((0, None, None), (34, None, None), (70, 70, 70), (82, 71, 38), (95, 93, 64), (100, 100, 100)):
            for n in set(int(x) for x in re.findall(r"\x1b\[38;5;(\d+)m", self.run_line(self.doc(ctx, five, week)))):
                r, g, b = (c / 255 for c in rgb256(n))
                h, s, v = colorsys.rgb_to_hsv(r, g, b)
                self.assertFalse(15 <= h * 360 <= 50 and s > 0.35, "color %d is orange or amber (state %r)" % (n, (ctx, five, week)))

    def test_without_a_context_yet_the_bar_is_left_out(self):
        d = self.doc()
        d["context_window"]["used_percentage"] = None
        self.assertEqual(plain(self.run_line(d)), "╶─ …/a/swarmbox ─ main ─ Sonnet 5.5")

    def test_no_color_turns_every_escape_off(self):
        out = self.run_line(self.doc(95, 93, 64), NO_COLOR="1")
        self.assertEqual(SGR.findall(out), [])
        self.assertIn("▰▰▰▰▰▰▰▰▰▰ 95%", out)

    def test_it_drops_the_limits_and_then_the_model_when_the_width_is_known_and_too_small(self):
        d = self.doc(82, five=71, week=38)
        full = plain(self.run_line(d))
        self.assertIn("7d", full)
        no_week = plain(self.run_line(d, COLUMNS=str(len(full) - 1)))
        self.assertNotIn("7d", no_week)
        self.assertIn("5h", no_week)
        narrow = plain(self.run_line(d, COLUMNS="45"))
        self.assertNotIn("5h", narrow)
        self.assertNotIn("Sonnet", narrow)
        self.assertIn("82%", narrow, "the context stays: it is the one that matters")

    def test_it_never_fails_the_line(self):
        self.assertEqual(self.run_line(None, raw="this is not json"), "")
        self.assertEqual(self.run_line(None, raw=""), "")
        self.assertEqual(plain(self.run_line({"model": {"display_name": "X"}}, PWD=self.home)).startswith("╶─ "), True)
        # a directory that does not exist: no branch, still a line
        self.assertEqual(plain(self.run_line(self.doc(cwd=os.path.join(self.tmp, "gone", "x")))).count("main"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
