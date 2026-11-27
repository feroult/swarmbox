"""The Cloudflare connector that `up` keeps running.

Runs the real helper against the shared FakePodman (the Base of tests/fast/test_host_up.py). The tunnel token must reach Podman only
through its environment (`-e TUNNEL_TOKEN`), so the fake records TUNNEL_* variables and the tests read them with fp.envs().
Run: python3 tests/fast/test_host_connector.py
"""
import concurrent.futures
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, DEFAULT_CONNECTOR, FakePodman  # noqa: E402
from host_support import DEFAULTS_SRC, HELPER_SRC, IMAGE, NAME, UpBase as Base, VERSION_SRC, env_hash, fingerprint, line  # noqa: E402

_EMPTY_ENV_HASH = env_hash([])
CN = DEFAULT_CONNECTOR
TOK = "eyJhIjoiYWNjdCIsInQiOiJ0dW4ifQ=="
OTHER = "eyJhIjoib3RoZXIifQ=="
PINNED = "docker.io/cloudflare/cloudflared:2026.10.7"


def cn_line(running, token=TOK, name=CN):
    return "%s|%s|PATH=/usr/bin\nTUNNEL_TOKEN=%s\nTUNNEL_METRICS=x\n" % (name, "true" if running else "false", token)


class ConnectorBase(Base):
    @classmethod
    def setUpClass(cls):
        cls._shared_dir = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cn-sh."))
        cls.addClassCleanup(shutil.rmtree, cls._shared_dir, True)
        hdir = os.path.join(cls._shared_dir, "helper")
        os.makedirs(hdir)
        shutil.copy(HELPER_SRC, os.path.join(hdir, "swarmbox-host"))
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        shutil.copy(VERSION_SRC, os.path.join(hdir, "VERSION"))
        shutil.copy(DEFAULTS_SRC, os.path.join(hdir, "DEFAULTS"))
        with open(os.path.join(hdir, "addon-ports"), "w") as f:
            f.write("")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            with open(os.path.join(cls._shared_dir, n), "w") as f:
                f.write(c)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-up."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.ws = os.path.join(self.tmp, "ws")
        os.mkdir(self.ws)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.hdir = os.path.join(self._shared_dir, "helper")
        self.helper = os.path.join(self.hdir, "swarmbox-host")
        self.fp = None
        self.podman()

    def env(self, **extra):
        e = super().env(
            SWARMBOX_LOCALTIME_FILE=os.path.join(self._shared_dir, "localtime"),
            SWARMBOX_TEST_PROC_VERSION=os.path.join(self._shared_dir, "proc-version"),
            SWARMBOX_TEST_TUN=os.path.join(self._shared_dir, "tun"),
            SWARMBOX_TEST_NAP="0.001",
        )
        e.update(extra)
        return e

    def matching_line(self, env_extra=None, **kw):
        if env_extra:
            return super().matching_line(env_extra, **kw)
        fp_lines = [
            "AGENT=", "BROWSER_URL=", "ENV_KEYS=", "HOSTNAME=" + NAME, "HOST_ACCESS=0",
            "IMAGE=" + IMAGE, "INIT=0", "NAME=" + NAME, "PORTS=",
            "TZ=local", "WEB=1", "WEB_PORT=7681", "WITH=", "WORKSPACE=" + self.ws, "YOLO=1",
        ]
        d = dict(ports="", env_hash=_EMPTY_ENV_HASH, fp=fingerprint(fp_lines, _EMPTY_ENV_HASH), ws=self.ws, image=IMAGE)
        d.update(kw)
        return line(**d)

    def _make_fp(self, conf):
        fp = FakePodman(conf)
        fp.__enter__()
        self.addCleanup(fp.__exit__)
        return fp

    def _env_for_fp(self, fp, home=None, **extra):
        e = self.env(**(dict(HOME=home, **extra) if home else extra))
        e["PATH"] = fp.env()["PATH"]
        return e

    def with_connector(self, inspect=None):
        """The default script plus an answer for the connector's inspect (None: no such container)."""
        c = self.conf()
        ans = inspect if inspect is not None else {"exit": 125, "stderr": "Error: no such container %s\n" % CN}
        c["container"]["rules"].insert(0, {"match": ["inspect", CN], **ans})
        self.fp.configure(c)

    def cn_calls(self, fp=None):
        return [c for c in (fp or self.fp).calls() if CN in c]

    def run_calls(self, fp=None):
        return [c for c in (fp or self.fp).calls() if c and c[0] == "run" and CN in c]

    def tok_env(self, **extra):
        return dict(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TOK, **extra)

    def assert_token_never_in_argv(self, fp=None):
        for tok in (TOK, OTHER):
            for c in (fp or self.fp).calls():
                self.assertFalse(any(tok in a for a in c), c)


