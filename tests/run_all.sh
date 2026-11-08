#!/bin/sh
# run_all.sh: the full regression, one line per test file (slice 3.7, design 13.4).
#
# Usage: sh tests/run_all.sh [--werror] [--repeat N] [--only a.py,b.py] [--browser] [--list]
#   --werror   run each file as `python3 -W error` (the earlier phases did this for their own files)
#   --repeat N run each selected file N times (the lock and function tests are run three times in a row)
#   --only     a comma-separated list of file names inside tests/; a name that does not exist is an error
#   --browser  include the three browser tests (they need chromium and ttyd and run in the scheduled job)
#   --list     print the selected file names and stop
# Env: SWARMBOX_TESTS_DIR points the runner at another folder of test files (used by tests/test_run_all.py).
# Output: "<file> OK|FAIL <n> tests, <k> skipped" per run, then "TOTAL <f> files, <n> tests, <x> failed files".
# Exit status: 0 when every run passed, 1 when one failed, 2 on a usage error. It starts nothing but python3 and takes no
# action against the host (the tests make their own mktemp folders and swarmbox-test- names).
set -u
DIR=${SWARMBOX_TESTS_DIR:-$(cd "$(dirname "$0")" && pwd)}
WERROR=0
REPEAT=1
ONLY=""
BROWSER=0
LIST=0
while [ $# -gt 0 ]; do
    case $1 in
        --werror) WERROR=1; shift ;;
        --repeat) [ $# -ge 2 ] || { echo "run_all: --repeat needs a number" >&2; exit 2; }; REPEAT=$2; shift 2 ;;
        --only) [ $# -ge 2 ] || { echo "run_all: --only needs a list" >&2; exit 2; }; ONLY=$2; shift 2 ;;
        --browser) BROWSER=1; shift ;;
        --list) LIST=1; shift ;;
        *) echo "run_all: unknown option $1" >&2; exit 2 ;;
    esac
done
case $REPEAT in ''|*[!0-9]*|0) echo "run_all: --repeat needs a positive number" >&2; exit 2 ;; esac

if [ -n "$ONLY" ]; then
    FILES=$(printf '%s' "$ONLY" | tr ',' ' ')
    for f in $FILES; do
        [ -f "$DIR/$f" ] || { echo "run_all: no such test file: $f" >&2; exit 2; }
    done
else
    FILES=""
    for p in "$DIR"/test_*.py; do
        f=$(basename "$p")
        case $f in
            test_clipboard_bridge.py|test_web_style.py|test_tmux_browser_keys.py) [ "$BROWSER" = 1 ] || continue ;;
        esac
        FILES="$FILES $f"
    done
fi
if [ "$LIST" = 1 ]; then
    for f in $FILES; do echo "$f"; done
    exit 0
fi

OUT=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-test-runall.XXXXXX") || exit 2
trap 'rm -rf "$OUT"' EXIT HUP INT TERM
FLAGS=""
[ "$WERROR" = 1 ] && FLAGS="-W error"
RUNS=0
NFILES=0
TESTS=0
BAD=0
for f in $FILES; do
    NFILES=$((NFILES + 1))
    i=0
    while [ "$i" -lt "$REPEAT" ]; do
        i=$((i + 1))
        RUNS=$((RUNS + 1))
        # shellcheck disable=SC2086  # FLAGS is a list of options
        python3 $FLAGS "$DIR/$f" > "$OUT/log" 2>&1
        rc=$?
        n=$(sed -n 's/^Ran \([0-9][0-9]*\) tests\{0,1\} in .*/\1/p' "$OUT/log" | tail -n 1)
        k=$(sed -n 's/^OK.*skipped=\([0-9][0-9]*\).*/\1/p; s/^FAILED.*skipped=\([0-9][0-9]*\).*/\1/p' "$OUT/log" | tail -n 1)
        n=${n:-0}
        k=${k:-0}
        if [ "$rc" = 0 ]; then st=OK; else st=FAIL; BAD=$((BAD + 1)); fi
        printf '%s %s %s tests, %s skipped\n' "$f" "$st" "$n" "$k"
        if [ "$rc" != 0 ]; then tail -n 15 "$OUT/log" | sed 's/^/    | /'; fi
        TESTS=$((TESTS + n))
    done
done
if [ "$REPEAT" -gt 1 ]; then echo "TOTAL $RUNS runs"; fi
echo "TOTAL $NFILES files, $TESTS tests, $BAD failed files"
[ "$BAD" = 0 ]
