#!/usr/bin/env python3
"""Image smoke test (design 13.3 layer 2; plan section 4, slice 2.7).

Builds (or reuses) the image and checks it in throwaway containers: `serve` reaches readiness, `box:/tmp/swarmbox` is empty
after a stop and a start, the ttyd page is built, `swarmbox-tool validate` passes, two `attach` calls share one session, the
image holds no agent, and (full mode only) a nested Podman runs a container.

Two modes:
  reduced (default once opted in)  for the development box, which is itself a container: the throwaway box starts with the
      test-only switch SWARMBOX_TEST_NO_NESTED=1, so there is no nested Podman and `serve` is ready with warnings. Every
      result is tagged [reduced: development box, no nested Podman in the box] and is never the full result.
  full (SWARMBOX_SMOKE_FULL=1)     for CI or the owner's host: the box gets the nested-Podman flags, readiness must be
      `ok`, and the nested steps run. Results are tagged [full]. The full result stays [unverified] until CI runs it.

Opt-in: nothing runs unless SWARMBOX_IMAGE_BUILD=1 or SWARMBOX_SMOKE_FULL=1 is set; every step is then reported SKIP.
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
               "for c in claude opencode gemini codex clasp gcloud go poetry; do command -v $c && echo FOUND:$c; done; true")
    assert "FOUND:" not in r.stdout, "the neutral image holds a program it should not: " + r.stdout


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


STEPS = [
    Step("ready", "serve reaches readiness (marker, PID 1, session main, user agent, ttyd)", False, step_ready),
    Step("tmpfs-restart", "stop is prompt (exit 143), start empties box:/tmp/swarmbox, workspace survives (B17, B3)", False, step_tmpfs_restart),
    Step("page-built", "the ttyd page is built into the image and served with the three settings (D13)", False, step_page_built),
    Step("tool-validate", "swarmbox-tool validate passes (the real validate; the image has no tool manifests until a later 4a slice)", False, step_tool_validate),
    Step("attach-session", "two attach calls share one session, the idle window is gone, exit codes (D1, B36, B13)", False, step_attach_session),
    Step("no-agent", "the image holds no agent, gcloud, clasp, Go or Poetry (D2)", False, step_no_agent),
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
    try:
        return run_steps(STEPS, full, ctx)
    finally:
        ctx.cleanup()
        if own:
            rmi_exact(tag)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
