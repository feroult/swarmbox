#!/usr/bin/env python3
"""Supplementary and fallback scanner for the git history audit (design D37, plan Phase 1 slice 1.5).

Usage: python3 -I tests/audit_history.py REPO [--json]

Read-only: runs git log, git for-each-ref and git rev-list against REPO and never writes into it. It scans every added line
of every commit reachable from any ref (git log --all -p), every commit message, every annotated tag message and every file
name that ever existed. gitleaks is the primary tool; this script adds what gitleaks does not report: identities, hosts, home
paths, IP addresses, e-mail addresses and file names, and it is the documented fallback when gitleaks cannot be downloaded.

Severity: "secret" (credential-shaped: exit status 1 when any), "pii" (personal data), "info" (hosts, addresses).
Secret values are never printed: only the first 4 characters and the length (redact()).
Limits: merge-commit diffs are not shown by git log -p (the blobs they bring in come from a parent and are scanned there);
binary files are skipped; the entropy rule is a heuristic and produces false positives that need triage.
"""
import fnmatch
import json
import math
import os
import re
import subprocess
import sys

SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("gcp-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("cloudflare-tunnel-token", re.compile(r"\beyJhIjoi[A-Za-z0-9+/=_\-]{40,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
]
ENTROPY_RE = re.compile(r"""(?i)(api[_-]?key|token|secret|passw(?:or)?d|credential)\w*["']?\s*[:=]\s*["']?([A-Za-z0-9+/_\-.]{20,})""")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b")
HOME_RE = re.compile(r"(?:/home/[a-z_][a-z0-9_\-]*|/Users/[A-Za-z][A-Za-z0-9_\-]*|/root)\b")
IP_RE = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
HOST_RE = re.compile(r"\bhttps?://([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
SENSITIVE_NAMES = [".env", ".env.*", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "*.pem", "*.key", "*.p12", "*.pfx",
                   "*.kdbx", "credentials", "credentials.*", ".git-credentials", ".netrc", "*tunnel-token*", "*.token"]
SAFE_NAMES = [".env.example", ".env.sample", ".env.template"]
BORING_IPS = ("0.0.0.0", "127.0.0.1", "255.255.255.255")


def redact(value):
    return "%s[%d chars]" % (value[:4], len(value))


def entropy(s):
    return -sum(s.count(c) / len(s) * math.log2(s.count(c) / len(s)) for c in set(s))


def git(repo, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    p = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", "-c", "safe.directory=*"] + list(args),
                       capture_output=True, env=env)
    if p.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), p.stderr.decode("utf-8", "replace").strip()))
    return p.stdout.decode("utf-8", "replace")


class Collector:
    def __init__(self):
        self.items = {}   # (class, path, value) -> finding

    def add(self, cls, severity, commit, path, value, show_value=False):
        key = (cls, path, value)
        f = self.items.get(key)
        if f is None:
            self.items[key] = {"class": cls, "severity": severity, "commit": commit, "path": path,
                               "redacted": value if show_value else redact(value), "count": 1}
        else:
            f["count"] += 1

    def scan_line(self, commit, path, line):
        for cls, rx in SECRET_PATTERNS:
            for m in rx.finditer(line):
                self.add(cls, "secret", commit, path, m.group(0))
        for m in ENTROPY_RE.finditer(line):
            v = m.group(2)
            if entropy(v) >= 3.5 and not any(rx.search(v) for _, rx in SECRET_PATTERNS):
                self.add("high-entropy-near-keyword", "secret", commit, path, v)
        for m in EMAIL_RE.finditer(line):
            self.add("email", "pii", commit, path, m.group(0), True)
        for m in HOME_RE.finditer(line):
            self.add("home-path", "pii", commit, path, m.group(0), True)
        for m in IP_RE.finditer(line):
            if m.group(0) not in BORING_IPS:
                self.add("ip-address", "info", commit, path, m.group(0), True)
        for m in HOST_RE.finditer(line):
            self.add("host", "info", commit, path, m.group(1).lower(), True)


def sensitive_name(path):
    base = path.rsplit("/", 1)[-1]
    if base in SAFE_NAMES:
        return False
    return any(fnmatch.fnmatch(base, pat) for pat in SENSITIVE_NAMES)


