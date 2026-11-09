"""Slice 4b.4: the go and gcloud tools (design 6.3, 6.4, 6.9, 6.12; D21, D29, B11, B25).

install.sh runs against a FAKE curl serving tiny tarballs; the real downloads (about 75 MB and 95 MB) are slice 4b.7.
Run with: python3 -W error tests/test_tool_go_gcloud.py   (needs bash, tar; zsh is optional)
"""
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

REAL_TOOLS = os.path.join(ROOT, "container", "tools")
TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")

# fake curl: `curl ... -o FILE URL` copies the file $FAKE_TARBALL to FILE; $FAKE_CURL_FAIL makes it fail; the call is recorded
FAKE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$FAKE_CALLS"
[ -z "${FAKE_CURL_FAIL:-}" ] || exit 22
out=""; while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift 2 ;; *) shift ;; esac; done
[ -n "$out" ] || exit 2
cp "$FAKE_TARBALL" "$out"
"""
SPECS = {
    "go": dict(top="go", bins=("bin/go", "bin/gofmt"), names=("go", "gofmt"),
               url="https://go.dev/dl/go%s.linux-%s.tar.gz", arch={"amd64": "amd64", "arm64": "arm64"}),
    "gcloud": dict(top="google-cloud-sdk", bins=("bin/gcloud", "bin/gsutil", "bin/bq"), names=("gcloud", "gsutil", "bq"),
                   url="https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-%s-linux-%s.tar.gz",
                   arch={"amd64": "x86_64", "arm64": "arm"}),
}


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read()


def conf_vars(name):
    out = subprocess.run(["bash", "-c", ". %s/%s/tool.conf; echo \"$KIND|$PROVIDES|$VERSION|${UPDATE:-managed}|${SHA256_amd64:-}|"
                          "${SHA256_arm64:-}|${PORTS:-}\"" % (REAL_TOOLS, name)], capture_output=True, text=True).stdout.strip()
    return out.split("|")


class InstallBase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="gg-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.prefix = os.path.join(self.base, "prefix")
        self.home = os.path.join(self.base, "home")
        self.fakebin = os.path.join(self.base, "fakebin")
        self.calls = os.path.join(self.base, "calls.txt")
        for d in (self.prefix, self.home):
            os.makedirs(d)
        write(os.path.join(self.fakebin, "curl"), FAKE_CURL, 0o755)

    def make_tarball(self, tool):
        s = SPECS[tool]
        p = os.path.join(self.base, tool + ".tgz")
        with tarfile.open(p, "w:gz") as t:
            for rel in s["bins"] + ("VERSION", "lib/x.txt"):
                data = ("#!/bin/sh\necho %s fake\n" % rel).encode()
                ti = tarfile.TarInfo("%s/%s" % (s["top"], rel))
                ti.size = len(data)
                ti.mode = 0o755 if rel.startswith("bin/") else 0o644
                t.addfile(ti, io.BytesIO(data))
        with open(p, "rb") as f:
            return p, hashlib.sha256(f.read()).hexdigest()

    def install(self, tool, version="1.2.3", arch="amd64", sha=None, tarball=None, **extra):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "TOOL_PREFIX": self.prefix, "TMPDIR": self.base,
               "FAKE_CALLS": self.calls, "FAKE_TARBALL": tarball or ""}
        for k, v in (("TOOL_VERSION", version), ("TOOL_ARCH", arch), ("TOOL_SHA256", sha)):
            if v is not None:
                env[k] = v
        env.update(extra)
        return subprocess.run(["bash", os.path.join(REAL_TOOLS, tool, "install.sh")], env=env, capture_output=True, text=True,
                              timeout=60, cwd=self.home)

    def outside(self):
        found = []
        for root, dirs, files in os.walk(self.base):
            if root.startswith(self.prefix) or root.startswith(self.fakebin):
                continue
            found += [os.path.relpath(os.path.join(root, f), self.base) for f in files + dirs]
        return sorted(f for f in found if f not in ("home", "prefix", "fakebin", "calls.txt", "go.tgz", "gcloud.tgz"))


class InstallTest(InstallBase):
    def test_a_correct_checksum_extracts_under_the_prefix(self):
        for tool, s in SPECS.items():
            with self.subTest(tool=tool):
                tb, sha = self.make_tarball(tool)
                r = self.install(tool, sha=sha, tarball=tb)
                self.assertEqual(r.returncode, 0, r.stderr)
                for b in s["bins"]:
                    self.assertTrue(os.access(os.path.join(self.prefix, b), os.X_OK), b)
                self.assertTrue(os.path.isfile(os.path.join(self.prefix, "lib", "x.txt")))  # top directory stripped
                self.assertFalse(os.path.exists(os.path.join(self.prefix, s["top"])))
                self.assertEqual(r.stdout, "")
                self.assertEqual(self.outside(), [])
                shutil.rmtree(self.prefix)
                os.makedirs(self.prefix)

    def test_a_wrong_checksum_aborts_with_no_partial_prefix(self):
        for tool in SPECS:
            with self.subTest(tool=tool):
                tb, sha = self.make_tarball(tool)
                r = self.install(tool, sha="0" * 64, tarball=tb)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("checksum", r.stderr)
                self.assertIn(sha, r.stderr)  # the computed one is shown
                self.assertEqual(os.listdir(self.prefix), [])
                self.assertEqual(self.outside(), [])

    def test_the_checksum_is_checked_before_anything_is_extracted(self):
        tb, sha = self.make_tarball("go")
        # a tarball that is not even a tarball but has the right checksum fails at extract, one with a wrong checksum fails before it
        bad = os.path.join(self.base, "bad.tgz")
        write(bad, "not a tarball")
        r = self.install("go", sha=sha, tarball=bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checksum", r.stderr)

    def test_a_missing_or_malformed_checksum_is_refused_before_downloading(self):
        for tool in SPECS:
            for sha in (None, "", "abc", "g" * 64):
                with self.subTest(tool=tool, sha=sha):
                    tb, _ = self.make_tarball(tool)
                    if os.path.exists(self.calls):
                        os.remove(self.calls)
                    r = self.install(tool, sha=sha, tarball=tb)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("TOOL_SHA256", r.stderr)
                    self.assertFalse(os.path.exists(self.calls))

    def test_the_url_uses_the_version_and_the_arch_name_of_the_vendor(self):
        for tool, s in SPECS.items():
            for arch, vendor in s["arch"].items():
                with self.subTest(tool=tool, arch=arch):
                    tb, sha = self.make_tarball(tool)
                    if os.path.exists(self.calls):
                        os.remove(self.calls)
                    r = self.install(tool, version="4.5.6", arch=arch, sha=sha, tarball=tb)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn(s["url"] % ("4.5.6", vendor), read(self.calls))
                    shutil.rmtree(self.prefix)
                    os.makedirs(self.prefix)

class ThroughSwarmboxToolTest(InstallBase):
    """The manifest's own checksum reaches the installer as TOOL_SHA256 for the host arch, and the real manifest validates."""

    def run_tool(self, *args, arch="amd64", image=None):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
               "SWARMBOX_TEST_IMAGE_TOOLS": image or REAL_TOOLS, "SWARMBOX_TEST_USER_TOOLS": os.path.join(self.base, "user"),
               "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"), "SWARMBOX_TEST_ARCH": arch,
               "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock"), "FAKE_CALLS": self.calls,
               "FAKE_TARBALL": self.tarball, "SWARMBOX_TEST_RUN_DIR": os.path.join(self.base, "run"), "TMPDIR": self.base}
        return subprocess.run(["bash", TOOL] + list(args), env=env, capture_output=True, text=True, timeout=60, cwd=self.base)

    def image_with(self, tool, sha_amd, sha_arm):
        image = os.path.join(self.base, "image")
        shutil.rmtree(image, ignore_errors=True)
        shutil.copytree(os.path.join(REAL_TOOLS, tool), os.path.join(image, tool))
        conf = os.path.join(image, tool, "tool.conf")
        text = re.sub(r"^SHA256_.*\n", "", read(conf), flags=re.M)
        write(conf, text + "SHA256_amd64=%s\nSHA256_arm64=%s\n" % (sha_amd, sha_arm))
        return image

    def test_install_passes_the_checksum_of_the_host_arch(self):
        for tool, s in SPECS.items():
            for arch in ("amd64", "arm64"):
                with self.subTest(tool=tool, arch=arch):
                    self.tarball, sha = self.make_tarball(tool)
                    other = "1" * 64
                    image = self.image_with(tool, sha if arch == "amd64" else other, sha if arch == "arm64" else other)
                    r = self.run_tool("install", tool, arch=arch, image=image)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertTrue(os.access(os.path.join(self.home, ".local", "share", "swarmbox", "tools", tool, "current", "bin",
                                                           s["names"][0]), os.X_OK))
                    shutil.rmtree(os.path.join(self.home, ".local"))

SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]


class GoShellTest(unittest.TestCase):
    SHSH = os.path.join(REAL_TOOLS, "go", "shell.sh")

    def run_in(self, shell, script, env_extra=None):
        d = tempfile.mkdtemp(prefix="gg-go-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": d}
        env.update(env_extra or {})
        r = subprocess.run([shell, "-c", ". %s; %s" % (self.SHSH, script)], env=env, capture_output=True, text=True, timeout=30, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return d, r.stdout.strip()

    def test_gopath_gocache_and_path(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                d, out = self.run_in(sh, 'echo "$GOPATH|$GOCACHE|$PATH"')
                self.assertEqual(out, "%s/go|%s/.cache/go-build|/usr/bin:/bin:%s/go/bin" % (d, d, d))

class ManifestTest(unittest.TestCase):
    def validate(self, path):
        return subprocess.run(["bash", TOOL, "validate", path], capture_output=True, text=True, timeout=60, cwd=ROOT,
                              env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "SWARMBOX_TEST_LIB": LIB})

    def test_the_real_tools_folder_validates(self):
        r = self.validate(REAL_TOOLS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for t in ("go", "gcloud"):
            self.assertIn(t, r.stdout)

    def test_the_real_manifests_carry_the_checksums_the_installers_need(self):
        for t in ("go", "gcloud"):
            self.assertIn("TOOL_SHA256", read(os.path.join(REAL_TOOLS, t, "install.sh")))

    def make(self, conf_extra, install="#!/bin/bash\nset -e\n: \"${TOOL_SHA256:?}\"\n"):
        d = tempfile.mkdtemp(prefix="gg-val-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        write(os.path.join(d, "demo", "tool.conf"), "SCHEMA=1\nNAME=demo\nKIND=tool\nPROVIDES=\"demo\"\nVERSION=1.0.0\n" + conf_extra)
        write(os.path.join(d, "demo", "install.sh"), install, 0o755)
        return d

    def test_an_installer_that_verifies_a_checksum_needs_both_in_the_manifest(self):
        h = "a" * 64
        r = self.validate(self.make(""))
        self.assertEqual(r.returncode, 1)
        self.assertIn("TOOL_SHA256", r.stdout + r.stderr)
        r = self.validate(self.make("SHA256_amd64=%s\n" % h))
        self.assertEqual(r.returncode, 1)
        self.assertIn("SHA256_arm64", r.stdout + r.stderr)
        r = self.validate(self.make("SHA256_arm64=%s\n" % h))
        self.assertEqual(r.returncode, 1)
        self.assertIn("SHA256_amd64", r.stdout + r.stderr)
        self.assertEqual(self.validate(self.make("SHA256_amd64=%s\nSHA256_arm64=%s\n" % (h, h))).returncode, 0)

if __name__ == "__main__":
    unittest.main()
