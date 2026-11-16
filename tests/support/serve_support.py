"""The fake world of `swarmbox-entrypoint serve`, shared by the tests of the entrypoint (test_serve_steps, test_serve_logs, test_bus_serve).

Nothing here touches the live box: tmux, ttyd, podman, swarmbox-pubkey and swarmbox-addon are fakes in a scratch folder that comes first on
PATH (the test refuses to run when tmux or podman would resolve elsewhere); HOME, the run folder and every XDG folder are mktemp directories;
`serve` is started by the test and only that PID is ever signalled. The test-only variables SWARMBOX_TEST_* are the ones decided in
docs/history/decision-log.md ([2.2] test-only switches).
"""
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, restore_signals  # noqa: E402
from waiting import wait_until as wait_for  # noqa: E402,F401  (used by the tests that import this module)

restore_signals()

ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie counts as gone
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


FAKE_TMUX = """#!/bin/bash
echo "tmux $*" >> "$FAKE_DIR/calls.log"
[ -f "$FAKE_DIR/tmux.exit" ] && exit "$(cat "$FAKE_DIR/tmux.exit")"
exit 0
"""

FAKE_TTYD = """#!/bin/bash
echo "ttyd $*" >> "$FAKE_DIR/calls.log"
echo start >> "$FAKE_DIR/ttyd.starts"
echo $$ > "$FAKE_DIR/ttyd.pid"
mode=run
[ -f "$FAKE_DIR/ttyd.mode" ] && mode=$(cat "$FAKE_DIR/ttyd.mode")
[ "$mode" = crash ] && exit 1
exec sleep 1000
"""

# the fake bus broker: `serve` records itself and runs (or exits with the status in bus.exit when bus.mode is crash); `ping` is
# answered unless bus.noping exists. SB_BUS_SOCKET is recorded, to see what the entrypoint passes.
FAKE_BUS = """#!/bin/bash
if [ "$1" = ping ]; then [ -f "$FAKE_DIR/bus.noping" ] && exit 4; exit 0; fi
echo "swarmbox-bus $* [$SB_BUS_SOCKET]" >> "$FAKE_DIR/calls.log"
echo start >> "$FAKE_DIR/bus.starts"
echo $$ > "$FAKE_DIR/bus.pid"
mode=run
[ -f "$FAKE_DIR/bus.mode" ] && mode=$(cat "$FAKE_DIR/bus.mode")
[ "$mode" = crash ] && exit "$(cat "$FAKE_DIR/bus.exit" 2>/dev/null || echo 1)"
exec sleep 1000
"""

FAKE_PODMAN = """#!/usr/bin/env python3
import os, socket, sys, time
d = os.environ["FAKE_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write("podman " + " ".join(args) + "\\n")
if "system" in args and "service" in args:
    if os.environ.get("FAKE_MARKER"):   # the stale-marker tests: was the fuse-overlayfs marker still there when the service started?
        open(os.path.join(d, "marker.seen"), "w").write("yes" if os.path.exists(os.environ["FAKE_MARKER"]) else "no")
    if os.path.exists(os.path.join(d, "service.mode")) and open(os.path.join(d, "service.mode")).read().strip() == "fail":
        sys.exit(1)
    path = [a for a in args if a.startswith("unix://")][0][len("unix://"):]
    s = socket.socket(socket.AF_UNIX)
    s.bind(path)
    s.listen(1)
    open(os.path.join(d, "service.pid"), "w").write(str(os.getpid()))
    time.sleep(1000)
    sys.exit(0)
if "--url" in args:
    sys.exit(1 if os.path.exists(os.path.join(d, "service.noanswer")) else 0)
sys.exit(0)
"""

FAKE_PROG = """#!/bin/bash
# generic fake: records the call, exit code from <name>.exit
n=$(basename "$0")
echo "$n $*" >> "$FAKE_DIR/calls.log"
if [ "$n" = swarmbox-addon ] && [ "$1" = install ]; then
    if [ -f "$SWARMBOX_TEST_RUN_DIR/ready" ]; then echo "install $2 saw-ready" >> "$FAKE_DIR/calls.log"; else echo "install $2 no-ready" >> "$FAKE_DIR/calls.log"; fi
fi
if [ -f "$FAKE_DIR/$n.$1.out" ]; then cat "$FAKE_DIR/$n.$1.out"; fi
[ -f "$FAKE_DIR/$n.exit" ] && exit "$(cat "$FAKE_DIR/$n.exit")"
exit 0
"""


