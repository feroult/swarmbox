#!/usr/bin/env python3
"""Tests for how `start.sh --web` brings up the Cloudflare connector (container swarmbox-cloudflared).

Run:  python3 tests/test_start_web_connector.py

start.sh runs against a fake `podman` that records its calls and its TUNNEL_TOKEN environment, and
reports the connector state given in STUB_CONNECTOR (empty = the container does not exist) with the
token STUB_CONNECTOR_TOKEN. Nothing real is started. What matters: SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN is
the source of truth (create / start / recreate), the token never reaches a command line, an output or
the SwarmBox container, and no API token is needed anywhere.
"""
import os
import socket
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
START = os.path.join(HERE, "..", "start.sh")
TOKEN = "eyJ-tunnel-token-for-tests"
OTHER = "eyJ-a-different-token"
STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$1" in
  images) echo img1 ;;
  ps) [ -n "$STUB_EXISTS" ] && echo cid1 ;;
  run)
    case "$*" in
      *--name\\ swarmbox-cloudflared*)
        [ -n "$STUB_RUN_FAILS" ] && { printf 'Trying to pull x...\\nCopying blob a\\nError: pull failed\\n' >&2; exit 125; }
        echo "TUNNEL_TOKEN=$TUNNEL_TOKEN" >> "$STUB_LOG.env" ;;
    esac
    echo cid ;;
  inspect)
    case "$*" in
      *swarmbox-cloudflared*)
        [ -n "$STUB_CONNECTOR" ] || exit 1
        case "$*" in
          *Config.Env*) [ -n "$STUB_CONNECTOR_TOKEN" ] && echo "TUNNEL_TOKEN=$STUB_CONNECTOR_TOKEN" ;;
          *) echo "$STUB_CONNECTOR" ;;
        esac ;;
      *Config.Env*) printf '%s\\n' "$STUB_CT_ENV" | tr ',' '\\n' ;;
      *PortBindings*) echo "$STUB_CT_PORT" ;;
      *) exit 1 ;;
    esac ;;
  start) [ -n "$STUB_START_FAILS" ] && exit 1 ;;
