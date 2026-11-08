#!/bin/bash
# swarmbox-attach (design 3.3, 3.4, 4.2; installed as /usr/local/bin/swarmbox-attach, called by `swarmbox-entrypoint attach`).
# Replaces v0.1.0's lib/attach-session.sh.
#
#   swarmbox-attach [--plain] [--] [command [args...]]
#
#   no command, terminal    a new window of tmux session "main" through a grouped session (no status bar, ends with the
#                           tab); when the only other window is the idle one `serve` made, that one is closed (B36)
#   command, terminal       the `swarmbox <command>` mechanism (3.3): a detached window runs the command through an
#                           interactive shell; this program waits on a tmux wait-for channel, with a poll of the window id
#                           as the fallback, and exits with the command's status (128+signal; 129 when the window was
#                           killed; 1 when the status is lost)
#   no terminal, or --plain no tmux at all: the command (or a shell) runs directly; without a terminal through a
#                           NON-interactive bash that sources the shell fragment (SWARMBOX_CMD=1), because `bash -ic`
#                           without a terminal prints job-control errors
#
# First it waits up to 60 s for the readiness marker of `serve` (4.2) and exits 6 when it does not appear.
#
# Test-only variables (decision log [2.3]; not in the configuration table of design 8): SWARMBOX_TEST_LIB (folder with
# dirs.sh), SWARMBOX_TEST_RUN_DIR (replaces /tmp/swarmbox), SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60),
# SWARMBOX_TEST_POLL_INTERVAL (seconds between window-id polls, default 1), SWARMBOX_TEST_FRAGMENT (the shell fragment file).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "swarmbox-attach: cannot read $SB_LIB/dirs.sh" >&2; exit 1; }
SB_RUN_DIR=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}
FRAGMENT=${SWARMBOX_TEST_FRAGMENT:-/etc/swarmbox/bashrc.sh}
READY_TIMEOUT=${SWARMBOX_TEST_READY_TIMEOUT:-60}
POLL=${SWARMBOX_TEST_POLL_INTERVAL:-1}
SESSION=main
IDLE_NAME=idle          # the name `serve` gives the idle window (step 9); keep in step with container/entrypoint.sh
BOX_NAME=${SWARMBOX_NAME:-swarmbox}

# A tmux started from inside a tmux window would refuse to nest; the target is always the server of this box.
unset TMUX

PLAIN=0
if [ "${1:-}" = "--plain" ]; then PLAIN=1; shift; fi
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

# direct: no tmux. $q is the quoted command string ("" for a plain shell).
direct() {
    if have_terminal; then
        if [ -n "$q" ]; then exec bash -ic "$q"; fi
        exec bash -i
    fi
    if [ -z "$q" ]; then exec bash; fi
    # shellcheck disable=SC2016  # the single quotes are the point: the inner bash expands $1 and $2
    exec env SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; [ -r "$2" ] && . "$2"; unset SWARMBOX_CMD; eval -- "$1"' bash "$q" "$FRAGMENT"
}

ensure_session() {
    tmux has-session -t "=$SESSION" 2>/dev/null && return 0
    tmux new-session -d -s "$SESSION" -n "$IDLE_NAME" 2>/dev/null || tmux has-session -t "=$SESSION" 2>/dev/null
}

# idle_window: print the id of the idle window when it is the ONLY window of the session, still named by `serve`, with
# one pane running just a shell (nothing typed into it that is still running). Anything else is a window of the user.
idle_window() {
    local rows id name cmd panes
    rows=$(tmux list-windows -t "=$SESSION" -F '#{window_id}|#{window_name}|#{pane_current_command}|#{window_panes}' 2>/dev/null) || return 1
    [ "$(printf '%s\n' "$rows" | wc -l)" = 1 ] || return 1
    IFS='|' read -r id name cmd panes <<< "$rows"
    [ "$name" = "$IDLE_NAME" ] && [ "$panes" = 1 ] || return 1
    case "$cmd" in bash|zsh|sh|dash|fish) ;; *) return 1 ;; esac
    printf '%s\n' "$id"
}

# new_window: a detached window in the session, in the caller's directory; prints its id. The rest are the shell command.
new_window() {
    tmux new-window -d -P -F '#{window_id}' -t "=$SESSION:" -c "$PWD" "$@"
}

window_listed() { tmux list-windows -t "=$SESSION" -F '#{window_id}' 2>/dev/null | grep -qxF "$1"; }

