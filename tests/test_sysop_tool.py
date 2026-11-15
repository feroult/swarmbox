"""The `sysop` tool as the box handles it: the manifest, install.sh and prepare.sh, run by the REAL swarmbox-tool.sh in a temporary tree (home,
image tools, lock): install, where, prepare, the detached service, idempotence, the refresh of the library. No network, no model, no tmux.
Run with: python3 -W error tests/test_sysop_tool.py
"""
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402
from helpers import ROOT  # noqa: E402

import swarmbox_sysop  # noqa: E402

TOOL = ss.SYSOP
TOOL_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Manifest(unittest.TestCase):
    def test_the_manifest_is_the_todays_format_pinned(self):
        text = rd(os.path.join(TOOL, "tool.conf"))
        lines = re.sub(r"(?m)^#.*$", "", text).split()
        for line in ("SCHEMA=1", "NAME=sysop", "KIND=tool", 'PROVIDES="swarmbox-sysop"'):
            self.assertIn(line, lines)
        version = re.search(r"^VERSION=(\S+)$", text, re.M).group(1)
        self.assertNotEqual(version, "latest")
        self.assertEqual(version, swarmbox_sysop.__version__, "tool.conf and swarmbox_sysop.__version__ are one number")
        for key in ("SHA256_", "PORTS=", "UPDATE", "YOLO", "MCP_", "plugin"):
            self.assertNotIn(key, re.sub(r"(?m)^#.*$", "", text))

    def test_scripts_are_executable_and_pass_bash_n_and_shellcheck(self):
        for name in ("install.sh", "prepare.sh"):
            p = os.path.join(TOOL, name)
            self.assertTrue(os.stat(p).st_mode & stat.S_IXUSR, name)
            self.assertEqual(subprocess.run(["bash", "-n", p]).returncode, 0)
            sc = shutil.which("shellcheck")
            if sc:
                r = subprocess.run([sc, "-s", "bash", p], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_nothing_is_built_at_image_build_and_no_network_word_is_in_the_scripts(self):
        self.assertNotRegex(rd(os.path.join(ROOT, "Dockerfile")), r"(?m)^[^#\n]*\bsysop\b")
        for name in ("install.sh", "prepare.sh"):
            self.assertNotRegex(re.sub(r"(?m)^\s*#.*$", "", rd(os.path.join(TOOL, name))), r"\b(curl|wget|pip|npm|git clone|apt)\b")

    def test_the_library_has_no_third_party_import(self):
        std = set(sys.stdlib_module_names)
        bad = []
        for name in os.listdir(os.path.join(ss.LIB, "swarmbox_sysop")):
            if name.endswith(".py"):
                for m in re.finditer(r"(?m)^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", rd(os.path.join(ss.LIB, "swarmbox_sysop", name))):
                    if m.group(1) not in std and m.group(1) != "swarmbox_sysop":
                        bad.append((name, m.group(1)))
        self.assertEqual(bad, [])


class Tree(unittest.TestCase):
    """a tree for the real swarmbox-tool.sh: image tools (a copy of this tool), a home, a lock, and a swarmbox-tool command on PATH"""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="sbtl-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.base, True)
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.image, self.home, self.user, self.fbin = j("image"), j("home"), j("user"), j("fbin")
        for d in (self.image, self.home, self.user, self.fbin):
            os.mkdir(d)
        shutil.copytree(TOOL, os.path.join(self.image, "sysop"), ignore=shutil.ignore_patterns("__pycache__"))
        self.env = {"PATH": self.fbin + ":/usr/bin:/bin", "HOME": self.home, "SB_RUN_DIR": j("run"), "SB_STATE_DIR": j("state"),
                    "SWARMBOX_TEST_LIB": os.path.join(ROOT, "container", "scripts"), "SWARMBOX_TEST_IMAGE_TOOLS": self.image,
                    "SWARMBOX_TEST_USER_TOOLS": self.user, "SWARMBOX_TEST_HOST_DIR": j("host"),
                    "SWARMBOX_TEST_IMAGE_SHIMS": j("out", "shims"), "SWARMBOX_TEST_USER_SHIMS": j("out", "ushims"), "SWARMBOX_TEST_LOCK": j("lock")}
        with open(os.path.join(self.fbin, "swarmbox-tool"), "w") as f:
            f.write('#!/bin/sh\nexec bash "%s" "$@"\n' % TOOL_SH)
        os.chmod(os.path.join(self.fbin, "swarmbox-tool"), 0o755)
        self.paths = ss.paths.Paths(self.env)
        self.addCleanup(self.kill_service)

    def kill_service(self):
        """the watcher first (it would start the service again), then the service"""
        for pidfile in (self.paths.watch_pidfile, self.paths.pidfile):
            try:
                with open(pidfile) as f:
                    pid = int(f.read())
            except (OSError, ValueError):
                continue
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    break
                if ss.wait_for(lambda: not self.alive(pid), 5):
                    break

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        try:
            return rd("/proc/%d/stat" % pid).rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False

    def tool(self, *args, timeout=60):
        return subprocess.run(["bash", TOOL_SH] + list(args), env=self.env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=self.home)

    @property
    def prefix(self):
        return os.path.join(self.home, ".local", "share", "swarmbox", "tools", "sysop", "1.0.0")

    def command(self, *args):
        return subprocess.run([os.path.join(self.prefix, "bin", "swarmbox-sysop")] + list(args), env={"PATH": "/usr/bin:/bin", "HOME": self.home, **{k: v for k, v in self.env.items() if k.startswith("SB_")}},
                              capture_output=True, text=True, timeout=30)

    def install(self, keep_service=False):
        """swarmbox-tool install runs prepare.sh after the install, so the service is already up; most tests want it down first"""
        r = self.tool("install", "sysop")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if not keep_service:
            self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.pidfile), 10), r.stderr)
            self.kill_service()
            self.assertTrue(ss.wait_for(lambda: self.command("status", "-q").returncode == 1, 10))
        return r

    def prepare(self):
        return self.tool("prepare")

    def pid(self):
        return int(rd(self.paths.pidfile))


