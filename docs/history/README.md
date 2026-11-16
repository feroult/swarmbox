# History

These files record how SwarmBox 2.0 was built. They are records, not current documentation: they describe an earlier
design, name files and tests that no longer exist, and may contradict the code.

- `decision-log.md`: the reasoning of each decision, with options and how to undo it.
- `overnight-report.md`, `implementation-plan.md`, `implementation-status.md`: the build order, its progress and the wrap-up report.
- `cleanup-log.md`: the simplification steps that followed, with how to undo each.
- `test-suite-review/`: the review of the test suite for version 1: `baseline.md` (what the old suite needed and where its seconds went), `mutants.md` (what a sample of 250 mutations of the product code shows that the old suite does not check), `layout-move.md` (the move to `tests/fast`, `slow`, `e2e`), one ledger for each area of the simplification (`shell-and-host.md`, `python-services.md`, `guards-web-release-image.md`: where every old test went), `regressions.md` (every real bug of version 1 and the test that guards it; a layout test keeps the ids true) and `mutants-after.md` (the same 249 mutants against the new suite: 180 killed before, 217 now, none lost), with the mutation plan and the kill matrices as JSON.
  Result in one line: the old suite had 102 files and 1849 tests and took 351 s one file after the other (550 s with tmux, ttyd and Chromium visible); the new one has 81 fast files and 1426 tests that take 20 s in parallel (offline, read-only root, or on a laptop) and 19 slow files and 288 tests that take 105 s in Podman.

Decisions D1 to D40 that are still true are summarized in [../design.md](../design.md).
