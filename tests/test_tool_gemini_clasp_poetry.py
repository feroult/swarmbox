"""Slice 4b.3: the gemini, clasp and poetry tools (design 6.3, 6.4, 6.6, 6.12; D3, D21).

install.sh runs against a FAKE npm and a FAKE curl serving a fake Poetry installer; the real npm, PyPI and network are NOT used here
(real installs are slice 4b.7). Run with: python3 -W error tests/test_tool_gemini_clasp_poetry.py   (needs bash, jq; zsh is optional)
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

REAL_TOOLS = os.path.join(ROOT, "container", "tools")
TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")
FRAGMENT = os.path.join(ROOT, "container", "config", "bashrc.sh")
NPM_TOOLS = {"gemini": ("@google/gemini-cli", "gemini"), "clasp": ("@google/clasp", "clasp")}

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
    out = subprocess.run(["bash", "-c", ". %s/%s/tool.conf; echo \"$KIND|$PROVIDES|$VERSION|${UPDATE:-managed}|${YOLO_FLAGS:-}|"
                          "${PORTS:-}|${MCP_FLAGS:-}|${YOLO_ALIAS:-}\"" % (REAL_TOOLS, name)], capture_output=True, text=True).stdout.strip()
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

    def install(self, tool, version, **extra):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "TOOL_PREFIX": self.prefix, "TMPDIR": self.base,
               "TOOL_ARCH": "amd64", "FAKE_CALLS": self.calls}
        if version is not None:
            env["TOOL_VERSION"] = version
        env.update(extra)
        return subprocess.run(["bash", os.path.join(REAL_TOOLS, tool, "install.sh")], env=env, capture_output=True, text=True,
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


class NpmToolInstallTest(InstallBase):
    def test_installs_the_package_under_the_prefix_and_cleans_the_cache(self):
        for tool, (pkg, cmd) in NPM_TOOLS.items():
            with self.subTest(tool=tool):
                r = self.install(tool, "9.8.7")
                self.assertEqual(r.returncode, 0, r.stderr)
                calls = read(self.calls).splitlines()
                self.assertIn("npm install -g --prefix %s %s@9.8.7" % (self.prefix, pkg), calls)
                self.assertEqual(calls[-1], "npm cache clean --force")
                self.assertTrue(os.access(os.path.join(self.prefix, "bin", cmd), os.X_OK))
                self.assertEqual(r.stdout, "")  # stdout belongs to the tool
                os.remove(self.calls)

    def test_the_version_comes_from_the_caller_and_latest_is_passed_through(self):
        r = self.install("gemini", "latest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("@google/gemini-cli@latest", read(self.calls))
        r = self.install("gemini", None)  # no TOOL_VERSION at all: an agent defaults to latest
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_pinned_tool_without_a_version_is_refused(self):
        r = self.install("clasp", None)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(self.calls))

    def test_writes_nothing_outside_the_prefix(self):
        for tool in NPM_TOOLS:
            with self.subTest(tool=tool):
                self.assertEqual(self.install(tool, "1.2.3").returncode, 0)
                self.assertEqual(self.outside(), [])

    def test_node_gyp_headers_go_to_a_scratch_dir_that_is_removed(self):
        """Measured in 4b.7: gemini's native dependency makes node-gyp download Node headers into ~/.cache/node-gyp (2811 files)."""
        for tool in NPM_TOOLS:
            with self.subTest(tool=tool):
                self.assertEqual(self.install(tool, "1.2.3").returncode, 0)
                lines = [l for l in read(self.calls).splitlines() if l.startswith("devdir=")]
                self.assertEqual(len(lines), 1, lines)
                devdir = lines[0][len("devdir="):]
                self.assertNotEqual(devdir, "unset")
                self.assertFalse(devdir.startswith(self.home), devdir)  # not in the home
                self.assertFalse(os.path.exists(devdir), "the scratch devdir was left behind")
                xdg = [l for l in read(self.calls).splitlines() if l.startswith("xdg=")][0][4:].split("|")
                for d in xdg:  # a postinstall that runs the program writes its data and logs here, not in the home
                    self.assertNotEqual(d, "unset")
                    self.assertFalse(d.startswith(self.home), d)
                    self.assertFalse(os.path.exists(d))
                self.assertEqual(self.outside(), [])
                os.remove(self.calls)

    def test_a_failing_npm_fails_the_install(self):
        for tool in NPM_TOOLS:
            with self.subTest(tool=tool):
                self.assertNotEqual(self.install(tool, "1.2.3", FAKE_NPM_FAIL="1").returncode, 0)

    def test_a_missing_program_fails_the_install(self):
        for tool in NPM_TOOLS:
            with self.subTest(tool=tool):
                r = self.install(tool, "1.2.3", FAKE_NO_BIN="1")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("missing", r.stderr)

    def test_a_failing_cache_clean_is_only_a_warning(self):
        r = self.install("clasp", "1.2.3", FAKE_CACHE_EXIT="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning", r.stderr)

    def test_the_package_name_is_one_variable(self):
        for tool, (pkg, _) in NPM_TOOLS.items():
            text = read(os.path.join(REAL_TOOLS, tool, "install.sh"))
            self.assertEqual([l for l in text.splitlines() if l.startswith("PACKAGE=")], ['PACKAGE="%s"' % pkg])


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

    def test_writes_nothing_outside_the_prefix_even_if_the_installer_writes_caches(self):
        r = self.install("poetry", "2.5.1", FAKE_WRITE_CACHE="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.outside(), [])  # the caches went to a private folder that is gone
        self.assertEqual(os.listdir(self.home), [])

    def test_a_failed_download_fails_and_runs_nothing(self):
        r = self.install("poetry", "2.5.1", FAKE_CURL_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("installer args", read(self.calls))
        self.assertEqual(os.listdir(self.prefix), [])

    def test_no_version_is_refused(self):
        self.assertNotEqual(self.install("poetry", None).returncode, 0)

    def test_the_installed_program_must_run(self):
        # an installer that leaves a poetry which fails: the install must fail
        write(os.path.join(self.fakebin, "curl"), FAKE_CURL.replace("echo \"Poetry", "exit 3; echo \"Poetry"), 0o755)
        r = self.install("poetry", "2.5.1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not run", r.stderr)


class ThroughSwarmboxToolTest(InstallBase):
    def run_tool(self, *args):
        image = os.path.join(self.base, "image")
        for t in ("gemini", "clasp", "poetry"):
            if not os.path.isdir(os.path.join(image, t)):
                shutil.copytree(os.path.join(REAL_TOOLS, t), os.path.join(image, t))
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
               "SWARMBOX_TEST_IMAGE_TOOLS": image, "SWARMBOX_TEST_USER_TOOLS": os.path.join(self.base, "user"),
               "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"), "SWARMBOX_TEST_ARCH": "amd64",
               "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock"), "FAKE_CALLS": self.calls,
               "SWARMBOX_TEST_RUN_DIR": os.path.join(self.base, "run"), "TMPDIR": self.base}
        return subprocess.run(["bash", TOOL] + list(args), env=env, capture_output=True, text=True, timeout=60, cwd=self.base)

    def tools(self, name):
        return os.path.join(self.home, ".local", "share", "swarmbox", "tools", name)

    def test_versions_come_from_the_manifest(self):
        expect = {"gemini": "latest", "clasp": manifest("clasp")[2], "poetry": manifest("poetry")[2]}
        for tool, version in expect.items():
            with self.subTest(tool=tool):
                r = self.run_tool("install", tool)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(os.readlink(os.path.join(self.tools(tool), "current")), version)
                self.assertTrue(os.access(os.path.join(self.tools(tool), "current", "bin", tool), os.X_OK))
        self.assertIn("@google/clasp@" + expect["clasp"], read(self.calls))
        self.assertIn("['--version', '%s']" % expect["poetry"], read(self.calls))

    def test_poetry_home_is_not_in_the_home_outside_the_tool_prefix(self):
        self.assertEqual(self.run_tool("install", "poetry").returncode, 0)
        top = sorted(os.listdir(self.home))
        self.assertEqual(top, [".local"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.home, ".local"))), ["share"])
        self.assertEqual(os.listdir(os.path.join(self.home, ".local", "share")), ["swarmbox"])

    def test_the_shim_runs_the_fake_installed_poetry(self):
        shims = os.path.join(self.base, "shims")
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
               "SWARMBOX_TEST_IMAGE_TOOLS": REAL_TOOLS, "SWARMBOX_TEST_USER_TOOLS": os.path.join(self.base, "user"),
               "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"), "SWARMBOX_TEST_IMAGE_SHIMS": shims,
               "SWARMBOX_TEST_ARCH": "amd64", "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock"), "FAKE_CALLS": self.calls,
               "SWARMBOX_TEST_RUN_DIR": os.path.join(self.base, "run"), "TMPDIR": self.base}
        r = subprocess.run(["bash", TOOL, "link", "--system"], env=env, capture_output=True, text=True, timeout=60, cwd=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.lexists(os.path.join(shims, "poetry")))
        # first call through the shim installs (fake) and runs the program
        # the symlink points at /usr/local/lib/swarmbox (absent here): aim it at the real dispatcher of the repository
        os.remove(os.path.join(shims, "poetry"))
        os.symlink(os.path.join(LIB, "swarmbox-shim.sh"), os.path.join(shims, "poetry"))
        os.makedirs(os.path.join(self.base, "ushims"))
        env.update({"SWARMBOX_TEST_USER_SHIMS": os.path.join(self.base, "ushims"), "SWARMBOX_TEST_TOOL": TOOL})
        env["PATH"] = ":".join([os.path.join(self.home, ".local", "bin"), os.path.join(self.base, "ushims"), shims, self.fakebin, "/usr/bin", "/bin"])
        r = subprocess.run([os.path.join(shims, "poetry"), "--version"], env=env, capture_output=True, text=True, timeout=60, cwd=self.base)
        self.assertIn("Poetry (version %s)" % manifest("poetry")[2], r.stdout, r.stderr)
        self.assertIn("installer args", read(self.calls))  # the fake installer ran, not the network
        self.assertEqual(r.returncode, 0, r.stderr)


