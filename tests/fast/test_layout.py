"""The layout of tests/: fast, slow, e2e and support, one runner, one list for the macOS job, and the test image recipe.

What the folders mean is in tests/README.md. These checks keep the layout from rotting: no test file outside its folder, no fast file that
needs a slow one, the macOS list made of real fast files, and the pins of dev/test-image/Containerfile equal to the root Dockerfile.
Run: python3 tests/fast/test_layout.py
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

TESTS = os.path.join(ROOT, "tests")


def names(layer):
    return sorted(f for f in os.listdir(os.path.join(TESTS, layer)) if f.endswith(".py"))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class Layout(unittest.TestCase):
    def test_a_test_file_lives_in_fast_or_slow_and_nowhere_else(self):
        for sub in ("", "support", "e2e"):
            stray = [f for f in os.listdir(os.path.join(TESTS, sub)) if re.match(r"test_.*\.py$", f)]
            self.assertEqual(stray, [], "test files belong in tests/fast or tests/slow, not in tests/%s" % sub)
        self.assertEqual(set(n for n in names("fast") if n.startswith("test_")) & set(names("slow")), set(), "one file, one layer")
        for layer in ("fast", "slow"):
            for f in names(layer):
                if f.startswith("test_"):
                    break
            else:
                self.fail("tests/%s has no test file" % layer)

    def test_a_fast_file_never_imports_a_slow_one(self):
        slow = set(os.path.splitext(f)[0] for f in names("slow"))
        for f in names("fast"):
            for m in re.finditer(r"(?m)^\s*(?:import|from) (\w+)", read("tests", "fast", f)):
                self.assertNotIn(m.group(1), slow, "tests/fast/%s imports tests/slow/%s.py: move the shared part to tests/support" % (f, m.group(1)))

    def test_the_macos_list_names_existing_fast_files(self):
        listed = [ln.split("#")[0].strip() for ln in read("tests", "support", "macos.list").splitlines()]
        listed = [x for x in listed if x]
        self.assertTrue(listed)
        self.assertEqual(sorted(set(listed)), sorted(listed), "a name twice")
        self.assertEqual([x for x in listed if x not in names("fast")], [])

    def test_the_test_image_pins_what_the_product_image_pins(self):
        docker, recipe = read("Dockerfile"), read("dev", "test-image", "Containerfile")
        for arg in ("TMUX_VERSION", "TMUX_SHA256_AMD64", "TMUX_SHA256_ARM64", "TMUX_SHA1_AMD64", "TMUX_SHA1_ARM64", "TTYD_VERSION"):
            a = re.search(r"(?m)^ARG %s=(\S+)" % arg, docker)
            b = re.search(r"(?m)^ARG %s=(\S+)" % arg, recipe)
            self.assertTrue(a and b, arg)
            self.assertEqual(a.group(1), b.group(1), "%s differs between Dockerfile and dev/test-image/Containerfile" % arg)

    def test_every_test_the_regression_ledger_names_exists(self):
        # docs/history/test-suite-review/regressions.md: bug -> test id -> layer. An id is `layer/test_file.py::Class` or `::Class::test_name`;
        # renaming or deleting a test that guards a past bug must be a decision, so the ledger has to be changed with it.
        import ast
        ledger = read("docs", "history", "test-suite-review", "regressions.md")
        ids = re.findall(r"`((?:fast|slow)/test_\w+\.py(?:::\w+){1,2})`", ledger)
        self.assertGreater(len(ids), 60, "the ledger lists the tests that guard the bugs of version 1")
        tree = {}
        for i in sorted(set(ids)):
            path, *rest = i.split("::")
            if path not in tree:
                with open(os.path.join(TESTS, path), encoding="utf-8") as f:
                    tree[path] = {c.name: {m.name for m in c.body if isinstance(m, ast.FunctionDef)}
                                  for c in ast.parse(f.read()).body if isinstance(c, ast.ClassDef)}
            self.assertIn(rest[0], tree[path], "%s: no such class" % i)
            if len(rest) == 2:
                self.assertIn(rest[1], tree[path][rest[0]], "%s: no such test" % i)

    def test_the_scripts_of_the_layout_parse(self):
        for rel in ("tests/run.sh", "dev/test-slow.sh", "dev/check.sh"):
            r = subprocess.run(["sh", "-n", os.path.join(ROOT, rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, rel + r.stderr)


if __name__ == "__main__":
    unittest.main()
