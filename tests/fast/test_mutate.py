"""The mutation harness dev/mutate.py on a toy repository: the mutations it makes, the plan that is the same every time, a run that kills one
mutant and lets another survive, the resume file, and the report. Nothing here touches the real repository.
Run: python3 tests/fast/test_mutate.py
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

MUTATE = os.path.join(ROOT, "dev", "mutate.py")
sys.path.insert(0, os.path.join(ROOT, "dev"))
import mutate  # noqa: E402

PY = '''def limit(n, items):
    if n > 3 and items:
        return 1
    return 0
'''
SH = '''#!/bin/sh
if [ "$1" -eq 2 ] && [ -n "$2" ]; then
    exit 3
fi
case $3 in
    go) echo go ;;
    *) echo other ;;
esac
'''
TEST = '''import os, subprocess, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import toy
class T(unittest.TestCase):
    def test_limit(self):
        self.assertEqual(toy.limit(5, [1]), 1)
        self.assertEqual(toy.limit(1, [1]), 0)
unittest.main()
'''


def apply(text, sites):
    return [text[:m["start"]] + m["new"] + text[m["end"]:] for m in sites]


class Sites(unittest.TestCase):
    def test_python_mutants_compile_and_cover_the_common_operators(self):
        sites = mutate.py_sites(PY)
        kinds = {m["kind"] for m in sites}
        self.assertTrue({"compare", "boolop", "negate-cond", "exit-code"} <= kinds, kinds)
        for new in apply(PY, sites):
            ast.parse(new)
            self.assertNotEqual(new, PY)
        self.assertIn("n >= 3", " ".join(apply(PY, sites)))
        self.assertIn("n > 3 or items", " ".join(apply(PY, sites)))

    def test_shell_mutants_flip_comparisons_codes_and_case_branches(self):
        sites = mutate.sh_sites(SH)
        kinds = {m["kind"] for m in sites}
        self.assertTrue({"sh-cmp", "sh-and-or", "exit-code", "sh-case", "sh-test-flag"} <= kinds, kinds)
        mutated = "\n".join(apply(SH, sites))
        for needle in ("-ne 2", "|| [ -n", "exit 0", "'__mutated_never__')", "[ -z "):
            self.assertIn(needle, mutated)
        for new in apply(SH, sites):
            self.assertTrue(mutate.valid("x.sh", new), new)

    def test_heredocs_and_comments_are_left_alone(self):
        sh = "#!/bin/sh\n# if [ 1 -eq 1 ]\ncat <<EOF\n[ 1 -eq 2 ] && exit 3\nEOF\n"
        self.assertEqual(mutate.sh_sites(sh), [])


class Toy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-mutate.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "tests", "fast"))
        with open(os.path.join(self.tmp, "toy.py"), "w") as f:
            f.write(PY)
        with open(os.path.join(self.tmp, "tests", "fast", "test_toy.py"), "w") as f:
            f.write(TEST)
        self.res = os.path.join(self.tmp, "r.jsonl")
        self.plan = os.path.join(self.tmp, "plan.json")

    @staticmethod
    def read(path):
        with open(path) as f:
            return f.read()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, MUTATE, "--root", self.tmp] + list(args), capture_output=True, text=True, timeout=120)

    def test_the_plan_is_the_same_every_time_and_a_run_kills_and_resumes(self):
        a = self.run_cli("plan", "--file", "toy.py", "--count", "20", "--out", self.plan)
        self.assertEqual(a.returncode, 0, a.stderr)
        first = self.read(self.plan)
        self.run_cli("plan", "--file", "toy.py", "--count", "20", "--out", self.plan)
        self.assertEqual(self.read(self.plan), first, "the same seed and sources give the same plan")
        n = len(json.loads(first)["mutants"])
        self.assertGreater(n, 3)
        r = self.run_cli("run", "--plan", self.plan, "--results", self.res, "-j", "2", "--control")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = [json.loads(x) for x in self.read(self.res).splitlines()]
        status = {x["id"]: x["status"] for x in rows}
        self.assertEqual(status["control:toy.py"], "survived", "no mutation, no failure")
        self.assertIn("killed", status.values())
        self.assertEqual(len(rows), n + 1)
        again = self.run_cli("run", "--plan", self.plan, "--results", self.res, "--control")
        self.assertIn("0 to run", again.stdout)
        self.assertEqual(self.read(os.path.join(self.tmp, "toy.py")), PY, "the source is restored")
        rep = self.run_cli("report", "--plan", self.plan, "--results", self.res, "--matrix", os.path.join(self.tmp, "m.json"))
        self.assertIn("kill rate", rep.stdout)
        matrix = json.loads(self.read(os.path.join(self.tmp, "m.json")))
        killed = [v for v in matrix.values() if v["status"] == "killed"]
        self.assertTrue(killed and all(v["killed_by"] == ["test_toy.py"] for v in killed))

    def test_a_mutant_whose_text_is_gone_is_stale_and_a_file_without_tests_has_none(self):
        self.run_cli("plan", "--file", "toy.py", "--count", "5", "--out", self.plan)
        with open(os.path.join(self.tmp, "toy.py"), "w") as f:
            f.write("def limit(n, items):\n    return 7\n")
        self.run_cli("run", "--plan", self.plan, "--results", self.res)
        self.assertEqual({json.loads(x)["status"] for x in self.read(self.res).splitlines()}, {"stale"})
        self.assertEqual(mutate.covering_tests(self.tmp, "toy.py"), ["tests/fast/test_toy.py"])
        # no file refers to it: the fast files are the fallback
        self.assertEqual(mutate.covering_tests(self.tmp, "container/other.py"), ["tests/fast/test_toy.py"])


if __name__ == "__main__":
    unittest.main()
