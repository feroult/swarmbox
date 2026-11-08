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
from helpers import ROOT  # noqa: E402

TOK = "tunnelTOKEN0123456789abcdefSECRETvalue=="
CN = "swarmbox-cloudflared"


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

    def test_up_passes_the_hostile_workspace_to_podman_as_one_argument(self):
        for name in ("with space", "it's", "$(touch MARK)", "`touch MARK`", "-leading-dash"):
            with self.subTest(name=name):
                ws = os.path.join(self.tmp, "up-" + name)
                os.makedirs(ws, exist_ok=True)
                shutil.rmtree(self.state, True)
                self.podman()
                r = self.up(SWARMBOX_WORKSPACE=ws)
                self.assertEqual(r.returncode, 0, r.stderr)
                runs = self.real_runs()
                self.assertEqual(len(runs), 1)
                self.assertIn(ws + ":/home/agent", runs[0])
                self.assert_no_marker()

    def test_a_relative_workspace_with_a_leading_dash_becomes_an_absolute_path(self):
        p = self.flags("-rf")
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.split("\n")[:-1]
        self.assertEqual(lines[lines.index("-v") + 1], os.path.join(self.tmp, "-rf") + ":/home/agent")

    def test_newlines_carriage_returns_and_colons_in_the_workspace_are_refused(self):
        for bad in ("/tmp/a\nb", "/tmp/a\rb", "/tmp/a:b", "/tmp/a\n--privileged"):
            with self.subTest(bad=bad):
                p = self.flags(bad)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertEqual(p.stdout, "")

    def test_the_hostile_name_from_the_config_file_is_just_as_literal(self):
        ws = os.path.join(self.tmp, "cfg-$(touch MARK) `touch MARK`")
        os.makedirs(ws)
        with open(os.path.join(self.cfg_dir(), "config"), "w") as f:
            f.write("WORKSPACE=%s\n" % ws)
        env = self.env()
        del env["SWARMBOX_WORKSPACE"]
        p = subprocess.run([self.helper, "create-flags"], env=env, capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(ws + ":/home/agent", p.stdout.split("\n"))
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

    def test_the_same_values_from_the_environment_are_refused_where_they_are_used(self):
        for key, val in (("SWARMBOX_HOSTNAME", "$(touch MARK)"), ("SWARMBOX_PORTS", "80;x"), ("SWARMBOX_IMAGE", "a;b"),
                         ("SWARMBOX_ENV_KEYS", "A;B"), ("SWARMBOX_TZ", "`x`")):
            with self.subTest(key=key):
                p = subprocess.run([self.helper, "create-flags"], env=self.env(**{key: val}), capture_output=True,
                                   text=True, input="", cwd=self.tmp)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertEqual(p.stdout, "")
                self.assert_no_marker()

    def test_the_value_of_a_listed_variable_never_reaches_a_shell_or_an_argv(self):
        value = "$(touch MARK) `touch MARK` 'q' \"d\" ; | &"
        self.podman()
        r = self.up(SWARMBOX_ENV_KEYS="MYVAR", MYVAR=value)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MYVAR", self.real_runs()[0])
        for c in self.calls():
            self.assertFalse(any(value in a for a in c), c)
        self.assert_no_marker()

    def test_an_env_key_that_names_a_host_side_secret_is_refused(self):
        for name in ("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", "SWARMBOX_CLOUDFLARE_X"):
            self.assertEqual(self.run_h("env", "add", name).returncode, 2)
            self.assertEqual(self.run_h("config", "set", "ENV_KEYS", name).returncode, 2)


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

    def test_init_refuses_a_dash_image_so_the_function_never_runs_podman_with_an_option(self):
        host = os.path.join(self.tmp, "hostdir")
        shutil.copytree(os.path.join(ROOT, "container", "host"), host)
        init = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
        env = self.env(SWARMBOX_TEST_HOST_DIR=host)
        for bad in ("-x", "--privileged"):
            for args in (["--image", bad], ["--image=" + bad]):
                r = subprocess.run(["sh", init, *args], env=env, capture_output=True, text=True, input="", cwd=self.tmp)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")

    def test_a_config_file_with_a_dash_image_never_reaches_podman(self):
        cfg = os.path.join(self.cfg_dir(), "config")
        with open(cfg, "w") as f:
            f.write("IMAGE=--privileged\n")
        os.chmod(cfg, 0o600)
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.real_runs(), [])
        for c in self.calls():
            self.assertNotIn("--privileged", c)

    def test_the_connector_image_override_cannot_be_an_option(self):
        self.podman()
        r = self.up(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TOK, SWARMBOX_WEB="1", SWARMBOX_CLOUDFLARED_IMAGE="--privileged")
        self.assertEqual(r.returncode, 0, r.stderr)
        for c in self.calls():
            self.assertNotIn("--privileged", c)
        self.assertEqual([c for c in self.subs("run") if CN in c], [])
        self.assertIn("SWARMBOX_CLOUDFLARED_IMAGE", r.stderr)

    def test_the_python_wrapper_refuses_a_connector_image_that_is_an_option(self):
        # the refusal must come from the image check (named in the message), not from the missing API token that follows it
        mod = load_cf("cfsetup_image")
        base = ["apply", "--domain", "example.com", "--email", "a@example.com", "--dry-run"]
        env = dict(os.environ)
        os.environ.pop("CLOUDFLARE_API_TOKEN", None)
        try:
            for bad in ("--privileged", "-x", "a b", "a;b", "$(x)"):
                with self.subTest(bad=bad):
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                        mod.main(base + ["--connector-image=" + bad])
                    self.assertNotEqual(cm.exception.code, 0)
                    self.assertIn("connector image", err.getvalue())
            os.environ["SWARMBOX_CLOUDFLARED_IMAGE"] = "--privileged"
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
                mod.main(base)
            self.assertIn("connector image", err.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(env)


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

    def test_the_seed_write_does_not_follow_a_planted_temp_symlink(self):
        cdir = self.cfg_dir()
        v = self.victim()

        def plant(pid):
            os.symlink(v, os.path.join(cdir, "config.tmp.%d" % pid))
        r = self.plant_run(["config", "seed", "--with", "claude"], plant)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_victim(v)

    def test_the_notices_rewrite_does_not_follow_a_planted_temp_symlink(self):
        os.makedirs(self.state)
        notices = os.path.join(self.state, "notices")
        with open(notices, "w") as f:
            f.write("swarmbox:WEB_PORT\nswarmbox:WITH\n")
        v = self.victim()

        def plant(pid):
            os.symlink(v, os.path.join(self.state, "notices.tmp.%d" % pid))
        r = self.plant_run(["config", "set", "WEB_PORT", "9000"], plant)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_victim(v)
        with open(notices) as f:
            self.assertEqual(f.read(), "swarmbox:WITH\n")

    def test_up_does_not_write_through_planted_err_flags_or_cid_symlinks(self):
        os.makedirs(self.state)
        victims = {n: self.victim("victim-" + n) for n in ("err", "flags", "cid")}

        def plant(pid):
            for n, v in victims.items():
                os.symlink(v, os.path.join(self.state, "%s.%d" % (n, pid)))
        self.podman()
        r = self.plant_run(["up"], plant)
        self.assertEqual(r.returncode, 0, r.stderr)
        for v in victims.values():
            self.assert_victim(v)
        self.assertEqual(len(self.real_runs()), 1)

    def test_a_failed_creation_does_not_write_the_error_text_through_a_planted_symlink(self):
        os.makedirs(self.state)
        v = self.victim()

        def plant(pid):
            os.symlink(v, os.path.join(self.state, "err.%d" % pid))
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 125, "stderr": "boom\n"}]})
        r = self.plant_run(["up"], plant)
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assert_victim(v)

    def test_a_symlink_planted_at_the_lock_path_is_replaced_and_its_target_left_alone(self):
        os.makedirs(self.state)
        target = os.path.join(self.tmp, "lock-target")
        os.mkdir(target)
        with open(os.path.join(target, "keep"), "w") as f:
            f.write("KEEP\n")
        lock = os.path.join(self.state, "up-swarmbox.lock")
        os.symlink(target, lock)
        self.podman()
        r = self.up(SWARMBOX_TEST_LOCK_PIDWAIT="3", SWARMBOX_TEST_NAP="0.02")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(target), ["keep"])
        self.assertFalse(os.path.lexists(lock))
        self.assertEqual(len(self.real_runs()), 1)

    def test_a_symlink_at_the_lock_to_a_folder_with_a_live_pid_is_waited_for_not_followed_into(self):
        os.makedirs(self.state)
        target = os.path.join(self.tmp, "lock-target")
        os.mkdir(target)
        with open(os.path.join(target, "pid"), "w") as f:
            f.write("%d\n" % os.getpid())
        os.symlink(target, os.path.join(self.state, "up-swarmbox.lock"))
        self.podman()
        r = self.up(SWARMBOX_TEST_LOCK_TRIES="3", SWARMBOX_TEST_NAP="0.02")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertEqual(sorted(os.listdir(target)), ["pid"])
        self.assertEqual(self.real_runs(), [])

    def test_the_state_and_config_folders_are_made_private(self):
        os.makedirs(self.state)
        os.chmod(self.state, 0o777)
        cdir = self.cfg_dir()
        os.chmod(cdir, 0o755)
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o700)
        r = self.run_h("config", "set", "WEB_PORT", "9000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(cdir).st_mode), 0o700)

    def test_a_python_config_written_through_a_planted_symlink_replaces_the_link(self):
        mod = load_cf("cfsetup_save")
        xdg = os.path.join(self.tmp, "xdgcfg")
        os.makedirs(os.path.join(xdg, "swarmbox"))
        v = self.victim()
        path = os.path.join(xdg, "swarmbox", "cloudflare.json")
        os.symlink(v, path)
        old = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = xdg
        old_mask = os.umask(0o000)
        try:
            mod.save_config("example.com", ["a@example.com"], "swarmbox", "4h", "box.example.com", "swarmbox")
        finally:
            os.umask(old_mask)
            if old is None:
                del os.environ["XDG_CONFIG_HOME"]
            else:
                os.environ["XDG_CONFIG_HOME"] = old
        self.assert_victim(v)
        self.assertFalse(os.path.islink(path))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class CleanupTest(Base):
    """Every way out of up, reset, stop and update leaves no temporary file and no lock (exact names)."""

    def leftovers(self):
        if not os.path.isdir(self.state):
            return []
        return [n for n in os.listdir(self.state)
                if re.match(r"^(flags|cid|err)\.\d+$", n) or n.endswith(".lock") or ".lock.stale." in n]

    def test_success_failure_and_reset_paths_leave_nothing(self):
        scenarios = {
            "create fails": (dict(run={"rules": [{"match": ["--cidfile"], "exit": 125, "stderr": "boom\n",
                                                  "cidfile": "abc123\n"}]}), "up", 7),
            "ready times out": (dict(exec={"exit": 1}), "up", 6),
            "reset": ({}, "reset", 0),
        }
        for name, (conf, cmd, rc) in scenarios.items():
            with self.subTest(name):
                shutil.rmtree(self.state, True)
                self.podman(**conf)
                r = self.run_h(cmd, env=self.env(SWARMBOX_TEST_READY_TRIES="2"))
                self.assertEqual(r.returncode, rc, r.stderr)
                self.assertEqual(self.leftovers(), [])

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
                self.assertTrue(os.path.isdir(os.path.join(self.state, "up-swarmbox.lock")))
                p.send_signal(sig)
                p.communicate(timeout=20)
                open(gate, "w").close()
                self.assertEqual(p.returncode, rc)
                self.assertEqual(self.leftovers(), [])
                self.assertEqual(self.real_runs(), [])

    def test_a_failed_stop_and_a_failed_update_leave_nothing(self):
        self.podman(stop={"exit": 1, "stderr": "no\n"},
                    container={"rules": [{"match": ["swarmbox.fingerprint"], "stdout": up_tests.line()}]})
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.leftovers(), [])
        self.podman(pull={"exit": 125, "stderr": "denied\n"})
        r = self.run_h("update", "--to", "9.9.9")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(self.leftovers(), [])


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

    def test_create_flags_and_fingerprint_do_not_carry_the_token(self):
        self.cfg_with_token()
        for sub in (["create-flags"], ["fingerprint"], ["fingerprint", "--explain", "--label", "swarmbox.image=x"]):
            p = subprocess.run([self.helper, *sub], env=self.env_clean(SWARMBOX_WEB="1"), capture_output=True, text=True,
                               input="", cwd=self.tmp)
            self.assertNotIn(TOK, p.stdout + p.stderr, sub)

    def test_config_list_shows_the_token_only_as_set_and_the_other_commands_never_print_it(self):
        self.cfg_with_token()
        p = self.run_h("config", "list", env=self.env_clean())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=set\tfile", p.stdout)
        self.assertNotIn(TOK, p.stdout + p.stderr)
        for sub in (["url"], ["version"], ["env", "list"]):
            q = self.run_h(*sub, env=self.env_clean())
            self.assertNotIn(TOK, q.stdout + q.stderr, sub)

    def test_the_token_is_never_accepted_on_the_command_line(self):
        r = self.run_h("config", "set", "CLOUDFLARE_TUNNEL_TOKEN", TOK)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn(TOK, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "swarmbox", "config")))
        r = self.run_h("config", "seed", "--token", TOK)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn(TOK, r.stdout + r.stderr)

    def test_the_token_is_not_read_from_a_pipe(self):
        r = subprocess.run([self.helper, "config", "set", "CLOUDFLARE_TUNNEL_TOKEN"], env=self.env(), input=TOK + "\n",
                           capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn(TOK, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "swarmbox", "config")))

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


