"""The shell fragment inside a real throwaway container from the 2.1 image.

Checks that the image's /etc/bash.bashrc sources /etc/swarmbox/bashrc.sh (banner, health lines, alias from a user-level
manifest, yolo message, Starship) and that `swarmbox-entrypoint attach <command>` without a terminal gets the aliases and
the PATH with a clean standard error and no banner. The nested Podman service is off (SWARMBOX_TEST_NO_NESTED), so this is
tagged reduced.
Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works. SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image.
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_bashrc_container.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_support import ENABLED, rnd, podman, setUpModule as _setup, tearDownModule as _teardown  # noqa: E402
import image_support as base  # noqa: E402
from test_attach_command import wait_until  # noqa: E402

# a line of the banner that does not change with its colours or its lettering: the signature under the bar. Its words are colored one by one,
# so the escape sequences are taken out before looking for it.
BANNER_MARK = "your agent's shell, from anywhere"


def plain(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def setUpModule():
    _setup()


def tearDownModule():
    _teardown()


@unittest.skipUnless(ENABLED, "container tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class FragmentInContainer(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="bashrc-ws-")
        self.name = "swarmbox-test-bashrc-" + rnd()
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.addCleanup(self._remove)
        r = podman("run", "-d", "--name", self.name, "--userns=keep-id:uid=1000,gid=1000", "-v", self.ws + ":/home/agent",
                   "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_NO_NESTED=1", "-e", "SWARMBOX_WEB=0", base.TAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(wait_until(lambda: self.sh("test -f /tmp/swarmbox/ready && echo y") == "y", 60, 0.3),
                        podman("logs", self.name).stdout)

    def _remove(self):
        assert self.name.startswith("swarmbox-test-bashrc-")
        podman("rm", "-f", "-t", "0", self.name)

    def sh(self, cmd):
        return podman("exec", self.name, "sh", "-c", cmd).stdout.decode().strip()

    def interactive(self, commands):
        r = subprocess.run(["podman", "exec", "-i", "-e", "TERM=xterm-256color", self.name, "bash", "-i"],
                           input=(commands + "\nexit\n").encode(), capture_output=True, timeout=60)
        return r.stdout.decode()

    def test_the_image_bashrc_sources_the_fragment(self):
        self.assertIn(". /etc/swarmbox/bashrc.sh", self.sh("cat /etc/bash.bashrc"))
        out = self.interactive("alias ll; type yolo | head -1; echo $SWARMBOX_AGENT-end")
        self.assertIn("alias ll=", out)
        self.assertIn("yolo is a function", out)

    def test_banner_health_lines_and_the_stale_image_line(self):
        state = os.path.join(self.ws, ".local", "state", "swarmbox")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "health"), "w") as f:
            f.write("web terminal keeps crashing; see web-terminal.log\nthe local image has been replaced; run swarmbox reset\n")
        out = self.interactive("true")
        self.assertIn(BANNER_MARK, plain(out))
        self.assertIn("web terminal keeps crashing", out)
        self.assertIn("the local image has been replaced", out)

    def test_the_shipped_claude_manifest_gives_the_alias_and_an_unknown_agent_is_reported(self):
        # the image ships the claude manifest (and no program). `yolo` is never run for claude here: it would
        # trigger the first-use install, a real download.
        out = self.interactive("alias claude; alias opencode gemini 2>&1; SWARMBOX_AGENT=nonesuch yolo 2>&1; echo status=$?")
        self.assertIn("alias claude='claude --dangerously-skip-permissions --mcp-config /home/agent/.claude/mcp-servers.json'", out)
        self.assertNotIn("alias opencode=", out)
        self.assertIn("'nonesuch' is not installed", out)
        self.assertIn("status=1", out)

    def test_a_user_manifest_gives_an_alias_and_yolo_runs_it(self):
        d = os.path.join(self.ws, ".config", "swarmbox", "tools", "fakeagent")
        os.makedirs(d)
        with open(os.path.join(d, "tool.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=fakeagent\nKIND=agent\nPROVIDES="fakeagent"\nYOLO_FLAGS="--auto-approve"\n')
        os.makedirs(os.path.join(self.ws, ".local", "bin"))
        prog = os.path.join(self.ws, ".local", "bin", "fakeagent")
        with open(prog, "w") as f:
            f.write('#!/bin/sh\necho "RAN fakeagent $*"\n')
        os.chmod(prog, 0o755)
        out = self.interactive("alias fakeagent; SWARMBOX_AGENT=fakeagent yolo extra")
        self.assertIn("alias fakeagent='fakeagent --auto-approve'", out)
        self.assertIn("RAN fakeagent --auto-approve extra", out)

    def test_attach_command_without_a_terminal_gets_alias_and_path_and_no_banner(self):
        d = os.path.join(self.ws, ".config", "swarmbox", "tools", "fakeagent")
        os.makedirs(d)
        with open(os.path.join(d, "tool.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=fakeagent\nKIND=agent\nPROVIDES="fakeagent"\nYOLO_FLAGS="--auto-approve"\n')
        r = podman("exec", self.name, "swarmbox-entrypoint", "attach", "sh", "-c", "true")
        self.assertEqual(r.returncode, 0)
        r = podman("exec", self.name, "swarmbox-entrypoint", "attach", "alias", "fakeagent")
        self.assertIn("alias fakeagent='fakeagent --auto-approve'", r.stdout.decode())
        self.assertEqual(r.stderr.decode(), "")
        r = podman("exec", self.name, "swarmbox-entrypoint", "attach", "printenv", "PATH")
        self.assertTrue(r.stdout.decode().startswith("/home/agent/.local/share/swarmbox/shims:"), r.stdout)
        self.assertNotIn(BANNER_MARK, plain(r.stdout.decode()))
        self.assertEqual(r.stderr.decode(), "")

    def test_starship_is_active_in_an_interactive_shell(self):
        out = self.interactive('echo "PC=$PROMPT_COMMAND|$PS1"; echo "SC=$STARSHIP_CONFIG"')
        self.assertIn("SC=/etc/swarmbox/starship.toml", out)
        self.assertRegex(out, r"PC=.*starship")


if __name__ == "__main__":
    unittest.main(verbosity=2)
