"""The `swarmbox` script under several `sh` implementations and shellcheck.

The same scenario (version, config set/get/list/seed, env add/list/rm, the tunnel-token mode rule, a second box, an
error exit) runs with each interpreter named explicitly: dash, `bash --posix`, busybox sh, bash started under the name
`sh` (a symlink: POSIX mode, the closest thing to macOS /bin/sh available here), the system /bin/sh, and zsh in sh
emulation. macOS /bin/sh itself and bash 3.2 are not here: those cases are reported as skipped with a tag and stay
[unverified]. shellcheck -s sh runs as a test and skips with a tag when it is missing.
Run: python3 tests/test_host_shells.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

HELPER = os.path.join(ROOT, "container", "host", "swarmbox-host")
CANARY = "CANARY-shells-9d1e"


def interpreters():
    """name -> argv prefix, for each interpreter that exists here; the symlink one is created by the test."""
    out = {}
    if shutil.which("dash"):
        out["dash"] = [shutil.which("dash")]
    if shutil.which("bash"):
        out["bash --posix"] = [shutil.which("bash"), "--posix"]
    if shutil.which("busybox"):
        out["busybox sh"] = [shutil.which("busybox"), "sh"]
    if os.path.exists("/bin/sh"):
        out["/bin/sh"] = ["/bin/sh"]
    if shutil.which("zsh"):
        out["zsh --emulate sh"] = [shutil.which("zsh"), "--emulate", "sh"]
    return out


class ShellMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-hostshells."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)

    def runner(self, prefix):
        env = {"PATH": os.environ["PATH"], "HOME": self.home}

        def run(*args, extra=None, cwd=None):
            e = dict(env)
            e.update(extra or {})
            return subprocess.run(prefix + [HELPER, *args], env=e, capture_output=True, text=True, input="", cwd=cwd or self.tmp, timeout=60)
        return run

    def scenario(self, name, prefix):
        run = self.runner(prefix)
        cfg = os.path.join(self.home, ".config", "swarmbox")

        def ok(p, out=None, code=0):
            self.assertEqual(p.returncode, code, (name, p.stderr))
            if out is not None:
                self.assertEqual(p.stdout, out, name)

        ok(run("version"), "2.0.0\n")
        # remote: no cloudflare-setup.py sits in the support folder (the repository folder here) (exit 3); an unknown subcommand is exit 2
        ok(run("remote", "nope"), "", 2)
        p = run("remote", "status")
        ok(p, "", 3)
        self.assertIn("the support files are missing", p.stderr)
        ok(run("config", "get", "WEB_PORT"), "7681\n")
        ok(run("config", "get", "WITH"), "", 1)
        ok(run("config", "get", "NOPE"), "", 2)
        ok(run("config", "set", "WITH", "claude,gcloud"))
        ok(run("config", "set", "WORKSPACE", "/srv/a b=c"))
        ok(run("config", "get", "WITH"), "claude,gcloud\n")
        ok(run("config", "get", "WORKSPACE"), "/srv/a b=c\n")
        ok(run("config", "get", "WITH", extra={"SWARMBOX_WITH": "x"}), "x\n")
        p = run("config", "list")
        ok(p)
        self.assertIn("WITH=claude,gcloud\tfile\n", p.stdout)
        self.assertEqual(len(p.stdout.splitlines()), 16)
        ok(run("config", "set", "PORTS", "99999"), "", 2)
        ok(run("config", "set", "PORTS", "3000,127.0.0.1:8080:80"))
        ok(run("env", "add", "ANTHROPIC_API_KEY"))
        ok(run("env", "add", "ANTHROPIC_API_KEY"))
        ok(run("env", "add", "SWARMBOX_CLOUDFLARE_X"), "", 2)
        ok(run("env", "list", extra={"ANTHROPIC_API_KEY": CANARY}), "ANTHROPIC_API_KEY\tset\n")
        ok(run("env", "rm", "ANTHROPIC_API_KEY"))
        ok(run("env", "list"), "")
        # file mode and the token rule
        self.assertEqual(oct(os.stat(os.path.join(cfg, "config")).st_mode & 0o777), "0o600")
        with open(os.path.join(cfg, "config"), "a") as f:
            f.write("CLOUDFLARE_TUNNEL_TOKEN=tok123\n")
        ok(run("config", "get", "CLOUDFLARE_TUNNEL_TOKEN"), "tok123\n")
        os.chmod(os.path.join(cfg, "config"), 0o644)
        p = run("config", "get", "CLOUDFLARE_TUNNEL_TOKEN")
        ok(p, "", 1)
        self.assertIn("mode is 644", p.stderr)
        os.chmod(os.path.join(cfg, "config"), 0o600)
        # seed on an existing file: one notice
        p = run("config", "seed", "--with", "other")
        ok(p, "")
        self.assertEqual(p.stderr.count("the installer asked for"), 1)
        ok(run("config", "seed", "--with", "other"), "")
        self.assertEqual(run("config", "seed", "--with", "other").stderr, "")
        # a second box in its own folder, and a fresh seed there
        p = run("config", "seed", "--with", "a", "--workspace", "rel", extra={"SWARMBOX_NAME": "other"}, cwd=self.tmp)
        ok(p)
        ok(run("config", "get", "WORKSPACE", extra={"SWARMBOX_NAME": "other"}), self.tmp + "/rel\n")
        self.assertTrue(os.path.isfile(os.path.join(cfg, "other", "config")))
        self.assertNotIn(CANARY, p.stdout + p.stderr)

    def test_matrix(self):
        ran = []
        for name, prefix in interpreters().items():
            with self.subTest(shell=name):
                shutil.rmtree(self.home)
                os.mkdir(self.home)
                self.scenario(name, prefix)
                ran.append(name)
        print("shells run:", ran)
        for must in ("dash", "bash --posix"):
            self.assertIn(must, ran)

    def test_busybox_runs_when_present(self):
        if not shutil.which("busybox"):
            self.skipTest("[skipped: busybox missing; busybox part unverified here]")
        self.assertIn("busybox sh", interpreters())

    def test_bash_under_the_name_sh(self):
        """A symlink named `sh` to bash: bash then runs in POSIX mode, as macOS's /bin/sh does (bash 3.2 there)."""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("[skipped: bash missing]")
        d = os.path.join(self.tmp, "bin")
        os.mkdir(d)
        os.symlink(bash, os.path.join(d, "sh"))
        self.scenario("bash as sh", [os.path.join(d, "sh")])

    def test_shellcheck_sh_has_no_findings(self):
        sc = shutil.which("shellcheck")
        if not sc:
            self.skipTest("[skipped: shellcheck missing; static part unverified here]")
        p = subprocess.run([sc, "-s", "sh", HELPER], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