class ConnectorTest(ConnectorBase):
    # (that the token never reaches the box container, argv or the output, from the file or the environment: test_security_review.py)

    def test_no_token_means_no_connector_calls(self):
        self.with_connector()
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cn_calls(), [])
        self.assertEqual(r.stderr, "")

    def test_token_and_web_on_creates_the_connector_with_expected_flags_and_the_token_only_in_env(self):
        self.with_connector()
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.run_calls()
        self.assertEqual(len(runs), 1, self.calls())
        self.assertEqual(runs[0], ["run", "-d", "--name", CN, "--restart=always", "--network=host", "--user", "root",
                                   "-e", "TUNNEL_TOKEN", PINNED, "tunnel", "--no-autoupdate", "run"])
        i = self.calls().index(runs[0])
        self.assertEqual(self.fp.envs()[i].get("TUNNEL_TOKEN"), TOK)
        self.assert_token_never_in_argv()
        self.assertNotIn(TOK, r.stdout + r.stderr)
        self.assertEqual(self.subs("rm"), [])

    def test_running_with_same_token_is_a_noop_beyond_inspect(self):
        self.with_connector({"stdout": cn_line(True)})
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.cn_calls()), 1, self.calls())
        self.assertEqual(self.cn_calls()[0][:2], ["container", "inspect"])
        self.assertEqual(self.run_calls(), [])
        self.assertEqual(self.subs("start"), [])
        self.assertEqual(self.subs("rm"), [])
        self.assert_token_never_in_argv()

    def test_stopped_with_same_token_is_started_not_recreated(self):
        self.with_connector({"stdout": cn_line(False)})
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("start"), [["start", CN]])
        self.assertEqual(self.run_calls(), [])
        self.assertEqual(self.subs("rm"), [])

    def test_different_token_recreates(self):
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            for running in (True, False):
                with self.subTest(running=running):
                    open(self.fp.log_path, "w").close()
                    self.with_connector({"stdout": cn_line(running, token=OTHER)})
                    r = self.up(**self.tok_env())
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(self.subs("rm"), [["rm", "-f", CN]])
                    self.assertEqual(len(self.run_calls()), 1)
                    self.assertLess(self.calls().index(["rm", "-f", CN]), self.calls().index(self.run_calls()[0]))
                    self.assertEqual(self.subs("start"), [])
                    self.assert_token_never_in_argv()
            return
        items = []
        for i, running in enumerate((True, False)):
            c = self.conf()
            c["container"]["rules"].insert(0, {"match": ["inspect", CN], "stdout": cn_line(running, token=OTHER)})
            h = os.path.join(self.tmp, "h-rec-%d" % i)
            os.mkdir(h)
            items.append((running, self._make_fp(c), h))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda it: (it[0], it[1], self.run_h("up", env=self._env_for_fp(it[1], home=it[2], **self.tok_env()))), items))
        for running, fp, r in results:
            with self.subTest(running=running):
                self.assertEqual(r.returncode, 0, r.stderr)
                calls = fp.calls()
                self.assertEqual([c for c in calls if c and c[0] == "rm"], [["rm", "-f", CN]])
                runs = self.run_calls(fp)
                self.assertEqual(len(runs), 1)
                self.assertLess(calls.index(["rm", "-f", CN]), calls.index(runs[0]))
                self.assertEqual([c for c in calls if c and c[0] == "start"], [])
                self.assert_token_never_in_argv(fp)

    def test_image_override_by_env_and_not_by_config(self):
        cfg = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config"), "w") as f:
            f.write("CLOUDFLARED_IMAGE=example.invalid/cf:2\n")
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            h_clean = os.path.join(self.tmp, "h-clean")
            os.mkdir(h_clean)
            self.with_connector()
            self.up(HOME=h_clean, **self.tok_env(SWARMBOX_CLOUDFLARED_IMAGE="example.invalid/cf:1"))
            self.assertEqual(self.run_calls()[0][-4], "example.invalid/cf:1")
            open(self.fp.log_path, "w").close()
            r = self.up(**self.tok_env())
            self.assertEqual(self.run_calls()[0][-4], PINNED)
            self.assertIn("CLOUDFLARED_IMAGE", r.stderr)
            return
        c = self.conf()
        c["container"]["rules"].insert(0, {"match": ["inspect", CN], "exit": 125, "stderr": "Error: no such container %s\n" % CN})
        fp1, fp2 = self._make_fp(c), self._make_fp(c)
        h_clean = os.path.join(self.tmp, "h-clean")
        os.mkdir(h_clean)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self.run_h, "up", env=self._env_for_fp(fp1, home=h_clean, **self.tok_env(SWARMBOX_CLOUDFLARED_IMAGE="example.invalid/cf:1")))
            f2 = pool.submit(self.run_h, "up", env=self._env_for_fp(fp2, **self.tok_env()))
            f1.result()
            r = f2.result()
        self.assertEqual(self.run_calls(fp1)[0][-4], "example.invalid/cf:1")
        self.assertEqual(self.run_calls(fp2)[0][-4], PINNED)
        self.assertIn("CLOUDFLARED_IMAGE", r.stderr)

    def test_default_image_equals_the_script_constant(self):
        with open(os.path.join(ROOT, "cloudflare-setup.py")) as f:
            script = re.search(r'^DEFAULT_CONNECTOR_IMAGE = "([^"]+)"', f.read(), re.M).group(1)
        with open(HELPER_SRC) as f:
            helper = re.search(r"^CONNECTOR_IMAGE_DEFAULT=(\S+)", f.read(), re.M).group(1)
        self.assertEqual(helper, script)
        self.assertEqual(helper, PINNED)
        self.assertNotIn(":latest", helper)

    def test_connector_failure_warns_and_the_up_exit_code_is_unchanged(self):
        cases = (("run fails", None), ("start fails", {"stdout": cn_line(False)}),
                 ("lookup fails", {"exit": 125, "stderr": "Error: something broke\n"}))
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            base = self.up()
            self.assertEqual(base.returncode, 0)
            for name, ans in cases:
                with self.subTest(name):
                    open(self.fp.log_path, "w").close()
                    c = self.conf()
                    c["container"]["rules"].insert(0, {"match": ["inspect", CN], **(ans or {"exit": 125, "stderr": "Error: no such container\n"})})
                    c["run"] = {"rules": [{"match": [CN], "exit": 126, "stderr": "Error: boom for connector\n"}]}
                    c["start"] = {"exit": 125, "stderr": "Error: cannot start\n"}
                    self.fp.configure(c)
                    r = self.up(**self.tok_env())
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("connector", r.stderr)
                    self.assertNotIn(TOK, r.stderr)
            return
        jobs = [(None, self.fp, self.home, {})]
        for i, (name, ans) in enumerate(cases):
            c = self.conf()
            c["container"]["rules"].insert(0, {"match": ["inspect", CN], **(ans or {"exit": 125, "stderr": "Error: no such container\n"})})
            c["run"] = {"rules": [{"match": [CN], "exit": 126, "stderr": "Error: boom for connector\n"}]}
            c["start"] = {"exit": 125, "stderr": "Error: cannot start\n"}
            h = os.path.join(self.tmp, "h-fail-%d" % i)
            os.mkdir(h)
            jobs.append((name, self._make_fp(c), h, self.tok_env()))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda j: (j[0], self.run_h("up", env=self._env_for_fp(j[1], home=j[2], **j[3]))), jobs))
        self.assertEqual(results[0][1].returncode, 0)
        for name, r in results[1:]:
            with self.subTest(name):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("connector", r.stderr)
                self.assertNotIn(TOK, r.stderr)

    def test_a_running_box_still_brings_the_connector_up_on_every_entry(self):
        """Ported from v0.1.0's test_existing_web_container_brings_up_the_tunnel_even_without_the_flag."""
        running = {"stdout": self.matching_line()}
        c = self.conf(lookup=running)
        c["container"]["rules"].insert(0, {"match": ["inspect", CN], "exit": 125, "stderr": "Error: no such container %s\n" % CN})
        self.fp.configure(c)
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.subs("run") if CN not in c], [], "the box itself was running: no box run")
        self.assertEqual(len(self.run_calls()), 1, self.calls())
        self.assertEqual(self.fp.envs()[self.calls().index(self.run_calls()[0])].get("TUNNEL_TOKEN"), TOK)
        self.assert_token_never_in_argv()

    def test_reset_also_ensures_the_connector_is_running(self):
        self.with_connector({"stdout": cn_line(False)})
        r = self.run_h("reset", env=self.env(**self.tok_env()))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("start"), [["start", CN]], self.calls())
        self.assert_token_never_in_argv()


if __name__ == "__main__":
    unittest.main()
