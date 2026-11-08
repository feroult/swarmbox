#!/bin/bash
# swarmbox-entrypoint (design 10.2): the image's entry point.
#
#   serve     the box's main process: the ordered startup of design 4.1, the readiness marker and health file of 4.2,
#             PID 1 signal handling, and the ttyd supervisor of 5.1 (slice 2.2, this file)
#   attach    forwards to swarmbox-attach (slice 2.3: the grouped session, the idle window, `swarmbox <command>`)
#   init, pubkey, tool, host-helper
#             written by the next slices of Phase 2; until then they fail loudly (exit 70, EX_SOFTWARE) instead of
#             pretending to work
#   (none)    exit 64
#   anything else is run as given (already the final behavior, design 10.2)
#
# Test-only variables (decision log "[2.2] test-only switches"; deliberately NOT in the configuration table of
# design 8 and not read by anything else): SWARMBOX_TEST_LIB (folder holding dirs.sh), SWARMBOX_TEST_RUN_DIR (replaces
# /tmp/swarmbox), SWARMBOX_TEST_TUN (replaces /dev/net/tun), SWARMBOX_TEST_NO_NESTED=1 (no nested Podman: a warning
# instead of a failure for step 2 and no service at step 8), SWARMBOX_TEST_BACKOFF_SCALE (integer multiplier of the
# ttyd backoff, 0 for none), SWARMBOX_TEST_SERVICE_WAIT (seconds to wait for the nested service, default 10).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}

# ---------------------------------------------------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------------------------------------------------

EARLY_LOG=""   # log lines written before the state folder exists (steps 0 to 2); flushed at step 3
WARNINGS=0
SUP=""
SVC=""
INST=""
STOPPING=0

log() {
    local line
    line="$(date '+%Y-%m-%dT%H:%M:%S') serve[$$]: $*"
    printf '%s\n' "$line"
    if [ -n "${SERVE_LOG:-}" ] && [ -d "${SB_STATE_DIR:-/nonexistent}" ]; then
        printf '%s\n' "$line" >> "$SERVE_LOG" 2>/dev/null
    else
        EARLY_LOG="$EARLY_LOG$line"$'\n'
    fi
    return 0
}

have() { command -v "$1" >/dev/null 2>&1; }

health_add() { printf '%s\n' "$1" >> "$SB_HEALTH_FILE" 2>/dev/null; return 0; }

health_remove() {
    # remove one exact line (a rewrite: the only writers are serve's steps, the installer job and the supervisor)
    [ -f "$SB_HEALTH_FILE" ] || return 0
    grep -vxF -- "$1" "$SB_HEALTH_FILE" > "$SB_HEALTH_FILE.tmp.$$" 2>/dev/null
    mv -f "$SB_HEALTH_FILE.tmp.$$" "$SB_HEALTH_FILE" 2>/dev/null
    return 0
}

# W: one health line, one log line, counted for the readiness marker.
warn() {
    WARNINGS=$((WARNINGS + 1))
    health_add "$1"
    log "WARNING: $1"
}

# stop_children: the ttyd supervisor (which stops ttyd), the installer job, the nested Podman service. The tmux server is
# left to end with the container (design 4.1).
stop_children() {
    local p
    for p in "$SUP" "$INST"; do
        if [ -n "$p" ]; then
            kill -TERM "$p" 2>/dev/null
            wait "$p" 2>/dev/null
        fi
    done
    if [ -n "$SVC" ]; then
        kill -TERM "$SVC" 2>/dev/null
        wait "$SVC" 2>/dev/null
    fi
    SUP=""; INST=""; SVC=""
    rm -f "${SB_RUN_DIR:-/nonexistent}/web-supervisor.pid" 2>/dev/null
    return 0
}

on_signal() {
    # $1 signal name, $2 exit status (128 + signal number)
    if [ "$STOPPING" = 0 ]; then
        STOPPING=1
        log "received SIG$1, stopping children"
        stop_children
        log "leaving the tmux server to end with the container"
    fi
    exit "$2"
}

# F: print the reason, stop what was started, exit 1 (the box stops; `podman logs` shows the reason).
fatal() {
    log "FATAL: $*"
    echo "swarmbox serve: $*" >&2
    stop_children
    exit 1
}

# run_logged <cmd...>: run it with its output appended to serve.log; return its status.
run_logged() {
    "$@" >> "$SERVE_LOG" 2>&1
}

