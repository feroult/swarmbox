"""`swarmbox-addon prepare` and the prepare.sh run after an install.

Fake addons whose prepare.sh succeeds, fails, hangs or is absent, in a mktemp tree (HOME, manifests, lock). Nothing touches the real
home, addons folder or lock. Run with: python3 -W error tests/fast/test_addon_prepare.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
from addon_support import ADDON, Base, LIB, make_addon  # noqa: E402

ADDON = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
LIB = os.path.join(ROOT, "container", "scripts")

PREPARE_OK = r"""#!/bin/bash
echo "$SWARMBOX_ADDON_NAME|$PWD|$HOME|$SWARMBOX_ADDON_DIR" >> "$MARKS/$SWARMBOX_ADDON_NAME.mark"
echo "$SWARMBOX_ADDON_NAME" >> "$MARKS/order"
if [ -t 0 ]; then echo tty >> "$MARKS/$SWARMBOX_ADDON_NAME.mark"; fi
echo "STDOUT-NOISE from $SWARMBOX_ADDON_NAME"
echo "stderr line from $SWARMBOX_ADDON_NAME" >&2
"""
PREPARE_FAIL = PREPARE_OK + 'echo "boom" >&2\nexit 3\n'
PREPARE_HANG = r"""#!/bin/bash
echo "$SWARMBOX_ADDON_NAME" >> "$MARKS/order"
sleep 30
echo late >> "$MARKS/$SWARMBOX_ADDON_NAME.late"
"""
INSTALLER = r"""#!/bin/bash
set -eu
mkdir -p "$ADDON_PREFIX/bin"
printf '#!/bin/sh\nexit 0\n' > "$ADDON_PREFIX/bin/$FAKE_CMD"
chmod +x "$ADDON_PREFIX/bin/$FAKE_CMD"
"""


def read(path):
    with open(path) as f:
        return f.read()


def put(path, text, mode=0o755):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="addon-prepare-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.home, self.image, self.user, self.tmp, self.marks = j("home"), j("image"), j("user"), j("tmp"), j("marks")
        for d in (self.home, self.image, self.user, self.tmp, self.marks):
            os.makedirs(d)
        self.addons = os.path.join(self.home, ".local", "share", "swarmbox", "addons")

    def addon(self, *args, **extra):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.home, "TMPDIR": self.tmp, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_ADDONS": self.image, "SWARMBOX_TEST_USER_ADDONS": self.user,
             "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"),
             "SWARMBOX_TEST_LOCK": os.path.join(self.base, "run", "addons.lock"), "SWARMBOX_TEST_ARCH": "amd64",
             "MARKS": self.marks}
        e.update(extra)
        return subprocess.run(["bash", ADDON, *args], env=e, capture_output=True, text=True, timeout=60, cwd=self.base)

    def make(self, name, prepare=PREPARE_OK, level=None, installed=True, mode=0o755, **over):
        d = make_addon(level or self.image, name, install=INSTALLER, COMMANDS='"%s"' % name, **over)
        if prepare is not None:
            put(os.path.join(d, "prepare.sh"), prepare, mode)
        if installed:
            v = os.path.join(self.addons, name, "1.2.3")
            put(os.path.join(v, "bin", name), "#!/bin/sh\nexit 0\n")
            put(os.path.join(v, ".swarmbox-env"), "ARCH=amd64\n", 0o644)
            os.symlink("1.2.3", os.path.join(self.addons, name, "current"))
        return d

    def order(self):
        p = os.path.join(self.marks, "order")
        return read(p).split() if os.path.exists(p) else []

    def failures(self, r):
        return [l for l in r.stderr.splitlines() if l.startswith("prepare-failed: ")]


class PrepareTest(Base):
    def test_installed_addon_runs_in_home_with_closed_stdin_and_its_names(self):
        d = self.make("alpha")
        r = self.addon("prepare")
        self.assertEqual(r.returncode, 0, r.stderr)
        line = read(os.path.join(self.marks, "alpha.mark")).splitlines()
        self.assertEqual(line, ["alpha|%s|%s|%s" % (self.home, self.home, d)])   # no 'tty' line: stdin is not a terminal

    def test_a_declared_addon_runs_without_being_installed(self):
        self.make("alpha", installed=False)
        self.make("beta", installed=False)
        for value in ("alpha", "x,alpha", "beta alpha", "alpha,,beta", " alpha "):
            with self.subTest(value=value):
                if os.path.exists(os.path.join(self.marks, "order")):
                    os.unlink(os.path.join(self.marks, "order"))
                r = self.addon("prepare", SWARMBOX_WITH=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.order(), sorted(set(value.replace(",", " ").split()) & {"alpha", "beta"}))

    def test_order_is_by_addon_name_and_a_failure_does_not_stop_the_others(self):
        self.make("c-addon")
        self.make("a-addon")
        self.make("b-addon", prepare=PREPARE_FAIL)
        r = self.addon("prepare")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.order(), ["a-addon", "b-addon", "c-addon"])
        f = self.failures(r)
        self.assertEqual(len(f), 1, r.stderr)
        self.assertIn("b-addon", f[0])
        self.assertIn("exit 3", f[0])

    def test_a_hanging_prepare_times_out_and_the_others_still_run(self):
        self.make("a-addon")
        self.make("b-hang", prepare=PREPARE_HANG)
        self.make("c-addon")
        t0 = time.time()
        r = self.addon("prepare", SWARMBOX_PREPARE_TIMEOUT="1")
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.order(), ["a-addon", "b-hang", "c-addon"])
        f = self.failures(r)
        self.assertEqual(len(f), 1, r.stderr)
        self.assertIn("b-hang", f[0])
        self.assertIn("timed out", f[0])
        self.assertFalse(os.path.exists(os.path.join(self.marks, "b-hang.late")))

    def test_a_broken_manifest_with_a_prepare_sh_is_a_failure_not_a_stop(self):
        d = self.make("a-bad")
        with open(os.path.join(d, "addon.conf"), "a") as f:
            f.write("exit 5\n")
        self.make("b-good")
        r = self.addon("prepare", SWARMBOX_WITH="a-bad")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.order(), ["b-good"])
        f = self.failures(r)
        self.assertEqual(len(f), 1, r.stderr)
        self.assertIn("a-bad", f[0])

class AfterInstallTest(Base):
    def test_install_runs_prepare_sh_once_after_success(self):
        self.make("alpha", installed=False)
        r = self.addon("install", "alpha", FAKE_CMD="alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.order(), ["alpha"])
        self.assertEqual(r.stdout, "")

    def test_a_failing_prepare_after_install_does_not_fail_the_install(self):
        self.make("alpha", installed=False, prepare=PREPARE_FAIL)
        r = self.addon("install", "alpha", FAKE_CMD="alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.failures(r)), 1)
        self.assertTrue(os.path.islink(os.path.join(self.addons, "alpha", "current")))

if __name__ == "__main__":
    unittest.main()
