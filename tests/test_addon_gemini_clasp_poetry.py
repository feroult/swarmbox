"""The gemini, clasp and poetry addons.

install.sh runs against a FAKE npm and a FAKE curl serving a fake Poetry installer; the real npm, PyPI and network are NOT used here
(real installs are in tests/test_addon_real.py). Run with: python3 -W error tests/test_addon_gemini_clasp_poetry.py   (needs bash, jq; zsh is optional)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

REAL_ADDONS = os.path.join(ROOT, "container", "addons")
ADDON = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
LIB = os.path.join(ROOT, "container", "scripts")
NPM_ADDONS = {"gemini": ("@google/gemini-cli", "gemini"), "clasp": ("@google/clasp", "clasp")}

# fake npm: `npm install -g --prefix P PKG@V` makes P/bin/<name>; `npm cache clean --force` is recorded
FAKE_NPM = r"""#!/bin/bash
echo "npm $*" >> "$FAKE_CALLS"
[ "$1" = cache ] && exit "${FAKE_CACHE_EXIT:-0}"
[ "$1" = install ] || exit 2
[ -z "${FAKE_NPM_FAIL:-}" ] || { echo "npm ERR! network" >&2; exit 1; }
# like node-gyp compiling a native dependency (measured on gemini in 4b.7): it unpacks Node headers into its devdir
echo "devdir=${npm_config_devdir:-unset}" >> "$FAKE_CALLS"
echo "xdg=${XDG_DATA_HOME:-unset}|${XDG_STATE_HOME:-unset}|${XDG_CONFIG_HOME:-unset}|${XDG_CACHE_HOME:-unset}" >> "$FAKE_CALLS"
[ -z "${npm_config_devdir:-}" ] || { mkdir -p "$npm_config_devdir/24.0.0"; echo hdr > "$npm_config_devdir/24.0.0/node.h"; }
shift
while [ $# -gt 0 ]; do case "$1" in --prefix) prefix=$2; shift 2 ;; -g) shift ;; *) pkg=$1; shift ;; esac; done
[ -z "${FAKE_NO_BIN:-}" ] || exit 0
name=${pkg##*/}; name=${name%@*}; name=${name%-cli}
mkdir -p "$prefix/bin" "$prefix/lib/node_modules/${pkg%@*}"
printf '#!/bin/sh\necho "%s fake ${pkg##*@}"\n' "$name" > "$prefix/bin/$name"; chmod +x "$prefix/bin/$name"
"""
# fake curl serves a python "installer" that, like the real one, installs below POETRY_HOME and (like a careless one) can write caches
FAKE_CURL = r"""#!/bin/bash
echo "curl $*" >> "$FAKE_CALLS"
[ -z "${FAKE_CURL_FAIL:-}" ] || exit 22
cat <<'PY'
import os, sys
args = sys.argv[1:]
version = args[args.index("--version") + 1]
home = os.environ["POETRY_HOME"]
open(os.environ["FAKE_CALLS"], "a").write("installer args=%s POETRY_HOME=%s PIP_NO_CACHE_DIR=%s\n" % (args, home, os.environ.get("PIP_NO_CACHE_DIR")))
os.makedirs(home + "/bin", exist_ok=True)
p = home + "/bin/poetry"
open(p, "w").write('#!/bin/sh\necho "Poetry (version %s)"\n' % version)
os.chmod(p, 0o755)
if os.environ.get("FAKE_WRITE_CACHE"):
    for d in (os.environ["XDG_CACHE_HOME"], os.environ["XDG_CONFIG_HOME"]):
        os.makedirs(d, exist_ok=True); open(d + "/x", "w").write("x")
print("fake installer stdout")
PY
"""


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read()


def manifest(name):
    """[VERSION, UPDATE, PORTS, COMMANDS, UPDATE_CMD] of a real manifest"""
    out = subprocess.run(["bash", "-c", ". %s/%s/addon.conf; echo \"$VERSION|${UPDATE:-managed}|${PORTS:-}|$COMMANDS|${UPDATE_CMD:-}\""
                          % (REAL_ADDONS, name)], capture_output=True, text=True).stdout.strip()
    return out.split("|")


class InstallBase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="gcp-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.prefix = os.path.join(self.base, "prefix")
        self.home = os.path.join(self.base, "home")
        self.fakebin = os.path.join(self.base, "fakebin")
        self.calls = os.path.join(self.base, "calls.txt")
        os.makedirs(self.prefix)
        os.makedirs(self.home)
        write(os.path.join(self.fakebin, "npm"), FAKE_NPM, 0o755)
        write(os.path.join(self.fakebin, "curl"), FAKE_CURL, 0o755)

    def install(self, addon, version, **extra):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "ADDON_PREFIX": self.prefix, "TMPDIR": self.base,
               "ADDON_ARCH": "amd64", "FAKE_CALLS": self.calls}
        if version is not None:
            env["ADDON_VERSION"] = version
        env.update(extra)
        return subprocess.run(["bash", os.path.join(REAL_ADDONS, addon, "install.sh")], env=env, capture_output=True, text=True,
                              timeout=60, cwd=self.home)

    def outside(self):
        """Every file the install made outside the prefix, apart from the fakes' own bookkeeping."""
        found = []
        for root, dirs, files in os.walk(self.base):
            if root.startswith(self.prefix) or root.startswith(self.fakebin):
                continue
            for f in files + dirs:
                p = os.path.join(root, f)
                if p not in (self.calls, self.prefix, self.fakebin):
                    found.append(os.path.relpath(p, self.base))
        return sorted(f for f in found if f not in ("home", "prefix", "fakebin", "calls.txt"))


class NpmAddonInstallTest(InstallBase):
    def test_installs_the_package_under_the_prefix_and_cleans_the_cache(self):
        for addon, (pkg, cmd) in NPM_ADDONS.items():
            with self.subTest(addon=addon):
                r = self.install(addon, "9.8.7")
                self.assertEqual(r.returncode, 0, r.stderr)
                calls = read(self.calls).splitlines()
                self.assertIn("npm install -g --prefix %s %s@9.8.7" % (self.prefix, pkg), calls)
                self.assertEqual(calls[-1], "npm cache clean --force")
                self.assertTrue(os.access(os.path.join(self.prefix, "bin", cmd), os.X_OK))
                self.assertEqual(r.stdout, "")  # stdout belongs to the addon
                os.remove(self.calls)

    def test_the_version_comes_from_the_caller_and_latest_is_passed_through(self):
        r = self.install("gemini", "latest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("@google/gemini-cli@latest", read(self.calls))
        r = self.install("gemini", None)  # no ADDON_VERSION at all: the installer falls back to latest
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_writes_nothing_outside_the_prefix(self):
        for addon in NPM_ADDONS:
            with self.subTest(addon=addon):
                self.assertEqual(self.install(addon, "1.2.3").returncode, 0)
                self.assertEqual(self.outside(), [])

    def test_a_failing_npm_fails_the_install(self):
        for addon in NPM_ADDONS:
            with self.subTest(addon=addon):
                self.assertNotEqual(self.install(addon, "1.2.3", FAKE_NPM_FAIL="1").returncode, 0)

class PoetryInstallTest(InstallBase):
    def test_runs_the_official_installer_with_the_version_and_poetry_home_under_the_prefix(self):
        r = self.install("poetry", "2.5.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = read(self.calls)
        self.assertIn("curl -fsSL https://install.python-poetry.org", calls)
        self.assertIn("installer args=['--version', '2.5.1'] POETRY_HOME=%s PIP_NO_CACHE_DIR=1" % self.prefix, calls)
        self.assertIn("(version 2.5.1)", subprocess.run([os.path.join(self.prefix, "bin", "poetry")], capture_output=True, text=True).stdout)
        self.assertNotIn("fake installer stdout", r.stdout)  # stdout is empty, progress goes to stderr
        self.assertIn("fake installer stdout", r.stderr)

    def test_a_failed_download_fails_and_runs_nothing(self):
        r = self.install("poetry", "2.5.1", FAKE_CURL_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("installer args", read(self.calls))
        self.assertEqual(os.listdir(self.prefix), [])

class ThroughSwarmboxAddonTest(InstallBase):
    def run_addon(self, *args):
        image = os.path.join(self.base, "image")
        for t in ("gemini", "clasp", "poetry"):
            if not os.path.isdir(os.path.join(image, t)):
                shutil.copytree(os.path.join(REAL_ADDONS, t), os.path.join(image, t))
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
               "SWARMBOX_TEST_IMAGE_ADDONS": image, "SWARMBOX_TEST_USER_ADDONS": os.path.join(self.base, "user"),
               "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"), "SWARMBOX_TEST_ARCH": "amd64",
               "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock"), "FAKE_CALLS": self.calls,
               "SWARMBOX_TEST_RUN_DIR": os.path.join(self.base, "run"), "TMPDIR": self.base}
        return subprocess.run(["bash", ADDON] + list(args), env=env, capture_output=True, text=True, timeout=60, cwd=self.base)

    def addons(self, name):
        return os.path.join(self.home, ".local", "share", "swarmbox", "addons", name)

    def test_versions_come_from_the_manifest(self):
        expect = {a: manifest(a)[0] for a in ("gemini", "clasp", "poetry")}
        for addon, version in expect.items():
            with self.subTest(addon=addon):
                r = self.run_addon("install", addon)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(os.readlink(os.path.join(self.addons(addon), "current")), version)
                self.assertTrue(os.access(os.path.join(self.addons(addon), "current", "bin", addon), os.X_OK))
        self.assertIn("@google/clasp@" + expect["clasp"], read(self.calls))
        self.assertIn("['--version', '%s']" % expect["poetry"], read(self.calls))

class ManifestTest(unittest.TestCase):
    def test_the_real_addons_folder_validates_with_all_five(self):
        r = subprocess.run(["bash", ADDON, "validate", REAL_ADDONS], capture_output=True, text=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "SWARMBOX_TEST_LIB": LIB}, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for t in ("claude", "opencode", "gemini", "clasp", "poetry"):
            self.assertIn(t, r.stdout)

    def test_latest_updates_itself_and_every_other_version_is_pinned_and_managed(self):
        for t in sorted(os.listdir(REAL_ADDONS)):
            version, update, _, _, update_cmd = manifest(t)
            with self.subTest(addon=t):
                if version == "latest":
                    self.assertEqual(update, "self")
                    self.assertNotEqual(update_cmd, "")
                else:
                    self.assertEqual(update, "managed")
                    self.assertRegex(version, r"^\d+\.\d+(\.\d+)?$")

class PortsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="gcp-ports-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_addon_ports_lists_43323_once_for_clasp_and_nothing_else(self):
        d = self.d
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_IMAGE_ADDONS": REAL_ADDONS,
               "SWARMBOX_TEST_USER_ADDONS": os.path.join(d, "u"), "SWARMBOX_TEST_HOST_DIR": os.path.join(d, "host"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(d, "shims")}
        r = subprocess.run(["bash", ADDON, "link", "--system"], env=env, capture_output=True, text=True, timeout=60, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(os.path.join(d, "host", "addon-ports")), "clasp\t43323\n")
        for c in ("gemini", "clasp", "poetry"):
            self.assertTrue(os.path.lexists(os.path.join(d, "shims", c)), c)


import test_host_create_flags as _hcf  # noqa: E402


class ClaspPortPublishedTest(_hcf.Base):
    """The real addon-ports of this image level, handed to the 3.2 helper: WITH=clasp publishes 43323 on 127.0.0.1 only."""

    def real_addon_ports(self):
        d = tempfile.mkdtemp(prefix="gcp-tp-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_IMAGE_ADDONS": REAL_ADDONS,
               "SWARMBOX_TEST_USER_ADDONS": os.path.join(d, "u"), "SWARMBOX_TEST_HOST_DIR": os.path.join(d, "host"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(d, "shims")}
        subprocess.run(["bash", ADDON, "link", "--system"], env=env, check=True, capture_output=True, timeout=60, cwd=d)
        return read(os.path.join(d, "host", "addon-ports"))

    def test_with_clasp_publishes_43323_and_without_it_does_not(self):
        self.make_helper(self.real_addon_ports())
        ps = _hcf.values(self.flags(env={"SWARMBOX_WITH": "clasp"}), "-p")
        self.assertEqual(sorted(p for p in ps if not p.endswith(":7681")), ["127.0.0.1:43323:43323"])
        ps = _hcf.values(self.flags(env={"SWARMBOX_WITH": "gemini,poetry"}), "-p")
        self.assertEqual(ps, ["127.0.0.1:7681:7681"])


SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]


class ClaspShellTest(unittest.TestCase):
    SHSH = os.path.join(REAL_ADDONS, "clasp", "shell.sh")

    def run_in(self, shell, args):
        d = tempfile.mkdtemp(prefix="gcp-clasp-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        write(os.path.join(d, "bin", "clasp"), '#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done; echo\n', 0o755)
        env = {"PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "HOME": d}
        r = subprocess.run([shell, "-c", ". %s; clasp %s" % (self.SHSH, args)], env=env, capture_output=True, text=True, timeout=30, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_login_gets_the_redirect_port_exactly_once(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "login"), "[login][--redirect-port][43323]")

    def test_a_login_that_names_its_own_port_is_untouched(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "login --redirect-port 5555"), "[login][--redirect-port][5555]")
                self.assertEqual(self.run_in(sh, "login --redirect-port=5555"), "[login][--redirect-port=5555]")

if __name__ == "__main__":
    unittest.main()
