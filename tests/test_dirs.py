"""Slice 1.2: container/scripts/dirs.sh, the one file that defines every path (design 4.3 item 4, D10).

Each case runs a real shell (sh, dash, bash when present) with the environment cleared except PATH, HOME and the XDG
variables the case sets, all inside mktemp directories. Nothing here touches the real HOME.
Run: python3 tests/test_dirs.py
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

DIRS = os.path.join(ROOT, "container", "scripts", "dirs.sh")

# name -> (path under home, XDG variable, tail) ; the table the design text is cross-checked against.
EXPECTED = {
    "SB_CONFIG_DIR": ("config", ".config", "swarmbox"),
    "SB_DATA_DIR": ("data", ".local/share", "swarmbox"),
    "SB_STATE_DIR": ("state", ".local/state", "swarmbox"),
    "SB_TOOLS_DIR": ("data", ".local/share", "swarmbox/tools"),
    "SB_SHIMS_DIR": ("data", ".local/share", "swarmbox/shims"),
    "SB_LOG_DIR": ("state", ".local/state", "swarmbox/logs"),
    "SB_HEALTH_FILE": ("state", ".local/state", "swarmbox/health"),
    "SB_PODMAN_SOCK": ("state", ".local/state", "swarmbox/podman.sock"),
}
XDGVAR = {"config": "XDG_CONFIG_HOME", "data": "XDG_DATA_HOME", "state": "XDG_STATE_HOME"}
FIXED = {"SB_RUN_DIR": "/tmp/swarmbox"}
SHELLS = [s for s in ("sh", "dash", "bash") if shutil.which(s)]


def run(shell, home, xdg=None, prelude="", postlude=""):
    """Source dirs.sh in `shell` and return {name: value} for every variable."""
    env = {"PATH": os.environ["PATH"], "HOME": home}
    env.update(xdg or {})
    names = list(EXPECTED) + list(FIXED)
    script = prelude + '\n. "$1"\n' + postlude + "\n" + "".join('printf "%s=%%s\\n" "$%s"\n' % (n, n) for n in names)
    p = subprocess.run([shell, "-c", script, shell, DIRS], env=env, capture_output=True, text=True)
    assert p.returncode == 0, (shell, p.returncode, p.stderr)
    return dict(line.split("=", 1) for line in p.stdout.splitlines())


class DirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-dirs.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        # the exit criterion: never the real home
        self.assertNotEqual(os.path.realpath(self.home), os.path.realpath(os.path.expanduser("~")))

    def expect(self, xdg_roots):
        out = {}
        for name, (kind, default, tail) in EXPECTED.items():
            out[name] = xdg_roots.get(kind, os.path.join(self.home, default)) + "/" + tail
        out.update(FIXED)
        return out

    def test_defaults_from_home(self):
        for sh in SHELLS:
            with self.subTest(sh=sh):
                self.assertEqual(run(sh, self.home), self.expect({}))

    def test_each_xdg_overrides_only_its_own(self):
        for kind, var in XDGVAR.items():
            for sh in SHELLS:
                with self.subTest(var=var, sh=sh):
                    root = os.path.join(self.tmp, "x-" + kind)
                    self.assertEqual(run(sh, self.home, {var: root}), self.expect({kind: root}))

    def test_all_three_set(self):
        roots = {k: os.path.join(self.tmp, "r-" + k) for k in XDGVAR}
        xdg = {XDGVAR[k]: v for k, v in roots.items()}
        for sh in SHELLS:
            with self.subTest(sh=sh):
                self.assertEqual(run(sh, self.home, xdg), self.expect(roots))

    def test_empty_counts_as_unset(self):
        for sh in SHELLS:
            with self.subTest(sh=sh):
                self.assertEqual(run(sh, self.home, {v: "" for v in XDGVAR.values()}), self.expect({}))

    def test_relative_is_ignored(self):
        # XDG spec: a relative path is invalid and must be ignored; the default applies.
        for sh in SHELLS:
            with self.subTest(sh=sh):
                xdg = {"XDG_CONFIG_HOME": "rel/cfg", "XDG_DATA_HOME": "./d", "XDG_STATE_HOME": "~/s"}
                self.assertEqual(run(sh, self.home, xdg), self.expect({}))

    def test_spaces_and_glob_characters_kept(self):
        root = os.path.join(self.tmp, "with space", "a*b  c")
        for sh in SHELLS:
            with self.subTest(sh=sh):
                got = run(sh, os.path.join(self.tmp, "my home"), {"XDG_STATE_HOME": root})
                self.assertEqual(got["SB_PODMAN_SOCK"], root + "/swarmbox/podman.sock")
                self.assertEqual(got["SB_CONFIG_DIR"], os.path.join(self.tmp, "my home", ".config", "swarmbox"))

    def test_trailing_slash_not_doubled(self):
        root = os.path.join(self.tmp, "slash")
        for sh in SHELLS:
            with self.subTest(sh=sh):
                got = run(sh, self.home, {"XDG_DATA_HOME": root + "/"})
                self.assertEqual(got["SB_DATA_DIR"], root + "/swarmbox")

    def test_source_twice_is_idempotent(self):
        for sh in SHELLS:
            with self.subTest(sh=sh):
                once = run(sh, self.home)
                twice = run(sh, self.home, prelude='. "$1"')
                self.assertEqual(once, twice)

    def test_second_source_ignores_changed_xdg_only_if_recomputed(self):
        # Sourcing recomputes from the environment every time (no hidden cache): a change between two sources shows.
        for sh in SHELLS:
            with self.subTest(sh=sh):
                root = os.path.join(self.tmp, "later")
                got = run(sh, self.home, postlude='XDG_STATE_HOME="%s"; . "$1"' % root)
                self.assertEqual(got["SB_STATE_DIR"], root + "/swarmbox")

    def test_no_side_effects(self):
        for sh in SHELLS:
            with self.subTest(sh=sh):
                before = sorted(os.listdir(self.tmp)), sorted(os.listdir(self.home))
                run(sh, self.home, {v: os.path.join(self.tmp, "n-" + k) for k, v in XDGVAR.items()})
                self.assertEqual(before, (sorted(os.listdir(self.tmp)), sorted(os.listdir(self.home))))
                self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))

    def test_set_eu(self):
        for sh in SHELLS:
            with self.subTest(sh=sh):
                run(sh, self.home, prelude="set -eu")
                # with HOME and XDG unset, -u must still not break once HOME exists; check unset XDG under -u:
                p = subprocess.run([sh, "-c", 'set -eu; . "$1"; echo ok', sh, DIRS],
                                   env={"PATH": os.environ["PATH"], "HOME": self.home}, capture_output=True, text=True)
                self.assertEqual((p.returncode, p.stdout.strip()), (0, "ok"), p.stderr)

    def test_no_bashisms_and_shellcheck(self):
        with open(DIRS, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("#!/bin/sh"))
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        for bad in ("[[", "declare ", "local ", "(( ", "<(", "${BASH_SOURCE"):
            self.assertNotIn(bad, code)
        if shutil.which("shellcheck"):
            p = subprocess.run(["shellcheck", "-s", "sh", DIRS], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout)
        else:
            print("shellcheck not found: skipped", file=sys.stderr)

    def test_design_names_every_path(self):
        with open(os.path.join(ROOT, "docs", "design.md"), encoding="utf-8") as f:
            design = f.read()
        sec = design[design.index("### 4.3 "):design.index("### 4.4 ")]
        for name, (_, default, tail) in EXPECTED.items():
            leaf = tail.split("/")[-1]
            self.assertIn(leaf if "/" in tail else "swarmbox", sec, name)
        for word in ("tools/", "shims/", "logs", "health", "podman.sock", "/tmp/swarmbox", "dirs.sh"):
            self.assertIn(word, sec)
        # every variable the script defines is in the header table and in the expected table
        with open(DIRS, encoding="utf-8") as f:
            defined = set(re.findall(r"^(SB_[A-Z_]+)=", f.read(), re.M))
        self.assertEqual(defined, set(EXPECTED) | set(FIXED))


if __name__ == "__main__":
    unittest.main()
