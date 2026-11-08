"""Spike B12 (b): `podman exec -e NAME` passes the host's current value and keeps it out of `podman inspect`.

Design claim (7.3): the value follows a change on the host, and does not appear in `podman inspect`.
Run: python3 tests/spikes/spike_b12_exec_env.py   Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"
VAR = "SWARMBOX_SPIKE_SECRET"


def main():
    sp = sc.Spike("b12e")
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container starts", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("podman exec -e", IMAGE), "no container")

    def entry(value, *extra):
        env = dict(os.environ)
        if value is None:
            env.pop(VAR, None)
        else:
            env[VAR] = value
        return sp.podman("exec", "-e", VAR, *extra, name, "sh", "-c", "echo \"[$%s]\"" % VAR, env=env).stdout.strip()

    v1 = entry("alpha-111")
    v2 = entry("beta-222")
    v3 = entry(None)
    print("  entries: %r %r %r" % (v1, v2, v3))
    sp.expect("the first entry sees the host value", v1 == "[alpha-111]", v1)
    sp.expect("the next entry sees the CHANGED host value", v2 == "[beta-222]", v2)
    sp.expect("with the variable unset on the host, the box gets an empty value (not the old one)", v3 == "[]", v3)
    # a process started earlier, and the container's own environment
    sp.exec(name, "sh", "-c", "true")
    insp = sp.podman("inspect", name).stdout
    sp.expect("neither value appears in podman inspect", "alpha-111" not in insp and "beta-222" not in insp)
    pid1 = sp.exec(name, "sh", "-c", "tr '\\0' '\\n' < /proc/1/environ | grep -c %s || true" % VAR).stdout.strip()
    sp.expect("PID 1's environment does not hold the variable (it is per entry, the tmux server would not see it)",
              pid1 == "0", pid1)
    tag = sc.evidence("podman exec -e NAME with three host values; podman inspect; /proc/1/environ", IMAGE)
    return sp.finish(tag, "exec -e NAME follows the host value on every entry and stays out of inspect")


if __name__ == "__main__":
    sys.exit(main())
