#!/usr/bin/env python3
"""End-to-end run of the install line, the first call, joining, stop, update and reset against a LOCAL registry
(design 3.1, 3.8 "Update flow", 13.3; plan Phase 3, slice 3.6; closes B20 against registry:2 with a placeholder organization).

What it does, in order (every step prints `STEP <id> PASS|FAIL|SKIP <title>`):
  1. pulls docker.io/library/registry:2 once when it is absent, starts it in a throwaway container named
     swarmbox-test-3-registry-<rand>, published on 127.0.0.1 only, on a random port 20000-40000, with a named volume;
  2. builds (or reuses) the 2.0 image once (dev/dev-build.sh, the APT override only in a scratch copy) and derives from it, with
     a one-layer scratch Containerfile that rewrites the helper's VERSION, the versions 2.0.1 and 2.1.0 (the builds of the other
     versions are layers on the first one: the registry gets three different images); pushes
     localhost:<port>/<placeholder-org>/swarmbox:2.0.0 and :2.0 first, :2.0.1 (and the moving :2.0 moved to it) and :2.1.0 later;
  3. for each shell (bash, zsh, fish) in a world of its own (mktemp HOME, XDG folders, workspace, helper folder, box name
     swarmbox-test-3-<shell>-<rand>): the documented install line of design 3.1 (the registry and --image substituted) into a temp
     rc file; the first `swarmbox` call; a second call joining the same box; two terminals started at once (one container); a
     real terminal pair sharing the tmux session; stop and start; `update`; the next call keeping the new helper; `update`
     with the registry stopped (exit 3, nothing changed); `reset` offline (no pull in the recorded Podman calls); `update --to`
     for a lower and a higher tag; an invalid tag; the removal of the world.
At every step the live box is checked: `tmux ls` and the containers that are not swarmbox-test-* must not change. A finally block
removes by EXACT name only what this run created: the registry container and its volume, the boxes and their volumes, the
derived images, the images tagged localhost:<port>/..., the base image (only when this run built it) and registry:2 (only when
this run pulled it).

All of it is REDUCED in the same way as tests/smoke_image.py: the development box is itself a container, so the boxes start with the
test-only switch SWARMBOX_TEST_NO_NESTED=1 (no nested Podman in the box). Nothing is run on macOS or arm64, and the real registry
(ghcr.io) is a Phase 7 check.

Opt-in: nothing runs unless SWARMBOX_E2E=1. SWARMBOX_E2E_IMAGE=<swarmbox-test-...> reuses a built image (not removed);
SWARMBOX_E2E_SHELLS=bash,zsh,fish limits the shells; SWARMBOX_E2E_KEEP_REGISTRY_IMAGE=1 keeps registry:2.
Run: SWARMBOX_E2E=1 python3 tests/e2e_registry.py       (about 10 to 20 minutes: run it in the background)
"""
import json
import os
import pty
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
from helpers import DEFAULT_IMAGE_REPO  # noqa: E402
from smoke_image import exact_name, free_port, rnd, wait_for  # noqa: E402

REGISTRY_IMAGE = "docker.io/library/registry:2"
ORG = "placeholder-org"
REDUCED = "[reduced: development box, no nested Podman in the box]"
UPDATED = "updated to %s; run `swarmbox reset` to use it (running sessions end)\n"
SKEW = "the helper (%s) is newer than this function (%s); kept"
SHELL_PATHS = {"bash": "/bin/bash", "zsh": "/usr/bin/zsh", "fish": "/usr/bin/fish"}


def sh(*args, env=None, timeout=600, **kw):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, env=env, **kw)


def podman(*args, env=None, timeout=900):
    return sh("podman", *args, env=env, timeout=timeout)


def out(r):
    return (r.stdout + r.stderr).strip()


def design_install_line():
    """The first install line of design 3.1 that appends to ~/.bashrc with `--with claude` and no other option."""
    with open(os.path.join(ROOT, "docs", "design.md")) as f:
        text = f.read()
    for ln in text.splitlines():
        if re.match(r"^podman run --rm -e SHELL ghcr\.io/<org>/swarmbox:\d+\.\d+\.\d+ init --with claude >> ~/\.bashrc\s*$", ln):
            return ln.strip()
    raise AssertionError("design 3.1 has no install line of the expected form")


