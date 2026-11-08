"""Spike B2: OpenCode's auto-approve flag, from `opencode --help` and the documentation.

Design claim (6.6, 6.12): the flag is unknown, so OpenCode gets no alias until it is verified.
Installs @opencode/cli (v0.1.0's package; 2.x line) and opencode-ai (1.x line) under --prefix in a throwaway container,
parses `--help` and `run --help` for an auto-approve / permissions flag, runs it once against a trivial prompt (no
credentials; it uses the free model OpenCode ships with, if it answers), and fetches the documentation pages to see
whether they mention the flag.
Run: python3 tests/spikes/spike_b2_opencode_flag.py   Needs the network.  Exit 1 if a claim is contradicted.
"""
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

IMAGE = "docker.io/library/node:24-slim"
FLAG_RE = re.compile(r"^\s*(--[a-z-]*(?:auto|approve|permission|yolo|danger)[a-z-]*)\s+(.*)$", re.I | re.M)
DOCS = ["https://opencode.ai/docs/cli/", "https://opencode.ai/docs/permissions/", "https://opencode.ai/docs/"]


def flags(text):
    return {m.group(1): m.group(2).strip() for m in FLAG_RE.finditer(text)}


def doc_text(url):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "swarmbox-spike"}), timeout=20).read()
    except Exception as e:  # network or HTTP failure
        return None, str(e)
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw.decode("utf-8", "replace"), flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)), ""


def main():
    sp = sc.Spike("b2")
    ws = sp.mkdtemp("home")
    os.chmod(ws, 0o755)
    name = sp.name()
    r = sp.run(name, IMAGE, "--userns=keep-id:uid=1000,gid=1000", "-v", ws + ":/home/agent:rw",
               "-e", "HOME=/home/agent", "-e", "NPM_CONFIG_CACHE=/opt/npm-cache", cmd=["sleep", "infinity"], check=False)
    if not sp.expect("container starts", r.returncode == 0, r.stderr.strip()[:200]):
        return sp.finish(sc.evidence("opencode --help", IMAGE), "no container")
    sp.exec(name, "sh", "-c", "mkdir -p /opt/npm-cache /tmp/w && chown 1000:1000 /opt/npm-cache /tmp/w", user="0")

    def sh(script, timeout=300):
        r = sp.exec(name, "sh", "-c", script, user="1000", timeout=timeout)
        return (r.stdout + r.stderr).strip()

    summary = []
    for pkg in ("@opencode/cli", "opencode-ai"):
        pfx = "/home/agent/.local/" + pkg.replace("@", "").replace("/", "-")
        sh("npm install -g --prefix %s %s >/dev/null 2>&1; true" % (pfx, pkg), timeout=600)
        ver = sh("%s/bin/opencode --version" % pfx)
        if not sp.expect("%s installs and runs" % pkg, ver != "" and "not found" not in ver, ver[:100]):
            summary.append("%s did not install" % pkg)
            continue
        top = flags(sh("%s/bin/opencode --help 2>&1" % pfx))
        run = flags(sh("%s/bin/opencode run --help 2>&1" % pfx))
        print("  %s %s: top-level %s; `run` %s" % (pkg, ver, top or "none", run or "none"))
        sp.expect("%s: `opencode run --help` lists an auto-approve flag" % pkg, "--auto" in run, str(run))
        sp.expect("%s: the flag's help text says it approves what is not explicitly denied" % pkg,
                  "not explicitly denied" in run.get("--auto", ""), run.get("--auto", ""))
        # the flag against a trivial prompt: no credentials, the built-in free model if it answers
        out = sh("cd /tmp/w && timeout 90 %s/bin/opencode run --auto 'reply with the single word ok' 2>&1 | tail -5" % pfx,
                 timeout=120)
        print("  %s run --auto: %s" % (pkg, out.replace("\n", " | ")[:200]))
        sp.expect("%s: `run --auto` is accepted (no 'unknown option' error)" % pkg,
                  not re.search(r"unknown (option|flag)|unrecognized", out, re.I), out[:200])
        summary.append("%s %s: `--auto` on `run`%s" % (pkg, ver.replace("opencode ", ""), " and top level" if "--auto" in top else ""))
    # documentation
    mentions = {}
    for url in DOCS:
        text, err = doc_text(url)
        if text is None:
            print("  docs %s: unreachable (%s)" % (url, err))
            continue
        hit = re.findall(r".{0,60}(?:--auto|auto-approve|dangerously|skip-permissions).{0,80}", text, re.I)
        mentions[url] = hit
        print("  docs %s: %d characters, %d mention(s) of an auto-approve flag" % (url, len(text), len(hit)))
    reached = bool(mentions) or None
    if not mentions:
        print("  documentation not reachable: the doc half stays [unverified]")
    tag = sc.evidence("npm install -g --prefix, opencode --help, opencode run --help, opencode run --auto; docs fetched over https",
                      IMAGE, reduced=None if mentions else "documentation unreachable")
    return sp.finish(tag, "; ".join(summary) + ("; docs mention the flag: %s" % any(mentions.values()) if reached else ""))


if __name__ == "__main__":
    sys.exit(main())
