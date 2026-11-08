"""Spike B5: the AF_UNIX path limit, and where the helper's short-symlink fallback must start.

Design claims (3.5, 3.7): unix socket paths are limited to roughly 108 bytes; the default workspace is far from the
limit; the helper checks the length and falls back to a short symlink. The measured limit gives the exact rule.
Measures: bind() on a host tmpfs (/dev/shm) and on the host disk; bind() inside a container on a bind mount whose
mount path differs from the host path (the real case: the service binds the container path, the host connects by the
host path); connect() through a short symlink to a deep folder; what `podman --url unix://` says for a too long path.
Run: python3 tests/spikes/spike_b5_socket_len.py   Exit 1 if a claim is contradicted.
"""
import os
import socket
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/python:3.11-slim-bookworm"
SOCK_TAIL = ".local/state/swarmbox/podman.sock"      # 3.5: the socket inside the workspace
SUFFIX = "/" + SOCK_TAIL
# the rule being tested (written into 3.5): the helper falls back when the host-side socket path is longer than
# FALLBACK_MAX characters (the limit minus a margin, because other kernels allow less: macOS and BSD have 104 bytes)
FALLBACK_MAX = 100

# runs inside the container: longest bindable path under a base folder
PROBE = """
import os, socket, sys
base = sys.argv[1]
best = 0
for n in range(len(base) + 2, 140):
    p = base + "/" + "s" * (n - len(base) - 1)
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(p)
        best = n
    except OSError:
        break
    finally:
        s.close()
        try:
            os.unlink(p)
        except OSError:
            pass
print(best)
"""


def longest(base):
    """Longest absolute socket path (in characters) that bind() accepts under base."""
    best = 0
    for n in range(len(base) + 2, 140):
        path = base + "/" + "s" * (n - len(base) - 1)
        s = socket.socket(socket.AF_UNIX)
        try:
            s.bind(path)
            best = n
        except OSError:
            break
        finally:
            s.close()
            try:
                os.unlink(path)
            except OSError:
                pass
    return best


def try_connect(path):
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(path)
        return None
    except OSError as e:
        return e
    finally:
        s.close()


def main():
    sp = sc.Spike("b5")
    results = {}
    shm = tempfile.mkdtemp(prefix="swarmbox-test-b5-", dir="/dev/shm")
    sp.tmpdirs.append(shm)
    for label, base in (("host tmpfs (/dev/shm)", shm), ("host disk (mktemp)", sp.mkdtemp("b5"))):
        results[label] = longest(base)
        print("  %s: longest bindable path = %d characters" % (label, results[label]))
    host_limit = min(results.values())
    sp.expect("a numeric limit was found, equal on tmpfs and disk", host_limit > 0 and len(set(results.values())) == 1,
              str(results))
    sp.expect("the limit is 107 usable characters (sun_path is 108 bytes including the terminating NUL)",
              host_limit == 107, "limit=%d" % host_limit)
    base = sp.mkdtemp("b5e")
    over = base + "/" + "s" * (108 - len(base) - 1)
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(over)
        err = None
    except OSError as e:
        err = e
    finally:
        s.close()
    print("  a path of %d characters: %r" % (len(over), err))
    sp.expect("a path of exactly 108 characters is refused by bind()", err is not None and len(over) == 108,
              "len=%d err=%r" % (len(over), err))
    # the fallback rule against the layouts
    for label, ws in (("default host:~/swarmbox", "/home/alice/swarmbox"),
                      ("long macOS-style workspace", "/Users/maximilian.longname/Documents/projects/swarmbox")):
        print("  %s: socket path %d characters (fallback above %d, limit %d)" % (
            label, len(ws + SUFFIX), FALLBACK_MAX, host_limit))
    sp.expect("the default workspace path gives a socket path below the fallback threshold",
              len("/home/alice/swarmbox" + SUFFIX) < FALLBACK_MAX)
    sp.expect("the fallback threshold is below the measured limit", FALLBACK_MAX < host_limit,
              "threshold=%d limit=%d" % (FALLBACK_MAX, host_limit))
    # a deep workspace: the long path is refused on connect, a short symlink to the same folder works
    deep = sp.mkdtemp("b5d")
    while len(deep + SUFFIX) <= 120:
        deep = os.path.join(deep, "deepfolder")
    state = os.path.join(deep, os.path.dirname(SOCK_TAIL))
    os.makedirs(state, exist_ok=True)
    long_sock = deep + SUFFIX
    print("  deep workspace: socket path %d characters" % len(long_sock))
    e1 = try_connect(long_sock)
    sp.expect("connecting by the long path fails with 'AF_UNIX path too long' (raised by Python before the kernel), "
              "not 'no such file'", e1 is not None and "too long" in str(e1), repr(e1))
    link_dir = sp.mkdtemp("b5s")
    link = os.path.join(link_dir, "w")
    os.symlink(state, link)
    # the service side, inside a container: the deep folder is mounted at the short /home/agent
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", "%s:/home/agent:rw" % deep,
               cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container with the deep workspace mounted at /home/agent starts", r.returncode == 0,
                     r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("bind() sweeps", IMAGE), "container did not start")
    server = ("import socket,time\n"
              "p='/home/agent/%s'\n"
              "s=socket.socket(socket.AF_UNIX); s.bind(p); s.listen(1); print('bound',len(p),flush=True)\n"
              "time.sleep(40)\n" % SOCK_TAIL)
    proc = sp.popen_exec(name, "python3", "-c", server, user="1000")
    line = proc.stdout.readline().strip()
    sp.expect("the service binds the short container path although the host path is %d characters" % len(long_sock),
              line.startswith("bound"), line)
    short_sock = os.path.join(link, "podman.sock")
    e2 = None
    for _ in range(20):
        e2 = try_connect(short_sock)
        if e2 is None:
            break
        time.sleep(0.2)
    print("  short symlink path: %d characters" % len(short_sock))
    sp.expect("the host connects to the container-bound socket through a short symlink to the deep folder",
              e2 is None, repr(e2))
    # the limit inside the container (same kernel) under the mount path
    cl = sp.exec(name, "python3", "-c", PROBE, "/home/agent")
    cont_limit = int(cl.stdout.strip() or 0)
    print("  inside the container, under /home/agent: longest bindable path = %d characters" % cont_limit)
    sp.expect("the limit inside the container is the same 107 (counting the container's own path)",
              cont_limit == 107, "limit=%d" % cont_limit)
    # podman itself, informational: a too long path and a path through the symlink
    pr = sp.podman_readonly("--url", "unix://" + long_sock, "info")
    print("  podman --url unix://<%d chars>: exit %d: %s" % (
        len(long_sock), pr.returncode, (pr.stderr.strip().splitlines() or [""])[-1][-120:]))
    sp.expect("podman fails (does not hang) on a too long socket path", pr.returncode != 0)
    pr2 = sp.podman_readonly("--url", "unix://" + short_sock, "info")
    print("  podman --url unix://<short symlink> (the stand-in socket does not speak HTTP): exit %d: %s" % (
        pr2.returncode, (pr2.stderr.strip().splitlines() or [""])[-1][-120:]))
    tag = sc.evidence("bind()/connect() sweeps on /dev/shm and disk; python container with a bind mount; short "
                      "symlink fallback; podman --url", IMAGE,
                      reduced="a python stand-in for the nested Podman service, no macOS")
    return sp.finish(tag, "AF_UNIX limit %d characters (108 bytes with the NUL); fallback rule: host-side socket path "
                     "longer than %d characters" % (host_limit, FALLBACK_MAX))


if __name__ == "__main__":
    sys.exit(main())
