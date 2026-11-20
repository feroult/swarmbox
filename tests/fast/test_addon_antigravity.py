"""The antigravity addon (command agy): its installer with a fake vendor server, and its manifest.

The real install (the vendor's release server) is in tests/slow/test_addon_real.py. Run with: python3 -W error tests/fast/test_addon_antigravity.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

ADDON = os.path.join(ROOT, "container", "addons", "antigravity")
INSTALL = os.path.join(ADDON, "install.sh")

# the fake vendor server: the manifest names the tarball by a path under FAKE_SERVER; every call is recorded
FAKE_CURL = r"""#!/bin/sh
echo "curl $*" >> "$FAKE_CALLS"
out=""
while [ $# -gt 0 ]; do
    case "$1" in -o) out=$2; shift ;; -*) ;; *) url=$1 ;; esac
    shift
done
[ -z "${FAKE_CURL_FAIL:-}" ] || exit 22
case "$url" in
    */manifests/*) f="$FAKE_SERVER/manifest.json" ;;
    *) f="$FAKE_SERVER/payload.tar.gz" ;;
esac
if [ -n "$out" ]; then cp "$f" "$out"; else cat "$f"; fi
"""
AGY = '#!/bin/sh\necho "1.2.3"\necho "$HOME" >> "$FAKE_CALLS"\n'


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="agy-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        self.prefix = os.path.join(self.base, "prefix")
        self.server = os.path.join(self.base, "server")
        self.fakebin = os.path.join(self.base, "fakebin")
        self.calls = os.path.join(self.base, "calls.txt")
        for d in (self.home, self.server, self.fakebin):
            os.makedirs(d)
        with open(self.calls, "w"):
            pass
        with open(os.path.join(self.fakebin, "curl"), "w") as f:
            f.write(FAKE_CURL)
        os.chmod(os.path.join(self.fakebin, "curl"), 0o755)
        self.publish()

    def publish(self, sha=None, url="https://example.invalid/agy/cli_linux_x64.tar.gz"):
        src = os.path.join(self.server, "antigravity")
        with open(src, "w") as f:
            f.write(AGY)
        os.chmod(src, 0o755)
        tgz = os.path.join(self.server, "payload.tar.gz")
        with tarfile.open(tgz, "w:gz") as t:
            t.add(src, arcname="antigravity")
        with open(tgz, "rb") as f:
            digest = hashlib.sha512(f.read()).hexdigest()
        with open(os.path.join(self.server, "manifest.json"), "w") as f:
            f.write('{\n  "version": "1.2.3",\n  "url": "%s",\n  "sha512": "%s"\n}\n' % (url, sha or digest))

    def install(self, version="latest", arch="amd64", **env):
        e = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "ADDON_PREFIX": self.prefix, "ADDON_ARCH": arch,
             "FAKE_SERVER": self.server, "FAKE_CALLS": self.calls, "TMPDIR": self.base}
        if version is not None:
            e["ADDON_VERSION"] = version
        e.update(env)
        return subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=60, cwd=self.base)

    def test_installs_agy_into_the_local_bin_and_records_it(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")  # stdout belongs to the addon
        agy = os.path.join(self.home, ".local", "bin", "agy")
        self.assertTrue(os.access(agy, os.X_OK))
        with open(os.path.join(self.prefix, "installed")) as f:
            self.assertEqual(f.read(), "requested=latest\nreported=1.2.3\narch=amd64\n")

    def test_the_manifest_asked_for_is_the_one_of_the_platform(self):
        self.assertEqual(self.install(arch="arm64").returncode, 0)
        with open(self.calls) as f:
            self.assertIn("/manifests/linux_arm64.json", f.read())

    def test_the_vendor_installer_is_never_run_and_nothing_else_is_written(self):
        self.assertEqual(self.install().returncode, 0)
        found = []
        for root, dirs, files in os.walk(self.base):
            if root.startswith((self.prefix, self.fakebin, self.server)):
                continue
            found += [os.path.relpath(os.path.join(root, n), self.base) for n in files + dirs]
        self.assertEqual(sorted(f for f in found if f not in ("home", "prefix", "fakebin", "server", "calls.txt")),
                         [os.path.join("home", ".local"), os.path.join("home", ".local", "bin"), os.path.join("home", ".local", "bin", "agy")])
        with open(self.calls) as f:
            self.assertNotIn("install.sh", f.read())

    def test_the_version_check_does_not_touch_the_home_of_the_user(self):
        self.assertEqual(self.install().returncode, 0)
        with open(self.calls) as f:
            homes = [line.strip() for line in f if line.startswith("/")]
        self.assertTrue(homes)
        self.assertNotIn(self.home, homes)

    def test_a_download_that_does_not_match_the_checksum_installs_nothing(self):
        self.publish(sha="0" * 128)
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHA-512", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "agy")))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "installed")))

    def test_a_url_that_is_not_https_is_refused(self):
        self.publish(url="http://example.invalid/agy.tar.gz")
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("https", r.stderr)

    def test_a_failing_download_fails_the_install(self):
        r = self.install(FAKE_CURL_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "installed")))

    def test_a_pinned_version_is_refused_because_the_vendor_offers_only_the_newest(self):
        r = self.install(version="1.0.0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("newest", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "agy")))

    def test_a_missing_version_falls_back_to_latest(self):
        self.assertEqual(self.install(version=None).returncode, 0)

    def test_an_unsupported_architecture_is_refused(self):
        self.assertNotEqual(self.install(arch="riscv64").returncode, 0)

    def test_a_running_agy_is_replaced_by_a_rename_and_not_overwritten(self):
        self.assertEqual(self.install().returncode, 0)
        agy = os.path.join(self.home, ".local", "bin", "agy")
        before = os.stat(agy).st_ino
        os.remove(self.calls)
        open(self.calls, "w").close()
        self.assertEqual(self.install().returncode, 0)
        self.assertNotEqual(os.stat(agy).st_ino, before)
        self.assertEqual([n for n in os.listdir(os.path.dirname(agy))], ["agy"])  # no temporary file is left


class StaticTest(unittest.TestCase):
    def test_the_installer_passes_bash_n_and_shellcheck(self):
        self.assertTrue(os.access(INSTALL, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", INSTALL]).returncode, 0)
        for f in (INSTALL, os.path.join(ADDON, "shell.sh")):
            if shutil.which("shellcheck"):
                r = subprocess.run(["shellcheck", "-s", "bash", f], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_the_manifest_is_a_self_updating_addon_named_antigravity_that_provides_agy(self):
        with open(os.path.join(ADDON, "addon.conf")) as f:
            text = f.read()
        for line in ("NAME=antigravity", 'COMMANDS="agy"', "VERSION=latest", "UPDATE=self", 'UPDATE_CMD="agy update"'):
            self.assertIn(line + "\n", text)

    def test_the_gemini_addon_says_it_is_deprecated(self):
        with open(os.path.join(ROOT, "container", "addons", "gemini", "addon.conf")) as f:
            self.assertRegex(f.read(), r'DESCRIPTION=".*(?i:deprecated).*antigravity')


if __name__ == "__main__":
    unittest.main()
