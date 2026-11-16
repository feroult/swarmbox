# The move to tests/fast, tests/slow, tests/e2e and tests/support

A pure move first (no test was simplified), so that structure and content do not mix. What changed besides the moves is listed at the end.

## Proof that the move changed nothing

Same commit, same machine. Tests that ran / skipped / failed:

| Environment | Before (one file at a time) | After (`tests/run.sh`) |
|---|---|---|
| host, tmux, ttyd, chromium and podman hidden | 102 files, 1849 tests, 308 skipped, 0 failed | fast: 87 files, 1492 tests, 9 skipped, 0 failed |
| Podman offline, read-only, `--network none` (`dev/test-slow.sh fast`) | the same 102 files (`test_dev_check` needed a `.git`, see baseline.md) | fast: 87 files, 1492 tests, 6 skipped, 0 failed |
| Podman, gates on (`dev/test-slow.sh slow`) | the 17 slow files: 368 tests, 57 skipped, 0 failed | slow: 17 files, 368 tests, 57 skipped, 0 failed |
| macOS list (host, fast files only) | the 31 files of the two lists of `ci.yml` | `tests/run.sh macos`: 30 files, 373 tests, 0 failed (`test_image_build.py`, which skipped all 4 tests off a built image, is a slow file now) |

Per file the counts are equal (`compare.py` in the review's scratch directory): the 85 fast files kept their number of tests; the differences are the ones below.
`dev/check.sh` ends `CHECK OK`. The tests of one file do not depend on a layer: `fast/test_layout.py` fails when a fast file imports a slow one.

## Times

| | Before | After |
|---|---|---|
| default run (host) | `tests/run_all.sh`, one file at a time: 351 s of file time, "about 7 minutes" with start-up | `tests/run.sh`: fast, 342 s of file time, **wall 56 s at `-j 8`** (idle machine, 32 cores) |
| default run, offline read-only Podman | 550 s sequential (the image has tmux, chromium, ttyd: the browser files run) | fast: wall 56 s at `-j 8` |
| slow suite in Podman | (mixed into the 550 s, and the gated files were not in any default run) | 507 s of file time, wall 181 s at `-j 3` (`sysop_always` 107 s alone) |

The fast wall time is the longest file: `test_sysop_panel.py` takes 47 s of the 56 s. `-j 16` gives 47 s. The area work trims those files.

## What is where

- `tests/fast` 87 files, `tests/slow` 17 files (+ `smoke_image.py`, which is not a unittest file), `tests/e2e` 3 harnesses and their `.sh`, `tests/support` helpers, `*_support.py`, `fixtures/`, `reap_run.py`, `runner.py`, `macos.list`. `baseline.md` has the classification of every file.
- Rule used: a file is slow when at least half of its tests need a real tmux, browser, Podman, network or the image (they skip without it); a fast file with a small gated tail (`test_addon_voice` 1 of 12, `test_host_socket`, `test_ci_workflow`, `test_release_workflow`, `test_addon_manifest`, `test_addon_shim`, `test_bashrc_fragment`, `test_host_shells`, `test_starship`) stays fast and the tail still skips there. The seventeen slow files also have fake-tmux halves that could be fast (see baseline.md): splitting them is a change of content.

## Changes of content (the only ones)

- `run_all.sh` and `test_run_all.py` became `run.sh` + `support/runner.py` and `fast/test_runner.py` (7 tests became 8: selectors, `--only`, `-j`, timeouts, the `--github` annotation).
- `fast/test_ci_workflow.py`: the checks that named the old runner, the macOS file lists and the browser files now check the new jobs (14 tests before, 14 after: one pair merged, one added that a step name is valid YAML: `name: a: b` is an error that makes GitHub show no job at all, and the first draft of the new `ci.yml` had it).
- New: `fast/test_layout.py` (5 tests: no test file outside its folder, no fast file imports a slow one, the macOS list names existing fast files, the pins of `dev/test-image/Containerfile` equal those of the `Dockerfile`, the scripts parse), `fast/test_mutate.py` (5 tests of `dev/mutate.py`).
- `test_web_build.py` read two path constants from `test_clipboard_bridge.py` (a slow file); it defines them itself now. `slow/test_web_strip.py` adds `tests/fast` to its path (a slow test may import a fast one).
- The path of every moved file in docs, comments and `ci.yml` was rewritten (a few product files carry comments that name a test path: comment-only changes).

## Found on the way (for the area agents)

- `slow/test_sysop_real.py` ends with `pgrep -f fixtures/sysop/bin/claude` over the whole machine: it fails whenever another test or mutant has a fake `claude` running. It breaks under any parallel run of two sysop files (`run.sh slow -j 3` can hit it) and the mutation run (9 of 40 controls). It must look at its own processes.
- `fast/test_sysop_service.py` failed once in five runs at `-j 16 --werror` (a `JSONDecodeError`: a file read while it is being written). It passed at the default `-j 8` every time.
- Leaks the runner reports as `reaped N`: `slow/test_sysop_web.py` (4).
- The fast files `test_sysop_panel`, `test_pull_ui`, `test_host_remote`, `test_host_update` use a pty and `test_sysop_service`, `test_voice_front`, `test_bus_cli`, `test_serve_steps` start long-lived processes: they are fast by the rules (no real tmux, browser, Podman or network) but slow in seconds.
