#!/bin/sh
# release-check.sh: the check the owner runs before creating the tag v2.0.0.
# READ-ONLY: it reads files and runs `git status`, `git rev-parse`, `git tag --list` (with GIT_OPTIONAL_LOCKS=0, so the index
# is not even refreshed). It creates, changes, pushes and tags nothing, and uses no network.
#
# Usage: sh dev/release-check.sh
# Env:   SWARMBOX_RELEASE_REPO    the repository to check (default: the one this script is in)
#        SWARMBOX_RELEASE_BRANCH  the branch the release is made from (default: main)
#        SWARMBOX_RELEASE_TAG     the tag to be created, for a prerelease such as v2.0.0-beta.1 (default: v<version>)
#        SWARMBOX_YAML_PYTHON     a python3 that can import yaml, when the default python3 cannot (optional)
# Output: one line per condition, "OK|FAIL|WARN <name> <text>", then "RELEASE CHECK OK" or "RELEASE CHECK FAILED <n>".
# Exit:   0 every condition holds (warnings do not count), 1 at least one FAIL.
# Conditions: tree (clean, nothing untracked), branch, version (the version design.md names equals the newest CHANGELOG
# entry), changelog (an entry for that version), notices (no [unverified] left in THIRD_PARTY_NOTICES.md), security-review
# (no row with status open), files (every release file exists), workflows (the YAML files parse), tag (v<version> does not
# exist yet), owner-todo (no [OWNER-TODO: ...] placeholder left in a release file). WARN org-placeholder: the README still
# has <org> (an owner decision; it does not fail the check).
set -u
REPO=${SWARMBOX_RELEASE_REPO:-$(cd "$(dirname "$0")/.." && pwd)}
BRANCH_WANTED=${SWARMBOX_RELEASE_BRANCH:-main}
BAD=0
GIT_OPTIONAL_LOCKS=0
export GIT_OPTIONAL_LOCKS

ok() { echo "OK $1 $2"; }
warn() { echo "WARN $1 $2"; }
fail() { echo "FAIL $1 $2"; BAD=$((BAD + 1)); }
G() { git -C "$REPO" "$@"; }

if [ ! -d "$REPO" ] || ! G rev-parse --git-dir >/dev/null 2>&1; then
    fail repo "$REPO is not a git repository"
    echo "RELEASE CHECK FAILED $BAD"
    exit 1
fi

# tree
st=$(G status --porcelain 2>&1)
if [ -z "$st" ]; then ok tree "clean"; else fail tree "$(printf '%s\n' "$st" | wc -l | tr -d ' ') path(s) changed or untracked; commit or remove them"; fi

# branch
br=$(G rev-parse --abbrev-ref HEAD 2>&1)
if [ "$br" = "$BRANCH_WANTED" ]; then ok branch "$br"; else fail branch "on '$br', the release is made from '$BRANCH_WANTED'"; fi

# version and changelog
dver=""
if [ -f "$REPO/docs/design.md" ]; then
    # shellcheck disable=SC2016  # the backticks are literal text to match
    dver=$(sed -n 's/.*The first public version is `\([0-9][0-9.]*\)`.*/\1/p' "$REPO/docs/design.md" | head -n 1)
fi
cver=""
if [ -f "$REPO/CHANGELOG.md" ]; then
    cver=$(sed -n 's/^## \[\([0-9][0-9.]*\)\].*/\1/p' "$REPO/CHANGELOG.md" | head -n 1)
fi
if [ -z "$dver" ]; then
    fail version "docs/design.md does not name 'The first public version is \`X.Y.Z\`'"
elif [ -z "$cver" ]; then
    fail version "CHANGELOG.md has no '## [X.Y.Z]' entry"
elif [ "$dver" = "$cver" ]; then
    ok version "$dver (design and the newest CHANGELOG entry agree)"
elif [ "$(printf '%s\n%s\n' "$dver" "$cver" | sort -V | tail -n 1)" = "$cver" ]; then
    ok version "$cver (a later release than the first public version $dver named by docs/design.md)"
else
    fail version "docs/design.md says $dver, the newest CHANGELOG.md entry is $cver"
fi
if [ -n "$dver" ] && grep -q "^## \[$dver\]" "$REPO/CHANGELOG.md" 2>/dev/null; then
    ok changelog "an entry for $dver exists"
else
    fail changelog "no '## [${dver:-?}]' entry in CHANGELOG.md"
fi

# notices
if [ ! -f "$REPO/THIRD_PARTY_NOTICES.md" ]; then
    fail notices "THIRD_PARTY_NOTICES.md is missing"
