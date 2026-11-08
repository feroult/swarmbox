"""Slice 5.4: the Cloudflare connector that `up` keeps running (design 5.2, 3.7.2, 8.2, 12.3; D14, D28).

Runs the real helper against the shared FakePodman (the Base of tests/test_host_up.py). The tunnel token must reach Podman only
through its environment (`-e TUNNEL_TOKEN`), so the fake records TUNNEL_* variables and the tests read them with fp.envs().
Run: python3 tests/test_host_connector.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_host_up import Base, HELPER_SRC  # noqa: E402

CN = "swarmbox-cloudflared"
TOK = "eyJhIjoiYWNjdCIsInQiOiJ0dW4ifQ=="
OTHER = "eyJhIjoib3RoZXIifQ=="
PINNED = "docker.io/cloudflare/cloudflared:2026.10.7"


def cn_line(running, token=TOK, name=CN):
    return "%s|%s|PATH=/usr/bin\nTUNNEL_TOKEN=%s\nTUNNEL_METRICS=x\n" % (name, "true" if running else "false", token)


class ConnectorBase(Base):
    def setUp(self):
        super().setUp()
        self.podman()

    def with_connector(self, inspect=None):
        """The default script plus an answer for the connector's inspect (None: no such container)."""
        c = self.conf()
        ans = inspect if inspect is not None else {"exit": 125, "stderr": "Error: no such container %s\n" % CN}
        c["container"]["rules"].insert(0, {"match": ["inspect", CN], **ans})
        self.fp.configure(c)

    def cn_calls(self):
        return [c for c in self.calls() if CN in c]

    def run_calls(self):
        return [c for c in self.subs("run") if CN in c]

    def tok_env(self, **extra):
        return dict(SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=TOK, **extra)

    def assert_token_never_in_argv(self):
        for tok in (TOK, OTHER):
            for c in self.calls():
                self.assertFalse(any(tok in a for a in c), c)


