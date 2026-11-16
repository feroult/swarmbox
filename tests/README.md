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

Targets: `fast` under 60 seconds on a 32-core machine, in parallel, offline, with a read-only root file system.

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
3. Use `support/helpers.py` (`ROOT`, `FakePodman`, ...) and the `*_support.py` of the area; fixtures live in `support/fixtures/`.
4. Name no default name, image repository or version as a literal (read `container/host/DEFAULTS`: `fast/test_default_names_lint.py` enforces it).
5. Run it alone, with `--werror`, and with `--repeat 3` for anything with processes or timing; then `sh tests/run.sh`.
6. If it must run on macOS (bash 3.2 as `/bin/sh`, a fake podman), add its file name to `support/macos.list`. That list is the only place CI reads.

CI (`.github/workflows/ci.yml`): `linux` runs fast and slow (tmux present, no browser); `macos` runs `tests/run.sh macos`; `smoke` and
`arm64` build the image and run `slow/smoke_image.py`; the scheduled `browser` job runs the whole slow suite with the gate set; `real-addons`
installs the addons for real. `fast/test_ci_workflow.py` keeps the workflow honest.

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
python3 dev/mutate.py tests container/scripts/swarmbox-tabs.py   # which test files cover a product file
```

Run it in the test image (it starts tmux, ttyd and Chromium through the tests): see the head of `dev/mutate.py` for the `podman run` command.
The baseline of the suite before the reorganisation is in `docs/history/test-suite-review/`.
