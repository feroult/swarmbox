# Test suite overhaul: summary

Done overnight on branch `sysop-v1` (from `ff7ddf6`). The goal: a suite that is organised, fast and simple, with a clear split between fast and slow tests, and
without losing coverage of the cases that can bring a regression back (coverage here is behaviours and past bugs, not a percentage).

## Numbers

| | Before (`ff7ddf6`) | After |
|---|---|---|
| Fast suite wall time | about 424 s, files one after the other | **20 s** (`-j 8`, 150 s of file time), measured again on a clean copy of the last commit |
| Fast suite files / tests | 98 / 1795 | 81 / 1424, 0 failed |
| Slow suite (real tmux, pty, ttyd, Chromium, Podman) | mixed into the one run | 20 files, about 286 tests, about 105 s at `-j 3` in Podman, on tmux 3.5a and 3.7c |
| Test functions in the repository | about 1798 | 1661 |
| Lines of test code | 36653 | 36819 (the suite is better organised, **not smaller by line count**: the runner, the layout guards and the mutation harness added about what the removed tests took out) |
| Longest fast file | `test_sysop_panel.py`, 47 s | `test_sysop_service.py`, 10 s |
| Under load (all cores busy, or two cores) | | 40 s to 178 s, and it still passes: tests wait for an effect, not for a duration |

## Structure

`tests/fast` (no real tmux, browser, podman or network; runs offline with a read-only root), `tests/slow` (integration: real tmux, pty, ttyd, Chromium, Podman),
`tests/e2e` (the harnesses with the real `claude` and the soak: manual), `tests/support` (helpers and fixtures). One runner, `sh tests/run.sh [fast|slow|all|e2e|macos]`
with `-j`, `--only`, `--list`, `--repeat`, `--shuffle`, `--werror`, `--timing`. `dev/check.sh` and the pre-push hook run shellcheck and the fast suite; `dev/test-slow.sh`
runs the slow suite in Podman (recipe in `dev/test-image/Containerfile`). See `tests/README.md`.

## The safety net

`dev/mutate.py` applies small bugs to the product code (249 mutants over 40 files, weighted to logic that can regress) and runs the tests that cover each one.
The old suite killed 180; the new one kills 216 (206 by the fast layer, 5 more by the slow layer, 5 stale-offset ones applied by hand). **No mutant that the old suite killed
is alive now.** One mutant that no suite ever killed is still alive and is behaviourally redundant (`entrypoint.sh`, the `rm -f` of the supervisors' pid files).
Every real bug of version 1 has a regression test in the new suite: `regressions.md` maps each bug to its test and layer, and a layout test keeps that ledger resolvable.

## What is still weak

- Files and classes named by where a bug was found (`test_sysop_soak.py` has 21 classes); four fast files and two slow files import another test file as a library.
- The fake install world is repeated in the three addon test files, and `write()` is copied into five files.
- The real-tmux gate (`SWARMBOX_TEST_REAL_TMUX=1`) is spelled out in about eight places with different messages.
- The idle-CPU measurements in `test_sysop_always` (104 s) and `test_sysop_dock` (69 s) are the long poles of the slow suite.
- A few wall-clock bounds remain (`test_serve_steps`, `test_sysop_soak`, `test_host_up`); none failed under load.
- `dev/check.sh` fetches shellcheck 0.9.0 with pip, so that step fails offline while the tests pass.
- Survivors of the mutation run that no test checks and that matter: publish commands (twine, cargo, gem) and `kubectl delete` / `terraform` clauses in the risk classifier,
  the validation of `voice.stt.model` and `voice.stt.vocabulary` in the host, the refusal to replace a foreign DNS record in `cloudflare-setup.py`; see `mutants.md`.

The ledgers of each area (`shell-and-host.md`, `python-services.md`, `guards-web-release-image.md`), the baseline and the kill matrices are in this folder.