class Live:
    """What must not change: the live tmux sessions (names) and the containers that are not swarmbox-test-*."""

    @staticmethod
    def snapshot():
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        t = sh("tmux", "ls", env=env)
        sessions = sorted(ln.split(":")[0] for ln in t.stdout.splitlines() if ":" in ln)
        names = sorted(n for n in podman("ps", "-a", "--format", "{{.Names}}").stdout.split() if not n.startswith("swarmbox-test-"))
        return {"tmux": sessions, "containers": names}


class Run:
    def __init__(self):
        self.r = rnd()
        self.results = []
        self.live0 = Live.snapshot()
        self.root = tempfile.mkdtemp(prefix="swarmbox-e2e-")
        self.containers, self.volumes, self.images = [], [], []
        self.pulled_registry = False
        self.built_base = False
        self.base = None
        self.port = None
        self.reg_name = exact_name("swarmbox-test-3-registry-%s" % self.r)
        self.published = set()
        self.repo = None
        self.real_podman = shutil.which("podman")
        self.version = open(os.path.join(ROOT, "container", "host", "VERSION")).read().strip()

    # -- reporting -------------------------------------------------------------------------------------------------

    def step(self, sid, title, fn, *a):
        t0 = time.time()
        try:
            note = fn(*a)
            status, extra = "PASS", note or REDUCED
        except Exception as e:  # noqa: BLE001 - every failure is a step failure, the run goes on to the cleanup
            status, extra = "FAIL", "%s: %s" % (type(e).__name__, str(e)[-900:].replace("\n", " | "))
        live = Live.snapshot()
        if live != self.live0:
            status, extra = "FAIL", "the live box changed: before %r, now %r. %s" % (self.live0, live, extra)
        self.results.append((sid, status, title))
        print("STEP %s %s %s (%.0f s) %s" % (sid, status, title, time.time() - t0, extra), flush=True)
        sys.stdout.flush()
        return status == "PASS"

    def skip(self, sid, title, why):
        self.results.append((sid, "SKIP", title))
        print("STEP %s SKIP %s %s" % (sid, title, why), flush=True)

    # -- the registry ----------------------------------------------------------------------------------------------

    def registry_up(self):
        if podman("image", "exists", REGISTRY_IMAGE).returncode != 0:
            r = podman("pull", "-q", REGISTRY_IMAGE)
            assert r.returncode == 0, "cannot pull %s: %s" % (REGISTRY_IMAGE, out(r))
            self.pulled_registry = True
        self.port = free_port()
        vol = exact_name(self.reg_name + "-data")
        self.volumes.append(vol)
        assert podman("volume", "create", vol).returncode == 0
        self.containers.append(self.reg_name)
        r = podman("run", "-d", "--name", self.reg_name, "-v", "%s:/var/lib/registry" % vol, "-p", "127.0.0.1:%d:5000" % self.port,
                   REGISTRY_IMAGE)
        assert r.returncode == 0, out(r)
        self.wait_registry()
        ports = podman("container", "inspect", "--format", "{{json .NetworkSettings.Ports}}", self.reg_name).stdout
        assert '"HostIp":"127.0.0.1"' in ports.replace(" ", "") and "0.0.0.0" not in ports, "registry binding: " + ports
        self.repo = "localhost:%d/%s/swarmbox" % (self.port, ORG)
        return "registry:2 on 127.0.0.1:%d (published on 127.0.0.1 only) %s" % (self.port, REDUCED)

    def wait_registry(self, up=True):
        def ping():
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/v2/" % self.port, timeout=2) as resp:
                    return resp.status == 200
            except Exception:  # noqa: BLE001
                return False
        if up:
            assert wait_for(ping, 60, 0.5), "the registry did not answer: " + podman("logs", "--tail", "5", self.reg_name).stderr[-300:]
        else:
            assert wait_for(lambda: not ping(), 30, 0.5), "the registry still answers"

    def registry_stop(self):
        r = podman("stop", "-t", "2", self.reg_name)
        assert r.returncode == 0, out(r)
        self.wait_registry(up=False)

    def registry_start(self):
        r = podman("start", self.reg_name)
        assert r.returncode == 0, out(r)
        self.wait_registry()

    def catalog(self):
        with urllib.request.urlopen("http://127.0.0.1:%d/v2/%s/swarmbox/tags/list" % (self.port, ORG), timeout=5) as resp:
            return json.load(resp)["tags"]

    # -- the images ------------------------------------------------------------------------------------------------

    def storage_conf(self):
        """A storage.conf for the scratch XDG_CONFIG_HOME that points at the REAL image store (the helper's own data
        folder is scratch, so Podman's default store would otherwise follow XDG_DATA_HOME and start empty on overlayfs)."""
        info = json.loads(podman("info", "--format", "json").stdout)
        st = info["store"]
        lines = ["[storage]", 'driver = "%s"' % st["graphDriverName"], 'graphroot = "%s"' % st["graphRoot"],
                 'runroot = "%s"' % st["runRoot"], "", "[storage.options.%s]" % st["graphDriverName"]]
        for k, v in sorted((st.get("graphOptions") or {}).items()):
            key = k.split(".", 1)[1] if "." in k else k
            lines.append('%s = "%s"' % (key, v))
        return "\n".join(lines) + "\n"

    def build_images(self):
        tag = os.environ.get("SWARMBOX_E2E_IMAGE")
        if tag:
            assert podman("image", "exists", tag).returncode == 0, "SWARMBOX_E2E_IMAGE %s does not exist" % tag
            self.base = tag
        else:
            self.base = exact_name("swarmbox-test-3-e2e-img-%s" % self.r)
            self.images.append(self.base)
            self.built_base = True
            r = sh("sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", self.base, timeout=3000)
            assert r.returncode == 0, out(r)[-800:]
        self.local = {}
        for v in ("2.0.0", "2.0.1", "2.1.0"):
            if v == self.version:
                self.local[v] = self.base
                continue
            name = exact_name("swarmbox-test-3-e2e-v%s-%s" % (v.replace(".", ""), self.r))
            ctx = tempfile.mkdtemp(prefix="swarmbox-e2e-ctx-")
            try:
                with open(os.path.join(ctx, "Containerfile"), "w") as f:
                    f.write("FROM %s\nUSER root\nRUN echo %s > /usr/local/share/swarmbox/host/VERSION\nUSER agent\n" % (self.base, v))
                self.images.append(name)
                r = podman("build", "-q", "-t", name, "-f", os.path.join(ctx, "Containerfile"), ctx)
                assert r.returncode == 0, out(r)[-800:]
            finally:
                shutil.rmtree(ctx, ignore_errors=True)
            self.local[v] = name
        return "base %s, versions %s %s" % (self.base, sorted(self.local), REDUCED)

    def push(self, version, *tags):
        env = self.podman_env()
        for t in tags:
            ref = "%s:%s" % (self.repo, t)
            self.images.append(ref)
            assert podman("tag", self.local[version], ref, env=env).returncode == 0
            r = podman("push", "-q", ref, env=env)
            assert r.returncode == 0, "push %s: %s" % (ref, out(r))
        self.published.update(tags)

    def untag_local(self, *tags):
        for t in tags:
            podman("rmi", "%s:%s" % (self.repo, t))

    def podman_env(self):
        e = dict(os.environ)
        e["CONTAINERS_REGISTRIES_CONF"] = self.registries_conf()
        return e

    def registries_conf(self):
        p = os.path.join(self.root, "registries.conf")
        with open(p, "w") as f:
            f.write('[[registry]]\nlocation = "localhost:%d"\ninsecure = true\n' % self.port)
        return p

    def publish_series(self):
        # the first build: 2.0.0, and the moving 2.0 pointing at it
        self.push("2.0.0", "2.0.0", "2.0")
        self.untag_local("2.0", "2.0.0")
        self.push("2.1.0", "2.1.0")
        self.untag_local("2.1.0")
        assert {"2.0.0", "2.0", "2.1.0"} <= set(self.catalog()), self.catalog()
        return "tags %s %s" % (sorted(self.catalog()), REDUCED)

    def publish_next(self):
        """The newer build of the series: 2.0.1, and the moving 2.0 moved to it."""
        self.push("2.0.1", "2.0.1", "2.0")
        self.untag_local("2.0", "2.0.1")
        assert "2.0.1" in self.catalog()

    # -- teardown --------------------------------------------------------------------------------------------------

    def cleanup(self):
        for c in self.containers:
            podman("rm", "-f", "-t", "0", exact_name(c))
        for v in self.volumes:
            podman("volume", "rm", "-f", exact_name(v))
        for i in reversed(self.images):
            if i.startswith("localhost:%s/" % self.port) or i.startswith("swarmbox-test-"):
                podman("rmi", "-f", i)
        if self.pulled_registry and os.environ.get("SWARMBOX_E2E_KEEP_REGISTRY_IMAGE") != "1":
            podman("rmi", REGISTRY_IMAGE)
        shutil.rmtree(self.root, ignore_errors=True)

    def leftovers(self):
        left = []
        for kind in (("ps", "-a", "--format", "{{.Names}}"), ("volume", "ls", "--format", "{{.Name}}"),
                     ("images", "--format", "{{.Repository}}:{{.Tag}}")):
            for n in podman(*kind).stdout.split():
                if n.startswith("swarmbox-test-3-e2e") or n.startswith("swarmbox-test-3-registry-%s" % self.r) or \
                        n.startswith("localhost:%s/" % self.port) or (n.startswith("swarmbox-test-3-") and self.r in n):
                    left.append(n)
        return left


