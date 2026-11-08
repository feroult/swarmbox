#!/usr/bin/env python3
"""Image smoke test (design 13.3 layer 2; plan section 4, slice 2.7).

Builds (or reuses) the image and checks it in throwaway containers: `serve` reaches readiness, `box:/tmp/swarmbox` is empty
after a stop and a start, the ttyd page is built, `swarmbox-tool validate` passes on the shipped manifests, the claude shim, index and tool-ports are there, two `attach` calls share one session, the
image holds no agent, the host helper's up, reset and stop work against a real throwaway box (slice 3.3), and (full mode only) a nested Podman runs a container.

Two modes:
  reduced (default once opted in)  for the development box, which is itself a container: the throwaway box starts with the
      test-only switch SWARMBOX_TEST_NO_NESTED=1, so there is no nested Podman and `serve` is ready with warnings. Every
      result is tagged [reduced: development box, no nested Podman in the box] and is never the full result.
  full (SWARMBOX_SMOKE_FULL=1)     for CI or the owner's host: the box gets the nested-Podman flags, readiness must be
      `ok`, and the nested steps run. Results are tagged [full]. The full result stays [unverified] until CI runs it.

Opt-in: nothing runs unless SWARMBOX_IMAGE_BUILD=1 or SWARMBOX_SMOKE_FULL=1 is set; every step is then reported SKIP.
SWARMBOX_SMOKE_ONLY=id,id runs only those steps (a development convenience).
SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image (and does not remove it); otherwise dev/dev-build.sh builds one,
removed at the end. Containers and volumes are swarmbox-test-smoke-<random>, removed by exact name; workspaces are mktemp
directories. No port is published. Output: one line per step, "STEP <id> PASS|FAIL|SKIP <title> <tag or reason>", then a
SMOKE summary line. Exit 1 only when a step failed.

Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/smoke_image.py            (reduced)
     SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py             (full: CI or the owner's host)
     python3 tests/smoke_image.py --list
"""
import os
import random
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

PREFIX = "swarmbox-test-"
REDUCED_TAG = "[reduced: development box, no nested Podman in the box]"
FULL_TAG = "[full]"
NESTED_IMAGE = "docker.io/library/debian:bookworm-slim"  # pulled by the nested Podman in full mode


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def exact_name(name):
    """Every container, volume and image this file creates or removes must start with swarmbox-test-."""
    assert name.startswith(PREFIX) and len(name) > len(PREFIX), "refusing a name without the %s prefix: %r" % (PREFIX, name)
    return name


def podman(*args, timeout=180, **kw):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout, **kw)


def rm_exact(name):
    return podman(*["rm", "-f", "-t", "0", exact_name(name)])


def rmi_exact(name):
    return podman(*["rmi", exact_name(name)])


def vol_rm_exact(name):
    return podman(*["volume", "rm", exact_name(name)])


def wait_for(fn, seconds=60, step=0.3):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


class Step:
    def __init__(self, id, title, needs_full, fn):
        self.id, self.title, self.needs_full, self.fn = id, title, needs_full, fn


