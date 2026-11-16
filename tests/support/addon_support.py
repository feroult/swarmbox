"""The fake world of the tests of the addon manager (swarmbox-addon.sh, swarmbox-shim.sh), shared by tests/fast/test_addon_*.py:

make_addon (a manifest and an installer in a mktemp folder), Base (HOME, both manifest levels, the lock, the architecture and the
recording fake installers: managed, self-updating, sha256), ShimBase (the same with both shim folders and the index), tree_hash.
Nothing here touches the real home, the real addons folder or the real lock: they are moved with the SWARMBOX_TEST_* variables.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

GOOD_CONF = {
    "SCHEMA": "1", "NAME": "demo", "DESCRIPTION": '"A demo addon"', "COMMANDS": '"demo demo2"', "VERSION": "1.2.3",
}
SELF_UPDATING = dict(VERSION="latest", UPDATE="self", UPDATE_CMD='"demo update"')
GOOD_INSTALL = '#!/bin/bash\nset -euo pipefail\nmkdir -p "$ADDON_PREFIX/bin"\necho installing >&2\n'


def write_conf(path, conf, extra=""):
    with open(path, "w") as f:
        for k, v in conf.items():
            f.write("%s=%s\n" % (k, v))
        f.write(extra)


def make_addon(level, name="demo", conf=None, install=GOOD_INSTALL, executable=True, extra="", drop=(), **over):
    d = os.path.join(level, name)
    os.makedirs(d, exist_ok=True)
    c = dict(GOOD_CONF, NAME=name)
    c.update(conf or {})
    c.update(over)
    for k in drop:
        c.pop(k, None)
    write_conf(os.path.join(d, "addon.conf"), c, extra)
    if install is not None:
        p = os.path.join(d, "install.sh")
        with open(p, "w") as f:
            f.write(install)
        os.chmod(p, 0o755 if executable else 0o644)
    return d




def tree_hash(root):
    h = hashlib.sha256()
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for n in sorted(fn + dn):
            p = os.path.join(dp, n)
            h.update(os.path.relpath(p, root).encode())
            if os.path.islink(p):
                h.update(b"L" + os.readlink(p).encode())
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    h.update(b"F" + f.read())
    return h.hexdigest()


ADDON = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
LIB = os.path.join(ROOT, "container", "scripts")

# The program the fake installers write: prints every argument as [arg] on its own line, exits with $DEMO_EXIT.
PROGRAM = r"""#!/bin/sh
if [ "$1" = update ] && [ -n "${FAKE_CALLS:-}" ]; then echo "update called with: $*" >> "$FAKE_CALLS"; exit "${UPDATE_EXIT:-0}"; fi
for a in "$@"; do printf '[%s]\n' "$a"; done
exit "${DEMO_EXIT:-0}"
"""

COMMON = r"""#!/bin/bash
set -eu
echo "$ADDON_PREFIX|$ADDON_VERSION|$ADDON_ARCH|${ADDON_SHA256:-}|$PWD|$HOME" >> "$FAKE_REC"
echo x >> "$FAKE_COUNT"
[ -z "${FAKE_SLEEP:-}" ] || sleep "$FAKE_SLEEP"
echo "INSTALLER-STDOUT-NOISE"
"""

PROG_WRITER = r"""cat > "$DEST" <<'PROG_EOF'
""" + PROGRAM + r"""PROG_EOF
chmod +x "$DEST"
"""

MANAGED = COMMON + r"""mkdir -p "$ADDON_PREFIX/bin"
echo partial > "$ADDON_PREFIX/partial.txt"
[ -z "${FAKE_FAIL:-}" ] || { echo "curl: could not resolve host" >&2; exit 1; }
DEST="$ADDON_PREFIX/bin/demo"
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
echo "requested=$ADDON_VERSION" > "$ADDON_PREFIX/installed"
"""

SHA = r"""#!/bin/bash
set -eu
echo x >> "$FAKE_COUNT"
mkdir -p "$ADDON_PREFIX/bin"
cp "$FIXTURE_ARCHIVE" "$ADDON_PREFIX/download.tar.gz"
echo "$ADDON_SHA256  $ADDON_PREFIX/download.tar.gz" | sha256sum -c - >&2 || exit 1
DEST="$ADDON_PREFIX/bin/demo"
""" + PROG_WRITER

SELF_CONF = {"VERSION": "latest", "UPDATE": "self", "UPDATE_CMD": '"selfy update"',
             "COMMANDS": '"selfy"'}


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="addon-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.home, self.image, self.user = j("home"), j("image"), j("user")
        self.tmp, self.lock = j("tmp"), j("run", "addons.lock")
        self.rec, self.count, self.calls = j("rec.txt"), j("count.txt"), j("calls.txt")
        for d in (self.home, self.image, self.user, self.tmp):
            os.makedirs(d)
        self.addons = os.path.join(self.home, ".local", "share", "swarmbox", "addons")

    def env(self, **extra):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.home, "TMPDIR": self.tmp, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_ADDONS": self.image, "SWARMBOX_TEST_USER_ADDONS": self.user,
             "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"),
             "SWARMBOX_TEST_LOCK": self.lock, "SWARMBOX_TEST_ARCH": "amd64",
             "FAKE_REC": self.rec, "FAKE_COUNT": self.count, "FAKE_CALLS": self.calls}
        e.update(extra)
        return e

    def addon(self, *args, env=None, **extra):
        return subprocess.run(["bash", ADDON, *args], env=env or self.env(**extra), capture_output=True, text=True,
                              timeout=60, cwd=self.base)

    def managed(self, name="demo", installer=MANAGED, level=None, **over):
        return make_addon(level or self.image, name, install=installer, COMMANDS='"demo"', **over)

    def selfy(self, installer=SELF, **over):
        conf = dict(SELF_CONF)
        conf.update(over)
        return make_addon(self.image, "selfy", install=installer, **conf)

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


SHIM = os.path.join(ROOT, "container", "scripts", "swarmbox-shim.sh")

INTERPRETERS = [("shebang", None)]
for _name, _argv in (("dash", ["dash"]), ("bash", ["bash"]), ("busybox", ["busybox", "sh"])):
    if shutil.which(_argv[0]):
        INTERPRETERS.append((_name, _argv))

# An "addon manager" that only records how it was called (for tests that must not run the real swarmbox-addon).
FAKE_MGR = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_ARGS"
printf '%s\\n' "${SWARMBOX_SHIM_DEPTH:-}" > "$FAKE_ARGS.depth"
exit "${MGR_EXIT:-0}"
"""


