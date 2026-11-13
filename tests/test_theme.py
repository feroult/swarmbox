"""One look for the three places that draw: the banner, the Starship prompt and the tmux theme.

Every color of the tmux theme must come from the palette that the prompt and the banner already use (plus two neutral inks for text),
so the three cannot drift apart: change a color in one and this says which of the others has to follow.
Run: python3 tests/test_theme.py
"""
import json
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
    m = re.search(r"^gradient COLS \$\{#FONT\[0\]\} ([0-9a-f ]+)$", read("container", "scripts", "banner.sh"), re.M)   # the one of the letters
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


def web_theme():
    m = re.search(r"^    \[theme\]='(\{.*\})'$", read("container", "scripts", "swarmbox-web.sh"), re.M)
    assert m, "the default theme of swarmbox-web.sh was not found"
    return json.loads(m.group(1))


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

    def test_the_claude_code_theme_is_well_formed_and_its_selection_is_the_one_of_tmux(self):
        c = json.loads(read("docs", "theme", "claude-code.json"))
        self.assertEqual((c["name"], c["base"]), ("SwarmBox Purple-Glow", "dark"))
        self.assertGreaterEqual(len(c["overrides"]), 20)
        for k, v in c["overrides"].items():
            self.assertRegex(v, r"^#[0-9a-fA-F]{6}$", k)
        tmux = [l for l in read("container", "config", "tmux.conf").splitlines() if l.startswith("setw -g mode-style")][0]
        self.assertEqual(c["overrides"]["selectionBg"], tmux.split("bg=")[1].split(",")[0])
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

    def test_the_scrollbar_of_the_browser_is_violet_not_white(self):
        css = read("container", "web", "ttyd-style.css")
        scroll = "\n".join(l for l in css.splitlines() if "scrollbar" in l)
        self.assertNotIn("255, 255, 255", scroll)
        self.assertIn("167, 139, 250", scroll)

    def test_claude_code_is_allowed_exact_colors_inside_tmux_because_tmux_declares_rgb(self):
        # inside tmux Claude Code caps itself at 256 colors (a rose came out as a salmon) unless CLAUDE_CODE_TMUX_TRUECOLOR is set
        self.assertIn("CLAUDE_CODE_TMUX_TRUECOLOR=1", read("container", "config", "bashrc.sh"))
        self.assertIn("export CLAUDE_CODE_TMUX_TRUECOLOR", read("container", "config", "bashrc.sh"))
        self.assertRegex(read("container", "config", "tmux.conf"), r"(?m)^set -as terminal-features \",xterm-256color:RGB\"$", "tmux must declare RGB for the variable to be honest")

    def test_the_doc_exists_and_every_file_it_links_exists(self):
        doc = read("docs", "theme.md")
        for target in re.findall(r"\]\((theme/[^)]+)\)", doc):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "docs", target)), target)
        self.assertIn("docs/theme.md", read("README.md"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
