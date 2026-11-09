"""Slice 4a.3: `swarmbox-tool install`, `run`, `list`, `update` (design 6.4, 6.5, 6.7, 6.11; decisions D2, D3, D21).

All installers are fakes: scripts that record their environment and working directory, then write a fake program into
$TOOL_PREFIX (managed tools) or into ~/.local/bin under a temp HOME (UPDATE=self tools, like the vendor installer of Claude Code).
Nothing here touches the real home, the real tools folder or the real lock: the lock is moved with SWARMBOX_TEST_LOCK, the
architecture can be forced with SWARMBOX_TEST_ARCH, and HOME, TMPDIR and the manifest folders are temp folders (decision log [4a.3]).
Run with: python3 tests/test_tool_install.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_tool_link import tree_hash  # noqa: E402
from test_tool_manifest import make_tool  # noqa: E402

TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")

# The program the fake installers write: prints every argument as [arg] on its own line, exits with $DEMO_EXIT.
PROGRAM = r"""#!/bin/sh
if [ "$1" = update ] && [ -n "${FAKE_CALLS:-}" ]; then echo "update called with: $*" >> "$FAKE_CALLS"; exit "${UPDATE_EXIT:-0}"; fi
for a in "$@"; do printf '[%s]\n' "$a"; done
exit "${DEMO_EXIT:-0}"
"""

COMMON = r"""#!/bin/bash
set -eu
echo "$TOOL_PREFIX|$TOOL_VERSION|$TOOL_ARCH|${TOOL_SHA256:-}|$PWD|$HOME" >> "$FAKE_REC"
echo x >> "$FAKE_COUNT"
[ -z "${FAKE_SLEEP:-}" ] || sleep "$FAKE_SLEEP"
echo "INSTALLER-STDOUT-NOISE"
"""

PROG_WRITER = r"""cat > "$DEST" <<'PROG_EOF'
""" + PROGRAM + r"""PROG_EOF
chmod +x "$DEST"
"""

MANAGED = COMMON + r"""mkdir -p "$TOOL_PREFIX/bin"
echo partial > "$TOOL_PREFIX/partial.txt"
[ -z "${FAKE_FAIL:-}" ] || { echo "curl: could not resolve host" >&2; exit 1; }
DEST="$TOOL_PREFIX/bin/demo"
""" + PROG_WRITER

SELF = COMMON + r"""mkdir -p "$HOME/.local/bin" "$HOME/.local/share/selfy"
echo partial > "$HOME/.local/share/selfy/blob"
[ -z "${FAKE_FAIL:-}" ] || { echo "curl: could not resolve host" >&2; exit 1; }
DEST="$HOME/.local/bin/selfy"
rm -f "$DEST"
if [ -n "${FAKE_LINK_TO_SHIM:-}" ]; then
    ln -s "$FAKE_LINK_TO_SHIM" "$DEST"
