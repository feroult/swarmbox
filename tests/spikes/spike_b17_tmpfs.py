"""Spike B17: --tmpfs /tmp/swarmbox is empty after podman stop/start, writable by the agent user (keep-id), options.

Design claims (3.6, 4.1 step 0, 4.2): the folder is a tmpfs that Podman empties at every start; the agent user can
write there with the keep-id mapping; its default options (Podman may add noexec) do not break serve or the shells.
Run: python3 tests/spikes/spike_b17_tmpfs.py   Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"


def main():
    sp = sc.Spike("b17")
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "--tmpfs", "/tmp/swarmbox",
               cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container with --tmpfs and keep-id starts", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("podman run --tmpfs --userns=keep-id", IMAGE), "could not start")

    def agent(*cmd):
        return sp.exec(name, *cmd, user="1000")

    ident = agent("id", "-un").stdout.strip()
    sp.expect("the process user under keep-id is uid 1000 'node' (the box renames it to agent)",
              agent("id", "-u").stdout.strip() == "1000", "user=" + ident)
    opts = agent("sh", "-c", "grep ' /tmp/swarmbox ' /proc/self/mountinfo").stdout.strip()
    print("  mountinfo: " + opts)
    sp.expect("/tmp/swarmbox is a tmpfs mount", " tmpfs " in opts)
    noexec = "noexec" in opts
    # the options Podman adds by default
    default_opts = opts.split(" - ")[0].split()[5] if " - " in opts else ""
    print("  mount options: " + default_opts)
    w = agent("sh", "-c", "echo ok > /tmp/swarmbox/ready && mkdir /tmp/swarmbox/d && touch /tmp/swarmbox/exit.1")
    sp.expect("agent can create files and folders in the tmpfs", w.returncode == 0, w.stderr.strip())
    st = agent("stat", "-c", "%u:%g %a", "/tmp/swarmbox").stdout.strip()
    print("  owner and mode of the mount point: " + st)
    sp.expect("agent owns or can write the mount point", w.returncode == 0)
    # exec bit: a script in the tmpfs
    agent("sh", "-c", "printf '#!/bin/sh\\necho ran\\n' > /tmp/swarmbox/x.sh; chmod +x /tmp/swarmbox/x.sh")
    ex = agent("/tmp/swarmbox/x.sh")
    print("  executing a script in the tmpfs: rc=%d out=%r err=%r (noexec in options: %s)" % (
        ex.returncode, ex.stdout.strip(), ex.stderr.strip()[:80], noexec))
    # the design says nothing needs exec there; record the fact either way
    ex_sh = agent("sh", "/tmp/swarmbox/x.sh")
    sp.expect("a script in the tmpfs can be run with an interpreter (sh file) whatever the options",
              ex_sh.stdout.strip() == "ran", ex_sh.stderr.strip())
    # stop and start
    s = sp.podman("stop", "-t", "2", name)
    sp.expect("podman stop succeeds", s.returncode == 0, s.stderr.strip())
    s = sp.podman("start", name)
    sp.expect("podman start succeeds", s.returncode == 0, s.stderr.strip())
    ls = agent("ls", "-A", "/tmp/swarmbox").stdout.split()
    sp.expect("the folder is EMPTY after stop and start (ready, exit.1, d, x.sh all gone)", ls == [],
              "listing=%s" % ls)
    w2 = agent("sh", "-c", "echo ok > /tmp/swarmbox/ready")
    sp.expect("agent can write again after the restart", w2.returncode == 0, w2.stderr.strip())
    # control: a normal path of the container filesystem survives stop/start (why the tmpfs matters)
    agent("sh", "-c", "echo old > /tmp/survivor")
    sp.podman("stop", "-t", "2", name)
    sp.podman("start", name)
    surv = agent("cat", "/tmp/survivor").stdout.strip()
    sp.expect("control: a file outside the tmpfs survives stop/start (so the tmpfs is what clears the marker)",
              surv == "old", "got=%r" % surv)
    tag = sc.evidence("podman run --tmpfs /tmp/swarmbox --userns=keep-id:uid=1000,gid=1000; stop; start; ls; write as uid 1000; mountinfo noexec=%s" % noexec, IMAGE)
    return sp.finish(tag, "tmpfs empty after restart, writable by uid 1000; mount options '%s'" % default_opts)


if __name__ == "__main__":
    sys.exit(main())
