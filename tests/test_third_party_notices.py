"""THIRD_PARTY_NOTICES.md and dev/gen-notices.sh (Phase 7, slice 7.2, design 11 last bullet, 10.4, D25, D29).

Checks:
  - no "[unverified" is left in the notices; what could not be checked is tagged "[owner-check: ...]" and says why;
  - every package of the Dockerfile apt lists and every manifest under container/tools appears in the file with a license
    identifier and a source URL;
  - the image-baked set (WITH_TOOLS default, empty) is stated, and equals the manifests that are installed on first use;
  - the notices say how to obtain the corresponding source of copyleft components;
  - the full package list (docs/debian-packages.tsv) has one line per package with a license column and flags;
  - dev/gen-notices.sh against a fake dpkg-query and a fixture /usr/share/doc tree: deterministic, flags a package without a
    copyright file, never writes into the tree.
Run: python3 tests/test_third_party_notices.py
"""
import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

GEN = os.path.join(ROOT, "dev", "gen-notices.sh")


def read(name):
    path = os.path.join(ROOT, name)
    if not os.path.isfile(path):
        raise AssertionError("%s does not exist" % name)
    with open(path, encoding="utf-8") as f:
        return f.read()


def apt_packages():
    """Every package named in an `apt-get install` of the Dockerfile."""
    d = read("Dockerfile")
    pkgs = []
    for block in re.findall(r"apt-get install -y ((?:[^\n]*\\\n)*[^\n]*)", d):
        block = block.split("&&")[0]
        for w in block.replace("\\", " ").split():
            if re.match(r"^[a-z0-9][a-z0-9.+-]*$", w):
                pkgs.append(w)
    return pkgs


def h2section(text, name):
    """From the "## ... name ..." heading to the next "## " heading (the ### subsections included)."""
    m = re.search(r"^## .*%s.*$" % re.escape(name), text, re.M | re.I)
    assert m, "no heading for %s" % name
    rest = text[m.end():]
    n = re.search(r"^## ", rest, re.M)
    return rest[:n.start()] if n else rest


def section(text, name):
    m = re.search(r"^#{2,3} .*\b%s\b.*$" % re.escape(name), text, re.M | re.I)
    assert m, "no heading for %s" % name
    rest = text[m.end():]
    n = re.search(r"^#{1,3} ", rest, re.M)
    return rest[:n.start()] if n else rest


