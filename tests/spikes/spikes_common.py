"""Shared harness for the Phase 0 spikes (not run in CI).

Safety rules enforced here, in code, so that a spike cannot disturb the box it runs in:
  * every container, image, volume and network name starts with swarmbox-test-;
  * cleanup removes by EXACT name only (never -a, never prune);
  * tmux is only invoked as `tmux -L <unique> -f /dev/null` with TMUX unset;
  * published ports bind 127.0.0.1 and lie in 20000-40000, never 7681, 8889 or 43323;
  * temporary directories come from mktemp (tempfile) and are removed by this module.

`podman` and `tmux` are looked up on PATH at call time, so tests can put fakes first.
"""
import atexit
import datetime
import os
import platform
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile

PREFIX = "swarmbox-test-"
FORBIDDEN_PORTS = {7681, 8889, 43323}
PORT_RANGE = (20000, 40000)
# podman subcommands that act on everything or on things we did not create
FORBIDDEN_PODMAN = [
    ["system", "reset"], ["system", "prune"], ["volume", "prune"], ["image", "prune"],
    ["container", "prune"], ["network", "prune"], ["pod", "prune"],
]
FORBIDDEN_FLAGS = {"-a", "--all"}
NAMED_VERBS = {"rm", "stop", "kill", "start", "restart", "exec", "logs", "inspect", "rmi",
               "cp", "wait", "pause", "unpause", "top", "port", "diff", "commit"}


class Refused(Exception):
    """An action that would break a safety rule."""


def check_name(name):
    if not isinstance(name, str) or not name.startswith(PREFIX) or len(name) <= len(PREFIX):
        raise Refused("refusing name %r: it must start with %s" % (name, PREFIX))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", name):
        raise Refused("refusing odd name %r" % (name,))
    return name


def check_port_spec(spec):
    """A -p value: must be 127.0.0.1:<host port in range>:<container port>."""
    m = re.fullmatch(r"127\.0\.0\.1:(\d+):(\d+)(/tcp)?", spec)
    if not m:
        raise Refused("refusing port spec %r: only 127.0.0.1:<port>:<port> is allowed" % (spec,))
    check_host_port(int(m.group(1)))
    return spec


def check_host_port(port):
    if port in FORBIDDEN_PORTS or not (PORT_RANGE[0] <= port <= PORT_RANGE[1]):
        raise Refused("refusing host port %s (allowed %d-%d, never %s)" % (
            port, PORT_RANGE[0], PORT_RANGE[1], sorted(FORBIDDEN_PORTS)))
    return port


def check_podman_args(args):
    """Validate a podman argument list; raise Refused on anything dangerous."""
    args = [str(a) for a in args]
    if not args:
        raise Refused("empty podman call")
    for bad in FORBIDDEN_PODMAN:
        if args[:len(bad)] == bad:
            raise Refused("refusing podman %s" % " ".join(bad))
    verb = args[0]
    if verb in ("container", "image", "volume", "network", "pod") and len(args) > 1:
        verb = args[1]
        rest = args[2:]
    else:
        rest = args[1:]
    if verb in ("rm", "stop", "kill", "rmi") and FORBIDDEN_FLAGS & set(rest):
        raise Refused("refusing podman %s with --all" % verb)
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--name", "--cidfile") and i + 1 < len(args):
            if a == "--name":
                check_name(args[i + 1])
            i += 2
            continue
        if a.startswith("--name="):
            check_name(a.split("=", 1)[1])
        if a in ("-p", "--publish") and i + 1 < len(args):
            check_port_spec(args[i + 1])
            i += 2
            continue
        if a.startswith("--publish="):
            check_port_spec(a.split("=", 1)[1])
        if a in ("-P", "--publish-all"):
            raise Refused("refusing --publish-all")
        if a in ("--network", "--net") and i + 1 < len(args) and args[i + 1] == "host":
            raise Refused("refusing host networking")
        i += 1
    # destructive verbs: every plain word (not an option value) must be a swarmbox-test- name
    if verb in ("rm", "stop", "kill", "rmi", "restart"):
        skip = False
        for a in rest:
            if skip:
                skip = False
                continue
            if a in ("-t", "--time", "-s", "--signal"):
                skip = True
                continue
            if a.startswith("-"):
                continue
            check_name(a.split("/")[-1] if verb == "rmi" else a)
    elif verb in NAMED_VERBS:
        if not any(str(a).startswith(PREFIX) or ("/" + PREFIX) in str(a) for a in rest):
            raise Refused("refusing podman %s: no %s name among the arguments" % (verb, PREFIX))
    return args