class Ctx:
    """The image, the full/reduced mode and everything created (so the cleanup removes it by exact name)."""

    def __init__(self, tag, full):
        self.tag, self.full = tag, full
        self.containers, self.volumes, self.dirs = [], [], []
        # ttyd listens on a random high port of the throwaway box's OWN network namespace (loopback only, nothing published)
        self.port = random.randrange(20000, 40000)

    def box(self, *extra_env, init=False):
        name = exact_name("swarmbox-test-smoke-" + rnd())
        ws = tempfile.mkdtemp(prefix="smoke-ws-")
        self.dirs.append(ws)
        args = ["run", "-d", "--name", name, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent",
                "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_WEB_PORT=%d" % self.port, "-e", "SWARMBOX_TEST_WEB_IFACE=lo"]
        if self.full:
            vol = exact_name(name + "-containers")
            self.volumes.append(vol)
            args += ["--device", "/dev/net/tun", "--security-opt", "unmask=/proc/*",
                     "-v", vol + ":/home/agent/.local/share/containers"]
        else:
            args += ["-e", "SWARMBOX_TEST_NO_NESTED=1"]
        for e in extra_env:
            args += ["-e", e]
        if init:
            args.append("--init")
        self.containers.append(name)
        r = podman(*args, self.tag)
        assert r.returncode == 0, "podman run failed: " + r.stderr
        return name

    def sh(self, name, cmd):
        return podman("exec", name, "sh", "-c", cmd).stdout.strip()

    def ready(self, name, seconds=90):
        return wait_for(lambda: self.sh(name, "cat /tmp/swarmbox/ready 2>/dev/null"), seconds)

    def http(self, name, code=False):
        flags = "-o /dev/null -w '%{http_code}'" if code else ""
        return self.sh(name, "curl -s %s http://127.0.0.1:%d/" % (flags, self.port))

    def state(self, name):
        return podman("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", name).stdout.strip()

    def logs(self, name):
        r = podman("logs", "--tail", "30", name)
        return r.stdout + r.stderr

    def cleanup(self):
        for n in self.containers:
            rm_exact(n)
        for v in self.volumes:
            vol_rm_exact(v)
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)
            if os.path.exists(d):   # a failed creation can leave folders that Podman made with other owners
                subprocess.run(["podman", "unshare", "rm", "-rf", d], capture_output=True)
        self.containers, self.volumes, self.dirs = [], [], []

    def expected_marker_ok(self, marker):
        if self.full:
            assert marker == "ok", "readiness marker is %r, expected ok\n%s" % (marker, "")
        else:
            assert marker.startswith("warnings="), "readiness marker is %r, expected warnings=<n> (no nested Podman)" % marker


# ---------------------------------------------------------------- steps

def step_ready(ctx):
    name = ctx.box()
    marker = ctx.ready(name)
    assert marker, "no readiness marker\n" + ctx.logs(name)
    ctx.expected_marker_ok(marker)
    cmd = ctx.sh(name, "tr '\\0' ' ' < /proc/1/cmdline")
    assert "swarmbox-entrypoint" in cmd and "serve" in cmd, "PID 1 is %r" % cmd
    assert "main:" in ctx.sh(name, "tmux ls"), "no tmux session main"
    assert ctx.sh(name, "id -un; id -u").split() == ["agent", "1000"], "user is not agent 1000"
    assert wait_for(lambda: ctx.http(name, code=True) == "200", 30), \
        "ttyd does not answer inside the box"   # the box's own network namespace, not this one


def step_tmpfs_restart(ctx):
    name = ctx.box()
    marker = ctx.ready(name)
    assert marker, "no readiness marker\n" + ctx.logs(name)
    ctx.sh(name, "echo x > /tmp/swarmbox/stale; echo y > /home/agent/keep.txt")
    t0 = time.time()
    r = podman("stop", "-t", "10", name, timeout=60)
    took = time.time() - t0
    assert r.returncode == 0, r.stderr
    assert took < 3.0, "podman stop -t 10 took %.2f s" % took
    assert ctx.state(name) == "exited 143", "state after stop: " + ctx.state(name)
    assert podman("start", name).returncode == 0
    assert ctx.ready(name), "no readiness marker after start\n" + ctx.logs(name)
    assert ctx.sh(name, "test -e /tmp/swarmbox/stale && echo STALE || echo gone") == "gone", "tmpfs was not emptied (B17)"
    assert ctx.sh(name, "cat /home/agent/keep.txt") == "y", "the workspace file did not survive"
    log = ctx.sh(name, "cat /home/agent/.local/state/swarmbox/serve.log")
    assert "received SIGTERM" in log, "serve.log has no SIGTERM line"


def step_page_built(ctx):
    built = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
                   "grep -o '__SWARMBOX_[A-Z_]*__' /usr/local/share/swarmbox/web/index.html | sort -u")
    assert built.stdout.split() == ["__SWARMBOX_CTRL_C__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_PADDING__"], \
        "the built page has no placeholders: " + built.stdout + built.stderr
    name = ctx.box()
    assert ctx.ready(name), ctx.logs(name)
    assert wait_for(lambda: ctx.http(name, code=True) == "200", 30)
    page = ctx.http(name)
    assert "__SWARMBOX_" not in page, "a placeholder is left in the served page"
    assert "--swarmbox-padding:" in page and "window.__swarmboxClipboard=" in page, "the served page is not the built page"


def step_tool_validate(ctx):
    r = podman("run", "--rm", "--entrypoint", "swarmbox-entrypoint", ctx.tag, "tool", "validate")
    out = r.stdout + r.stderr
    assert r.returncode == 0, "tool validate exited %d: %s" % (r.returncode, out)
    assert "manifest(s) checked" in out, "validate did not report what it checked (the real validate, slice 4a.1): " + out
    assert " 0 manifest" not in out, "validate checked no manifest: the image does not ship container/tools: " + out