class PtyRun:
    """A command with a real terminal on stdin and stdout (the function only passes -t then, 3.3)."""

    def __init__(self, argv, env, cwd):
        master, slave = pty.openpty()
        self.p = subprocess.Popen(argv, env=env, cwd=cwd, stdin=slave, stdout=slave, stderr=subprocess.PIPE)
        os.close(slave)
        self.master = master
        self.buf = b""
        self.t = threading.Thread(target=self._drain, daemon=True)
        self.t.start()

    def _drain(self):
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                break
            if not chunk:
                break
            self.buf += chunk

    def wait(self, timeout=120):
        rc = self.p.wait(timeout=timeout)
        self.t.join(5)
        err = self.p.stderr.read().decode()
        self.p.stderr.close()
        os.close(self.master)
        return rc, self.buf.decode(errors="replace"), err


class World:
    """One shell, one box, one scratch HOME. Everything the function and the helper write lives under self.root."""

    def __init__(self, run, shell):
        self.run, self.shell = run, shell
        self.root = tempfile.mkdtemp(prefix="swarmbox-e2e-%s-" % shell, dir=run.root)
        self.home = os.path.join(self.root, "home")
        self.ws = os.path.join(self.root, "ws")
        self.cfg = os.path.join(self.root, "cfg")
        self.data = os.path.join(self.root, "data")
        self.state = os.path.join(self.root, "state")
        self.bindir = os.path.join(self.root, "bin")
        for d in (self.home, self.ws, os.path.join(self.cfg, "containers"), self.data, self.state, self.bindir):
            os.makedirs(d)
        with open(os.path.join(self.cfg, "containers", "storage.conf"), "w") as f:
            f.write(run.storage_conf())
        if os.path.exists("/etc/containers/containers.conf"):
            shutil.copy("/etc/containers/containers.conf", os.path.join(self.cfg, "containers", "containers.conf"))
        self.log = os.path.join(self.root, "podman-calls.log")
        open(self.log, "w").close()
        with open(os.path.join(self.bindir, "podman"), "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"$*\" >> %s\nexec %s \"$@\"\n" % (shlex.quote(self.log), shlex.quote(run.real_podman)))
        os.chmod(os.path.join(self.bindir, "podman"), 0o755)
        self.box = exact_name("swarmbox-test-3-%s-%s" % (shell, run.r))
        run.containers.append(self.box)
        run.volumes.append(exact_name(self.box + "-containers"))
        self.web_port = free_port()
        self.rc = os.path.join(self.root, "rc.%s" % shell)
        self.cwd = os.path.join(self.root, "cwd")
        os.makedirs(self.cwd)

    # the environment of everything that runs as "the user's shell"
    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_", "TMUX"))}
        e["PATH"] = self.bindir + os.pathsep + e.get("PATH", "")
        e.update({"HOME": self.home, "XDG_CONFIG_HOME": self.cfg, "XDG_DATA_HOME": self.data, "XDG_STATE_HOME": self.state,
                  "CONTAINERS_REGISTRIES_CONF": self.run.registries_conf(), "SHELL": SHELL_PATHS[self.shell], "TERM": "dumb",
                  "LC_ALL": "C", "SWARMBOX_NAME": self.box, "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_WEB_PORT": str(self.web_port),
                  "SWARMBOX_INIT": "auto", "SWARMBOX_TEST_NO_NESTED": "1"})
        e.update(extra)
        return e

    def argv(self, *args):
        if self.shell == "bash":
            return ["bash", "--noprofile", "--norc", "-c", '. "$1"; shift; swarmbox "$@"; exit $?', "bash", self.rc, *args]
        if self.shell == "zsh":
            return ["zsh", "-f", "-c", '. "$1"; shift; swarmbox "$@"; exit $?', "zsh", self.rc, *args]
        return ["fish", "--no-config", "-c", "set -l f $argv[1]; set -e argv[1]; source $f; swarmbox $argv; exit $status", self.rc, *args]

    def call(self, *args, timeout=400, **extra):
        return subprocess.run(self.argv(*args), env=self.env(**extra), cwd=self.cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def popen(self, *args):
        return subprocess.Popen(self.argv(*args), env=self.env(), cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True)

    def pty(self, *args):
        return PtyRun(self.argv(*args), self.env(), self.cwd)

    # facts about the box, from the real Podman (the same store)
    def fmt(self, template, name=None):
        r = podman("container", "inspect", "--format", template, name or self.box)
        return r.stdout.strip() if r.returncode == 0 else ""

    def cid(self):
        return self.fmt("{{.ID}}")

    def label(self, key="swarmbox.image"):
        return self.fmt('{{index .Config.Labels "%s"}}' % key)

    def status(self):
        return self.fmt("{{.State.Status}}")

    def count(self):
        r = podman("ps", "-a", "--filter", "name=^%s$" % self.box, "--format", "{{.Names}}")
        return len(r.stdout.split())

    def calls(self):
        with open(self.log) as f:
            return [ln.rstrip("\n") for ln in f if ln.strip()]

    def mark(self):
        return len(self.calls())

    def helper_version(self):
        p = os.path.join(self.data, "swarmbox", "host", "VERSION")
        with open(p) as f:
            return f.read().strip()

    def config_image(self):
        r = self.call("config", "get", "IMAGE")
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def remove_box(self):
        podman("rm", "-f", "-t", "0", self.box)


def ok(r, what=""):
    assert r.returncode == 0, "%s exited %d: %s" % (what, r.returncode, out(r)[-700:])


def scenario(run, shell):
    w = World(run, shell)
    repo = run.repo
    ref = lambda t: "%s:%s" % (repo, t)  # noqa: E731
    rid = "%s-" % shell
    tag = REDUCED

    def install():
        line = design_install_line()
        run.untag_local("2.0", "2.0.0", "2.0.1", "2.1.0")   # an earlier shell's world pulled them; this one must pull again
        assert podman("image", "exists", ref("2.0.0")).returncode != 0, "the image is already local: the first call would not pull"
        assert (DEFAULT_IMAGE_REPO + ":2.0.0") in line
        cmd = line.replace(DEFAULT_IMAGE_REPO, repo).replace(">> ~/.bashrc", "--image %s >> %s" % (ref("2.0.0"), shlex.quote(w.rc)))
        r = subprocess.run(["sh", "-c", cmd], env=w.env(), capture_output=True, text=True, timeout=600)
        ok(r, "the install line")
        with open(w.rc) as f:
            text = f.read()
        assert "# >>> swarmbox 2.0.0 >>>" in text and "# <<< swarmbox 2.0.0 <<<" in text, text[:300]
        assert ref("2.0.0") in text, "the seed image is not in the block"
        assert not os.path.exists(os.path.join(w.data, "swarmbox")), "init wrote to the data folder"
        assert not os.path.exists(os.path.join(w.cfg, "swarmbox")), "init wrote to the config folder"
        if shell == "fish":
            assert "function swarmbox" in text
        elif shell == "zsh":
            assert "swarmbox()" in text or "function swarmbox" in text
        return "line: %s %s" % (cmd.split(">>")[0].strip().replace(repo, "<registry>"), tag)

    def first_call():
        r = w.call("echo", "first-call-" + shell)
        ok(r, "the first call")
        assert r.stdout.strip() == "first-call-" + shell, (r.stdout, r.stderr)
        assert w.status() == "running" and w.count() == 1
        assert w.label() == ref("2.0.0"), w.label()
        assert w.label("swarmbox.managed") == "2"
        assert w.helper_version() == "2.0.0"
        assert w.config_image() == ref("2.0.0")
        pulls = [c for c in w.calls() if c.startswith("run ") and c.endswith("host-helper")]
        assert pulls and ref("2.0.0") in pulls[0], "the function did not extract the helper from the registry image: %r" % w.calls()[:5]
        assert podman("image", "exists", ref("2.0.0")).returncode == 0, "the image was not pulled from the registry"
        ports = w.fmt("{{json .NetworkSettings.Ports}}")
        assert "0.0.0.0" not in ports, ports
        w.cid0 = w.cid()
        with open(os.path.join(w.ws, "survives"), "w") as f:
            f.write("x")
        return "box %s created from %s, helper extracted by the function %s" % (w.box, ref("2.0.0"), tag)

    def second_call_joins():
        m = w.mark()
        t0 = time.time()
        r = w.call("echo", "second-" + shell)
        dt = time.time() - t0
        ok(r, "the second call")
        assert r.stdout.strip() == "second-" + shell
        assert w.cid() == w.cid0 and w.count() == 1, "the second call made another box"
        made = w.calls()[m:]
        plain = [c for c in made if not c.startswith("system connection ")]
        before_exec = [c for i, c in enumerate(plain) if not any(x.startswith("exec ") for x in plain[:i + 1])]
        assert len(before_exec) <= 2, "fast path: %r" % (made,)
        assert not any(c.startswith(("run ", "start ", "rm ", "pull ")) for c in made), made
        return "same container; %d podman call(s) before the exec, %.2f s in all %s (B35)" % (len(before_exec), dt, tag)

    def two_at_once():
        w.remove_box()
        assert w.count() == 0
        a, b = w.popen("echo", "A-" + shell), w.popen("echo", "B-" + shell)
        oa, ob = a.communicate(timeout=400), b.communicate(timeout=400)
        assert a.returncode == 0 and b.returncode == 0, (oa, ob, a.returncode, b.returncode)
        assert oa[0].strip() == "A-" + shell and ob[0].strip() == "B-" + shell, (oa, ob)
        assert w.count() == 1, "two terminals made %d boxes" % w.count()
        assert podman("ps", "-a", "--filter", "name=^swarmbox-test-3-%s-%s" % (shell, run.r), "--format", "{{.Names}}").stdout.split() == [w.box]
        w.cid0 = w.cid()
        return "exactly one container (%s) %s" % (w.box, tag)

    def terminals_share_a_session():
        t1 = w.pty("sleep", "14")

        def windows():
            r = podman("exec", w.box, "tmux", "list-windows", "-t", "=main", "-F", "#{window_name}")
            return [x for x in r.stdout.split() if x and x != "idle"]
        try:
            assert wait_for(lambda: len(windows()) >= 1, 30), "the first terminal has no window"
            t2 = w.pty("sleep", "10")
            assert wait_for(lambda: len(windows()) >= 2, 30), "the second terminal did not join the session: %r" % windows()
            assert w.cid() == w.cid0 and w.count() == 1
        finally:
            r2 = t2.wait(60) if "t2" in locals() else (0, "", "")
            r1 = t1.wait(60)
        assert r1[0] == 0 and r2[0] == 0, (r1, r2)
        return "two real terminals, two windows of the session main in one box %s" % tag

    def stop_and_start():
        r = w.call("stop")
        ok(r, "stop")
        assert w.status() in ("exited", "stopped"), w.status()
        assert w.cid() == w.cid0, "stop removed the box"
        r = w.call("echo", "after-stop-" + shell)
        ok(r, "the call after stop")
        assert r.stdout.strip() == "after-stop-" + shell and w.status() == "running" and w.cid() == w.cid0
        return "same container started again %s" % tag

    def update_step():
        run.untag_local("2.0", "2.0.1", "2.1.0")
        assert podman("image", "exists", ref("2.0.1")).returncode != 0, "a local 2.0.1 exists before the update"
        before_cid = w.cid()
        m = w.mark()
        r = w.call("update")
        ok(r, "update")
        assert r.stdout == UPDATED % "2.0.1", (r.stdout, r.stderr)
        assert podman("image", "exists", ref("2.0.1")).returncode == 0, "the local X.Y.Z tag was not made"
        i1 = podman("image", "inspect", "--format", "{{.Id}}", ref("2.0.1")).stdout.strip()
        i2 = podman("image", "inspect", "--format", "{{.Id}}", ref("2.0")).stdout.strip()
        assert i1 and i1 == i2, "the exact tag is not the series tag's image"
        made = w.calls()[m:]
        assert any(c.startswith("pull") and c.endswith(ref("2.0")) for c in made), made
        assert any(c.startswith("tag ") and c.endswith(ref("2.0.1")) for c in made), made
        assert not any(c.startswith(("rm ", "stop ", "start ", "kill ")) for c in made), made
        assert w.config_image() == ref("2.0.1")
        assert w.helper_version() == "2.0.1"
        assert w.cid() == before_cid and w.status() == "running" and w.label() == ref("2.0.0"), "update touched the box"
        return "pulled %s, tagged %s, IMAGE written, box untouched %s" % (ref("2.0"), ref("2.0.1"), tag)

    def next_call_keeps_helper():
        m = w.mark()
        r = w.call("version")
        ok(r, "version")
        assert r.stdout.strip() == "2.0.1", r.stdout
        assert SKEW % ("2.0.1", "2.0.0") in r.stderr, r.stderr
        r = w.call("echo", "x")
        ok(r, "echo")
        assert r.stdout.strip() == "x"
        assert "this box was created from %s; the config asks for %s; run `swarmbox reset`" % (ref("2.0.0"), ref("2.0.1")) in r.stderr, r.stderr
        assert not any(c.startswith("run ") and c.endswith("host-helper") for c in w.calls()[m:]), "the function extracted again"
        assert w.helper_version() == "2.0.1"
        return "helper 2.0.1 kept, skew notice and the reset hint shown %s" % tag

    def offline():
        run.registry_stop()
        try:
            before = (w.config_image(), w.helper_version(), w.cid())
            r = w.call("update")
            assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
            assert "cannot pull %s" % ref("2.0") in r.stderr, r.stderr
            assert (w.config_image(), w.helper_version(), w.cid()) == before, "a failed update changed something"
            m = w.mark()
            r = w.call("reset")
            ok(r, "reset offline")
            made = w.calls()[m:]
            assert not any(c.startswith("pull") for c in made), made
            assert w.cid() != before[2] and w.label() == ref("2.0.1"), (w.label(), made)
            assert os.path.exists(os.path.join(w.ws, "survives")), "the workspace changed"
            r = w.call("echo", "offline-" + shell)
            ok(r, "call after the offline reset")
            assert r.stdout.strip() == "offline-" + shell and not r.stderr.strip().count("run `swarmbox reset`"), r.stderr
        finally:
            run.registry_start()
        return "registry stopped: update exit 3 with nothing changed, reset exit 0 with no pull, box now %s %s" % (ref("2.0.1"), tag)

    def update_to():
        r = w.call("update", "--to", "2.0.0")
        ok(r, "update --to 2.0.0")
        assert r.stdout == UPDATED % "2.0.0", (r.stdout, r.stderr)
        assert w.config_image() == ref("2.0.0") and w.helper_version() == "2.0.0"
        r = w.call("echo", "rb")
        ok(r)
        assert "this box was created from %s; the config asks for %s" % (ref("2.0.1"), ref("2.0.0")) in r.stderr, r.stderr
        r = w.call("update", "--to", "2.1.0")
        ok(r, "update --to 2.1.0")
        assert r.stdout == UPDATED % "2.1.0", (r.stdout, r.stderr)
        assert w.config_image() == ref("2.1.0") and w.helper_version() == "2.1.0"
        r = w.call("version")
        assert r.stdout.strip() == "2.1.0" and SKEW % ("2.1.0", "2.0.0") in r.stderr, (r.stdout, r.stderr)
        before = (w.config_image(), w.helper_version())
        r = w.call("update", "--to", "bad tag")
        assert r.returncode == 2 and (w.config_image(), w.helper_version()) == before, (r.returncode, r.stderr)
        r = w.call("update", "--to", "9.9.9")
        assert r.returncode == 3 and (w.config_image(), w.helper_version()) == before, (r.returncode, r.stderr)
        r = w.call("reset")
        ok(r, "reset to 2.1.0")
        assert w.label() == ref("2.1.0"), w.label()
        r = w.call("update", "--to", "2.0.0")
        ok(r)
        assert w.label() == ref("2.1.0"), "update touched the box"
        return "--to lower (2.0.0), higher in another series (2.1.0), invalid (exit 2), absent tag (exit 3); reset applied 2.1.0 %s" % tag

    def teardown():
        w.remove_box()
        podman("volume", "rm", "-f", w.box + "-containers")
        assert w.count() == 0
        assert podman("volume", "inspect", w.box + "-containers").returncode != 0
        return "world removed %s" % tag

    steps = [("install", "the documented install line (init output into a temp rc file)", install),
             ("first", "the first `swarmbox` call creates the box", first_call),
             ("join", "a second call joins the same box (fast path)", second_call_joins),
             ("race", "two terminals started at once create one box", two_at_once),
             ("tty", "two real terminals share the tmux session of one box", terminals_share_a_session),
             ("stop", "stop, then the next call starts the same box", stop_and_start),
             ("publish", "a newer build of the series is published (2.0.1, and the moving 2.0 moves)",
              lambda: None if "2.0.1" in run.published else (run.publish_next(), "tags %s %s" % (sorted(run.catalog()), tag))[1]),
             ("update", "update pulls the series tag, tags X.Y.Z, writes IMAGE, leaves the box", update_step),
             ("next", "the next call keeps the updated helper (D33)", next_call_keeps_helper),
             ("offline", "update fails cleanly and reset works with the registry stopped", offline),
             ("to", "update --to: lower, higher, invalid and absent tags", update_to),
             ("teardown", "stop and remove the world", teardown)]
    all_ok = True
    for sid, title, fn in steps:
        if not all_ok and sid != "teardown":
            run.skip("%s%s" % (rid, sid), title, "(an earlier step of this shell failed)")
            continue
        if not run.step("%s%s" % (rid, sid), title, fn):
            all_ok = False
    if not all_ok:
        w.remove_box()


def main():
    if os.environ.get("SWARMBOX_E2E") != "1":
        print("SKIP the registry end-to-end run is opt-in: set SWARMBOX_E2E=1")
        return 0
    run = Run()
    shells = [s for s in (os.environ.get("SWARMBOX_E2E_SHELLS") or "bash,zsh,fish").split(",") if s]
    try:
        if not run.step("registry", "registry:2 in a throwaway container on 127.0.0.1", run.registry_up):
            print("SUMMARY registry:2 could not be started; the fake-registry reduced run is tests/test_host_update.py")
            return 1
        if run.step("images", "build the 2.0 image once and derive 2.0.1 and 2.1.0", run.build_images):
            run.step("publish", "push 2.0.0, 2.0 and 2.1.0 to the registry", run.publish_series)
            for s in shells:
                if shutil.which(s) is None:
                    run.skip("%s-all" % s, "the scenario in %s" % s, "(%s is not installed)" % s)
                    continue
                scenario(run, s)
    finally:
        run.cleanup()
        left = run.leftovers()
        live = Live.snapshot()
        run.results.append(("cleanup", "PASS" if not left and live == run.live0 else "FAIL", "cleanup"))
        print("STEP cleanup %s nothing of this run remains (%s), the live box is unchanged (%s)"
              % (run.results[-1][1], left or "none", live == run.live0), flush=True)
    failed = [r for r in run.results if r[1] == "FAIL"]
    print("SUMMARY %d passed, %d failed, %d skipped" % (sum(r[1] == "PASS" for r in run.results), len(failed),
                                                       sum(r[1] == "SKIP" for r in run.results)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