# ttyd_command: the program line the supervisor runs. `swarmbox-web run` (a later slice) assembles the page and the
# options and execs ttyd in the foreground; until it exists the supervisor runs ttyd directly (port 7681 inside the box).
ttyd_command() {
    if have swarmbox-web; then
        TTYD_CMD=(swarmbox-web run)
    else
        TTYD_CMD=(ttyd -W -p 7681 tmux attach -t main)
    fi
}

# supervise: design 4.2 "ttyd restart policy". Runs in a subshell. Restarts ttyd after 1, 2, 4 ... 30 s; after 5 exits
# within 60 s it records a health line and idles (alive) until `swarmbox-web restart` sends USR1; TERM stops it.
supervise() {
    local tp=0 sp=0 stop=0 restart=0 delay=1 i
    local -a exits=() keep=()
    local scale=${SWARMBOX_TEST_BACKOFF_SCALE:-1}
    local line="web terminal keeps crashing; see web-terminal.log"
    local wlog="$SB_STATE_DIR/web-terminal.log"
    # shellcheck disable=SC2317  # called from the traps below
    kill_pids() {
        [ "$tp" -gt 0 ] && kill "$tp" 2>/dev/null
        [ "$sp" -gt 0 ] && kill "$sp" 2>/dev/null
        return 0
    }
    # nap <seconds|infinity>: an interruptible sleep. A signal that arrived before sp was known sets a flag, which is
    # checked right after sp is assigned, so no signal can be lost between the two.
    nap() {
        sleep "$1" &
        sp=$!
        if [ "$stop" = 1 ] || [ "$restart" = 1 ]; then kill "$sp" 2>/dev/null; fi
        wait "$sp" 2>/dev/null
        sp=0
    }
    trap 'stop=1; kill_pids' TERM
    trap 'restart=1; kill_pids' USR1
    ttyd_command
    while [ "$stop" = 0 ]; do
        if [ "$restart" = 1 ]; then
            restart=0; exits=(); delay=1; health_remove "$line"
            log "ttyd restarted by hand; crash count reset"
        fi
        "${TTYD_CMD[@]}" >> "$wlog" 2>&1 < /dev/null &
        tp=$!
        # a signal that arrived before tp was known must still act on this ttyd
        if [ "$restart" = 1 ] || [ "$stop" = 1 ]; then kill "$tp" 2>/dev/null; fi
        while kill -0 "$tp" 2>/dev/null; do wait "$tp" 2>/dev/null; done   # wait returns early when a trap fires
        tp=0
        [ "$stop" = 1 ] && break
        [ "$restart" = 1 ] && continue
        exits+=("$SECONDS")
        keep=()
        for i in "${exits[@]}"; do
            [ $((SECONDS - i)) -lt 60 ] && keep+=("$i")
        done
        exits=("${keep[@]}")
        if [ "${#exits[@]}" -ge 5 ]; then
            health_add "$line"
            log "ttyd exited 5 times within 60 s: giving up; waiting for 'swarmbox-web restart'"
            while [ "$restart" = 0 ] && [ "$stop" = 0 ]; do
                nap infinity
            done
            continue
        fi
        log "ttyd exited; restarting in $((delay * scale)) s"
        nap "$((delay * scale))"
        delay=$((delay * 2)); [ "$delay" -gt 30 ] && delay=30
    done
    exit 0
}

wait_for_service() {
    # $1 seconds; returns 0 when the socket exists, 1 when the service died or the time ran out
    local n=$(( $1 * 5 ))
    while [ "$n" -gt 0 ]; do
        [ -S "$SB_PODMAN_SOCK" ] && return 0
        kill -0 "$SVC" 2>/dev/null || return 1
        sleep 0.2
        n=$((n - 1))
    done
    [ -S "$SB_PODMAN_SOCK" ]
}

