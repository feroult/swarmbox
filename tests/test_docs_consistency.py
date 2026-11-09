"""Docs consistency of the plan and the design (Phase 0 close-out, slice 0.5).

Checks: every B and D id the plan cites exists in the design; Part B has B1 to B36 once each and the decisions table
has D1 to D40; code fences of design.md and implementation-plan.md are balanced; every spike of the plan's Phase 0 table
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
from helpers import ROOT, DEFAULT_CONNECTOR, DEFAULT_IMAGE_REPO, DEFAULT_NAME, DEFAULT_VOLUME  # noqa: E402


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

    def test_decisions_d1_to_d40(self):
        ids = re.findall(r"^\| (D\d+) \|", DESIGN, re.M)
        self.assertEqual(sorted(set(ids), key=lambda x: int(x[1:])), ["D%d" % n for n in range(1, 41)])

    def test_ids_cited_exist(self):
        for name, text in (("plan", PLAN), ("design", DESIGN)):
            for b in set(re.findall(r"\bB(\d+)\b", text)):
                self.assertTrue(1 <= int(b) <= 36, "%s cites B%s" % (name, b))
            for d in set(re.findall(r"\bD(\d+)\b", text)):
                self.assertTrue(1 <= int(d) <= 40, "%s cites D%s" % (name, d))

    def test_design_range_statements_match(self):
        self.assertNotIn("D1 to D37", DESIGN)

    def test_appendix_a3_lists_all_facts(self):
        a3 = PLAN[PLAN.index("### A.3"):]
        ids = re.findall(r"^\| (B\d+) \|", a3, re.M)
        self.assertEqual(ids, ["B%d" % n for n in range(1, 37)])

    def test_appendix_a1_lists_all_decisions(self):
        a1 = PLAN[PLAN.index("### A.1"):PLAN.index("### A.2")]
        ids = re.findall(r"^\| (D\d+) \|", a1, re.M)
        self.assertEqual(ids, ["D%d" % n for n in range(1, 41)])

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


PHASE3_SLICES = ["3.1-host-helper-core", "3.2-create-flags-fingerprint", "3.3-up-reset-stop-url",
                 "3.4-host-connection-socket", "3.5-init-function-bootstrap", "3.6-update-registry", "3.7-host-closeout"]
PHASE3_FACTS = ["B5", "B19", "B20", "B21", "B22", "B23", "B31", "B32", "B33", "B34", "B35"]
PHASE3_CLOSE = DESIGN[DESIGN.index("#### Results of Phase 3 (slice 3.7") if "#### Results of Phase 3 (slice 3.7" in DESIGN else 0:
                      DESIGN.index("## 15. Roadmap")]


def phase3_close_rows(text):
    """Rows of a close-out table: first cell (an id, with the prefix "3.7 " in the design), then the other cells."""
    out = {}
    for l in text.splitlines():
        m = re.match(r"\| (?:3\.7 )?((?:B|D)\d+) \|(.*)\|\s*$", l)
        if m:
            out[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return out


class PhaseThreeCloseTest(unittest.TestCase):
    """Phase 3 close-out (slice 3.7)."""

    def test_status_row_per_slice(self):
        status = read("docs", "implementation-status.md")
        for sl in PHASE3_SLICES:
            r = [l for l in status.splitlines() if l.startswith("| %s |" % sl)]
            self.assertEqual(len(r), 1, sl)
            cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
            self.assertIn(cells[2], ("done", "partial", "blocked"), sl)

    def test_gate_row_is_partial_with_the_owner_actions_and_the_untestable_list(self):
        status = read("docs", "implementation-status.md")
        r = [l for l in status.splitlines() if l.startswith("| 3.gate |")]
        self.assertEqual(len(r), 1)
        cells = [c.strip() for c in r[0].strip().strip("|").split("|")]
        self.assertEqual(cells[2], "partial")
        for word in ("push", "CI", "arm64", "macOS", "WSL", "B31", "bash 3.2", "UID", "Podman older than 4.3",
                     "real registry", "Windows-drive", "sh/stat/sort"):
            self.assertIn(word, r[0], word)

    def test_row_3_7_records_the_regression_counts(self):
        status = read("docs", "implementation-status.md")
        r = [l for l in status.splitlines() if l.startswith("| 3.7-host-closeout |")][0]
        self.assertIn("run_all.sh", r)
        self.assertRegex(r, r"TOTAL \d+ files, \d+ tests, 0 failed files")

    def test_decision_log_has_a_3_7_entry_and_one_per_earlier_slice(self):
        log = read("docs", "decision-log.md")
        for n in range(1, 8):
            self.assertRegex(log, r"(?m)^## \[3\.%d\] " % n, "decision-log entry [3.%d]" % n)

    def test_every_phase3_command_row_of_a2_names_a_built_command(self):
        a2 = PLAN[PLAN.index("### A.2"):PLAN.index("### A.3")]
        helper = read("container", "host", "swarmbox-host")
        built = set(re.findall(r"^    ([a-z-]+)\) cmd_", helper, re.M))
        function = read("container", "host", "templates", "bash")
        rows3 = [l for l in a2.splitlines() if l.startswith("| `swarmbox") and re.search(r"\| [^|]*\b3\b[^|]*\|\s*$", l)]
        self.assertGreaterEqual(len(rows3), 6)
        for l in rows3:
            if "remote" in l:
                continue
            words = re.findall(r"`(?:swarmbox )?([a-z][a-z-]*)", l.split("|")[1])
            self.assertTrue(words, l)
            for w in words:
                if w in ("claude", "yolo", "tool", "pubkey", "attach", "command"):
                    continue
                self.assertTrue(w in built or w in function or w == "swarmbox", "%s is not built: %s" % (w, l))
        self.assertIn("--plain", function)
        self.assertNotIn("remote", built - {"remote"})

    def test_close_table_covers_every_phase3_decision_and_fact(self):
        sec = PLAN[PLAN.index("## 6. Phase 3"):PLAN.index("## 7. ")]
        self.assertIn("**3.7 state", sec)
        table = phase3_close_rows(sec)
        a1 = PLAN[PLAN.index("### A.1"):PLAN.index("### A.2")]
        want = []
        for l in a1.splitlines():
            m = re.match(r"\| (D\d+) \|.*\| ([^|]*) \| [^|]*\|\s*$", l)
            if m and re.search(r"\b3\b", m.group(2)):
                want.append(m.group(1))
        a3 = PLAN[PLAN.index("### A.3"):]
        for l in a3.splitlines():
            m = re.match(r"\| (B\d+) \|.*\| (\d+) \|", l)
            if m and m.group(2) == "3":
                want.append(m.group(1))
        self.assertGreaterEqual(len(want), 30)
        for k in want:
            self.assertIn(k, table, "%s has no row in the Phase 3 close table" % k)
            self.assertIn(table[k][0].split()[0].rstrip(",;."), ("closed", "reduced", "open"), k)
            self.assertTrue(table[k][1], k)
        for k in ("B31",):
            self.assertTrue(table[k][0].startswith("open"), k)

    def test_part_b_facts_of_phase3_carry_a_tag_or_unverified_with_a_pointer(self):
        self.assertIn("#### Results of Phase 3 (slice 3.7", DESIGN)
        table = phase3_close_rows(PHASE3_CLOSE)
        for b in PHASE3_FACTS:
            self.assertIn(b, table, b)
            state, where, tag = table[b][0], table[b][1], table[b][2]
            if b == "B31":
                self.assertIn("[unverified]", tag)
                self.assertIn("ci.yml", where)
                self.assertIn("arm64", where)
                self.assertIn("first CI run", where)
                continue
            self.assertRegex(tag, r"\[verified: [^\]]+\]|\[unverified[^\]]*\]", b)
            if "[unverified" in tag:
                self.assertRegex(tag, r"Phase [67]", b)
            for f in re.findall(r"tests/[A-Za-z0-9_]+\.py", tag):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), "%s names %s" % (b, f))

    def test_part_b_main_table_rows_are_marked_by_state(self):
        for b in PHASE3_FACTS:
            row = [l for l in PART_B.splitlines() if l.startswith("| %s |" % b)][0]
            if b == "B31":
                self.assertNotIn("**Closed", row)
                self.assertIn("ci.yml", row)
            else:
                self.assertRegex(row, r"\*\*(Closed|Linux part|Refusal logic)", b)

    def test_a_row_of_a3_for_b31_says_the_job_exists_but_never_ran(self):
        r = rows(PLAN[PLAN.index("### A.3"):], "B31")[0]
        self.assertIn("3.7", r)
        self.assertIn("never ran", r)

    def test_no_stale_phase3_wording_in_code_or_docs(self):
        pats = [r"Phase 3 writes", r"Phase 3 adds", r"until Phase 3", r"Phase 3 will", r"is a later phase and is not here",
                r"added by later phases"]
        files = [os.path.join(ROOT, f) for f in ("README.md", "Dockerfile", "CONTRIBUTING.md")]
        for base in ("container", "docs", "dev", ".github"):
            for d, _, names in os.walk(os.path.join(ROOT, base)):
                files += [os.path.join(d, n) for n in names if n.endswith((".md", ".sh", ".py", ".yml", "")) and "." in n or n in ("swarmbox-host", "bash", "zsh", "fish")]
        hits = []
        for f in files:
            if f.endswith("decision-log.md") or f.endswith("implementation-status.md"):
                continue    # history files may quote the old wording
            try:
                text = open(f, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for pat in pats:
                for m in re.finditer(pat, text):
                    hits.append("%s: %s" % (os.path.relpath(f, ROOT), pat))
        self.assertEqual(hits, [])

    def test_the_plan_marks_3_7_and_the_arm64_job(self):
        sec = PLAN[PLAN.index("## 6. Phase 3"):PLAN.index("## 7. ")]
        for word in ("arm64", "tests/run_all.sh", "B31", "bash 3.2", "dash", "busybox"):
            self.assertIn(word, sec, word)

    def test_design_13_4_describes_the_jobs_as_built(self):
        sec = DESIGN[DESIGN.index("### 13.4"):DESIGN.index("## 14. Open questions")]
        self.assertIn("`arm64` job", sec)
        self.assertIn("ubuntu-24.04-arm", sec)
        self.assertIn("SWARMBOX_TEST_BASH", sec)
        self.assertNotIn("are added by later phases", sec)

    def test_ci_files_named_in_the_docs_exist(self):
        for f in ("tests/run_all.sh", "tests/test_run_all.py", "tests/e2e_registry.py", "docs/local-registry.md"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), f)


class PhaseFourBCloseTest(unittest.TestCase):
    """Phase 4b close-out (slice 4b.7): the appendix rows of the phase point at closed or explicitly open evidence."""

    APPENDIX_IDS = ("D3", "D4", "D21", "D23", "D29", "B2", "B10", "B11", "B24", "B25")

    def test_appendix_a_has_one_row_per_id_naming_a_phase(self):
        app = PLAN[PLAN.index("## Appendix A. Where"):]
        for i in self.APPENDIX_IDS:
            r = rows(app, i)
            self.assertGreaterEqual(len(r), 1, i)
            self.assertRegex(r[0], r"\| (\d[ab]?|4a, 4b|2, 4b|0)\b", i)

    def test_partb_says_closed_or_names_what_is_open_for_each_id(self):
        for i in ("B2", "B10", "B11", "B24", "B25"):
            hits = re.findall(r"^\| %s \| \**(Closed|Reduced|Open|Unverified)\b(.*)$" % i, PART_B, re.M)
            self.assertGreaterEqual(len(hits), 1, i)
            for state, rest in hits:
                if state != "Closed":
                    self.assertTrue(rest.strip(" |"), i)  # an open fact says what is missing

    def test_design_6_9_and_the_plan_carry_the_4b_7_state_and_the_tests_exist(self):
        sec = DESIGN[DESIGN.index("### 6.9"):DESIGN.index("### 6.10")]
        self.assertIn("4b.7 state", sec)
        self.assertIn("tests/test_tool_real.py", sec)
        self.assertIn("4b.7 state", PLAN[PLAN.index("## 7. Phase 4b"):PLAN.index("## 8.")])
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "tests", "test_tool_real.py")))

    def test_every_tool_has_a_per_tool_result_line_with_an_evidence_tag_or_reduced(self):
        sec = DESIGN[DESIGN.index("### 6.9"):DESIGN.index("### 6.10")]
        for tool in sorted(os.listdir(os.path.join(ROOT, "container", "tools"))):
            lines = [l for l in sec.splitlines() if re.match(r"\s*- \*\*%s\*\*" % re.escape(tool), l)]
            self.assertEqual(len(lines), 1, tool)
            self.assertRegex(lines[0], r"\[verified: [^\]]+; 2026-\d\d-\d\d; [^\]]*\]|(?i:reduced|blocked)", tool)

    def test_status_rows_for_4b_7_and_the_gate(self):
        status = read("docs", "implementation-status.md")
        for sl in ("4b.7-real-installers-closeout", "4b.gate"):
            r = [l for l in status.splitlines() if l.startswith("| %s |" % sl)]
            self.assertEqual(len(r), 1, sl)
            self.assertIn([c.strip() for c in r[0].strip().strip("|").split("|")][2], ("done", "partial", "blocked"), sl)


CF_DOC = read("docs", "cloudflare.md")


class PhaseFiveDocsTest(unittest.TestCase):
    """Slice 5.6: docs/cloudflare.md matches the wrapper and carries the owner checklist."""

    def test_doc_names_every_remote_subcommand(self):
        helper = read("container", "host", "swarmbox-host")
        usage = re.search(r"remote ((?:[a-z]+\|)+[a-z]+) \[options\]", helper)
        self.assertTrue(usage)
        subs = usage.group(1).split("|")
        self.assertEqual(set(subs), {"setup", "status", "off", "token"})
        for sub in subs:
            self.assertIn("swarmbox remote %s" % sub, CF_DOC)
        dispatch = re.search(r"cmd_remote\(\) \{.*?\n\}\n", helper, re.S).group(0)
        self.assertEqual(set(re.findall(r"^        ([a-z]+)\) r_cmd=", dispatch, re.M)), set(subs))

    def test_doc_names_every_option_of_the_script(self):
        script = read("cloudflare-setup.py")
        opts = set(re.findall(r'add_argument\("(--[a-z-]+)"', script))
        opts -= {"--verify-timeout"}  # help=SUPPRESS: internal
        self.assertTrue(opts)
        for o in sorted(opts):
            self.assertIn("`%s`" % o, CF_DOC, o)
        self.assertIn("`-y`", CF_DOC)

    def test_help_and_doc_list_the_same_subcommands(self):
        helper = read("container", "host", "swarmbox-host")
        m = re.search(r"^  remote ((?:[a-z]+\|)+[a-z]+) \[options\]", helper, re.M)
        self.assertTrue(m)
        listed = set(m.group(1).split("|"))
        in_doc = set(re.findall(r"swarmbox remote ([a-z]+)", CF_DOC))
        self.assertEqual(listed, in_doc)

    def test_checklist_and_section_headings(self):
        self.assertRegex(CF_DOC, r"(?m)^## Owner checklist")
        sec = CF_DOC[CF_DOC.index("## Owner checklist"):]
        for step in ("remote setup --dry-run", "remote status", "from outside", "one-time code",
                     "podman-restart.service", "remote off"):
            self.assertIn(step, sec, step)
        for h in ("## What it provisions", "## Options", "## Tunnel token", "## Remote off", "## Rerun keeps the session",
                  "## The connector image", "## Running outside a box"):
            self.assertIn("\n" + h, CF_DOC, h)

    def test_connector_image_is_pinned_and_never_latest(self):
        self.assertNotRegex(CF_DOC, r"cloudflared:latest")
        script = read("cloudflare-setup.py")
        pin = re.search(r'DEFAULT_CONNECTOR_IMAGE = "([^"]+)"', script).group(1)
        self.assertIn(pin, CF_DOC)
        self.assertIn("SWARMBOX_CLOUDFLARED_IMAGE", CF_DOC)

    def test_code_fences_are_balanced_and_no_real_looking_token(self):
        self.assertEqual(len(re.findall(r"(?m)^```", CF_DOC)) % 2, 0)
        self.assertNotRegex(CF_DOC, r"eyJ[A-Za-z0-9_-]{10,}")
        self.assertNotRegex(CF_DOC, r"\b[A-Za-z0-9_-]{37,}\b(?<![a-z/.-]{37})")

    def test_cross_references_and_v010_only_as_history(self):
        for d in ("D14", "D16", "D28", "D39"):
            self.assertIn(d, CF_DOC)
        self.assertIn("5.2", CF_DOC)
        for line in CF_DOC.splitlines():
            if "start.sh" in line or "cloudflare-setup.py --" in line and "swarmbox" not in line:
                self.assertTrue("v0.1.0" in line or "history" in line.lower(), line)

    def test_design_plan_status_and_log_carry_5_6(self):
        sec = DESIGN[DESIGN.index("### 5.2 Remote"):DESIGN.index("## 6. Tools")]
        self.assertIn("docs/cloudflare.md", sec)
        self.assertIn("5.6 state", sec)
        status = read("docs", "implementation-status.md")
        r = [l for l in status.splitlines() if l.startswith("| 5.6-")]
        self.assertEqual(len(r), 1)
        self.assertIn("checklist", r[0])
        self.assertTrue(any(l.startswith("| 5.owner-checklist") for l in status.splitlines()))
        self.assertRegex(read("docs", "decision-log.md"), r"(?m)^## \[5\.6\] ")

    def test_phase_5_rows_and_gate_are_in_the_status_file(self):
        status = read("docs", "implementation-status.md")
        for n in range(1, 8):
            self.assertEqual(len([l for l in status.splitlines() if l.startswith("| 5.%d-" % n)]), 1, n)
        g = [l for l in status.splitlines() if l.startswith("| 5.gate")]
        self.assertEqual(len(g), 1)
        self.assertIn("| partial |", g[0])
        for word in ("real Cloudflare account", "reboot", "unverified", "cloudflared"):
            self.assertIn(word, g[0])
        plan = read("docs", "implementation-plan.md")
        sec = plan[plan.index("## 8. Phase 5"):plan.index("**Exit criteria:**", plan.index("## 8. Phase 5"))]
        self.assertIn("5.7 state", sec)
        self.assertRegex(read("docs", "decision-log.md"), r"(?m)^## \[5\.7\] ")


class ParityTableTest(unittest.TestCase):
    """Slice 6.1: design 13.2 maps every row of the feature catalog (8.4) to tests of tests/test_parity.py that exist."""

    @classmethod
    def setUpClass(cls):
        s = DESIGN.index("### 8.4 Feature catalog")
        e = DESIGN.index("## 9. Repository layout")
        cls.catalog = [l for l in DESIGN[s:e].splitlines()
                       if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Area")]
        s = DESIGN.index("### 13.2 Parity")
        cls.section = DESIGN[s:DESIGN.index("### 13.3 Test layers")]
        cls.defined = set(re.findall(r"(?m)^    def (test_\w+)\(", read("tests", "test_parity.py")))

    def test_the_catalog_has_14_rows(self):
        self.assertEqual(len(self.catalog), 14)

    def test_every_catalog_row_is_in_the_table_with_existing_tests(self):
        for n, row in enumerate(self.catalog, 1):
            area, feature = [c.strip() for c in row.strip().strip("|").split("|")[:2]]
            line = [l for l in self.section.splitlines() if l.startswith("| %02d |" % n)]
            self.assertEqual(len(line), 1, "row %02d (%s) is not in the table of 13.2" % (n, feature[:40]))
            self.assertIn(feature.replace("|", "/"), line[0], "row %02d names another feature than 8.4" % n)
            names = re.findall(r"`(test_row%02d_\w+)`" % n, line[0])
            self.assertTrue(names, "row %02d has no test" % n)
            for t in names:
                self.assertIn(t, self.defined, "row %02d names %s, which does not exist" % (n, t))

    def test_every_named_test_exists_and_the_12_sections_are_covered(self):
        for t in re.findall(r"`(test_(?:row\d\d|removed|kept|map)_\w+)`", self.section):
            self.assertIn(t, self.defined, t)
        for word in ("test_removed_host_network", "test_removed_uuid", "test_map_ports", "test_map_no_shell",
                     "test_kept_remote_browser"):
            self.assertRegex(self.section, word)

    def test_the_reduced_tag_is_explained(self):
        self.assertIn("[reduced:", self.section)
        self.assertIn("[unverified]", self.section)


# ---------------------------------------------------------------------------------------------------------------------
# Slice 6.5: README and docs/*.md rewritten for 2.0 (design 12.5, 3.8, D36; plan section 9).
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from helpers import FakePodman  # noqa: E402

README = read("README.md")
INIT_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
HOST = os.path.join(ROOT, "container", "host", "swarmbox-host")
OLD_NAMES = re.compile(r"(?<![\w/-])start\.sh|(?<![\w/-])build\.sh|(?<![/\w])lib/|\.work\b|~/\.swarmbox|--web\b|--reset\b|pkill ttyd|swarmbox-web-terminal|--env-keys")
INIT_ENV = {"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": os.path.join(ROOT, "container", "host")}
HOST_WORDS_ROUTED = ["stop", "reset", "up", "url", "update", "config", "env", "remote", "fingerprint", "version"]
FORWARDED_WORDS = ["attach", "pubkey", "tool", "--plain", "claude", "gemini", "yolo", "bash"]


def section(text, heading):
    """The text of a '## heading' section up to the next '## ' heading."""
    m = re.search(r"^## %s[^\n]*$" % re.escape(heading), text, re.M)
    assert m, "no section '## %s'" % heading
    n = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end():m.end() + n.start()] if n else text[m.end():]


def outside_fences(text):
    return re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)


def slug(h):
    h = re.sub(r"`", "", h.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(text):
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} +(.+?)\s*$", outside_fences(text), re.M)}


def uninstall_steps():
    sec = section(read("docs", "uninstall.md"), "Uninstall")
    parts = re.split(r"^(\d+)\. ", sec, flags=re.M)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def ticks(step):
    return re.findall(r"`([^`]+)`", step)


class ReadmeSixFiveTest(unittest.TestCase):
    def test_readme_is_short_and_has_the_sections(self):
        self.assertLess(len(README.splitlines()), 200)
        for h in ("Quick start", "Everyday commands", "Security", "Privacy"):
            section(README, h)
        self.assertRegex(README, r"(?m)^## Migrating from v0\.1\.0")
        self.assertEqual(README.count("```") % 2, 0)

    def test_quick_start_builds_locally_and_has_no_org_placeholder(self):
        self.assertNotIn("<org>", README)
        self.assertNotRegex(README, r"ghcr\.io")
        local = "localhost/" + DEFAULT_NAME + ":local"
        for cmd in ("podman build -t " + local + " .",
                    "podman run --rm -e SHELL " + local + " init --image " + local + " --with claude",
                    ">> ~/.zshrc", "swarmbox config set WEB_PORT 7682"):
            self.assertIn(cmd, section(README, "Quick start"), cmd)

    def test_readme_covers_the_topics(self):
        for needle in ("swarmbox config", "swarmbox env add", "swarmbox url", "swarmbox update", "swarmbox tool list",
                       "docs/cloudflare.md", "docs/web-terminal.md", "docs/nested-podman.md", "docs/uninstall.md",
                       "swarmbox remote setup", "swarmbox reset"):
            self.assertIn(needle, README, needle)

    def test_security_section_states_the_kernel_limit_and_no_safe_claim(self):
        sec = section(README, "Security")
        self.assertIn("shares the kernel", sec)
        self.assertIn("not a virtual machine", sec)
        self.assertNotRegex(sec.lower(), r"\b(is|are|completely|totally) (secure|safe)\b")

    def test_seven_uninstall_steps_in_order(self):
        steps = uninstall_steps()
        self.assertEqual(sorted(steps), [1, 2, 3, 4, 5, 6, 7])
        needles = {1: ["# >>> swarmbox 2.0.0 >>>", "# <<< swarmbox 2.0.0 <<<"], 2: ["podman rm -f swarmbox", "SWARMBOX_NAME"],
                   3: ["~/.local/share/swarmbox/host", "~/.local/state/swarmbox"], 4: ["~/.config/swarmbox"],
                   5: ["swarmbox remote off", DEFAULT_CONNECTOR], 6: [DEFAULT_VOLUME, "~/swarmbox"],
                   7: ["podman rmi", (DEFAULT_IMAGE_REPO + ":<tag>")]}
        for n, items in needles.items():
            for it in items:
                self.assertIn(it, steps[n], "step %d lacks %s" % (n, it))
        self.assertIn("before step 1", steps[5])

    def test_step_one_marker_text_is_the_functions(self):
        r = subprocess.run(["sh", INIT_SH, "--shell", "bash"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=INIT_ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        with open(os.path.join(ROOT, "container", "host", "VERSION")) as f:
            version = f.read().strip()
        first = [l for l in lines if l.startswith("# >>> swarmbox ")][0]
        last = [l for l in lines if l.startswith("# <<< swarmbox ")][0]
        self.assertEqual(first, "# >>> swarmbox %s >>>" % version)
        self.assertEqual(last, "# <<< swarmbox %s <<<" % version)
        self.assertIn(first, uninstall_steps()[1])
        self.assertIn(last, uninstall_steps()[1])

    def test_no_old_scripts_outside_the_migration_section(self):
        body = README.replace(section(README, "Migrating from v0.1.0"), "")
        for ln in body.splitlines():
            m = OLD_NAMES.search(ln)
            self.assertFalse(m and "v0.1.0" not in ln, "stale v0.1.0 text in the README: %r" % ln)

    def test_other_docs_name_no_old_instruction(self):
        for name in ("web-terminal.md", "nested-podman.md", "local-registry.md", "cloudflare.md"):
            text = read("docs", name)
            for ln in text.splitlines():
                m = OLD_NAMES.search(ln)
                self.assertFalse(m and "v0.1.0" not in ln and "history" not in ln,
                                 "docs/%s names the old way without marking it: %r" % (name, ln))

    def test_every_swarmbox_command_in_code_blocks_is_a_real_word(self):
        usage = subprocess.run(["sh", HOST], capture_output=True, text=True).stderr
        tool_words = set(re.findall(r"^    ([a-z]+)\) cmd_", read("container", "scripts", "swarmbox-tool.sh"), re.M))
        tool_words |= {"validate", "link"}
        subs = {"config": ["get", "set", "list", "seed"], "env": ["add", "rm", "list"], "remote": ["setup", "status", "off", "token"]}
        for w, words in subs.items():     # the helper's own usage must list each of them
            for x in words:
                self.assertRegex(usage, r"\b%s\b.*\b%s\b" % (w, x))
        seen = 0
        for block in re.findall(r"^```[a-z]*\n(.*?)^```", README, re.M | re.S):
            for ln in block.splitlines():
                words = ln.split("  #")[0].strip().split()
                while words and re.match(r"^[A-Z_]+=", words[0]):
                    words = words[1:]
                if not words or words[0] != "swarmbox":
                    continue
                seen += 1
                w = words[1] if len(words) > 1 else "attach"
                self.assertIn(w, HOST_WORDS_ROUTED + FORWARDED_WORDS, ln)
                if w in subs and len(words) > 2:
                    self.assertIn(words[2], subs[w], ln)
                if w == "tool" and len(words) > 2:
                    self.assertIn(words[2], tool_words, ln)
                if w in HOST_WORDS_ROUTED:
                    self.assertIn(w, usage, ln)
        self.assertGreater(seen, 8)

    def test_every_relative_link_resolves(self):
        files = [os.path.join(ROOT, n) for n in ("README.md", "SECURITY.md", "CHANGELOG.md")] + sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))
        bad = []
        for f in files:
            text = outside_fences(open(f, encoding="utf-8").read())
            text = re.sub(r"`[^`\n]*`", "", text)
            for m in re.finditer(r"\]\(([^)\s]+)\)", text):
                target = m.group(1)
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(f), path)) if path else f
                if not os.path.exists(dest):
                    bad.append("%s -> %s" % (os.path.relpath(f, ROOT), target))
                elif frag and dest.endswith(".md") and frag not in anchors(open(dest, encoding="utf-8").read()):
                    bad.append("%s -> %s (no such heading)" % (os.path.relpath(f, ROOT), target))
        self.assertEqual(bad, [])

    def test_telemetry_and_logs_statement_matches_design_12_5(self):
        sec = section(README, "Privacy")
        self.assertRegex(sec.lower(), r"no telemetry")
        d = DESIGN[DESIGN.index("### 12.5 Uninstall"):DESIGN.index("## 13. Tests and CI")]
        design_paths = re.findall(r"`([^`]*\.local/state/swarmbox/?)`", d)
        self.assertGreaterEqual(len(design_paths), 2)
        for p in design_paths:
            self.assertIn(p.replace("host:", ""), sec, p)
        for name in ("serve.log", "health", "web-terminal.log"):
            self.assertIn(name, sec)

    def test_security_md_states_the_same_policy_as_design_12_5(self):
        sec = read("SECURITY.md")
        d = DESIGN[DESIGN.index("### 12.5 Uninstall"):DESIGN.index("## 13. Tests and CI")]
        self.assertIn("no telemetry", sec.lower())
        for p in re.findall(r"`([^`]*\.local/state/swarmbox/?)`", d):
            self.assertIn(p, sec, p)

    def test_uninstall_paths_are_the_ones_dirs_sh_produces(self):
        home = "/home/fake"
        r = subprocess.run(["sh", "-c", '. "$1"; printf "%s\\n%s\\n%s\\n" "$SB_CONFIG_DIR" "$SB_DATA_DIR" "$SB_STATE_DIR"', "sh",
                            os.path.join(ROOT, "container", "scripts", "dirs.sh")],
                           capture_output=True, text=True, env={"HOME": home, "PATH": os.environ["PATH"]})
        cfg, data, state = [x.replace(home, "~") for x in r.stdout.split()]
        steps = uninstall_steps()
        self.assertIn(data + "/host", steps[3])
        self.assertIn(state, steps[3])
        self.assertIn(cfg, steps[4])
        self.assertIn("/swarmbox/host", read("container", "host", "templates", "bash"))
        self.assertNotIn("~/.swarmbox", README.replace(section(README, "Migrating from v0.1.0"), ""))

    def test_steps_one_to_four_on_a_fake_home(self):
        steps = uninstall_steps()
        home = tempfile.mkdtemp(prefix="swarmbox-test-65-")
        try:
            def w(rel, text="x\n"):
                p = os.path.join(home, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(text)
            fn = subprocess.run(["sh", INIT_SH, "--shell", "bash", "--with", "claude"], capture_output=True, text=True, env=INIT_ENV).stdout
            self.assertIn("# >>> swarmbox", fn)
            rc = "export A=1\n" + fn + "alias k=ls\n" + fn + "export B=2\n"     # a second init run leaves a second block
            w(".bashrc", rc)
            w(".local/share/swarmbox/host/swarmbox-host")
            w(".local/share/swarmbox/host/VERSION", "2.0.0\n")
            w(".local/state/swarmbox/notices")
            w(".local/state/swarmbox/locks/up.lock")
            w(".config/swarmbox/config", "WITH=claude\n")
            w(".config/swarmbox/cloudflare.json", "{}\n")
            w(".config/swarmbox/second/config", "WITH=\n")
            w(".local/share/other/keep")
            w(".config/other/keep")
            w("swarmbox/proj/file.txt")
            keep = {".local/share/other/keep", ".config/other/keep", "swarmbox/proj/file.txt"}
            with FakePodman() as fp:
                env = {"HOME": home, "PATH": fp.env()["PATH"]}
                for n in (1, 2, 3, 4):
                    cmds = [c for c in ticks(steps[n]) if re.match(r"(sed|podman|rm) ", c)]
                    self.assertTrue(cmds, "step %d has no command" % n)
                    for c in cmds:
                        if n == 1 and ".bashrc" not in c:
                            continue    # the zsh and fish lines are the same command on another file
                        r = subprocess.run(["sh", "-c", c], env=env, capture_output=True, text=True, cwd=home)
                        self.assertEqual(r.returncode, 0, "%s: %s" % (c, r.stderr))
                calls = fp.calls()
            self.assertIn(["rm", "-f", "swarmbox"], calls)
            self.assertIn(["system", "connection", "rm", "swarmbox"], calls)
            left = set()
            for d, _, names in os.walk(home):
                for n in names:
                    left.add(os.path.relpath(os.path.join(d, n), home))
            with open(os.path.join(home, ".bashrc")) as f:
                self.assertEqual(f.read(), "export A=1\nalias k=ls\nexport B=2\n")
            with open(os.path.join(home, ".bashrc.bak")) as f:
                self.assertEqual(f.read(), rc)
            self.assertEqual(left, keep | {".bashrc", ".bashrc.bak"})
        finally:
            shutil.rmtree(home, ignore_errors=True)


class DocsSixFiveTest(unittest.TestCase):
    def test_web_terminal_doc_is_2_0(self):
        t = read("docs", "web-terminal.md")
        for needle in ("swarmbox-web restart", "build-index.sh", "WEB_PORT", ".config/swarmbox/web-terminal.conf",
                       "swarmbox url", "swarmbox --plain", "web-terminal.log"):
            self.assertIn(needle, t, needle)
        self.assertEqual(t.count("```") % 2, 0)

    def test_nested_podman_doc_is_2_0(self):
        t = read("docs", "nested-podman.md")
        for needle in ("podman -c " + DEFAULT_NAME, DEFAULT_VOLUME, "swarmbox config set PORTS", "swarmbox reset",
                       "always on", "SWARMBOX_NAME", "/dev/net/tun"):
            self.assertIn(needle, t, needle)
        self.assertIn("[unverified", t)

    def test_design_and_plan_carry_the_6_5_state(self):
        self.assertIn("**6.5 state", PLAN)
        self.assertIn("**6.5 state", DESIGN)
        self.assertNotIn("their rewrite is the rest of Phase 6", DESIGN)
        self.assertNotIn("The documentation rewrite (README, `docs/web-terminal.md`, `docs/nested-podman.md`) remains", PLAN)

    def test_status_row_and_decision_log_entry(self):
        self.assertRegex(read("docs", "implementation-status.md"), r"(?m)^\| 6\.5-")
        self.assertRegex(read("docs", "decision-log.md"), r"(?m)^## \[6\.5\] ")


class OwnerChecksSixSixTest(unittest.TestCase):
    """Slice 6.6: the hardware checks are runnable checklists and every fact keeps an honest state."""
    FACTS = ("B6", "B7", "B8", "B15", "B19", "B21", "B22", "B23", "B32", "B34")
    DOC = read("docs", "owner-checks.md")
    STATUS = read("docs", "implementation-status.md")

    def state_rows(self):
        t = section(self.DOC, "State of each fact")
        return {m.group(1): m.group(0) for m in re.finditer(r"(?m)^\| (B\d+)[^|]*\|.*$", t)}

    def test_every_fact_is_in_the_state_table_open_with_the_owner(self):
        rows = self.state_rows()
        for b in self.FACTS:
            self.assertIn(b, rows, b)
            self.assertIn("open with the owner", rows[b], b)
            self.assertNotIn("closed", rows[b].replace("closed-reduced", "").replace("(Linux closed)", "").replace("closed-reduced)", ""), b)

    def test_every_fact_has_a_section_with_a_command(self):
        for b in self.FACTS:
            self.assertRegex(self.DOC, r"(?m)^(## .*|- \*\*)%s\b" % b, b) if b in ("B6", "B7", "B8", "B15") else self.assertIn("**%s**" % b, self.DOC)
        self.assertGreaterEqual(self.DOC.count("dev/owner-check.sh"), 10)
        self.assertEqual(self.DOC.count("```") % 2, 0)

    def test_every_script_id_and_option_in_the_doc_exists(self):
        ids = subprocess.run(["sh", os.path.join(ROOT, "dev", "owner-check.sh"), "--list"], capture_output=True, text=True).stdout.split()
        for i in ids:
            if i.startswith(("B", "box.")):
                self.assertIn(i.split(".")[0] if i.startswith("B") else i, self.DOC, i)
        with open(os.path.join(ROOT, "dev", "owner-check.sh")) as f:
            script = f.read()
        for opt in set(re.findall(r"`(--[a-z-]+)", self.DOC)):
            self.assertIn(opt, script, opt)

    def test_part_b_rows_stay_unverified_and_cite_the_doc(self):
        for b in ("B6", "B7", "B8", "B15"):
            row = rows(PART_B, b)[0]
            self.assertIn("Open with the owner after 6.6", row, b)
            self.assertIn("[unverified]", row, b)
            self.assertNotIn("[verified:", row, b)
        self.assertIn("docs/owner-checks.md", rows(PART_B, "B6")[0])
        self.assertIn("#### Results of Phase 6 (slice 6.6", DESIGN)

    def test_no_closed_claim_without_a_tag(self):
        res = DESIGN[DESIGN.index("#### Results of Phase 6 (slice 6.6"):DESIGN.index("## 15. Roadmap")]
        for line in res.splitlines():
            if line.startswith("| 6.6 "):
                self.assertIn("open with the owner", line)
                self.assertNotRegex(line.split("|")[2], r"(?i)\bclosed\b")

    def test_status_rows_are_blocked_needing_hardware_with_steps(self):
        self.assertRegex(self.STATUS, r"(?m)^\| 6\.6-owner-checks \|")
        for key in ("6.6-owner-b6-macos", "6.6-owner-b7-uid", "6.6-owner-b8-podman", "6.6-owner-b15-python", "6.6-owner-rechecks", "6.6-owner-dogfood"):
            m = re.search(r"(?m)^\| %s \|.*$" % re.escape(key), self.STATUS)
            self.assertTrue(m, key)
            self.assertIn("| blocked |", m.group(0), key)
            self.assertIn("needs real hardware", m.group(0), key)
            self.assertIn("docs/owner-checks.md", m.group(0), key)

    def test_plan_and_decision_log(self):
        self.assertIn("**6.6 state", PLAN)
        self.assertRegex(read("docs", "decision-log.md"), r"(?m)^## \[6\.6\] ")
        self.assertIn("docs/owner-checks.md", PLAN)


class PhaseSixCloseTest(unittest.TestCase):
    """Slice 6.7: the Phase 6 close-out. The design tree matches the repository, every reference resolves, M3 is reduced."""

    STATUS = read("docs", "implementation-status.md")
    LOG = read("docs", "decision-log.md")
    RETIRED = ("start.sh", "build.sh", "Dockerfile.v0.1.0", "lib", "container/scripts/init.sh", "container/opencode",
               "container/web/web-terminal.sh")

    def test_retired_files_are_absent_from_the_tree(self):
        for p in self.RETIRED:
            self.assertFalse(os.path.exists(os.path.join(ROOT, p)), p)

    def _table_13_1(self):
        sec = DESIGN[DESIGN.index("### 13.1 "):DESIGN.index("### 13.2 ")]
        return [l for l in sec.splitlines() if l.startswith("| `") and "test_" in l.split("|")[1] or l.startswith("| `helpers.py`")]

    def test_13_1_names_only_existing_files_or_marks_them_retired(self):
        rows = self._table_13_1()
        self.assertEqual(len(rows), 12)  # helpers.py and the 11 files of v0.1.0
        for row in rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            name = cells[0].strip("`")
            exists = os.path.isfile(os.path.join(ROOT, "tests", name))
            self.assertTrue(exists or "deleted" in cells[2], "%s: neither on disk nor marked deleted" % name)
            if not exists:
                # the replacement named in the row must exist
                for m in re.findall(r"`(test_[a-z0-9_]+\.py)`", cells[2]):
                    self.assertTrue(os.path.isfile(os.path.join(ROOT, "tests", m)), "%s -> %s" % (name, m))

    def test_13_1_lists_every_test_file_on_disk(self):
        sec = DESIGN[DESIGN.index("### 13.1 "):DESIGN.index("### 13.2 ")]
        final = sec[sec.index("**Final file list (slice 7.6)"):].split("\n\n")[0]
        listed = set(re.findall(r"`(test_[a-z0-9_]+\.py)`", final))
        disk = {f for f in os.listdir(os.path.join(ROOT, "tests")) if re.match(r"test_.*\.py$", f)}
        self.assertEqual(sorted(disk - listed), [], "on disk but not listed")
        self.assertEqual(sorted(listed - disk), [], "listed but not on disk")

    def test_plan_cites_only_known_decisions_and_facts(self):
        ds = set(re.findall(r"(?m)^\| (D\d+) \|", DESIGN))
        self.assertEqual(len(ds), 40)
        for d in set(re.findall(r"\bD(\d+)\b", PLAN)):
            self.assertIn("D" + d, ds, "plan cites D" + d)
        for b in set(re.findall(r"\bB(\d+)\b", PLAN)):
            self.assertTrue(1 <= int(b) <= 36, "plan cites B" + b)

    def test_code_fences_are_balanced_in_every_doc(self):
        for path in glob.glob(os.path.join(ROOT, "docs", "*.md")) + [os.path.join(ROOT, n) for n in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md")]:
            with open(path, encoding="utf-8") as f:
                n = sum(1 for l in f if l.lstrip().startswith("```"))
            self.assertEqual(n % 2, 0, path)

    def test_design_and_plan_carry_the_6_7_state(self):
        sec = DESIGN[DESIGN.index("## 12. Comparison"):DESIGN.index("## 13. Tests and CI")]
        self.assertIn("6.7 state", sec)
        self.assertIn("**6.7 state", PLAN)
        for text in (sec, PLAN):
            self.assertIn("M3", text)
        self.assertIn("reduced", PLAN[PLAN.index("**6.7 state"):])

    def test_status_has_every_phase_6_row_and_a_partial_gate(self):
        for sid in ("6.1-parity", "6.2-port-old-tests", "6.3-retire-scripts", "6.4-migration-e2e", "6.5-docs-rewrite",
                    "6.6-owner-checks", "6.7-closeout"):
            self.assertRegex(self.STATUS, r"(?m)^\| %s \| " % re.escape(sid))
        gate = re.search(r"(?m)^\| 6\.gate \|.*$", self.STATUS)
        self.assertIsNotNone(gate)
        row = gate.group(0)
        self.assertIn("| partial |", row)
        for needle in ("push", "owner-check.sh", "macOS", "WSL", "backup", "decision log", "M3"):
            self.assertIn(needle, row, needle)

    def test_every_phase_6_slice_has_a_decision_log_entry(self):
        for n in range(1, 8):
            self.assertRegex(self.LOG, r"(?m)^## \[6\.%d\] " % n)

    def test_audit_script_is_documented(self):
        self.assertIn("dev/final-audit.sh", read("CONTRIBUTING.md"))
        self.assertIn("final-audit", PLAN)


class PhaseSevenCloseTest(unittest.TestCase):
    """Slice 7.7: the Phase 7 close-out. M4 is prepared, not reached; the owner's ordered actions are in the gate row."""

    STATUS = read("docs", "implementation-status.md")
    LOG = read("docs", "decision-log.md")
    SLICES = ("7.1-policy-files", "7.2-third-party-notices", "7.3-security-review", "7.4-update-bot",
              "7.5-release-workflow", "7.6-release-readiness", "7.7-closeout")

    def test_status_has_rows_7_1_to_7_7_with_all_columns(self):
        for sid in self.SLICES:
            rows = [l for l in self.STATUS.splitlines() if l.startswith("| %s |" % sid)]
            self.assertEqual(len(rows), 1, sid)
            cells = [c.strip() for c in rows[0].strip().strip("|").split("|")]
            self.assertEqual(len(cells), 6, sid)
            self.assertTrue(all(cells), sid)
            self.assertIn(cells[2], ("done", "partial", "blocked"), sid)

    def test_gate_row_says_prepared_not_reached_with_the_ordered_actions(self):
        rows = [l for l in self.STATUS.splitlines() if l.startswith("| 7.gate |")]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("| partial |", row)
        self.assertIn("M4", row)
        self.assertIn("prepared", row)
        self.assertIn("not reached", row)
        order = ["contacts", "copyright holder", "name", "history", "push", "B30", "B31", "B28", "B6", "B15",
                 "v2.0.0", "release.yml", "B20"]
        self.assertIn("Ordered owner actions", row)
        row = row[row.index("Ordered owner actions"):]
        pos = [row.find(w) for w in order]
        self.assertNotIn(-1, pos, dict(zip(order, pos)))
        self.assertEqual(pos, sorted(pos), "the owner actions are not in the documented order")

    def test_every_phase_7_slice_has_a_decision_log_entry(self):
        for n in range(1, 8):
            self.assertRegex(self.LOG, r"(?m)^## \[7\.%d\] " % n)
        for n in range(1, 8):
            sec = self.LOG[self.LOG.index("## [7.%d] " % n):]
            sec = re.split(r"(?m)^## ", sec[3:])[0]
            for key in ("Context:", "Options:", "Chosen:", "Impact on the design:", "How to reverse:"):
                self.assertIn(key, sec, "[7.%d] lacks %s" % (n, key))

    def test_design_and_plan_carry_the_7_7_state(self):
        self.assertIn("7.7 state", DESIGN)
        self.assertIn("**7.7 state", PLAN)
        for text in (DESIGN[DESIGN.index("7.7 state"):][:1500], PLAN[PLAN.index("**7.7 state"):][:1500]):
            self.assertIn("M4", text)
            self.assertIn("prepared", text)

    def test_part_b_rows_touched_in_phase_7_keep_honest_tags(self):
        for b in ("B20", "B28", "B30", "B31"):
            row = [l for l in DESIGN.splitlines() if l.startswith("| %s |" % b)][0]
            self.assertTrue("[unverified" in row or "[verified:" in row, b)

    def test_new_files_are_documented_and_links_resolve(self):
        for name in ("release-check.sh", "final-audit.sh"):
            self.assertIn("dev/" + name, read("CONTRIBUTING.md"))
        for path in ("docs/security-review.md", "docs/release-checklist.md", "SECURITY.md", "CODE_OF_CONDUCT.md",
                     "CHANGELOG.md", "THIRD_PARTY_NOTICES.md", ".github/workflows/release.yml",
                     ".github/dependabot.yml"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)
            if path.endswith(".md"):
                with open(os.path.join(ROOT, path), encoding="utf-8") as f:
                    text = f.read()
                for target in re.findall(r"\]\(([^)#\s:]+)(?:#[^)]*)?\)", text):
                    base = os.path.dirname(os.path.join(ROOT, path))
                    self.assertTrue(os.path.exists(os.path.normpath(os.path.join(base, target))), "%s -> %s" % (path, target))


if __name__ == "__main__":
    unittest.main()
