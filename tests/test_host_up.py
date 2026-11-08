"""Slice 3.3: `up`, `reset`, `stop` and `url` of the host helper (design 3.5, 3.6, 3.7.2, 3.8, 4.1, 4.2, 5.2).

The helper runs as a real program (copied with a fixture `tool-ports` into a mktemp folder) against the shared FakePodman,
which records every call and answers from a script (rules by arguments, answers in sequence). Nothing here starts a real
container (tests/smoke_image.py does, in its opt-in `up-lifecycle` step). HOME, XDG_STATE_HOME and the workspace are mktemp
folders. Tests-only switches of the helper used here (all start with SWARMBOX_TEST_): TUN (the file that stands for
/dev/net/tun), NAP (the pause of the wait loops, seconds), READY_TRIES, LOCK_TRIES, LOCK_PIDWAIT (the counts of those loops) and
CREATE_FLAGS (a program that stands for `swarmbox-host create-flags`, so a test can make it slow or make it fail).
The race tests wait on marker files, never on sleeps that decide the outcome.
Run: python3 tests/test_host_up.py
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
with open(VERSION_SRC) as _f:
    VERSION = _f.read().strip()
NAME = "swarmbox"
IMAGE = "ghcr.io/<org>/swarmbox:%s" % VERSION
BUSY = ("Error: rootlessport listen tcp 127.0.0.1:7681: bind: address already in use")
NOSUCH = {"exit": 125, "stderr": "Error: inspecting object: no such container swarmbox\n"}
HELPER_TOOLS = ["sh", "dash", "bash", "cat", "rm", "mkdir", "rmdir", "sleep", "kill", "sort", "tail", "head", "grep", "sed",
                "tr", "uname", "date", "find", "stat", "mv", "chmod", "printf", "cut", "readlink", "env", "id", "test",
                "sha256sum", "wc", "basename", "dirname", "mktemp", "touch", "ls", "true", "false", "expr", "awk"]


def line(state="running", name=NAME, image_id="sha256:aaa", init="false", managed="2", image=IMAGE, ports="",
         env_hash="", fp="", ws=""):
    """What `podman container inspect --format` prints for the box (the helper's format, in this order)."""
    return "|".join([state, name, image_id, init, managed, image, ports, env_hash, fp, ws]) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-up."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.ws = os.path.join(self.tmp, "ws")
        os.mkdir(self.ws)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.hdir = os.path.join(self.tmp, "helper")
        os.makedirs(self.hdir)
        shutil.copy(HELPER_SRC, os.path.join(self.hdir, "swarmbox-host"))
        os.chmod(os.path.join(self.hdir, "swarmbox-host"), 0o755)
        shutil.copy(VERSION_SRC, os.path.join(self.hdir, "VERSION"))
        with open(os.path.join(self.hdir, "tool-ports"), "w") as f:
            f.write("")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            with open(os.path.join(self.tmp, n), "w") as f:
                f.write(c)
        self.helper = os.path.join(self.hdir, "swarmbox-host")
        self.fp = None

    def podman(self, **over):
        """A FakePodman with a default script for a box that does not exist; `over` replaces entries."""
        conf = self.conf(**over)
        self.fp = FakePodman(conf)
        self.fp.__enter__()
        self.addCleanup(self.fp.__exit__)
        return self.fp

    def conf(self, lookup=None, state="running\n", mounts="", **over):
        lookup = NOSUCH if lookup is None else lookup
        c = {
            "container": {"rules": [
                {"match": ["inspect", ".Mounts"], "stdout": mounts},
                {"match": ["inspect", "swarmbox.fingerprint"], **lookup},
                {"match": ["inspect", "State.Status"], "stdout": state},
            ]},
            "image": {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": "sha256:aaa\n"}]},
            "version": {"stdout": "4.3.1\n"},
            "exec": {"stdout": "ok\n"},
        }
        c.update(over)
        return c

    def env(self, **extra):
        e = self.fp.env() if self.fp else dict(os.environ)
        for k in list(e):
            if k.startswith("SWARMBOX_"):
                del e[k]
        e.update({
            "HOME": self.home, "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_INIT": "0",
            "SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "localtime"),
            "SWARMBOX_TEST_PROC_VERSION": os.path.join(self.tmp, "proc-version"),
            "SWARMBOX_TEST_OS": "Linux", "SWARMBOX_TEST_TUN": os.path.join(self.tmp, "tun"),
            "SWARMBOX_TEST_NAP": "0.02", "SWARMBOX_TEST_READY_TRIES": "40",
            "SWARMBOX_TEST_LOCK_TRIES": "100", "SWARMBOX_TEST_LOCK_PIDWAIT": "10",
        })
        for k in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            e.pop(k, None)
        e.update(extra)
        return e

    def run_h(self, *args, env=None, timeout=60):
        return subprocess.run([self.helper, *args], env=env if env is not None else self.env(), capture_output=True,
                              text=True, input="", cwd=self.tmp, timeout=timeout)

    def up(self, **extra):
        return self.run_h("up", env=self.env(**extra))

    def calls(self):
        return self.fp.calls()

    def subs(self, name):
        """The recorded calls of one podman subcommand (the first word)."""
        return [c for c in self.calls() if c and c[0] == name]

    def lookups(self):
        return [c for c in self.calls() if c[:2] == ["container", "inspect"] and any("swarmbox.fingerprint" in a for a in c)]

    def creation_flags(self, env_extra=None):
        """The real create-flags output for the default configuration: labels in it make a box that matches the config."""
        p = subprocess.run([self.helper, "create-flags"], env=self.env(**(env_extra or {})), capture_output=True, text=True,
                           input="", cwd=self.tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split("\n")[:-1]

    def matching_line(self, env_extra=None, **kw):
        """A lookup line whose labels equal what the helper would create now (so no warning is due)."""
        flags = self.creation_flags(env_extra)
        labels = {}
        for i, a in enumerate(flags):
            if a == "--label":
                k, v = flags[i + 1].split("=", 1)
                labels[k] = v
        d = dict(ports=labels["swarmbox.ports"], env_hash=labels["swarmbox.env-hash"], fp=labels["swarmbox.fingerprint"],
                 ws=labels["swarmbox.workspace"], image=labels["swarmbox.image"])
        d.update(kw)
        return line(**d)

    def assert_no_run(self):
        self.assertEqual([c for c in self.subs("run") if "--rm" not in c], [])

    def real_runs(self):
        return [c for c in self.subs("run") if "--rm" not in c]


# ============================================================================ the fast path and the exact-name match

class FastPathTest(Base):
    def running(self, **kw):
        return {"stdout": self.matching_line(**kw)}

    def test_a_running_box_takes_one_inspect_and_no_run(self):
        self.podman(lookup=self.running())
        # the lookup needs the labels of the configuration: build them with the fake in place (create-flags calls no podman)
        self.fp.configure(self.conf(lookup=self.running()))
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        ins = [c for c in self.calls() if c[:2] == ["container", "inspect"]]
        self.assertEqual(len(ins), 1, self.calls())
        self.assertEqual(self.calls()[0][:2], ["container", "inspect"])
        self.assertIn("--format", ins[0])
        self.assertEqual(ins[0][-1], NAME)
        self.assert_no_run()
        for sub in ("start", "rm", "ps", "pull", "version"):
            self.assertEqual(self.subs(sub), [], sub)

    def test_the_fast_path_call_count_budget_of_b35(self):
        self.podman(lookup=self.running())
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLessEqual(len(self.calls()), 2, self.calls())

    def test_the_fast_path_does_not_need_the_version_or_the_tun_file(self):
        self.podman(lookup=self.running())
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "no-such-file"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_box_that_merely_shares_the_name_prefix_is_not_the_box(self):
        # `podman container inspect swarmbox` resolved to a container named swarmbox-cloudflared (or an ID prefix):
        # the printed name differs, so the box does not exist and is created
        self.podman(lookup={"stdout": line(name="swarmbox-cloudflared", managed="")})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.real_runs()), 1)
        self.assertEqual(self.real_runs()[0][:3], ["run", "-d", "--name"])
        self.assertEqual(self.real_runs()[0][3], NAME)
        self.assertEqual(self.subs("rm"), [])

    def test_a_name_that_is_an_id_prefix_resolves_to_another_container_and_is_still_a_miss(self):
        self.podman(lookup={"stdout": line(name="quirky_name", managed="2")})
        r = self.up(SWARMBOX_NAME="ab12")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.real_runs()[0][3], "ab12")

    def test_no_call_filters_by_name(self):
        self.podman()
        self.up()
        for c in self.calls():
            self.assertFalse(any(a.startswith("name=") for a in c), c)
        with open(HELPER_SRC) as f:
            src = f.read()
        self.assertNotIn("-f name=", src)
        self.assertNotIn("filter name=", src)
        self.assertNotIn("ps -a -q", src)


