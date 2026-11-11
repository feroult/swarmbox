#!/bin/sh
# check.sh: the checks of .github/workflows/ci.yml that can run on this machine, before a push.
#
# Usage: sh dev/check.sh [--release] [--no-tests] [--no-shellcheck] [--print-shellcheck]
#   (nothing)           shellcheck 0.9 on the files ci.yml lists, then the unit tests in a clean environment
#   --release           also dev/release-check.sh (the tag is about to be pushed: it must print RELEASE CHECK OK)
#   --no-tests          skip the unit tests
#   --no-shellcheck     skip shellcheck
#   --print-shellcheck  print the shellcheck commands taken from ci.yml and stop
#
# Why each part exists:
#   Lint        CI runs shellcheck 0.9 over the new shell files. The file lists are read from ci.yml itself, so they cannot drift. The
#               exact version is used because another one reports other things; when none is installed, it is fetched with pip into
#               ${XDG_CACHE_HOME:-~/.cache}/swarmbox-dev (set SWARMBOX_SHELLCHECK to use a binary of your own).
#   Tests       a CI runner has no TERM, no COLORTERM, no STARSHIP_SHELL: a test that only passes with the variables of your terminal
#               passes here and fails there. The tests run under `env -i` with PATH, HOME and a UTF-8 LANG only.
# What it cannot cover: the macOS job (bash 3.2), the arm64 job and the image smoke test exist only in CI.
# Exit: 0 when everything that ran passed, 1 otherwise.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
CI=.github/workflows/ci.yml
SC_VERSION=0.9.0
SC_PIP=0.9.0.6

DO_TESTS=1
DO_SC=1
DO_RELEASE=0
PRINT=0
for a in "$@"; do
    case $a in
        --release) DO_RELEASE=1 ;;
        --no-tests) DO_TESTS=0 ;;
        --no-shellcheck) DO_SC=0 ;;
        --print-shellcheck) PRINT=1 ;;
        *) echo "check.sh: unknown option $a" >&2; exit 2 ;;
    esac
done

BAD=0
say() { printf '%s\n' "$*"; }
fail() { say "FAIL $*"; BAD=$((BAD + 1)); }
ok() { say "OK   $*"; }

# The shellcheck command lines of ci.yml: "shellcheck -s sh FILES" and "shellcheck -s bash FILES".
sc_lines() {
    grep -E '^[[:space:]]+shellcheck -s (sh|bash) ' "$CI" | sed 's/^[[:space:]]*//'
}

if [ "$PRINT" = 1 ]; then
    sc_lines
    exit 0
fi

# find_shellcheck: sets SC to a shellcheck 0.9, fetching it when needed; empty when there is none.
find_shellcheck() {
    SC=
    for fs_c in "${SWARMBOX_SHELLCHECK:-}" "$(command -v shellcheck 2> /dev/null)" "${XDG_CACHE_HOME:-$HOME/.cache}/swarmbox-dev/shellcheck/bin/shellcheck"; do
        if [ -z "$fs_c" ] || [ ! -x "$fs_c" ]; then continue; fi
        if "$fs_c" --version 2> /dev/null | grep -q "^version: $SC_VERSION"; then SC=$fs_c; return 0; fi
        [ -z "${SWARMBOX_SHELLCHECK:-}" ] || { SC=$fs_c; return 0; }   # a binary you named is used as it is
    done
    fs_dir=${XDG_CACHE_HOME:-$HOME/.cache}/swarmbox-dev/shellcheck
    say "     fetching shellcheck $SC_VERSION into $fs_dir (pip) ..."
    if command -v python3 > /dev/null 2>&1 && python3 -m pip install -q --target "$fs_dir" "shellcheck-py==$SC_PIP" > /dev/null 2>&1 \
        && "$fs_dir/bin/shellcheck" --version 2> /dev/null | grep -q "^version: $SC_VERSION"; then
        SC=$fs_dir/bin/shellcheck
    fi
}

if [ "$DO_SC" = 1 ]; then
    find_shellcheck
    if [ -z "$SC" ]; then
        fail "shellcheck: no shellcheck $SC_VERSION and pip could not fetch one (install it, or set SWARMBOX_SHELLCHECK, or use --no-shellcheck)"
    else
        lines=$(sc_lines)
        if [ -z "$lines" ]; then
            fail "shellcheck: no 'shellcheck -s sh|bash FILES' line found in $CI"
        else
            sc_bad=0
            sc_n=0
            while IFS= read -r line; do
                sc_n=$((sc_n + 1))
                # shellcheck disable=SC2086  # the line is words: the shell option and the file names
                set -- $line
                shift   # the word `shellcheck`
                out=$("$SC" "$@" 2>&1) || { sc_bad=1; printf '%s\n' "$out" | head -n 30; }
            done <<EOF
$lines
EOF
            if [ "$sc_bad" = 0 ]; then ok "shellcheck $SC_VERSION: the $sc_n command lines of ci.yml are clean"; else fail "shellcheck: findings above"; fi
        fi
    fi
fi

if [ "$DO_TESTS" = 1 ]; then
    out=$(mktemp "${TMPDIR:-/tmp}/swarmbox-check.XXXXXX") || exit 1
    trap 'rm -f "$out"' EXIT HUP INT TERM
    say "     running tests/run_all.sh in a clean environment (about a minute) ..."
    if env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 TMPDIR="${TMPDIR:-/tmp}" sh tests/run_all.sh > "$out" 2>&1; then
        total=$(grep '^TOTAL ' "$out" | tail -n 1)
        skipped=$(sed -n 's/.* \([0-9][0-9]*\) skipped.*/\1/p' "$out" | awk '{s += $1} END {print s + 0}')
        ok "tests: $total"
        [ "$skipped" = 0 ] || say "     note: $skipped test(s) were skipped here; CI installs tmux, dash and busybox and runs them"
    else
        grep -E ' FAIL |^TOTAL ' "$out" | head -n 20
        fail "tests: see the files above (run: env -i PATH=\"\$PATH\" HOME=\"\$HOME\" LANG=C.UTF-8 sh tests/run_all.sh --only FILE)"
    fi
fi

if [ "$DO_RELEASE" = 1 ]; then
    if r=$(sh dev/release-check.sh 2>&1); then
        ok "release-check: $(printf '%s\n' "$r" | tail -n 1)"
    else
        printf '%s\n' "$r" | grep -v '^OK'
        fail "release-check"
    fi
fi

if [ "$BAD" = 0 ]; then
    say "CHECK OK"
    exit 0
fi
say "CHECK FAILED ($BAD)"
exit 1
