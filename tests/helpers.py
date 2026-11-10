"""Shared helpers for the tests.

ROOT is the repository root, wherever the tests are run from.

FakePodman is a fake `podman` that records its calls and answers from a script, so a test can run repository code
that calls podman without a real container. Use it as a context manager:

    with FakePodman(subcommands={"ps": {"stdout": "cid1\\n"}}) as fp:
        subprocess.run(["sh", "x.sh"], env=fp.env())
        fp.calls()            # [["ps", "-a", "-q"], ...]  one argv list per call, exact

Call log: a JSON-lines file, one object per call, {"argv": [...], "pid": N}. JSON makes arguments with spaces,
quotes, $ and newlines unambiguous. Each call is one os.write on an O_APPEND descriptor, so concurrent calls never
interleave.

Behavior per subcommand (the first argument that is not an option; the global options --url, --connection, -c,
--remote-host, --identity, --log-level, --root, --runroot and --storage-driver are skipped with their value). Keys:
  exit    exit code (default 0)
  stdout  text, or a list of lines (one per line, trailing newline); the shape of `create-flags` output
  stderr  text, written to standard error
  stdout_file  path of a file whose bytes are written to standard output after "stdout" (a tar archive for `run ... host-helper`)
  cidfile text written to the file named by --cidfile (or --cidfile=FILE), only when this key is present
A subcommand entry may instead be {"rules": [...], "default": {...}}: the first rule whose "match" (a list of strings, all of
which must occur in the call's arguments joined by spaces) fits answers, with the same keys; "default" answers when none fits.
A rule (or the entry) may carry "seq": a list of such answers, used one per call that this rule answered (the last one
repeats), so "the box does not exist the first time and runs afterwards" is {"match": ["inspect"], "seq": [{"exit": 125}, {...}]}.
A subcommand that is not configured defaults to: exit 0, no output, nothing written. The key "*" in `subcommands`
is a fallback for every subcommand without its own entry.

The fake never runs anything else (it only records and prints), so a real podman is never invoked through it.
PATH is the fake's folder first, then the original PATH (so sh, bash and friends still resolve).
assert_no_leak() fails loudly if "podman" does not resolve to the fake on the current PATH.
"""
import io
import json
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

# A long temporary folder (macOS: /private/var/folders/xx/yyyy/T/) pushes the Podman socket path of a test workspace past the 100
# byte limit of a unix socket, and the script then exits 4. Use /tmp when the default is long. Children inherit TMPDIR.
if len(os.path.realpath(tempfile.gettempdir())) > 40 and os.path.isdir("/tmp"):
    os.environ["TMPDIR"] = "/tmp"
    tempfile.tempdir = "/tmp"

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DEFAULTS_FILE = os.path.join(ROOT, "container", "host", "DEFAULTS")