class WarningsTest(Base):
    def setUp(self):
        super().setUp()
        self.podman()

    def run_with(self, over_env=None, image_inspect=None, **kw):
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line(**kw)}))
        if image_inspect is not None:
            c = self.conf(lookup={"stdout": self.matching_line(**kw)})
            c["image"] = {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": image_inspect}]}
            self.fp.configure(c)
        return self.up(**(over_env or {}))

    def test_a_matching_box_prints_nothing(self):
        r = self.run_with()
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_ports_changed_line(self):
        r = self.run_with({"SWARMBOX_PORTS": "3000"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("`PORTS` changed: box has (none), config has 127.0.0.1:3000:3000; run `swarmbox reset` to apply", r.stderr)

    def test_the_image_label_differs_from_the_config(self):
        r = self.run_with({"SWARMBOX_IMAGE": "other/img:9"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("this box was created from %s; the config asks for other/img:9; run `swarmbox reset`" % IMAGE, r.stderr)

    def test_same_reference_but_the_local_image_was_replaced_is_stale(self):
        r = self.run_with(image_inspect="sha256:bbb\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("is newer than the one this box runs", r.stderr)
        self.assertIn(IMAGE, r.stderr)

    def test_same_image_id_is_not_stale_and_the_sha256_prefix_does_not_matter(self):
        r = self.run_with(image_inspect="aaa\n")
        self.assertEqual(r.stderr, "")

    def test_an_image_that_cannot_be_inspected_is_not_a_warning(self):
        c = self.conf(lookup={"stdout": self.matching_line()})
        c["image"] = {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "exit": 125, "stderr": "no such image\n"}]}
        self.fp.configure(c)
        r = self.up()
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_workspace_changed_in_the_config(self):
        other = os.path.join(self.tmp, "other-ws")
        os.mkdir(other)
        r = self.run_with({"SWARMBOX_WORKSPACE": other})
        self.assertEqual(r.returncode, 0)
        self.assertIn("the workspace in the config is %s, this box uses %s; run `swarmbox reset` to switch" % (other, self.ws), r.stderr)

    def test_a_variable_changed_on_the_host(self):
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line({"SWARMBOX_ENV_KEYS": "FOO", "FOO": "1"})}))
        r = self.up(SWARMBOX_ENV_KEYS="FOO", FOO="2")
        self.assertEqual(r.returncode, 0)
        self.assertIn("the variables changed on the host", r.stderr)

    def test_another_key_gives_the_generic_line(self):
        r = self.run_with({"SWARMBOX_HOSTNAME": "elsewhere"})
        self.assertEqual(r.returncode, 0)
        self.assertIn("another creation setting changed", r.stderr)

    def test_init_auto_takes_the_value_the_box_was_created_with(self):
        # created with --init (HostConfig.Init true) and a fingerprint made with INIT=1; the config says auto: no warning
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line({"SWARMBOX_INIT": "1"}, init="true")}))
        r = self.up(SWARMBOX_INIT="auto")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        # and the other way: created without it
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line({"SWARMBOX_INIT": "0"}, init="false")}))
        r = self.up(SWARMBOX_INIT="auto")
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_warnings_never_change_the_exit_code(self):
        r = self.run_with({"SWARMBOX_PORTS": "3000", "SWARMBOX_IMAGE": "x/y:1"}, image_inspect="sha256:bbb\n")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.real_runs(), [])
        self.assertEqual(self.subs("rm"), [])