class Install(Tree):
    def test_validate_accepts_it(self):
        r = self.tool("validate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("image/sysop  (tool, VERSION=1.0.0", r.stdout)

    def test_install_copies_the_library_and_leaves_a_working_command(self):
        r = self.install(keep_service=True)
        self.assertIn("self-test ok", r.stderr)
        self.assertIn("started the goal subscriber", r.stderr, "the install runs prepare.sh, which starts the service")
        self.assertTrue(ss.wait_for(lambda: self.command("status", "-q").returncode == 0, 10))
        self.kill_service()
        self.assertTrue(ss.wait_for(lambda: self.command("status", "-q").returncode == 1, 10))
        for rel in ("bin/swarmbox-sysop", "lib/swarmbox_sysop/__init__.py", "lib/swarmbox_sysop/cli.py", "lib/swarmbox_sysop/mcpserver.py", "lib/swarmbox_sysop/brain.py"):
            self.assertTrue(os.path.exists(os.path.join(self.prefix, rel)), rel)
        self.assertTrue(os.access(os.path.join(self.prefix, "bin", "swarmbox-sysop"), os.X_OK))
        self.assertEqual([p for d, ds, fs in os.walk(self.prefix) for p in ds if p == "__pycache__"], [], "no bytecode copied or written")
        w = self.tool("where", "sysop", "swarmbox-sysop")
        self.assertEqual(w.returncode, 0)
        self.assertTrue(w.stdout.strip().endswith("bin/swarmbox-sysop"))
        c = self.command("status")
        self.assertEqual(c.returncode, 1)
        self.assertIn("not running", c.stdout)
        self.assertEqual(self.command("--self-test").returncode, 0)

    def test_install_writes_only_under_the_tool_folder_and_uses_no_network(self):
        before = set()
        self.install(keep_service=True)
        self.kill_service()
        for d, ds, fs in os.walk(self.home):
            for n in fs + ds:
                before.add(os.path.relpath(os.path.join(d, n), self.home))
        top = ".local/share/swarmbox/tools/sysop"
        self.assertTrue(all(x.startswith(top) or top.startswith(x) for x in before), sorted(before)[:10])

    def test_the_installer_refuses_a_missing_or_floating_version(self):
        inst = os.path.join(TOOL, "install.sh")
        prefix = os.path.join(self.base, "p")
        for version in ("latest", "", "1.0; rm -rf x", "../1"):
            r = subprocess.run(["bash", inst], env={"PATH": "/usr/bin:/bin", "TOOL_PREFIX": prefix, "TOOL_VERSION": version, "TOOL_ARCH": "amd64"}, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, version)
            self.assertFalse(os.path.exists(prefix), version)
        r = subprocess.run(["bash", inst], env={"PATH": "/usr/bin:/bin", "TOOL_VERSION": "1.0.0"}, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        r = subprocess.run(["bash", inst], env={"PATH": "/usr/bin:/bin", "TOOL_PREFIX": prefix, "TOOL_VERSION": "1.0.0", "TOOL_ARCH": "amd64"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")


class Prepare(Tree):
    def test_prepare_of_a_tool_that_is_not_installed_does_nothing(self):
        r = self.prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.paths.pidfile))
        r = subprocess.run(["bash", os.path.join(TOOL, "prepare.sh")], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.paths.pidfile))

    def test_prepare_starts_the_subscriber_detached_and_returns_at_once(self):
        self.install()
        t0 = time.time()
        r = self.prepare()               # capture_output waits for EOF on the pipes: a service that kept them would hang this until the timeout
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("started the goal subscriber", r.stderr)
        self.assertTrue(ss.wait_for(lambda: self.command("status", "-q").returncode == 0, 10))
        pid = self.pid()
        self.assertTrue(self.alive(pid))
        stat_ = rd("/proc/%d/stat" % pid).rsplit(")", 1)[1].split()
        watcher = int(rd(self.paths.watch_pidfile))
        self.assertNotEqual(watcher, pid, "the service runs under a watcher that starts it again when it dies")
        self.assertEqual(int(rd("/proc/%d/stat" % watcher).rsplit(")", 1)[1].split()[3]), watcher, "the watcher is the leader of a session of its own (setsid)")
        self.assertEqual((int(stat_[2]), int(stat_[3])), (watcher, watcher), "the service is in that session and group: the timeout of prepare cannot reach it")
        self.assertEqual(os.readlink("/proc/%d/fd/0" % pid), "/dev/null")
        self.assertEqual(os.readlink("/proc/%d/fd/1" % pid), self.paths.log)
        self.assertEqual(stat.S_IMODE(os.stat(self.paths.log).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.paths.run).st_mode), 0o700)
        self.assertTrue(ss.wait_for(lambda: "serving" in (rd(self.paths.log) if os.path.exists(self.paths.log) else ""), 10))

    def test_prepare_is_idempotent_one_service_however_often_it_runs(self):
        self.install()
        self.assertEqual(self.prepare().returncode, 0)
        self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.pidfile), 10))
        pid = self.pid()
        for _ in range(3):
            r = self.prepare()
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("started", r.stderr)
        self.assertEqual(self.pid(), pid)
        self.assertTrue(self.alive(pid))

    def test_two_prepares_at_once_end_with_one_service(self):
        self.install()
        procs = [subprocess.Popen(["bash", TOOL_SH, "prepare"], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, cwd=self.home) for _ in range(4)]
        for p in procs:
            self.assertEqual(p.wait(30), 0)
        self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.pidfile), 10))
        pid = self.pid()
        count = lambda: [x for x in os.listdir("/proc") if x.isdigit() and self.is_service(int(x))]  # noqa: E731
        # the ones that lose the lock wait for it for Service.LOCK_WAIT (1 s) before they give up, so the count settles a moment later
        ss.wait_for(lambda: count() == [str(pid)], 6)
        time.sleep(0.5)
        self.assertEqual(count(), [str(pid)], "exactly one service")

    def is_service(self, pid):
        try:
            cmd = rd("/proc/%d/cmdline" % pid).split("\0")
            env = rd("/proc/%d/environ" % pid)
        except OSError:
            return False
        return "swarmbox_sysop" in cmd and "serve" in cmd and "--watch" not in cmd and ("SB_RUN_DIR=" + self.env["SB_RUN_DIR"]) in env       # the watcher is not a service

    def test_a_service_that_died_is_started_again(self):
        self.install()
        self.prepare()
        self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.pidfile), 10))
        pid = self.pid()
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(ss.wait_for(lambda: not self.alive(pid), 5))
        r = self.prepare()
        self.assertIn("started", r.stderr)
        self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.pidfile) and self.pid() != pid and self.alive(self.pid()), 10))

    def test_prepare_refreshes_the_installed_library_from_the_image_copy(self):
        self.install()
        cli = os.path.join(self.prefix, "lib", "swarmbox_sysop", "cli.py")
        with open(cli, "a") as f:
            f.write("\n# an old version\n")
        extra = os.path.join(self.prefix, "lib", "swarmbox_sysop", "stale_module.py")
        with open(extra, "w") as f:
            f.write("x = 1\n")
        r = self.prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refreshed lib from the image", r.stderr)
        self.assertEqual(rd(cli), rd(os.path.join(TOOL, "lib", "swarmbox_sysop", "cli.py")))
        self.assertFalse(os.path.exists(extra))
        self.assertEqual([n for n in os.listdir(self.prefix) if n.startswith(".")][:1], [".swarmbox-env"] if os.path.exists(os.path.join(self.prefix, ".swarmbox-env")) else [])
        r = self.prepare()
        self.assertNotIn("refreshed", r.stderr, "equal folders: nothing is written")

    def test_prepare_and_goals_work_together_with_the_real_command(self):
        self.install()
        self.prepare()
        self.assertTrue(ss.wait_for(lambda: os.path.exists(self.paths.status), 10))
        bus = ss.FakeBus(os.path.join(self.base, "run", "bus.sock"))
        self.addCleanup(bus.stop)
        self.assertTrue(bus.wait_subscriber(1, 15), "the service reconnects to a bus that was not there when it started")
        s = self.command("status")
        self.assertEqual(s.returncode, 0)
        self.assertIn("running", s.stdout)


if __name__ == "__main__":
    unittest.main()
