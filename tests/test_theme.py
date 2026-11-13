"""One look for the three places that draw: the banner, the Starship prompt and the tmux theme.

Every color of the tmux theme must come from the palette that the prompt and the banner already use (plus two neutral inks for text),
so the three cannot drift apart: change a color in one and this says which of the others has to follow.
Run: python3 tests/test_theme.py
"""
import os
import re
import sys
import tomllib
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

CONFIG = os.path.join(ROOT, "container", "config")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# the dark and the light ink for text on a colored background: not part of the palette, shared by the three
INKS = {"#fafafa", "#111111"}


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def config_lines(name):
    """the lines of a tmux file that configure something: a comment may mention any color"""
    return "\n".join(l for l in read("container", "config", name).splitlines() if not l.lstrip().startswith("#"))


def prompt_palette():
    return {v.lower() for v in tomllib.loads(read("container", "config", "starship.toml"))["palettes"]["swarmbox"].values()}


def banner_palette():
    m = re.search(r"^gradient \$\{#FONT\[0\]\} ([0-9a-f ]+)$", read("container", "scripts", "banner.sh"), re.M)
    assert m, "the gradient line of banner.sh was not found"
    return {"#" + h for h in m.group(1).split()}


class OneLook(unittest.TestCase):
    def test_the_palettes_are_not_empty(self):
        self.assertGreaterEqual(len(prompt_palette()), 8)
        self.assertGreaterEqual(len(banner_palette()), 4)

    def test_every_color_of_the_tmux_theme_comes_from_the_prompt_or_the_banner(self):
        allowed = prompt_palette() | banner_palette() | INKS
        for name in ("tmux.conf", "tmux-browser-keys.conf"):
            used = {c.lower() for c in HEX.findall(config_lines(name))}
            self.assertEqual(sorted(used - allowed), [], "%s uses colors that the prompt and the banner do not have" % name)

    def test_the_old_pastel_theme_is_gone(self):
        text = config_lines("tmux.conf") + config_lines("tmux-browser-keys.conf")
        for old in ("#b4befe", "#a6e3a1", "#f5c2e7", "#45475a", "#313244", "#7f849c", "#a9b1d6", "#1e1e2e"):
            self.assertNotIn(old, text.lower())

    def test_the_current_window_is_as_wide_as_the_others_so_nothing_moves(self):
        def shown(option):
            line = [l for l in read("container", "config", "tmux.conf").splitlines() if l.startswith("setw -g " + option + " ")][0]
            text = line.split('"', 1)[1].rsplit('"', 1)[0]
            return re.sub(r"#\[[^\]]*\]", "", text).replace("#I", "2").replace("#W", "claude")
        self.assertEqual(len(shown("window-status-format")), len(shown("window-status-current-format")),
                         "the current window adds or drops characters: every window after it would shift when you select it")

    def test_the_plus_button_keeps_the_first_three_columns(self):
        # the click on [+] is read as mouse_x < 3: the button is exactly " + ", nothing drawn before it
        line = [l for l in read("container", "config", "tmux-browser-keys.conf").splitlines() if l.startswith("set -g status-left")][0]
        shown = re.sub(r"#\[[^\]]*\]", "", line.split('"', 1)[1])
        self.assertTrue(shown.startswith(" + "), repr(shown[:6]))
        self.assertIn("#{<:#{mouse_x},3}", read("container", "config", "tmux-browser-keys.conf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