# ============================================================================ prerequisites

class PrerequisiteTest(Base):
    def test_podman_missing_is_exit_3_with_the_advice(self):
        self.podman()
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS:
            p = shutil.which(t)
            if p and not os.path.exists(os.path.join(bindir, t)):
                os.symlink(p, os.path.join(bindir, t))
        self.assertIsNone(shutil.which("podman", path=bindir))
        r = self.run_h("up", env=self.env(PATH=bindir))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("swarmbox: Podman is not installed.", r.stderr)
        self.assertIn("sudo apt install podman", r.stderr)
        self.assertIn("brew install podman", r.stderr)

    def version_case(self, text, code):
        self.podman(version={"stdout": text})
        r = self.up()
        self.assertEqual(r.returncode, code, r.stderr)
        return r

    def test_podman_4_2_is_too_old(self):
        r = self.version_case("4.2.9\n", 3)
        self.assertIn("swarmbox: Podman 4.2 found, 4.3 or newer is required. Upgrade Podman and try again.", r.stderr)
        self.assert_no_run()

    def test_versions_are_compared_as_numbers(self):
        for v in ("4.3.1", "4.10.0", "5.0.1", "10.0.0", "4.3.0-dev"):
            self.version_case(v + "\n", 0)

    def test_podman_3_is_too_old_even_with_a_big_minor(self):
        self.version_case("3.14.0\n", 3)

    def test_an_unreadable_version_is_a_warning_not_a_failure(self):
        r = self.version_case("garbage\n", 0)
        self.assertIn("could not read the Podman version", r.stderr)

    def test_tun_missing_is_exit_3_with_the_modprobe_hint(self):
        self.podman()
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "absent"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("swarmbox: /dev/net/tun is missing on this host. Nested Podman needs it. On Linux try: sudo modprobe tun", r.stderr)
        self.assert_no_run()

    def test_tun_is_not_checked_on_macos(self):
        self.podman()
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "absent"), SWARMBOX_TEST_OS="Darwin")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_order_is_podman_then_version_then_tun_then_workspace(self):
        self.podman(version={"stdout": "4.0.0\n"})
        with open(os.path.join(self.tmp, "afile"), "w"):
            pass
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "absent"), SWARMBOX_WORKSPACE=os.path.join(self.tmp, "afile"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("4.3 or newer", r.stderr)
        self.podman(version={"stdout": "4.3.1\n"})
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "absent"), SWARMBOX_WORKSPACE=os.path.join(self.tmp, "afile"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("/dev/net/tun", r.stderr)
        r = self.up(SWARMBOX_WORKSPACE=os.path.join(self.tmp, "afile"))
        self.assertEqual(r.returncode, 4)

    def test_image_not_local_and_not_pullable_is_exit_3(self):
        self.podman(image={"rules": [{"match": ["exists"], "exit": 1}]},
                    pull={"exit": 125, "stderr": "Error: initializing source: no such host\n"})
        r = self.up()
        self.assertEqual(r.returncode, 3)
        self.assertIn("swarmbox: cannot pull %s: Error: initializing source: no such host" % IMAGE, r.stderr)
        self.assertIn("SWARMBOX_IMAGE", r.stderr)
        self.assert_no_run()

    def test_a_missing_image_is_pulled_then_used(self):
        self.podman(image={"rules": [{"match": ["exists"], "exit": 1}]})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.subs("pull") if IMAGE in c][0][-1], IMAGE)
        self.assertEqual(len(self.real_runs()), 1)

    def test_a_present_image_is_not_pulled(self):
        self.podman()
        self.up()
        self.assertEqual(self.subs("pull"), [])


# ============================================================================ creation