def step_tool_shim(ctx):
    """The generated shim is a link to swarmbox-shim, the shim directory is on PATH, and nothing was installed (D2)."""
    r = podman("run", "--rm", "--entrypoint", "bash", ctx.tag, "-c",
               "readlink /usr/local/lib/swarmbox/shims/claude; test -x /usr/local/bin/swarmbox-shim && echo SHIM-EXEC; "
               "SWARMBOX_CMD=1 . /etc/swarmbox/bashrc.sh; command -v claude; ls -d ~/.local/share/swarmbox/tools/claude 2>&1; true")
    out = r.stdout
    assert out.splitlines()[:2] == ["/usr/local/bin/swarmbox-shim", "SHIM-EXEC"], "the shim is not a link to swarmbox-shim: " + out + r.stderr
    assert "/usr/local/lib/swarmbox/shims/claude" in out.splitlines()[2:3], "command -v claude does not find the shim: " + out
    assert "No such file" in out, "a claude tool directory exists before any call: " + out


def step_tool_index_ports(ctx):
    r = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
               "cat /usr/local/lib/swarmbox/index; echo ---; ls -l /usr/local/share/swarmbox/host/tool-ports; "
               "echo ---; wc -c < /usr/local/share/swarmbox/host/tool-ports")
    index, ports, size = r.stdout.split("---\n")
    assert "claude claude" in index.splitlines(), "the index lacks the line 'claude claude': " + r.stdout + r.stderr
    assert "tool-ports" in ports, "tool-ports is missing: " + r.stdout + r.stderr
    assert size.strip() == "0", "tool-ports is not empty (claude declares no PORTS): " + size


def step_attach_session(ctx):
    from test_attach_command import PtyProc, wait_until
    name = ctx.box("SWARMBOX_WEB=0")
    assert ctx.ready(name), ctx.logs(name)
    assert podman("exec", name, "swarmbox-entrypoint", "attach", "false").returncode == 1
    assert podman("exec", name, "swarmbox-entrypoint", "attach", "true").returncode == 0

    def windows():
        return [w for w in ctx.sh(name, "tmux list-windows -t =main -F '#{window_name}'").splitlines() if w]
    assert windows() == ["idle"], "windows before attach: %r" % windows()
    tabs = []
    try:
        for _ in range(2):
            p = PtyProc(["podman", "exec", "-it", name, "swarmbox-entrypoint", "attach"], dict(os.environ, TERM="xterm-256color"))
            tabs.append(p)
            want = 1 + len(tabs)
            assert wait_until(lambda: len(ctx.sh(name, "tmux list-sessions -F x").split()) == want, 30), p.out
        assert len(windows()) == 2 and "idle" not in windows(), "windows after two attaches: %r" % windows()
        assert set(ctx.sh(name, "tmux list-sessions -F '#{session_group}'").split()) == {"main"}, "not one shared session"
        for p in tabs:
            p.write(b"\x01d")   # the tmux detach key (prefix C-a, d)
            assert p.wait(30) == 0, p.out
    finally:
        for p in tabs:
            p.close()


def step_no_agent(ctx):
    r = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
               "for c in claude opencode gemini codex clasp gcloud go poetry; do p=$(command -v $c) && echo \"FOUND:$c:$p\"; done; true")
    # the claude SHIM is on PATH since slice 4a.5 (a link to swarmbox-shim); it is not the program
    found = [l for l in r.stdout.splitlines() if l.startswith("FOUND:")]
    assert found == ["FOUND:claude:/usr/local/lib/swarmbox/shims/claude"], "the neutral image holds a program it should not: " + r.stdout


def step_nested_podman(ctx):
    name = ctx.box()
    assert ctx.ready(name) == "ok", ctx.logs(name)
    r = podman("exec", name, "podman", "run", "--rm", NESTED_IMAGE, "echo", "nested-ok", timeout=600)
    assert r.returncode == 0 and "nested-ok" in r.stdout, "nested podman run failed: " + r.stdout + r.stderr


