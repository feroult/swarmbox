#!/bin/sh
# install-preview.sh: build the local image and run the real `| sh` installer into your $HOME (or an isolated mktemp HOME).
#
# Usage: sh dev/install-preview.sh [--no-build] [--install-sh] [--isolated] [--in-path] [--no-path] [--with ADDONS] [--rmi] [--verbose]
#   (default)      build via dev/dev-build.sh, then run `podman run --rm IMAGE install | sh` into your real $HOME (~/.local/bin)
#   --no-build     skip the build and reuse localhost/swarmbox-test-install-preview
#   --install-sh   run `sh install.sh` against a local file:// release built from container/host/swarmbox-host
#   --isolated     install into a throwaway mktemp HOME instead of your real $HOME
#   --in-path      with --isolated, put the temporary bin dir on PATH (hides the `! PATH setup needed` block)
#   --no-path      hide ~/.local/bin from PATH so the `! PATH setup needed` block is previewed
#   --with ADDONS  pass --with ADDONS to the installer (e.g. claude,sysop)
#   --rmi          remove the test image after the preview finishes
#   --verbose      stream the image build output instead of hiding it until failure
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=swarmbox-test-install-preview
DO_BUILD=1
MODE=podman
ISOLATED=0
IN_PATH=0
NO_PATH=0
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
        --isolated) ISOLATED=1; shift ;;
        --in-path) IN_PATH=1; shift ;;
        --no-path) NO_PATH=1; shift ;;
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
REAL_XDG_DATA=${XDG_DATA_HOME:-$HOME/.local/share}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-install-preview.XXXXXX")
BUILD_PID=
cleanup() {
    if [ -n "$BUILD_PID" ] && kill -0 "$BUILD_PID" 2> /dev/null; then
        kill "$BUILD_PID" 2> /dev/null || true
    fi
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
        build_start=$(date +%s)
        sh "$ROOT/dev/dev-build.sh" --tag "$TAG" > "$TMP/build.log" 2>&1 &
        BUILD_PID=$!
        last_step=
        spin='|/-\'
        i=0
        is_tty=0
        [ -t 2 ] && is_tty=1
        if [ "$is_tty" = 0 ]; then
            printf 'install-preview: building %s...\n' "$IMG" >&2
        fi
        while kill -0 "$BUILD_PID" 2> /dev/null; do
            elapsed=$(( $(date +%s) - build_start ))
            step=$(grep -E '^STEP [0-9]+/[0-9]+:' "$TMP/build.log" 2> /dev/null | tail -n 1 | cut -c1-60 || true)
            if [ "$is_tty" = 1 ]; then
                idx=$(( (i % 4) + 1 ))
                ch=$(printf '%s' "$spin" | cut -c"$idx")
                if [ -n "$step" ]; then
                    printf '\r\033[Kinstall-preview: [%s] building %s (%ds) %s' "$ch" "$IMG" "$elapsed" "$step" >&2
                else
                    printf '\r\033[Kinstall-preview: [%s] building %s (%ds)...' "$ch" "$IMG" "$elapsed" >&2
                fi
                i=$(( i + 1 ))
            elif [ -n "$step" ] && [ "$step" != "$last_step" ]; then
                printf 'install-preview: (%ds) %s\n' "$elapsed" "$step" >&2
                last_step=$step
            fi
            sleep 1
        done
        set +e
        wait "$BUILD_PID"
        build_rc=$?
        set -e
        BUILD_PID=
        elapsed=$(( $(date +%s) - build_start ))
        if [ "$is_tty" = 1 ]; then
            printf '\r\033[K' >&2
        fi
        if [ "$build_rc" -ne 0 ]; then
            printf 'install-preview: image build failed after %ds:\n' "$elapsed" >&2
            cat "$TMP/build.log" >&2
            exit 1
        fi
        printf 'install-preview: built %s (%ds)\n' "$IMG" "$elapsed" >&2
    fi
elif ! podman image exists "$IMG" > /dev/null 2>&1; then
    echo "install-preview.sh: image '$IMG' not found; run without --no-build first." >&2
    exit 1
fi

if [ "$ISOLATED" = 1 ]; then
    BIN="$TMP/.local/bin"
    SUPPORT_TMP="$TMP/.local/share/swarmbox/host"
    PREVIEW_PATH=$PATH
    if [ "$IN_PATH" = 1 ]; then
        PREVIEW_PATH="$BIN:$PATH"
    fi
    printf '\n── simulated user install (isolated HOME) ─────────────────────────────────────\n\n' >&2
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
        XDG_DATA_HOME="$REAL_XDG_DATA" \
        XDG_STATE_HOME="$TMP/.local/state" \
        SWARMBOX_BIN_DIR="$BIN" \
        SWARMBOX_TEST_SUPPORT_DIR="$SUPPORT_TMP" \
        SWARMBOX_NO_START=1 \
        SWARMBOX_RELEASE_URL="file://$REL" \
        PATH="$PREVIEW_PATH" \
        sh "$ROOT/install.sh" --image "$IMG" ${WITH:+--with "$WITH"}
    else
        podman run --rm --pull=never "$IMG" install --image "$IMG" ${WITH:+--with "$WITH"} | \
        HOME="$TMP" \
        XDG_CONFIG_HOME="$TMP/.config" \
        XDG_DATA_HOME="$REAL_XDG_DATA" \
        XDG_STATE_HOME="$TMP/.local/state" \
        SWARMBOX_BIN_DIR="$BIN" \
        SWARMBOX_TEST_SUPPORT_DIR="$SUPPORT_TMP" \
        SWARMBOX_NO_START=1 \
        PATH="$PREVIEW_PATH" \
        sh
    fi
else
    REAL_BIN=${SWARMBOX_BIN_DIR:-$HOME/.local/bin}
    PREVIEW_PATH=$PATH
    if [ "$NO_PATH" = 1 ]; then
        PREVIEW_PATH=$(printf '%s' "$PATH" | awk -v RS=: -v ORS=: -v rm="$REAL_BIN" '$0 != rm && $0 != ""' | sed 's/:$//')
    fi
    printf '\n── user install (%s) ──────────────────────────────────────────────────────────\n\n' "$REAL_BIN" >&2
    if [ "$MODE" = install-sh ]; then
        REL="$TMP/release"
        mkdir -p "$REL"
        cp "$ROOT/container/host/swarmbox-host" "$REL/swarmbox"
        if command -v sha256sum > /dev/null 2>&1; then
            (cd "$REL" && sha256sum swarmbox > swarmbox.sha256)
        else
            (cd "$REL" && shasum -a 256 swarmbox > swarmbox.sha256)
        fi
        SWARMBOX_RELEASE_URL="file://$REL" \
        PATH="$PREVIEW_PATH" \
        sh "$ROOT/install.sh" --image "$IMG" ${WITH:+--with "$WITH"}
    else
        podman run --rm --pull=never "$IMG" install --image "$IMG" ${WITH:+--with "$WITH"} | \
        PATH="$PREVIEW_PATH" \
        sh
    fi
fi