class CreateTest(Base):
    def test_a_missing_box_is_created_with_the_captured_flags(self):
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.real_runs()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        flags = self.creation_flags()
        self.assertEqual(run[:5], ["run", "-d", "--name", NAME, "--cidfile"])
        self.assertTrue(run[5].startswith(self.state + os.sep), run[5])
        self.assertEqual(run[6:-2], flags)
        self.assertEqual(run[-2:], [IMAGE, "serve"])
        self.assertEqual(run[0], "run")

    def test_the_mount_point_of_the_nested_storage_is_made_by_the_helper_as_the_user(self):
        # if Podman made .local/share/containers it would make .local and .local/share too, owned by the container's root
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        for d in (".local", ".local/share", ".local/share/containers"):
            st = os.stat(os.path.join(self.ws, d))
            self.assertEqual(st.st_uid, os.getuid(), d)
            self.assertEqual(stat.S_IMODE(st.st_mode) & 0o700, 0o700, d)
        self.assertEqual(os.listdir(os.path.join(self.ws, ".local", "share", "containers")), [])

    def test_an_existing_local_share_is_left_as_it_is(self):
        os.makedirs(os.path.join(self.ws, ".local", "share"))
        os.chmod(os.path.join(self.ws, ".local", "share"), 0o700)
        self.podman()
        self.up()
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.ws, ".local", "share")).st_mode), 0o700)

    def test_a_mount_point_that_cannot_be_made_is_exit_4_and_no_run(self):
        os.makedirs(os.path.join(self.ws, ".local"))
        with open(os.path.join(self.ws, ".local", "share"), "w"):
            pass   # a file where the folder must go
        self.podman()
        r = self.up()
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn(".local/share/containers", r.stderr)
        self.assert_no_run()

    def test_nothing_is_left_in_the_state_folder_after_success(self):
        self.podman()
        self.up()
        self.assertEqual(sorted(os.listdir(self.state)), [])

    def test_the_cidfile_path_is_fresh_for_every_call(self):
        self.podman()
        self.up()
        self.up()
        paths = [c[5] for c in self.real_runs()]
        self.assertEqual(len(paths), 2)
        self.assertFalse(os.path.exists(paths[0]))

    def test_flags_with_spaces_and_dollars_stay_one_argument_each(self):
        weird = os.path.join(self.tmp, "my work $HOME `x` 'q'")
        os.mkdir(weird)
        self.podman()
        r = self.up(SWARMBOX_WORKSPACE=weird)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(weird + ":/home/agent", self.real_runs()[0])

    def test_init_auto_is_resolved_by_a_throwaway_probe_that_supports_it(self):
        self.podman(run={"rules": [{"match": ["--rm", "--init"], "exit": 0}]})
        r = self.up(SWARMBOX_INIT="auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        probe = [c for c in self.subs("run") if "--rm" in c]
        self.assertEqual(len(probe), 1)
        self.assertIn("--init", probe[0])
        self.assertIn(IMAGE, probe[0])
        self.assertTrue(any(a.startswith(NAME + "-init-probe-") for a in probe[0]), probe[0])
        self.assertIn("--init", self.real_runs()[0])
        self.assertIn("swarmbox.managed=2", self.real_runs()[0])

    def test_init_auto_without_init_support_runs_without_it_and_says_so(self):
        self.podman(run={"rules": [{"match": ["--rm", "--init"], "exit": 126, "stderr": "no catatonit\n"}]})
        r = self.up(SWARMBOX_INIT="auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("--init", self.real_runs()[0])
        self.assertIn("cannot run --init", r.stderr)

    def test_init_0_and_1_need_no_probe(self):
        for v in ("0", "1"):
            self.podman()
            self.up(SWARMBOX_INIT=v)
            self.assertEqual([c for c in self.subs("run") if "--rm" in c], [], v)
            self.assertEqual("--init" in self.real_runs()[0], v == "1")

    def test_create_flags_exit_4_is_exit_4_and_no_run(self):
        self.podman()
        with open(os.path.join(self.tmp, "afile"), "w"):
            pass
        r = self.up(SWARMBOX_WORKSPACE=os.path.join(self.tmp, "afile"))
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("is not a folder", r.stderr)
        self.assert_no_run()

    def test_create_flags_exit_3_missing_tool_ports_is_exit_3_and_no_run(self):
        self.podman()
        os.unlink(os.path.join(self.hdir, "tool-ports"))
        r = self.up()
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("tool-ports", r.stderr)
        self.assert_no_run()

    def test_the_status_of_create_flags_is_checked_even_when_it_printed_flags(self):
        self.podman()
        prog = os.path.join(self.tmp, "cf-fail")
        with open(prog, "w") as f:
            f.write("#!/bin/sh\nprintf '%s\\n' --hostname half\nexit 4\n")
        os.chmod(prog, 0o755)
        r = self.up(SWARMBOX_TEST_CREATE_FLAGS=prog)
        self.assertEqual(r.returncode, 4)
        self.assert_no_run()
        self.assertEqual(os.listdir(self.state), [])

    def test_workspace_checks_happen_before_the_box_is_touched(self):
        self.podman()
        r = self.up(SWARMBOX_WORKSPACE="/mnt/c/Users/me/swarmbox",
                    SWARMBOX_TEST_PROC_VERSION=self.wsl_version())
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("is on a Windows drive", r.stderr)
        self.assert_no_run()

    def wsl_version(self):
        p = os.path.join(self.tmp, "wsl-version")
        with open(p, "w") as f:
            f.write("Linux version 5.15.153.1-microsoft-standard-WSL2\n")
        return p

    def test_a_failed_run_removes_only_the_container_of_its_cidfile(self):
        cid = "a" * 64
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 126, "stderr": "x\n" + BUSY + "\n", "cidfile": cid}]})
        r = self.up()
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assertEqual(self.subs("rm"), [["rm", "-f", cid]])
        self.assertIn("swarmbox: could not create the box:", r.stderr)
        self.assertIn(BUSY, r.stderr)
        self.assertIn("swarmbox config set", r.stderr)
        self.assertIn("WEB_PORT", r.stderr)
        self.assertEqual(os.listdir(self.state), [])

    def test_a_foreign_container_with_the_same_name_is_untouched(self):
        # `podman run --name X` when X exists: exit 125, no cidfile (B18); the foreign container must not be removed
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 125,
                                    "stderr": "Error: creating container storage: the container name \"swarmbox\" is already in use\n"}]})
        r = self.up()
        self.assertEqual(r.returncode, 7)
        self.assertEqual(self.subs("rm"), [])
        self.assertIn("already in use", r.stderr)

    def test_a_failure_with_an_empty_cidfile_removes_nothing(self):
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 125, "stderr": "boom\n", "cidfile": ""}]})
        r = self.up()
        self.assertEqual(r.returncode, 7)
        self.assertEqual(self.subs("rm"), [])

    def test_only_the_last_lines_of_podmans_error_are_shown(self):
        many = "".join("noise %d\n" % i for i in range(30)) + "the real reason\n"
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 125, "stderr": many}]})
        r = self.up()
        self.assertIn("the real reason", r.stderr)
        self.assertNotIn("noise 0\n", r.stderr)

    def test_the_removal_of_the_partial_container_is_quiet_and_its_failure_does_not_change_the_code(self):
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 126, "stderr": BUSY + "\n", "cidfile": "b" * 64}]},
                    rm={"exit": 1, "stderr": "rm failed\n"})
        r = self.up()
        self.assertEqual(r.returncode, 7)
        self.assertNotIn("rm failed", r.stderr)