esac
exit 0
"""


class StartWeb(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.log = os.path.join(self.work, "calls.log")
        stub = os.path.join(self.bin, "podman")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        # a socket file where start.sh looks for the nested podman API (relative bind: short path)
        os.makedirs(os.path.join(self.work, ".work", ".swarmbox"))
        sock = socket.socket(socket.AF_UNIX)
        cwd = os.getcwd()
        os.chdir(os.path.join(self.work, ".work", ".swarmbox"))
        try:
            sock.bind("podman.sock")
        finally:
            os.chdir(cwd)
        self.addCleanup(sock.close)
        # something listening where the web terminal "is", so start.sh sees it as up
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.addCleanup(self.listener.close)
        self.port = self.listener.getsockname()[1]

    def start(self, *args, connector="", connector_token="", token="", start_fails=False, run_fails=False,
              extra_env=None, expect_ok=True, existing=False, ct_env="", ct_port=""):
        env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.work,
               "STUB_LOG": self.log, "STUB_CONNECTOR": connector, "STUB_CONNECTOR_TOKEN": connector_token,
               "STUB_CT_ENV": ct_env, "STUB_CT_PORT": ct_port}
        if existing:
            env["STUB_EXISTS"] = "1"
        if token:
            env["SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN"] = token
        if start_fails:
            env["STUB_START_FAILS"] = "1"
        if run_fails:
            env["STUB_RUN_FAILS"] = "1"
        env.update(extra_env or {})
        r = subprocess.run(["bash", START, "--no-shell"] + list(args), cwd=self.work, env=env,
                           capture_output=True, text=True, timeout=60)
        if expect_ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout + r.stderr
        return out, self.read(self.log), self.read(self.log + ".env"), r.returncode

    @staticmethod
    def read(path):
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.read().splitlines()

    def web(self):
        return ["--web", str(self.port)]

    @staticmethod
    def connector_runs(calls):
        return [c for c in calls if c.startswith("run ") and "--name swarmbox-cloudflared" in c]

    # ---- with the tunnel token: it is the source of truth -------------------------------------------
    def test_missing_connector_is_created_from_the_token(self):
        out, calls, envs, _ = self.start(*self.web(), token=TOKEN)
        runs = self.connector_runs(calls)
        self.assertEqual(len(runs), 1)
        for flag in ("-d", "--restart=always", "--network=host", "--user root", "-e TUNNEL_TOKEN",
                     "docker.io/cloudflare/cloudflared:latest", "tunnel --no-autoupdate run"):
            self.assertIn(flag, runs[0])
        self.assertEqual(envs, ["TUNNEL_TOKEN=" + TOKEN])  # reached podman through the environment
        self.assertIn("created and started", out)

    def test_the_token_never_appears_on_a_command_line_or_in_the_output(self):
        out, calls, _, _ = self.start(*self.web(), token=TOKEN)
        self.assertFalse([c for c in calls if TOKEN in c], "token leaked into a podman command line")
        self.assertNotIn(TOKEN, out)

    def test_a_stopped_connector_with_the_same_token_is_started_not_recreated(self):
        out, calls, envs, _ = self.start(*self.web(), token=TOKEN, connector="exited", connector_token=TOKEN)
        self.assertIn("start swarmbox-cloudflared", calls)
        self.assertEqual(self.connector_runs(calls), [])
        self.assertEqual(envs, [])
        self.assertIn("started", out)

    def test_a_running_connector_with_the_same_token_is_left_alone(self):
        out, calls, _, _ = self.start(*self.web(), token=TOKEN, connector="running", connector_token=TOKEN)
        self.assertIn("running", out)
        self.assertNotIn("start swarmbox-cloudflared", calls)
        self.assertEqual(self.connector_runs(calls), [])

    def test_a_connector_holding_another_token_is_recreated_even_if_running(self):
        for state in ("running", "exited"):
            if os.path.exists(self.log):
                os.remove(self.log)
            if os.path.exists(self.log + ".env"):
                os.remove(self.log + ".env")
            out, calls, envs, _ = self.start(*self.web(), token=TOKEN, connector=state, connector_token=OTHER)
            self.assertIn("rm -f swarmbox-cloudflared", calls, state)
            self.assertEqual(len(self.connector_runs(calls)), 1, state)
            self.assertEqual(envs, ["TUNNEL_TOKEN=" + TOKEN], state)
            self.assertIn("different token", out)
            self.assertNotIn(OTHER, out + "".join(calls))

    def test_a_failed_create_is_reported_briefly(self):
        out, _, _, _ = self.start(*self.web(), token=TOKEN, run_fails=True)
        self.assertIn("Could not create the Cloudflare connector", out)
        self.assertIn("pull failed", out)
        self.assertNotIn(TOKEN, out)

    def test_the_connector_image_can_be_chosen(self):
        _, calls, _, _ = self.start(*self.web(), token=TOKEN, extra_env={"SWARMBOX_CLOUDFLARED_IMAGE": "example.org/cf:1"})
        self.assertIn("example.org/cf:1", self.connector_runs(calls)[0])

    # ---- without the token: only an existing connector is started ------------------------------------
    def test_without_a_token_a_stopped_connector_is_started(self):
        for state in ("exited", "created", "stopped"):
            if os.path.exists(self.log):
                os.remove(self.log)
            out, calls, _, _ = self.start(*self.web(), connector=state)
            self.assertIn("start swarmbox-cloudflared", calls, state)
            self.assertIn("Cloudflare connector: started", out)

    def test_without_a_token_a_running_connector_is_left_alone(self):
        out, calls, _, _ = self.start(*self.web(), connector="running")
        self.assertIn("Cloudflare connector: running", out)
        self.assertNotIn("start swarmbox-cloudflared", calls)

    def test_a_connector_that_will_not_start_is_reported(self):
        out, _, _, _ = self.start(*self.web(), connector="exited", start_fails=True)
        self.assertIn("Could not start the Cloudflare connector", out)

    def test_without_token_or_connector_nothing_is_created_and_it_stays_quiet(self):
        out, calls, _, _ = self.start(*self.web())
        self.assertEqual(self.connector_runs(calls), [])
        self.assertNotIn("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", out)
        self.assertNotIn("cloudflare-setup", out)

    def test_people_using_remote_access_are_told_how_to_get_a_connector(self):
        out, calls, _, _ = self.start(*self.web(), extra_env={"SWARMBOX_WEB_HOSTNAME": "tty.example.com"})
        self.assertIn("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", out)
        self.assertIn("cloudflare-setup.py", out)
        self.assertEqual(self.connector_runs(calls), [])

    # ---- a container that already exists (the everyday case after the first --reset) ----------------
    def existing(self, *args, **kw):
        kw.setdefault("ct_env", "SWARMBOX_WEB=1,PATH=/usr/bin")
        kw.setdefault("ct_port", str(self.port))
        return self.start(*args, existing=True, **kw)

    def test_existing_web_container_accepts_web_and_brings_up_the_tunnel(self):
        out, calls, envs, _ = self.existing(*self.web(), token=TOKEN)
        self.assertNotIn("would be ignored", out)
        self.assertIn("start swarmbox", calls)
        self.assertEqual(len(self.connector_runs(calls)), 1)
        self.assertEqual(envs, ["TUNNEL_TOKEN=" + TOKEN])
        self.assertIn("Web terminal:", out)

    def test_existing_web_container_brings_up_the_tunnel_even_without_the_flag(self):
        # reattaching with a plain ./start.sh after a reboot must not leave the terminal unreachable
        out, calls, envs, _ = self.existing(token=TOKEN)
        self.assertEqual(len(self.connector_runs(calls)), 1)
        self.assertEqual(envs, ["TUNNEL_TOKEN=" + TOKEN])
        self.assertIn("Web terminal:", out)

    def test_existing_web_container_starts_a_stopped_connector_without_a_token(self):
        _, calls, _, _ = self.existing(connector="exited")
        self.assertIn("start swarmbox-cloudflared", calls)

    def test_the_port_the_container_really_publishes_wins_over_the_flag(self):
        out, calls, _, _ = self.existing("--web", "1", token=TOKEN)
        self.assertIn("already publishes the web terminal on port %d" % self.port, out)
        self.assertIn("Web terminal: http://127.0.0.1:%d" % self.port, out)
        self.assertEqual(len(self.connector_runs(calls)), 1)

    def test_an_existing_container_without_the_web_terminal_still_refuses_web(self):
        out, calls, _, code = self.existing(*self.web(), ct_env="PATH=/usr/bin", ct_port="", token=TOKEN, expect_ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("would be ignored", out)
        self.assertIn("--web", out)
        self.assertEqual(self.connector_runs(calls), [])
        self.assertNotIn("start swarmbox", calls)

    def test_an_existing_container_without_the_web_terminal_never_touches_the_connector(self):
        out, calls, _, _ = self.existing(ct_env="PATH=/usr/bin", ct_port="", token=TOKEN, connector="exited")
        self.assertFalse([c for c in calls if "swarmbox-cloudflared" in c], calls)
        self.assertNotIn("Cloudflare connector", out)

    # ---- scope and safety ----------------------------------------------------------------------------
    def test_without_web_the_connector_is_not_even_looked_at(self):
        out, calls, envs, _ = self.start(token=TOKEN, connector="exited")
        self.assertFalse([c for c in calls if "swarmbox-cloudflared" in c], calls)
        self.assertEqual(envs, [])
        self.assertNotIn("Cloudflare connector", out)

    def test_the_token_is_not_passed_to_the_swarmbox_container(self):
        _, calls, _, _ = self.start(*self.web(), token=TOKEN)
        main = [c for c in calls if c.startswith("run ") and "--name swarmbox " in c]
        self.assertEqual(len(main), 1)
        self.assertNotIn("TUNNEL", main[0])
        self.assertNotIn(TOKEN, main[0])

    def test_listing_the_token_in_env_keys_is_refused(self):
        for keys in ("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", "FOO, SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN ,BAR"):
            out, calls, _, code = self.start(*self.web(), "--env-keys", keys, token=TOKEN, expect_ok=False)
            self.assertNotEqual(code, 0, keys)
            self.assertIn("must not be passed to the container", out)
            self.assertFalse([c for c in calls if c.startswith("run ")], "nothing may be created: " + keys)

    def test_no_api_token_is_needed_or_used(self):
        out, calls, _, _ = self.start(*self.web(), token=TOKEN, extra_env={"CLOUDFLARE_API_TOKEN": ""})
        self.assertNotIn("CLOUDFLARE_API_TOKEN", out)
        self.assertEqual(len(self.connector_runs(calls)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
