#!/bin/sh
# final-audit.sh: the end-of-phase audit of the repository (slice 6.7). Read-only.
#
# Usage: sh dev/final-audit.sh
# Checks, one line each ("OK|FAIL|SKIP <name> ..."), then "AUDIT OK" or "AUDIT FAILED <n>":
#   tree     no uncommitted or untracked file
#   retired  none of the files retired in slice 6.3 is tracked (they stay in the tag v0.1.0)
#   branch   the current branch is opensource
#   tags     the only tag is v0.1.0 (no tag was created)
#   podman   no swarmbox-test- container, volume or image is left (skipped when podman is not installed)
# Env: SWARMBOX_AUDIT_REPO points at another repository (used by tests/test_final_audit.py).
# It lists only; it never removes, stops or changes anything.
set -u
REPO=${SWARMBOX_AUDIT_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
BAD=0
fail() { echo "FAIL $1 $2"; BAD=$((BAD + 1)); }
ok() { echo "OK $1 $2"; }

G() { git -C "$REPO" "$@"; }

st=$(G status --porcelain 2>&1)
if [ -z "$st" ]; then ok tree "clean"; else fail tree "$(printf '%s\n' "$st" | wc -l | tr -d ' ') path(s) changed or untracked"; fi

gone=""
for p in start.sh build.sh Dockerfile.v0.1.0 lib container/scripts/init.sh container/opencode container/web/web-terminal.sh; do
    if [ -n "$(G ls-files -- "$p")" ]; then gone="$gone $p"; fi
done
if [ -z "$gone" ]; then ok retired "none tracked"; else fail retired "tracked:$gone"; fi

br=$(G rev-parse --abbrev-ref HEAD 2>&1)
if [ "$br" = "opensource" ]; then ok branch "$br"; else fail branch "on $br, expected opensource"; fi

tags=$(G tag --list | tr '\n' ' ' | sed 's/ $//')
if [ "$tags" = "v0.1.0" ]; then ok tags "v0.1.0 only"; else fail tags "found: $tags"; fi

if command -v podman >/dev/null 2>&1; then
    left=""
    for what in "ps -a --format {{.Names}}" "volume ls --format {{.Name}}" "images --format {{.Repository}}"; do
        # shellcheck disable=SC2086
        out=$(podman $what 2>/dev/null | grep 'swarmbox-test-' || true)
        [ -n "$out" ] && left="$left $(printf '%s' "$out" | tr '\n' ' ')"
    done
    if [ -z "$left" ]; then ok podman "no swarmbox-test- leftovers"; else fail podman "left:$left"; fi
else
    echo "SKIP podman not installed"
fi

if [ "$BAD" = 0 ]; then echo "AUDIT OK"; exit 0; fi
echo "AUDIT FAILED $BAD"
exit 1