class ConflictTest(Base):
    V010 = line(managed="", image="swarmbox:latest")

    def test_a_v0_1_0_container_is_exit_5_for_up_and_is_never_removed(self):
        self.podman(lookup={"stdout": self.V010}, mounts="/home/me/work\n")
        r = self.up()
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("A container named 'swarmbox' made by SwarmBox v0.1.0 exists (workspace: /home/me/work).", r.stderr)
        self.assertIn("podman rm -f swarmbox", r.stderr)
        self.assertIn("swarmbox config set WORKSPACE /home/me/work", r.stderr)
        self.assert_no_run()
        self.assertEqual(self.subs("rm"), [])
        self.assertEqual(self.subs("start"), [])

    def test_the_v0_1_0_message_survives_a_mounts_lookup_that_fails(self):
        self.podman(lookup={"stdout": self.V010})
        self.fp.configure(self.conf(lookup={"stdout": self.V010}, mounts=""))
        r = self.up()
        self.assertEqual(r.returncode, 5)
        self.assertIn("v0.1.0", r.stderr)

    def test_a_v0_1_0_container_is_exit_5_for_reset_and_is_never_removed(self):
        self.podman(lookup={"stdout": self.V010}, mounts="/home/me/work\n")
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("made by SwarmBox v0.1.0", r.stderr)
        self.assertEqual(self.subs("rm"), [])
        self.assert_no_run()

    def test_a_v0_1_0_container_that_is_stopped_is_also_refused(self):
        self.podman(lookup={"stdout": line(state="exited", managed="")})
        r = self.up()
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.subs("start"), [])

    def test_another_box_on_the_same_workspace_is_exit_5(self):
        self.podman(ps={"stdout": "other\n"})
        r = self.up()
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("swarmbox: workspace %s is already used by box 'other'" % self.ws, r.stderr)
        self.assert_no_run()
        ps = self.subs("ps")[0]
        self.assertIn("label=swarmbox.workspace=%s" % self.ws, ps)
        self.assertEqual(self.subs("rm"), [])

    def test_the_workspace_check_asks_podman_for_the_label_not_for_a_name(self):
        self.podman()
        self.up()
        ps = self.subs("ps")
        self.assertEqual(len(ps), 1)
        self.assertIn("-a", ps[0])
        self.assertTrue(any(a.startswith("label=swarmbox.workspace=") for a in ps[0]))

    def test_the_same_box_listed_by_the_label_is_not_a_conflict(self):
        self.podman(ps={"stdout": NAME + "\n"})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)


# ============================================================================ start and readiness

