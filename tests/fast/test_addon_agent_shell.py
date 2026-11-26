"""The shell functions of the agent addons (claude, antigravity, opencode): how each starts in auto-approve mode.

The auto-approve words are not in bashrc.sh: each agent addon declares them in its agent/agent.conf, and `swarmbox-agents sh` turns
them into one function per agent, which the box evaluates in every interactive shell; an addon whose agent needs more than the
declaration has its own shell.sh (OpenCode). These tests run the REAL generated functions and the REAL shell.sh in a mktemp tree with a
fake agent program that prints every argument as [arg], in every shell that exists here (bash always, zsh when installed), and also
through the real bashrc.sh fragment (what `yolo` runs). SWARMBOX_YOLO=0 turns auto-approve off everywhere.
Run with: python3 -W error tests/fast/test_addon_agent_shell.py   (needs bash; zsh is optional)
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

REAL_ADDONS = os.path.join(ROOT, "container", "addons")
FRAGMENT = os.path.join(ROOT, "container", "config", "bashrc.sh")
LIB = os.path.join(ROOT, "container", "scripts")
SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]
AGENTS = ("claude", "opencode", "agy")
ADDON_OF = {"agy": "antigravity"}  # the command agy comes from the addon antigravity


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="agent-shell-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        for name in AGENTS:
            write(os.path.join(self.d, "bin", name), '#!/bin/sh\nprintf "%s:" "$(basename "$0")"; for a in "$@"; do printf "[%s]" "$a"; done; echo\n', 0o755)

    def env(self, yolo=None):
        e = {"PATH": os.path.join(self.d, "bin") + ":/usr/bin:/bin", "HOME": self.d, "TERM": "dumb"}
        if yolo is not None:
            e["SWARMBOX_YOLO"] = yolo
        return e

    def run_in(self, shell, agent, args, yolo=None):
        """Define the function of `agent` in `shell` (its addon's shell.sh, else the registry's generated one) and run `agent args`;
        the fake program prints what it received."""
        own = os.path.join(REAL_ADDONS, ADDON_OF.get(agent, agent), "shell.sh")
        if os.path.exists(own):
            script = ". %s; %s %s" % (own, agent, args)
        else:
            gen = subprocess.run([sys.executable, "-I", os.path.join(LIB, "swarmbox-agents.py"), "sh"], capture_output=True, text=True, timeout=30,
                                 env={"PATH": "/usr/bin:/bin", "HOME": self.d, "SWARMBOX_TEST_IMAGE_ADDONS": REAL_ADDONS})
            self.assertEqual(gen.returncode, 0, gen.stderr)
            self.assertIn("%s() {" % agent, gen.stdout)
            path = os.path.join(self.d, "agents.sh")
            write(path, gen.stdout)
            script = ". %s; %s %s" % (path, agent, args)
        r = subprocess.run([shell, "-c", script], env=self.env(yolo), capture_output=True, text=True, timeout=30, cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout.strip()


class ClaudeShell(Base):
    MCP = "[--mcp-config][%s/.claude/mcp-servers.json]"

    def want(self, rest=""):
        return "claude:[--dangerously-skip-permissions]" + self.MCP % self.d + rest

    def test_the_prompt_forms_get_auto_approve_and_the_mcp_config(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "claude", ""), self.want())
                self.assertEqual(self.run_in(sh, "claude", "-p hello"), self.want("[-p][hello]"))
                self.assertEqual(self.run_in(sh, "claude", "'fix the build'"), self.want("[fix the build]"))
                self.assertEqual(self.run_in(sh, "claude", "--model haiku"), self.want("[--model][haiku]"))

    def test_subcommands_do_not_receive_the_flags(self):
        for sh in SHELLS:
            for args in ("update", "mcp list", "mcp add x -- y", "doctor", "auth login", "install", "agents"):
                with self.subTest(shell=sh, args=args):
                    self.assertEqual(self.run_in(sh, "claude", args), "claude:" + "".join("[%s]" % a for a in args.split()))

    def test_swarmbox_yolo_zero_turns_auto_approve_off_and_keeps_the_mcp_config(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                for args in ("", "-p hello"):
                    got = self.run_in(sh, "claude", args, yolo="0")
                    self.assertNotIn("--dangerously-skip-permissions", got)
                    self.assertIn(self.MCP % self.d, got, "the MCP servers of the box are not a permission")
                self.assertIn("--dangerously-skip-permissions", self.run_in(sh, "claude", "", yolo="1"))

class AntigravityShell(Base):
    def test_agy_starts_with_dangerously_skip_permissions(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "agy", ""), "agy:[--dangerously-skip-permissions]")
                self.assertEqual(self.run_in(sh, "agy", "-p 'say hi'"), "agy:[--dangerously-skip-permissions][-p][say hi]")
                self.assertEqual(self.run_in(sh, "agy", "--model x"), "agy:[--dangerously-skip-permissions][--model][x]")

    def test_subcommands_do_not_receive_the_flag(self):
        for sh in SHELLS:
            for args in ("update", "mcp list", "mcp add x", "models", "install", "agents", "help"):
                with self.subTest(shell=sh, args=args):
                    self.assertEqual(self.run_in(sh, "agy", args), "agy:" + "".join("[%s]" % a for a in args.split()))

    def test_swarmbox_yolo_zero_turns_it_off(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "agy", "-p x", yolo="0"), "agy:[-p][x]")


class OpencodeShell(Base):
    def test_auto_goes_to_opencode_and_opencode_run_only(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "opencode", ""), "opencode:[--auto]")
                self.assertEqual(self.run_in(sh, "opencode", "run 'do it'"), "opencode:[run][--auto][do it]")
                self.assertEqual(self.run_in(sh, "opencode", "--model local/x"), "opencode:[--auto][--model][local/x]")

    def test_other_subcommands_are_refused_the_flag_so_they_do_not_get_it(self):
        for sh in SHELLS:
            for args in ("mcp list", "auth login", "models", "upgrade", "--version", "--help"):
                with self.subTest(shell=sh, args=args):
                    self.assertEqual(self.run_in(sh, "opencode", args), "opencode:" + "".join("[%s]" % a for a in args.split()))

    def test_a_subcommand_wins_over_a_folder_of_the_same_name(self):
        for sh in SHELLS:
            for name in ("mcp", "auth", "models", "stats", "export", "web", "agent"):
                with self.subTest(shell=sh, name=name):
                    os.makedirs(os.path.join(self.d, name), exist_ok=True)
                    self.assertEqual(self.run_in(sh, "opencode", name + " list"), "opencode:[%s][list]" % name)

    def test_a_project_folder_gets_the_flag(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                os.makedirs(os.path.join(self.d, "proj"), exist_ok=True)
                self.assertEqual(self.run_in(sh, "opencode", "proj"), "opencode:[--auto][proj]")

    def test_swarmbox_yolo_zero_turns_it_off(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "opencode", "run x", yolo="0"), "opencode:[run][x]")
                self.assertEqual(self.run_in(sh, "opencode", "", yolo="0"), "opencode:")

    def test_the_configuration_file_of_the_box_is_exported(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                r = subprocess.run([sh, "-c", '. %s; echo "$OPENCODE_CONFIG"' % os.path.join(REAL_ADDONS, "opencode", "shell.sh")],
                                   env=self.env(), capture_output=True, text=True, timeout=30, cwd=self.d)
                self.assertEqual(r.stdout.strip(), "/tmp/swarmbox/opencode.json")


class ThroughTheFragment(Base):
    """The real bashrc.sh over the real addons: the functions are there, `yolo` runs the default agent, and no alias is built."""

    def frag(self, commands, **extra):
        d = self.d
        env = {"PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "HOME": d, "XDG_CONFIG_HOME": os.path.join(d, "c"),
               "XDG_DATA_HOME": os.path.join(d, "d"), "XDG_STATE_HOME": os.path.join(d, "s"),
               "SWARMBOX_IMAGE_ADDONS_DIR": REAL_ADDONS, "SWARMBOX_IMAGE_SHIMS_DIR": os.path.join(d, "shims"),
               "SWARMBOX_VENV": os.path.join(d, "no-venv"), "SWARMBOX_DIRS_SH": os.path.join(LIB, "dirs.sh"),
               "SWARMBOX_STARSHIP_INIT": os.path.join(d, "none"),
               "SWARMBOX_AGENTS_BIN": os.path.join(LIB, "swarmbox-agents.py"),
               "TERM": "dumb"}
        env.update(extra)
        os.makedirs(os.path.join(d, "s", "swarmbox"), exist_ok=True)
        return subprocess.run(["bash", "--noprofile", "--norc", "-i"], input='. %s\n%s\nexit\n' % (FRAGMENT, commands), env=env,
                              capture_output=True, text=True, timeout=30, cwd=d)

    def test_every_agent_is_a_function_and_none_is_an_alias(self):
        r = self.frag("type claude opencode agy")
        for name in AGENTS:
            self.assertIn("%s is a function" % name, r.stdout, r.stdout + r.stderr)
        self.assertNotIn("aliased", r.stdout)
        self.assertEqual(self.frag("alias claude opencode agy 2>&1").stdout.count("alias "), 0)

    def test_yolo_runs_the_default_agent_in_auto_approve_mode(self):
        for agent, want in (("claude", "claude:[--dangerously-skip-permissions]"),
                            ("opencode", "opencode:[run][--auto][go]")):
            with self.subTest(agent=agent):
                args = {"claude": "-p go", "opencode": "run go"}[agent]
                r = self.frag("yolo %s" % args, SWARMBOX_AGENT=agent)
                self.assertIn(want, r.stdout, r.stdout + r.stderr)
                self.assertEqual(r.stdout.count("%s:" % agent), 1)

    def test_yolo_runs_agy_when_the_default_agent_is_the_addon_antigravity(self):
        # the host records the first addon of WITH, and the addon antigravity provides the command agy
        for agent in ("antigravity", "agy"):
            with self.subTest(agent=agent):
                r = self.frag("yolo -p go", SWARMBOX_AGENT=agent)
                self.assertIn("agy:[--dangerously-skip-permissions][-p][go]", r.stdout, r.stdout + r.stderr)


class DeclaredOnly(Base):
    """An agent addon with only agent/agent.conf: the registry gives it a function in every shell, through the real fragment."""

    def test_a_declared_agent_gets_a_function_with_its_words(self):
        addon = os.path.join(self.d, "c", "swarmbox", "addons", "robo")
        write(os.path.join(addon, "addon.conf"), 'SCHEMA=1\nNAME=robo\nDESCRIPTION="x"\nVERSION=1\nCOMMANDS="robo"\n')
        write(os.path.join(addon, "agent", "agent.conf"),
              'ID=robo\nYOLO_ARGS="--yes --fast"\nMCP_ARGS="--mcp {home}/m.json"\nPRINT_FLAGS="-q"\nPASSTHROUGH="login logout"\n')
        write(os.path.join(self.d, "bin", "robo"), '#!/bin/sh\nprintf "robo:"; for a in "$@"; do printf "[%s]" "$a"; done; echo\n', 0o755)
        guard = '_sb_worktree_guard() { echo "GUARD $*"; }; '
        env = {"PATH": os.path.join(self.d, "bin") + ":/usr/bin:/bin", "HOME": self.d, "XDG_CONFIG_HOME": os.path.join(self.d, "c"),
               "XDG_DATA_HOME": os.path.join(self.d, "d"), "XDG_STATE_HOME": os.path.join(self.d, "s"),
               "SWARMBOX_IMAGE_ADDONS_DIR": REAL_ADDONS, "SWARMBOX_IMAGE_SHIMS_DIR": os.path.join(self.d, "shims"),
               "SWARMBOX_VENV": os.path.join(self.d, "no-venv"), "SWARMBOX_DIRS_SH": os.path.join(LIB, "dirs.sh"),
               "SWARMBOX_STARSHIP_INIT": os.path.join(self.d, "none"), "SWARMBOX_AGENTS_BIN": os.path.join(LIB, "swarmbox-agents.py"),
               "TERM": "dumb"}
        os.makedirs(os.path.join(self.d, "s", "swarmbox"), exist_ok=True)

        def run(cmds, **extra):
            r = subprocess.run(["bash", "--noprofile", "--norc", "-i"], input=". %s\n%s%s\nexit\n" % (FRAGMENT, guard, cmds),
                               env=dict(env, **extra), capture_output=True, text=True, timeout=30, cwd=self.d)
            return r.stdout

        m = "[--mcp][%s/m.json]" % self.d
        self.assertIn("GUARD robo go\nrobo:[--yes][--fast]%s[go]" % m, run("robo go"))
        self.assertIn("robo:[--yes][--fast]%s[-q][x]" % m, run("robo -q x"))
        self.assertNotIn("GUARD", run("robo -q x"), "a one-shot call (PRINT_FLAGS) is not guarded")
        self.assertIn("robo:[login][me]", run("robo login me"))
        self.assertIn("robo:%s[go]" % m, run("robo go", SWARMBOX_YOLO="0"))
        self.assertIn("robo:[--yes][--fast]%s[go]" % m, run("yolo go", SWARMBOX_YOLO="0", SWARMBOX_AGENT="robo"))
        # an agent whose addon has a shell.sh keeps its own function (OpenCode: --auto only where it is accepted)
        self.assertIn("opencode:[--auto]", run("opencode"))


if __name__ == "__main__":
    unittest.main()
