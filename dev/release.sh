#!/bin/sh
# release.sh: one command from "CHANGELOG.md says what changed" to "the release is public and checked".
#
# Usage: sh dev/release.sh [patch|minor|major|X.Y.Z] [--dry-run] [--bump-only] [--no-wait]
#   (nothing)    the next patch version after the newest vX.Y.Z tag
#   --dry-run    check everything that can be checked, say what would happen, change nothing
#   --bump-only  stop after the files are bumped (no gate, commit, push or tag)
#   --no-wait    stop after the tag is pushed, without waiting for the release
#
# The CHANGELOG is written BEFORE this runs, by whoever made the changes (an agent or a person), under "## [Unreleased]". This script does
# not write prose: it refuses to go on when that section is empty, a placeholder or too thin, and its error says what to do, with the commits
# since the last release and the last entry as a model, so the author can write it and run the command again.
#
# Steps: preconditions (on main, in step with origin, only CHANGELOG.md may be modified) -> version -> CHANGELOG gate -> bump
# (CHANGELOG.md, container/host/VERSION, SCRIPT_VERSION) -> dev/check.sh -> commit -> dev/release-check.sh -> push main -> wait for the CI of
# that commit -> tag -> push the tag -> wait for the release -> verify it (checksum, version, image manifests).
# A failure after the bump puts the three files back (your CHANGELOG text included) and leaves no commit; a failed CI leaves no tag.
#
# Environment: GH_TOKEN or GITHUB_TOKEN (optional, avoids the anonymous rate limit of the API while it waits).
# Test-only: SWARMBOX_RELEASE_API, _DL, _SLUG, _POLL, _CHECK_CMD, _RCHECK_CMD, _NO_IMAGE_CHECK.
# Exit: 0 released (or dry run ok), 1 something failed, 2 the CHANGELOG is not ready.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
CHANGELOG=CHANGELOG.md
SCRIPT=container/host/swarmbox-host
VERSION_FILE=container/host/VERSION
API=${SWARMBOX_RELEASE_API:-https://api.github.com}
DL=${SWARMBOX_RELEASE_DL:-https://github.com}
POLL=${SWARMBOX_RELEASE_POLL:-60}
CHECK_CMD=${SWARMBOX_RELEASE_CHECK_CMD:-sh dev/check.sh}
RCHECK_CMD=${SWARMBOX_RELEASE_RCHECK_CMD:-sh dev/release-check.sh}

DRY=0
BUMP_ONLY=0
NO_WAIT=0
WANT=
for a in "$@"; do
    case $a in
        --dry-run) DRY=1 ;;
        --bump-only) BUMP_ONLY=1 ;;
        --no-wait) NO_WAIT=1 ;;
        -*) echo "release.sh: unknown option $a" >&2; exit 1 ;;
        *) WANT=$a ;;
    esac
done

say() { printf '%s\n' "$*"; }
die() { printf 'release.sh: %s\n' "$*" >&2; exit 1; }
BACKUP=

# ---------------------------------------------------------------- preconditions
git rev-parse --is-inside-work-tree > /dev/null 2>&1 || die "not inside a git repository"
branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = main ] || die "a release is made from main; you are on '$branch'"
# Only CHANGELOG.md may be modified: the items under [Unreleased] are written, uncommitted, before this runs, and go in the release commit.
other=$(git status --porcelain | sed 's/^...//' | grep -v '^CHANGELOG.md$' || true)
[ -z "$other" ] || die "these paths have changes that are not the CHANGELOG (commit or stash them first):
$other"
git fetch -q origin main 2> /dev/null || die "cannot reach origin (git fetch origin main failed)"
git merge-base --is-ancestor origin/main HEAD 2> /dev/null || die "main is behind or has diverged from origin/main: pull first"

# ---------------------------------------------------------------- the version
last_tag=$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | grep -v -e '-' | head -n 1)
[ -n "$last_tag" ] || die "no vX.Y.Z tag yet: the first release is made by hand"
last=${last_tag#v}
case $WANT in
    ''|patch|minor|major)
        IFS=. read -r _a _b _c <<EOF
$last
EOF
        case ${WANT:-patch} in
            major) new=$((_a + 1)).0.0 ;;
            minor) new=$_a.$((_b + 1)).0 ;;
            *) new=$_a.$_b.$((_c + 1)) ;;
        esac
        ;;
    *)
        case $WANT in
            [0-9]*.[0-9]*.[0-9]*) ;;
            *) die "the version must look like 2.0.7 (or be patch, minor or major), not '$WANT'" ;;
        esac
        case $WANT in *[!0-9.]*) die "the version must look like 2.0.7, not '$WANT'" ;; esac
        new=$WANT
        if [ "$new" = "$last" ] || [ "$(printf '%s\n%s\n' "$last" "$new" | sort -V | tail -n 1)" != "$new" ]; then
            die "$new is not newer than the last release ($last)"
        fi
        ;;