def step_nested_cgroup(ctx):
    """B28: informational. The image's settings (cgroupfs, file logger) run a nested container; the systemd manager does not.
    Fails only when the image's own settings fail; the systemd result is printed for the record."""
    name = ctx.box()
    assert ctx.ready(name) == "ok", ctx.logs(name)
    own = podman("exec", name, "podman", "info", "--format", "{{.Host.CgroupManager}} {{.Host.EventLogger}}")
    assert own.stdout.split() == ["cgroupfs", "file"], "the image's engine settings are %r" % own.stdout
    alt = podman("exec", name, "podman", "--cgroup-manager=systemd", "run", "--rm", NESTED_IMAGE, "true", timeout=600)
    print("    B28 systemd manager: exit %d %s" % (alt.returncode, (alt.stderr.strip().splitlines() or [""])[-1][:200]))


def free_port():
    """A random high port that is free on 127.0.0.1 now (never a well-known one)."""
    for _ in range(100):
        port = random.randrange(20000, 40000)
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    raise AssertionError("no free port found")


class HostSide:
    """The host helper (container/host/swarmbox-host) run against the real Podman, for one throwaway box.

    Everything is in a mktemp folder: the helper copy with an empty tool-ports, HOME (so the config, the state folder and
    the lock are there, never the real ones), the workspace, and a `podman` wrapper that only records the arguments of each
    call and then runs the real Podman (so the number of calls of a command is measured, not assumed)."""

    def __init__(self, ctx, name=None, port=None):
        self.ctx = ctx
        self.root = tempfile.mkdtemp(prefix="smoke-up-")
        ctx.dirs.append(self.root)
        hdir = os.path.join(self.root, "helper")
        os.makedirs(hdir)
        for f in ("swarmbox-host", "VERSION"):
            shutil.copy(os.path.join(ROOT, "container", "host", f), os.path.join(hdir, f))
        open(os.path.join(hdir, "tool-ports"), "w").close()
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        self.helper = os.path.join(hdir, "swarmbox-host")
        self.home = os.path.join(self.root, "home")
        self.ws = os.path.join(self.root, "ws")
        os.makedirs(self.home)
        os.makedirs(self.ws)
        self.bindir = os.path.join(self.root, "bin")
        os.makedirs(self.bindir)
        self.log = os.path.join(self.root, "podman-calls.log")
        open(self.log, "w").close()
        real = shutil.which("podman")
        with open(os.path.join(self.bindir, "podman"), "w") as f:
            f.write("#!/bin/sh\nprintf '%%s\\n' \"$*\" >> '%s'\nexec '%s' \"$@\"\n" % (self.log, real))
        os.chmod(os.path.join(self.bindir, "podman"), 0o755)
        self.name = exact_name(name or "swarmbox-test-3-" + rnd())
        self.port = port or free_port()
        ctx.containers.append(self.name)
        ctx.volumes.append(exact_name(self.name + "-containers"))

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_"))}
        e["PATH"] = self.bindir + os.pathsep + e.get("PATH", "")
        # HOME and the XDG state and config folders are scratch ones (the helper's config, lock and state go there), but Podman's
        # own image store stays where it is: a store in a scratch folder would sit on overlayfs inside this box and fail
        e["XDG_DATA_HOME"] = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        e.update({"HOME": self.home, "SWARMBOX_NAME": self.name, "SWARMBOX_WORKSPACE": self.ws,
                  "SWARMBOX_WEB_PORT": str(self.port), "SWARMBOX_IMAGE": self.ctx.tag, "SWARMBOX_INIT": "auto"})
        if not self.ctx.full:
            e["SWARMBOX_TEST_NO_NESTED"] = "1"   # no /dev/net/tun and no unmask flags: a third nesting level cannot honour them
        e.update(extra)
        return e

    def run(self, *args, timeout=240, **extra):
        return subprocess.run([self.helper, *args], env=self.env(**extra), capture_output=True, text=True, timeout=timeout,
                              input="")

    def calls(self):
        with open(self.log) as f:
            return [l.rstrip("\n") for l in f if l.strip()]

    def cid(self, name=None):
        return podman("container", "inspect", "--format", "{{.ID}}", name or self.name).stdout.strip()

    def fmt(self, template, name=None):
        return podman("container", "inspect", "--format", template, name or self.name).stdout.strip()


