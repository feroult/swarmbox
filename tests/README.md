# The tests

Python `unittest` files, standard library only, one runner. They are split by what they need, so that the default run is fast and
the slow ones run where their programs are (a container).

```
tests/
  run.sh              the one runner (sh tests/run.sh [fast|slow|all|e2e|macos] ...)
  fast/               no real tmux, browser, Podman or network, no long waits. The default. dev/check.sh and the pre-push hook run it.
  slow/               integration: real tmux, a pty, ttyd, Chromium, Podman, the image. Skips with a message when a program is missing.
  e2e/                harnesses with the real `claude` and the long soak (manual, never in a default run)
  support/            helpers.py (FakePodman and friends), *_support.py, fixtures/, reap_run.py, runner.py, macos.list
```

## Running

```
sh tests/run.sh                         # fast, in parallel (-j: the CPUs up to 8), one line per file, the slowest files at the end
sh tests/run.sh slow                    # slow (3 files at a time): in a container, see below
sh tests/run.sh all                     # fast, then slow
sh tests/run.sh e2e                     # the manual harnesses (they start containers and need a Claude login)
sh tests/run.sh macos                   # the fast files of support/macos.list: what the macOS job runs
sh tests/run.sh --only test_bus.py      # one file, wherever it is (a name that does not exist is an error)
sh tests/run.sh --list | --repeat 3 | --werror | -j 16 | --timing 25 | --timeout 600 | --durations 10
python3 tests/fast/test_bus.py          # one file directly (the usual way when you work on it)
sh dev/test-slow.sh                     # slow, in Podman, in the image of dev/test-image/Containerfile (built when missing)
sh dev/test-slow.sh fast                # fast in the same offline, read-only container: the world of a CI runner
sh dev/test-slow.sh --tmux 37           # with tmux 3.7c, the version of the product image (default 3.5a)
sh dev/check.sh                         # shellcheck + the fast tests in a clean environment (also run by the pre-push hook)
```

`--werror` runs each file as `python3 -W error`; `--github` adds a GitHub annotation for a failed file (CI). Every file runs under
`support/reap_run.py`: when it ends, the processes it left behind are found by PID (never by name), killed and shown as `reaped N`.
A test that leaks a process is a bug in that test: end children in `addCleanup`.

Targets and what they measure today (32 cores, Podman, tmux 3.5a): `fast` under 60 seconds in parallel, offline, with a read-only root file system:
81 files, 1426 tests, 20 s wall (150 s of file time at `-j 8`, the same in `sh dev/test-slow.sh fast`); `slow` 19 files, 288 tests, about 105 s at `-j 3`
(`test_sysop_always` 104 s and `test_sysop_dock` 71 s are the long poles; the same with tmux 3.7c). A loaded machine (every core busy, or two cores for the
whole run) takes 2 to 9 times longer (40 s, 80 s and 178 s in the three runs of the review) and still passes: the tests wait for the effect they check, never for a fixed time.

## Which folder

A test goes in **fast** when it needs only: python3, sh/bash, the programs in `PATH` that every CI runner has (jq, git, node if the test skips
without it), fake binaries that the test writes (a fake `podman`, a fake `tmux`, a fake `claude`), our own scripts as processes, and a
`mktemp` world. No port other than `127.0.0.1` on a free port, no sleep for a clock to run out: inject the clock or shorten the
constant with the environment variable the product reads for tests.

A test goes in **slow** when it needs a real tmux, a pty against a real service, ttyd, Chromium, Podman, the built image, the network, or
a wait that cannot be injected. The rules:

- It must skip, not fail, when the program is missing, with a message that says what to install (`@unittest.skipUnless(shutil.which("tmux"), "needs tmux")`).
- Anything that starts a real tmux, ttyd or a browser also needs `SWARMBOX_TEST_REAL_TMUX=1`: only a container sets it (`dev/test-slow.sh`, the
  `browser` job of CI), never a machine whose tmux you use. The tests use a private socket (`-L swarmbox-test-<random>` and `TMUX_TMPDIR`
  in a `mktemp` directory) and stop it by that exact name, but the gate is the second lock.
- The tests that build the image or install for real are gated by `SWARMBOX_IMAGE_BUILD=1`, `SWARMBOX_TEST_NETWORK=1`,
  `SWARMBOX_REAL_VOICE_INSTALL=1`, `SWARMBOX_TEST_NESTED=1`; CI sets them in its own jobs.
- A slow file may import a fast one (`sys.path` to `../fast`); a fast file never imports a slow one (`fast/test_layout.py` checks it).
  Shared code goes to `support/`.
- `slow/smoke_image.py` is the image smoke test (not a unittest file, so the runner does not collect it): `SWARMBOX_IMAGE_BUILD=1 python3 tests/slow/smoke_image.py`.

**e2e** is for what costs money or minutes and needs a login or a soak: `e2e/e2e_sysop.sh`, `e2e/e2e_voice.sh`, `e2e/soak_v1.sh` start the
container themselves and pass the Claude login without printing it. They are never part of `all`.

