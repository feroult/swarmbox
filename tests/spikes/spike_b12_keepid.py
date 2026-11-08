"""Spike B12 (a): `podman run` accepts --userns=keep-id:uid=1000,gid=1000 and maps the host user to uid 1000.

Design claim (3.6): the option is accepted (the form is observed on Podman 4.3); one image serves every host UID
(only the UID 1000 host is testable here, B7 stays open). Re-recorded with date, version, OS and image.
Run: python3 tests/spikes/spike_b12_keepid.py   Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"


def main():
    sp = sc.Spike("b12k")
    ws = sp.mkdtemp("ws")
    os.chmod(ws, 0o755)
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent:rw",
               cmd=["sleep", "infinity"], check=False)
    if not sp.expect("podman run accepts --userns=keep-id:uid=1000,gid=1000", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("podman run --userns=keep-id:uid=1000,gid=1000", IMAGE), "option refused")
    ins = sp.podman("inspect", "--format", "{{.HostConfig.UsernsMode}}", name).stdout.strip()
    print("  UsernsMode in inspect: %r" % ins)
    # Podman 4.3.1 reports keep-id as 'private' in inspect; the proof is the uid map
    um = sp.exec(name, "cat", "/proc/self/uid_map").stdout.split("\n")
    print("  uid_map inside: %s" % [l.split() for l in um if l.strip()])
    # the map is relative to Podman's own rootless namespace, where the invoking user is 0: container 1000 -> 0, length 1
    sp.expect("the uid map sends container uid 1000 alone (length 1) to the invoking user",
              any(l.split() == ["1000", "0", "1"] for l in um if l.strip()), str(um))
    me = os.getuid()
    out = sp.exec(name, "sh", "-c", "id -u; id -g; echo hi > /home/agent/f; stat -c %u:%g /home/agent/f").stdout.split()
    sp.expect("the process runs as uid 1000 and gid 1000", out[:2] == ["1000", "1000"], str(out))
    st = os.stat(os.path.join(ws, "f"))
    print("  file written in the container seen on the host: owner %d:%d (host user is %d:%d)" % (
        st.st_uid, st.st_gid, me, os.getgid()))
    sp.expect("a file written as uid 1000 in the container is owned by the host user", st.st_uid == me, str(st.st_uid))
    sp.expect("host UID is 1000 here, so a UID other than 1000 is NOT tested (B7 stays open)", me == 1000, str(me))
    # the same option without the explicit ids, as a control for what 'keep-id' alone does with a host uid of 1000
    n2 = sp.name("plain")
    r2 = sp.run(n2, IMAGE, "--userns=keep-id", cmd=["id", "-u"], detach=False, check=False)
    print("  --userns=keep-id alone: exit %d, uid %s" % (r2.returncode, r2.stdout.strip()))
    sp.expect("plain keep-id also works on this host (control)", r2.returncode == 0, r2.stderr.strip()[:200])
    tag = sc.evidence("podman run --userns=keep-id:uid=1000,gid=1000; inspect; id; file owner on host", IMAGE,
                      reduced="host uid is 1000, so only same-uid mapping was exercised")
    return sp.finish(tag, "keep-id:uid=1000,gid=1000 accepted; host user maps to uid 1000")


if __name__ == "__main__":
    sys.exit(main())
