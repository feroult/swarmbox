#!/bin/bash
# mux.sh: loads the terminal multiplexer backend selected by SWARMBOX_MUX (default: tmux).
#
# Backend contract (each <name>.sh in the mux folder implements these bash functions):
#   mux_available             0 when the backend's binary is installed on PATH
#   mux_serve_init            step 9 of `serve`: start the backend's background session/daemon
#   mux_serve_shutdown_note   log line written when `serve` stops on SIGTERM/SIGINT
#   mux_attach_web            attach a browser client (`swarmbox-attach --web`)
#   mux_attach_interactive    open and attach an interactive host terminal tab
#   mux_attach_command CMD    run quoted shell command CMD in an attached tab and exit with its status
#   mux_web_fallback          set array MUX_WEB_FALLBACK_CMD (used by swarmbox-web when swarmbox-attach is absent)
#
# Test-only variable: SWARMBOX_TEST_MUX_DIR replaces the folder holding <backend>.sh.

# shellcheck disable=SC2034  # read by callers and tests
SB_MUX_NAME=${SWARMBOX_MUX:-tmux}

_sb_mux_load() {
    local name=$SB_MUX_NAME dir='' cand
    case "$name" in
        ''|*[!a-z0-9_-]*|-*|_* )
            echo "swarmbox: invalid SWARMBOX_MUX '$name' (lowercase letters, digits, '-' and '_' only)" >&2
            return 2
            ;;
    esac
    for cand in \
        "${SWARMBOX_TEST_MUX_DIR:-}" \
        "${SB_LIB:-/usr/local/lib/swarmbox}/mux" \
        "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; do
        [ -n "$cand" ] || continue
        if [ -r "$cand/$name.sh" ]; then
            dir=$cand
            break
        fi
    done
    if [ -z "$dir" ]; then
        echo "swarmbox: unknown multiplexer backend '$name' (no $name.sh in mux folder)" >&2
        return 1
    fi
    # shellcheck source=/dev/null
    . "$dir/$name.sh"
}

_sb_mux_load || return $?