class UpdateModeTest(upd.UpdateBase):
    def test_the_helper_folder_made_by_update_is_private_with_umask_000(self):
        self.podman_for("2.0.1")
        r = subprocess.run(["/bin/sh", "-c", 'umask 000; exec "$@"', "sh", self.helper, "update"], env=self.env(),
                           capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(self.host_dir).st_mode) & 0o077, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.cfg).st_mode), 0o600)


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

    def test_rollback_to_a_tag_whose_image_is_missing_changes_nothing(self):
        self.podman_for("2.0.1", pull={"exit": 125, "stderr": "Error: manifest unknown\n"})
        before = self.before()
        r = self.update("--to", "1.9.9")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assert_unchanged(before)
        self.assertEqual(self.names(), ["pull"])

    def test_a_dash_image_in_the_config_is_refused_before_any_podman_call(self):
        self.write_config("IMAGE=--privileged\n")
        self.podman_for("2.0.1")
        r = self.update("--to", "2.0.1")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_an_exact_tag_must_equal_the_version_inside_the_image(self):
        self.podman_for("2.0.5")
        before = self.before()
        r = self.update("--to", "2.0.9")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assert_unchanged(before)

    def test_a_version_line_with_shell_or_control_text_is_refused(self):
        for ver in ("2.0.1; touch MARK", "$(touch MARK)", "2.0", "x.y.z", "2.0.1\x1b[31m"):
            with self.subTest(ver=ver):
                self.podman_for(ver)
                before = self.before()
                r = self.update("--to", "2.0.1")
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assert_unchanged(before)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "MARK")))

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

    def test_an_archive_with_a_symlink_member_is_refused(self):
        p = os.path.join(self.tmp, "ln.tar")
        make_archive(p, version="2.0.1")
        with tarfile.open(p, "a") as tf:
            ti = tarfile.TarInfo("./evil-link")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
        self.podman(run={"stdout_file": p})
        before = self.before()
        r = self.update("--to", "2.0.1")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assert_unchanged(before)

    def test_planted_symlinks_at_the_old_and_current_helper_folder_names_are_not_followed(self):
        victim_dir = os.path.join(self.tmp, "victim-dir")
        os.mkdir(victim_dir)
        with open(os.path.join(victim_dir, "keep"), "w") as f:
            f.write("KEEP\n")
        os.symlink(victim_dir, self.host_dir + ".old")
        self.podman_for("2.0.1")
        r = self.update("--to", "2.0.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(victim_dir), ["keep"])
        self.assertFalse(os.path.lexists(self.host_dir + ".old"))
        shutil.rmtree(self.host_dir)
        os.symlink(victim_dir, self.host_dir)
        self.podman_for("2.0.2")
        r = self.update("--to", "2.0.2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(victim_dir), ["keep"])
        self.assertFalse(os.path.islink(self.host_dir))

    def test_a_failed_extraction_leaves_the_old_copy_and_no_temporary_folder(self):
        for run in ({"exit": 125, "stderr": "boom\n"}, {"stdout": "not a tar archive\n"}):
            with self.subTest(run=run):
                self.podman_for("2.0.1", run=run)
                before = self.before()
                r = self.update("--to", "2.0.1")
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assert_unchanged(before)
                left = [n for n in os.listdir(os.path.dirname(self.host_dir)) if n != "host"]
                self.assertEqual(left, [])


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

    def test_a_valid_file_with_a_path_key_still_uses_the_fake_podman(self):
        evil = os.path.join(self.tmp, "evilbin")
        os.mkdir(evil)
        with open(os.path.join(evil, "podman"), "w") as f:
            f.write("#!/bin/sh\ntouch %s/MARK\n" % self.tmp)
        os.chmod(os.path.join(evil, "podman"), 0o755)
        self.write("PATH=%s\n" % evil)
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.real_runs()), 1)
        self.assert_no_marker()

    def test_crlf_and_blank_and_comment_lines_do_not_leak_into_values(self):
        self.write("# c\r\n\r\nWEB_PORT=9000\r\nWITH=claude\r\n")
        r = self.run_h("config", "get", "WEB_PORT")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("\r", r.stdout)

    def test_a_very_long_line_and_binary_noise_do_not_crash_or_execute(self):
        self.write("WEB_PORT=" + "9" * 100000 + "\n\x01\x02=\x03\n" + "A" * 50000 + "\n")
        r = self.run_h("config", "list")
        self.assertIn(r.returncode, (0, 1, 2))
        self.assert_no_marker()

    def test_a_directory_where_the_config_file_should_be(self):
        os.makedirs(os.path.join(self.cfg_dir(), "config"))
        r = self.run_h("config", "list")
        self.assertIn(r.returncode, (0, 1))
        self.assertNotIn("Traceback", r.stderr)


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