def step_up_lifecycle(ctx):
    """Slice 3.3 (design 3.7.2, 13.3 layers 2 and 5): the host helper's up, reset and stop against a real throwaway box."""
    hs = HostSide(ctx)
    marker = os.path.join(hs.ws, "survives-reset")
    # up creates the box and returns after readiness
    r = hs.run("up")
    assert r.returncode == 0, "up exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert r.stdout == "", "up wrote to standard output: %r" % r.stdout
    assert hs.fmt("{{.State.Status}}") == "running", "box is not running"
    assert hs.fmt('{{index .Config.Labels "swarmbox.managed"}}') == "2", "swarmbox.managed label missing"
    ready = ctx.sh(hs.name, "cat /tmp/swarmbox/ready")
    assert ready == "ok" or ready.startswith("warnings="), "marker %r" % ready
    cid1 = hs.cid()
    assert cid1
    with open(marker, "w") as f:
        f.write("x")
    # a second up takes the fast path: the calls are recorded by the wrapper (B35)
    before = len(hs.calls())
    t0 = time.time()
    r = hs.run("up")
    fast = time.time() - t0
    assert r.returncode == 0, "second up exited %d: %s" % (r.returncode, r.stderr[-800:])
    made = hs.calls()[before:]
    assert len(made) <= 2, "the fast path made %d podman calls: %r" % (len(made), made)
    assert not any(c.startswith(("run ", "start ", "rm ")) for c in made), made
    assert hs.cid() == cid1, "the second up replaced the box"
    t0 = time.time()
    podman("exec", hs.name, "true")
    base = time.time() - t0
    print("UP fast path: %d podman call(s) %r, %.2f s; one `podman exec ... true` takes %.2f s [measured here, reduced: development box]"
          % (len(made), [c.split(" ")[0] + " " + c.split(" ")[1] for c in made], fast, base))
    # url never touches podman
    before = len(hs.calls())
    r = hs.run("url")
    assert r.returncode == 0 and r.stdout.strip() == "http://127.0.0.1:%d" % hs.port, r.stdout
    assert len(hs.calls()) == before, "url called podman"
    # reset replaces the box, keeps the volume and the workspace
    r = hs.run("reset")
    assert r.returncode == 0, "reset exited %d: %s" % (r.returncode, r.stderr[-800:])
    cid2 = hs.cid()
    assert cid2 and cid2 != cid1, "reset did not replace the container"
    assert podman("volume", "inspect", hs.name + "-containers").returncode == 0, "the volume is gone after reset"
    assert os.path.exists(marker), "the workspace changed"
    assert ctx.sh(hs.name, "cat /tmp/swarmbox/ready"), "reset returned before the marker"
    # stop stops it; the next up starts the same container again and waits for the new marker
    r = hs.run("stop")
    assert r.returncode == 0, "stop exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert hs.fmt("{{.State.Status}}") in ("exited", "stopped"), hs.fmt("{{.State.Status}}")
    r = hs.run("up")
    assert r.returncode == 0, "up after stop exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert hs.fmt("{{.State.Status}}") == "running"
    assert hs.cid() == cid2, "up after stop made a new container"


def step_up_busy_port_and_foreign(ctx):
    """B33 and B18 with the real Podman: a creation that fails on a busy port leaves nothing of its own and exits 7; a
    container that already has the box's name (not made by SwarmBox 2.0) is refused with exit 5 and is still there."""
    hs = HostSide(ctx)
    busy = socket.socket()
    busy.bind(("127.0.0.1", hs.port))   # the box's WEB_PORT is taken by the test
    busy.listen(1)
    try:
        r = hs.run("up")
    finally:
        busy.close()
    assert r.returncode == 7, "up with a busy port exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert "could not create the box" in r.stderr and "already in use" in r.stderr, r.stderr[-800:]
    assert podman("container", "exists", hs.name).returncode != 0, "the partly created container was left behind"
    assert os.listdir(os.path.join(hs.home, ".local", "state", "swarmbox")) == [], "state files or the lock were left"
    # a foreign container with the box's name
    other = HostSide(ctx)
    c = podman("create", "--name", other.name, ctx.tag)
    assert c.returncode == 0, c.stderr
    r = other.run("up")
    assert r.returncode == 5, "up over a container without the managed label exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert "made by SwarmBox v0.1.0" in r.stderr, r.stderr[-800:]
    assert podman("container", "exists", other.name).returncode == 0, "the foreign container was removed"
    r = other.run("reset")
    assert r.returncode == 5, "reset exited %d" % r.returncode
    assert podman("container", "exists", other.name).returncode == 0, "reset removed the foreign container"