def check_tmux_args(args, env):
    """tmux must use its own socket and never see the live TMUX variable."""
    args = [str(a) for a in args]
    if "TMUX" in env:
        raise Refused("TMUX is set; unset it before running tmux")
    if len(args) < 4 or args[0] != "-L" or not args[1].startswith(PREFIX) or args[2:4] != ["-f", "/dev/null"]:
        raise Refused("tmux must be run as: tmux -L %s<unique> -f /dev/null ..." % PREFIX)
    return args


def os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def podman_version():
    try:
        out = subprocess.run(["podman", "--version"], capture_output=True, text=True).stdout.strip()
        return out.replace("podman version", "Podman").strip() or "Podman unknown"
    except OSError:
        return "Podman unknown"


def evidence(how, image, reduced=None):
    """The Part B evidence tag, with the date from the date command's source of truth (system clock)."""
    date = datetime.date.today().isoformat()
    tag = "[verified: %s; %s; %s, %s; %s]" % (how, date, podman_version(), os_name(), image)
    if reduced:
        tag = tag[:-1] + "; reduced: %s]" % reduced
    return tag


class Spike:
    """One spike run: tracks everything it creates and removes it by exact name."""

    def __init__(self, ident):
        self.ident = ident
        self.rand = "%06x" % random.randrange(16 ** 6)
        self.containers = []
        self.images = []
        self.volumes = []
        self.tmux_sockets = []
        self.tmpdirs = []
        self.pids = []
        self.sockets = []
        self.results = []   # (claim, ok, detail)
        self._cleaned = False
        atexit.register(self.cleanup)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._on_signal)

    def _on_signal(self, signum, frame):
        self.cleanup()
        sys.exit(128 + signum)

    # names
    def name(self, suffix=""):
        n = "%s%s-%s%s" % (PREFIX, self.ident, self.rand, ("-" + suffix) if suffix else "")
        return check_name(n)

    def mkdtemp(self, label="x"):
        d = tempfile.mkdtemp(prefix="swarmbox-test-%s-" % label)
        self.tmpdirs.append(d)
        return d

    # podman
    def podman(self, *args, check=False, timeout=300, input=None):
        a = check_podman_args(args)
        r = subprocess.run(["podman"] + a, capture_output=True, text=True, timeout=timeout, input=input)
        if check and r.returncode != 0:
            raise RuntimeError("podman %s failed (%d): %s" % (" ".join(a), r.returncode, r.stderr.strip()))
        return r

    def track_container(self, name):
        self.containers.append(check_name(name))

    def run(self, name, image, *opts, cmd=(), detach=True, check=True):
        """podman run [-d] --name NAME ... IMAGE cmd; the container is tracked for cleanup."""
        check_name(name)
        self.track_container(name)
        args = ["run"] + (["-d"] if detach else []) + ["--name", name] + list(opts) + [image] + list(cmd)
        return self.podman(*args, check=check)

    def exec(self, name, *cmd, user=None, tty=False, timeout=120):
        args = ["exec"] + (["-u", user] if user else []) + (["-t"] if tty else []) + [check_name(name)] + list(cmd)
        return self.podman(*args, timeout=timeout)

    def remove_container(self, name):
        check_name(name)
        subprocess.run(["podman", "rm", "-f", "-t", "0", name], capture_output=True, text=True)

    def rm_by_id(self, cid):
        """Remove a container by the ID read from a --cidfile, only after inspect shows it is a swarmbox-test- one."""
        if not re.fullmatch(r"[0-9a-f]{64}", cid or ""):
            raise Refused("not a full container ID: %r" % (cid,))
        r = subprocess.run(["podman", "inspect", "--format", "{{.Name}}", cid], capture_output=True, text=True)
        check_name(r.stdout.strip())
        return subprocess.run(["podman", "rm", "-f", "-t", "0", cid], capture_output=True, text=True)

    def build_image(self, tag, dockerfile_dir):
        check_name(tag)
        self.images.append(tag)
        r = self.podman("build", "-t", tag, dockerfile_dir, timeout=900)
        if r.returncode != 0:
            raise RuntimeError("build failed: " + r.stderr[-2000:])

    # ports
    def free_port(self):
        for _ in range(200):
            p = random.randint(*PORT_RANGE)
            if p in FORBIDDEN_PORTS:
                continue
            s = socket.socket()
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
            finally:
                s.close()
            return p
        raise RuntimeError("no free port")

    def bind_port(self, port):
        check_host_port(port)
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        self.sockets.append(s)
        return s

    # host tmux (only with its own socket)
    def tmux_host(self, *args, check=False):
        sock = "%s%s-%s" % (PREFIX, self.ident, self.rand)
        if sock not in self.tmux_sockets:
            self.tmux_sockets.append(sock)
        env = {k: v for k, v in os.environ.items() if k != "TMUX"}
        a = check_tmux_args(["-L", sock, "-f", "/dev/null"] + [str(x) for x in args], env)
        return subprocess.run(["tmux"] + a, capture_output=True, text=True, env=env)

    # results
    def expect(self, claim, ok, detail=""):
        self.results.append((claim, bool(ok), detail))
        print("  %s  %s%s" % ("ok  " if ok else "FAIL", claim, (" -- " + detail) if detail else ""))
        return ok

    def finish(self, tag, summary):
        """Print one RESULT line; return the exit status (non-zero on any contradiction)."""
        bad = [r for r in self.results if not r[1]]
        status = "CONFIRMED" if not bad else "CONTRADICTED"
        print("RESULT %s %s: %s %s" % (self.ident, status, summary, tag))
        for claim, _, detail in bad:
            print("  contradicts: %s (%s)" % (claim, detail))
        return 1 if bad else 0

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        for s in self.sockets:
            try:
                s.close()
            except OSError:
                pass
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for name in reversed(self.containers):
            self.remove_container(name)
        for name in self.volumes:
            subprocess.run(["podman", "volume", "rm", "-f", check_name(name)], capture_output=True)
        for sock in self.tmux_sockets:
            env = {k: v for k, v in os.environ.items() if k != "TMUX"}
            subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", "kill-server"], capture_output=True, env=env)
        if not os.environ.get("SWARMBOX_SPIKE_KEEP_IMAGE"):
            for tag in self.images:
                subprocess.run(["podman", "rmi", check_name(tag)], capture_output=True)
        for d in self.tmpdirs:
            shutil.rmtree(d, ignore_errors=True)