class ConnectorTest(ConnectorBase):
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

    def test_the_connector_step_runs_after_the_box_is_ready(self):
        self.with_connector()
        self.up(**self.tok_env())
        first_box_run = next(i for i, c in enumerate(self.calls()) if c[:1] == ["run"] and CN not in c)
        self.assertLess(first_box_run, self.calls().index(self.run_calls()[0]))

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
        for running in (True, False):
            with self.subTest(running=running):
                self.podman()
                self.with_connector({"stdout": cn_line(running, token=OTHER)})
                r = self.up(**self.tok_env())
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.subs("rm"), [["rm", "-f", CN]])
                self.assertEqual(len(self.run_calls()), 1)
                self.assertLess(self.calls().index(["rm", "-f", CN]), self.calls().index(self.run_calls()[0]))
                self.assertEqual(self.subs("start"), [])
                self.assert_token_never_in_argv()

    def test_a_token_that_is_a_prefix_of_the_stored_one_is_a_different_token(self):
        self.with_connector({"stdout": cn_line(True, token=TOK + "xx")})
        self.up(**self.tok_env())
        self.assertEqual(len(self.run_calls()), 1)

    def test_image_override_by_env_and_not_by_config(self):
        self.with_connector()
        self.up(**self.tok_env(SWARMBOX_CLOUDFLARED_IMAGE="example.invalid/cf:1"))
        self.assertEqual(self.run_calls()[0][-4], "example.invalid/cf:1")
        # the config table (8.2) has no file key for it: a line in the file is an unknown key, never the image
        self.podman()
        self.with_connector()
        cfg = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config"), "w") as f:
            f.write("CLOUDFLARED_IMAGE=example.invalid/cf:2\n")
        r = self.up(**self.tok_env())
        self.assertEqual(self.run_calls()[0][-4], PINNED)
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
        base = self.up()
        self.assertEqual(base.returncode, 0)
        for name, ans in (("run fails", None), ("start fails", {"stdout": cn_line(False)}),
                          ("lookup fails", {"exit": 125, "stderr": "Error: something broke\n"})):
            with self.subTest(name):
                self.podman()
                self.with_connector(ans)
                c = self.conf()
                c["container"]["rules"].insert(0, {"match": ["inspect", CN], **(ans or {"exit": 125, "stderr": "Error: no such container\n"})})
                c["run"] = {"rules": [{"match": [CN], "exit": 126, "stderr": "Error: boom for connector\n"}]}
                c["start"] = {"exit": 125, "stderr": "Error: cannot start\n"}
                self.fp.configure(c)
                r = self.up(**self.tok_env())
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("connector", r.stderr)
                self.assertNotIn(TOK, r.stderr)

    def test_exact_name_match_does_not_confuse_swarmbox_cloudflared_with_swarmbox(self):
        # an inspect that resolves to the box (ID prefix or name quirk) is not the connector: it is created
        self.with_connector({"stdout": cn_line(True, name="swarmbox")})
        self.up(**self.tok_env())
        self.assertEqual(len(self.run_calls()), 1)
        # and the box's own lookup is not mistaken for the connector either (the box exists, the connector is created)
        for c in self.calls():
            self.assertFalse(any(a.startswith("name=") for a in c), c)
        with open(HELPER_SRC) as f:
            src = f.read()
        self.assertNotIn("grep -q swarmbox-cloudflared", src)

    def test_web_off_skips_the_connector(self):
        self.with_connector()
        r = self.up(**self.tok_env(SWARMBOX_WEB="0"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cn_calls(), [])

    def test_a_second_box_name_does_not_create_a_second_connector(self):
        self.with_connector({"stdout": cn_line(True)})
        r = self.up(**self.tok_env(SWARMBOX_NAME="other"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.run_calls(), [])
        for c in self.cn_calls():
            self.assertNotIn("swarmbox-cloudflared-other", " ".join(c))
        self.assertTrue(all(CN == c[-1] for c in self.cn_calls()))

    def test_the_token_of_the_config_file_is_used_only_with_mode_600(self):
        cfg = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(cfg)
        path = os.path.join(cfg, "config")
        with open(path, "w") as f:
            f.write("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOK)
        os.chmod(path, 0o644)
        self.with_connector()
        r = self.up()
        self.assertEqual(self.cn_calls(), [])
        self.assertIn("chmod 600", r.stderr)
        os.chmod(path, 0o600)
        self.podman()
        self.with_connector()
        r = self.up()
        self.assertEqual(len(self.run_calls()), 1)
        self.assert_token_never_in_argv()

    def test_a_running_box_still_brings_the_connector_up_on_every_entry(self):
        """Ported from v0.1.0's test_existing_web_container_brings_up_the_tunnel_even_without_the_flag (slice 6.2)."""
        running = {"stdout": self.matching_line()}
        self.podman(lookup=running)
        c = self.conf(lookup=running)
        c["container"]["rules"].insert(0, {"match": ["inspect", CN], "exit": 125, "stderr": "Error: no such container %s\n" % CN})
        self.fp.configure(c)
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.subs("run") if CN not in c], [], "the box itself was running: no box run")
        self.assertEqual(len(self.run_calls()), 1, self.calls())
        self.assertEqual(self.fp.envs()[self.calls().index(self.run_calls()[0])].get("TUNNEL_TOKEN"), TOK)
        self.assert_token_never_in_argv()

    def test_a_stopped_box_is_started_and_the_connector_is_still_ensured(self):
        self.with_connector({"stdout": cn_line(False)})
        r = self.up(**self.tok_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("start"), [["start", CN]])

    def test_no_cloudflare_api_token_is_needed_or_used(self):
        """Ported from v0.1.0's test_no_api_token_is_needed_or_used: only the tunnel token matters to up."""
        self.with_connector()
        r = self.up(**self.tok_env(CLOUDFLARE_API_TOKEN=""))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", r.stdout + r.stderr)
        self.assertEqual(len(self.run_calls()), 1)

    def test_the_tunnel_token_never_reaches_the_box_container(self):
        """Ported from v0.1.0's test_the_token_is_not_passed_to_the_swarmbox_container: the box run has no TUNNEL and no token."""
        self.with_connector()
        self.up(**self.tok_env())
        box = [c for c in self.subs("run") if CN not in c]
        self.assertEqual(len(box), 1, self.calls())
        self.assertFalse(any("TUNNEL" in a or TOK in a for a in box[0]), box[0])
        self.assertNotIn("TUNNEL_TOKEN", self.fp.envs()[self.calls().index(box[0])])

    def test_reset_and_stop_do_not_touch_the_connector(self):
        self.with_connector({"stdout": cn_line(True)})
        self.run_h("stop", env=self.env(**self.tok_env()))
        self.run_h("reset", env=self.env(**self.tok_env()))
        self.assertEqual(self.cn_calls(), [])


if __name__ == "__main__":
    unittest.main()
