"""Docs consistency check for Part B of docs/design.md (the facts closed by the Phase 0 documentation reads).

For B4, B11, B14, B16 and B25 (slice 0.4): the Part B row says it was closed or checked in 0.4; at least one citing
line outside Part B carries an evidence tag `[verified: how; date; Podman and OS; image]` or `[unverified]`; every
`[verified:` tag in the file has the five parts and an ISO date; the recorded checksums are 64 hex digits; and the
code fences of design.md and implementation-plan.md are balanced.
Run: python3 tests/test_design_partb.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

DESIGN = open(os.path.join(ROOT, "docs", "design.md"), encoding="utf-8").read()
PLAN = open(os.path.join(ROOT, "docs", "implementation-plan.md"), encoding="utf-8").read()
TOUCHED = ["B4", "B11", "B14", "B16", "B25"]
TAG = re.compile(r"\[verified: [^\]]*\]")


def part_b_split():
    i = DESIGN.index("| ID | Fact | Test that closes it | Where cited |")
    return DESIGN[:i], DESIGN[i:]


class PartBTest(unittest.TestCase):
    def test_rows_say_closed_or_checked_in_0_4(self):
        _, tail = part_b_split()
        for b in TOUCHED:
            row = [l for l in tail.splitlines() if l.startswith("| %s |" % b)]
            self.assertGreaterEqual(len(row), 1, b)   # the table row, then the row of the results table
            self.assertRegex(row[0], r"(Closed|Checked|Partly checked) in 0\.4", b)

    def test_each_touched_fact_has_a_tag_where_cited(self):
        head, _ = part_b_split()
        for b in TOUCHED:
            lines = [l for l in head.splitlines() if re.search(r"\b%s\b" % b, l)]
            self.assertTrue(lines, "%s is not cited outside Part B" % b)
            self.assertTrue(any(TAG.search(l) or "[unverified]" in l for l in lines),
                            "%s has no evidence tag or [unverified] where cited" % b)

    def test_verified_tags_are_well_formed(self):
        tags = [t for t in TAG.findall(DESIGN) if "; date;" not in t and "not recorded" not in t]   # not the format's own description
        self.assertTrue(tags)
        for t in tags:
            parts = [p.strip() for p in t[len("[verified:"):-1].split(";")]
            self.assertGreaterEqual(len(parts), 4, t)
            self.assertTrue(any(re.fullmatch(r"\d{4}-\d\d-\d\d", p) for p in parts), "no date in " + t)

    def test_recorded_checksums_are_64_hex(self):
        for m in re.finditer(r"SHA256_(?:amd64|arm64)=`?([0-9a-fA-F]+)`?", DESIGN):
            self.assertRegex(m.group(1), r"^[0-9a-f]{64}$")
        for want in ("65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40",
                     "a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49",
                     "16fda6058d66e4ec29e8575e2b6e19b0d03cea7b091e6730f7e8361209e6955f",
                     "cc584dabf7b1f7ba79354744027b6de654ff6876c03dffb2174c1b1e3c0c6956"):
            self.assertIn(want, DESIGN)

    def test_fences_balanced(self):
        for name, text in (("design", DESIGN), ("plan", PLAN)):
            n = len([l for l in text.splitlines() if l.lstrip().startswith("```")])
            self.assertEqual(n % 2, 0, name)


if __name__ == "__main__":
    unittest.main()
