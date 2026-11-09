"""Slice 7.3: the adversarial tests behind docs/security-review.md (design 11, D16, D26, D28, 3.3 "up lock", 3.7.1-3.7.3).

One class per finding class of the review. Everything runs the REAL host helper (swarmbox-host, POSIX sh) and the real
cloudflare-setup.py against the shared FakePodman; HOME, the XDG folders and the workspaces are mktemp folders and nothing
here starts a real container. The pre-planted symlink tests need the pid of the helper before it runs: a wrapper writes its
own pid, waits for a marker file and `exec`s the helper, so the pid is the helper's and the planting happens before its first
step (no sleeps decide an outcome).
Also checked here: docs/security-review.md exists, every finding row has a severity, a location and a status, a row that says
"fixed" or "documented" names a test that exists in tests/, and no row is open.
Run: python3 tests/test_security_review.py
"""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_host_update as upd  # noqa: E402
import test_host_up as up_tests  # noqa: E402
from function_cases import make_archive  # noqa: E402
from helpers import ROOT, DEFAULT_CONNECTOR, DEFAULT_NAME  # noqa: E402

TOK = "tunnelTOKEN0123456789abcdefSECRETvalue=="
CN = DEFAULT_CONNECTOR


def load_cf(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "cloudflare-setup.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base(up_tests.Base):
    def assert_no_marker(self):
        for d in (self.tmp, self.ws, self.home, os.getcwd()):
            self.assertFalse(os.path.exists(os.path.join(d, "MARK")), "a command substitution ran")

    def plant_run(self, args, plant, env=None, timeout=60):
        """Run the helper with `args`; call plant(pid) after the pid is known and before the helper does anything."""
        wrap = os.path.join(self.tmp, "wrap.sh")
        pidf = os.path.join(self.tmp, "wrap.pid")
        go = os.path.join(self.tmp, "wrap.go")
        for p in (pidf, go):
            if os.path.exists(p):
                os.unlink(p)
        with open(wrap, "w") as f:
            f.write('#!/bin/sh\necho $$ > "$1.tmp"; mv "$1.tmp" "$1"; shift\n'
                    'while [ ! -e "$1" ]; do sleep 0.01; done\nshift\nexec "$@"\n')
        os.chmod(wrap, 0o755)
        p = subprocess.Popen([wrap, pidf, go, self.helper, *args], env=env or self.env(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.tmp)
        deadline = time.time() + 20
        while not os.path.exists(pidf):
            self.assertLess(time.time(), deadline, "the wrapper did not start")
            time.sleep(0.01)
        with open(pidf) as f:
            pid = int(f.read().strip())
        self.assertEqual(pid, p.pid)
        plant(pid)
        open(go, "w").close()
        out, err = p.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, p.returncode, out, err)

    def victim(self, name="victim"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write("KEEP\n")
        return path

    def assert_victim(self, path):
        with open(path) as f:
            self.assertEqual(f.read(), "KEEP\n", "a planted symlink was followed and its target was written")

    def cfg_dir(self):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d, exist_ok=True)
        return d


# ============================================================================ quoting of user values

HOSTILE_NAMES = ["with space", "it's", 'dq"quote', "$(touch MARK)", "`touch MARK`", "semi;colon&amp|pipe", "-leading-dash",
                 "star*glob?[x]", "#hash", "back\\slash", "tab\there", "{brace,comma}", "unicode-é"]


class QuotingTest(Base):
    def flags(self, ws, **extra):
        return subprocess.run([self.helper, "create-flags"], env=self.env(SWARMBOX_WORKSPACE=ws, **extra),
                              capture_output=True, text=True, input="", cwd=self.tmp)

    def test_workspace_names_with_hostile_characters_stay_one_literal_argument(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                ws = os.path.join(self.tmp, "ws-" + name)
                os.makedirs(ws, exist_ok=True)
                p = self.flags(ws)
                self.assertEqual(p.returncode, 0, p.stderr)
                lines = p.stdout.split("\n")[:-1]
                i = lines.index("-v")
                self.assertEqual(lines[i + 1], ws + ":/home/agent")
                self.assertIn("swarmbox.workspace=" + ws, lines)
                self.assert_no_marker()

    def test_config_set_refuses_shell_metacharacters_in_every_validated_key(self):
        cases = [("HOSTNAME", "$(touch MARK)"), ("HOSTNAME", "a b"), ("HOSTNAME", "a;b"), ("TZ", "`touch MARK`"),
                 ("TZ", "../../etc/passwd"), ("PORTS", "80;touch MARK"), ("PORTS", "80,$(x)"), ("WITH", "a;b"),
                 ("WITH", "$(x)"), ("AGENT", "$(touch MARK)"), ("AGENT", "-x"), ("ENV_KEYS", "A;B"), ("ENV_KEYS", "A B"),
                 ("ENV_KEYS", "$(x)"), ("IMAGE", "$(touch MARK)"), ("IMAGE", "`x`"), ("IMAGE", "a b"), ("IMAGE", "a;b"),
                 ("WEB_PORT", "80;x"), ("WEB", "1;x"), ("INIT", "$(x)"), ("BROWSER_URL", "http://a b"),
                 ("WORKSPACE", "/tmp/a:b")]
        for key, val in cases:
            with self.subTest(key=key, val=val):
                r = self.run_h("config", "set", key, val)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "swarmbox", "config")))
                self.assert_no_marker()

