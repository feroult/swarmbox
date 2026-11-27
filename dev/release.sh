#!/bin/sh
# release.sh: one command from "changelog.d/ says what changed" to "the release is public and checked".
#
# Usage: sh dev/release.sh [patch|minor|major|X.Y.Z] [--dry-run] [--bump-only] [--no-wait]
#   (nothing)    the next patch version after the newest vX.Y.Z tag
#   --dry-run    check everything that can be checked, say what would happen, change nothing
#   --bump-only  stop after the files are bumped (no gate, commit, push or tag)
#   --no-wait    stop after the tag is pushed, without waiting for the release
#
# Changelog entries are written BEFORE this runs, by whoever made the changes (an agent or a person), as fragment files
# under changelog.d/*.md (one file per change, avoiding merge conflicts across branches/worktrees; changelog.d/README.md
# is ignored). This script does not write prose: it refuses to go on when there are no fragments or an item is a
# placeholder or too thin, and its error says what to do, with the commits since the last release and the last entry as
# a model, so the author can write a fragment and run the command again.
#
# Steps: preconditions (on main, in step with origin, only changelog.d/ may be uncommitted) -> version -> CHANGELOG gate
# -> bump (merge changelog.d/*.md into CHANGELOG.md and remove them, bump container/host/VERSION and SCRIPT_VERSION)
# -> dev/check.sh -> commit -> dev/release-check.sh -> push main -> wait for the CI of that commit -> tag -> push the
# tag -> wait for the release -> verify it (checksum, version, image manifests).
# A failure after the bump puts all files back (your fragments included) and leaves no commit; a failed CI leaves no tag.
#
# Environment: GH_TOKEN or GITHUB_TOKEN (optional, avoids the anonymous rate limit of the API while it waits).
# Test-only: SWARMBOX_RELEASE_API, _DL, _SLUG, _POLL, _CHECK_CMD, _RCHECK_CMD, _NO_IMAGE_CHECK.
# Exit: 0 released (or dry run ok), 1 something failed, 2 the CHANGELOG is not ready.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
CHANGELOG=CHANGELOG.md
FRAG_DIR=changelog.d
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
# Only changelog.d/ may have uncommitted changes: fragments may already be committed by feature branches or written just before release.
other=$(git status --porcelain | sed 's/^...//' | grep -v '^changelog\.d/' || true)
[ -z "$other" ] || die "these paths have changes that are not in $FRAG_DIR/ (commit or stash them first):
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
            *) die "the version must look like 0.1.1 (or be patch, minor or major), not '$WANT'" ;;
        esac
        case $WANT in *[!0-9.]*) die "the version must look like 0.1.1, not '$WANT'" ;; esac
        new=$WANT
        if [ "$new" = "$last" ] || [ "$(printf '%s\n%s\n' "$last" "$new" | sort -V | tail -n 1)" != "$new" ]; then
            die "$new is not newer than the last release ($last)"
        fi
        ;;
esac
say "release: $last -> $new (from the tag $last_tag)"

