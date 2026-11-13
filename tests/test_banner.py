"""The banner as it prints (container/scripts/banner.sh), outside tmux: the lettering, the bar and the signature under it.

The glint is another file (test_banner_glint.py). Run: python3 tests/test_banner.py
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

BANNER = os.path.join(ROOT, "container", "scripts", "banner.sh")
TAGLINE = "your agent's shell, from anywhere"
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def banner():
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env.update(LANG="C.UTF-8")
    r = subprocess.run(["bash", BANNER], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stderr == "", r.stderr
    return r.stdout


def plain(text):
    return SGR.sub("", text)


def brightness(n):
    """how bright a 256-colour number is, 0 to 255: the index does not tell (59 of the cube is brighter than 239 of the gray ramp)"""
    if n >= 232:
        return 8 + 10 * (n - 232)
    n -= 16
    levels = (0, 95, 135, 175, 215, 255)
    return (levels[n // 36] + levels[n // 6 % 6] + levels[n % 6]) // 3


class Signature(unittest.TestCase):
    def setUp(self):
        self.raw = banner()
        self.lines = self.raw.split("\n")
        self.sig = [l for l in self.lines if TAGLINE in plain(l)]

    def test_the_tagline_is_under_the_bar(self):
        self.assertEqual(len(self.sig), 1, "the tagline is printed once")
        bar = [i for i, l in enumerate(self.lines) if "━" in l]
        self.assertEqual(self.lines.index(self.sig[0]), bar[-1] + 1, "the line right under the bar")
        self.assertTrue(plain(self.sig[0]).lstrip().startswith("// " + TAGLINE))

    def test_it_is_right_aligned_with_the_end_of_the_lettering(self):
        letters = [plain(l) for l in self.lines if "█" in l or "▀" in l or "▄" in l][0]
        self.assertEqual(len(plain(self.sig[0]).rstrip()), len(letters.rstrip()), "it ends in the last column of the first row of lettering")

    def test_the_last_word_only_darkens_and_the_rest_is_not_brighter_than_it(self):
        # the colors of the letters of "anywhere": their brightness must never go up
        raw = self.sig[0]
        pos, color, levels = 0, None, []
        for m in SGR.finditer(raw):
            for ch in raw[pos:m.start()]:
                if ch != " ":
                    levels.append((ch, color))
            pos = m.end()
            codes = m.group(1).split(";")
            if len(codes) == 3 and codes[0] == "38" and codes[1] == "5":
                color = int(codes[2])
        word = [brightness(c) for ch, c in levels][-len("anywhere"):]
        self.assertEqual(len(word), 8)
        self.assertEqual(word, sorted(word, reverse=True), "the last word darkens letter by letter: %r" % word)
        self.assertLess(word[-1], word[0], "and it does end darker than it starts")
        everything = [brightness(c) for ch, c in levels if c is not None]
        self.assertLessEqual(max(everything), 175, "the signature stays in the dark grays of the box, never white")

    def test_no_blank_line_after_the_signature(self):
        # the prompt brings its own blank line above it (add_newline in starship.toml)
        self.assertEqual(self.raw.rstrip("\n").split("\n")[-1], self.sig[0])
        self.assertTrue(self.raw.endswith("\n") and not self.raw.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
