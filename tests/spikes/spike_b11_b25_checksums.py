"""Spike B11 and B25: the gcloud and Go download URLs and checksum sources, both architectures (D29).

B11: Google's install page (docs.cloud.google.com/sdk/docs/install-sdk) has a Linux table with a SHA256 column
for the x86_64 and arm archives under dl.google.com/dl/cloudsdk/channels/rapid/downloads/. Downloads both
archives (about 90 MB each), computes sha256 and compares with the page, and checks that the version-pinned URL
(google-cloud-cli-<version>-linux-<arch>.tar.gz) exists and what it holds compared with the unversioned archive
(finding: other bytes, so the page's checksum does not apply to it).
B25: go.dev/dl/?mode=json lists each file with a sha256; downloads linux-amd64 and linux-arm64 (about 75 MB each)
and compares.
All downloads go to a mktemp directory removed at the end. Needs network; exits 2 (skipped) when unreachable.
Run: python3 tests/spikes/spike_b11_b25_checksums.py   Exit 1 if a claim is contradicted.
"""
import hashlib
import json
import os
import re
import sys
import tarfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

GCLOUD_PAGE = "https://docs.cloud.google.com/sdk/docs/install-sdk"
GCLOUD_BASE = "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/"
COMPONENTS = "https://dl.google.com/dl/cloudsdk/channels/rapid/components-2.json"
GCLOUD_ARCH = {"amd64": "x86_64", "arm64": "arm"}      # the manifest's names -> Google's names
GO_JSON = "https://go.dev/dl/?mode=json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def members(path):
    """name -> (size, sha256 of content) of every regular file in the tarball (read in memory, not extracted)."""
    out = {}
    with tarfile.open(path) as t:
        for m in t:
            if m.isfile():
                out[m.name] = (m.size, hashlib.sha256(t.extractfile(m).read()).hexdigest())
    return out


def sha_of(url, path, keep=False):
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            h.update(b)
            f.write(b)
    if not keep:
        os.unlink(path)
    return h.hexdigest()


def main():
    sp = sc.Spike("b11b25")
    d = sp.mkdtemp("b11b25")
    try:
        page = fetch(GCLOUD_PAGE).decode("utf-8", "replace")
        golist = json.loads(fetch(GO_JSON))
        comp = json.loads(fetch(COMPONENTS))
    except OSError as e:
        print("SKIPPED: network unreachable: %s" % e)
        return 2
    version = comp["version"]
    print("  gcloud rapid channel version %s" % version)
    pinned_differs = []
    # --- B11
    for mine, theirs in GCLOUD_ARCH.items():
        url = GCLOUD_BASE + "google-cloud-cli-linux-%s.tar.gz" % theirs
        sp.expect("the install page names the %s Linux URL" % theirs, url in page)
        # the first 64-hex string after the URL in the page is that row's checksum
        m = re.search(re.escape(url) + r".{0,2000}?\b([0-9a-f]{64})\b", page, re.S)
        published = m.group(1) if m else ""
        sp.expect("the install page publishes a 64-hex sha256 for %s" % theirs, bool(HEX64.match(published)), published)
        got = sha_of(url, os.path.join(d, "g-" + theirs), keep=True)
        print("  gcloud %-6s published %s\n  %s computed  %s" % (theirs, published, " " * 13, got))
        sp.expect("computed sha256 of the unversioned %s archive equals the published one (same release)" % theirs,
                  got == published, "published=%s computed=%s" % (published, got))
        vurl = GCLOUD_BASE + "google-cloud-cli-%s-linux-%s.tar.gz" % (version, theirs)
        req = urllib.request.Request(vurl, method="HEAD")
        try:
            code = urllib.request.urlopen(req, timeout=30).status
        except OSError as e:
            code = getattr(e, "code", str(e))
        sp.expect("the version-pinned URL for %s answers 200: %s" % (theirs, vurl), code == 200, str(code))
        if code == 200:
            vgot = sha_of(vurl, os.path.join(d, "gv-" + theirs), keep=True)
            same = vgot == got
            print("  gcloud %-6s version-pinned archive sha256 %s (%s the unversioned one)" % (
                theirs, vgot, "equals" if same else "DIFFERS from"))
            # finding: the page's checksum belongs to the unversioned URL only; the pinned archive is a separate
            # file. Compare the content of the two, so the maintainer script knows whether they are the same release.
            a, b = members(os.path.join(d, "g-" + theirs)), members(os.path.join(d, "gv-" + theirs))
            print("  gcloud %-6s regular files: %d unversioned, %d pinned; identical content: %s" % (
                theirs, len(a), len(b), a == b))
            sp.expect("the pinned and unversioned %s archives hold the same files with the same content" % theirs,
                      a == b)
            os.unlink(os.path.join(d, "g-" + theirs))
            os.unlink(os.path.join(d, "gv-" + theirs))
            pinned_differs.append(not same)
    # the recorded finding (D29): the published checksum cannot be reused for the pinned URL when the bytes differ
    print("  version-pinned archives differ in bytes from the unversioned ones: %s" % pinned_differs)
    # --- B25
    latest = golist[0]
    print("  go latest stable %s" % latest["version"])
    sp.expect("the first entry of the go.dev JSON is stable", latest.get("stable") is True)
    for mine, goarch in (("amd64", "amd64"), ("arm64", "arm64")):
        fname = "%s.linux-%s.tar.gz" % (latest["version"], goarch)
        ent = [f for f in latest["files"] if f["filename"] == fname]
        sp.expect("go.dev JSON lists %s" % fname, len(ent) == 1)
        listed = ent[0]["sha256"] if ent else ""
        sp.expect("go.dev JSON gives a 64-hex sha256 for %s" % fname, bool(HEX64.match(listed)), listed)
        got = sha_of("https://go.dev/dl/" + fname, os.path.join(d, fname))
        print("  go %-6s listed %s\n  %s computed %s" % (goarch, listed, " " * 10, got))
        sp.expect("computed sha256 of %s equals the JSON value" % fname, got == listed)
    tag = sc.evidence("pages and archives fetched over HTTPS and hashed with hashlib; gcloud %s, %s" % (
        version, latest["version"]), "no container (network reads)", reduced="no container")
    return sp.finish(tag, "gcloud: the install page publishes sha256 for linux x86_64 and arm; Go: go.dev JSON "
                     "publishes sha256 per file; both match the computed values. Pinned gcloud archives differ in "
                     "bytes from the unversioned ones: %s" % pinned_differs)


if __name__ == "__main__":
    sys.exit(main())