class NoticesContentTest(unittest.TestCase):
    def setUp(self):
        self.t = read("THIRD_PARTY_NOTICES.md")

    def test_no_unverified_left(self):
        self.assertNotIn("[unverified", self.t)

    def test_owner_check_items_are_tagged_and_explained(self):
        tags = re.findall(r"\[owner-check: ([^\]]+)\]", self.t)
        self.assertTrue(tags)
        for tag in tags:
            self.assertGreater(len(tag.split()), 4, "owner-check tag too short to explain anything: %s" % tag)
        low = self.t.lower()
        self.assertIn("legal", low)
        self.assertIn("not legal advice", low)
        self.assertTrue(any("chromium" in tg.lower() for tg in tags), "Chromium's non-bundled licenses must be an owner-check item")

    def test_verified_tags_carry_a_date(self):
        for tag in re.findall(r"\[verified: ([^\]]+)\]", self.t):
            self.assertRegex(tag, r"20\d\d-\d\d-\d\d", tag)

    def test_every_apt_package_has_license_and_source(self):
        pkgs = apt_packages()
        self.assertIn("podman", pkgs)
        self.assertIn("libcap2-bin", pkgs)
        for p in sorted(set(pkgs)):
            m = re.search(r"^\|\s*`%s`\s*\|(.*)$" % re.escape(p), self.t, re.M)
            self.assertIsNotNone(m, "%s is in the Dockerfile apt list but has no table row in the notices" % p)
            cells = [c.strip() for c in m.group(1).split("|")]
            self.assertGreaterEqual(len(cells), 3, p)
            self.assertTrue(cells[1], "%s has an empty license cell" % p)
            self.assertRegex(m.group(0), r"https://\S+", "%s has no source URL" % p)

    def test_every_manifest_has_license_and_source(self):
        low = self.t.lower()
        notice_name = {"gcloud": "google cloud cli"}
        for name in sorted(os.listdir(os.path.join(ROOT, "container", "tools"))):
            s = section(self.t, notice_name.get(name, name))
            self.assertRegex(s, r"(?i)license:", "%s has no license line" % name)
            self.assertRegex(s, r"https://\S+", "%s has no source URL" % name)
            self.assertIn(name, low)

    def test_other_downloads_have_license_and_source(self):
        for name in ("ttyd", "starship", "uv", "chrome-devtools-mcp", "cloudflared"):
            s = section(self.t, name)
            self.assertRegex(s, r"(?i)license:", name)
            self.assertRegex(s, r"https://\S+", name)

    def test_image_baked_set_matches_the_default(self):
        d = read("Dockerfile")
        m = re.search(r'^ARG WITH_TOOLS="([^"]*)"', d, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "", "the default WITH_TOOLS changed: the notices' baked-set statement must be revisited")
        s = h2section(self.t, "Not shipped in the image")
        manifests = sorted(os.listdir(os.path.join(ROOT, "container", "tools")))
        self.assertIn("WITH_TOOLS", s)
        for name in manifests:
            self.assertIn(name, s.lower(), "%s missing from the not-shipped section" % name)

    def test_proprietary_items_are_flagged_not_redistributed(self):
        for name, key in (("Claude Code", "proprietary"), ("Google Cloud CLI", "first use")):
            s = section(self.t, name).lower()
            self.assertIn("not redistributed", s, name)
            self.assertIn(key, s, name)

    def test_copyleft_source_offer(self):
        s = h2section(self.t, "Corresponding source").lower()
        for word in ("gpl", "lgpl", "apt-get source", "sources.debian.org", "written offer", "deb-src"):
            self.assertIn(word, s)

    def test_evidence_of_the_generated_list(self):
        s = section(self.t, "Full package list")
        self.assertIn("docs/debian-packages.tsv", s)
        self.assertIn("dev/gen-notices.sh", s)
        tags = re.findall(r"\[verified: ([^\]]+)\]", s)
        self.assertTrue(any("swarmbox-test-" in t and "Podman 4.3.1" in t and re.search(r"20\d\d-\d\d-\d\d", t) and "Debian 12" in t
                            for t in tags), tags)

    def test_notices_state_who_does_the_legal_review(self):
        self.assertIn("[OWNER-TODO", self.t)


class PackageListTest(unittest.TestCase):
    def setUp(self):
        self.rows = [l.split("\t") for l in read("docs/debian-packages.tsv").split("\n") if l and not l.startswith("#")]

    def test_columns_and_order(self):
        header = self.rows[0]
        self.assertEqual(header, ["package", "version", "licenses", "source", "flags"])
        names = [r[0] for r in self.rows[1:]]
        self.assertEqual(names, sorted(names))
        self.assertGreater(len(names), 100)
        for r in self.rows[1:]:
            self.assertEqual(len(r), 5, r)
            self.assertTrue(r[2], "empty license column: %s" % r)

    def test_dockerfile_packages_are_in_the_list(self):
        names = {r[0] for r in self.rows[1:]}
        for p in sorted(set(apt_packages())):
            self.assertIn(p, names)

    def test_counts_in_the_notices_match_the_list(self):
        t = read("THIRD_PARTY_NOTICES.md")
        n = len(self.rows) - 1
        self.assertIn("(%d packages)" % n, t)
        named = len(set(apt_packages()))
        self.assertIn("the other %d are" % (n - named), t)
        self.assertIn("(%d packages," % len([r for r in self.rows[1:] if "NO-LICENSE-FIELD" in r[4]]), t)

    def test_flagged_rows_are_explained_in_the_notices(self):
        t = read("THIRD_PARTY_NOTICES.md")
        flagged = [r for r in self.rows[1:] if r[4]]
        for flag in {f for r in flagged for f in r[4].split(",")}:
            self.assertIn(flag, t, "flag %s of the list is not explained in the notices" % flag)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def tree_hash(root):
    h = hashlib.sha256()
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for n in sorted(fn):
            p = os.path.join(dp, n)
            h.update(p.encode())
            h.update(str(os.lstat(p).st_mtime_ns).encode())
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    h.update(f.read())
    return h.hexdigest()


class GenNoticesScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-gennotices-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.tmp]))
        self.root = os.path.join(self.tmp, "root")
        doc = os.path.join(self.root, "usr", "share", "doc")
        write(os.path.join(doc, "zlib-x", "copyright"),
              "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\nFiles: *\nLicense: Zlib\n")
        write(os.path.join(doc, "alpha", "copyright"),
              "Format: x\n\nFiles: *\nLicense: MIT\n\nFiles: debian/*\nLicense: GPL-2+\n GPL text\n\nLicense: MIT\n Permission\n")
        write(os.path.join(doc, "oldstyle", "copyright"), "This package was debianized by Somebody.\n\nIt is under the GNU GPL.\n")
        write(os.path.join(doc, "crlf", "copyright"), "Format: x\r\n\r\nFiles: *\r\nLicense: BSD-3-clause\r\n\r\nLicense:\r\n text\r\n")
        os.makedirs(os.path.join(doc, "nocopy"))
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir)
        # the fake prints the packages in reverse order, with an arch suffix on one, and a Source field with a version
        fake = os.path.join(self.bindir, "dpkg-query")
        write(fake, "#!/bin/sh\nprintf 'zlib-x|1.0||https://zlib.example/\\n'\n"
                    "printf 'oldstyle:amd64|2|oldsrc (2.0-1)|\\n'\n"
                    "printf 'nocopy|3||\\n'\n"
                    "printf 'crlf|1||\\n'\n"
                    "printf 'alpha|1:4.5-6||https://alpha.example/\\n'\n"
                    "echo \"$@\" > \"$FAKE_DPKG_ARGS\"\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        self.args = os.path.join(self.tmp, "args")

    def run_gen(self, *extra):
        env = dict(os.environ, PATH=self.bindir + os.pathsep + os.environ["PATH"], FAKE_DPKG_ARGS=self.args)
        return subprocess.run(["sh", GEN, "--root", self.root] + list(extra), env=env, capture_output=True, text=True)

    def test_output_is_a_sorted_tsv_with_licenses(self):
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "package\tversion\tlicenses\tsource\tflags")
        by = {l.split("\t")[0]: l.split("\t") for l in lines[1:]}
        self.assertEqual([l.split("\t")[0] for l in lines[1:]], ["alpha", "crlf", "nocopy", "oldstyle", "zlib-x"])
        self.assertEqual(by["alpha"][1], "1:4.5-6")
        self.assertEqual(by["alpha"][2], "GPL-2+, MIT")
        self.assertEqual(by["zlib-x"][2], "Zlib")
        self.assertEqual(by["crlf"][2], "BSD-3-clause")  # a CRLF file gives no carriage return and no empty identifier
        self.assertIn("https://sources.debian.org/src/zlib-x/", by["zlib-x"][3])
        self.assertIn("https://sources.debian.org/src/oldsrc/", by["oldstyle"][3])  # the Source field wins over the binary name

    def test_flags(self):
        by = {l.split("\t")[0]: l.split("\t") for l in self.run_gen().stdout.splitlines()[1:]}
        self.assertEqual(by["alpha"][4], "")
        self.assertEqual(by["nocopy"][4], "NO-COPYRIGHT-FILE")
        self.assertIn("NO-LICENSE-FIELD", by["oldstyle"][4])
        self.assertTrue(by["nocopy"][2])  # never empty: says unknown
        r = self.run_gen()
        self.assertIn("nocopy", r.stderr)
        self.assertIn("NO-COPYRIGHT-FILE", r.stderr)

    def test_deterministic(self):
        self.assertEqual(self.run_gen().stdout, self.run_gen().stdout)

    def test_read_only(self):
        before = tree_hash(self.tmp + "/root")
        self.run_gen()
        self.assertEqual(before, tree_hash(self.tmp + "/root"))
        with open(self.args) as f:
            a = f.read()
        self.assertIn("-W", a)
        self.assertNotIn("--remove", a)

    def test_unknown_option_and_missing_root(self):
        r = subprocess.run(["sh", GEN, "--bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 64)
        r = self.run_gen("--root", os.path.join(self.tmp, "nope"))
        self.assertNotEqual(r.returncode, 0)

    def test_image_name_must_be_a_test_image(self):
        r = subprocess.run(["sh", GEN, "--image", "docker.io/library/debian"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 64)
        self.assertIn("swarmbox-test-", r.stderr)

    def test_works_under_dash_and_bash(self):
        for sh in ("dash", "bash"):
            if subprocess.run(["which", sh], capture_output=True).returncode:
                continue
            env = dict(os.environ, PATH=self.bindir + os.pathsep + os.environ["PATH"], FAKE_DPKG_ARGS=self.args)
            r = subprocess.run([sh, GEN, "--root", self.root], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, sh)
            self.assertEqual(r.stdout, self.run_gen().stdout)


if __name__ == "__main__":
    unittest.main()