class ReadinessTest(Base):
    def test_a_stopped_box_is_started_and_waited_for(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("start"), [["start", NAME]])
        self.assert_no_run()
        self.assertEqual(self.subs("rm"), [])
        self.assertTrue(self.subs("exec"))

    def test_a_stopped_box_with_a_changed_config_warns_and_still_starts(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")})
        r = self.up(SWARMBOX_PORTS="3000")
        self.assertEqual(r.returncode, 0)
        self.assertIn("`PORTS` changed", r.stderr)
        self.assertEqual(self.subs("start"), [["start", NAME]])

    def test_a_start_that_fails_is_exit_7_and_removes_nothing(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")},
                    start={"exit": 125, "stderr": "Error: " + BUSY + "\n"})
        r = self.up()
        self.assertEqual(r.returncode, 7)
        self.assertIn("could not start the box", r.stderr)
        self.assertIn("address already in use", r.stderr)
        self.assertEqual(self.subs("rm"), [])

    def test_the_marker_is_read_with_exec(self):
        self.podman()
        self.up()
        ex = self.subs("exec")[0]
        self.assertEqual(ex, ["exec", NAME, "cat", "/tmp/swarmbox/ready"])

    def test_a_late_marker_is_waited_for(self):
        self.podman(exec={"seq": [{"exit": 1}, {"exit": 1}, {"exit": 1}, {"stdout": "ok\n"}]})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.subs("exec")), 4)

    def test_a_marker_with_warnings_is_reported(self):
        self.podman(exec={"stdout": "warnings=2\n"})
        r = self.up()
        self.assertEqual(r.returncode, 0)
        self.assertIn("2 warning", r.stderr)

    def test_a_marker_that_never_appears_is_exit_6_after_the_tuned_wait(self):
        self.podman(exec={"exit": 1, "stderr": "no such file\n"})
        r = self.up(SWARMBOX_TEST_READY_TRIES="6")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertIn("swarmbox: the box did not become ready", r.stderr)
        self.assertIn("podman logs %s" % NAME, r.stderr)
        self.assertEqual(len(self.subs("exec")), 6)
        self.assertEqual(self.subs("logs"), [])

    def test_the_default_wait_is_60_polls_of_one_second_and_the_text_gives_the_seconds(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        self.assertIn("SWARMBOX_TEST_READY_TRIES:-60", src)
        self.assertIn("SWARMBOX_TEST_NAP:-1}", src)
        self.podman(exec={"exit": 1})
        r = self.up(SWARMBOX_TEST_READY_TRIES="3", SWARMBOX_TEST_NAP="1")
        self.assertEqual(r.returncode, 6)
        self.assertIn("did not become ready in 3 s; see `podman logs swarmbox`", r.stderr)

    def test_a_container_that_exits_while_waiting_is_exit_6_at_once_with_its_logs(self):
        self.podman(exec={"exit": 125, "stderr": "container is not running\n"},
                    logs={"stdout": "serve: workspace is not writable\n"})
        c = self.conf(state="exited\n", exec={"exit": 125, "stderr": "no\n"}, logs={"stdout": "serve: workspace is not writable\n"})
        self.fp.configure(c)
        t0 = time.time()
        r = self.up(SWARMBOX_TEST_READY_TRIES="60", SWARMBOX_TEST_NAP="5")
        self.assertLess(time.time() - t0, 4)
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertEqual(len(self.subs("exec")), 1)
        self.assertEqual(len(self.subs("logs")), 1)
        self.assertEqual(self.subs("logs")[0][:2], ["logs", "--tail"])
        self.assertEqual(self.subs("logs")[0][-1], NAME)
        self.assertIn("serve: workspace is not writable", r.stderr)
        self.assertIn("exited", r.stderr)

    def test_the_state_is_read_only_when_the_marker_is_not_there(self):
        self.podman()
        self.up()
        states = [c for c in self.calls() if c[:2] == ["container", "inspect"] and any("swarmbox.fingerprint" not in a and "State.Status" in a for a in c)]
        self.assertEqual(states, [])

    def test_an_unreadable_state_while_waiting_counts_as_gone(self):
        c = self.conf(exec={"exit": 1}, logs={"stdout": "x\n"})
        c["container"]["rules"][2] = {"match": ["inspect", "State.Status"], **NOSUCH}
        self.podman()
        self.fp.configure(c)
        r = self.up(SWARMBOX_TEST_READY_TRIES="60", SWARMBOX_TEST_NAP="5")
        self.assertEqual(r.returncode, 6)


# ============================================================================ the lock

class LockTest(Base):
    def slow_create_flags(self):
        """A create-flags that announces itself, waits for a `release` file, then runs the real one."""
        self.release = os.path.join(self.tmp, "release")
        self.entered = os.path.join(self.tmp, "entered")
        prog = os.path.join(self.tmp, "cf-slow")
        with open(prog, "w") as f:
            f.write("#!/bin/sh\n"
                    "echo $$ >> '%s'\n"
                    "while [ ! -e '%s' ]; do sleep 0.02; done\n"
                    "exec '%s' \"$@\"\n" % (self.entered, self.release, self.helper))
        os.chmod(prog, 0o755)
        return prog

    def start(self, prog, **extra):
        env = self.env(SWARMBOX_TEST_CREATE_FLAGS=prog, **extra)
        p = subprocess.Popen([self.helper, "up"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             stdin=subprocess.DEVNULL, cwd=self.tmp, start_new_session=True)
        self.addCleanup(self._reap, p)
        return p

    def _reap(self, p):
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        p.communicate()
        if hasattr(self, "release"):
            open(self.release, "a").close()

    def wait_for(self, fn, what, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            if fn():
                return
            time.sleep(0.02)
        self.fail("timed out waiting for " + what)

    def entered_count(self):
        try:
            with open(self.entered) as f:
                return len(f.read().split())
        except OSError:
            return 0

    @property
    def lock(self):
        return os.path.join(self.state, "up-%s.lock" % NAME)

    def two_terminal_conf(self):
        # the first lookup finds no box; once one `run` has happened every later lookup finds it running
        line_ok = self.matching_line()
        return self.conf(lookup={"seq": [NOSUCH, {"stdout": line_ok}]})

    def test_two_up_calls_started_together_make_exactly_one_box(self):
        self.podman()
        prog = self.slow_create_flags()
        self.fp.configure(self.two_terminal_conf())
        p1 = self.start(prog)
        self.wait_for(lambda: self.entered_count() == 1, "the first call inside create-flags")
        self.assertTrue(os.path.isdir(self.lock))
        with open(os.path.join(self.lock, "pid")) as f:
            self.assertEqual(f.read().strip(), str(p1.pid))
        p2 = self.start(prog)
        time.sleep(0.4)   # the second call is at the lock by now; if it were later the outcome below is the same
        self.assertIsNone(p2.poll(), "the second call must wait for the lock")
        self.assertEqual(self.entered_count(), 1)
        open(self.release, "a").close()
        o1, e1 = p1.communicate(timeout=30)
        o2, e2 = p2.communicate(timeout=30)
        self.assertEqual((p1.returncode, p2.returncode), (0, 0), e1 + e2)
        self.assertEqual(len(self.real_runs()), 1)
        self.assertEqual(len(self.lookups()), 2)
        self.assertFalse(os.path.exists(self.lock))

    def test_many_concurrent_up_calls_make_one_box(self):
        self.podman()
        self.fp.configure(self.two_terminal_conf())
        procs = [self.start("") for _ in range(6)]
        for p in procs:
            p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0)
        self.assertEqual(len(self.real_runs()), 1)
        self.assertFalse(os.path.exists(self.lock))

    def test_the_lock_is_atomic_over_repeated_rounds_of_concurrent_calls(self):
        # B33: ten rounds of eight real processes started together; every round makes exactly one box
        for rnd in range(10):
            self.podman()
            self.fp.configure(self.two_terminal_conf())
            shutil.rmtree(self.state, True)
            procs = [self.start("") for _ in range(8)]
            for p in procs:
                p.communicate(timeout=60)
                self.assertEqual(p.returncode, 0, "round %d" % rnd)
            self.assertEqual(len(self.real_runs()), 1, "round %d: %r" % (rnd, self.real_runs()))
            self.assertFalse(os.path.exists(self.lock))

    def test_sigterm_leaves_no_lock_and_no_run(self):
        self.podman()
        prog = self.slow_create_flags()
        p = self.start(prog)
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        self.assertTrue(os.path.isdir(self.lock))
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertFalse(os.path.exists(self.lock))
        self.assert_no_run()
        self.assertEqual(os.listdir(self.state), [])

    def test_sigint_leaves_no_lock(self):
        self.podman()
        prog = self.slow_create_flags()
        p = self.start(prog)
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        p.send_signal(signal.SIGINT)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 130)
        self.assertFalse(os.path.exists(self.lock))

    def test_sigkill_leaves_a_stale_lock_that_the_next_call_removes_by_the_dead_pid(self):
        self.podman()
        prog = self.slow_create_flags()
        p = self.start(prog)
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        os.kill(p.pid, signal.SIGKILL)
        open(self.release, "a").close()   # the orphaned create-flags holds the pipes until it is released
        p.communicate(timeout=20)
        self.assertTrue(os.path.isdir(self.lock), "a killed -9 call cannot clean up")
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.real_runs()), 1)
        self.assertFalse(os.path.exists(self.lock))
        # the dead call's temporary files (flags.<pid>) are swept by the call that took over
        self.assertEqual([n for n in os.listdir(self.state) if n.endswith(".%d" % p.pid)], [])

    def test_a_lock_without_a_pid_file_is_stale_after_the_tuned_wait(self):
        self.podman()
        os.makedirs(self.lock)
        r = self.up(SWARMBOX_TEST_LOCK_PIDWAIT="4", SWARMBOX_TEST_NAP="0.05")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.real_runs()), 1)

    def test_a_lock_that_is_new_and_has_no_pid_yet_is_waited_for(self):
        # the holder has made the folder and not yet written its pid: not stale until the tuned wait has passed
        self.podman()
        os.makedirs(self.lock)
        r = self.up(SWARMBOX_TEST_LOCK_PIDWAIT="1000", SWARMBOX_TEST_LOCK_TRIES="5", SWARMBOX_TEST_NAP="0.02")
        self.assertEqual(r.returncode, 6)
        self.assertTrue(os.path.isdir(self.lock))

    def test_a_dead_pid_in_the_lock_is_stale_at_once(self):
        self.podman()
        dead = subprocess.Popen(["true"])
        dead.wait()
        os.makedirs(self.lock)
        with open(os.path.join(self.lock, "pid"), "w") as f:
            f.write("%d\n" % dead.pid)
        r = self.up(SWARMBOX_TEST_NAP="5")   # a pause of 5 s would show if it waited
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_live_holder_for_longer_than_the_tuned_wait_is_exit_6_and_the_lock_stays(self):
        self.podman()
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(holder.wait)   # cleanups run last-in first-out: kill, then wait
        self.addCleanup(holder.kill)
        os.makedirs(self.lock)
        with open(os.path.join(self.lock, "pid"), "w") as f:
            f.write("%d\n" % holder.pid)
        r = self.up(SWARMBOX_TEST_LOCK_TRIES="8", SWARMBOX_TEST_NAP="0.05")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertIn("another 'up' holds %s" % self.lock, r.stderr)
        self.assertTrue(os.path.isdir(self.lock), "a live lock is never removed")
        self.assertEqual(self.calls(), [])

    def test_the_default_wait_is_90_polls_of_one_second(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        self.assertIn("SWARMBOX_TEST_LOCK_TRIES:-90", src)
        self.assertIn("SWARMBOX_TEST_LOCK_PIDWAIT:-5", src)

    def test_the_lock_folder_is_named_for_the_box(self):
        self.podman()
        prog = self.slow_create_flags()
        p = self.start(prog, SWARMBOX_NAME="other")
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        self.assertTrue(os.path.isdir(os.path.join(self.state, "up-other.lock")))
        self.assertFalse(os.path.exists(self.lock))
        open(self.release, "a").close()
        p.communicate(timeout=30)

    def test_the_lock_is_released_after_a_failure_too(self):
        self.podman(run={"rules": [{"match": ["--cidfile"], "exit": 125, "stderr": "boom\n"}]})
        r = self.up()
        self.assertEqual(r.returncode, 7)
        self.assertEqual(os.listdir(self.state), [])

    def test_the_xdg_state_home_is_honored(self):
        self.podman()
        xdg = os.path.join(self.tmp, "xdgstate")
        prog = self.slow_create_flags()
        p = self.start(prog, XDG_STATE_HOME=xdg)
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        self.assertTrue(os.path.isdir(os.path.join(xdg, "swarmbox", "up-%s.lock" % NAME)))
        open(self.release, "a").close()
        p.communicate(timeout=30)

    def test_a_signal_while_waiting_for_the_lock_leaves_the_holders_lock_alone(self):
        self.podman()
        prog = self.slow_create_flags()
        p1 = self.start(prog)
        self.wait_for(lambda: self.entered_count() == 1, "create-flags")
        p2 = self.start(prog)
        time.sleep(0.3)
        p2.send_signal(signal.SIGTERM)
        p2.communicate(timeout=20)
        self.assertEqual(p2.returncode, 143)
        self.assertTrue(os.path.isdir(self.lock), "the waiter must not remove the lock it never held")
        open(self.release, "a").close()
        p1.communicate(timeout=30)
        self.assertEqual(p1.returncode, 0)


# ============================================================================ reset

class ResetTest(Base):
    def test_reset_removes_then_creates_and_keeps_the_volume(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        rm = [i for i, c in enumerate(calls) if c[:1] == ["rm"]]
        run = [i for i, c in enumerate(calls) if c[:1] == ["run"]]
        self.assertEqual([calls[i] for i in rm], [["rm", "-f", NAME]])
        self.assertEqual(len(run), 1)
        self.assertLess(rm[0], run[0])
        for c in calls:
            self.assertNotIn("volume", c[:2])
            self.assertNotEqual(c[:1], ["volume"])
        self.assertEqual(self.subs("start"), [])
        self.assertTrue(self.subs("exec"), "reset waits for readiness")

    def test_reset_returns_the_code_of_up(self):
        self.podman(lookup={"stdout": self.matching_line()},
                    run={"rules": [{"match": ["--cidfile"], "exit": 126, "stderr": BUSY + "\n", "cidfile": "c" * 64}]})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 7)
        self.assertEqual(self.subs("rm"), [["rm", "-f", NAME], ["rm", "-f", "c" * 64]])

    def test_reset_returns_6_when_the_new_box_is_not_ready(self):
        self.podman(lookup={"stdout": self.matching_line()}, exec={"exit": 1})
        r = self.run_h("reset", env=self.env(SWARMBOX_TEST_READY_TRIES="3"))
        self.assertEqual(r.returncode, 6)

    def test_reset_is_exit_1_when_the_removal_fails_and_creates_nothing(self):
        self.podman(lookup={"stdout": self.matching_line()}, rm={"exit": 1, "stderr": "Error: cannot remove\n"})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot remove", r.stderr)
        self.assert_no_run()

    def test_reset_without_a_box_just_creates_one(self):
        self.podman()
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("rm"), [])
        self.assertEqual(len(self.real_runs()), 1)

    def test_reset_recreates_a_stopped_box_too(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.subs("rm"), [["rm", "-f", NAME]])
        self.assertEqual(len(self.real_runs()), 1)

    def test_reset_refuses_a_container_without_the_managed_label(self):
        self.podman(lookup={"stdout": line(managed="")})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.subs("rm"), [])

    def test_reset_does_not_remove_a_container_that_only_shares_the_name_prefix(self):
        self.podman(lookup={"stdout": line(name="swarmbox-cloudflared")})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("rm"), [])

    def test_reset_takes_the_lock_and_releases_it(self):
        self.podman(lookup={"stdout": self.matching_line()})
        self.run_h("reset")
        self.assertEqual(os.listdir(self.state), [])

    def test_reset_refuses_when_another_box_uses_the_workspace(self):
        self.podman(lookup={"stdout": self.matching_line()}, ps={"stdout": "other\n"})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.subs("rm"), [], "the old box must not be removed when the new one could not be made")

    def test_a_workspace_problem_is_found_before_the_old_box_is_removed(self):
        # the flags are captured and checked before `rm -f`: a reset that cannot create the new box keeps the old one
        self.podman(lookup={"stdout": self.matching_line()})
        with open(os.path.join(self.tmp, "afile"), "w"):
            pass
        r = self.run_h("reset", env=self.env(SWARMBOX_WORKSPACE=os.path.join(self.tmp, "afile")))
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.subs("rm"), [])
        self.assert_no_run()

    def test_prerequisites_are_checked_before_the_old_box_is_removed(self):
        self.podman(lookup={"stdout": self.matching_line()}, version={"stdout": "4.0.0\n"})
        r = self.run_h("reset")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.subs("rm"), [])