serve() {
    # shellcheck source=/dev/null
    . "$SB_LIB/dirs.sh" || { echo "swarmbox serve: cannot read $SB_LIB/dirs.sh" >&2; exit 1; }
    SB_RUN_DIR=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}
    SERVE_LOG=$SB_STATE_DIR/serve.log
    local tun=${SWARMBOX_TEST_TUN:-/dev/net/tun}
    local no_nested=${SWARMBOX_TEST_NO_NESTED:-0}
    local rc probe

    # PID 1: handlers first, so that `podman stop` ends the box promptly at any point (design 4.1)
    trap 'on_signal TERM 143' TERM
    trap 'on_signal INT 130' INT

    # step 0 [-]: delete the readiness marker and every exit.* file, before anything else (second defense after the tmpfs)
    rm -f "$SB_RUN_DIR/ready" "$SB_RUN_DIR/ready.tmp" "$SB_RUN_DIR"/exit.* 2>/dev/null
    log "step 0: old readiness marker and exit.* files removed"

    # step 1 [F]: the workspace is a directory and the agent user can create a file in it
    log "step 1: checking the workspace $HOME"
    case "${HOME:-}" in /*) ;; *) fatal "the workspace is not set: HOME is '${HOME:-}'" ;; esac
    [ -d "$HOME" ] || fatal "the workspace $HOME is not a directory"
    if probe=$(mktemp "$HOME/.swarmbox-serve-probe.XXXXXX" 2>/dev/null); then
        rm -f "$probe"
    else
        fatal "cannot create a file in the workspace $HOME (is it writable by the agent user?)"
    fi

    # step 2 [F]: /dev/net/tun exists
    log "step 2: checking $tun"
    if [ ! -e "$tun" ]; then
        if [ "$no_nested" = 1 ]; then
            NOTUN=1
        else
            fatal "nested Podman needs /dev/net/tun ($tun is missing; start the box with --device /dev/net/tun)"
        fi
    fi

    # step 3 [F]: the XDG folders and the run folder
    if ! mkdir -p "$SB_CONFIG_DIR" "$SB_DATA_DIR" "$SB_STATE_DIR" "$SB_TOOLS_DIR" "$SB_SHIMS_DIR" "$SB_LOG_DIR" "$SB_RUN_DIR" 2>/dev/null; then
        fatal "cannot create the SwarmBox folders under $HOME and $SB_RUN_DIR"
    fi
    : > "$SB_HEALTH_FILE" 2>/dev/null || fatal "cannot create $SB_HEALTH_FILE"   # cleared at every start (design 4.2)
    printf '%s' "$EARLY_LOG" >> "$SERVE_LOG" 2>/dev/null
    EARLY_LOG=""
    log "step 3: folders created; health file cleared"
    if [ "${NOTUN:-0}" = 1 ]; then
        warn "nested Podman needs /dev/net/tun ($tun is missing; SWARMBOX_TEST_NO_NESTED=1)"
    fi

    # step 4 [W]: migrate an old .swarmbox/ layout (12.4; written by a later slice)
    if have swarmbox-migrate; then
        log "step 4: migrating an old layout"
        run_logged swarmbox-migrate; rc=$?
        [ "$rc" = 0 ] || warn "layout migration failed (swarmbox-migrate exit $rc); see serve.log"
    else
        log "step 4: swarmbox-migrate is not installed yet (layout migration, later slice), skipped"
    fi

    # step 5 [W]: ensure the SSH key
    log "step 5: ensuring the SSH key"
    if have swarmbox-pubkey; then
        run_logged swarmbox-pubkey --ensure; rc=$?
        [ "$rc" = 0 ] || warn "could not create the Git SSH key (swarmbox-pubkey exit $rc); see serve.log"
    else
        warn "could not create the Git SSH key: swarmbox-pubkey not found"
    fi

    # step 6 [W]: link the user-level tools (6.2; swarmbox-tool is a later phase)
    if have swarmbox-tool; then
        log "step 6: swarmbox-tool link --user"
        run_logged swarmbox-tool link --user; rc=$?
        [ "$rc" = 0 ] || warn "linking the user tools failed (swarmbox-tool link exit $rc); see serve.log"
    else
        log "step 6: swarmbox-tool is not installed yet (later phase), skipped"
    fi

    # step 7 [W]: the MCP configuration (4.4, later slice), then prepare.sh of every tool (6.3, later phase)
    log "step 7: the MCP registry is not implemented yet (design 4.4), skipped"
    if have swarmbox-tool; then
        log "step 7: swarmbox-tool prepare"
        run_logged swarmbox-tool prepare; rc=$?
        [ "$rc" = 0 ] || warn "preparing the tools failed (swarmbox-tool prepare exit $rc); see serve.log"
    else
        log "step 7: swarmbox-tool is not installed yet, tool preparation skipped"
    fi

    # step 8 [W]: start the nested Podman service and check that it answers
    if [ "$no_nested" = 1 ]; then
        warn "nested Podman service not started (SWARMBOX_TEST_NO_NESTED=1)"
        log "step 8: skipped (no nested Podman)"
    elif ! have podman; then
        warn "nested Podman service not started: podman not found"
    else
        log "step 8: starting the nested Podman service on $SB_PODMAN_SOCK"
        rm -f "$SB_PODMAN_SOCK"
        env -u CONTAINER_HOST podman system service --time=0 "unix://$SB_PODMAN_SOCK" \
            >> "$SB_STATE_DIR/podman-service.log" 2>&1 < /dev/null &
        SVC=$!
        if ! wait_for_service "${SWARMBOX_TEST_SERVICE_WAIT:-10}"; then
            warn "nested Podman service did not start (no socket at $SB_PODMAN_SOCK); see podman-service.log"
        elif ! timeout 5 podman --url "unix://$SB_PODMAN_SOCK" version > /dev/null 2>&1; then
            warn "nested Podman service did not answer on $SB_PODMAN_SOCK; see podman-service.log"
        fi
    fi

    # step 9 [W]: the tmux server with the session main and one idle window
    log "step 9: starting tmux, session main"
    if have tmux; then
        run_logged env -u TMUX tmux new-session -d -s main -n idle; rc=$?
        [ "$rc" = 0 ] || warn "tmux did not start the session main (exit $rc); see serve.log"
    else
        warn "tmux not found; the session main was not created"
    fi

    # step 10 [W]: start and supervise ttyd, when the web terminal is on
    if [ "${SWARMBOX_WEB:-1}" = 0 ]; then
        log "step 10: WEB=0, no web terminal and no supervisor"
    elif ! have swarmbox-web && ! have ttyd; then
        warn "web terminal not started: ttyd not found"
    else
        log "step 10: starting the ttyd supervisor"
        supervise &
        SUP=$!
        printf '%s\n' "$SUP" > "$SB_RUN_DIR/web-supervisor.pid"
    fi

    # step 11 [W]: the readiness marker (ok, or warnings=<n>)
    local marker=ok
    [ "$WARNINGS" -eq 0 ] || marker="warnings=$WARNINGS"
    log "step 11: ready ($marker); pid $$"   # logged first: the marker is what other programs wait for
    if ! { printf '%s\n' "$marker" > "$SB_RUN_DIR/ready.tmp" && mv -f "$SB_RUN_DIR/ready.tmp" "$SB_RUN_DIR/ready"; }; then
        warn "could not write the readiness marker $SB_RUN_DIR/ready"
    fi

    # step 12 [W]: in the background, install the tools listed in WITH, one after another, output to serve.log
    local -a with=()
    local t
    IFS=', ' read -r -a with <<< "${SWARMBOX_WITH:-}"
    if [ "${#with[@]}" -eq 0 ]; then
        log "step 12: WITH is empty, nothing to install, skipped"
    elif ! have swarmbox-tool; then
        log "step 12: swarmbox-tool is not installed yet (later phase), the WITH tools (${with[*]}) skipped"
    else
        log "step 12: installing ${with[*]} in the background"
        (
            for t in "${with[@]}"; do
                [ -n "$t" ] || continue
                if swarmbox-tool install "$t" >> "$SERVE_LOG" 2>&1; then
                    log "installed $t"
                else
                    health_add "installing $t failed (the next call of it retries); see serve.log"
                    log "WARNING: installing $t failed"
                fi
            done
        ) &
        INST=$!
    fi

    # Block on a background sleep, so that a signal handler runs at once (a foreground sleep would delay it, B3).
    while :; do
        sleep infinity &
        wait $!
    done
}

# ---------------------------------------------------------------------------------------------------------------------

case "${1:-}" in
    serve)
        serve
        ;;
    attach)
        shift
        if ! command -v swarmbox-attach > /dev/null 2>&1; then
            echo "swarmbox-entrypoint: swarmbox-attach not found on PATH" >&2
            exit 127
        fi
        exec swarmbox-attach "$@"
        ;;
    init|pubkey|tool|host-helper)
        echo "swarmbox-entrypoint: '$1' is not implemented in this build yet (Phase 2, slice 2.1 placeholder)" >&2
        exit 70
        ;;
    "")
        echo "swarmbox-entrypoint: no command given" >&2
        exit 64
        ;;
    *)
        exec "$@"
        ;;
esac