else
""" + PROG_WRITER + r"""fi
echo "requested=$TOOL_VERSION" > "$TOOL_PREFIX/installed"
"""

SHA = r"""#!/bin/bash
set -eu
echo x >> "$FAKE_COUNT"
mkdir -p "$TOOL_PREFIX/bin"
cp "$FIXTURE_ARCHIVE" "$TOOL_PREFIX/download.tar.gz"
echo "$TOOL_SHA256  $TOOL_PREFIX/download.tar.gz" | sha256sum -c - >&2 || exit 1
DEST="$TOOL_PREFIX/bin/demo"
""" + PROG_WRITER

SELF_CONF = {"KIND": "agent", "VERSION": "latest", "UPDATE": "self", "UPDATE_CMD": '"selfy update"',
             "PROVIDES": '"selfy"'}


def all_paths(root):
    out = []
    for dp, dn, fn in os.walk(root):
        for n in dn + fn:
            out.append(os.path.join(dp, n))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="tool-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.home, self.image, self.user = j("home"), j("image"), j("user")
        self.tmp, self.lock = j("tmp"), j("run", "tools.lock")
        self.rec, self.count, self.calls = j("rec.txt"), j("count.txt"), j("calls.txt")
        for d in (self.home, self.image, self.user, self.tmp):
            os.makedirs(d)
        self.tools = os.path.join(self.home, ".local", "share", "swarmbox", "tools")

    def env(self, **extra):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.home, "TMPDIR": self.tmp, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_TOOLS": self.image, "SWARMBOX_TEST_USER_TOOLS": self.user,
             "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"),
             "SWARMBOX_TEST_LOCK": self.lock, "SWARMBOX_TEST_ARCH": "amd64",
             "FAKE_REC": self.rec, "FAKE_COUNT": self.count, "FAKE_CALLS": self.calls}
        e.update(extra)
        return e

    def tool(self, *args, env=None, **extra):
        return subprocess.run(["bash", TOOL, *args], env=env or self.env(**extra), capture_output=True, text=True,
                              timeout=60, cwd=self.base)

    def managed(self, name="demo", installer=MANAGED, level=None, **over):
        return make_tool(level or self.image, name, install=installer, PROVIDES='"demo"', **over)

    def selfy(self, installer=SELF, **over):
        conf = dict(SELF_CONF)
        conf.update(over)
        return make_tool(self.image, "selfy", install=installer, **conf)

    def installs(self):
        if not os.path.exists(self.count):
            return 0
        with open(self.count) as f:
            return len(f.read().split())

    def records(self):
        if not os.path.exists(self.rec):
            return []
        with open(self.rec) as f:
            return [line.rstrip("\n").split("|") for line in f if line.strip()]

    def write_program(self, content, version="1.2.3"):
        with open(os.path.join(self.tools, "demo", version, "bin", "demo"), "w") as f:
            f.write(content)


class InstallManaged(Base):
    def test_passes_prefix_version_arch_and_runs_in_home(self):
        self.managed()
        r = self.tool("install", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.records()
        self.assertEqual(rec[0], os.path.join(self.tools, "demo", "1.2.3"))
        self.assertEqual(rec[1], "1.2.3")
        self.assertEqual(rec[2], "amd64")
        self.assertEqual(rec[4], self.home)
        self.assertEqual(rec[5], self.home)

    def test_arch_from_uname_m(self):
        fake = os.path.join(self.base, "fakebin")
        os.makedirs(fake)
        for machine, want in (("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64"), ("amd64", "amd64")):
            with self.subTest(machine=machine):
                with open(os.path.join(fake, "uname"), "w") as f:
                    f.write("#!/bin/sh\necho %s\n" % machine)
                os.chmod(os.path.join(fake, "uname"), 0o755)
                shutil.rmtree(self.tools, ignore_errors=True)
                self.managed()
                env = self.env(PATH=fake + ":/usr/bin:/bin")
                del env["SWARMBOX_TEST_ARCH"]
                r = self.tool("install", "demo", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.records()[-1][2], want)

    def test_failure_leaves_nothing_and_the_next_call_retries(self):
        self.managed()
        before = tree_hash(self.home)
        r = self.tool("install", "demo", FAKE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not resolve host", r.stderr)
        self.assertIn("demo", r.stderr)
        self.assertEqual(tree_hash(self.home), before)
        self.assertFalse(os.path.lexists(os.path.join(self.tools, "demo", "current")))
        r = self.tool("install", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.installs(), 2)
        self.assertTrue(os.path.islink(os.path.join(self.tools, "demo", "current")))

    def test_version_installs_side_by_side_and_moves_current(self):
        self.managed()
        self.tool("install", "demo")
        r = self.tool("install", "demo", "--version", "2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.tools, "demo")
        self.assertEqual(sorted(os.listdir(d)), ["1.2.3", "2.0.0", "current"])
        self.assertEqual(os.readlink(os.path.join(d, "current")), "2.0.0")
        self.assertEqual(self.records()[-1][1], "2.0.0")
        # asking again for the older installed version only moves the link, the installer does not run
        r = self.tool("install", "demo", "--version", "1.2.3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(os.path.join(d, "current")), "1.2.3")
        self.assertEqual(self.installs(), 2)

    def test_force_reinstalls(self):
        self.managed()
        self.tool("install", "demo")
        r = self.tool("install", "demo", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.installs(), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.tools, "demo", "current", "bin", "demo")))

    def test_sha256_mismatch_aborts_and_removes_files(self):
        arch = os.path.join(self.base, "fixture.tar.gz")
        with open(arch, "wb") as f:
            f.write(b"fixture archive bytes\n")
        self.managed(installer=SHA, SHA256_amd64="0" * 64, SHA256_arm64="1" * 64)
        before = tree_hash(self.home)
        r = self.tool("install", "demo", FIXTURE_ARCHIVE=arch)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAILED", r.stderr)  # sha256sum -c said so
        self.assertEqual(tree_hash(self.home), before)

    def test_sha256_match_installs_and_the_installer_gets_the_arch_checksum(self):
        arch = os.path.join(self.base, "fixture.tar.gz")
        with open(arch, "wb") as f:
            f.write(b"fixture archive bytes\n")
        good = hashlib.sha256(b"fixture archive bytes\n").hexdigest()
        self.managed(installer=SHA, SHA256_amd64=good, SHA256_arm64="1" * 64)
        r = self.tool("install", "demo", FIXTURE_ARCHIVE=arch)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.tool("install", "demo", "--force", FIXTURE_ARCHIVE=arch, SWARMBOX_TEST_ARCH="arm64")
        self.assertNotEqual(r.returncode, 0)  # the arm64 checksum is wrong for this archive

class InstallSelf(Base):
    def setUp(self):
        super().setUp()
        self.selfy()
        self.record = os.path.join(self.tools, "selfy", "self")
        self.launcher = os.path.join(self.home, ".local", "bin", "selfy")

    def test_install_writes_the_record_dir_and_the_program_outside_it(self):
        r = self.tool("install", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.records()
        self.assertEqual(rec[1], "latest")
        self.assertTrue(os.path.isfile(os.path.join(self.record, ".swarmbox-env")))
        self.assertTrue(os.path.isfile(os.path.join(self.record, "installed")))  # written by the installer into TOOL_PREFIX
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertEqual(os.listdir(os.path.join(self.tools, "selfy")), ["self"])  # no current link, no versions, no staging

    def test_update_runs_update_cmd_with_the_real_binary(self):
        self.tool("install", "selfy")
        r = self.tool("update", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.calls) as f:
            self.assertEqual(f.read().strip(), "update called with: update")

class Run(Base):
    def test_not_installed_triggers_install_then_exec(self):
        self.managed()
        r = self.tool("run", "demo", "demo", "--", "a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "[a]\n")  # only the tool's stdout
        self.assertIn("Installing demo (first use)...", r.stderr)
        r = self.tool("run", "demo", "demo", "--", "b")
        self.assertEqual(r.stdout, "[b]\n")
        self.assertNotIn("Installing", r.stderr)
        self.assertEqual(self.installs(), 1)

class Concurrency(Base):
    def test_two_installs_at_once_run_the_installer_once(self):
        self.managed()
        env = self.env(FAKE_SLEEP="1.5")
        procs = [subprocess.Popen(["bash", TOOL, "install", "demo"], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, cwd=self.base) for _ in range(2)]
        outs = [p.communicate(timeout=60) for p in procs]
        for p, (_, err) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(self.installs(), 1)
        self.assertTrue(any("already installed" in err for _, err in outs), outs)

class ListAndLater(Base):
    def test_list_shows_both_levels_and_the_state(self):
        self.managed()
        self.selfy()
        self.managed(name="other", level=self.user)
        self.tool("install", "demo")
        r = self.tool("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {line.split()[0]: line for line in r.stdout.splitlines()[1:]}
        self.assertEqual(sorted(rows), ["demo", "other", "selfy"])
        self.assertIn("1.2.3", rows["demo"])
        self.assertIn("not installed", rows["other"])
        self.assertIn("not installed", rows["selfy"])
        self.tool("install", "selfy")
        r = self.tool("list")
        self.assertIn("installed (self)", [x for x in r.stdout.splitlines() if x.startswith("selfy")][0])
        self.assertEqual(self.tool("list", "extra").returncode, 64)

if __name__ == "__main__":
    unittest.main()
