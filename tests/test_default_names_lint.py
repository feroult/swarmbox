"""The default names live in container/host/DEFAULTS and nowhere else.

The lint fails when a product file (the Dockerfile, cloudflare-setup.py, container/, dev/, .github/) or a test holds the default
box name or the default image repository as a literal, or one of the retired spellings of them. Documentation (README.md, docs/,
CONTRIBUTING.md, THIRD_PARTY_NOTICES.md, CHANGELOG.md) describes the defaults in prose and is checked by tests/test_docs_consistency.py.
The allowed exceptions are listed in ALLOWED, each with its reason. The scanner is also tried on a small tree made here, so a lint
that stopped finding anything would fail too. Also here: the flip test (change the two lines of a copy of DEFAULTS and the products
follow) lives in tests/test_host_config.py.
"""
import os
import re
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_NAME, DEFAULT_IMAGE_REPO, read_defaults  # noqa: E402

PRODUCT_ROOTS = ("Dockerfile", "cloudflare-setup.py", "container", "dev", ".github")
TEST_ROOT = "tests"
SKIP_DIRS = {"__pycache__", ".git", "fixtures"}
SELF = "tests/test_default_names_lint.py"
DEFAULTS = "container/host/DEFAULTS"

# Retired spellings: the names v0.1.0 used as defaults, which must not come back as defaults of 2.0.
RETIRED = [
    r"ghcr\.io/<org>/swarmbox(?![\w-])",
    r"swarmbox-cloudflared",
    r"swarmbox-containers",
    r":-swarmbox\}",
    r"--name swarmbox(?![\w-])",
    r"default: swarmbox\)",
]

# (path, regex of the allowed text, reason). A match of a pattern is ignored only when the line also matches the regex.
ALLOWED = [
    (SELF, r".", "this file names the retired spellings it looks for"),
]


def pattern_for(name, repo):
    """The patterns that count as the default being written down again: the current name as a whole word, the image path."""
    return [r"(?<![\w.])%s(?![\w-])" % re.escape(name), re.escape(repo),
                                                     r"(?<![\w.])%s-(?:containers|cloudflared)\b" % re.escape(name)] + RETIRED


def files_under(root, rels):
    for rel in rels:
        top = os.path.join(root, rel)
        if os.path.isfile(top):
            yield rel
            continue
        for d, dirs, names in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
            for n in sorted(names):
                yield os.path.relpath(os.path.join(d, n), root)


def scan(root, rels, name, repo, allowed=ALLOWED, defaults=DEFAULTS):
    """Returns ["path:line: text", ...] for every use of the default name or image repository outside the DEFAULTS file."""
    pats = [re.compile(p) for p in pattern_for(name, repo)]
    found = []
    for rel in files_under(root, rels):
        if rel == defaults or rel.endswith((".pyc", ".png", ".ico", ".gz", ".tar")):
            continue
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                lines = f.read().split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        ok = [re.compile(rx) for (p, rx, _why) in allowed if p == rel]
        for n, line in enumerate(lines, 1):
            if any(p.search(line) for p in pats) and not any(rx.search(line) for rx in ok):
                found.append("%s:%d: %s" % (rel, n, line.strip()[:120]))
    return found


class DefaultNamesLint(unittest.TestCase):
    def test_defaults_file_has_exactly_the_two_keys(self):
        d = read_defaults()
        self.assertEqual(sorted(d), ["SWARMBOX_DEFAULT_IMAGE_REPO", "SWARMBOX_DEFAULT_NAME"])
        self.assertTrue(d["SWARMBOX_DEFAULT_IMAGE_REPO"].endswith("/" + d["SWARMBOX_DEFAULT_NAME"]), d)
        self.assertIn("<org>", d["SWARMBOX_DEFAULT_IMAGE_REPO"])   # the placeholder stays

    def test_no_product_file_holds_a_default_name(self):
        self.assertEqual(scan(ROOT, PRODUCT_ROOTS, DEFAULT_NAME, DEFAULT_IMAGE_REPO), [])

    def test_no_test_holds_a_default_name(self):
        self.assertEqual(scan(ROOT, [TEST_ROOT], DEFAULT_NAME, DEFAULT_IMAGE_REPO), [])

    def test_every_allowance_is_still_needed(self):
        """An exception that no longer matches a line is dead weight: remove it."""
        pats = [re.compile(p) for p in pattern_for(DEFAULT_NAME, DEFAULT_IMAGE_REPO)]
        for path, rx, why in ALLOWED:
            if path == SELF:
                continue
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
            with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                hits = [l for l in f.read().split("\n") if any(p.search(l) for p in pats) and re.search(rx, l)]
            self.assertTrue(hits, "%s: the allowance '%s' (%s) matches nothing" % (path, rx, why))

    def test_the_scanner_finds_what_it_should(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-lint-")
        try:
            os.makedirs(os.path.join(tmp, "container", "host"))
            os.makedirs(os.path.join(tmp, "dev"))
            with open(os.path.join(tmp, "container", "host", "DEFAULTS"), "w") as f:
                f.write("SWARMBOX_DEFAULT_NAME=%s\n" % DEFAULT_NAME)
            cases = {
                "a.sh": ["BOX=${SWARMBOX_NAME:-%s}" % DEFAULT_NAME, 'REPO="%s"' % DEFAULT_IMAGE_REPO,
                         "podman rm -f swarmbox-cloudflared", "podman volume rm swarmbox-containers",
                         "NAME=${SWARMBOX_NAME:-swarmbox}", "ghcr.io/<org>/swarmbox:1", "podman rm -f %s-cloudflared" % DEFAULT_NAME],
                "b.sh": ["# swarmbox-test-ok and %s-extra and x%s are not the default" % (DEFAULT_NAME, DEFAULT_NAME),
                         "tmux -L swarmbox; ghcr.io/<org>/swarmbox-other"],
            }
            for n, lines in cases.items():
                with open(os.path.join(tmp, "dev", n), "w") as f:
                    f.write("\n".join(lines) + "\n")
            got = scan(tmp, ["dev"], DEFAULT_NAME, DEFAULT_IMAGE_REPO, allowed=[])
            self.assertEqual(sorted(set(g.split(":")[0] + ":" + g.split(":")[1] for g in got)),
                             ["dev/a.sh:1", "dev/a.sh:2", "dev/a.sh:3", "dev/a.sh:4", "dev/a.sh:5", "dev/a.sh:6", "dev/a.sh:7"])
            allowed = [("dev/a.sh", r"swarmbox-containers", "test")]
            got = scan(tmp, ["dev"], DEFAULT_NAME, DEFAULT_IMAGE_REPO, allowed=allowed)
            self.assertEqual(len(got), 6)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
