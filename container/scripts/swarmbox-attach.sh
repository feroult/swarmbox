#!/bin/bash
# swarmbox-attach (installed as /usr/local/bin/swarmbox-attach, called by `swarmbox-entrypoint attach`).
#
#   swarmbox-attach [--plain | --web] [--] [command [args...]]
#
#   --web                   what the web terminal runs: delegates to mux_attach_web so the browser sees every tab
#   no command, terminal    delegates to mux_attach_interactive for an interactive host terminal tab
#   command, terminal       delegates to mux_attach_command so the command runs in a shared tab and exits with its status
#   no terminal, or --plain bypasses the multiplexer completely: the command (or a shell) runs directly; without a terminal
#                           through a NON-interactive bash that sources the shell fragment (SWARMBOX_CMD=1), because `bash -ic`
#                           without a terminal prints job-control errors
#
# First it waits up to 60 s for the readiness marker of `serve` and exits 6 when it does not appear.
# Multiplexer-specific logic lives in container/scripts/mux/<backend>.sh (default: tmux).
#
# Test-only variables (not in the configuration table): SWARMBOX_TEST_LIB (folder with
# dirs.sh), SWARMBOX_TEST_MUX_DIR (folder with mux.sh and <backend>.sh), SWARMBOX_TEST_RUN_DIR (replaces /tmp/swarmbox),
# SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60), SWARMBOX_TEST_POLL_INTERVAL (seconds between window-id polls, default 1),
# SWARMBOX_TEST_FRAGMENT (the shell fragment file).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "swarmbox-attach: cannot read $SB_LIB/dirs.sh" >&2; exit 1; }
SB_RUN_DIR=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}
FRAGMENT=${SWARMBOX_TEST_FRAGMENT:-/etc/swarmbox/bashrc.sh}
READY_TIMEOUT=${SWARMBOX_TEST_READY_TIMEOUT:-60}
# shellcheck disable=SC2034  # used by mux backends (mux_attach_command)
POLL=${SWARMBOX_TEST_POLL_INTERVAL:-1}
# The box name (only used in messages): SWARMBOX_NAME, which the helper passes to every box; else the default name of the DEFAULTS file
# that the image keeps next to the script. SWARMBOX_TEST_HOST_DIR replaces that folder in tests, as for swarmbox-install.
BOX_NAME=${SWARMBOX_NAME:-}
if [ -z "$BOX_NAME" ]; then
    while IFS= read -r _l || [ -n "$_l" ]; do
        case $_l in SWARMBOX_DEFAULT_NAME=*) BOX_NAME=${_l#*=} ;; esac
    done 2> /dev/null < "${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}/DEFAULTS"
    BOX_NAME=${BOX_NAME//[\'\"]/}
fi
: "${BOX_NAME:=<box>}"

PLAIN=0
WEB=0
if [ "${1:-}" = "--plain" ]; then PLAIN=1; shift; elif [ "${1:-}" = "--web" ]; then WEB=1; shift; fi
if [ "${1:-}" = "--" ]; then shift; fi

die() { echo "swarmbox: $*" >&2; exit "${2:-1}"; }

wait_ready() {
    local n=$(( READY_TIMEOUT * 5 ))
    while [ "$n" -gt 0 ]; do
        [ -f "$SB_RUN_DIR/ready" ] && return 0
        sleep 0.2
        n=$((n - 1))
    done
    [ -f "$SB_RUN_DIR/ready" ] && return 0
    die "the box is not ready; run \`podman logs $BOX_NAME\` on the host" 6
}

have_terminal() { [ -t 0 ] && [ -t 1 ]; }

# direct: no multiplexer. $q is the quoted command string ("" for a plain shell).
direct() {
    if have_terminal; then
        if [ -n "$q" ]; then exec bash -ic "$q"; fi
        exec bash -i
    fi
    if [ -z "$q" ]; then exec bash; fi
    # shellcheck disable=SC2016  # the single quotes are the point: the inner bash expands $1 and $2
    exec env SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; [ -r "$2" ] && . "$2"; unset SWARMBOX_CMD; eval -- "$1"' bash "$q" "$FRAGMENT"
}

load_mux() {
    local cand
    for cand in "${SWARMBOX_TEST_MUX_DIR:-}" "$SB_LIB/mux" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mux"; do
        [ -n "$cand" ] || continue
        if [ -r "$cand/mux.sh" ]; then
            # shellcheck source=/dev/null
            . "$cand/mux.sh"
            return $?
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------------------------------------------------
q=""
if [ "$#" -gt 0 ]; then q=$(printf '%q ' "$@"); fi

wait_ready

if [ "$PLAIN" = 1 ] || ! have_terminal; then
    direct
fi
if ! load_mux || ! mux_available; then
    direct
fi
if [ "$WEB" = 1 ]; then
    mux_attach_web
elif [ -z "$q" ]; then
    mux_attach_interactive
else
    mux_attach_command "$q"
fi