def audit(repo):
    c = Collector()
    head = git(repo, "rev-parse", "HEAD").strip()
    commits = int(git(repo, "rev-list", "--all", "--count"))
    refs = [l.split()[2] for l in git(repo, "for-each-ref").splitlines() if l.strip()]
    objects = git(repo, "rev-list", "--all", "--objects").splitlines()
    # content of every added line, oldest commit first so that "commit" is where a value first appeared
    log = git(repo, "log", "--all", "--reverse", "-p", "-U0", "--no-color", "--no-ext-diff", "--format=@@COMMIT %H")
    commit, path, in_header = None, None, False
    for line in log.split("\n"):
        if line.startswith("@@COMMIT "):
            commit, path, in_header = line[9:], None, False
        elif line.startswith("diff --git "):
            in_header, path = True, line.split(" b/", 1)[-1] if " b/" in line else line
        elif in_header:
            if line.startswith("@@"):
                in_header = False
            elif line.startswith("+++ b/"):
                path = line[6:]
        elif line.startswith("+"):
            c.scan_line(commit, path or "(unknown)", line[1:])
    # every blob once: covers content that only merge commits bring in (git log -p shows no merge diffs)
    seen_vals = {(k[0], k[2]) for k in c.items}
    blobs = []
    for l in objects:
        sha, _, name = l.partition(" ")
        if name:
            blobs.append((sha, name))
    if blobs:
        types = subprocess.run(["git", "-C", repo, "cat-file", "--batch-check"], input="".join(s + "\n" for s, _ in blobs).encode(),
                               capture_output=True, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0")).stdout.decode().splitlines()
        for (sha, name), info in zip(blobs, types):
            if " blob " not in info:
                continue
            text = git(repo, "cat-file", "blob", sha)
            for line in text.splitlines():
                for cls, rx in SECRET_PATTERNS:
                    for m in rx.finditer(line):
                        if (cls, m.group(0)) not in seen_vals:
                            seen_vals.add((cls, m.group(0)))
                            c.add(cls, "secret", "(blob %s)" % sha[:10], name, m.group(0))
    # commit messages and tag messages
    for chunk in git(repo, "log", "--all", "--reverse", "--format=@@C %H%n%B").split("@@C ")[1:]:
        sha, _, body = chunk.partition("\n")
        for l in body.splitlines():
            c.scan_line(sha.strip(), "(commit message)", l)
    for ref in refs:
        if ref.startswith("refs/tags/"):
            if git(repo, "cat-file", "-t", ref).strip() == "tag":
                for l in git(repo, "cat-file", "tag", ref).splitlines():
                    c.scan_line(git(repo, "rev-parse", ref + "^{commit}").strip(), "(tag %s)" % ref[10:], l)
    # file names that ever existed, with the first commit that had them
    seen = set()
    for chunk in git(repo, "log", "--all", "--reverse", "--name-only", "--format=@@C %H").split("@@C ")[1:]:
        lines = chunk.splitlines()
        for name in lines[1:]:
            if name and name not in seen:
                seen.add(name)
                if sensitive_name(name):
                    c.add("sensitive-filename", "secret", lines[0].strip(), name, name, True)
    idents = {}
    for fmt in ("%an <%ae>", "%cn <%ce>"):
        for l in git(repo, "log", "--all", "--format=" + fmt).splitlines():
            idents[l] = idents.get(l, 0) + 1
    for ref in refs:
        if ref.startswith("refs/tags/") and git(repo, "cat-file", "-t", ref).strip() == "tag":
            t = re.search(r"^tagger (.*) \d+ [+-]\d{4}$", git(repo, "cat-file", "tag", ref), re.M)
            if t:
                idents[t.group(1)] = idents.get(t.group(1), 0) + 1
    findings = sorted(c.items.values(), key=lambda f: (f["severity"] != "secret", f["class"], f["path"], f["commit"]))
    return {"scope": {"head": head, "commits": commits, "refs": refs, "objects": len(objects),
                      "paths_ever": len(seen)},
            "findings": findings, "identities": sorted(idents), "identity_counts": idents}


def render_text(d):
    s = d["scope"]
    out = ["HEAD %s, %d commits, %d refs, %d objects, %d distinct paths" % (s["head"], s["commits"], len(s["refs"]),
                                                                          s["objects"], s["paths_ever"]), ""]
    out.append("severity\tclass\tcommit\tpath\tvalue\tcount")
    for f in d["findings"]:
        out.append("\t".join([f["severity"], f["class"], f["commit"][:10], f["path"], f["redacted"], str(f["count"])]))
    out += ["", "identities:"] + ["  %s (%d)" % (i, d["identity_counts"][i]) for i in d["identities"]]
    return "\n".join(out) + "\n"


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        sys.stderr.write(__doc__.split("\n\n")[0] + "\n")
        return 2
    d = audit(args[0])
    sys.stdout.write(json.dumps(d, indent=1) + "\n" if "--json" in argv else render_text(d))
    return 1 if any(f["severity"] == "secret" for f in d["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
