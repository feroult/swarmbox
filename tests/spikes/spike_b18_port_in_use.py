"""Spike B18: podman run -d -p fails because the host port is in use: what is left behind, exit status, message, --cidfile.

Design claims (3.5 edge cases, 3.8, B33): `podman run` fails; Podman may leave the container in state Created; the
--cidfile holds the ID of the container this call created (or nothing); removing by that ID removes only that
container, and a container that merely has the box's name (created beforehand) is never removed.
Run: python3 tests/spikes/spike_b18_port_in_use.py   Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"


def state(sp, name):
    r = sp.podman("ps", "-a", "--filter", "name=^%s$" % name, "--format", "{{.Names}} {{.Status}}")
    return r.stdout.strip()


def main():
    sp = sc.Spike("b18")
    work = sp.mkdtemp("b18")
    port = sp.free_port()
    sp.bind_port(port)  # the host side: something already listens on 127.0.0.1:port

    # 1. the port is in use
    name = sp.name("a")
    sp.track_container(name)
    cid = os.path.join(work, "a.cid")
    r = sp.podman("run", "-d", "--cidfile", cid, "--name", name, "-p", "127.0.0.1:%d:8080" % port, IMAGE,
                  "sleep", "infinity")
    print("  exit status: %d" % r.returncode)
    print("  stdout: %r" % r.stdout.strip())
    print("  stderr: %r" % r.stderr.strip())
    sp.expect("podman run -d fails when the host port is in use", r.returncode != 0)
    st = state(sp, name)
    print("  podman ps -a after the failure: %r" % st)
    left = bool(st)
    cid_text = open(cid).read().strip() if os.path.exists(cid) else None
    print("  cidfile exists: %s; content: %r" % (os.path.exists(cid), cid_text))
    sp.expect("message names the address or port (so 3.8's message can quote it)",
              str(port) in r.stderr or "address already in use" in r.stderr.lower() or "bind" in r.stderr.lower(),
              r.stderr.strip()[:200])
    if left:
        sp.expect("a container left behind is in state Created", "Created" in st, st)
        sp.expect("the cidfile holds a 64-hex ID when a container is left", bool(cid_text) and len(cid_text) == 64,
                  repr(cid_text))
        if cid_text:
            full = sp.podman("inspect", "--format", "{{.Id}}", name)
            sp.expect("the cidfile ID is the left container's ID", full.stdout.strip() == cid_text)
    else:
        sp.expect("no container left: the cidfile is absent or empty", not cid_text, repr(cid_text))
    # removal by the cidfile ID removes that container only
    bystander = sp.name("b")  # a separate, healthy container that must survive
    sp.run(bystander, IMAGE, cmd=["sleep", "infinity"])
    if cid_text:
        rm = sp.rm_by_id(cid_text)
        sp.expect("removing by the cidfile ID succeeds", rm.returncode == 0, rm.stderr.strip())
    sp.expect("the failed container is gone after removal by ID", state(sp, name) == "")
    sp.expect("the bystander container is untouched", "Up" in state(sp, bystander), state(sp, bystander))

    # 2. control: a free port works
    free = sp.free_port()
    ok = sp.name("c")
    r2 = sp.run(ok, IMAGE, "-p", "127.0.0.1:%d:8080" % free, cmd=["sleep", "infinity"], check=False)
    sp.expect("control: the same command on a free port starts", r2.returncode == 0, r2.stderr.strip()[:120])

    # 3. name clash: a container that already has the box's name (created beforehand by the test)
    clash = sp.name("d")
    sp.run(clash, IMAGE, cmd=["sleep", "infinity"])
    cid2 = os.path.join(work, "d.cid")
    r3 = sp.podman("run", "-d", "--cidfile", cid2, "--name", clash, IMAGE, "sleep", "infinity")
    print("  name clash: exit %d, stderr %r, cidfile exists %s content %r" % (
        r3.returncode, r3.stderr.strip()[:160], os.path.exists(cid2),
        open(cid2).read().strip() if os.path.exists(cid2) else None))
    sp.expect("a second run with an existing name fails", r3.returncode != 0)
    c2 = open(cid2).read().strip() if os.path.exists(cid2) else ""
    sp.expect("name clash: the cidfile is absent or empty, so cleanup by cidfile ID removes nothing", not c2, repr(c2))
    sp.expect("name clash: the pre-existing container is still running", "Up" in state(sp, clash), state(sp, clash))

    # 4. an existing cidfile makes podman refuse (the helper must use a fresh path every call)
    sp.track_container(sp.name("e"))
    r4 = sp.podman("run", "-d", "--cidfile", cid, "--name", sp.name("e"), IMAGE, "true")
    print("  existing cidfile (the one the failed run wrote): exit %d stderr %r" % (r4.returncode, r4.stderr.strip()[:160]))
    sp.expect("an already existing cidfile makes podman refuse (the helper must use a fresh path for every call)",
              r4.returncode != 0, r4.stderr.strip()[:120])
    tag = sc.evidence("bind 127.0.0.1:port on the host, podman run -d -p --cidfile; ps -a; read cidfile; rm by ID", IMAGE)
    summary = "port in use -> exit %d, %s, cidfile %s" % (
        r.returncode, "container left (%s)" % st if left else "no container left",
        "holds an ID" if cid_text else "empty or absent")
    return sp.finish(tag, summary)


if __name__ == "__main__":
    sys.exit(main())
