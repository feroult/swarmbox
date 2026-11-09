"""Slice 4b.4: the maintainer script dev/record-checksums.sh (design 6.4, 6.12; D29, B11, B25).

It runs against a FAKE curl that serves small tarballs and a fake go.dev JSON listing; no network is used (the real run is a
maintainer's act, once per version bump). Run with: python3 -W error tests/test_record_checksums.py   (needs bash, jq, sha256sum)
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "record-checksums.sh")
GO_JSON = "https://go.dev/dl/?mode=json"
GO_JSON_ALL = "https://go.dev/dl/?mode=json&include=all"
GCLOUD = "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-%s-linux-%s.tar.gz"

# fake curl: `curl ... [-o FILE] URL`; the URL is looked up in the file $FAKE_MAP (lines "URL<TAB>PATH"); unknown URL = HTTP failure (22)
FAKE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$FAKE_CALLS"
out=""; url=""
while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift 2 ;; -*) shift ;; *) url=$1; shift ;; esac; done
src=$(awk -F'\t' -v u="$url" '$1==u {print $2; exit}' "$FAKE_MAP")
[ -n "$src" ] || { echo "curl: (22) 404 $url" >&2; exit 22; }
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
"""


def tarball(path, top, names):
    with tarfile.open(path, "w:gz") as t:
        for n in names:
            data = ("fake %s\n" % n).encode()
            ti = tarfile.TarInfo("%s/%s" % (top, n))
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))


def slurp(path):
    with open(path) as f:
        return f.read()


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="rc-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.fakebin = os.path.join(self.d, "fakebin")
        os.makedirs(self.fakebin)
        with open(os.path.join(self.fakebin, "curl"), "w") as f:
            f.write(FAKE_CURL)
        os.chmod(os.path.join(self.fakebin, "curl"), 0o755)
        self.map = os.path.join(self.d, "map")
        self.calls = os.path.join(self.d, "calls")
        self.served = {}
        self.conf = os.path.join(self.d, "tool.conf")

    def serve(self, url, path):
        self.served[url] = path
        with open(self.map, "w") as f:
            for u, p in self.served.items():
                f.write("%s\t%s\n" % (u, p))

    def run_script(self, *args):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.d, "TMPDIR": self.d, "FAKE_MAP": self.map, "FAKE_CALLS": self.calls}
        return subprocess.run(["bash", SCRIPT] + list(args), env=env, capture_output=True, text=True, timeout=60, cwd=self.d)

    def write_conf(self, text):
        with open(self.conf, "w") as f:
            f.write(text)

    def conf_text(self):
        with open(self.conf) as f:
            return f.read()

    def leftovers(self):
        return sorted(x for x in os.listdir(self.d) if x not in ("fakebin", "map", "calls", "tool.conf") and not x.endswith(".json")
                      and not x.endswith(".tgz"))


CONF = ("# comment kept as is\nSCHEMA=1\nNAME=%s\nKIND=tool\nPROVIDES=\"%s\"\nVERSION=%s\n")


