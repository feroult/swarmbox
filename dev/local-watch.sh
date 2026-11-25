#!/bin/sh
# local-watch.sh: watch for a trigger file in this checkout and run `dev/local-up.sh --yes` on the host,
# so you can trigger an image rebuild and box reset from inside a running SwarmBox (e.g. while developing remotely).
#
# Usage (on the HOST):
#   sh dev/local-watch.sh [--interval SEC] [--file PATH] [--once] [--no-cache] [--no-reset] [--dry-run] [--release] [--with ADDONS]
#
# Usage (from INSIDE the box, or on the host):
#   sh dev/local-watch.sh --trigger [--file PATH] [--no-cache] [--no-reset] [--dry-run] [--release]
#   sh dev/local-watch.sh --status  [--file PATH]
#
# Options:
#   --trigger      create the trigger file (works inside the box) so the host watchdog runs local-up.sh --yes
#   --status       print pending trigger state and the last reload result/log path (works inside the box)
#   --file PATH    trigger file path (default: <repo>/.work/local-reload, or $SWARMBOX_WATCH_FILE)
#   --interval SEC poll interval in seconds (default: 2, or $SWARMBOX_WATCH_INTERVAL)
#   --once         wait for one trigger, run local-up.sh --yes, and exit with its status
#   --no-cache     pass --no-cache to local-up.sh
#   --no-reset     pass --no-reset to local-up.sh
#   --dry-run      pass --dry-run to local-up.sh
#   --release      pass --release to local-up.sh
#   --with ADDONS  pass --with ADDONS to local-up.sh (host-side only)
#
# Security: the trigger file may come from inside the container, so the host only accepts an explicit
# allowlist of boolean flags (--no-cache, --no-reset, --dry-run, --release) from it and removes the
# file before starting the build so a failed build never loops.
#
# Environment: SWARMBOX_WATCH_FILE, SWARMBOX_WATCH_INTERVAL.
# Test-only: SWARMBOX_LOCAL_UP (overrides dev/local-up.sh), SWARMBOX_TEST_CONTAINERENV (overrides /run/.containerenv).
# Exit: 0 ok, 1 reload failed (with --once), 2 usage or watch started inside a box.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LOCAL_UP=${SWARMBOX_LOCAL_UP:-$ROOT/dev/local-up.sh}
TRIGGER=${SWARMBOX_WATCH_FILE:-$ROOT/.work/local-reload}
INTERVAL=${SWARMBOX_WATCH_INTERVAL:-2}
CONTAINERENV=${SWARMBOX_TEST_CONTAINERENV:-/run/.containerenv}

MODE=watch
ONCE=0
NO_CACHE=0
NO_RESET=0
DRY_RUN=0
RELEASE=0
WITH=

say() { printf '%s\n' "$*"; }
die() { _rc=$1; shift; printf 'local-watch: %s\n' "$*" >&2; exit "$_rc"; }

while [ $# -gt 0 ]; do
    case $1 in
        --trigger) MODE=trigger ;;
        --status) MODE=status ;;
        --file) [ $# -ge 2 ] || die 2 "--file needs a path"; TRIGGER=$2; shift ;;
        --interval) [ $# -ge 2 ] || die 2 "--interval needs a value"; INTERVAL=$2; shift ;;
        --once) ONCE=1 ;;
        --no-cache) NO_CACHE=1 ;;
        --no-reset) NO_RESET=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --release) RELEASE=1 ;;
        --with) [ $# -ge 2 ] || die 2 "--with needs a value"; WITH=$2; shift ;;
        -h|--help) awk 'NR == 1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; exit 0 ;;
        *) die 2 "unknown option $1 (try --help)" ;;
    esac
    shift
done

LOG_FILE="${TRIGGER}.log"
STATUS_FILE="${TRIGGER}.status"

case $INTERVAL in
    ''|.|*[!0-9.]*|*.*.*) die 2 "invalid --interval '$INTERVAL' (expected a positive number)" ;;
esac

