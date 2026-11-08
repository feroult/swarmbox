"""Slice 5.2: `swarmbox-host remote setup|status|off|token` (design 5.2, 3.7.2, 3.8, 7; D14, D16, D28, D39).

The wrapper runs as a real program (copied into a mktemp folder next to a STUB cloudflare-setup.py that records its argv, the
names (never the values) of the environment variables it sees, the XDG_CONFIG_HOME it got and its working directory into a JSON
file, then exits with the code the test asks for). No Cloudflare account, no network, no Podman is involved: the wrapper
itself never calls Podman (the script does, and the real script is covered by tests/test_cloudflare_setup.py).
HOME, XDG_* and the workspace are mktemp folders.
Run: python3 tests/test_host_remote.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
REAL_SCRIPT = os.path.join(ROOT, "cloudflare-setup.py")
API_SECRET = "CANARY-api-token-5f2a"
TUNNEL_SECRET = "CANARY-tunnel-token-77c1"
HELPER_TOOLS = ["sh", "dash", "bash", "cat", "rm", "mkdir", "rmdir", "sed", "grep", "head", "tail", "tr", "uname", "find", "stat",
                "mv", "chmod", "printf", "cut", "readlink", "env", "id", "test", "wc", "basename", "dirname", "mktemp", "touch",
                "ls", "true", "false", "expr", "awk", "sort"]

STUB = r'''#!/usr/bin/env python3
import json, os, sys
rec = {"argv": sys.argv[1:], "env_names": sorted(os.environ), "xdg": os.environ.get("XDG_CONFIG_HOME"),
       "cwd": os.getcwd(), "script": sys.argv[0]}
with open(os.environ["STUB_OUT"], "w") as f:
    json.dump(rec, f)
if os.environ.get("STUB_WRITE_CFG"):
    d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "swarmbox")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "cloudflare.json"), "w") as f:
        json.dump({"domain": "example.org", "emails": ["a@example.org"], "tunnel": "swarmbox"}, f, indent=2)
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-remote."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.hdir = os.path.join(self.tmp, "helper")
        os.makedirs(self.hdir)
        self.helper = os.path.join(self.hdir, "swarmbox-host")
        shutil.copy(HELPER_SRC, self.helper)
        os.chmod(self.helper, 0o755)
        shutil.copy(VERSION_SRC, os.path.join(self.hdir, "VERSION"))
        self.stub = os.path.join(self.hdir, "cloudflare-setup.py")
        with open(self.stub, "w") as f:
            f.write(STUB)
        os.chmod(self.stub, 0o755)
        self.out = os.path.join(self.tmp, "stub-out.json")

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_", "CLOUDFLARE_"))}
        e.update({"HOME": self.home, "STUB_OUT": self.out})
        e.update(extra)
        return e

    def run_h(self, *args, env=None):
        return subprocess.run([self.helper, "remote", *args], env=env if env is not None else self.env(),
                              capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)

    def rec(self):
        with open(self.out) as f:
            return json.load(f)


class MappingTest(Base):
    def test_setup_is_apply_with_the_full_passthrough(self):
        r = self.run_h("setup", "--session", "168h", "--hostname", "tty.example.org", "--port", "8123", "--dry-run",
                       "--no-connector", "--tunnel", "t2", "--no-verify", "--yes", "--domain", "example.org",
                       "--email", "a@example.org,b@example.org")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.rec()["argv"]
        self.assertEqual(argv[0], "apply")
        for opt in ("--dry-run", "--no-connector", "--no-verify", "--yes"):
            self.assertIn(opt, argv)
        for opt, val in (("--session", "168h"), ("--hostname", "tty.example.org"), ("--tunnel", "t2"),
                         ("--domain", "example.org"), ("--email", "a@example.org,b@example.org")):
            self.assertEqual(argv[argv.index(opt) + 1], val, opt)
        # the user's --port comes after the default one, so argparse's last value wins
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == "--port"][-1], "8123")

    def test_status_off_and_token_map(self):
        for sub, want in (("status", "status"), ("off", "remove"), ("token", "token")):
            with self.subTest(sub=sub):
                if os.path.exists(self.out):
                    os.remove(self.out)
                r = self.run_h(sub, "--dry-run")
                self.assertEqual(r.returncode, 0, r.stderr)
                argv = self.rec()["argv"]
                self.assertEqual(argv[0], want)
                self.assertIn("--dry-run", argv)

    def test_short_yes_and_connector_image_pass_through(self):
        self.run_h("off", "-y", "--connector-image", "x/y:1")
        argv = self.rec()["argv"]
        self.assertEqual(argv[0], "remove")
        self.assertIn("-y", argv)
        self.assertEqual(argv[argv.index("--connector-image") + 1], "x/y:1")

    def test_arguments_with_spaces_and_glob_characters_stay_single_arguments(self):
        self.run_h("setup", "--domain", "a b*", "--email", "$HOME;x")
        argv = self.rec()["argv"]
        self.assertEqual(argv[argv.index("--domain") + 1], "a b*")
        self.assertEqual(argv[argv.index("--email") + 1], "$HOME;x")


class DefaultsTest(Base):
    def test_name_and_web_port_defaults_follow_config(self):
        self.run_h("status")
        argv = self.rec()["argv"]
        self.assertEqual(argv[argv.index("--name") + 1], "swarmbox")
        self.assertEqual(argv[argv.index("--port") + 1], "7681")
        self.run_h("status", env=self.env(SWARMBOX_NAME="dev", SWARMBOX_WEB_PORT="8888"))
        argv = self.rec()["argv"]
        self.assertEqual(argv[argv.index("--name") + 1], "dev")
        self.assertEqual(argv[argv.index("--port") + 1], "8888")

    def test_web_port_from_the_config_file(self):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d)
        with open(os.path.join(d, "config"), "w") as f:
            f.write("WEB_PORT=9001\n")
        os.chmod(os.path.join(d, "config"), 0o600)
        self.run_h("status")
        argv = self.rec()["argv"]
        self.assertEqual(argv[argv.index("--port") + 1], "9001")

    def test_invalid_name_or_port_is_exit_2_and_the_script_is_not_run(self):
        for k, v in (("SWARMBOX_NAME", "bad name"), ("SWARMBOX_WEB_PORT", "99999")):
            with self.subTest(k=k):
                r = self.run_h("status", env=self.env(**{k: v}))
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertFalse(os.path.exists(self.out))

    def test_cloudflare_json_dir_is_shared_with_url(self):
        for label, extra in (("default", {}),
                             ("xdg", {"XDG_CONFIG_HOME": os.path.join(self.tmp, "xdgc")}),
                             ("relative xdg is ignored", {"XDG_CONFIG_HOME": "rel/dir"})):
            with self.subTest(label=label):
                if os.path.exists(self.out):
                    os.remove(self.out)
                r = self.run_h("setup", env=self.env(STUB_WRITE_CFG="1", **extra))
                self.assertEqual(r.returncode, 0, r.stderr)
                u = subprocess.run([self.helper, "url"], env=self.env(**extra), capture_output=True, text=True, input="",
                                   cwd=self.tmp, timeout=60)
                self.assertEqual(u.returncode, 0, u.stderr)
                self.assertIn("https://swarmbox.example.org\n", u.stdout)


class PrerequisiteAndCodesTest(Base):
    def test_python3_missing_exits_3_with_the_documented_message(self):
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS:
            p = shutil.which(t)
            if p and not os.path.exists(os.path.join(bindir, t)):
                os.symlink(p, os.path.join(bindir, t))
        self.assertIsNone(shutil.which("python3", path=bindir))
        r = self.run_h("status", env=self.env(PATH=bindir))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(r.stderr, "swarmbox: python3 is needed for 'swarmbox remote' and was not found.\n")
        self.assertFalse(os.path.exists(self.out))

    def test_missing_script_next_to_the_helper_is_exit_3(self):
        os.remove(self.stub)
        r = self.run_h("status")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("cloudflare-setup.py", r.stderr)
        self.assertIn("swarmbox update", r.stderr)

    def test_exit_code_of_the_script_is_returned(self):
        for code in (0, 2, 3, 130):
            with self.subTest(code=code):
                r = self.run_h("status", env=self.env(STUB_EXIT=str(code)))
                self.assertEqual(r.returncode, code, r.stderr)

    def test_unknown_remote_subcommand_exit_2_and_usage(self):
        for args in ([], ["frobnicate"], ["--dry-run"], ["apply"], ["remove"]):
            with self.subTest(args=args):
                r = self.run_h(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage: swarmbox-host", r.stderr)
                self.assertIn("remote setup|status|off|token", r.stderr)
                self.assertFalse(os.path.exists(self.out))

    def test_unknown_subcommand_is_checked_before_python3(self):
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS:
            p = shutil.which(t)
            if p:
                os.symlink(p, os.path.join(bindir, t))
        r = self.run_h("nope", env=self.env(PATH=bindir))
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_remote_works_without_podman_installed(self):
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS + ["python3"]:
            p = shutil.which(t)
            if p:
                os.symlink(p, os.path.join(bindir, t))
        self.assertIsNone(shutil.which("podman", path=bindir))
        r = self.run_h("status", env=self.env(PATH=bindir))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_wrapper_never_calls_podman(self):
        from helpers import FakePodman
        with FakePodman({}) as fp:
            e = fp.env()
            e.update({"HOME": self.home, "STUB_OUT": self.out})
            r = self.run_h("setup", "--dry-run", env=e)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(fp.calls(), [])


class SecretsTest(Base):
    def test_no_secret_in_argv(self):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d)
        with open(os.path.join(d, "config"), "w") as f:
            f.write("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TUNNEL_SECRET)
        os.chmod(os.path.join(d, "config"), 0o600)
        for sub in ("setup", "status", "off", "token"):
            with self.subTest(sub=sub):
                r = self.run_h(sub, env=self.env(CLOUDFLARE_API_TOKEN=API_SECRET))
                self.assertEqual(r.returncode, 0, r.stderr)
                rec = self.rec()
                self.assertNotIn(API_SECRET, json.dumps(rec["argv"]))
                self.assertNotIn(TUNNEL_SECRET, json.dumps(rec["argv"]))
                self.assertIn("CLOUDFLARE_API_TOKEN", rec["env_names"])  # the API token stays in the environment only
                self.assertNotIn(API_SECRET, r.stdout + r.stderr)
                self.assertNotIn(TUNNEL_SECRET, r.stdout + r.stderr)

    def test_the_tunnel_token_is_not_exported_to_any_command(self):
        """No command of the script reads it (it fetches the tunnel token from the API), so none gets it (decision [5.2])."""
        for sub in ("setup", "status", "off", "token"):
            with self.subTest(sub=sub):
                r = self.run_h(sub, env=self.env(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TUNNEL_SECRET))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", self.rec()["env_names"])


class RealScriptTest(Base):
    def test_real_script_usage_error_is_exit_2(self):
        shutil.copy(REAL_SCRIPT, self.stub)
        r = self.run_h("status", "--no-such-option")
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_real_script_accepts_the_mapped_arguments(self):
        shutil.copy(REAL_SCRIPT, self.stub)
        # no API token and no terminal: the script refuses at once, after parsing every argument we pass (exit 1, not 2)
        r = self.run_h("setup", "--dry-run", "--session", "168h", "--domain", "example.org", "--email", "a@example.org",
                       "--hostname", "tty.example.org", "--port", "8123", "--no-connector", "--tunnel", "t", "--no-verify", "-y")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("CLOUDFLARE_API_TOKEN", r.stderr)


if __name__ == "__main__":
    unittest.main()