# ============================================================================ image references (option injection)

class ImageReferenceTest(Base):
    def test_an_image_reference_that_starts_with_a_dash_is_refused_in_every_source(self):
        for bad in ("-x:1", "--privileged", "--rm=false", "-"):
            with self.subTest(bad=bad):
                self.assertEqual(self.run_h("config", "set", "IMAGE", bad).returncode, 2)
                p = subprocess.run([self.helper, "create-flags"], env=self.env(SWARMBOX_IMAGE=bad), capture_output=True,
                                   text=True, input="", cwd=self.tmp)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertEqual(self.run_h("config", "seed", "--image", bad).returncode, 2)

# ============================================================================ temporary files, the lock, private folders

class TempFileTest(Base):
    def test_the_config_write_does_not_follow_a_planted_temp_symlink(self):
        cdir = self.cfg_dir()
        v = self.victim()

        def plant(pid):
            os.symlink(v, os.path.join(cdir, "config.tmp.%d" % pid))
        r = self.plant_run(["config", "set", "WEB_PORT", "9000"], plant)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_victim(v)
        with open(os.path.join(cdir, "config")) as f:
            self.assertIn("WEB_PORT=9000\n", f.read())
        self.assertEqual(os.stat(os.path.join(cdir, "config")).st_mode & 0o777, 0o600)

    def test_a_symlink_planted_at_the_lock_path_is_replaced_and_its_target_left_alone(self):
        os.makedirs(self.state)
        target = os.path.join(self.tmp, "lock-target")
        os.mkdir(target)
        with open(os.path.join(target, "keep"), "w") as f:
            f.write("KEEP\n")
        lock = os.path.join(self.state, "up-%s.lock" % DEFAULT_NAME)
        os.symlink(target, lock)
        self.podman()
        r = self.up(SWARMBOX_TEST_LOCK_PIDWAIT="3", SWARMBOX_TEST_NAP="0.02")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(target), ["keep"])
        self.assertFalse(os.path.lexists(lock))
        self.assertEqual(len(self.real_runs()), 1)