class ServeCase(unittest.TestCase):
    PROGRAMS = ("swarmbox-pubkey", "swarmbox-addon", "swarmbox-mcp")

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="serve-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.fake = os.path.join(self.base, "fake")
        self.lib = os.path.join(self.base, "lib")
        self.home = os.path.join(self.base, "home")
        self.run_dir = os.path.join(self.base, "run")
        self.tun = os.path.join(self.base, "tun")
        for d in (self.fake, self.lib, self.home):
            os.mkdir(d)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        open(self.tun, "w").close()
        write_exec(os.path.join(self.fake, "tmux"), FAKE_TMUX)
        write_exec(os.path.join(self.fake, "swarmbox-web"), FAKE_TTYD)
        write_exec(os.path.join(self.fake, "podman"), FAKE_PODMAN)
        write_exec(os.path.join(self.fake, "swarmbox-bus"), FAKE_BUS)
        for p in self.PROGRAMS:
            write_exec(os.path.join(self.fake, p), FAKE_PROG)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.health = os.path.join(self.state, "health")
        self.procs = []
        self.addCleanup(self._reap)

    # -- environment -------------------------------------------------------------------------------------------------
    def env(self, **extra):
        path = self.fake + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
        env = {"PATH": path, "HOME": self.home, "FAKE_DIR": self.fake, "SWARMBOX_TEST_LIB": self.lib,
               "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_TUN": self.tun,
               # step 8 removes this folder: by default it is the real /tmp/storage-run-<uid>, i.e. the runtime state of the nested Podman of whatever
               # box runs these tests (found when the gate wiped it in a running box); every test gets its own
               "SWARMBOX_TEST_PODMAN_RUNROOT": os.path.join(self.base, "storage-run"),
               "SWARMBOX_TEST_PODMAN_LIBPOD_RUN": os.path.join(self.base, "podman-run"),
               "SWARMBOX_TEST_BACKOFF_SCALE": "0", "SWARMBOX_TEST_SERVICE_WAIT": "2", "SWARMBOX_TEST_BUS_WAIT": "1", "LANG": "C.UTF-8"}
        env.update({k: v for k, v in extra.items() if v is not None})
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        for prog in ("tmux", "podman"):  # a real tmux or podman must never run from these tests
            self.assertEqual(shutil.which(prog, path=env["PATH"]), os.path.join(self.fake, prog))
        return env

    def start(self, **extra):
        p = subprocess.Popen(["bash", ENTRYPOINT, "serve"], env=self.env(**extra), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.procs.append(p)
        return p

    def _reap(self):
        for p in self.procs:
            if p.poll() is None:  # only the PID this test started
                try:
                    os.kill(p.pid, signal.SIGTERM)
                    p.wait(timeout=30)
                except Exception:
                    p.kill()
                    p.wait()
            try:  # serve is the leader of its own session: end what it left behind (its `sleep infinity`, fake ttyd)
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            for f in (p.stdout, p.stderr):
                if f:
                    f.close()
        for name in ("ttyd.pid", "service.pid", "bus.pid", "web-supervisor.pid", "bus-supervisor.pid"):
            for base in (self.fake, self.run_dir):
                s = read(os.path.join(base, name)).strip()
                if s.isdigit() and alive(int(s)):
                    os.kill(int(s), signal.SIGKILL)

    def run_to_exit(self, **extra):
        p = self.start(**extra)
        out, err = p.communicate(timeout=60)
        return p.returncode, out, err

    def run_ready(self, **extra):
        """Start serve, wait for the readiness marker, return the process."""
        p = self.start(**extra)
        ok = wait_for(lambda: os.path.exists(os.path.join(self.run_dir, "ready")) or p.poll() is not None, 15)
        self.assertTrue(ok and p.poll() is None, "serve did not become ready: rc=%s %s" % (p.poll(), p.stderr.read() if p.poll() is not None else ""))
        return p

    def marker(self):
        return read(os.path.join(self.run_dir, "ready")).strip()

    def calls(self):
        return read(os.path.join(self.fake, "calls.log")).splitlines()

    def health_lines(self):
        return [l for l in read(self.health).splitlines() if l.strip()]

    def serve_log(self):
        return read(os.path.join(self.state, "serve.log"))

    def fresh(self):
        """Forget the state of the serve that ran before, for a test that starts serve more than once (stop it first)."""
        for name in os.listdir(self.fake):
            if name.endswith((".exit", ".mode", ".noanswer", ".starts", ".pid", ".log", ".seen")):
                os.unlink(os.path.join(self.fake, name))
        shutil.rmtree(self.run_dir, ignore_errors=True)
        shutil.rmtree(os.path.join(self.home, ".local"), ignore_errors=True)

    def stop(self, p, sig=signal.SIGTERM):
        os.kill(p.pid, sig)
        p.wait(timeout=60)
        return p.returncode