esac
say "release: $last -> $new (from the tag $last_tag)"

# ---------------------------------------------------------------- the CHANGELOG gate
unreleased_body() { awk '/^## \[Unreleased\]/ {f = 1; next} /^## \[/ {f = 0} f' "$CHANGELOG"; }

# A model for the author: the newest dated entry.
last_entry() { awk '/^## \[[0-9]/ {n++; if (n == 2) exit} n == 1' "$CHANGELOG" | head -n 40; }

changelog_not_ready() {
    {
        printf 'release.sh: %s is not ready for %s\n' "$CHANGELOG" "$new"
        printf '  problem: %s\n\n' "$1"
        printf 'What to do (for the agent or the person who made the changes):\n'
        printf '  1. These are the commits since %s:\n' "$last_tag"
        git log --format='       %h %s' "$last_tag..HEAD" | head -n 60
        printf '\n  2. This is the last entry, as a model of the style:\n\n'
        last_entry | sed 's/^/       /'
        printf '\n  3. Under "## [Unreleased]" in %s write one "- " item per change that matters to a USER of SwarmBox\n' "$CHANGELOG"
        printf '     (what changed and, when it is not obvious, why). Say only what the commits show: no "verified" or "tested\n'
        printf '     on" claims that are not in them. Changes only to dev/, tests or CI go in one short line, or are left out.\n'
        printf '     Do not touch the version numbers or the dates: this script sets them.\n'
        printf '  4. Run it again:  sh dev/release.sh %s\n' "${WANT:-}"
    } >&2
    exit 2
}

grep -q '^## \[Unreleased\]' "$CHANGELOG" || changelog_not_ready 'there is no "## [Unreleased]" section'
grep -q "^## \[$new\]" "$CHANGELOG" && changelog_not_ready "there is already an entry for $new: it must not exist before the release"
body=$(unreleased_body)
bullets=$(printf '%s\n' "$body" | grep -c '^- ' || true)
[ "$bullets" -ge 1 ] || changelog_not_ready 'the "## [Unreleased]" section has no "- " items'
placeholder=$(printf '%s\n' "$body" | grep -i -n -E 'TODO|TBD|FIXME|XXX|lorem ipsum|<describe|\.\.\.$' | head -n 3 || true)
[ -z "$placeholder" ] || changelog_not_ready "an item looks like a placeholder:
$placeholder"
thin=$(printf '%s\n' "$body" | grep '^- ' | awk 'length($0) < 25 {print "         " $0}' | head -n 3)
[ -z "$thin" ] || changelog_not_ready "an item is too short to say anything (under 25 characters):
$thin"
say "changelog: $bullets item(s) under [Unreleased]"

if [ "$DRY" = 1 ]; then
    say "dry run: would bump $CHANGELOG, $VERSION_FILE and SCRIPT_VERSION to $new, run '$CHECK_CMD', commit 'release: $new', run '$RCHECK_CMD',"
    say "          push main, wait for its CI, tag v$new, push the tag, wait for the release and verify it. Nothing was changed."
    exit 0
fi

# The slug owner/repo of the GitHub repository, from origin: needed from the push on, so a repository this cannot read fails now.
slug=${SWARMBOX_RELEASE_SLUG:-}
if [ -z "$slug" ] && [ "$BUMP_ONLY" = 0 ]; then
    url=$(git remote get-url origin)
    case $url in
        *github.com[:/]*) slug=${url#*github.com[:/]}; slug=${slug%.git} ;;
        *) die "cannot tell the GitHub repository from origin ($url): set SWARMBOX_RELEASE_SLUG=owner/repo" ;;
    esac
fi

# ---------------------------------------------------------------- the bump
BACKUP=$(mktemp "${TMPDIR:-/tmp}/swarmbox-release.XXXXXX") || exit 1
cp "$CHANGELOG" "$BACKUP"
trap '[ -z "$BACKUP" ] || rm -f "$BACKUP" "$BACKUP.new"' EXIT

# restore: the three files as they were before the bump; the CHANGELOG comes from the copy, so the author's text is kept.
restore() {
    cp "$BACKUP" "$CHANGELOG"
    git checkout -q -- "$SCRIPT" "$VERSION_FILE" 2> /dev/null || true
}