class CleanupTest(Base):
    """Every way out of up, reset, stop and update leaves no temporary file and no lock (exact names)."""

    def leftovers(self):
        if not os.path.isdir(self.state):
            return []
        return [n for n in os.listdir(self.state)
                if re.match(r"^(flags|cid|err)\.\d+$", n) or n.endswith(".lock") or ".lock.stale." in n]

    def test_sighup_sigint_sigterm_leave_nothing_and_report_the_signal(self):
        for sig, rc in ((signal.SIGHUP, 129), (signal.SIGINT, 130), (signal.SIGTERM, 143)):
            with self.subTest(sig=int(sig)):
                shutil.rmtree(self.state, True)
                self.podman()
                gate = os.path.join(self.tmp, "gate-%d" % sig)
                prog = os.path.join(self.tmp, "slow-flags-%d" % sig)
                with open(prog, "w") as f:
                    f.write('#!/bin/sh\n: > "%s.in"\nwhile [ ! -e "%s" ]; do sleep 0.02; done\nexec "%s" create-flags\n'
                            % (gate, gate, self.helper))
                os.chmod(prog, 0o755)
                p = subprocess.Popen([self.helper, "up"], env=self.env(SWARMBOX_TEST_CREATE_FLAGS=prog),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     cwd=self.tmp,
                                     # a runner started with nohup passes SIGHUP as ignored, and a shell cannot trap that
                                     preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_DFL))
                deadline = time.time() + 20
                while not os.path.exists(gate + ".in"):
                    self.assertLess(time.time(), deadline)
                    time.sleep(0.02)
                self.assertTrue(os.path.isdir(os.path.join(self.state, "up-%s.lock" % DEFAULT_NAME)))
                p.send_signal(sig)
                p.communicate(timeout=20)
                open(gate, "w").close()
                self.assertEqual(p.returncode, rc)
                self.assertEqual(self.leftovers(), [])
                self.assertEqual(self.real_runs(), [])

# ============================================================================ the tunnel token

class TokenTest(Base):
    def cfg_with_token(self, mode=0o600):
        cfg = os.path.join(self.cfg_dir(), "config")
        with open(cfg, "w") as f:
            f.write("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOK)
        os.chmod(cfg, mode)

    def env_clean(self, **extra):
        e = self.env(**extra)
        e.pop("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", None)
        return e

    def test_the_token_from_the_file_or_the_environment_is_never_in_argv_output_or_the_box_flags(self):
        for source in ("env", "file"):
            with self.subTest(source=source):
                shutil.rmtree(self.state, True)
                if source == "file":
                    self.cfg_with_token()
                    extra = dict(SWARMBOX_WEB="1")
                else:
                    extra = dict(SWARMBOX_WEB="1", SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TOK)
                self.podman()
                r = self.run_h("up", env=self.env(**extra))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn(TOK, r.stdout)
                self.assertNotIn(TOK, r.stderr)
                for c in self.calls():
                    self.assertFalse(any(TOK in a for a in c), c)
                run = [c for c in self.subs("run") if CN in c][0]
                self.assertEqual(run[run.index("-e") + 1], "TUNNEL_TOKEN")
                self.assertEqual(self.fp.envs()[self.calls().index(run)].get("TUNNEL_TOKEN"), TOK)
                box = [c for c in self.real_runs() if CN not in c][0]
                self.assertFalse(any("TUNNEL" in a for a in box), box)

    def test_a_token_in_a_file_with_a_loose_mode_is_ignored_and_not_echoed(self):
        self.cfg_with_token(0o644)
        self.podman()
        r = self.run_h("up", env=self.env_clean(SWARMBOX_WEB="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("chmod 600", r.stderr)
        self.assertNotIn(TOK, r.stdout + r.stderr)
        self.assertEqual([c for c in self.subs("run") if CN in c], [])

    def test_the_remote_wrapper_does_not_pass_the_tunnel_token_to_the_script(self):
        script = os.path.join(self.hdir, "cloudflare-setup.py")
        out = os.path.join(self.tmp, "seen")
        with open(script, "w") as f:
            f.write("import os, sys\nopen(%r, 'w').write(repr((sys.argv, [k for k in os.environ if 'TUNNEL' in k])))\n" % out)
        r = self.run_h("remote", "status", env=self.env(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TOK))
        with open(out) as f:
            seen = f.read()
        self.assertNotIn(TOK, seen + r.stdout + r.stderr)
        self.assertTrue(seen.endswith(", [])"), seen)


# ============================================================================ modes of created files

class ModeTest(Base):
    def umask0(self, *args, **extra):
        return subprocess.run(["/bin/sh", "-c", 'umask 000; exec "$@"', "sh", self.helper, *args], env=self.env(**extra),
                              capture_output=True, text=True, input="", cwd=self.tmp)

    def test_nothing_the_helper_creates_is_open_to_group_or_others_even_with_umask_000(self):
        self.podman()
        for args in (("config", "set", "WEB_PORT", "9000"), ("env", "add", "MYVAR"), ("up",),
                     ("config", "seed", "--with", "x")):
            r = self.umask0(*args)
            self.assertIn(r.returncode, (0, 1), (args, r.stderr))
        files = []
        for root in (os.path.join(self.home, ".config"), os.path.join(self.home, ".local")):
            for dp, dns, fns in os.walk(root):
                for n in dns + fns:
                    p = os.path.join(dp, n)
                    if not os.path.islink(p):
                        files.append((p, stat.S_IMODE(os.lstat(p).st_mode)))
        self.assertTrue(files)
        for path, mode in files:
            self.assertEqual(mode & 0o077, 0, "%s has mode %o" % (path, mode))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.home, ".config", "swarmbox", "config")).st_mode), 0o600)


