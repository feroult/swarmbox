"""dev/gen-notices.sh against a fake dpkg-query and a fixture /usr/share/doc tree: a sorted TSV of the packages with their licenses and sources,
deterministic, and read-only (it never writes into the tree and asks dpkg only to list, never to remove). That the notices of the repository
cover what the Dockerfile installs is in test_guard_docs.py.
Run: python3 tests/fast/test_gen_notices.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

GEN = os.path.join(ROOT, "dev", "gen-notices.sh")

# the fake prints the packages in a shuffled order, with an arch suffix on one, and a Source field with a version on another
FAKE_DPKG = ("#!/bin/sh\nprintf 'zlib-x|1.0||https://zlib.example/\\n'\nprintf 'oldstyle:amd64|2|oldsrc (2.0-1)|\\n'\nprintf 'nocopy|3||\\n'\n"
             "printf 'crlf|1||\\n'\nprintf 'alpha|1:4.5-6||https://alpha.example/\\n'\necho \"$@\" > \"$FAKE_DPKG_ARGS\"\n")
COPYRIGHTS = {
    "zlib-x": "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\nFiles: *\nLicense: Zlib\n",
    "alpha": "Format: x\n\nFiles: *\nLicense: MIT\n\nFiles: debian/*\nLicense: GPL-2+\n GPL text\n\nLicense: MIT\n Permission\n",
    "oldstyle": "This package was debianized by Somebody.\n\nIt is under the GNU GPL.\n",
    "crlf": "Format: x\r\n\r\nFiles: *\r\nLicense: BSD-3-clause\r\n\r\nLicense:\r\n text\r\n",
}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
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


class GenNotices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-gennotices-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "root")
        for name, text in COPYRIGHTS.items():
            write(os.path.join(self.root, "usr", "share", "doc", name, "copyright"), text)
        os.makedirs(os.path.join(self.root, "usr", "share", "doc", "nocopy"))
        self.bindir = os.path.join(self.tmp, "bin")
        write(os.path.join(self.bindir, "dpkg-query"), FAKE_DPKG)
        os.chmod(os.path.join(self.bindir, "dpkg-query"), 0o755)
        self.args = os.path.join(self.tmp, "args")

    def run_gen(self):
        env = dict(os.environ, PATH=self.bindir + os.pathsep + os.environ["PATH"], FAKE_DPKG_ARGS=self.args)
        return subprocess.run(["sh", GEN, "--root", self.root], env=env, capture_output=True, text=True)

    def test_the_output_is_a_sorted_deterministic_tsv_with_licenses_and_sources(self):
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "package\tversion\tlicenses\tsource\tflags")
        by = {l.split("\t")[0]: l.split("\t") for l in lines[1:]}
        self.assertEqual([l.split("\t")[0] for l in lines[1:]], ["alpha", "crlf", "nocopy", "oldstyle", "zlib-x"])
        self.assertEqual((by["alpha"][1], by["alpha"][2], by["zlib-x"][2]), ("1:4.5-6", "GPL-2+, MIT", "Zlib"))
        self.assertEqual(by["crlf"][2], "BSD-3-clause")  # a CRLF file gives no carriage return and no empty identifier
        self.assertIn("NO-COPYRIGHT-FILE", by["nocopy"][4])
        self.assertIn("https://sources.debian.org/src/zlib-x/", by["zlib-x"][3])
        self.assertIn("https://sources.debian.org/src/oldsrc/", by["oldstyle"][3])  # the Source field wins over the binary name
        self.assertEqual(self.run_gen().stdout, r.stdout)

    def test_it_never_writes_into_the_tree_and_only_lists_packages(self):
        before = tree_hash(self.root)
        self.run_gen()
        self.assertEqual(before, tree_hash(self.root))
        with open(self.args) as f:
            a = f.read()
        self.assertIn("-W", a)
        self.assertNotIn("--remove", a)


if __name__ == "__main__":
    unittest.main()