bump_files() {
    bf_date=$(date +%Y-%m-%d)
    bf_tmpl=$(grep -m1 '^\[[0-9]' "$CHANGELOG" || true)
    bf_link=
    if [ -n "$bf_tmpl" ]; then
        bf_old=${bf_tmpl#\[}
        bf_old=${bf_old%%\]*}
        bf_link=$(printf '%s\n' "$bf_tmpl" | sed "s/$bf_old/$new/g")
    fi
    if ! awk -v v="$new" -v d="$bf_date" -v link="$bf_link" '
        /^## \[Unreleased\]/ && !h { print; print ""; print "## [" v "] - " d; h = 1; next }
        /^\[[0-9]/ && !l && link != "" { print link; l = 1 }
        { print }' "$CHANGELOG" > "$BACKUP.new"; then
        die "cannot rewrite $CHANGELOG"
    fi
    mv -f "$BACKUP.new" "$CHANGELOG"
    printf '%s\n' "$new" > "$VERSION_FILE"
    if ! sed "s/^SCRIPT_VERSION=.*/SCRIPT_VERSION=$new/" "$SCRIPT" > "$BACKUP.new"; then
        die "cannot rewrite $SCRIPT"
    fi
    cat "$BACKUP.new" > "$SCRIPT"   # written through the file, not renamed over it: its mode stays
    rm -f "$BACKUP.new"
}
bump_files
say "bumped: $CHANGELOG, $VERSION_FILE, SCRIPT_VERSION -> $new"
if [ "$BUMP_ONLY" = 1 ]; then
    BACKUP=
    exit 0
fi

# ---------------------------------------------------------------- the gate, the commit, the release check
say "running the gate: $CHECK_CMD"
# shellcheck disable=SC2086  # the command and its option are words
if ! $CHECK_CMD; then
    restore
    die "the gate failed; the three files are back as they were (your CHANGELOG text is kept). Fix it and run again."
fi
git add "$CHANGELOG" "$VERSION_FILE" "$SCRIPT"
git commit -q -m "release: $new" || { restore; die "git commit failed"; }
say "committed: release: $new ($(git rev-parse --short HEAD))"
# shellcheck disable=SC2086
if ! $RCHECK_CMD > /dev/null 2>&1; then
    git reset -q --mixed HEAD~1
    restore
    # shellcheck disable=SC2086
    $RCHECK_CMD 2>&1 | grep -v '^OK' >&2
    die "the release check failed; the commit was undone and the files restored. Fix what it says and run again."
fi
say "release check: ok"
BACKUP_KEEP=$BACKUP
BACKUP=
rm -f "$BACKUP_KEEP"
trap - EXIT

# ---------------------------------------------------------------- push, CI, tag
token=${GH_TOKEN:-${GITHUB_TOKEN:-}}

# api PATH: the body of a GET to the GitHub API, nothing and a failure when it cannot be read.
api() {
    if [ -n "$token" ]; then
        curl -fsS -m 30 -H "Authorization: Bearer $token" "$API/repos/$slug/$1" 2> /dev/null
    else
        curl -fsS -m 30 "$API/repos/$slug/$1" 2> /dev/null
    fi
}

sha=$(git rev-parse HEAD)
say "pushing main (the gate just ran, so the pre-push hook is skipped) ..."
SWARMBOX_SKIP_CHECK=1 git push -q origin main || die "git push origin main failed"

# wait_ci SHA: 0 when the CI (the workflow ci.yml, not the release workflow that the tag starts) of that commit passed, 1 when it failed or took too long.
wait_ci() {
    wc_tries=0
    while [ "$wc_tries" -lt 60 ]; do
        wc_tries=$((wc_tries + 1))
        wc_out=$(api "actions/workflows/ci.yml/runs?head_sha=$1&event=push&per_page=5" | tr -d ' \r\n') || wc_out=
        wc_run=$(printf '%s' "$wc_out" | sed 's/.*"workflow_runs":\[{//; s/},{"id".*//')
        wc_status=$(printf '%s' "$wc_run" | grep -o '"status":"[a-z_]*"' | head -n 1 | cut -d'"' -f4)
        wc_concl=$(printf '%s' "$wc_run" | grep -o '"conclusion":[^,]*' | head -n 1 | cut -d: -f2 | tr -d '"')
        case $wc_status in
            completed)
                if [ "$wc_concl" = success ]; then say "ci: passed"; return 0; fi
                wc_id=$(printf '%s' "$wc_run" | grep -o '"id":[0-9]*' | head -n 1 | cut -d: -f2)
                say "ci: $wc_concl. Jobs that did not pass:" >&2
                # one job per line; the conclusion and the name are those of the JOB (scalars before its "steps" list), not of its steps
                api "actions/runs/$wc_id/jobs" | tr -d '\r\n' | sed 's/{ *"id"/\
&/g' \
                    | sed -n 's/^{ *"id"[^{}]*"conclusion": *"\{0,1\}\([a-z_]*\)"\{0,1\},[^{}]*"name": *"\([^"]*\)".*/\1 \2/p' \
                    | grep -v -E '^(success|skipped) ' | sed 's/^/    /' >&2
                return 1
                ;;
            *) printf '  ci: %s (check %s)\n' "${wc_status:-no run yet}" "$wc_tries" ;;
        esac
        sleep "$POLL"
    done
    say "ci: still not finished after an hour; the tag was NOT created" >&2
    return 1
}
if ! wait_ci "$sha"; then
    die "the CI of $(git rev-parse --short "$sha") did not pass. main is pushed with the release commit but there is no tag: fix, commit, and tag by hand or run again."
