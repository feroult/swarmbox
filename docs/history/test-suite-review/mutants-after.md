# Mutation comparison: the old suite and the new one

The same 249 mutants of `mutants-plan.json` (seed of the baseline, `dev/mutate.py`), replayed against the suite of this branch. The kill matrix of the old
suite is `mutants-kill-matrix.json`; the new one is `mutants-kill-matrix-after.json` (per mutant: before, after, which file killed it, in which layer).

## How it was run

- Test image `swarmbox-test-slow:tmux35` in Podman, `--network none`, the repository copied to a tmpfs, a private `HOME` and `TMPDIR` for every mutant, `--confirm`
  (a failing file runs once more; a file that then passes is a flake, not a kill).
- Phase 1, the **fast** files that cover each product file (`--layer fast`, 24 mutants in parallel, the mutant stops at its first failing file): 187 killed, 4 by a
  timeout that a file noticed, 38 survived, 21 stale.
- The 21 stale ones: the plan holds byte offsets and a few comments of the product had changed length since it was made (the test-suite commits touched comments of
  seven product files). `dev/mutate.py` now finds the mutant again by its line (`test_mutate.py`); 18 of the 21 ran again (15 killed by fast files, 3 survived: `busclient.py:53`, `policy.py:301`, `policy.py:322`, all survivors of the old suite too); 3 have several
  equal tokens on the line (`2` in `len(p) == 2`, `&&` four times in one `if`): each token was run as a mutant of its own, all killed except `len(p) > 2` -> `> 3`
  on `swarmbox-tabs.py:565`, which the old suite did not kill either (it is an equivalent change for every output tmux gives).
- Phase 2, the **slow** files (`--layer slow`, tmux 3.5a, `SWARMBOX_TEST_REAL_TMUX=1`) on the 44 mutants that no fast file killed.
- Which test files cover a product file: `dev/mutate.py` now follows the support modules (a test file that imports `tests/support/serve_support.py`, which names
  `entrypoint.sh`, covers it); the baseline's replay reported 56 false survivors without it.
- The three mutants left (`enable -f`, the disk note of a goal that did not fail, a line break in a setting) got a case in the cheapest layer, then ran again: killed.

## Result

| | mutants | killed |
|---|---|---|
| old suite | 249 | 180 (72 %) |
| this suite | 249 | **217 (87 %)** |

- **Killed before and not after: none.** (Two of the old kills were first reported stale; run by their line they are killed.)
- **Newly killed: 37** (of the 69 survivors of the old suite). 31 by the fast files that were written for the old survivors in the three areas of this review
  (the bus CLI and its supervisor, the host's connector and settings, the addon manager's doctor and install, the release scripts, record-checksums, the web restart,
  the risk table), 2 by slow files (`entrypoint.sh:117` by `test_attach_real.py`, `page.js:254` blur ends the recording by `test_voice_page_browser.py`), 3 by cases added in
  the Integrate step (`risk.py:304`, `service.py:506`, `config.py:90`), and 1 more kill of a stale mutant (`swarmbox-host:2607`).
- **Killed only by slow tests: 6** (4 that the old suite also killed only in its slow files: `banner.sh:195` by `test_banner_glint.py`, `ttyd-clipboard.js:58` by
  `test_clipboard_bridge.py`, `page.js:79` and `page.js:202` by `test_voice_page_browser.py`; and the 2 above). They are the cases that need a browser, a
  real tmux and a clock; nothing cheaper can see them.
- Still surviving (32), the same ones as before the review minus those above. Looked at one by one, they are of three kinds:
  - boundaries that no output tells apart (`< len` against `<= len` in the loops of `swarmbox-tabs.py` that cut a long line, `len(raw) > MAX_LINE` in the bus client and
    the broker, the `Gt -> GtE` of a `len(a) > 1`), and a belt-and-braces `os.chmod(self.path, 0o600)` after a `umask(0o177)` bind (the mode is asserted by the permission test);
  - the length of a wait (`self.cond.wait(...)` of the service loop, `self.stop.set()` of the dock thread) that only a test of the timing itself would see;
  - the text of a message (`brain.py:259`, `watch.py:133`, `watch.py:141`, `tabsclient.py:38`), and the `dirty` flag of the policy's memory of what was typed after Esc
    (it differs only for a prompt that is empty and unreliable at once, which `_agent_start` checks anyway).

  The kill-matrix file lists each of them (`"after": "survived"`).

## By product file (before / after killed, of the mutants planned)

The 38 product files with the largest changes: `swarmbox-bus.py` 6 -> 15 of 18, `swarmbox-host` 13 -> 20 of 20, `swarmbox-addon.sh` 9 -> 16 of 18, `risk.py` 15 -> 17 of 21,
`entrypoint.sh` 15 -> 16 of 16, `cloudflare-setup.py` 2 -> 4 of 4, `release.sh` 3 -> 4 of 4, `swarmbox-web.sh` 4 -> 5 of 5, `page.js` 2 -> 3 of 3; every other file kept its count.
The full table is the matrix file.
