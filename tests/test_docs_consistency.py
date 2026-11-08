"""Docs consistency of the plan and the design (Phase 0 close-out, slice 0.5).

Checks: every B and D id the plan cites exists in the design; Part B has B1 to B36 once each and the decisions table
has D1 to D39; code fences of design.md and implementation-plan.md are balanced; every spike of the plan's Phase 0 table
has a result row in Part B with an evidence tag or `[unverified]`; the Phase 0 outcome table of the design lists every
Phase 0 fact with a state and an owner and names B6, B7, B8 and B15 as not doable here; Appendix A.3 lists B1 to B36;
tests/spikes/README.md lists every spike script with its B number and how to run it.
Run: python3 tests/test_docs_consistency.py
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


DESIGN = read("docs", "design.md")
PLAN = read("docs", "implementation-plan.md")
SPIKES = os.path.join(ROOT, "tests", "spikes")
PART_B = DESIGN[DESIGN.index("### Part B. Facts to verify"):DESIGN.index("## 15. Roadmap")]
OUTCOME_MARK = "#### Phase 0 outcome"
RESULTS = PART_B[PART_B.index("#### Results of the Phase 0 spikes"):PART_B.index(OUTCOME_MARK)]


def phase0_table_ids():
    s = PLAN.index("## 2. Phase 0")
    e = PLAN.index("**Cannot be checked in this environment**")
    return re.findall(r"^\| (B\d+) \|", PLAN[s:e], re.M)


def rows(text, ident):
    return [l for l in text.splitlines() if re.match(r"\| %s\b" % re.escape(ident), l)]


class IdsTest(unittest.TestCase):
    def test_partb_has_b1_to_b36_once(self):
        ids = re.findall(r"^\| (B\d+) \|", PART_B[:PART_B.index("#### Results")], re.M)
        self.assertEqual(ids, ["B%d" % n for n in range(1, 37)])

    def test_decisions_d1_to_d39(self):
        ids = re.findall(r"^\| (D\d+) \|", DESIGN, re.M)
        self.assertEqual(sorted(set(ids), key=lambda x: int(x[1:])), ["D%d" % n for n in range(1, 40)])

    def test_ids_cited_exist(self):
        for name, text in (("plan", PLAN), ("design", DESIGN)):
            for b in set(re.findall(r"\bB(\d+)\b", text)):
                self.assertTrue(1 <= int(b) <= 36, "%s cites B%s" % (name, b))
            for d in set(re.findall(r"\bD(\d+)\b", text)):
                self.assertTrue(1 <= int(d) <= 39, "%s cites D%s" % (name, d))

    def test_design_range_statements_match(self):
        self.assertNotIn("D1 to D37", DESIGN)

    def test_appendix_a3_lists_all_facts(self):
        a3 = PLAN[PLAN.index("### A.3"):]
        ids = re.findall(r"^\| (B\d+) \|", a3, re.M)
        self.assertEqual(ids, ["B%d" % n for n in range(1, 37)])

    def test_appendix_a1_lists_all_decisions(self):
        a1 = PLAN[PLAN.index("### A.1"):PLAN.index("### A.2")]
        ids = re.findall(r"^\| (D\d+) \|", a1, re.M)
        self.assertEqual(ids, ["D%d" % n for n in range(1, 40)])

    def test_fences_balanced(self):
        for name, text in (("design", DESIGN), ("plan", PLAN)):
            n = len([l for l in text.splitlines() if l.lstrip().startswith("```")])
            self.assertEqual(n % 2, 0, name)


class PhaseZeroTest(unittest.TestCase):
    def test_every_spike_has_result_with_tag(self):
        ids = phase0_table_ids()
        self.assertGreaterEqual(len(ids), 15)
        for b in ids:
            r = rows(RESULTS, b)
            self.assertTrue(r, "%s has no row in the results table" % b)
            for line in r:
                self.assertTrue("[verified:" in line or "[unverified" in line, "%s: no evidence tag" % b)

    def test_outcome_table_states_and_owners(self):
        self.assertIn(OUTCOME_MARK, DESIGN)
        out = DESIGN[DESIGN.index(OUTCOME_MARK):DESIGN.index("## 15. Roadmap")]
        for b in phase0_table_ids():
            r = rows(out, b)
            self.assertEqual(len(r), 1, "%s needs one row in the outcome table" % b)
            cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
            self.assertTrue(cells[1].lower().startswith(("closed", "reduced", "open")), "%s: state %r" % (b, cells[1]))
            self.assertTrue(cells[2], "%s: no owner" % b)
        for b in ("B6", "B7", "B8", "B15"):
            r = rows(out, b)
            self.assertEqual(len(r), 1, b)
            self.assertIn("not doable here", r[0], b)

    def test_plan_phase0_points_at_outcome(self):
        s = PLAN.index("## 2. Phase 0")
        e = PLAN.index("**Exit criteria:**", s)
        self.assertIn("Phase 0 outcome", PLAN[s:e])


class SpikeReadmeTest(unittest.TestCase):
    def test_readme_lists_every_script(self):
        readme = read("tests", "spikes", "README.md")
        for path in sorted(glob.glob(os.path.join(SPIKES, "spike_*"))):
            name = os.path.basename(path)
            line = [l for l in readme.splitlines() if name in l]
            self.assertTrue(line, "%s not in the README" % name)
            self.assertRegex(line[0], r"B\d+", name)
            self.assertIn("python3 tests/spikes/" if name.endswith(".py") else "bash tests/spikes/", line[0], name)
        self.assertIn("spikes_common.py", readme)


PHASE1_SLICES = ["1.1-license-notices", "1.2-dirs-sh", "1.3-fake-podman", "1.4-fake-host-helper", "1.5-history-audit",
                 "1.6-ci-workflow", "1.7-phase-close"]
PHASE1_FILES = ["LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", ".github/workflows/ci.yml",
                "container/scripts/dirs.sh", "docs/history-audit.md"]


class PhaseOneCloseTest(unittest.TestCase):
    """Phase 1 close-out (slice 1.7)."""

    def test_status_row_per_slice(self):
        status = read("docs", "implementation-status.md")
        for sl in PHASE1_SLICES:
            r = [l for l in status.splitlines() if l.startswith("| %s |" % sl)]
            self.assertEqual(len(r), 1, sl)
            cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
            self.assertIn(cells[2], ("done", "partial", "blocked"), sl)

    def test_status_has_phase1_gate_row(self):
        status = read("docs", "implementation-status.md")
        r = [l for l in status.splitlines() if l.startswith("| 1.gate |")]
        self.assertEqual(len(r), 1)
        for word in ("B30", "visib", "copyright"):
            self.assertIn(word, r[0], word)

    def test_decision_log_entry_per_slice(self):
        log = read("docs", "decision-log.md")
        for n in range(1, 8):
            self.assertRegex(log, r"(?m)^## \[1\.%d\] " % n, "decision-log entry [1.%d]" % n)

    def test_promised_files_exist(self):
        for f in PHASE1_FILES:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), f)

    def test_tests_do_not_touch_real_home(self):
        bad = re.compile(r"~/\.config/swarmbox|~/\.ssh|~/swarmbox|~/\.claude|~/\.local/share/swarmbox|~/\.swarmbox")
        hits = []
        for path in sorted(glob.glob(os.path.join(ROOT, "tests", "**", "*.py"), recursive=True)):
            if os.path.basename(path) == "test_docs_consistency.py":
                continue
            for i, line in enumerate(open(path, encoding="utf-8"), 1):
                if bad.search(line):
                    hits.append("%s:%d" % (os.path.relpath(path, ROOT), i))
        print("home-path mentions to review:", hits)
        for h in hits:
            f, n = h.rsplit(":", 1)
            line = open(os.path.join(ROOT, f), encoding="utf-8").read().splitlines()[int(n) - 1]
            code = line.split("#")[0]
            ok = re.search(r"assert|expanduser|host:|mktemp|TemporaryDirectory|Not |not |never|NOT", line) or \
                not ("open(" in code or "write" in code or "makedirs" in code or "mkdir" in code)
            self.assertTrue(ok, "%s may write to a real home path: %s" % (h, line.strip()))


PHASE2_SLICES = ["2.1-image", "2.2-serve", "2.3-attach", "2.4-shell", "2.5-entrypoint-web", "2.6-migration", "2.7-smoke-closeout"]


class PhaseTwoCloseTest(unittest.TestCase):
    """Phase 2 close-out (slice 2.7)."""

    def test_status_row_per_slice(self):
        status = read("docs", "implementation-status.md")
        for sl in PHASE2_SLICES:
            r = [l for l in status.splitlines() if l.startswith("| %s |" % sl)]
            self.assertEqual(len(r), 1, sl)
            cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
            self.assertIn(cells[2], ("done", "partial", "blocked"), sl)

    def test_gate_row_is_partial_until_the_smoke_test_runs_in_ci(self):
        status = read("docs", "implementation-status.md")
        r = [l for l in status.splitlines() if l.startswith("| 2.gate |")]
        self.assertEqual(len(r), 1)
        cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
        self.assertEqual(cells[2], "partial")
        for word in ("CI", "B28", "M1", "reduced"):
            self.assertIn(word, r[0], word)

    def test_decision_log_has_a_2_7_entry(self):
        self.assertRegex(read("docs", "decision-log.md"), r"(?m)^## \[2\.7\] ")

    def test_partb_rows_for_phase2_facts_carry_a_tag_or_unverified(self):
        design = read("docs", "design.md")
        sec = design[design.index("#### Results of Phase 2 (slice 2.7"):design.index("## 15. Roadmap")]
        for fact in ("B3", "B17", "B13, B36", "B28"):
            rows = [l for l in sec.splitlines() if l.startswith("| 2.7 %s |" % fact)]
            self.assertEqual(len(rows), 1, fact)
            self.assertRegex(rows[0], r"\[verified: [^\]]+\]|\[unverified\]", fact)
        b28 = [l for l in sec.splitlines() if l.startswith("| 2.7 B28 |")][0]
        self.assertIn("[unverified]", b28)
        self.assertIn("Open", b28)
        for l in sec.splitlines():
            if l.startswith("| 2.7 B3 |") or l.startswith("| 2.7 B17 |") or l.startswith("| 2.7 B13"):
                self.assertIn("reduced: development box, no nested Podman in the box", l)

    def test_plan_says_m1_is_reduced_only(self):
        plan = read("docs", "implementation-plan.md")
        self.assertRegex(plan, r"Slice 2\.7 wrote `tests/smoke_image\.py`")
        self.assertIn("M1 is reached as reduced only", plan)

    def test_smoke_files_exist(self):
        for f in ("tests/smoke_image.py", "tests/test_smoke_skeleton.py"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), f)

PHASE4A_SLICES = ["4a.1-manifest-validate", "4a.2-link-index-ports", "4a.3-install-run-lock", "4a.4-shim-dispatcher",
                  "4a.5-image-wiring", "4a.6-real-claude-first-call", "4a.7-closeout"]
PHASE4A_TESTS = ["test_tool_manifest.py", "test_tool_link.py", "test_tool_install.py", "test_tool_shim.py",
                 "test_tool_claude_real.py", "test_tool_stub.py"]


class PhaseFourACloseTest(unittest.TestCase):
    """Phase 4a close-out (slice 4a.7)."""

    def test_no_stub_wording_for_swarmbox_tool_remains(self):
        # the live files never call the real program a stub or placeholder
        for rel in (("Dockerfile",), ("container", "entrypoint.sh"), ("container", "scripts", "swarmbox-tool.sh"),
                    ("container", "scripts", "swarmbox-shim.sh")):
            for n, line in enumerate(read(*rel).splitlines(), 1):
                self.assertNotRegex(line, r"(?i)\b(stub|placeholder)\b", "%s:%d" % ("/".join(rel), n))
        # the design and the plan may tell the history of the Phase 2 stub only with the phase that replaced it
        for name, text in (("design", DESIGN), ("plan", PLAN)):
            for n, line in enumerate(text.splitlines(), 1):
                if re.search(r"(?i)\bstubs?\b", line) and "swarmbox-tool" in line:
                    self.assertRegex(line, r"4a", "%s:%d" % (name, n))

    def test_plan_lists_the_4a_test_files_and_each_exists_and_runs_in_ci(self):
        sec = PLAN[PLAN.index("## 5. Phase 4a"):PLAN.index("## 6. Phase 3")]
        ci = read(".github", "workflows", "ci.yml")
        for t in PHASE4A_TESTS:
            self.assertIn("tests/" + t, sec, t)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "tests", t)), t)
            self.assertIn("python3 tests/" + t, ci, t)

    def test_d18_absence_tests_exist_in_manifest_link_and_shim_tests(self):
        for f in ("test_tool_manifest.py", "test_tool_link.py", "test_tool_shim.py"):
            src = read("tests", f)
            self.assertRegex(src, r"def test_\w*project\w*", f)
            self.assertIn("D18", src, f)

    def test_status_rows_and_gate(self):
        status = read("docs", "implementation-status.md")
        for sl in PHASE4A_SLICES:
            r = [l for l in status.splitlines() if l.startswith("| %s |" % sl)]
            self.assertEqual(len(r), 1, sl)
            self.assertIn([c.strip() for c in r[0].strip().strip("|").split("|")][2], ("done", "partial", "blocked"), sl)
        g = [l for l in status.splitlines() if l.startswith("| 4a.gate |")]
        self.assertEqual(len(g), 1)
        self.assertIn([c.strip() for c in g[0].strip().strip("|").split("|")][2], ("done", "partial"))
        for word in ("B1", "CI"):
            self.assertIn(word, g[0], word)

    def test_decision_log_has_entries_for_every_4a_slice(self):
        log = read("docs", "decision-log.md")
        for n in range(1, 8):
            self.assertRegex(log, r"(?m)^## \[4a\.%d\] " % n)

    def test_appendix_a_rows_for_4a_decisions_and_b1(self):
        for d in ("D2", "D3", "D18", "D21"):
            r = rows(PLAN, d)
            self.assertEqual(len(r), 1, d)
            self.assertIn("4a", r[0], d)
        self.assertRegex(rows(PLAN, "B1")[-1], r"closed in 0\.3")
        self.assertIn("4a.6", rows(PLAN, "B1")[-1])

    def test_plan_marks_4a_done_with_the_gate_reading(self):
        sec = PLAN[PLAN.index("## 5. Phase 4a"):PLAN.index("## 6. Phase 3")]
        self.assertIn("**4a.7 done:**", sec)
        self.assertIn("fake installer", sec)
        self.assertIn("tool-ports", sec)

    def test_phase3_notes_that_depend_on_tool_ports_and_shims_point_at_4a(self):
        sec = PLAN[PLAN.index("## 6. Phase 3"):PLAN.index("## 7. ")]
        self.assertIn("tool-ports", sec)
        self.assertRegex(sec, r"4a")


if __name__ == "__main__":
    unittest.main()
