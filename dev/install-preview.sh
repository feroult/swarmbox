#!/bin/sh
# install-preview.sh: build the local image and simulate a first-time `| sh` install in an isolated temporary HOME.
#
# Usage: sh dev/install-preview.sh [--no-build] [--install-sh] [--in-path] [--with ADDONS] [--rmi] [--verbose]
#   (default)      build via dev/dev-build.sh, then run `podman run --rm IMAGE install | sh` in a fresh mktemp HOME
#   --no-build     skip the build and reuse localhost/swarmbox-test-install-preview
#   --install-sh   simulate `sh install.sh` against a local file:// release built from container/host/swarmbox-host
#   --in-path      put the temporary bin dir on PATH (hides the `! PATH setup needed` block)
#   --with ADDONS  pass --with ADDONS to the installer (e.g. claude,sysop)
#   --rmi          remove the test image after the preview finishes
#   --verbose      stream the image build output instead of hiding it until failure
#
# Safety: never touches ~/.config/swarmbox, ~/.local/share/swarmbox, ~/.local/bin, or any live box.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=swarmbox-test-install-preview
DO_BUILD=1
MODE=podman
IN_PATH=0
WITH=
DO_RMI=0
VERBOSE=0

usage() {
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case $1 in
        --no-build) DO_BUILD=0; shift ;;
        --install-sh) MODE=install-sh; shift ;;
        --in-path) IN_PATH=1; shift ;;
        --with)
            [ $# -ge 2 ] || { echo "install-preview.sh: --with needs a value" >&2; exit 2; }
            WITH=$2
            shift 2
            ;;
        --with=*) WITH=${1#*=}; shift ;;
        --rmi) DO_RMI=1; shift ;;
        --verbose|-v) VERBOSE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "install-preview.sh: unknown option '$1'" >&2; usage >&2; exit 2 ;;
    esac
done

IMG="localhost/$TAG"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-install-preview.XXXXXX")
cleanup() {
    rm -rf "$TMP"
    if [ "$DO_RMI" = 1 ]; then
        podman rmi -f "$IMG" > /dev/null 2>&1 || true
    fi
}
trap cleanup EXIT HUP INT TERM

if [ "$DO_BUILD" = 1 ]; then
    if [ "$VERBOSE" = 1 ]; then
        sh "$ROOT/dev/dev-build.sh" --tag "$TAG" >&2
    else
        printf 'install-preview: building %s...\n' "$IMG" >&2
        if ! sh "$ROOT/dev/dev-build.sh" --tag "$TAG" > "$TMP/build.log" 2>&1; then
            echo "install-preview: image build failed:" >&2
            cat "$TMP/build.log" >&2
            exit 1
        fi
    fi
elif ! podman image exists "$IMG" > /dev/null 2>&1; then
    echo "install-preview.sh: image '$IMG' not found; run without --no-build first." >&2
    exit 1
fi

BIN="$TMP/.local/bin"
PREVIEW_PATH=$PATH
if [ "$IN_PATH" = 1 ]; then
    PREVIEW_PATH="$BIN:$PATH"
fi

if [ "$MODE" = install-sh ]; then
    REL="$TMP/release"
    mkdir -p "$REL"
    cp "$ROOT/container/host/swarmbox-host" "$REL/swarmbox"
    if command -v sha256sum > /dev/null 2>&1; then
        (cd "$REL" && sha256sum swarmbox > swarmbox.sha256)
    else
        (cd "$REL" && shasum -a 256 swarmbox > swarmbox.sha256)
    fi
    HOME="$TMP" \
    XDG_CONFIG_HOME="$TMP/.config" \
    XDG_DATA_HOME="$TMP/.local/share" \
    XDG_STATE_HOME="$TMP/.local/state" \
    SWARMBOX_BIN_DIR="$BIN" \
    SWARMBOX_RELEASE_URL="file://$REL" \
    PATH="$PREVIEW_PATH" \
    sh "$ROOT/install.sh" --image "$IMG" ${WITH:+--with "$WITH"}
else
    HOME="$TMP" \
    XDG_CONFIG_HOME="$TMP/.config" \
    XDG_DATA_HOME="$TMP/.local/share" \
    XDG_STATE_HOME="$TMP/.local/state" \
    SWARMBOX_BIN_DIR="$BIN" \
    PATH="$PREVIEW_PATH" \
    podman run --rm "$IMG" install --image "$IMG" ${WITH:+--with "$WITH"} | \
    HOME="$TMP" \
    XDG_CONFIG_HOME="$TMP/.config" \
    XDG_DATA_HOME="$TMP/.local/share" \
    XDG_STATE_HOME="$TMP/.local/state" \
    SWARMBOX_BIN_DIR="$BIN" \
    PATH="$PREVIEW_PATH" \
    sh
fi