class ManifestTest(unittest.TestCase):
    def test_the_real_tools_folder_validates_with_all_five(self):
        r = subprocess.run(["bash", TOOL, "validate", REAL_TOOLS], capture_output=True, text=True, timeout=60,
                           env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "SWARMBOX_TEST_LIB": LIB}, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for t in ("claude", "opencode", "gemini", "clasp", "poetry"):
            self.assertIn(t, r.stdout)

    def test_agents_are_latest_and_the_others_are_pinned(self):
        for t in sorted(os.listdir(REAL_TOOLS)):
            kind, _, version = manifest(t)[:3]
            with self.subTest(tool=t):
                if kind == "agent":
                    self.assertEqual(version, "latest")
                else:
                    self.assertEqual(kind, "tool")
                    self.assertRegex(version, r"^\d+\.\d+(\.\d+)?$")

    def test_provides_names_are_unique_across_tools(self):
        seen = []
        for t in sorted(os.listdir(REAL_TOOLS)):
            seen += manifest(t)[1].split()
        self.assertEqual(len(seen), len(set(seen)), seen)

    def test_manifest_values(self):
        self.assertEqual(manifest("gemini"), ["agent", "gemini", "latest", "managed", "--yolo", "", "", ""])
        self.assertEqual(manifest("clasp")[:2] + manifest("clasp")[3:], ["tool", "clasp", "managed", "", "43323", "", ""])
        self.assertEqual(manifest("poetry")[:2] + manifest("poetry")[3:], ["tool", "poetry", "managed", "", "", "", ""])

    def test_files_and_modes(self):
        for t, files in (("gemini", ("install.sh", "tool.conf")), ("clasp", ("install.sh", "shell.sh", "tool.conf")),
                         ("poetry", ("install.sh", "tool.conf"))):
            for f in files:
                self.assertTrue(os.path.isfile(os.path.join(REAL_TOOLS, t, f)), t + "/" + f)
            self.assertTrue(os.access(os.path.join(REAL_TOOLS, t, "install.sh"), os.X_OK))
        for t in ("gemini", "poetry"):
            self.assertFalse(os.path.exists(os.path.join(REAL_TOOLS, t, "shell.sh")), "design 6.12: no environment set")


class PortsTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="gcp-ports-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def test_tool_ports_lists_43323_once_for_clasp_and_nothing_else(self):
        d = self.d
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_IMAGE_TOOLS": REAL_TOOLS,
               "SWARMBOX_TEST_USER_TOOLS": os.path.join(d, "u"), "SWARMBOX_TEST_HOST_DIR": os.path.join(d, "host"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(d, "shims")}
        r = subprocess.run(["bash", TOOL, "link", "--system"], env=env, capture_output=True, text=True, timeout=60, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(os.path.join(d, "host", "tool-ports")), "clasp\t43323\n")
        for c in ("gemini", "clasp", "poetry"):
            self.assertTrue(os.path.lexists(os.path.join(d, "shims", c)), c)


import test_host_create_flags as _hcf  # noqa: E402


class ClaspPortPublishedTest(_hcf.Base):
    """The real tool-ports of this image level, handed to the 3.2 helper: WITH=clasp publishes 43323 on 127.0.0.1 only."""

    def real_tool_ports(self):
        d = tempfile.mkdtemp(prefix="gcp-tp-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_IMAGE_TOOLS": REAL_TOOLS,
               "SWARMBOX_TEST_USER_TOOLS": os.path.join(d, "u"), "SWARMBOX_TEST_HOST_DIR": os.path.join(d, "host"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(d, "shims")}
        subprocess.run(["bash", TOOL, "link", "--system"], env=env, check=True, capture_output=True, timeout=60, cwd=d)
        return read(os.path.join(d, "host", "tool-ports"))

    def test_with_clasp_publishes_43323_and_without_it_does_not(self):
        self.make_helper(self.real_tool_ports())
        ps = _hcf.values(self.flags(env={"SWARMBOX_WITH": "clasp"}), "-p")
        self.assertEqual(sorted(p for p in ps if not p.endswith(":7681")), ["127.0.0.1:43323:43323"])
        ps = _hcf.values(self.flags(env={"SWARMBOX_WITH": "gemini,poetry"}), "-p")
        self.assertEqual(ps, ["127.0.0.1:7681:7681"])


SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]