# ============================================================================ stop and url

class StopUrlTest(Base):
    def test_stop_stops_the_box_by_its_exact_name(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("stop"), [["stop", NAME]])

    def test_stop_is_exit_1_when_podman_fails(self):
        self.podman(lookup={"stdout": self.matching_line()}, stop={"exit": 125, "stderr": "Error: boom\n"})
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 1)
        self.assertIn("boom", r.stderr)

    def test_stop_without_a_box_says_so_and_is_exit_0(self):
        self.podman()
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no box named 'swarmbox'", r.stderr)
        self.assertEqual(self.subs("stop"), [])

    def test_stop_of_a_container_that_is_not_ours_is_refused(self):
        self.podman(lookup={"stdout": line(managed="")})
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 5)
        self.assertEqual(self.subs("stop"), [])

    def test_stop_of_an_already_stopped_box_is_fine(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")})
        r = self.run_h("stop")
        self.assertEqual(r.returncode, 0)

    def test_stop_with_podman_missing_is_exit_3(self):
        self.podman()
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS:
            p = shutil.which(t)
            if p and not os.path.exists(os.path.join(bindir, t)):
                os.symlink(p, os.path.join(bindir, t))
        r = self.run_h("stop", env=self.env(PATH=bindir))
        self.assertEqual(r.returncode, 3)

    def url_env(self, **extra):
        return self.env(**extra)

    def test_url_prints_the_local_url_and_never_calls_podman(self):
        self.podman()
        r = self.run_h("url", env=self.url_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\n")
        self.assertEqual(self.calls(), [])

    def test_url_works_without_podman_on_the_path(self):
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        for t in HELPER_TOOLS:
            p = shutil.which(t)
            if p and not os.path.exists(os.path.join(bindir, t)):
                os.symlink(p, os.path.join(bindir, t))
        e = self.env(PATH=bindir)
        r = self.run_h("url", env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\n")

    def test_url_follows_web_port(self):
        self.podman()
        r = self.run_h("url", env=self.url_env(SWARMBOX_WEB_PORT="7700"))
        self.assertEqual(r.stdout, "http://127.0.0.1:7700\n")

    def cloudflare_json(self, domain):
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "cloudflare.json"), "w") as f:
            json.dump({"domain": domain, "emails": ["a@b.c"], "tunnel": "t"}, f, indent=2)

    def test_url_adds_the_public_url_from_cloudflare_json(self):
        self.podman()
        self.cloudflare_json("example.com")
        r = self.run_h("url", env=self.url_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\nhttps://swarmbox.example.com\n")
        self.assertEqual(self.calls(), [])

    def test_url_public_name_is_per_box(self):
        self.podman()
        self.cloudflare_json("example.com")
        r = self.run_h("url", env=self.url_env(SWARMBOX_NAME="other"))
        self.assertEqual(r.stdout.splitlines()[1], "https://other.example.com")

    def test_url_web_hostname_wins(self):
        self.podman()
        self.cloudflare_json("example.com")
        r = self.run_h("url", env=self.url_env(SWARMBOX_WEB_HOSTNAME="term.example.org"))
        self.assertEqual(r.stdout.splitlines()[1], "https://term.example.org")

    def test_url_web_domain_from_the_environment(self):
        self.podman()
        r = self.run_h("url", env=self.url_env(SWARMBOX_WEB_DOMAIN="example.net"))
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\nhttps://swarmbox.example.net\n")

    def test_url_ignores_a_broken_cloudflare_json_and_a_hostile_domain(self):
        self.podman()
        d = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(d)
        with open(os.path.join(d, "cloudflare.json"), "w") as f:
            f.write("{not json")
        r = self.run_h("url", env=self.url_env())
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\n")
        r = self.run_h("url", env=self.url_env(SWARMBOX_WEB_DOMAIN="a b;rm -rf"))
        self.assertEqual(r.stdout, "http://127.0.0.1:7681\n")
        self.assertIn("ignoring", r.stderr)

    def test_url_with_the_web_terminal_off_is_exit_1(self):
        self.podman()
        r = self.run_h("url", env=self.url_env(SWARMBOX_WEB="0"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("WEB=0", r.stderr)

    def test_url_usage(self):
        self.podman()
        r = self.run_h("url", "extra")
        self.assertEqual(r.returncode, 2)

    def test_the_url_code_path_has_no_podman_call(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        body = src.split("cmd_url() {", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("podman", body)


class StaticTest(unittest.TestCase):
    def test_no_destructive_podman_verbs_and_no_bashisms_in_the_new_code(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        for bad in ("system prune", "system reset", "volume prune", "volume rm", "image prune", "rm -a", "stop -a", "kill -a",
                    "rmi "):
            self.assertNotIn(bad, src, bad)

    def test_shellcheck_posix_if_available(self):
        sc = shutil.which("shellcheck")
        if not sc:
            self.skipTest("shellcheck is not installed")
        r = subprocess.run([sc, "-s", "sh", HELPER_SRC], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class ShellsTest(Base):
    """The same up/reset/stop scenario under the other sh implementations (B23): the helper must not depend on bash."""

    def test_up_fast_path_and_create_under_each_shell(self):
        shells = [s for s in ("dash", "bash", "busybox") if shutil.which(s)]
        self.assertTrue(shells)
        for sh in shells:
            argv0 = [shutil.which(sh)] + (["sh"] if sh == "busybox" else ["--posix"] if sh == "bash" else [])
            self.podman()
            p = subprocess.run(argv0 + [self.helper, "up"], env=self.env(), capture_output=True, text=True, input="",
                               cwd=self.tmp, timeout=60)
            self.assertEqual(p.returncode, 0, "%s: %s" % (sh, p.stderr))
            self.assertEqual(len(self.real_runs()), 1, sh)
            self.assertEqual(os.listdir(self.state), [], sh)


if __name__ == "__main__":
    unittest.main()