class ShimBase(Base):
    def setUp(self):
        super().setUp()
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.ishims, self.ushims = j("img", "shims"), j("home", ".local", "share", "swarmbox", "shims")
        os.makedirs(self.ishims)
        os.makedirs(self.ushims)
        self.args = j("args.txt")

    def env(self, **extra):
        e = super().env(**extra)
        for k, v in (("SWARMBOX_TEST_IMAGE_SHIMS", self.ishims), ("SWARMBOX_TEST_USER_SHIMS", self.ushims),
                     ("SWARMBOX_TEST_ADDON", ADDON), ("FAKE_ARGS", self.args)):
            e.setdefault(k, v)
        e["PATH"] = ":".join([os.path.join(self.home, ".local", "bin"), self.ushims, self.ishims, "/usr/bin", "/bin"])
        return e

    def link(self, level, shims, *commands):
        """Shims of `commands` in `shims` pointing to the real dispatcher in the repository."""
        for c in commands:
            p = os.path.join(shims, c)
            if os.path.lexists(p):
                os.remove(p)
            os.symlink(SHIM, p)

    def index(self, shims, *lines):
        with open(os.path.join(os.path.dirname(shims), "index"), "w") as f:
            f.write("".join(l + "\n" for l in lines))

    def call(self, shim_path, *args, interp=None, env=None, **extra):
        argv = (interp or []) + [shim_path, *args]
        return subprocess.run(argv, env=env or self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.base)

    def fake_mgr(self):
        p = os.path.join(self.base, "fake-mgr")
        with open(p, "w") as f:
            f.write(FAKE_MGR)
        os.chmod(p, 0o755)
        return p

    def setup_demo(self, **over):
        """Image-level managed addon 'demo' and self addon 'selfy', both indexed and linked."""
        self.managed(**over)
        self.selfy()
        self.index(self.ishims, "demo demo", "selfy selfy")
        self.link("image", self.ishims, "demo", "selfy")