class ClaspShellTest(unittest.TestCase):
    SHSH = os.path.join(REAL_TOOLS, "clasp", "shell.sh")

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

    def test_login_keeps_its_other_arguments(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "login --no-localhost 'a b'"),
                                 "[login][--redirect-port][43323][--no-localhost][a b]")

    def test_a_login_that_names_its_own_port_is_untouched(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "login --redirect-port 5555"), "[login][--redirect-port][5555]")
                self.assertEqual(self.run_in(sh, "login --redirect-port=5555"), "[login][--redirect-port=5555]")

    def test_other_subcommands_are_untouched(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.assertEqual(self.run_in(sh, "push --force"), "[push][--force]")
                self.assertEqual(self.run_in(sh, "logout"), "[logout]")
                self.assertEqual(self.run_in(sh, "--version"), "[--version]")
                self.assertEqual(self.run_in(sh, ""), "")
                self.assertEqual(self.run_in(sh, "run login"), "[run][login]")

    def test_the_file_defines_one_function_and_sets_no_variable(self):
        text = read(self.SHSH)
        self.assertEqual(len(re.findall(r"^clasp\(\)", text, re.M)), 1)
        self.assertEqual(len(re.findall(r"^[A-Za-z_]+=", text, re.M)), 0)


class GeminiFragmentTest(unittest.TestCase):
    def run_frag(self, script, agent="gemini"):
        d = tempfile.mkdtemp(prefix="gcp-frag-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        write(os.path.join(d, "bin", "gemini"), '#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done; echo\n', 0o755)
        write(os.path.join(d, "banner.sh"), "#!/bin/sh\n", 0o755)
        env = {"PATH": os.path.join(d, "bin") + ":/usr/bin:/bin", "HOME": d, "XDG_CONFIG_HOME": os.path.join(d, "c"),
               "XDG_DATA_HOME": os.path.join(d, "d"), "XDG_STATE_HOME": os.path.join(d, "s"), "SWARMBOX_AGENT": agent,
               "SWARMBOX_IMAGE_TOOLS_DIR": REAL_TOOLS, "SWARMBOX_IMAGE_SHIMS_DIR": os.path.join(d, "shims"),
               "SWARMBOX_VENV": os.path.join(d, "no-venv"), "SWARMBOX_DIRS_SH": os.path.join(LIB, "dirs.sh"),
               "SWARMBOX_BANNER_SCRIPT": os.path.join(d, "banner.sh"), "SWARMBOX_STARSHIP_INIT": os.path.join(d, "none"),
               "TERM": "dumb"}
        os.makedirs(os.path.join(d, "s", "swarmbox"))
        r = subprocess.run(["bash", "--noprofile", "--norc", "-i"], input='. %s\n%s\nexit\n' % (FRAGMENT, script), env=env,
                           capture_output=True, text=True, timeout=30, cwd=d)
        return r.stdout

    def test_the_gemini_alias_uses_yolo(self):
        out = self.run_frag("alias gemini")
        self.assertIn("--yolo", out)
        self.assertRegex(out, r"alias gemini='?gemini --yolo")
        self.assertNotIn("mcp", out.lower())

    def test_yolo_runs_gemini_with_the_flag_and_no_mcp_flags(self):
        out = self.run_frag("yolo hello")
        self.assertEqual(out.strip().splitlines()[-1], "[--yolo][hello]")

    def test_clasp_and_poetry_get_no_alias(self):
        out = self.run_frag("alias clasp poetry 2>&1")
        self.assertNotIn("alias clasp=", out)
        self.assertNotIn("alias poetry=", out)

    def test_the_clasp_function_is_defined_by_the_fragment(self):
        out = self.run_frag("type clasp | head -n 1")
        self.assertIn("clasp is a function", out)


if __name__ == "__main__":
    unittest.main()