class GoTest(Base):
    def setUp(self):
        super().setUp()
        self.amd = os.path.join(self.d, "go-amd.tgz")
        self.arm = os.path.join(self.d, "go-arm.tgz")
        tarball(self.amd, "go", ["bin/go", "bin/gofmt"])
        tarball(self.arm, "go", ["bin/go", "bin/gofmt", "extra"])
        self.write_conf(CONF % ("go", "go gofmt", "1.27.3"))
        self.serve("https://go.dev/dl/go1.27.3.linux-amd64.tar.gz", self.amd)
        self.serve("https://go.dev/dl/go1.27.3.linux-arm64.tar.gz", self.arm)
        self.listing(sha(self.amd), sha(self.arm))

    def listing(self, amd, arm, include_all=False):
        def files(v, a, s):
            return [{"filename": "go%s.linux-%s.tar.gz" % (v, a), "os": "linux", "arch": a, "sha256": s, "kind": "archive"},
                    {"filename": "go%s.windows-%s.zip" % (v, a), "os": "windows", "arch": a, "sha256": "0" * 64, "kind": "archive"},
                    {"filename": "go%s.linux-%s.tar.gz" % (v, a), "os": "linux", "arch": a, "sha256": "f" * 64, "kind": "source"}]
        rel = [{"version": "go1.28.0", "stable": True, "files": files("1.28.0", "amd64", "1" * 64) + files("1.28.0", "arm64", "2" * 64)},
               {"version": "go1.27.3", "stable": True, "files": files("1.27.3", "amd64", amd)[:2] + files("1.27.3", "arm64", arm)[:2]}]
        p = os.path.join(self.d, "listing.json")
        with open(p, "w") as f:
            json.dump(rel, f)
        self.serve(GO_JSON_ALL if include_all else GO_JSON, p)
        return p

    def test_writes_both_checksums_into_the_conf(self):
        r = self.run_script("go", self.conf)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.conf_text()
        self.assertIn("SHA256_amd64=%s\n" % sha(self.amd), text)
        self.assertIn("SHA256_arm64=%s\n" % sha(self.arm), text)
        self.assertTrue(text.startswith(CONF % ("go", "go gofmt", "1.27.3")))

    def test_a_listing_that_disagrees_with_the_download_is_refused_and_the_conf_is_untouched(self):
        self.listing(sha(self.amd), "c" * 64)
        before = self.conf_text()
        r = self.run_script("go", self.conf)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("arm64", r.stderr)
        self.assertIn("does not match", r.stderr)
        self.assertEqual(self.conf_text(), before)

class GcloudTest(Base):
    def setUp(self):
        super().setUp()
        self.x86 = os.path.join(self.d, "g-x86.tgz")
        self.arm = os.path.join(self.d, "g-arm.tgz")
        tarball(self.x86, "google-cloud-sdk", ["bin/gcloud", "bin/gsutil", "bin/bq"])
        tarball(self.arm, "google-cloud-sdk", ["bin/gcloud", "bin/gsutil", "bin/bq", "arm"])
        self.write_conf(CONF % ("gcloud", "gcloud gsutil bq", "592.0.0"))
        self.serve(GCLOUD % ("592.0.0", "x86_64"), self.x86)
        self.serve(GCLOUD % ("592.0.0", "arm"), self.arm)

    def test_computes_and_records_both_checksums(self):
        r = self.run_script("gcloud", self.conf)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.conf_text(), CONF % ("gcloud", "gcloud gsutil bq", "592.0.0") + "SHA256_amd64=%s\nSHA256_arm64=%s\n"
                         % (sha(self.x86), sha(self.arm)))
        calls = slurp(self.calls)
        self.assertIn("-linux-x86_64.tar.gz", calls)
        self.assertIn("-linux-arm.tar.gz", calls)
        self.assertNotIn("components-2.json", calls)

    def test_downloads_the_pinned_url_never_the_unversioned_one(self):
        self.run_script("gcloud", self.conf)
        for line in slurp(self.calls).splitlines():
            self.assertIn("google-cloud-cli-592.0.0-linux-", line)

    def test_a_failed_download_leaves_the_conf_untouched(self):
        del self.served[GCLOUD % ("592.0.0", "arm")]
        self.serve("https://x/unused", self.x86)
        before = self.conf_text()
        self.assertNotEqual(self.run_script("gcloud", self.conf).returncode, 0)
        self.assertEqual(self.conf_text(), before)

class UsageTest(Base):
    def test_usage_errors(self):
        self.write_conf(CONF % ("go", "go", "1.0.0"))
        self.assertEqual(self.run_script().returncode, 64)
        self.assertEqual(self.run_script("nosuch", self.conf).returncode, 64)
        self.assertEqual(self.run_script("go", os.path.join(self.d, "missing.conf")).returncode, 64)

if __name__ == "__main__":
    unittest.main()