def read_defaults():
    """The KEY=VALUE pairs of container/host/DEFAULTS, one pair of single quotes removed from a value."""
    out = {}
    with open(DEFAULTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if len(v) >= 2 and v[0] == v[-1] == "'":
                    v = v[1:-1]
                out[k] = v
    return out


_DEFAULTS = read_defaults()
# The default names of the product. Tests read them here, never as a literal (tests/test_default_names_lint.py enforces it).
DEFAULT_NAME = _DEFAULTS["SWARMBOX_DEFAULT_NAME"]
DEFAULT_IMAGE_REPO = _DEFAULTS["SWARMBOX_DEFAULT_IMAGE_REPO"]
DEFAULT_VOLUME = DEFAULT_NAME + "-containers"
DEFAULT_CONNECTOR = DEFAULT_NAME + "-cloudflared"
# The v0.1.0 name: only for tests that look at migration or the old fixtures, never a default of 2.0.

_FAKE_SCRIPT = r'''#!%(python)s
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
fd = os.open(os.path.join(d, "calls.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(fd, (json.dumps({"argv": argv, "pid": os.getpid(),
                          "env": {k: v for k, v in os.environ.items() if k.startswith("TUNNEL_")}}) + "\n").encode())
os.close(fd)
with open(os.path.join(d, "script.json")) as f:
    subs = json.load(f)
WITH_VALUE = {"--url", "--connection", "-c", "--remote-host", "--identity", "--log-level", "--root", "--runroot",
              "--storage-driver"}
sub, i = None, 0
while i < len(argv):
    a = argv[i]
    if a in WITH_VALUE:
        i += 2
        continue
    if a.startswith("-"):
        i += 1
        continue
    sub = a
    break
conf = subs.get(sub, subs.get("*", {}))


def matches(rule, args):
    joined = " ".join(args)
    return all(tok in joined for tok in rule.get("match", []))


rules = conf.get("rules", [])
chosen = conf
if rules:
    chosen = conf.get("default", {})
    for rule in rules:
        if matches(rule, argv):
            chosen = rule
            break
if True:
    if "seq" in chosen:
        # the n-th call that this rule answers gets the n-th entry (the last one repeats); n is counted in the log,
        # up to this process's own line, so it is the same for concurrent callers as for sequential ones
        with open(os.path.join(d, "calls.jsonl")) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        mine = max(i for i, e in enumerate(entries) if e["pid"] == os.getpid())
        n = 0
        for e in entries[:mine]:
            e_sub = None
            k = 0
            while k < len(e["argv"]):
                if e["argv"][k] in WITH_VALUE:
                    k += 2
                    continue
                if e["argv"][k].startswith("-"):
                    k += 1
                    continue
                e_sub = e["argv"][k]
                break
            if e_sub == sub and matches(chosen, e["argv"]) and all(
                    not matches(r, e["argv"]) for r in (rules[:rules.index(chosen)] if chosen in rules else rules)):
                n += 1
        chosen = chosen["seq"][min(n, len(chosen["seq"]) - 1)]
    conf = chosen
for j, a in enumerate(argv):
    path = None
    if a == "--cidfile" and j + 1 < len(argv):
        path = argv[j + 1]
    elif a.startswith("--cidfile="):
        path = a.split("=", 1)[1]
    if path is not None and "cidfile" in conf:
        with open(path, "w") as f:
            f.write(conf["cidfile"])
out = conf.get("stdout", "")
if isinstance(out, list):
    out = "".join(line + "\n" for line in out)
sys.stdout.write(out)
sys.stdout.flush()
if "stdout_file" in conf:
    with open(conf["stdout_file"], "rb") as f:
        sys.stdout.buffer.write(f.read())
    sys.stdout.buffer.flush()
sys.stderr.write(conf.get("stderr", ""))
sys.exit(int(conf.get("exit", 0)))
'''


class FakePodman:
    def __init__(self, subcommands=None):
        self.subcommands = dict(subcommands or {})
        self.dir = None
        self._old_path = None

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="fakepodman-")
        self._old_path = os.environ.get("PATH", "")
        try:
            exe = os.path.join(self.dir, "podman")
            with open(exe, "w") as f:
                f.write(_FAKE_SCRIPT % {"python": sys.executable})
            os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            self.log_path = os.path.join(self.dir, "calls.jsonl")
            open(self.log_path, "w").close()
            self.configure(self.subcommands)
            os.environ["PATH"] = self.dir + os.pathsep + self._old_path
            self.assert_no_leak()
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._old_path
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def configure(self, subcommands):
        """Replace the script; takes effect for the next call."""
        self.subcommands = dict(subcommands)
        with open(os.path.join(self.dir, "script.json"), "w") as f:
            json.dump(self.subcommands, f)

    def env(self, **extra):
        """A copy of the environment with the fake first on PATH, plus extras."""
        env = dict(os.environ)
        env["PATH"] = self.dir + os.pathsep + self._old_path
        env.update(extra)
        return env

    def calls(self):
        """Every recorded call as a list of argv lists (without "podman"), in log order."""
        with open(self.log_path) as f:
            return [json.loads(line)["argv"] for line in f if line.strip()]

    def envs(self):
        """The TUNNEL_* variables of each call's environment (a test can see that a secret went through the environment)."""
        with open(self.log_path) as f:
            return [json.loads(line).get("env", {}) for line in f if line.strip()]

    def assert_no_leak(self):
        found = shutil.which("podman", path=os.environ.get("PATH", ""))
        if found != os.path.join(self.dir, "podman"):
            raise AssertionError("podman resolves to %r, not the fake: a real podman could run" % found)


# ---- the helper archive of an image, and a command run on a pseudo terminal

HELPER_SH = """#!/bin/sh
d=$(dirname "$0")
echo "$*" >> "$d/calls"
case "$1" in
    version) cat "$d/VERSION" ;;
    config) [ "$2" = get ] && echo swarmbox ;;
esac
exit 0
"""


def make_archive(path, version="2.0.0", helper=True, executable=True, extra=None):
    """A helper archive like the image's: swarmbox-host (a fake that records its calls), VERSION, DEFAULTS, cloudflare-setup.py, tool-ports."""
    with tarfile.open(path, "w") as tf:
        def add(name, data, mode):
            ti = tarfile.TarInfo("./" + name)
            ti.size = len(data)
            ti.mode = mode
            ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(data))
        if helper:
            add("swarmbox-host", HELPER_SH.encode(), 0o755 if executable else 0o644)
        add("VERSION", (version + "\n").encode(), 0o644)
        with open(os.path.join(ROOT, "container", "host", "DEFAULTS"), "rb") as f:
            add("DEFAULTS", f.read(), 0o644)
        add("cloudflare-setup.py", b"# cf\n", 0o644)
        add("tool-ports", b"", 0o644)
        for name, data in (extra or {}).items():
            add(name, data, 0o644)


def pty_run(argv, env, cwd, stdin_tty, stdout_tty=True):
    master, slave = pty.openpty()
    p = subprocess.Popen(argv, env=env, cwd=cwd, stdin=slave if stdin_tty else subprocess.DEVNULL,
                         stdout=slave if stdout_tty else subprocess.PIPE, stderr=subprocess.PIPE)
    if not stdout_tty:
        out, err = p.communicate()
        os.close(slave)
        os.close(master)
        return p.returncode, out.decode(), err.decode()
    os.close(slave)
    out = b""
    while True:
        r, _, _ = select.select([master], [], [], 10)
        if not r:
            break
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    err = p.stderr.read()
    p.stderr.close()
    p.wait()
    os.close(master)
    return p.returncode, out.decode(), err.decode()
