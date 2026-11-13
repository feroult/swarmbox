#!/bin/sh
# local-up.sh: build the image from this checkout and switch your box to it, in one command, so a change can be tried
# without a release. Run it on the HOST (your own machine), from anywhere: it finds the checkout by its own path.
#
# Usage: sh dev/local-up.sh [--yes] [--no-reset] [--no-cache] [--with TOOLS] [--dry-run]
#        sh dev/local-up.sh --release [--yes] [--no-reset] [--dry-run]
#   (nothing)    build localhost/swarmbox:local from this checkout, install the `swarmbox` script that image carries, record the
#                image in your config, and reset the box so it runs on it
#   --yes        reset without asking (without it, the reset is asked for on a terminal, and only printed otherwise)
#   --no-reset   stop before the reset: build, install and record only; run `swarmbox reset` yourself when you are ready
#   --no-cache   build from scratch (podman build --no-cache)
#   --with TOOLS tools to record in a config that does not exist yet (an existing config keeps its own)
#   --dry-run    print the commands, run none
#   --release    the way back: pull the published image of this series (the repository of container/host/DEFAULTS, the tag
#                X.Y of container/host/VERSION), install its `swarmbox` script, record that image again, and reset
#
# Why it does more than `podman build`: `swarmbox setup` never overwrites an IMAGE that is already in the config, and `swarmbox update`
# does not replace a script of the same version, so the script of the image and the IMAGE are set here, explicitly. A reset ends
# the running sessions of the box.
# Environment: SWARMBOX_BIN_DIR (where the script lives, default ~/.local/bin), SWARMBOX_LOCAL_TAG (default localhost/swarmbox:local).
# Test-only: SWARMBOX_TEST_CONTAINERENV replaces /run/.containerenv.
# Exit: 0 ok, 1 a step failed, 2 usage or not on a host, 3 Podman is missing.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=${SWARMBOX_LOCAL_TAG:-localhost/swarmbox:local}
BIN_DIR=${SWARMBOX_BIN_DIR:-$HOME/.local/bin}
BIN=$BIN_DIR/swarmbox
CONTAINERENV=${SWARMBOX_TEST_CONTAINERENV:-/run/.containerenv}

YES=0
NO_RESET=0
NO_CACHE=
WITH=
DRY=0
RELEASE=0
while [ $# -gt 0 ]; do
    case $1 in
        --yes|-y) YES=1 ;;
        --no-reset) NO_RESET=1 ;;
        --no-cache) NO_CACHE=--no-cache ;;
        --with) [ $# -ge 2 ] || { echo "local-up: --with needs a value" >&2; exit 2; }; WITH=$2; shift ;;
        --dry-run) DRY=1 ;;
        --release) RELEASE=1 ;;
        -h|--help) awk 'NR == 1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; exit 0 ;;
        *) echo "local-up: unknown option $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die() { _rc=$1; shift; printf 'local-up: %s\n' "$*" >&2; exit "$_rc"; }

# run CMD...: print it when dry, else run it
run() {
    if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; return 0; fi
    "$@"
}

if [ -e "$CONTAINERENV" ]; then
    die 2 "this is inside a box (nested Podman): the image would land in the box's own storage, not on your machine. Run it on the host. (Inside a box, dev/dev-build.sh builds a test image.)"
fi
command -v podman > /dev/null 2>&1 || die 3 "podman is not installed (or not on the PATH)."

TMP=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-local-up.XXXXXX") || exit 1
trap 'rm -rf "${TMP:?}"' EXIT

# install_from REF: the installer that image prints, run by sh: it writes the swarmbox script of the image to $BIN_DIR
install_from() {
    if [ "$DRY" = 1 ]; then
        printf '+ podman run --rm %s install --image %s%s | SWARMBOX_BIN_DIR=%s sh\n' "$1" "$1" "${WITH:+ --with $WITH}" "$BIN_DIR"
        return 0
    fi
    if [ -n "$WITH" ]; then
        podman run --rm "$1" install --image "$1" --with "$WITH" > "$TMP/install.sh" || die 1 "cannot get the installer from $1."
    else
        podman run --rm "$1" install --image "$1" > "$TMP/install.sh" || die 1 "cannot get the installer from $1."
    fi
    SWARMBOX_BIN_DIR=$BIN_DIR sh "$TMP/install.sh" || die 1 "the installer of $1 failed."
}

# record_image REF: IMAGE in the config, which setup would leave alone when it already has a value
record_image() {
    if [ "$DRY" = 1 ]; then printf '+ %s config set IMAGE %s\n' "$BIN" "$1"; return 0; fi
    [ -x "$BIN" ] || die 1 "$BIN was not written; look at the installer's messages above."
    "$BIN" config set IMAGE "$1" || die 1 "cannot record IMAGE=$1."
}

# finish: the reset, which is what makes the box use the image
finish() {
    if [ "$NO_RESET" = 1 ]; then
        say "Recorded. Run \`swarmbox reset\` when you want the box to use it (running sessions end)."
        return 0
    fi
    if [ "$YES" = 0 ]; then
        if [ "$DRY" = 1 ]; then
            say "+ (asks before: swarmbox reset)"
            return 0
        fi
        if [ -t 0 ] && [ -t 1 ]; then
            printf 'Reset the box now? The sessions that are open end. [y/N] '
            read -r ans || ans=
            case $ans in y|Y|yes|YES) ;; *) say "Not reset. Run \`swarmbox reset\` when you want the box to use it."; return 0 ;; esac
        else
            say "Recorded. No terminal to ask on: run \`swarmbox reset\` (or this again with --yes)."
            return 0
        fi
    fi
    step "resetting the box"
    run "$BIN" reset
}

if [ "$RELEASE" = 1 ]; then
    repo=$(sed -n "s/^SWARMBOX_DEFAULT_IMAGE_REPO=['\"]*\([^'\"]*\)['\"]*$/\1/p" "$ROOT/container/host/DEFAULTS")
    [ -n "$repo" ] || die 1 "cannot read the image repository from container/host/DEFAULTS."
    read -r version < "$ROOT/container/host/VERSION" || die 1 "cannot read container/host/VERSION."
    REF=$repo:${version%.*}
    step "going back to the published image $REF"
    run podman pull "$REF"
    install_from "$REF"
    record_image "$REF"
    finish
    say "Done: the box is on $REF."
    exit 0
fi

step "building $TAG from $ROOT (minutes the first time; the layers are cached after)"
if [ -n "$NO_CACHE" ]; then run podman build --no-cache -t "$TAG" "$ROOT"; else run podman build -t "$TAG" "$ROOT"; fi
step "installing the swarmbox script of that image in $BIN_DIR"
install_from "$TAG"
step "recording the image in the config"
record_image "$TAG"
finish
say "Done: the box is on $TAG. Back to the published one: sh dev/local-up.sh --release"