if [ "$MODE" = trigger ]; then
    [ -z "$WITH" ] || die 2 "--with is a host-side option; pass it when starting the watchdog"
    mkdir -p "$(dirname "$TRIGGER")"
    tmp_trigger="${TRIGGER}.tmp.$$"
    : > "$tmp_trigger"
    [ "$NO_CACHE" = 1 ] && printf '%s\n' "--no-cache" >> "$tmp_trigger"
    [ "$NO_RESET" = 1 ] && printf '%s\n' "--no-reset" >> "$tmp_trigger"
    [ "$DRY_RUN" = 1 ] && printf '%s\n' "--dry-run" >> "$tmp_trigger"
    [ "$RELEASE" = 1 ] && printf '%s\n' "--release" >> "$tmp_trigger"
    mv "$tmp_trigger" "$TRIGGER"
    say "local-watch: triggered reload ($TRIGGER)."
    say "local-watch: if the host watchdog is running, the box will rebuild and reset shortly."
    say "local-watch: check status/logs with: sh dev/local-watch.sh --status"
    exit 0
fi

if [ "$MODE" = status ]; then
    if [ -f "$TRIGGER" ]; then
        say "pending: yes ($TRIGGER)"
    else
        say "pending: no"
    fi
    if [ -f "$STATUS_FILE" ]; then
        cat "$STATUS_FILE"
    else
        say "last: none"
    fi
    if [ -f "$LOG_FILE" ]; then
        say "log: $LOG_FILE"
    fi
    exit 0
fi

if [ -e "$CONTAINERENV" ]; then
    die 2 "this is inside a box: run the watchdog on the host. From inside the box, trigger it with: sh dev/local-watch.sh --trigger"
fi

[ -f "$LOCAL_UP" ] || die 2 "cannot find local-up script at $LOCAL_UP"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-local-watch.XXXXXX") || exit 1
cleanup() { rm -rf "${TMP:?}"; }
trap cleanup EXIT
trap 'say ""; say "local-watch: stopped."; exit 0' INT TERM

mkdir -p "$(dirname "$TRIGGER")"

run_reload() {
    trig_no_cache=$NO_CACHE
    trig_no_reset=$NO_RESET
    trig_dry_run=$DRY_RUN
    trig_release=$RELEASE

    # Read trigger file into a temporary copy and remove it immediately so a failed build never loops.
    cp "$TRIGGER" "$TMP/trigger" 2>/dev/null || : > "$TMP/trigger"
    rm -f "$TRIGGER"

    while IFS= read -r line || [ -n "$line" ]; do
        for tok in $line; do
            case $tok in
                --no-cache) trig_no_cache=1 ;;
                --no-reset) trig_no_reset=1 ;;
                --dry-run) trig_dry_run=1 ;;
                --release) trig_release=1 ;;
                \#*) break ;;
                *) printf 'local-watch: ignoring disallowed trigger token: %s\n' "$tok" >&2 ;;
            esac
        done
    done < "$TMP/trigger"

    set -- --yes
    [ "$trig_no_cache" = 1 ] && set -- "$@" --no-cache
    [ "$trig_no_reset" = 1 ] && set -- "$@" --no-reset
    [ "$trig_dry_run" = 1 ] && set -- "$@" --dry-run
    [ "$trig_release" = 1 ] && set -- "$@" --release
    [ -n "$WITH" ] && set -- "$@" --with "$WITH"

    started=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    say ""
    say "==> local-watch [$started]: running sh $LOCAL_UP $*"
    printf 'status: running\nstarted: %s\nargs: %s\n' "$started" "$*" > "$STATUS_FILE"

    rc_file="$TMP/rc"
    rm -f "$rc_file"
    (
        rc=0
        sh "$LOCAL_UP" "$@" 2>&1 || rc=$?
        printf '%s\n' "$rc" > "$rc_file"
    ) | tee "$LOG_FILE"

    rc=$(cat "$rc_file" 2>/dev/null || printf '1')
    finished=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    if [ "$rc" = 0 ]; then
        printf 'status: ok\nstarted: %s\nfinished: %s\nexit: 0\nargs: %s\n' "$started" "$finished" "$*" > "$STATUS_FILE"
        say "==> local-watch [$finished]: reload succeeded."
    else
        printf 'status: failed\nstarted: %s\nfinished: %s\nexit: %s\nargs: %s\n' "$started" "$finished" "$rc" "$*" > "$STATUS_FILE"
        say "==> local-watch [$finished]: reload failed (exit $rc). Waiting for next trigger."
    fi
    return "$rc"
}

say "local-watch: watching $TRIGGER (every ${INTERVAL}s)"
say "local-watch: from inside the box, run: sh dev/local-watch.sh --trigger"

while :; do
    if [ -f "$TRIGGER" ]; then
        rc=0
        run_reload || rc=$?
        if [ "$ONCE" = 1 ]; then
            exit "$rc"
        fi
    fi
    sleep "$INTERVAL"
done