## Adding a test

1. Decide the folder by the rules above; write `tests/fast/test_<area>_<what>.py` (or `slow/`) as a `unittest` file that ends with `unittest.main()`.
2. Start it with the bootstrap that every file has:
   ```python
   import os, sys, unittest
   sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
   sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
   from helpers import ROOT  # noqa: E402
   ```
3. Use `support/helpers.py` (`ROOT`, `FakePodman`, ...) and the `*_support.py` of the area; fixtures live in `support/fixtures/`. Never sleep for a fixed time: `support/waiting.py` has `wait_until(fn, seconds)`. A browser test uses `support/browser_support.py` (one `Chromium` per file, a `WebTerminal` per test: a real ttyd over a real tmux in a private socket); a guard that reads every file of the repository uses `support/repo_scan.py` (one `git ls-files`, each file read once).
4. Name no default name, image repository or version as a literal (read `container/host/DEFAULTS`: `fast/test_guard_names.py` enforces it).
5. Run it alone, with `--werror`, and with `--repeat 3` for anything with processes or timing; then `sh tests/run.sh`.
6. If it must run on macOS (bash 3.2 as `/bin/sh`, a fake podman), add its file name to `support/macos.list`. That list is the only place CI reads.

CI (`.github/workflows/ci.yml`): `linux` runs fast (also in the dash and busybox step) and the slow files that need no gate (the gate is off there, so the real-tmux and browser parts skip: that is 271 of 288 slow tests, checked in a container with tmux and without ttyd and Chromium); `macos` runs `tests/run.sh macos`; `smoke` and
`arm64` build the image and run `slow/smoke_image.py`; the scheduled `browser` job runs the whole slow suite with the gate set; `real-addons`
installs the addons for real. `fast/test_workflows.py` keeps both workflows honest.

## Tests that do not flake

A test that passes on a quiet machine and fails on a loaded one is a bug of the test. What was found and fixed in this suite, as the rules to follow:

- Wait for the effect, not for a duration: `support/waiting.py` `wait_until(fn, seconds)`. Where a service writes two things one after the other (the
  state file of a goal, then its audit line), wait for the LAST one. A supervisor that starts a child in the background is not started yet when its readiness
  marker appears.
- Do not assert an exact split of work between threads that read a socket (`5` and `5`): the bus does not give a message to a member that has not read the last one,
  so a slow reader changes the split. Wait for each read before the next publish, or assert the sum.
- A file that is cut and rewritten (the log trimmer) is empty for a moment: wait for the finished content, not for the size.
- End what the test starts in `addCleanup`, with the same environment that started it (a tmux server started with another `TMUX_TMPDIR` is not found by a bare `tmux kill-server`).
- Check a new test the way a loaded CI runner would: `taskset -c 0,1 sh tests/run.sh --only test_x.py --repeat 20` while four `python3 -c 'while True: pass'`
  (started by you, stopped by PID) run on the same two cores.

## The regression ledger

`docs/history/test-suite-review/regressions.md` lists the real bugs of version 1 and the test that guards each one (`layer/test_file.py::Class::test`).
`fast/test_layout.py` fails when a test named there no longer exists. When you fix a bug, add the test and one row.

## Coverage is behaviours, not a percentage

What a regression can bring back is the set of distinct behaviours and past bugs. Before you delete or merge a test, know which case it
protects and where that case is checked afterwards (a cheaper test, a table row, or a slow test). `dev/mutate.py` measures it: it applies
about 250 small mutations to the product code (a comparison flipped, a condition negated, an exit code or a constant moved, a call dropped,
`and` swapped with `or`, a case branch that never matches), runs the test files that cover each product file, and records the mutant as
killed or survived. A plan file replays the same mutants against a changed suite:

```
python3 dev/mutate.py plan --out /tmp/plan.json                  # choose the mutants (seed and weights: dev/mutate.py)
python3 dev/mutate.py run --plan /tmp/plan.json --results /tmp/r.jsonl -j 8 --all-tests --confirm --control
python3 dev/mutate.py report --plan /tmp/plan.json --results /tmp/r.jsonl --matrix /tmp/matrix.json
python3 dev/mutate.py tests container/scripts/swarmbox-tabs.py   # which test files cover a product file (it follows the modules of tests/support they import)
python3 dev/mutate.py run --plan P --results R --layer fast       # only the fast files: cheap, run the survivors again with --layer slow
```

A mutant that moved because a comment above it changed length is found again by its line. The plan of the baseline (249 mutants) is
`docs/history/test-suite-review/mutants-plan.json`; the old suite killed 180 of them and this one kills 217, none lost
(`mutants-after.md`, the matrix in `mutants-kill-matrix-after.json`).

Run it in the test image (it starts tmux, ttyd and Chromium through the tests): see the head of `dev/mutate.py` for the `podman run` command.
The baseline of the suite before the reorganisation is in `docs/history/test-suite-review/`.
