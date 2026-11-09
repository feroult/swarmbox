"""`swarmbox-host remote setup|status|off|token`.

The wrapper runs as a real program (copied into a mktemp folder next to a STUB cloudflare-setup.py that records its argv, the
names (never the values) of the environment variables it sees, the XDG_CONFIG_HOME it got and its working directory into a JSON
file, then exits with the code the test asks for). No Cloudflare account, no network, no Podman is involved: the wrapper
itself never calls Podman (the script does, and the real script is covered by tests/test_cloudflare_setup.py).
HOME, XDG_* and the workspace are mktemp folders.
Run: python3 tests/test_host_remote.py
"""
import json
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_CONNECTOR, DEFAULT_NAME  # noqa: E402

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
        json.dump({"domain": "example.org", "emails": ["a@example.org"], "tunnel": "t"}, f, indent=2)
if sys.argv[1:2] == ["token"] and os.environ.get("STUB_TOKEN"):
    print(os.environ["STUB_TOKEN"])
    print("(info line: the tunnel's own token)", file=sys.stderr)
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
        shutil.copy(os.path.join(ROOT, "container", "host", "DEFAULTS"), os.path.join(self.hdir, "DEFAULTS"))
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


class PrerequisiteAndCodesTest(Base):
    def test_exit_code_of_the_script_is_returned(self):
        for code in (0, 2, 3, 130):
            with self.subTest(code=code):
                r = self.run_h("status", env=self.env(STUB_EXIT=str(code)))
                self.assertEqual(r.returncode, code, r.stderr)

class StatusHostLinesTest(Base):
    CN = DEFAULT_CONNECTOR

    def cfg(self, **data):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "cloudflare.json"), "w") as f:
            json.dump({"domain": "example.org", "emails": ["a@example.org"], "tunnel": DEFAULT_NAME, **data}, f, indent=2)

    def run_with_podman(self, rules, *args):
        from helpers import FakePodman
        with FakePodman({"container": {"rules": rules}}) as fp:
            e = fp.env()
            e.update({"HOME": self.home, "STUB_OUT": self.out})
            r = self.run_h(*args, env=e)
            return r, fp.calls()

    def test_status_adds_the_connector_line_from_the_fake_podman(self):
        self.cfg(session="168h")
        r, calls = self.run_with_podman([{"match": ["inspect", self.CN], "stdout": self.CN + "|true\n"}], "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("connector: running", r.stdout)
        self.assertIn("login session: 168h", r.stdout)
        self.assertEqual(self.rec()["argv"][0], "status")
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][:2], ["container", "inspect"])
        self.assertEqual(calls[0][-1], self.CN)

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
        """No command of the script reads it (it fetches the tunnel token from the API), so none gets it."""
        for sub in ("setup", "status", "off", "token"):
            with self.subTest(sub=sub):
                r = self.run_h(sub, env=self.env(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TUNNEL_SECRET))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", self.rec()["env_names"])


def pty_run(argv, env, answer=None, cwd=None, timeout=30):
    """Run argv on a pseudo-terminal; after the prompt "[y/N]" type `answer` (a line). Returns (exit code, terminal output)."""
    pid, fd = pty.fork()
    if pid == 0:
        if cwd:
            os.chdir(cwd)
        os.execve(argv[0], argv, env)
    out = b""
    sent = answer is None
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if not sent and b"[y/N]" in out:
            time.sleep(0.2)
            os.write(fd, answer.encode() + b"\n")
            sent = True
    _, status = os.waitpid(pid, 0)
    try:
        os.close(fd)
    except OSError:
        pass
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


class TunnelTokenTest(Base):
    """Where the tunnel token comes from, how `remote token` prints it, and the terminal-only setup epilogue."""

    def cfgdir(self):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d, exist_ok=True)
        return d

    def write_cfg(self, text, mode=0o600):
        f = os.path.join(self.cfgdir(), "config")
        if os.path.exists(f):
            os.chmod(f, 0o600)
        with open(f, "w") as fh:
            fh.write(text)
        os.chmod(f, mode)
        return f

    def get(self, env=None, path=None):
        e = self.env(**(env or {}))
        if path:
            e["PATH"] = path
        p = subprocess.run([self.helper, "config", "get", "CLOUDFLARE_TUNNEL_TOKEN"], env=e, capture_output=True, text=True,
                           input="", cwd=self.tmp, timeout=60)
        return p.returncode, p.stdout, p.stderr

    def test_token_from_environment_wins_over_the_file(self):
        f = self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % "file-token-1")
        self.assertEqual(self.get()[:2], (0, "file-token-1\n"))
        self.assertEqual(self.get({"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": "env-token-2"})[:2], (0, "env-token-2\n"))
        # also when the file is too open: the environment needs no file
        os.chmod(f, 0o644)
        rc, out, err = self.get({"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": "env-token-2"})
        self.assertEqual((rc, out), (0, "env-token-2\n"))

    def shims(self, variant):
        d = os.path.join(self.tmp, "shims-" + variant)
        os.mkdir(d)
        real = shutil.which("stat")
        if variant == "bsd":   # BSD stat: no -c, and -f %Lp answers (translated to GNU stat on this host)
            body = ('if [ "$1" = -f ] && [ "$2" = %%Lp ]; then exec %s -c %%a "$3"; fi\n'
                    'echo "stat: illegal option" >&2\nexit 1\n' % real)
        else:                  # no stat at all: the find -perm form must answer
            body = 'echo "stat: not available" >&2\nexit 1\n'
        with open(os.path.join(d, "stat"), "w") as fh:
            fh.write("#!/bin/sh\n" + body)
        os.chmod(os.path.join(d, "stat"), 0o755)
        return d + os.pathsep + os.environ["PATH"]

    def test_remote_token_prints_only_the_token_on_stdout_and_info_on_stderr(self):
        r = self.run_h("token", env=self.env(STUB_TOKEN=TUNNEL_SECRET))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, TUNNEL_SECRET + "\n")
        self.assertIn("info line", r.stderr)
        self.assertNotIn(TUNNEL_SECRET, r.stderr)
        self.assertEqual(self.rec()["argv"][0], "token")
        self.assertNotIn(TUNNEL_SECRET, json.dumps(self.rec()["argv"]))

    def run_pty_setup(self, answer, *args, **env):
        e = self.env(STUB_TOKEN=TUNNEL_SECRET, **env)
        return pty_run([self.helper, "remote", "setup", *args], e, answer=answer, cwd=self.tmp)

    def test_setup_epilogue_yes_stores_the_token_at_mode_600_without_showing_it(self):
        old = os.umask(0o022)
        try:
            rc, shown = self.run_pty_setup("y")
        finally:
            os.umask(old)
        self.assertEqual(rc, 0, shown)
        self.assertNotIn(TUNNEL_SECRET, shown)
        f = os.path.join(self.cfgdir(), "config")
        with open(f) as fh:
            self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TUNNEL_SECRET, fh.read())
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(self.rec()["argv"][0], "token")
        self.assertNotIn(TUNNEL_SECRET, json.dumps(self.rec()["argv"]))
        self.assertEqual(self.get()[:2], (0, TUNNEL_SECRET + "\n"))


if __name__ == "__main__":
    unittest.main()
