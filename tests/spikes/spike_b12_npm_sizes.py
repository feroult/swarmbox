"""Spike B12 (d): install sizes of Claude Code under `npm install -g --prefix <home dir>` and where the npm cache goes.

Design claims (3.6 persistence table, 6.4, 6.11, 10.2): the install wrote the prefix (about 325 MB, all in the home)
and the npm cache (about 157 MB); with NPM_CONFIG_CACHE=/opt/npm-cache the cache lands in the container's own
filesystem, not in the prefix; nothing is written in /usr or /etc. Also records the size of the base image, and
whether any swarmbox image exists to read the 4.2 GB figure from (it is never rebuilt here).
Run: python3 tests/spikes/spike_b12_npm_sizes.py   Needs the network.  Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"
PKG = "@anthropic-ai/claude-code"
MB = 1024 * 1024


def main():
    sp = sc.Spike("b12n")
    ws = sp.mkdtemp("home")
    os.chmod(ws, 0o755)
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent:rw",
               "-e", "NPM_CONFIG_CACHE=/opt/npm-cache", "-e", "HOME=/home/agent",
               cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container starts", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("npm install -g --prefix", IMAGE), "no container")
    # what the image Dockerfile does: /opt/npm-cache owned by the agent user
    sp.exec(name, "sh", "-c", "mkdir -p /opt/npm-cache && chown 1000:1000 /opt/npm-cache", user="0")

    def du(path):
        out = sp.exec(name, "sh", "-c", "du -sk %s 2>/dev/null | cut -f1" % path, user="0").stdout.strip()
        return int(out or 0) * 1024

    r = sp.exec(name, "sh", "-c", "npm install -g --prefix /home/agent/.local/npm %s 2>&1 | tail -3" % PKG,
                user="1000", timeout=600)
    print("  npm: %s" % r.stdout.strip().replace("\n", " | ")[:300])
    prefix = du("/home/agent/.local/npm")
    cache = du("/opt/npm-cache")
    in_home_cache = du("/home/agent/.npm")
    print("  prefix: %.0f MB; /opt/npm-cache: %.0f MB; /home/agent/.npm: %.0f MB" % (prefix / MB, cache / MB, in_home_cache / MB))
    sp.expect("the install produced a prefix and a cache", prefix > 0 and cache > 0)
    sp.expect("the cache went to /opt/npm-cache (the container's own filesystem), not into the home",
              cache > 0 and in_home_cache == 0, "home .npm=%d" % in_home_cache)
    host_size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(ws) for f in fs
                    if not os.path.islink(os.path.join(dp, f)))
    print("  the home folder on the host holds %.0f MB" % (host_size / MB))
    sp.expect("the prefix is entirely in the mounted home (the host sees it)", host_size > 0.5 * prefix)
    ver = sp.exec(name, "/home/agent/.local/npm/bin/claude", "--version", user="1000").stdout.strip()
    print("  claude --version: %s" % ver)
    sp.expect("the installed claude runs", ver != "", ver)
    # /opt aside, compare /usr and /etc alone
    usr = sp.exec(name, "sh", "-c", "find /usr /etc -xdev -newer /home/agent/.local/npm -type f 2>/dev/null | head -3",
                  user="0").stdout.strip()
    sp.expect("no file in /usr or /etc is newer than the prefix (nothing written there by the install)", usr == "", usr)
    print("  Claude Code version " + ver + " installed from the npm registry today; the sizes depend on the version")
    # the base image and the 4.2 GB figure
    sz = sp.podman_readonly("image", "inspect", "--format", "{{.Size}}", IMAGE).stdout.strip()
    print("  base image %s: %.0f MB" % (IMAGE, int(sz or 0) / MB))
    own = sp.podman_readonly("images", "--format", "{{.Repository}}:{{.Tag}} {{.Size}}").stdout
    sw = [l for l in own.splitlines() if "swarmbox" in l and "swarmbox-test-" not in l]
    print("  existing swarmbox images (not test ones): %s" % (sw or "none"))
    sp.expect("no swarmbox image exists here, so the 4.2 GB figure cannot be read (recorded as reduced)", sw == [],
              str(sw))
    tag = sc.evidence("npm install -g --prefix /home/agent/.local/npm %s as uid 1000 with NPM_CONFIG_CACHE=/opt/npm-cache; du; find; "
                      "podman image inspect" % PKG, IMAGE,
                      reduced="the 4.2 GB image was not rebuilt or measured; only its components")
    return sp.finish(tag, "prefix %.0f MB in the home, cache %.0f MB in /opt/npm-cache, nothing in /usr or /etc; base image %.0f MB" % (
        prefix / MB, cache / MB, int(sz or 0) / MB))


if __name__ == "__main__":
    sys.exit(main())
