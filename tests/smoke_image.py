#!/usr/bin/env python3
"""Image smoke test.

Builds (or reuses) the image and checks it in throwaway containers: `serve` reaches readiness, `box:/tmp/swarmbox` is empty
after a stop and a start, the ttyd page is built, `swarmbox-tool validate` passes on the shipped manifests, the claude shim, index and tool-ports are there, two `attach` calls share one session, the
image holds no agent, the `swarmbox` script installs from the image (twice) and its up, reset and stop work against a real throwaway box, and (full mode only) a nested Podman runs a container.

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
import re
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
    assert ctx.sh(name, "test -e /tmp/swarmbox/stale && echo STALE || echo gone") == "gone", "tmpfs was not emptied"
    assert ctx.sh(name, "cat /home/agent/keep.txt") == "y", "the workspace file did not survive"
    log = ctx.sh(name, "cat /home/agent/.local/state/swarmbox/serve.log")
    assert "received SIGTERM" in log, "serve.log has no SIGTERM line"


def step_tmux_scrollbar(ctx):
    """The tmux of the image is the pinned backport, and our configuration gives it the scrollbar: `on`, so the pane is one column narrower
    (79 of 80) in and out of copy mode, which keeps the program in it from being resized each time you start or stop scrolling.
    (The tmux of Debian 13 has no such option.)"""
    with open(os.path.join(ROOT, "Dockerfile")) as f:
        want = re.search(r"^ARG TMUX_VERSION=(\S+)", f.read(), re.M).group(1).split("-")[0]
    r = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
               "tmux -V; K=sbchk; tmux -L $K -f /etc/tmux.conf new-session -d -x 80 -y 24 -s x 'sleep 30' && "
               "tmux -L $K show-options -gqv pane-scrollbars && tmux -L $K display-message -p -t x '#{pane_width}' && "
               "tmux -L $K copy-mode -t x && sleep 0.3 && tmux -L $K display-message -p -t x '#{pane_width}'; tmux -L $K kill-server")
    assert r.stdout.split() == ["tmux", want, "on", "79", "79"], "tmux in the image: %r %r" % (r.stdout, r.stderr)
    assert r.stderr.strip() == "", "the configuration did not load cleanly: " + r.stderr


def step_page_built(ctx):
    built = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
                   "grep -o '__SWARMBOX_[A-Z_]*__' /usr/local/share/swarmbox/web/index.html | sort -u")
    assert sorted(built.stdout.split()) == sorted(["__SWARMBOX_CTRL_C__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_PADDING__",
                                                   "__SWARMBOX_SCROLLBAR__", "__SWARMBOX_SCROLLBAR_FF__"]), \
        "the built page has no placeholders: " + built.stdout + built.stderr
    name = ctx.box()
    assert ctx.ready(name), ctx.logs(name)
    assert wait_for(lambda: ctx.http(name, code=True) == "200", 30)
    page = ctx.http(name)
    assert "__SWARMBOX_" not in page, "a placeholder is left in the served page"
    assert "--swarmbox-padding:" in page and "window.__swarmboxClipboard=" in page, "the served page is not the built page"


# The seven tools of the repository and the commands they provide (the order of the index is the sort of `link`).
TOOL_COMMANDS = {"claude": ["claude"], "gemini": ["gemini"], "opencode": ["opencode"], "gcloud": ["gcloud", "gsutil", "bq"],
                 "clasp": ["clasp"], "go": ["go", "gofmt"], "poetry": ["poetry"]}
ALL_COMMANDS = [c for cmds in TOOL_COMMANDS.values() for c in cmds]


def step_tool_validate(ctx):
    r = podman("run", "--rm", "--entrypoint", "swarmbox-entrypoint", ctx.tag, "tool", "validate")
    out = r.stdout + r.stderr
    assert r.returncode == 0, "tool validate exited %d: %s" % (r.returncode, out)
    assert "manifest(s) checked" in out, "validate did not report what it checked (the real validate): " + out
    assert " 0 manifest" not in out, "validate checked no manifest: the image does not ship container/tools: " + out
    assert "%d manifest(s) checked" % len(TOOL_COMMANDS) in out, "validate did not check all %d manifests: %s" % (len(TOOL_COMMANDS), out)


def step_tool_shim(ctx):
    """Every command of the seven tools is a shim (a link to swarmbox-shim) found on PATH, and nothing is installed."""
    r = podman("run", "--rm", "--entrypoint", "bash", ctx.tag, "-c",
               "test -x /usr/local/bin/swarmbox-shim && echo SHIM-EXEC; SWARMBOX_CMD=1 . /etc/swarmbox/bashrc.sh; "
               "for c in %s; do echo \"$c|$(readlink /usr/local/lib/swarmbox/shims/$c)|$(type -P $c)\"; done; "
               "ls -d ~/.local/share/swarmbox/tools/claude 2>&1; ls -A /opt/swarmbox/tools 2>&1 | wc -l; true" % " ".join(ALL_COMMANDS))
    lines = r.stdout.splitlines()
    assert lines[:1] == ["SHIM-EXEC"], "swarmbox-shim is not executable: " + r.stdout + r.stderr
    for c, line in zip(ALL_COMMANDS, lines[1:]):
        assert line == "%s|/usr/local/bin/swarmbox-shim|/usr/local/lib/swarmbox/shims/%s" % (c, c), "the shim of %s is wrong: %s" % (c, line)
    assert len(lines) == len(ALL_COMMANDS) + 3, "unexpected output: " + r.stdout
    assert "No such file" in lines[-2], "a claude tool directory exists before any call: " + r.stdout
    assert lines[-1].strip() == "0", "/opt/swarmbox/tools is not empty in a default build (WITH_TOOLS is empty): " + r.stdout


def step_tool_index_ports(ctx):
    r = podman("run", "--rm", "--entrypoint", "sh", ctx.tag, "-c",
               "cat /usr/local/lib/swarmbox/index; echo ---; cat /usr/local/share/swarmbox/host/tool-ports; echo ---; "
               "ls -l /usr/local/share/swarmbox/host/tool-ports")
    index, ports, listing = r.stdout.split("---\n")
    rows = [tuple(l.split()[:2]) for l in index.splitlines() if l.strip()]
    for tool, cmds in TOOL_COMMANDS.items():
        for c in cmds:
            assert (c, tool) in rows, "the index lacks the line '%s %s': %s %s" % (c, tool, r.stdout, r.stderr)
    assert sorted(c for c, _ in rows) == sorted(ALL_COMMANDS), "the index lists other commands: " + index
    assert "tool-ports" in listing, "tool-ports is missing: " + r.stdout + r.stderr
    assert ports.split() == ["clasp", "43323"], "tool-ports is not exactly 'clasp<TAB>43323': %r" % ports


def step_mcp_generated(ctx):
    """serve step 7 writes mcp-servers.json from the registry: chrome-devtools runs the installed program, never npx."""
    r = podman("run", "--rm", "--entrypoint", "bash", ctx.tag, "-c",
               "export HOME=$(mktemp -d); swarmbox-mcp generate && cat \"$HOME/.claude/mcp-servers.json\"")
    assert r.returncode == 0, "swarmbox-mcp exited %d: %s" % (r.returncode, r.stdout + r.stderr)
    import json
    doc = json.loads(r.stdout)
    servers = doc.get("mcpServers", doc)
    assert "chrome-devtools" in servers, "mcp-servers.json lacks chrome-devtools: " + r.stdout
    assert "npx" not in r.stdout, "mcp-servers.json runs npx: " + r.stdout
    assert servers["chrome-devtools"]["command"] == "chrome-devtools-mcp", "unexpected command: " + r.stdout


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
    """A default build holds no tool (bash, because dash has no `type -P`; the step used sh and found nothing at first): every command resolves to its shim and /opt/swarmbox/tools is empty."""
    r = podman("run", "--rm", "--entrypoint", "bash", ctx.tag, "-c",
               "for c in claude opencode gemini codex clasp gcloud gsutil bq go gofmt poetry; do p=$(type -P $c) && echo \"FOUND:$c:$p\"; done; "
               "ls -A /opt/swarmbox/tools | wc -l; true")
    found = [l for l in r.stdout.splitlines() if l.startswith("FOUND:")]
    # the shims are on PATH (a link to swarmbox-shim each); codex has no tool; none is a program
    bad = [l for l in found if not l.split(":", 2)[2] == "/usr/local/lib/swarmbox/shims/" + l.split(":")[1]]
    assert not bad, "the neutral image holds a program it should not: " + r.stdout
    assert len(found) == len(ALL_COMMANDS), "a shim is missing: " + r.stdout
    assert r.stdout.splitlines()[-1].strip() == "0", "/opt/swarmbox/tools is not empty: " + r.stdout


def step_nested_podman(ctx):
    name = ctx.box()
    assert ctx.ready(name) == "ok", ctx.logs(name)
    r = podman("exec", name, "podman", "run", "--rm", NESTED_IMAGE, "echo", "nested-ok", timeout=600)
    assert r.returncode == 0 and "nested-ok" in r.stdout, "nested podman run failed: " + r.stdout + r.stderr


def step_nested_cgroup(ctx):
    """Informational. The image's settings (cgroupfs, file logger) run a nested container; the systemd manager does not.
    Fails only when the image's own settings fail; the systemd result is printed for the record."""
    name = ctx.box()
    assert ctx.ready(name) == "ok", ctx.logs(name)
    own = podman("exec", name, "podman", "info", "--format", "{{.Host.CgroupManager}} {{.Host.EventLogger}}")
    assert own.stdout.split() == ["cgroupfs", "file"], "the image's engine settings are %r" % own.stdout
    alt = podman("exec", name, "podman", "--cgroup-manager=systemd", "run", "--rm", NESTED_IMAGE, "true", timeout=600)
    print("    systemd manager: exit %d %s" % (alt.returncode, (alt.stderr.strip().splitlines() or [""])[-1][:200]))


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
    """The `swarmbox` script, installed from the image by its own installer, run against the real Podman for one throwaway box.

    Everything is in a mktemp folder: the script (SWARMBOX_BIN_DIR) and its support files (SWARMBOX_TEST_SUPPORT_DIR), HOME (so the
    config, the state folder and the lock are there, never the real ones), the workspace, and a `podman` wrapper that only records
    the arguments of each call and then runs the real Podman (so the number of calls of a command is measured, not assumed)."""

    def __init__(self, ctx, name=None, port=None):
        self.ctx = ctx
        self.root = tempfile.mkdtemp(prefix="smoke-up-")
        ctx.dirs.append(self.root)
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
        self.helper = os.path.join(self.bindir, "swarmbox")
        r = self.install()
        assert r.returncode == 0, "the installer exited %d: %s" % (r.returncode, r.stderr[-800:])

    def install(self):
        """`podman run --rm IMAGE install --image IMAGE | sh`, the way a user runs it, into this host side's scratch folders."""
        text = subprocess.run([os.path.join(self.bindir, "podman"), "run", "--rm", self.ctx.tag, "install", "--image", self.ctx.tag],
                              env=self.env(), capture_output=True, text=True, timeout=240)
        assert text.returncode == 0 and text.stdout.startswith("#!/bin/sh"), "install printed no installer: %s" % text.stderr[-800:]
        return subprocess.run(["sh"], input=text.stdout, env=self.env(), capture_output=True, text=True, timeout=240)

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_"))}
        e["PATH"] = self.bindir + os.pathsep + e.get("PATH", "")
        # HOME and the XDG state and config folders are scratch ones (the helper's config, lock and state go there), but Podman's
        # own image store stays where it is: a store in a scratch folder would sit on overlayfs inside this box and fail
        e["XDG_DATA_HOME"] = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        # the host connection of `up` is registered in this scratch folder, never in the real Podman configuration
        # CONTAINERS_CONF replaces /etc/containers/containers.conf (the development box's utsns=host lives there), so the scratch file
        # starts as a copy of it
        conf = os.path.join(self.root, "containers.conf")
        system = "/etc/containers/containers.conf"
        if os.path.exists(system) and not os.path.exists(conf):
            shutil.copy(system, conf)
        open(conf, "a").close()
        e["CONTAINERS_CONF"] = conf
        e["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        e["SWARMBOX_BIN_DIR"] = self.bindir
        e["SWARMBOX_TEST_SUPPORT_DIR"] = os.path.join(self.root, "support")
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


def step_install_script(ctx):
    """The installer of the image, twice: one executable file, the config, the PATH advice, the warning for an old function block,
    and the installed script answers `version`, `--help` and `config list` without touching a box."""
    hs = HostSide(ctx)   # installed once already
    first = open(hs.helper, "rb").read()
    assert os.stat(hs.helper).st_mode & 0o777 == 0o755, "mode of the installed script"
    names = sorted(os.listdir(hs.bindir))
    assert "swarmbox" in names and set(names) <= {"podman", "swarmbox", "sx"}, names   # sx, the short name, is written unless another sx exists
    with open(os.path.join(hs.home, ".bashrc"), "w") as f:
        f.write("# >>> swarmbox 2.0.0 >>>\nswarmbox() { :; }\n# <<< swarmbox 2.0.0 <<<\n")
    rc_before = open(os.path.join(hs.home, ".bashrc"), "rb").read()
    r = hs.install()
    assert r.returncode == 0, "the second install exited %d: %s" % (r.returncode, r.stderr[-800:])
    assert open(hs.helper, "rb").read() == first, "the second install changed the script"
    assert "old swarmbox shell function is still in:" in r.stderr and ".bashrc" in r.stderr, r.stderr
    assert open(os.path.join(hs.home, ".bashrc"), "rb").read() == rc_before, "an rc file was changed"
    for args, want in ((["version"], None), (["--help"], "usage: swarmbox"), (["config", "list"], "IMAGE=%s\t" % ctx.tag)):
        p = hs.run(*args)
        assert p.returncode == 0, "%s exited %d: %s" % (args, p.returncode, p.stderr[-400:])
        assert (p.stdout.strip() if want is None else want in p.stdout), (args, p.stdout[:200])
    assert not any(c.startswith(("start ", "rm ", "exec ")) for c in hs.calls()), "an install or a help touched a box: %r" % hs.calls()
    assert podman("container", "exists", hs.name).returncode != 0, "a box was created"


def step_up_lifecycle(ctx):
    """The script's up, reset and stop against a real throwaway box."""
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
    # a second up takes the fast path: the calls are recorded by the wrapper
    before = len(hs.calls())
    t0 = time.time()
    r = hs.run("up")
    fast = time.time() - t0
    assert r.returncode == 0, "second up exited %d: %s" % (r.returncode, r.stderr[-800:])
    made = hs.calls()[before:]
    plain = [c for c in made if not c.startswith("system connection ")]
    assert len(plain) <= 2, "the fast path made %d podman calls before the connection step: %r" % (len(plain), made)
    assert len(made) - len(plain) == 1, "the connection step of a registered box is one `list`: %r" % (made,)
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
    """With the real Podman: a creation that fails on a busy port leaves nothing of its own and exits 7; a
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
    assert "SwarmBox did not make" in r.stderr, r.stderr[-800:]
    assert podman("container", "exists", other.name).returncode == 0, "the foreign container was removed"
    r = other.run("reset")
    assert r.returncode == 5, "reset exited %d" % r.returncode
    assert podman("container", "exists", other.name).returncode == 0, "reset removed the foreign container"


STEPS = [
    Step("ready", "serve reaches readiness (marker, PID 1, session main, user agent, ttyd)", False, step_ready),
    Step("tmpfs-restart", "stop is prompt (exit 143), start empties box:/tmp/swarmbox, workspace survives", False, step_tmpfs_restart),
    Step("tmux-scrollbar", "the pinned tmux is in the image and has the scrollbar on (79 of 80 columns, in and out of copy mode)", False, step_tmux_scrollbar),
    Step("page-built", "the ttyd page is built into the image and served with the three settings", False, step_page_built),
    Step("tool-validate", "swarmbox-tool validate passes on the shipped manifests (the real validate)", False, step_tool_validate),
    Step("tool-shim", "the shims of all seven tools are links to swarmbox-shim found on PATH; nothing is installed", False, step_tool_shim),
    Step("tool-index-ports", "the index lists the commands of all seven tools and tool-ports is exactly clasp 43323", False, step_tool_index_ports),
    Step("mcp-generated", "swarmbox-mcp generates mcp-servers.json with chrome-devtools and no npx", False, step_mcp_generated),
    Step("attach-session", "two attach calls share one session, the idle window is gone, exit codes", False, step_attach_session),
    Step("no-agent", "a default build holds no agent, gcloud, clasp, Go or Poetry and /opt/swarmbox/tools is empty", False, step_no_agent),
    Step("install-script", "the image's installer writes one script and the config, twice, warns about an old function, edits no rc file", False, step_install_script),
    Step("up-lifecycle", "the script: up creates, a second up takes the fast path, reset replaces, stop and up again (3.7.2)", False, step_up_lifecycle),
    Step("up-busy-port", "up on a busy port exits 7 and leaves nothing; a foreign container with the name is refused with exit 5", False, step_up_busy_port_and_foreign),
    Step("nested-podman", "a nested Podman runs a container inside the box", True, step_nested_podman),
    Step("nested-cgroup", "the nested engine settings cgroupfs and file logger work", True, step_nested_cgroup),
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
              "the nested-container check stays open until then", file=out)
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
