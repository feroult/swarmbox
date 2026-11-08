"""Spike B10: the OpenCode size saving of about 720 MB under `npm install -g --prefix`, and that the binary still runs.

Design claim (6.4): OpenCode ships several platform builds of about 240 MB each, hard-links the right one into bin/;
removing node_modules/@opencode under the package saves about 720 MB and `opencode --version` still runs.
Both packages are measured: `@opencode/cli` (what v0.1.0 installs) and `opencode-ai` (the other npm name).
Run: python3 tests/spikes/spike_b10_opencode_prefix.py   Needs the network.  Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"
# package, directory of the package under lib/node_modules, folder of the platform builds under it
PACKAGES = [("@opencode/cli", "@opencode/cli", "node_modules/@opencode"),
            ("opencode-ai", "opencode-ai", "node_modules")]


def main():
    sp = sc.Spike("b10")
    ws = sp.mkdtemp("home")
    os.chmod(ws, 0o755)
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent:rw",
               "-e", "HOME=/home/agent", "-e", "NPM_CONFIG_CACHE=/opt/npm-cache", cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container starts", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("npm install -g --prefix", IMAGE), "no container")
    sp.exec(name, "sh", "-c", "mkdir -p /opt/npm-cache && chown 1000:1000 /opt/npm-cache", user="0")

    def sh(script, timeout=600):
        r = sp.exec(name, "sh", "-c", script, user="1000", timeout=timeout)
        return (r.stdout + r.stderr).strip()

    def mb(path):
        return int(sh("du -sm %s | cut -f1" % path) or 0)

    summary = []
    for pkg, pdir, builds in PACKAGES:
        pfx = "/home/agent/.local/" + pdir.replace("@", "").replace("/", "-")
        sh("npm install -g --prefix %s %s >/dev/null 2>&1; true" % (pfx, pkg))
        ver = sh("%s/bin/opencode --version" % pfx)
        if not sp.expect("%s installs under --prefix and runs" % pkg, ver != "" and "not found" not in ver, ver[:100]):
            continue
        before = mb(pfx)
        pkgdir = "%s/lib/node_modules/%s" % (pfx, pdir)
        names = sh("ls %s/%s" % (pkgdir, builds)).split()
        inode = sh("stat -c '%%h' %s/bin/opencode.exe" % pkgdir)
        print("  %s %s: prefix %d MB; platform builds %s; links on bin/opencode.exe: %s" % (pkg, ver, before, names, inode))
        sp.expect("%s: the real binary in bin/ is hard-linked to one platform build (link count 2)" % pkg, inode == "2", inode)
        sh("rm -rf %s/%s" % (pkgdir, builds if pkg != "opencode-ai" else "node_modules"))
        after = mb(pfx)
        run = sh("%s/bin/opencode --version" % pfx)
        print("  %s after pruning: %d MB (saved %d MB); `opencode --version`: %s" % (pkg, after, before - after, run))
        sp.expect("%s: the binary still runs after pruning" % pkg, run == ver, run)
        # @opencode/cli installs four builds (three removable); opencode-ai installs two on glibc (one removable)
        need = 600 if pkg == "@opencode/cli" else 150
        sp.expect("%s: pruning saves at least %d MB" % (pkg, need), before - after >= need, "%d MB" % (before - after))
        if pkg == "@opencode/cli":
            sp.expect("%s: the saving is about 720 MB as the design says (within 20 percent)" % pkg,
                      abs((before - after) - 720) <= 144, "saved %d MB" % (before - after))
        summary.append("%s %s: %d MB to %d MB (saved %d)" % (pkg, ver.replace("opencode ", ""), before, after, before - after))
    cache = mb("/opt/npm-cache")
    print("  npm cache after both installs: %d MB (in /opt/npm-cache, not in the home)" % cache)
    tag = sc.evidence("npm install -g --prefix <home>/.local/<pkg> <pkg>; rm -rf the platform builds; du -sm", IMAGE)
    return sp.finish(tag, "; ".join(summary))


if __name__ == "__main__":
    sys.exit(main())
