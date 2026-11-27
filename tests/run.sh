#!/bin/sh
# run.sh: the one runner of the test suite. A thin front end of tests/support/runner.py (python3 only).
#
#   sh tests/run.sh                  the fast tests (tests/fast), in parallel
#   sh tests/run.sh loop             inner loop: tests for changed files + guards (--fail-fast by default)
#   sh tests/run.sh commit           alias for fast (full local suite)
#   sh tests/run.sh smoke            alias for slow (pty, Chromium, Podman; use dev/test-slow.sh)
#   sh tests/run.sh slow             the integration tests (tests/slow): pty, Chromium, Podman (use dev/test-slow.sh)
#   sh tests/run.sh all              fast, then slow
#   sh tests/run.sh e2e              the harnesses with the real claude and the soak (manual)
#   sh tests/run.sh macos            the fast files of tests/support/macos.list (the macOS job)
#   options: -j N  --area NAME  --only a.py,b.py  --since REF  --fail-fast  --no-fail-fast  --list  --repeat N  --werror  --timeout S  --timing N  --durations N  --github  --help
# See tests/README.md. Exit status: 0 all passed, 1 a file failed, 2 usage.
here=$(cd "$(dirname "$0")" && pwd) || exit 2
exec python3 "$here/support/runner.py" "$@"
