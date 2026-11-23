"""One look for the places that draw: the Starship prompt, the Purple Glow theme of the Web Studio's terminal, the schemes for the terminals
outside the box and the theme of Claude Code: one palette, in docs/theme.md, so the themes cannot drift apart.
Run: python3 tests/fast/test_theme.py
"""
import json
import os
import re
import sys
import tomllib
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def prompt_palette():
    return {v.lower() for v in tomllib.loads(read("container", "config", "starship.toml"))["palettes"]["swarmbox"].values()}


class OneLook(unittest.TestCase):
    def test_the_palettes_are_not_empty(self):
        self.assertGreaterEqual(len(prompt_palette()), 8)


def web_theme():
    """the xterm colors of the Purple Glow theme of the Web Studio (container/web/herdr/public/app.js)"""
    text = read("container", "web", "herdr", "public", "app.js")
    m = re.search(r"'purple-glow': \{.*?xterm: \{(.*?)\}", text, re.S)
    assert m, "the Purple Glow xterm theme of app.js was not found"
    return dict(re.findall(r"(\w+): '(#[0-9a-fA-F]{6})'", m.group(1)))


def luminance(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


ANSI16 = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")


class OnePalette(unittest.TestCase):
    """The browser terminal, the schemes for the terminals outside the box, the colors of ls and grep, the messages of the scripts and the
    theme of Claude Code: one palette, in docs/theme.md."""

    def test_the_browser_terminal_has_all_its_colors_and_every_text_color_is_legible_on_the_background(self):
        t = web_theme()
        names = ["background", "foreground", "cursor", "selectionBackground", "selectionForeground"] + list(ANSI16) + ["bright" + n.capitalize() for n in ANSI16]
        self.assertEqual(sorted(set(names) - set(t)), [], "a color of the theme is missing")
        for k in names:
            self.assertRegex(t[k], r"^#[0-9a-f]{6}$", k)
        text = ["foreground", "cursor"] + [n for n in ANSI16 if n != "black"] + ["bright" + n.capitalize() for n in ANSI16 if n != "black"]
        text.remove("brightBlack") if "brightBlack" in text else None
        for k in text:
            self.assertGreaterEqual(contrast(t[k], t["background"]), 4.5, "%s is hard to read on the background" % k)
        self.assertGreaterEqual(contrast(t["brightBlack"], t["background"]), 4.0, "the dim text")
        self.assertGreaterEqual(contrast(t["selectionForeground"], t["selectionBackground"]), 4.5, "the text of a selection")

    def test_the_schemes_for_windows_terminal_and_ghostty_say_the_same_as_the_browser_terminal(self):
        t = web_theme()
        wt = json.loads(read("docs", "theme", "windows-terminal.json"))["schemes"][0]
        self.assertEqual(wt["name"], "SwarmBox Purple-Glow")
        for k in ("background", "foreground", "selectionBackground", "black", "red", "green", "yellow", "blue", "cyan", "white",
                  "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightCyan", "brightWhite"):
            self.assertEqual(wt[k], t[k], "windows-terminal.json: " + k)
        self.assertEqual(wt["purple"], t["magenta"])
        self.assertEqual(wt["brightPurple"], t["brightMagenta"])
        self.assertEqual(wt["cursorColor"], t["cursor"])
        g = dict(l.split(" = ", 1) for l in read("docs", "theme", "ghostty").splitlines() if " = " in l and not l.startswith("#"))
        palette = [l.split(" = ", 1)[1] for l in read("docs", "theme", "ghostty").splitlines() if l.startswith("palette = ")]
        order = list(ANSI16) + ["bright" + n.capitalize() for n in ANSI16]
        self.assertEqual([v.split("=", 1)[1] for v in palette], [t[k] for k in order], "the 16 colors of the ghostty theme")
        self.assertEqual((g["background"], g["foreground"], g["cursor-color"]), (t["background"], t["foreground"], t["cursor"]))
        self.assertEqual((g["selection-background"], g["selection-foreground"]), (t["selectionBackground"], t["selectionForeground"]))

    def test_the_claude_code_theme_is_well_formed_and_its_selection_is_the_one_of_the_browser_terminal(self):
        c = json.loads(read("docs", "theme", "claude-code.json"))
        self.assertEqual((c["name"], c["base"]), ("SwarmBox Purple-Glow", "dark"))
        self.assertGreaterEqual(len(c["overrides"]), 20)
        for k, v in c["overrides"].items():
            self.assertRegex(v, r"^#[0-9a-fA-F]{6}$", k)
        self.assertEqual(c["overrides"]["selectionBg"], web_theme()["selectionBackground"])

    def test_ls_and_grep_use_256_colour_numbers_never_the_16_of_the_terminal(self):
        text = read("container", "config", "bashrc.sh")
        for var in ("LS_COLORS", "GREP_COLORS"):
            value = re.search(r"^export %s='([^']*)'" % var, text, re.M).group(1)
            for entry in filter(None, value.split(":")):
                codes = entry.split("=", 1)[1].split(";")
                i = 0
                while i < len(codes):
                    c = int(codes[i])
                    if c in (38, 48):
                        self.assertEqual(codes[i + 1], "5", "%s %s: only 256-colour numbers" % (var, entry))
                        i += 3
                        continue
                    self.assertFalse(30 <= c <= 37 or 40 <= c <= 47 or 90 <= c <= 97, "%s %s: a color of the terminal's own palette, which each scheme paints its own way" % (var, entry))
                    i += 1

    def test_the_messages_of_the_scripts_use_two_fixed_grays(self):
        text = read("container", "scripts", "messages.sh")
        for name in ("GRAY", "WHITE"):
            self.assertIn("%s='\\033[38;5;" % name, text)
        self.assertNotIn("[0;90m", text)
        self.assertNotIn("[0;37m", text)

    def test_the_doc_exists_and_every_file_it_links_exists(self):
        doc = read("docs", "theme.md")
        for target in re.findall(r"\]\((theme/[^)]+)\)", doc):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "docs", target)), target)
        self.assertIn("docs/theme.md", read("README.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