class ReviewDocumentTest(unittest.TestCase):
    def test_the_document_exists_and_has_finding_rows(self):
        self.assertTrue(os.path.isfile(DOC))
        _t, rs = doc_rows()
        self.assertGreaterEqual(len(rs), 10)

    def test_every_row_has_id_severity_location_status_and_test_and_none_is_open(self):
        _t, rs = doc_rows()
        ids = set()
        for r in rs:
            self.assertEqual(len(r), 6, r)
            fid, sev, loc, what, status, test = r
            self.assertRegex(fid, r"^SR-\d+$")
            self.assertNotIn(fid, ids)
            ids.add(fid)
            self.assertIn(sev.lower(), ("high", "medium", "low", "info"), r)
            self.assertTrue(loc and what, r)
            self.assertIn(status.lower().split()[0], ("fixed", "documented"), "no row may stay open: %r" % r)
            self.assertTrue(test, r)

    def test_a_named_test_exists_for_every_row(self):
        _t, rs = doc_rows()
        for r in rs:
            names = re.findall(r"(test_[a-z0-9_]+\.py)::(?:(\w+)\.)?(test_\w+)", r[5])
            self.assertTrue(names, "row %s names no test as file::Class.test_name: %r" % (r[0], r[5]))
            for fname, cls, tname in names:
                path = os.path.join(TESTS_DIR, fname)
                self.assertTrue(os.path.isfile(path), (r[0], fname))
                with open(path) as f:
                    src = f.read()
                self.assertRegex(src, r"def %s\(" % tname, (r[0], tname))
                if cls:
                    self.assertRegex(src, r"class %s\b" % cls, (r[0], cls))

    def test_a_fixed_row_names_a_fix_in_the_code_and_a_documented_row_is_in_the_decision_log(self):
        _t, rs = doc_rows()
        with open(os.path.join(ROOT, "docs", "decision-log.md")) as f:
            log = f.read()
        self.assertIn("## [7.3]", log)
        for r in rs:
            if r[4].lower().startswith("documented"):
                self.assertIn(r[0], log, "documented finding %s is not explained in the decision log" % r[0])

    def test_the_document_records_the_shellcheck_result_and_the_scope(self):
        text, _rs = doc_rows()
        self.assertRegex(text, r"(?i)shellcheck")
        self.assertRegex(text, r"(?i)out of scope|not covered|scope")


if __name__ == "__main__":
    unittest.main()
