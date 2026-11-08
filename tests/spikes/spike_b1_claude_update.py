"""Spike B1: which Claude Code install method keeps `claude update` working, and what the install writes outside the home.

Design claims (6.4, 6.7, 6.11): Claude Code is an UPDATE=self tool installed once; its updater must work for the way
install.sh installs it, and an installer must not write outside the prefix or the home (no /usr, /etc, /opt).
Two throwaway containers (node:24-slim, uid 1000, empty home), each installs an OLD release and runs `claude update`:
  A. npm install -g --prefix <home>/.local/npm   (the v0.1.0 method moved under --prefix)
  B. the vendor's native installer (curl https://claude.ai/install.sh | bash -s <old version>)
A file listing of /usr /etc /opt /var /root and the home is compared before and after. The native installer is also
run with XDG_DATA_HOME, XDG_STATE_HOME and XDG_CACHE_HOME redirected, to see which files could live under a prefix.
No credentials are used; `claude update` and `claude --version` do not log in.
Run: python3 tests/spikes/spike_b1_claude_update.py   Needs the network.  Exit 1 if a claim is contradicted.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"
PKG = "@anthropic-ai/claude-code"
LIST = "find /usr /etc /opt /var /root /home/agent -xdev 2>/dev/null | sort"
HOME_ENV = "HOME=/home/agent"


def main():
    sp = sc.Spike("b1")
    results = {}

    def start(label):
        ws = sp.mkdtemp("b1" + label)
        os.chmod(ws, 0o755)
        name = sp.name(label)
        r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent:rw",
                   "-e", HOME_ENV, "-e", "NPM_CONFIG_CACHE=/opt/npm-cache", cmd=["sleep", "infinity"], check=False)
        if r.returncode != 0:
            return None
        sp.exec(name, "sh", "-c", "mkdir -p /opt/npm-cache && chown 1000:1000 /opt/npm-cache", user="0")
        return name

    def sh(name, script, timeout=400):
        r = sp.exec(name, "sh", "-c", script, user="1000", timeout=timeout)
        return (r.stdout + r.stderr).strip()

    def listing(name, tag):
        sh(name, "%s > /tmp/%s.txt" % (LIST, tag))

    def new_files(name, before, after):
        out = sh(name, "diff /tmp/%s.txt /tmp/%s.txt | grep '^>' | cut -c3-" % (before, after))
        return [l for l in out.splitlines() if l]

    a = start("npm")
    if not sp.expect("container A starts", a is not None):
        return sp.finish(sc.evidence("npm and native install", IMAGE), "no container")
    # choose an old release: five releases before the latest
    vs = json.loads(sh(a, "npm view %s versions --json 2>/dev/null" % PKG) or "[]")
    stable = [v for v in vs if v.count(".") == 2 and "-" not in v]
    old = stable[-6] if len(stable) > 6 else ""
    latest = stable[-1] if stable else ""
    print("  registry: latest %s, old release used %s" % (latest, old))
    if not sp.expect("the npm registry answered with a version list", bool(old)):
        return sp.finish(sc.evidence("npm view", IMAGE, reduced="registry unreachable"), "registry unreachable")

    # ---- A. npm under --prefix
    pfx = "/home/agent/.local/npm"
    sh(a, "npm install -g --prefix %s %s@%s >/dev/null 2>&1; true" % (pfx, PKG, old))
    v0 = sh(a, "%s/bin/claude --version" % pfx)
    print("  A: installed %s" % v0)
    sp.expect("A: the old release is installed", old in v0, v0)
    listing(a, "a_before")
    default = sh(a, "cd /tmp; PATH=%s/bin:$PATH timeout 200 claude update 2>&1" % pfx)
    v1 = sh(a, "%s/bin/claude --version" % pfx)
    print("  A default env: version after update %s | %s" % (v1, default.replace("\n", " | ")[-260:]))
    results["npm_default"] = old not in v1
    sp.expect("A: with npm's default prefix (/usr/local, not writable) `claude update` does NOT update the --prefix install",
              old in v1, v1)
    sp.expect("A: the updater says why (npm global folder not writable / insufficient permissions)",
              "isn't writable" in default or "Insufficient permissions" in default, default[-200:])
    withp = sh(a, "cd /tmp; export NPM_CONFIG_PREFIX=%s; PATH=%s/bin:$PATH timeout 300 claude update 2>&1" % (pfx, pfx))
    v2 = sh(a, "%s/bin/claude --version" % pfx)
    print("  A with NPM_CONFIG_PREFIX=<prefix>: version after update %s | %s" % (v2, withp.replace("\n", " | ")[-200:]))
    results["npm_prefix_env"] = old not in v2
    sp.expect("A: with NPM_CONFIG_PREFIX set to the prefix `claude update` works", old not in v2 and "Successfully" in withp,
              v2)
    listing(a, "a_after")
    outside = [f for f in new_files(a, "a_before", "a_after")
               if f.startswith(("/usr", "/etc", "/var", "/root")) or (f.startswith("/opt") and not f.startswith("/opt/npm-cache"))]
    sp.expect("A: the update wrote nothing in /usr, /etc, /var, /root or /opt (the npm cache /opt/npm-cache aside: it is the image's own, 3.6)", outside == [], str(outside[:5]))

    # ---- B. native installer
    b = start("native")
    if not sp.expect("container B starts", b is not None):
        return sp.finish(sc.evidence("npm and native install", IMAGE), "no container B")
    sp.exec(b, "sh", "-c", "apt-get -o APT::Sandbox::User=root update -qq >/dev/null 2>&1; "
            "apt-get -o APT::Sandbox::User=root install -y -qq curl ca-certificates >/dev/null 2>&1", user="0", timeout=300)
    listing(b, "b_empty")
    out = sh(b, "curl -fsSL https://claude.ai/install.sh | bash -s %s 2>&1" % old, timeout=600)
    print("  B: " + out.replace("\n", " | ")[-200:])
    reached = "Installation complete" in out
    if not sp.expect("B: the native installer is reachable and runs nested", reached, out[-200:]):
        results["native"] = None
        tag = sc.evidence("npm install and update", IMAGE, reduced="the native installer did not run")
        return sp.finish(tag, "npm only; native installer failed: " + out[-100:])
    nb = "PATH=/home/agent/.local/bin:$PATH"
    vb0 = sh(b, "%s claude --version" % nb)
    sp.expect("B: the old release is installed", old in vb0, vb0)
    listing(b, "b_before")
    upd = sh(b, "cd /tmp; %s timeout 300 claude update 2>&1" % nb)
    vb1 = sh(b, "%s claude --version" % nb)
    print("  B: version after update %s | %s" % (vb1, upd.replace("\n", " | ")[-160:]))
    results["native"] = old not in vb1
    sp.expect("B: `claude update` works with no setting at all", old not in vb1 and "Successfully" in upd, vb1)
    listing(b, "b_after")
    outside = [f for f in new_files(b, "b_empty", "b_after")
               if f.startswith(("/usr", "/etc", "/var", "/root")) or (f.startswith("/opt") and not f.startswith("/opt/npm-cache"))]
    sp.expect("B: the native installer and updater wrote nothing in /usr, /etc, /var, /root or /opt", outside == [],
              str(outside[:5]))
    homefiles = new_files(b, "b_empty", "b_after")
    tops = sorted({"/".join(f.split("/")[:5]) for f in homefiles if f.startswith("/home/agent/")})
    print("  B: new paths under the home (first levels): " + ", ".join(tops))
    vers = sh(b, "ls /home/agent/.local/share/claude/versions").split()
    sizes = sh(b, "du -sm /home/agent/.local/share/claude/versions/* | cut -f1").split()
    print("  B: versions kept after the update: %s (MB: %s); launcher: %s" % (
        vers, sizes, sh(b, "readlink /home/agent/.local/bin/claude")))
    sp.expect("B: the old version stays on disk after the update (two copies)", len(vers) >= 2, str(vers))
    meth = sh(b, "grep installMethod /home/agent/.claude.json")
    print("  B: " + meth)

    # ---- B2. native with XDG variables redirected
    c = start("xdg")
    if c:
        sp.exec(c, "sh", "-c", "apt-get -o APT::Sandbox::User=root update -qq >/dev/null 2>&1; "
                "apt-get -o APT::Sandbox::User=root install -y -qq curl ca-certificates >/dev/null 2>&1", user="0", timeout=300)
        env = "XDG_DATA_HOME=/home/agent/pfx/data XDG_STATE_HOME=/home/agent/pfx/state XDG_CACHE_HOME=/home/agent/pfx/cache"
        sh(c, "export %s; curl -fsSL https://claude.ai/install.sh | bash -s %s >/dev/null 2>&1; true" % (env, old), timeout=600)
        under = sh(c, "ls /home/agent/pfx/data/claude/versions 2>&1").split()
        link = sh(c, "readlink /home/agent/.local/bin/claude")
        elsewhere = sh(c, "ls -d /home/agent/.local/share/claude /home/agent/.cache/claude /home/agent/.local/state/claude 2>&1 | grep -v 'No such'")
        up = sh(c, "cd /tmp; export %s PATH=/home/agent/.local/bin:$PATH; claude update 2>&1 | tail -1; claude --version" % env)
        print("  XDG: versions under the redirected data dir %s; launcher -> %s; default XDG dirs created: %s; update: %s" % (
            under, link, elsewhere or "none", up.replace("\n", " | ")))
        sp.expect("XDG_DATA_HOME, XDG_STATE_HOME and XDG_CACHE_HOME are honored (the versions land under them)",
                  bool(under) and elsewhere == "", "under=%s elsewhere=%s" % (under, elsewhere))
        sp.expect("the launcher link stays in ~/.local/bin (it cannot be redirected)", link.startswith("/home/agent/pfx/"),
                  link)
        sp.expect("`claude update` works with the redirected directories", old not in up.split("\n")[-1], up)

    summary = ("npm under --prefix: updater works only with NPM_CONFIG_PREFIX=<prefix> (%s with the default env); "
               "native installer: updater works unconfigured (%s); Claude Code latest %s" % (
                   "fails" if results.get("npm_default") is False else "works",
                   results.get("native"), latest))
    tag = sc.evidence("npm install -g --prefix and curl https://claude.ai/install.sh, then claude update; find listings", IMAGE)
    return sp.finish(tag, summary)


if __name__ == "__main__":
    sys.exit(main())
