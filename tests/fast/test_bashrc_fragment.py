#!/usr/bin/env python3
"""The shell fragment container/config/bashrc.sh.

Run: python3 tests/fast/test_bashrc_fragment.py

Every test runs in a mktemp tree (HOME, XDG_*), with fake addons (a manifest and a shell.sh), fake agent programs and a fake banner.
Interactive runs use `bash --norc -i` with `. <fragment>` and the commands on standard input (a real interactive shell
without a terminal; its job-control complaints on standard error are ignored). Every run has a timeout.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

FRAGMENT = os.path.join(ROOT, "container", "config", "bashrc.sh")
TIMEOUT = 30


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        t = self.tmp
        self.home = os.path.join(t, "home")
        self.cfg = os.path.join(t, "xdg-config")
        self.data = os.path.join(t, "xdg-data")
        self.state = os.path.join(t, "xdg-state")
        self.imgaddons = os.path.join(t, "image-addons")
        self.imgshims = os.path.join(t, "image-shims")
        self.bin = os.path.join(t, "bin")
        for d in (self.home, self.cfg, self.data, self.state, self.imgaddons, self.imgshims, self.bin):
            os.makedirs(d)
        self.user_addons = os.path.join(self.cfg, "swarmbox", "addons")
        self.state_dir = os.path.join(self.state, "swarmbox")
        os.makedirs(self.state_dir)
        self.banner = os.path.join(t, "banner.sh")
        write(self.banner, "#!/bin/sh\necho BANNER-ART\n", 0o755)

    def env(self, **extra):
        e = {"HOME": self.home, "XDG_CONFIG_HOME": self.cfg, "XDG_DATA_HOME": self.data, "XDG_STATE_HOME": self.state,
             "PATH": self.bin + ":/usr/bin:/bin", "SWARMBOX_IMAGE_ADDONS_DIR": self.imgaddons,
             "SWARMBOX_IMAGE_SHIMS_DIR": self.imgshims, "SWARMBOX_VENV": os.path.join(self.tmp, "no-venv"),
             "SWARMBOX_DIRS_SH": os.path.join(ROOT, "container", "scripts", "dirs.sh"), "SWARMBOX_BANNER_SCRIPT": self.banner,
             "SWARMBOX_STARSHIP_INIT": os.path.join(self.tmp, "none-starship-init.sh"), "TERM": "dumb"}
        e.update(extra)
        return {k: v for k, v in e.items() if v is not None}

    def addon(self, name, shell_sh=None, level="image", conf_extra=""):
        """An addon folder with its manifest and (optional) shell.sh, at the image level or the user level."""
        base = self.imgaddons if level == "image" else self.user_addons
        write(os.path.join(base, name, "addon.conf"),
              'SCHEMA=1\nNAME=%s\nDESCRIPTION="%s"\nVERSION=1.0.0\nCOMMANDS="%s"\n%s' % (name, name, name, conf_extra))
        if shell_sh is not None:
            write(os.path.join(base, name, "shell.sh"), shell_sh)

    def fake_agent(self, name):
        write(os.path.join(self.bin, name), '#!/bin/sh\necho "RAN %s $*"\n' % name, 0o755)

    def health(self, text):
        write(os.path.join(self.state_dir, "health"), text)

    def interactive(self, commands, **extra):
        # --norc also skips Debian's /etc/bash.bashrc (which, on the live box, runs the v0.1.0 init), so it is hermetic
        script = '. "%s"\n%s\nexit\n' % (FRAGMENT, commands)
        r = subprocess.run(["bash", "--noprofile", "--norc", "-i"], input=script, env=self.env(**extra),
                           capture_output=True, text=True, timeout=TIMEOUT)
        return r

    def command_mode(self, command, **extra):
        e = self.env(SWARMBOX_CMD="1", **extra)
        return subprocess.run(["bash", "-c", 'shopt -s expand_aliases; . "$2"; unset SWARMBOX_CMD; eval -- "$1"', "bash",
                               command, FRAGMENT], env=e, capture_output=True, text=True, timeout=TIMEOUT)

    def two_agents(self):
        """Two agent addons the way the real ones are: a shell.sh with a function that adds the flags of the agent."""
        self.addon("alpha", shell_sh='alpha() { command alpha --auto-approve-a --mcp-config "$HOME/m.json" "$@"; }\n')
        self.addon("beta", shell_sh='beta() {\n    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then command beta "$@"; else command beta --yes "$@"; fi\n}\n')
        self.addon("plain")   # an addon without a shell.sh gives the shell nothing
        self.fake_agent("alpha")
        self.fake_agent("beta")


class AddonShells(Base):
    def test_the_function_of_a_shell_sh_runs_the_agent_with_its_flags(self):
        self.two_agents()
        r = self.interactive("beta hello; alpha x")
        self.assertIn("RAN beta --yes hello", r.stdout)
        self.assertIn("RAN alpha --auto-approve-a --mcp-config %s/m.json x" % self.home, r.stdout)

    def test_the_fragment_builds_no_alias(self):
        self.two_agents()
        r = self.interactive("alias alpha beta plain 2>&1")
        self.assertNotIn("alias alpha=", r.stdout)
        self.assertNotIn("alias beta=", r.stdout)
        self.assertEqual(self.interactive("alias | grep -c -E '^alias (alpha|beta|plain)='").stdout.split()[-1], "0")

    def test_an_addon_without_a_shell_sh_is_fine(self):
        self.two_agents()
        r = self.interactive("type plain 2>&1; echo STILL-HERE")
        self.assertIn("STILL-HERE", r.stdout)
        self.assertNotIn("plain is a function", r.stdout)

    def test_swarmbox_yolo_zero_is_read_by_the_shell_sh_of_the_addon(self):
        self.two_agents()
        r = self.interactive("beta hello", SWARMBOX_YOLO="0")
        self.assertIn("RAN beta hello", r.stdout)
        self.assertNotIn("--yes", r.stdout)

    def test_the_user_level_shell_sh_wins_over_the_image_level_of_the_same_name(self):
        self.addon("beta", shell_sh='beta() { echo IMAGE-BETA; }\n')
        self.addon("beta", shell_sh='beta() { echo USER-BETA; }\n', level="user")
        r = self.interactive("beta")
        self.assertIn("USER-BETA", r.stdout)
        self.assertNotIn("IMAGE-BETA", r.stdout)

    def test_a_user_addon_with_a_shell_sh_is_sourced_too(self):
        self.addon("mine", shell_sh='export FROM_MINE=yes\n', level="user")
        self.addon("theirs", shell_sh='export FROM_THEIRS=yes\n')
        r = self.interactive("echo $FROM_MINE $FROM_THEIRS")
        self.assertIn("yes yes", r.stdout)

    def test_a_manifest_is_never_read_by_the_fragment(self):
        marker = os.path.join(self.tmp, "SOURCED")
        self.addon("evil", conf_extra="touch %s\n" % marker)
        write(os.path.join(self.user_addons, "bad", "addon.conf"), "this is ( not shell\nexit 9\ntouch %s\n" % marker)
        r = self.interactive("echo STILL-HERE")
        self.assertIn("STILL-HERE", r.stdout)
        self.assertFalse(os.path.exists(marker))

    def test_a_broken_shell_sh_does_not_break_the_shell(self):
        self.two_agents()
        self.addon("bad", shell_sh="this is ( not shell\nexit 9\n", level="user")
        r = self.interactive("beta hello; echo STILL-HERE")
        self.assertIn("RAN beta --yes hello", r.stdout)
        self.assertIn("STILL-HERE", r.stdout)

    def test_a_shell_sh_that_reads_standard_input_does_not_eat_the_commands(self):
        self.addon("greedy", shell_sh="cat >/dev/null\n")
        r = self.interactive("echo STILL-HERE")
        self.assertIn("STILL-HERE", r.stdout)


class Yolo(Base):
    def test_yolo_runs_swarmbox_agent_through_its_function_once(self):
        self.two_agents()
        r = self.interactive("yolo go", SWARMBOX_AGENT="alpha")
        self.assertIn("RAN alpha --auto-approve-a --mcp-config %s/m.json go" % self.home, r.stdout)
        self.assertEqual(r.stdout.count("RAN alpha"), 1)

    def test_yolo_without_a_default_agent_says_so_and_fails(self):
        self.two_agents()
        r = self.interactive("yolo; echo status=$?")
        self.assertRegex(r.stdout + r.stderr, r"no default agent")
        self.assertIn("status=1", r.stdout)
        self.assertNotIn("RAN", r.stdout)

    def test_yolo_with_a_default_agent_that_is_not_a_command_says_so_and_fails(self):
        # WITH=sysop,voice records SWARMBOX_AGENT=sysop, which is no command: not the bare "command not found" of the shell
        self.two_agents()
        r = self.interactive("yolo; echo status=$?", SWARMBOX_AGENT="sysop")
        self.assertIn("the default agent 'sysop' is not a command", r.stdout + r.stderr)
        self.assertNotIn("command not found", r.stdout + r.stderr)
        self.assertIn("status=127", r.stdout)

    def test_yolo_as_the_default_agent_is_refused_instead_of_calling_itself(self):
        self.two_agents()
        r = self.interactive("yolo; echo status=$?", SWARMBOX_AGENT="yolo")
        self.assertIn("cannot be 'yolo'", r.stdout + r.stderr)
        self.assertIn("status=1", r.stdout)

    def test_yolo_is_a_function(self):
        self.assertIn("yolo is a function", self.interactive("type yolo | head -1").stdout)

class CommandMode(Base):
    def test_swarmbox_cmd_gives_aliases_and_path_with_clean_stderr(self):
        self.two_agents()
        r = self.command_mode("beta x; echo $PATH | tr : '\\n' | head -1")
        self.assertIn("RAN beta --yes x", r.stdout)
        self.assertEqual(r.stderr, "")
        self.assertIn(os.path.join(self.data, "swarmbox", "shims"), r.stdout)

class Banner(Base):
    def test_the_banner_and_the_health_lines_are_shown(self):
        self.health("step 5 failed: ssh key\nweb terminal keeps crashing; see web-terminal.log\n")
        out = self.interactive("true").stdout
        self.assertIn("BANNER-ART", out)
        self.assertIn("step 5 failed: ssh key", out)
        self.assertIn("web terminal keeps crashing; see web-terminal.log", out)
        self.assertLess(out.index("BANNER-ART"), out.index("step 5 failed"))

    def test_the_stale_image_line_is_shown(self):
        line = "the local image has been replaced since this box was created; run `swarmbox reset`"
        self.health("one failure\n" + line + "\n")
        out = self.interactive("true").stdout
        self.assertIn(line, out)

    def test_control_characters_in_a_health_line_are_not_printed(self):
        self.health("bad \x1b[31mred\x1b[0m line\n")
        out = self.interactive("true").stdout
        self.assertNotIn("\x1b[31m", out)
        self.assertIn("bad", out)

class PathAndEnvironment(Base):
    def test_path_additions_in_the_design_order(self):
        cur = os.path.join(self.data, "swarmbox", "addons", "gcloud", "current", "bin")
        os.makedirs(cur)
        out = self.interactive('echo "P=$PATH"').stdout
        path = [l for l in out.splitlines() if l.startswith("P=")][0][2:].split(":")
        user_shims = os.path.join(self.data, "swarmbox", "shims")
        order = [path.index(p) for p in (user_shims, self.imgshims, cur, os.path.join(self.home, ".local", "bin"))]
        self.assertEqual(order, sorted(order), path)
        self.assertEqual(order[0], 0)

    def test_shell_sh_of_an_addon_is_sourced_after_the_aliases_of_the_fragment_and_can_override_them(self):
        self.addon("alpha", shell_sh="alias ls='ls --overridden'\nexport FROM_SHELL_SH=yes\n")
        r = self.interactive("alias ls; echo $FROM_SHELL_SH")
        self.assertIn("alias ls='ls --overridden'", r.stdout)
        self.assertIn("yes", r.stdout)

    def test_starship_is_initialised_last_when_present(self):
        init = os.path.join(self.tmp, "starship-init-fake.sh")
        write(init, 'echo STARSHIP-INIT-RAN\n')
        out = self.interactive("true", SWARMBOX_STARSHIP_INIT=init).stdout
        self.assertIn("STARSHIP-INIT-RAN", out)
        self.assertLess(out.index("BANNER-ART"), out.index("STARSHIP-INIT-RAN"))


# (the fragment over the real agent addons, their flags and SWARMBOX_YOLO=0: tests/fast/test_addon_agent_shell.py)


@unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
class Lint(unittest.TestCase):
    def test_shellcheck_bash_is_clean(self):
        r = subprocess.run(["shellcheck", "-s", "bash", FRAGMENT], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)



if __name__ == "__main__":
    unittest.main(verbosity=2)