IMAGE_TAG = PREFIX + "spikes-img:1"


def ensure_spike_image(spike):
    """Build (once) swarmbox-test-spikes-img: node:24-slim + tmux + procps + the box's pinned ttyd binary.

    The apt sandbox line lives only in this scratch Dockerfile, never in the product Dockerfile.
    """
    r = subprocess.run(["podman", "image", "exists", IMAGE_TAG])
    if r.returncode == 0:
        spike.images.append(IMAGE_TAG)
        return IMAGE_TAG
    d = spike.mkdtemp("img")
    ttyd = shutil.which("ttyd")
    have_ttyd = bool(ttyd)
    if have_ttyd:
        shutil.copy(ttyd, os.path.join(d, "ttyd"))
    with open(os.path.join(d, "Dockerfile"), "w") as f:
        f.write("FROM docker.io/library/node:24-slim\n"
                "RUN echo 'APT::Sandbox::User \"root\";' > /etc/apt/apt.conf.d/99sandbox \\\n"
                " && apt-get update && apt-get install -y --no-install-recommends tmux procps \\\n"
                " && rm -rf /var/lib/apt/lists/*\n")
        if have_ttyd:
            f.write("COPY ttyd /usr/local/bin/ttyd\n")
    spike.build_image(IMAGE_TAG, d)
    return IMAGE_TAG