fi

git tag -a "v$new" -m "SwarmBox $new" || die "git tag failed"
SWARMBOX_SKIP_CHECK=1 git push -q origin "v$new" || die "git push origin v$new failed"
say "tag v$new pushed: the release workflow is running"
if [ "$NO_WAIT" = 1 ]; then exit 0; fi

# ---------------------------------------------------------------- wait for the release and verify it
wt_tries=0
until curl -fsS -m 30 -L -o /dev/null "$DL/$slug/releases/download/v$new/swarmbox.sha256" 2> /dev/null; do
    wt_tries=$((wt_tries + 1))
    [ "$wt_tries" -lt 120 ] || die "the release files did not appear after two hours: look at the release workflow on GitHub"
    printf '  release: not published yet (check %s)\n' "$wt_tries"
    sleep "$POLL"
done
say "release: the files are published"

vd=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-verify.XXXXXX") || exit 1
trap 'rm -rf "$vd"' EXIT
curl -fsS -m 120 -L -o "$vd/swarmbox" "$DL/$slug/releases/download/v$new/swarmbox" || die "cannot download the published swarmbox"
curl -fsS -m 30 -L -o "$vd/sha" "$DL/$slug/releases/download/v$new/swarmbox.sha256" || die "cannot download swarmbox.sha256"
want=$(cut -d ' ' -f 1 < "$vd/sha")
if command -v sha256sum > /dev/null 2>&1; then got=$(sha256sum < "$vd/swarmbox" | cut -d ' ' -f 1); else got=$(shasum -a 256 < "$vd/swarmbox" | cut -d ' ' -f 1); fi
if [ -z "$want" ] || [ "$want" != "$got" ]; then die "the checksum of the published swarmbox does not match swarmbox.sha256"; fi
reported=$(sh "$vd/swarmbox" version 2> /dev/null | head -n 1)
[ "$reported" = "$new" ] || die "the published swarmbox says '$reported', not $new"
say "verified: the checksum matches and the published script says $new"

if [ -z "${SWARMBOX_RELEASE_NO_IMAGE_CHECK:-}" ] && command -v podman > /dev/null 2>&1; then
    repo=$(sed -n "s/^SWARMBOX_DEFAULT_IMAGE_REPO=['\"]*\([^'\"]*\)['\"]*$/\1/p" container/host/DEFAULTS)
    series=${new%.*}
    m_new=$(podman manifest inspect "$repo:$new" 2> /dev/null | sha256sum | cut -c1-16)
    m_ser=$(podman manifest inspect "$repo:$series" 2> /dev/null | sha256sum | cut -c1-16)
    m_lat=$(podman manifest inspect "$repo:latest" 2> /dev/null | sha256sum | cut -c1-16)
    archs=$(podman manifest inspect "$repo:$new" 2> /dev/null | grep -c '"architecture"')
    if [ "$m_new" = "$m_ser" ] && [ "$m_new" = "$m_lat" ] && [ "$archs" -ge 2 ]; then
        say "verified: $repo:$new, :$series and :latest are the same image, with $archs architectures"
    else
        die "the image tags do not agree ($new $m_new, $series $m_ser, latest $m_lat; $archs architectures): look at the release workflow"
    fi
else
    say "image: not checked (no podman here, or SWARMBOX_RELEASE_NO_IMAGE_CHECK is set)"
fi
say "RELEASED $new. To use it: swarmbox update && swarmbox reset"
exit 0