else
    n=$(grep -c '\[unverified' "$REPO/THIRD_PARTY_NOTICES.md" || true)
    if [ "$n" = 0 ]; then ok notices "no [unverified] left"; else fail notices "$n line(s) with [unverified] in THIRD_PARTY_NOTICES.md"; fi
fi

# security review: a table row "| SR-nn | ... | <status> | <test> |" whose status is open
if [ ! -f "$REPO/docs/security-review.md" ]; then
    fail security-review "docs/security-review.md is missing"
else
    rows=$(grep -c '^| SR-[0-9]' "$REPO/docs/security-review.md" || true)
    open=$(awk -F'|' '/^\| SR-[0-9]/ { s = $(NF - 2); gsub(/^ +| +$/, "", s); id = $2; gsub(/^ +| +$/, "", id); if (tolower(s) == "open") printf "%s ", id }' "$REPO/docs/security-review.md")
    if [ "$rows" = 0 ]; then
        fail security-review "no finding rows (| SR-nn |) in docs/security-review.md"
    elif [ -n "$open" ]; then
        fail security-review "open finding(s): $open"
    else
        ok security-review "$rows findings, none open"
    fi
fi

# files
missing=""
for f in README.md LICENSE SECURITY.md CODE_OF_CONDUCT.md CHANGELOG.md CONTRIBUTING.md THIRD_PARTY_NOTICES.md \
         docs/design.md docs/security-review.md docs/release-checklist.md \
         .github/workflows/ci.yml .github/workflows/release.yml .github/dependabot.yml .grype.yaml; do
    [ -f "$REPO/$f" ] || missing="$missing $f"
done
if [ -z "$missing" ]; then ok files "all release files exist"; else fail files "missing:$missing"; fi

# workflows parse
YPY=""
for py in python3 "${SWARMBOX_YAML_PYTHON:-}"; do
    [ -n "$py" ] || continue
    if "$py" -c 'import yaml' >/dev/null 2>&1; then YPY=$py; break; fi
done
bad=""
for f in .github/workflows/ci.yml .github/workflows/release.yml .github/dependabot.yml; do
    [ -f "$REPO/$f" ] || continue
    if [ -n "$YPY" ]; then
        "$YPY" -c 'import sys, yaml
d = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if isinstance(d, dict) and d else 1)' "$REPO/$f" >/dev/null 2>&1 || bad="$bad $f"
    else
        # reduced check: no tabs for indentation, flow brackets and braces balanced, not empty
        if grep -q "$(printf '^\t')" "$REPO/$f"; then bad="$bad $f"; continue; fi
        o=$(tr -cd '[' < "$REPO/$f" | wc -c); c=$(tr -cd ']' < "$REPO/$f" | wc -c)
        ob=$(tr -cd '{' < "$REPO/$f" | wc -c); cb=$(tr -cd '}' < "$REPO/$f" | wc -c)
        [ "$o" = "$c" ] && [ "$ob" = "$cb" ] && [ -s "$REPO/$f" ] || bad="$bad $f"
    fi
done
if [ -n "$bad" ]; then
    fail workflows "do not parse:$bad"
elif [ -n "$YPY" ]; then
    ok workflows "ci.yml, release.yml and dependabot.yml parse (PyYAML)"
else
    ok workflows "reduced: no PyYAML here, only tabs, brackets and braces were checked (set SWARMBOX_YAML_PYTHON)"
fi

# tag
RTAG=${SWARMBOX_RELEASE_TAG:-v${cver:-$dver}}   # the newest CHANGELOG entry: 2.0.1 after 2.0.0
if [ -n "$dver" ]; then
    if [ -n "$(G tag --list "$RTAG")" ]; then fail tag "$RTAG already exists"; else ok tag "$RTAG does not exist yet"; fi
else
    fail tag "no version to look for"
fi

# owner placeholders
todo=""
for f in README.md SECURITY.md CODE_OF_CONDUCT.md CHANGELOG.md CONTRIBUTING.md LICENSE THIRD_PARTY_NOTICES.md; do
    [ -f "$REPO/$f" ] && grep -q '\[OWNER-TODO:' "$REPO/$f" && todo="$todo $f"
done
if [ -z "$todo" ]; then ok owner-todo "no [OWNER-TODO: ...] placeholder left"; else fail owner-todo "still in:$todo (docs/release-checklist.md says what to put there)"; fi
if [ -f "$REPO/README.md" ] && grep -q '<org>' "$REPO/README.md"; then
    warn org-placeholder "README.md still has <org> (name and registry owner are an owner decision, docs/release-checklist.md)"
fi

if [ "$BAD" = 0 ]; then echo "RELEASE CHECK OK"; exit 0; fi
echo "RELEASE CHECK FAILED $BAD"
exit 1