# ============================================================================ update --to, the archive, the folder swap

class UpdateInputTest(upd.UpdateBase):
    def test_update_to_refuses_references_and_hostile_tags_before_any_podman_call(self):
        bad = ["a b", "-x", "--help", "a;b", "$(touch MARK)", "`touch MARK`", "a/b", "a:b", "a@sha256:abc", "a|b", "a&b",
               "a>b", "a'b", 'a"b', ".hidden", "a\\b", "x" * 129, "a*b", "a?b", "a\tb", "~", "${HOME}", "a\nb", "a\rb", ""]
        self.podman_for("2.0.1")
        for tag in bad:
            with self.subTest(tag=tag):
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(r.stdout, "")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "MARK")))

    def test_an_exact_tag_must_equal_the_version_inside_the_image(self):
        self.podman_for("2.0.5")
        before = self.before()
        r = self.update("--to", "2.0.9")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assert_unchanged(before)

    def test_an_archive_with_parent_or_absolute_entries_is_refused_and_nothing_escapes(self):
        outside = os.path.join(self.tmp, "escaped")
        for extra in ({"../escaped": b"x"}, {"../../escaped": b"x"}, {"a/../../escaped": b"x"}):
            with self.subTest(extra=list(extra)):
                self.podman_for("2.0.1", extra=extra)
                before = self.before()
                r = self.update("--to", "2.0.1")
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assert_unchanged(before)
                self.assertFalse(os.path.lexists(outside))
        p = os.path.join(self.tmp, "abs.tar")
        make_archive(p, version="2.0.1")
        absname = os.path.join(self.tmp, "abs-escaped")
        with tarfile.open(p, "a") as tf:
            ti = tarfile.TarInfo(absname)
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        self.podman(run={"stdout_file": p})
        before = self.before()
        r = self.update("--to", "2.0.1")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assert_unchanged(before)
        self.assertFalse(os.path.lexists(absname))

# ============================================================================ parsing of the config file

class ConfigParsingTest(Base):
    def write(self, text, mode=0o600):
        cfg = os.path.join(self.cfg_dir(), "config")
        with open(cfg, "w", newline="") as f:
            f.write(text)
        os.chmod(cfg, mode)

    def test_substitutions_and_dangerous_keys_in_the_file_are_inert(self):
        evil = os.path.join(self.tmp, "evilbin")
        os.mkdir(evil)
        with open(os.path.join(evil, "podman"), "w") as f:
            f.write("#!/bin/sh\ntouch %s/MARK\n" % self.tmp)
        os.chmod(os.path.join(evil, "podman"), 0o755)
        self.write("PATH=%s\nLD_PRELOAD=/x\nIFS=x\nSWARMBOX_WORKSPACE=/nowhere\nHOSTNAME=$(touch %s/MARK)\n"
                   "WEB_PORT=`touch %s/MARK`\n$(touch %s/MARK)=1\nWITH=a=b=c\n" % (evil, self.tmp, self.tmp, self.tmp))
        self.podman()
        for args in (("config", "list"), ("config", "get", "WEB_PORT"), ("create-flags",), ("url",), ("up",)):
            self.run_h(*args)
            self.assert_no_marker()
        self.assertEqual(self.real_runs(), [])  # the invalid HOSTNAME stops `up` before Podman creates anything

# ============================================================================ the review document

DOC = os.path.join(ROOT, "docs", "security-review.md")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def doc_rows():
    with open(DOC) as f:
        text = f.read()
    out = []
    for ln in text.splitlines():
        if re.match(r"^\|\s*SR-\d+", ln):
            out.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return text, out


if __name__ == "__main__":
    unittest.main()