# ---------------------------------------------------------------- the CHANGELOG gate
list_fragments() {
    [ -d "$FRAG_DIR" ] || return 0
    for f in "$FRAG_DIR"/*.md; do
        [ -f "$f" ] || continue
        case $(basename "$f") in
            README.md) continue ;;
        esac
        printf '%s\n' "$f"
    done | LC_ALL=C sort
}

collect_fragments() {
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        awk '
            /^[[:space:]]*$/ { blank = blank "\n"; next }
            { if (seen && blank != "") printf "%s", blank; blank = ""; print; seen = 1 }
        ' "$f"
    done
}

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
        printf '\n  3. Create a fragment file under %s/ (for example %s/%s-short-slug.md) with one "- " item per change\n' "$FRAG_DIR" "$FRAG_DIR" "$(date +%Y%m%d)"
        printf '     that matters to a USER of SwarmBox (what changed and, when it is not obvious, why). Say only what the commits\n'
        printf '     show: no "verified" or "tested on" claims that are not in them. Changes only to dev/, tests or CI go in one\n'
        printf '     short line, or are left out. Do not touch %s, version numbers or dates: this script sets them.\n' "$CHANGELOG"
        printf '  4. Run it again:  sh dev/release.sh %s\n' "${WANT:-}"
    } >&2
    exit 2
}

[ -f "$CHANGELOG" ] || changelog_not_ready "$CHANGELOG does not exist"
grep -q "^## \[$new\]" "$CHANGELOG" && changelog_not_ready "there is already an entry for $new: it must not exist before the release"
frags=$(list_fragments)
[ -n "$frags" ] || changelog_not_ready "no changelog fragments in $FRAG_DIR/"
frag_count=$(printf '%s\n' "$frags" | wc -l | tr -d ' ')
body=$(printf '%s\n' "$frags" | collect_fragments)
bullets=$(printf '%s\n' "$body" | grep -c '^- ' || true)
[ "$bullets" -ge 1 ] || changelog_not_ready "the fragments in $FRAG_DIR/ have no \"- \" items"
placeholder=$(printf '%s\n' "$body" | grep -i -n -E 'TODO|TBD|FIXME|XXX|lorem ipsum|<describe|\.\.\.$' | head -n 3 || true)
[ -z "$placeholder" ] || changelog_not_ready "an item looks like a placeholder:
$placeholder"
thin=$(printf '%s\n' "$body" | grep '^- ' | awk 'length($0) < 25 {print "         " $0}' | head -n 3)
[ -z "$thin" ] || changelog_not_ready "an item is too short to say anything (under 25 characters):
$thin"
say "changelog: $bullets item(s) from $frag_count fragment(s) in $FRAG_DIR/"

if [ "$DRY" = 1 ]; then
    say "dry run: would merge $frag_count fragment(s) from $FRAG_DIR/ into $CHANGELOG, bump $VERSION_FILE and SCRIPT_VERSION to $new,"
    say "          run '$CHECK_CMD', commit 'release: $new', run '$RCHECK_CMD', push main, wait for its CI, tag v$new,"
    say "          push the tag, wait for the release and verify it. Nothing was changed."
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
BACKUP=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-release.XXXXXX") || exit 1
mkdir -p "$BACKUP/frags"
cp "$CHANGELOG" "$BACKUP/CHANGELOG.md"
printf '%s\n' "$body" > "$BACKUP/body.md"
printf '%s\n' "$frags" | while IFS= read -r f; do
    [ -n "$f" ] || continue
    cp "$f" "$BACKUP/frags/$(basename "$f")"
done
trap '[ -z "$BACKUP" ] || rm -rf "$BACKUP"' EXIT

# restore: put CHANGELOG.md, fragments, SCRIPT and VERSION_FILE back as they were before the bump.
restore() {
    cp "$BACKUP/CHANGELOG.md" "$CHANGELOG"
    for bf in "$BACKUP/frags"/*.md; do
        [ -f "$bf" ] || continue
        cp "$bf" "$FRAG_DIR/$(basename "$bf")"
    done
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
    if ! awk -v v="$new" -v d="$bf_date" -v link="$bf_link" -v bodyfile="$BACKUP/body.md" '
        function emit_section(    line) {
            print "## [" v "] - " d
            print ""
            while ((getline line < bodyfile) > 0) print line
            close(bodyfile)
            print ""
        }
        /^## \[[0-9]/ && !h { emit_section(); h = 1 }
        /^\[[0-9]/ && !l && link != "" { print link; l = 1 }
        { print }
        END { if (!h) { print ""; emit_section() } }' "$CHANGELOG" > "$BACKUP/CHANGELOG.new"; then
        die "cannot rewrite $CHANGELOG"
    fi
    mv -f "$BACKUP/CHANGELOG.new" "$CHANGELOG"
    printf '%s\n' "$frags" | while IFS= read -r f; do
        [ -n "$f" ] || continue
        rm -f "$f"
    done
    printf '%s\n' "$new" > "$VERSION_FILE"
    if ! sed "s/^SCRIPT_VERSION=.*/SCRIPT_VERSION=$new/" "$SCRIPT" > "$BACKUP/script.new"; then
        die "cannot rewrite $SCRIPT"
    fi
    cat "$BACKUP/script.new" > "$SCRIPT"   # written through the file, not renamed over it: its mode stays
    rm -f "$BACKUP/script.new"
}
bump_files
say "bumped: $CHANGELOG (merged $frag_count fragment(s)), $VERSION_FILE, SCRIPT_VERSION -> $new"
if [ "$BUMP_ONLY" = 1 ]; then
    rm -rf "$BACKUP"
    BACKUP=
    exit 0
fi

# ---------------------------------------------------------------- the gate, the commit, the release check
say "running the gate: $CHECK_CMD"
# shellcheck disable=SC2086  # the command and its option are words
if ! $CHECK_CMD; then
    restore
    die "the gate failed; the files are back as they were (your fragments in $FRAG_DIR/ are kept). Fix it and run again."
fi
git add -A "$CHANGELOG" "$VERSION_FILE" "$SCRIPT" "$FRAG_DIR"
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
rm -rf "$BACKUP_KEEP"
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
