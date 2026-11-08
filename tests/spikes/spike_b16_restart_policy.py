"""Spike B16: what Podman 4.3.1 offers for restarting a --restart container after a host reboot, rootless.

Design claim (4.2): after a host reboot the user's podman-restart.service (enabled) restarts containers created
with --restart; whether that works for rootless Podman was not checked. No systemd runs in this sandbox, so the
reboot itself cannot be tried: this spike checks what can be (reduced).
  * the package ships a USER unit /usr/lib/systemd/user/podman-restart.service installed WantedBy=default.target;
  * its ExecStart filters on restart-policy=always;
  * `podman ps --filter restart-policy=always` (the same filter) lists a throwaway container created with
    --restart=always and, tested here, whether one created with --restart=unless-stopped is listed too (finding: it is not);
  * a container created without --restart is not listed.
It reads the unit file and the documentation text saved from podman's v4.3.1 sources when the network allows.
Run: python3 tests/spikes/spike_b16_restart_policy.py   Exit 1 if a claim is contradicted.
"""
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/debian:bookworm-slim"
UNIT = "/usr/lib/systemd/user/podman-restart.service"
DOC = "https://raw.githubusercontent.com/containers/podman/v4.3.1/docs/source/markdown/options/restart.md"


def listed(sp, name):
    r = sp.podman("ps", "-a", "--filter", "restart-policy=always", "--filter", "name=" + name,
                  "--format", "{{.Names}}")
    return name in r.stdout.split()


def main():
    sp = sc.Spike("b16")
    try:
        unit = open(UNIT).read()
    except OSError:
        unit = ""
    sp.expect("the podman package ships a user unit %s" % UNIT, bool(unit))
    sp.expect("the unit is installed WantedBy=default.target (a user unit: systemctl --user enable)",
              "WantedBy=default.target" in unit)
    sp.expect("the unit starts containers by --filter restart-policy=always",
              "start --all --filter restart-policy=always" in unit)
    names = {}
    for pol in ("always", "unless-stopped", "no"):
        n = sp.name(pol)
        sp.run(n, IMAGE, "--restart=" + pol, cmd=("sleep", "300"))
        names[pol] = n
    for pol, expect_listed in (("always", True), ("unless-stopped", None), ("no", False)):
        got = listed(sp, names[pol])
        print("  --restart=%s: listed by --filter restart-policy=always: %s" % (pol, got))
        if expect_listed is not None:
            sp.expect("a container created with --restart=%s is %slisted by the unit's filter" % (
                pol, "" if expect_listed else "not "), got == expect_listed)
    # finding: the 4.3.1 documentation calls unless-stopped "identical to always", but the unit's filter does not
    # match it, so a reboot would not restart such a container. Only --restart=always is covered on 4.3.1.
    sp.expect("FINDING: --restart=unless-stopped is NOT matched by the unit's filter on 4.3.1 (only always is)",
              not listed(sp, names["unless-stopped"]))
    try:
        doc = urllib.request.urlopen(DOC, timeout=30).read().decode()
        m = re.search(r"Please note that restart will not restart containers after a system reboot\.", doc)
        sp.expect("the v4.3.1 documentation says --restart alone does not survive a reboot", bool(m))
        sp.expect("the v4.3.1 documentation says unless-stopped is identical to always",
                  "`unless-stopped`           : Identical to **always**" in doc)
    except OSError as e:
        print("  documentation not reachable (%s): [unverified]" % e)
    tag = sc.evidence("unit file read, throwaway containers created with each policy and listed by the unit's "
                      "filter, v4.3.1 documentation text", IMAGE,
                      reduced="no systemd here, so no reboot and no systemctl --user enable was tried")
    return sp.finish(tag, "podman-restart.service exists as a user unit and selects restart-policy=always; the "
                     "reboot itself is [unverified]")


if __name__ == "__main__":
    sys.exit(main())
