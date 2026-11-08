#!/usr/bin/env python3
"""Tests for the Starship prompt: container/config/starship.toml, container/scripts/starship-init.sh and their
wiring in the Dockerfile.

Run:  python3 tests/test_starship.py

The config checks need only Python (tomllib, 3.11+). Rendering the prompt needs the `starship` binary and git
(skipped otherwise). The init script is tested with a fake `starship` so nothing depends on the real one.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest

from helpers import ROOT

CONFIG = os.path.join(ROOT, "container", "config", "starship.toml")
INIT = os.path.join(ROOT, "container", "scripts", "starship-init.sh")
DOCKERFILE = os.path.join(ROOT, "Dockerfile")  # the 2.0 image (slice 2.4: the bashrc fragment sources the init script)
FRAGMENT = os.path.join(ROOT, "container", "config", "bashrc.sh")

# The warm Gruvbox colors of the preset this layout comes from: the SwarmBox palette must not reuse any
# of them, so a SwarmBox shell is never mistaken for a personal one.
GRUVBOX = {"#fbf1c7", "#3c3836", "#665c54", "#458588", "#689d6a", "#98971a", "#d65d0e", "#b16286",
           "#cc241d", "#d79921", "#83a598"}


def luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def load():
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def text():
    with open(CONFIG, encoding="utf-8") as f:
        return f.read()


class Config(unittest.TestCase):
    def test_it_parses_and_uses_the_swarmbox_palette(self):
        cfg = load()
        self.assertEqual(cfg["palette"], "swarmbox")
        self.assertIn("swarmbox", cfg["palettes"])

    def test_every_color_the_config_names_is_defined_in_the_palette(self):
        palette = load()["palettes"]["swarmbox"]
        used = set(re.findall(r"\bcolor_[a-z0-9_]+\b", text())) - set(palette)
        self.assertEqual(used, set(), "colors used but not defined")

    def test_no_color_is_hard_coded_outside_the_palette(self):
        # everything except the palette table itself: the layout and every module section
        outside = re.sub(r"\[palettes\.swarmbox\]\n(?:color_[a-z0-9_]+ = '#[0-9a-fA-F]{6}'\n)+", "", text())
        self.assertNotEqual(outside, text(), "the palette table must be found (and removed) for this check to mean anything")
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", outside), [], "recolor in the palette only")

    def test_the_palette_shares_no_color_with_the_gruvbox_preset(self):
        shared = {c.lower() for c in load()["palettes"]["swarmbox"].values()} & GRUVBOX
        self.assertEqual(shared, set())

    def test_the_text_is_legible_on_every_segment(self):
        # every (text color, background) pair the config actually uses, whatever the module or the order
        palette = load()["palettes"]["swarmbox"]
        text_roles = r"color_fg0|color_[a-z0-9]+_fg"
        pairs = set(re.findall(r"fg:(%s)\s+bg:(color_[a-z0-9_]+)" % text_roles, text()))
        pairs |= {(fg, bg) for bg, fg in re.findall(r"bg:(color_[a-z0-9_]+)\s+fg:(%s)" % text_roles, text())}
        backgrounds = {bg for _, bg in pairs}
        self.assertGreaterEqual(len(backgrounds), 6, "user, path, vcs, lang, ctx and clock segments are all covered")
        for fg, bg in sorted(pairs):
            self.assertGreaterEqual(contrast(palette[fg], palette[bg]), 4.5, "%s on %s" % (fg, bg))

    def test_the_powerline_separators_and_nerd_font_glyphs_are_still_there(self):
        fmt = load()["format"]
        separators = [c for c in fmt if 0xE0B0 <= ord(c) <= 0xE0BF]
        self.assertGreaterEqual(len(separators), 7, "the powerline arrows between segments")
        self.assertGreaterEqual(len({c for c in text() if ord(c) >= 0xE000}), 30, "Nerd Font icons")

    def test_the_layout_keeps_the_segments_of_the_preset(self):
        fmt = load()["format"]
        for module in ("$os", "$username", "$directory", "$git_branch", "$git_status", "$python", "$time"):
            self.assertIn(module, fmt)


@unittest.skipUnless(shutil.which("starship") and shutil.which("git"), "needs starship and git")
class Rendering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(self.repo)
        run = lambda *a: subprocess.run(a, cwd=self.repo, check=True, capture_output=True)
        run("git", "init", "-q", "-b", "main", ".")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("print(1)\n")
        run("git", "add", ".")
        run("git", "commit", "-q", "-m", "init")
        with open(os.path.join(self.repo, "app.py"), "a") as f:
            f.write("print(2)\n")

    def prompt(self, status=0):
        env = {"HOME": self.tmp, "PATH": os.environ["PATH"], "STARSHIP_CONFIG": os.path.abspath(CONFIG),
               "STARSHIP_SHELL": "bash"}
        r = subprocess.run(["starship", "prompt", "--status=%d" % status, "--terminal-width=120"], cwd=self.repo,
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_it_renders_without_warnings_and_shows_the_repository(self):
        r = self.prompt()
        self.assertEqual(r.stderr.strip(), "", "starship warned about the config")
        plain = re.sub(r"\x1b\[[0-9;]*m|\\\[|\\\]|[\x01\x02]", "", r.stdout)
        self.assertIn("main", plain)
        self.assertIn("proj", plain)

    def test_it_only_emits_colors_from_the_palette(self):
        palette = load()["palettes"]["swarmbox"]
        allowed = {tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in palette.values()}
        emitted = {tuple(map(int, m)) for m in re.findall(r"[34]8;2;(\d+);(\d+);(\d+)", self.prompt().stdout)}
        self.assertTrue(emitted, "truecolor expected")
        self.assertEqual(emitted - allowed, set(), "a color outside the palette is being emitted")

    def test_the_prompt_is_one_powerline_line_closed_by_an_arrow(self):
        # As in the config it comes from: no $line_break$character in `format`, so there is no prompt symbol
        # (and no exit-status color); the command is typed right after the last arrow.
        plain = re.sub(r"\x1b\[[0-9;]*m|\\\[|\\\]|[\x01\x02]", "", self.prompt().stdout)
        self.assertEqual(plain.lstrip("\n").count("\n"), 0, "a single line")
        self.assertTrue(plain.endswith("\ue0b0 "), "closed by the powerline arrow and a space")
        self.assertNotIn("\u276f", plain)


class InitScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        shim = os.path.join(self.bin, "starship")
        with open(shim, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = init ] && echo \'SHIM_INIT=1\'\nexit 0\n')
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IXUSR)

    def source(self, interactive=True, env=None, with_shim=True):
        path = (self.bin + os.pathsep if with_shim else "") + "/usr/bin:/bin"
        e = {"HOME": self.home, "PATH": path}
        e.update(env or {})
        flags = ["-i"] if interactive else []
        r = subprocess.run(["bash"] + flags + ["-c", '. "%s"; echo "R=${SHIM_INIT:-}|C=${STARSHIP_CONFIG-unset}"' % INIT],
                           env=e, capture_output=True, text=True, timeout=30)
        line = [l for l in r.stdout.splitlines() if l.startswith("R=")]
        self.assertEqual(len(line), 1, r.stdout + r.stderr)
        init, config = line[0][2:].split("|C=")
        return init == "1", config, r

    def test_it_turns_starship_on_with_the_swarmbox_config(self):
        on, config, _ = self.source()
        self.assertTrue(on)
        self.assertEqual(config, "/etc/swarmbox/starship.toml")

    def test_a_personal_starship_toml_wins(self):
        os.makedirs(os.path.join(self.home, ".config"))
        with open(os.path.join(self.home, ".config", "starship.toml"), "w") as f:
            f.write("# mine\n")
        on, config, _ = self.source()
        self.assertTrue(on)
        self.assertEqual(config, "unset", "left unset so starship reads the user's file")

    def test_an_STARSHIP_CONFIG_you_set_is_respected(self):
        on, config, _ = self.source(env={"STARSHIP_CONFIG": "/elsewhere/s.toml"})
        self.assertTrue(on)
        self.assertEqual(config, "/elsewhere/s.toml")

    def test_it_can_be_turned_off(self):
        on, config, _ = self.source(env={"SWARMBOX_STARSHIP": "0"})
        self.assertFalse(on)
        self.assertEqual(config, "unset")

    def test_it_does_nothing_in_a_non_interactive_shell(self):
        on, config, _ = self.source(interactive=False)
        self.assertFalse(on)
        self.assertEqual(config, "unset")

    def test_it_is_harmless_when_starship_is_not_installed(self):
        on, config, r = self.source(with_shim=False)
        self.assertFalse(on)
        self.assertNotIn("not found", r.stderr)


class DockerfileWiring(unittest.TestCase):
    def setUp(self):
        with open(DOCKERFILE) as f:
            self.d = f.read()

    def test_the_release_is_pinned_and_its_checksum_verified(self):
        self.assertRegex(self.d, r"ARG STARSHIP_VERSION=\d+\.\d+\.\d+")
        block = self.d[self.d.index("ARG STARSHIP_VERSION"):]
        block = block[:block.index("COPY container/config/starship.toml")]
        self.assertIn("sha256sum -c -", block)
        self.assertIn("starship-x86_64-unknown-linux-musl", block)
        self.assertIn("starship-aarch64-unknown-linux-musl", block)

    def test_starship_is_initialised_after_everything_else_by_the_fragment(self):
        # Starship redefines PS1, so the fragment sources the init script after the venv, the PATH, the aliases,
        # the tools' shell.sh and the banner (v0.1.0 did the same from /etc/bash.bashrc)
        with open(FRAGMENT) as f:
            frag = f.read()
        init = frag.index("${SWARMBOX_STARSHIP_INIT:-")
        for earlier in (". \"$_sb_venv/bin/activate\"", "shell.sh", "_sb_banner\"", "alias ll="):
            self.assertGreater(init, frag.index(earlier), earlier)
        self.assertIn("/etc/swarmbox/scripts/starship-init.sh", frag)

    def test_the_image_bashrc_sources_the_fragment(self):
        self.assertIn("COPY container/config/bashrc.sh /etc/swarmbox/bashrc.sh", self.d)
        self.assertRegex(self.d, r">> /etc/bash\.bashrc")
        self.assertIn(". /etc/swarmbox/bashrc.sh", self.d)

    def test_the_config_and_the_script_are_installed(self):
        self.assertIn("COPY container/config/starship.toml /etc/swarmbox/starship.toml", self.d)
        self.assertIn("COPY container/scripts/starship-init.sh /etc/swarmbox/scripts/starship-init.sh", self.d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