interactive() {
    local idle w
    ensure_session || die "tmux could not start the session $SESSION"
    idle=$(idle_window)
    w=$(new_window) || die "tmux could not open a window"
    [ -n "$w" ] || die "tmux could not open a window"
    [ -z "$idle" ] || tmux kill-window -t "$idle" 2>/dev/null
    exec tmux new-session -t "=$SESSION" \; set-option destroy-unattached on \; set-option status off \; select-window -t "$w"
}

# The wrapper runs as the window's command (design 3.3). $1 the quoted command, $2 the status file, $3 the channel.
# bash -ic runs in the background and the wrapper waits, so that the trap can run when tmux hangs the window up
# (kill-window); stdin is passed on explicitly because a background job of a non-interactive shell would get /dev/null.
read -r -d '' WRAPPER <<'EOF'
sb_status=$2
sb_chan=$3
sb_fin() { echo "$1" > "$sb_status.tmp" && mv "$sb_status.tmp" "$sb_status"; tmux wait-for -S "$sb_chan"; }
trap 'kill "$sb_pid" 2>/dev/null; sb_fin 129; exit 129' HUP TERM
exec 3<&0
bash -ic "$1" <&3 3<&- &
sb_pid=$!
wait "$sb_pid"
sb_rc=$?
trap - HUP TERM
sb_fin "$sb_rc"
EOF

run_command() {
    local id status chan grp w client waiter ticks n rc detached=0
    id="$(date +%s%N)p$$"
    status="$SB_RUN_DIR/exit.$id"
    chan="swarmbox-$id"
    grp="swarmbox-cmd-$id"
    ensure_session || die "tmux could not start the session $SESSION"
    rm -f "$status" "$status.tmp"
    w=$(new_window bash -c "$WRAPPER" wrapper "$q" "$status" "$chan") || die "tmux could not open a window"
    [ -n "$w" ] || die "tmux could not open a window"

    # the grouped client, as a child (not exec), selected on the command's window; stdin is passed on explicitly
    exec 3<&0
    tmux new-session -t "=$SESSION" -s "$grp" \; set-option destroy-unattached on \; set-option status off \; select-window -t "$w" <&3 3<&- &
    client=$!
    exec 3<&-
    tmux wait-for "$chan" < /dev/null &
    waiter=$!

    # shellcheck disable=SC2317  # called from the trap
    abort() {
        kill "$waiter" 2>/dev/null
        tmux kill-session -t "=$grp" 2>/dev/null
        kill "$client" 2>/dev/null
        exit "$1"
    }
    trap 'abort 129' HUP
    trap 'abort 143' TERM

    ticks=$(awk -v p="$POLL" 'BEGIN { t = int(p * 10 + 0.5); if (t < 1) t = 1; print t }')
    n=0
    while kill -0 "$waiter" 2>/dev/null; do
        sleep 0.1
        n=$((n + 1))
        [ "$n" -ge "$ticks" ] || continue
        n=0
        [ -s "$status" ] && break
        if ! window_listed "$w" || ! kill -0 "$client" 2>/dev/null; then
            # the window is gone or the client ended: give a status that is on its way a moment to arrive
            for _ in 1 2 3 4 5; do
                kill -0 "$waiter" 2>/dev/null || break
                [ -s "$status" ] && break
                sleep 0.2
            done
            if ! kill -0 "$waiter" 2>/dev/null || [ -s "$status" ]; then break; fi
            window_listed "$w" && detached=1
            break
        fi
    done
    kill "$waiter" 2>/dev/null
    wait "$waiter" 2>/dev/null

    # end the grouped client so that this call returns although other windows exist; restore the terminal before exiting
    tmux kill-session -t "=$grp" 2>/dev/null
    for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        kill -0 "$client" 2>/dev/null || break
        sleep 0.2
    done
    kill "$client" 2>/dev/null
    wait "$client" 2>/dev/null
    trap - HUP TERM

    if [ "$detached" = 1 ]; then
        rm -f "$status" "$status.tmp"
        echo "swarmbox: detached; the command keeps running in window $w of the session $SESSION" >&2
        exit 0
    fi
    rc=$(cat "$status" 2>/dev/null)
    rm -f "$status" "$status.tmp"
    case "$rc" in
        ''|*[!0-9]*) die "the command's status is lost (its window was closed hard or tmux ended); exit status unknown" 1 ;;
    esac
    exit "$rc"
}

# ---------------------------------------------------------------------------------------------------------------------
q=""
if [ "$#" -gt 0 ]; then q=$(printf '%q ' "$@"); fi

wait_ready

if [ "$PLAIN" = 1 ] || ! have_terminal || ! command -v tmux > /dev/null 2>&1; then
    direct
fi
if [ -z "$q" ]; then
    interactive
else
    run_command
fi