STEPS = [
    Step("ready", "serve reaches readiness (marker, PID 1, session main, user agent, ttyd)", False, step_ready),
    Step("tmpfs-restart", "stop is prompt (exit 143), start empties box:/tmp/swarmbox, workspace survives (B17, B3)", False, step_tmpfs_restart),
    Step("page-built", "the ttyd page is built into the image and served with the three settings (D13)", False, step_page_built),
    Step("tool-validate", "swarmbox-tool validate passes on the shipped manifests (the real validate, 6.9)", False, step_tool_validate),
    Step("tool-shim", "the claude shim is a link to swarmbox-shim and is found on PATH; nothing is installed (6.2, D2)", False, step_tool_shim),
    Step("tool-index-ports", "the generated index lists 'claude claude' and tool-ports exists and is empty (6.2, 9.3)", False, step_tool_index_ports),
    Step("attach-session", "two attach calls share one session, the idle window is gone, exit codes (D1, B36, B13)", False, step_attach_session),
    Step("no-agent", "the image holds no agent, gcloud, clasp, Go or Poetry (D2)", False, step_no_agent),
    Step("up-lifecycle", "the host helper: up creates, a second up takes the fast path, reset replaces, stop and up again (3.7.2)", False, step_up_lifecycle),
    Step("up-busy-port", "up on a busy port exits 7 and leaves nothing; a foreign container with the name is refused with exit 5 (B33)", False, step_up_busy_port_and_foreign),
    Step("nested-podman", "a nested Podman runs a container inside the box (D5)", True, step_nested_podman),
    Step("nested-cgroup", "the nested engine settings cgroupfs and file logger work (B28)", True, step_nested_cgroup),
]


def run_steps(steps, full, ctx, out=sys.stdout):
    tag = FULL_TAG if full else REDUCED_TAG
    passed = failed = skipped = 0
    for s in steps:
        if s.needs_full and not full:
            skipped += 1
            print("STEP %s SKIP %s (needs the third nesting level: set SWARMBOX_SMOKE_FULL=1 in CI or on the owner's host)" % (s.id, s.title), file=out)
            continue
        try:
            s.fn(ctx)
        except Exception as e:  # a failed assertion or a timeout: report and go on with the next step
            failed += 1
            msg = (str(e) or type(e).__name__).strip().replace("\n", " | ")[:600]
            print("STEP %s FAIL %s: %s %s" % (s.id, s.title, msg, tag), file=out)
        else:
            passed += 1
            print("STEP %s PASS %s %s" % (s.id, s.title, tag), file=out)
        finally:
            if ctx is not None:
                ctx.cleanup()
    print("SMOKE %s: passed=%d failed=%d skipped=%d" % ("full" if full else "reduced", passed, failed, skipped), file=out)
    if not full:
        print("SMOKE the full result (every step, nested Podman) is [unverified] until CI runs this with SWARMBOX_SMOKE_FULL=1; "
              "B28 stays open until then", file=out)
    return 1 if failed else 0


def main(argv):
    if "--list" in argv:
        for s in STEPS:
            print("%s %s  %s" % (s.id, "full-only" if s.needs_full else "reduced-capable", s.title))
        return 0
    full = os.environ.get("SWARMBOX_SMOKE_FULL") == "1"
    if not (full or os.environ.get("SWARMBOX_IMAGE_BUILD") == "1"):
        for s in STEPS:
            print("STEP %s SKIP %s (opt-in: set SWARMBOX_IMAGE_BUILD=1 for the reduced run or SWARMBOX_SMOKE_FULL=1 for the full run)" % (s.id, s.title))
        print("SMOKE skipped: nothing was run")
        return 0
    if not shutil.which("podman"):
        print("SMOKE cannot run: podman not found")
        return 1
    tag = os.environ.get("SWARMBOX_IMAGE_TAG")
    own = False
    if tag:
        exact_name(tag)
    else:
        tag = exact_name("swarmbox-test-img-" + rnd())
        own = True
        r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", tag], capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
            print("SMOKE image build failed")
            return 1
    ctx = Ctx(tag, full)
    only = [x for x in os.environ.get("SWARMBOX_SMOKE_ONLY", "").split(",") if x]
    steps = [st for st in STEPS if not only or st.id in only]
    try:
        return run_steps(steps, full, ctx)
    finally:
        ctx.cleanup()
        if own:
            rmi_exact(tag)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
