#!/usr/bin/env python3
"""The shell fragment container/config/bashrc.sh.

Run: python3 tests/test_bashrc_fragment.py

Every test runs in a mktemp tree (HOME, XDG_*), with fake agent manifests, fake agent programs and a fake banner.
Interactive runs use `bash --norc -i` with `. <fragment>` and the commands on standard input (a real interactive shell
without a terminal; its job-control complaints on standard error are ignored). Every run has a timeout.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
        self.imgtools = os.path.join(t, "image-tools")
        self.imgshims = os.path.join(t, "image-shims")
        self.bin = os.path.join(t, "bin")
        for d in (self.home, self.cfg, self.data, self.state, self.imgtools, self.imgshims, self.bin):
            os.makedirs(d)
        self.user_tools = os.path.join(self.cfg, "swarmbox", "tools")
        self.state_dir = os.path.join(self.state, "swarmbox")
        os.makedirs(self.state_dir)
        self.banner = os.path.join(t, "banner.sh")
        write(self.banner, "#!/bin/sh\necho BANNER-ART\n", 0o755)

    def env(self, **extra):
        e = {"HOME": self.home, "XDG_CONFIG_HOME": self.cfg, "XDG_DATA_HOME": self.data, "XDG_STATE_HOME": self.state,
             "PATH": self.bin + ":/usr/bin:/bin", "SWARMBOX_IMAGE_TOOLS_DIR": self.imgtools,
             "SWARMBOX_IMAGE_SHIMS_DIR": self.imgshims, "SWARMBOX_VENV": os.path.join(self.tmp, "no-venv"),
             "SWARMBOX_DIRS_SH": os.path.join(ROOT, "container", "scripts", "dirs.sh"), "SWARMBOX_BANNER_SCRIPT": self.banner,
             "SWARMBOX_STARSHIP_INIT": os.path.join(self.tmp, "none-starship-init.sh"), "TERM": "dumb"}
        e.update(extra)
        return {k: v for k, v in e.items() if v is not None}

    def manifest(self, name, body, level="image", shell_sh=None):
        base = self.imgtools if level == "image" else self.user_tools
        write(os.path.join(base, name, "tool.conf"), "SCHEMA=1\nNAME=%s\n%s\n" % (name, body))
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
        self.manifest("alpha", 'KIND=agent\nPROVIDES="alpha"\nYOLO_FLAGS="--auto-approve-a"\nMCP_FLAGS="--mcp-config $HOME/m.json"')
        self.manifest("beta", 'KIND=agent\nPROVIDES="beta"\nYOLO_FLAGS="--yes"')
        self.manifest("tooly", 'KIND=tool\nPROVIDES="tooly"\nYOLO_FLAGS="--nope"')
        self.fake_agent("alpha")
        self.fake_agent("beta")


class Aliases(Base):
    def test_aliases_are_generated_from_two_manifests(self):
        self.two_agents()
        r = self.interactive("alias alpha; alias beta; alias tooly")
        self.assertIn("alias alpha='alpha --auto-approve-a --mcp-config %s/m.json'" % self.home, r.stdout)
        self.assertIn("alias beta='beta --yes'", r.stdout)
        self.assertNotIn("tooly", r.stdout.replace("alias: tooly: not found", ""))  # a tool is no agent: no alias

    def test_the_alias_runs_the_agent_with_its_flags(self):
        self.two_agents()
        r = self.interactive("beta hello")
        self.assertIn("RAN beta --yes hello", r.stdout)

    def test_swarmbox_yolo_zero_disables_all_aliases(self):
        self.two_agents()
        r = self.interactive("alias alpha; alias beta", SWARMBOX_YOLO="0")
        self.assertNotIn("alias alpha=", r.stdout)
        self.assertNotIn("alias beta=", r.stdout)

    def test_the_user_level_manifest_wins(self):
        self.manifest("beta", 'KIND=agent\nPROVIDES="beta"\nYOLO_FLAGS="--image-flag"')
        self.manifest("beta", 'KIND=agent\nPROVIDES="beta"\nYOLO_FLAGS="--user-flag"', level="user")
        r = self.interactive("alias beta")
        self.assertIn("--user-flag", r.stdout)
        self.assertNotIn("--image-flag", r.stdout)

    def test_a_broken_manifest_does_not_break_the_shell(self):
        self.two_agents()
        write(os.path.join(self.user_tools, "bad", "tool.conf"), "this is ( not shell\nexit 9\n")
        r = self.interactive("alias beta; echo STILL-HERE")
        self.assertIn("alias beta='beta --yes'", r.stdout)
        self.assertIn("STILL-HERE", r.stdout)

class Yolo(Base):
    def test_yolo_runs_swarmbox_agent_with_its_flags_once(self):
        self.two_agents()
        r = self.interactive("yolo go", SWARMBOX_AGENT="alpha")
        self.assertIn("RAN alpha --auto-approve-a --mcp-config %s/m.json go" % self.home, r.stdout)
        self.assertEqual(r.stdout.count("RAN alpha"), 1)

    def test_no_manifest_yolo_says_no_agent_and_fails(self):
        r = self.interactive("yolo; echo status=$?")
        self.assertRegex(r.stdout + r.stderr, r"no agent (is )?installed")
        self.assertIn("status=1", r.stdout)

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
        cur = os.path.join(self.data, "swarmbox", "tools", "gcloud", "current", "bin")
        os.makedirs(cur)
        out = self.interactive('echo "P=$PATH"').stdout
        path = [l for l in out.splitlines() if l.startswith("P=")][0][2:].split(":")
        user_shims = os.path.join(self.data, "swarmbox", "shims")
        order = [path.index(p) for p in (user_shims, self.imgshims, cur, os.path.join(self.home, ".local", "bin"))]
        self.assertEqual(order, sorted(order), path)
        self.assertEqual(order[0], 0)

    def test_shell_sh_of_a_tool_is_sourced_after_the_aliases_and_can_override_them(self):
        self.manifest("alpha", 'KIND=agent\nPROVIDES="alpha"\nYOLO_FLAGS="--a"', shell_sh="alias alpha='alpha --overridden'\nexport FROM_SHELL_SH=yes\n")
        r = self.interactive("alias alpha; echo $FROM_SHELL_SH")
        self.assertIn("alias alpha='alpha --overridden'", r.stdout)
        self.assertIn("yes", r.stdout)

    def test_starship_is_initialised_last_when_present(self):
        init = os.path.join(self.tmp, "starship-init-fake.sh")
        write(init, 'echo STARSHIP-INIT-RAN\n')
        out = self.interactive("true", SWARMBOX_STARSHIP_INIT=init).stdout
        self.assertIn("STARSHIP-INIT-RAN", out)
        self.assertLess(out.index("BANNER-ART"), out.index("STARSHIP-INIT-RAN"))


class RealClaudeManifest(Base):
    """The fragment reads the manifest the image ships (container/tools/claude), not a made-up one."""

    def setUp(self):
        super().setUp()
        shutil.copytree(os.path.join(ROOT, "container", "tools"), self.imgtools, dirs_exist_ok=True)

    def test_the_claude_alias_is_generated_with_the_yolo_flag_and_the_mcp_config(self):
        r = self.interactive("alias claude")
        self.assertIn("alias claude='claude --dangerously-skip-permissions --mcp-config %s/.claude/mcp-servers.json'" % self.home,
                      r.stdout, r.stdout + r.stderr)

    def test_the_path_has_the_user_shims_first_then_the_image_shims(self):
        out = self.interactive('echo "P=$PATH"').stdout
        path = [l for l in out.splitlines() if l.startswith("P=")][0][2:].split(":")
        user_shims = os.path.join(self.data, "swarmbox", "shims")
        self.assertEqual(path[0], user_shims)
        self.assertLess(path.index(user_shims), path.index(self.imgshims))
        self.assertLess(path.index(self.imgshims), path.index(os.path.join(self.home, ".local", "bin")))


@unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
class Lint(unittest.TestCase):
    def test_shellcheck_bash_is_clean(self):
        r = subprocess.run(["shellcheck", "-s", "bash", FRAGMENT], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)



if __name__ == "__main__":
    unittest.main(verbosity=2)
