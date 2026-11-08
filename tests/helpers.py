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
  cidfile text written to the file named by --cidfile (or --cidfile=FILE), only when this key is present
A subcommand that is not configured defaults to: exit 0, no output, nothing written. The key "*" in `subcommands`
is a fallback for every subcommand without its own entry.

The fake never runs anything else (it only records and prints), so a real podman is never invoked through it.
PATH is the fake's folder first, then the original PATH (so sh, bash and friends still resolve).
assert_no_leak() fails loudly if "podman" does not resolve to the fake on the current PATH.
"""
import json
import os
import shutil
import stat
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_FAKE_SCRIPT = r'''#!%(python)s
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
fd = os.open(os.path.join(d, "calls.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(fd, (json.dumps({"argv": argv, "pid": os.getpid()}) + "\n").encode())
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

    def assert_no_leak(self):
        found = shutil.which("podman", path=os.environ.get("PATH", ""))
        if found != os.path.join(self.dir, "podman"):
            raise AssertionError("podman resolves to %r, not the fake: a real podman could run" % found)
