# History

These files record how SwarmBox 2.0 was built. They are records, not current documentation: they describe an earlier
design, name files and tests that no longer exist, and may contradict the code.

- `decision-log.md`: the reasoning of each decision, with options and how to undo it.
- `overnight-report.md`, `implementation-plan.md`, `implementation-status.md`: the build order, its progress and the wrap-up report.
- `cleanup-log.md`: the simplification steps that followed, with how to undo each.
- `test-suite-review/`: the review of the test suite for version 1: `baseline.md` (what the old suite needed and where its seconds went), `mutants.md` (what a sample of 250 mutations of the product code shows that the old suite does not check), `layout-move.md` (the move to `tests/fast`, `slow`, `e2e`), with the mutation plan and the kill matrix as JSON.

Decisions D1 to D40 that are still true are summarized in [../design.md](../design.md).
