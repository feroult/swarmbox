#!/bin/bash
# swarmbox-entrypoint: the image's entry point.
#
#   serve     the box's main process: the ordered startup, the readiness marker and health file,
#             PID 1 signal handling, and the supervisors of the bus broker and of the web server
#   attach    forwards to swarmbox-attach (the session of each tab, the idle window, `swarmbox <command>`)
#   install   forwards to swarmbox-install
#   pubkey    forwards to swarmbox-pubkey (the SSH key; `serve` calls it with --ensure at step 5)
#   addon     forwards to swarmbox-addon
#   bus       forwards to swarmbox-bus (the bus broker's command line)
#   tabs      forwards to swarmbox-tabs (the tabs of the box: list, active, screen, send)
#   host-helper
#             writes the helper archive (box:/usr/local/share/swarmbox/host/) as a tar archive on stdout
#   (none)    exit 64
#   anything else is run as given (already the final behavior)
#
# Test-only variables (not in the configuration table and not read by anything else): SWARMBOX_TEST_LIB (folder holding dirs.sh), SWARMBOX_TEST_RUN_DIR (replaces
# /tmp/swarmbox), SWARMBOX_TEST_TUN (replaces /dev/net/tun), SWARMBOX_TEST_PODMAN_RUNROOT and SWARMBOX_TEST_NO_STATE_SOCKET=1 and SWARMBOX_TEST_FALLBACK_SOCK (the state folder cannot hold a socket; where the service listens then), SWARMBOX_TEST_PODMAN_LIBPOD_RUN (the folders serve clears before the nested service), SWARMBOX_TEST_PODMAN_GRAPHROOT (the graph root whose stale fuse-overlayfs marker serve removes), SWARMBOX_TEST_FUSE (replaces /dev/fuse), SWARMBOX_TEST_NO_NESTED=1 (no nested Podman: a warning
# instead of a failure for step 2 and no service at step 8), SWARMBOX_TEST_BACKOFF_SCALE (integer multiplier of the
# backoff of both supervisors, 0 for none), SWARMBOX_TEST_BUS_WAIT (seconds to wait for the bus to answer, default 2), SWARMBOX_TEST_SERVICE_WAIT (seconds to wait for the nested service, default 10), SWARMBOX_TEST_LOG_EVERY (seconds between two looks of the log trimmer, default 300), SWARMBOX_TEST_LOG_MAX (bytes past which it trims a log, default 4194304).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}

# ---------------------------------------------------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------------------------------------------------

EARLY_LOG=""   # log lines written before the state folder exists (steps 0 to 2); flushed at step 3
WARNINGS=0
SUP=""
BUSSUP=""
JANITOR=""
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

# fuse_usable: 0 when /dev/fuse is a character device the agent can open (a box started by hand with --device /dev/fuse), else 1.
fuse_usable() {
    local f=${SWARMBOX_TEST_FUSE:-/dev/fuse}
    [ -c "$f" ] && [ -r "$f" ] && [ -w "$f" ]
}

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

# trim_log FILE MAX: when FILE is bigger than MAX bytes keep its last quarter (the writers append with >>, so they go on at the new end; a line
# written in the instant of the trim may be lost, which a log can bear). Never fails: a disk that is full leaves the file as it was.
trim_log() {
    local f=$1 max=$2 size
    size=$(stat -c %s -- "$f" 2>/dev/null) || return 0
    [ "$size" -gt "$max" ] || return 0
    if tail -c "$((max / 4))" -- "$f" > "$f.trim.$$" 2>/dev/null && cat -- "$f.trim.$$" > "$f" 2>/dev/null; then
        printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "serve: the log was cut to its last $((max / 4)) bytes (limit $max)" >> "$f" 2>/dev/null
    fi
    rm -f -- "$f.trim.$$"
    return 0
}

# log_trimmer: runs in a subshell. The logs of the box (serve.log, bus.log, web-terminal.log, podman-service.log) are written by `>>` redirections of processes that
# stay up for weeks (the web server logs every connection of a browser), so nothing else would ever shorten them.
log_trimmer() {
    local sp=0 f
    trap '[ "$sp" -gt 0 ] && kill "$sp" 2>/dev/null; exit 0' TERM
    while :; do
        sleep "${SWARMBOX_TEST_LOG_EVERY:-300}" &
        sp=$!
        wait "$sp" 2>/dev/null
        for f in "$SERVE_LOG" "$SB_STATE_DIR/bus.log" "$SB_STATE_DIR/web-terminal.log" "$SB_STATE_DIR/podman-service.log"; do
            trim_log "$f" "${SWARMBOX_TEST_LOG_MAX:-4194304}"
        done
    done
}

# stop_children: the web and bus supervisors (which stop the web server and the broker), the installer job, the nested Podman service.
# The multiplexer backend is left to end with the container.
stop_children() {
    local p
    for p in "$SUP" "$BUSSUP" "$INST" "$JANITOR"; do
        if [ -n "$p" ]; then
            kill -TERM "$p" 2>/dev/null
            wait "$p" 2>/dev/null
        fi
    done
    if [ -n "$SVC" ]; then
        kill -TERM "$SVC" 2>/dev/null
        wait "$SVC" 2>/dev/null
    fi
    SUP=""; BUSSUP=""; INST=""; JANITOR=""; SVC=""
    rm -f "${SB_RUN_DIR:-/nonexistent}/web-supervisor.pid" "${SB_RUN_DIR:-/nonexistent}/bus-supervisor.pid" 2>/dev/null
    return 0
}

load_mux() {
    local cand
    for cand in "${SWARMBOX_TEST_MUX_DIR:-}" "$SB_LIB/mux" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/mux"; do
        [ -n "$cand" ] || continue
        if [ -r "$cand/mux.sh" ]; then
            # shellcheck source=/dev/null
            . "$cand/mux.sh"
            return $?
        fi
    done
    return 1
}

on_signal() {
    # $1 signal name, $2 exit status (128 + signal number)
    if [ "$STOPPING" = 0 ]; then
        STOPPING=1
        log "received SIG$1, stopping children"
        stop_children
        if declare -F mux_serve_shutdown_note >/dev/null 2>&1; then
            mux_serve_shutdown_note
        fi
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

# supervise_one NAME HEALTH-LINE LOGFILE RESTART-COMMAND STOP-STATUS COMMAND [ARGS...]: the restart policy of a long-running child
# (the web server, the bus broker). Runs in a subshell. Restarts it after 1, 2, 4 ... 30 s; after 5 exits within 60 s it records HEALTH-LINE and
# idles (alive) until RESTART-COMMAND sends USR1; TERM stops it. A child that exits with STOP-STATUS (empty: none) is not restarted and
# the supervisor ends: someone else runs that service.
supervise_one() {
    local name=$1 line=$2 wlog=$3 hint=$4 stop_rc=$5
    shift 5
    # SUP_PIDFILE (set for this call only): the supervisor writes its own pid there and removes the file when it ends, whatever the reason
    # (a child with STOP-STATUS, a TERM): a pid file that outlives its supervisor would send USR1 to whatever process has that pid later.
    # It writes it itself, so the file cannot be written after the supervisor already left.
    if [ -n "${SUP_PIDFILE:-}" ]; then
        printf '%s\n' "$BASHPID" > "$SUP_PIDFILE" 2>/dev/null
        # shellcheck disable=SC2064  # the path is expanded now, on purpose
        trap "rm -f -- $(printf '%q' "$SUP_PIDFILE")" EXIT
    fi
    local tp=0 sp=0 stop=0 restart=0 delay=1 i rc
    local -a exits=() keep=()
    local scale=${SWARMBOX_TEST_BACKOFF_SCALE:-1}
    # shellcheck disable=SC2317,SC2329  # called from the traps below
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
    while [ "$stop" = 0 ]; do
        if [ "$restart" = 1 ]; then
            restart=0; exits=(); delay=1; health_remove "$line"
            log "$name restarted by hand; crash count reset"
        fi
        "$@" >> "$wlog" 2>&1 < /dev/null &
        tp=$!
        # a signal that arrived before tp was known must still act on this child
        if [ "$restart" = 1 ] || [ "$stop" = 1 ]; then kill "$tp" 2>/dev/null; fi
        rc=0
        while kill -0 "$tp" 2>/dev/null; do wait "$tp" 2>/dev/null; rc=$?; done   # wait returns early when a trap fires
        tp=0
        [ "$stop" = 1 ] && break
        [ "$restart" = 1 ] && continue
        if [ -n "$stop_rc" ] && [ "$rc" = "$stop_rc" ]; then
            log "$name exited with status $rc: another one is running; not restarting"
            break
        fi
        exits+=("$SECONDS")
        keep=()
        for i in "${exits[@]}"; do
            [ $((SECONDS - i)) -lt 60 ] && keep+=("$i")
        done
        exits=("${keep[@]}")
        if [ "${#exits[@]}" -ge 5 ]; then
            health_add "$line"
            log "$name exited 5 times within 60 s: giving up; waiting for '$hint'"
            while [ "$restart" = 0 ] && [ "$stop" = 0 ]; do
                nap infinity
            done
            continue
        fi
        log "$name exited; restarting in $((delay * scale)) s"
        nap "$((delay * scale))"
        delay=$((delay * 2)); [ "$delay" -gt 30 ] && delay=30
    done
    exit 0
}

# wait_for_bus SECONDS: 0 when `swarmbox-bus ping` answers, 1 when the time ran out or the supervisor is gone.
wait_for_bus() {
    local n=$(( $1 * 5 ))
    while [ "$n" -gt 0 ]; do
        SB_BUS_SOCKET=$SB_BUS_SOCK swarmbox-bus ping > /dev/null 2>&1 && return 0
        kill -0 "$BUSSUP" 2>/dev/null || return 1
        sleep 0.2
        n=$((n - 1))
    done
    SB_BUS_SOCKET=$SB_BUS_SOCK swarmbox-bus ping > /dev/null 2>&1
}

# socket_works_in DIR: 0 when a unix socket can be bound (and removed) in DIR. SWARMBOX_TEST_NO_STATE_SOCKET=1 says no (tests).
socket_works_in() {
    [ "${SWARMBOX_TEST_NO_STATE_SOCKET:-0}" = 1 ] && return 1
    local probe="$1/.socket-probe.$$"
    python3 -c 'import socket, sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' "$probe" 2>/dev/null
    local rc=$?
    rm -f "$probe" 2>/dev/null
    return $rc
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
    SB_BUS_SOCK=$SB_RUN_DIR/bus.sock   # dirs.sh's value, recomputed because the test switch may have moved the run folder
    SERVE_LOG=$SB_STATE_DIR/serve.log
    local tun=${SWARMBOX_TEST_TUN:-/dev/net/tun}
    local no_nested=${SWARMBOX_TEST_NO_NESTED:-0}
    local rc probe

    # PID 1: handlers first, so that `podman stop` ends the box promptly at any point
    trap 'on_signal TERM 143' TERM
    trap 'on_signal INT 130' INT

    # step 0 [-]: delete the readiness marker and every exit.* file, before anything else (second defense after the tmpfs)
    # After a host reboot the run folder has come back as a folder the agent cannot write: no ready marker, no web supervisor pid file, and
    # `swarmbox` waited for a marker that could not appear. The agent has sudo without a password, so make the folder writable first.
    if [ -d "$SB_RUN_DIR" ] && [ ! -w "$SB_RUN_DIR" ] && have sudo; then
        if sudo -n chmod 1777 "$SB_RUN_DIR" 2>/dev/null; then
            log "step 0: $SB_RUN_DIR was not writable by $(id -un); made it writable (mode 1777)"
        fi
    fi
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
    if ! mkdir -p "$SB_CONFIG_DIR" "$SB_DATA_DIR" "$SB_STATE_DIR" "$SB_ADDONS_DIR" "$SB_SHIMS_DIR" "$SB_LOG_DIR" "$SB_RUN_DIR" 2>/dev/null; then
        fatal "cannot create the SwarmBox folders under $HOME and $SB_RUN_DIR"
    fi
    : > "$SB_HEALTH_FILE" 2>/dev/null || fatal "cannot create $SB_HEALTH_FILE"   # cleared at every start
    printf '%s' "$EARLY_LOG" >> "$SERVE_LOG" 2>/dev/null
    EARLY_LOG=""
    log "step 3: folders created; health file cleared"
    if [ "${NOTUN:-0}" = 1 ]; then
        warn "nested Podman needs /dev/net/tun ($tun is missing; SWARMBOX_TEST_NO_NESTED=1)"
    fi

    # step 5 [W]: ensure the SSH key
    log "step 5: ensuring the SSH key"
    run_logged swarmbox-pubkey --ensure; rc=$?
    [ "$rc" = 0 ] || warn "could not create the Git SSH key (swarmbox-pubkey exit $rc); see serve.log"

    # step 6 [W]: link the user-level addons: shims and index in the workspace
    log "step 6: swarmbox-addon link --user"
    run_logged swarmbox-addon link --user; rc=$?
    [ "$rc" = 0 ] || warn "linking the user addons failed (swarmbox-addon link exit $rc); see serve.log"

    # step 6b [W]: the bus broker, supervised, before step 7 because the prepare.sh of an addon may start subscribers and publishers.
    # It needs only the run folder (step 3): the bus knows nothing about the multiplexer. Nothing of the box depends on it.
    if ! have swarmbox-bus; then
        warn "the bus was not started: swarmbox-bus not found"
    else
        log "step 6b: starting the bus broker supervisor"
        SUP_PIDFILE="$SB_RUN_DIR/bus-supervisor.pid" supervise_one bus "the bus keeps crashing; see bus.log" "$SB_STATE_DIR/bus.log" "swarmbox-bus restart" 8 \
            env "SB_BUS_SOCKET=$SB_BUS_SOCK" swarmbox-bus serve &
        BUSSUP=$!
        wait_for_bus "${SWARMBOX_TEST_BUS_WAIT:-2}" || warn "the bus did not answer on $SB_BUS_SOCK; see bus.log"
    fi

    # step 7 [W]: the MCP configuration (swarmbox-mcp), then prepare.sh of every addon
    # The claude alias passes --mcp-config <workspace>/.claude/mcp-servers.json and claude refuses a missing file, so when the
    # generator is missing or fails before it wrote anything, an empty valid list is left where there is none.
    log "step 7: swarmbox-mcp generate"
    run_logged swarmbox-mcp generate; rc=$?
    [ "$rc" = 0 ] || warn "generating the MCP configuration failed or was incomplete (swarmbox-mcp exit $rc); see serve.log"
    if [ ! -e "$HOME/.claude/mcp-servers.json" ]; then
        if mkdir -p "$HOME/.claude" 2>/dev/null && printf '{"mcpServers": {}}\n' > "$HOME/.claude/mcp-servers.json.tmp" \
            && mv -f "$HOME/.claude/mcp-servers.json.tmp" "$HOME/.claude/mcp-servers.json"; then
            log "step 7: left an empty mcp-servers.json"
        else
            rm -f "$HOME/.claude/mcp-servers.json.tmp"
            warn "could not write $HOME/.claude/mcp-servers.json; the claude alias may refuse to start"
        fi
    fi
    log "step 7: swarmbox-addon prepare"
    # prepare prints one "prepare-failed: <addon>: <reason>" line per failing addon; each becomes one W line (health line),
    # and a failure with no such line (the command itself failed) is one generic W line.
    prep_out=$(mktemp "${TMPDIR:-/tmp}/swarmbox-prepare.XXXXXX" 2>/dev/null) || prep_out=/dev/null
    swarmbox-addon prepare > "$prep_out" 2>&1; rc=$?
    [ "$prep_out" = /dev/null ] || cat "$prep_out" >> "$SERVE_LOG" 2>/dev/null
    nfail=0
    if [ "$prep_out" != /dev/null ]; then
        while IFS= read -r pline; do
            case "$pline" in
                "prepare-failed: "*)
                    nfail=$((nfail + 1))
                    warn "preparing ${pline#prepare-failed: } (see serve.log)" ;;
            esac
        done < "$prep_out"
        rm -f "$prep_out"
    fi
    if [ "$rc" != 0 ] && [ "$nfail" = 0 ]; then
        warn "preparing the addons failed (swarmbox-addon prepare exit $rc); see serve.log"
    fi

    # step 8 [W]: start the nested Podman service and check that it answers
    if [ "$no_nested" = 1 ]; then
        warn "nested Podman service not started (SWARMBOX_TEST_NO_NESTED=1)"
        log "step 8: skipped (no nested Podman)"
    elif ! have podman; then
        warn "nested Podman service not started: podman not found"
    else
        # The nested Podman keeps its runtime state in /tmp/storage-run-<uid>, which is in the box's own filesystem, not in a tmpfs. After a
        # host reboot it still holds the old boot ID and Podman refuses to start ("an unhandled reboot has occurred"). Nothing of a previous
        # run is alive when serve starts, so remove it, as the Podman message itself says to do.
        runroot=${SWARMBOX_TEST_PODMAN_RUNROOT:-/tmp/storage-run-$(id -u)}
        # Podman keeps a second runtime folder, the one its own message names ("delete /tmp/podman-run-1000/containers and /tmp/podman-run-1000/libpod/tmp"):
        # with no XDG_RUNTIME_DIR it is /tmp/podman-run-<uid>, and it holds the boot ID too. Both go.
        libpodrun=${SWARMBOX_TEST_PODMAN_LIBPOD_RUN:-/tmp/podman-run-$(id -u)}
        for stale in "$runroot" "$libpodrun"; do
            if [ -e "$stale" ]; then
                rm -rf "$stale" 2>/dev/null && log "step 8: removed the runtime state of the previous run of nested Podman ($stale)"
            fi
        done
        # The box is created without /dev/fuse (the host script passes /dev/net/tun only), so the only overlay that can work is the kernel's own
        # (rootless, kernel 5.13+). But fuse-overlayfs is on the PATH, and Podman falls back to it when its probe of native overlay says "no": that
        # answer is cached in the runtime folder, which is shared by every graph root of this user (one `podman --root /tmp/x ...`, or a run with
        # another HOME, on a file system that cannot do native overlay is enough to cache "no" for the real graph root), and the fallback leaves
        # $graphroot/overlay/.has-mount-program = true, which is never revisited. From then on every run fails with "fuse: device not found".
        # The runtime folder was removed above; this removes the other half of the poison when there is no usable /dev/fuse. With /dev/fuse
        # nothing is touched (a marker there is legitimate).
        if ! fuse_usable; then
            local fuse_marker=${SWARMBOX_TEST_PODMAN_GRAPHROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/containers/storage}/overlay/.has-mount-program
            if [ -f "$fuse_marker" ] && [ "$(cat "$fuse_marker" 2>/dev/null)" = true ]; then
                if rm -f "$fuse_marker" 2>/dev/null; then
                    log "step 8: no usable /dev/fuse: removed the stale marker $fuse_marker (it made Podman use fuse-overlayfs); native overlay is tried again"
                else
                    log "step 8: no usable /dev/fuse and the stale marker $fuse_marker could not be removed"
                fi
            fi
        fi
        # The state folder is in the workspace, and on macOS the workspace is a virtiofs share that cannot hold a unix socket: a stale socket there cannot be
        # seen or removed ("Operation not supported") and Podman cannot bind a new one, so the service never started. When a socket cannot be made in
        # the folder, the service listens on the box's own disk instead (the host reaches no socket through the macOS VM anyway).
        if ! socket_works_in "$SB_STATE_DIR"; then
            SB_PODMAN_SOCK=${SWARMBOX_TEST_FALLBACK_SOCK:-/tmp/swarmbox-podman-$(id -u).sock}
            log "step 8: the state folder cannot hold a unix socket (a shared drive of the host): the nested Podman service uses $SB_PODMAN_SOCK"
        fi
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

    # step 9 [W]: start the multiplexer daemon (herdr-core)
    if load_mux; then
        mux_serve_init
    else
        warn "multiplexer backend '${SWARMBOX_MUX:-herdr}' could not be loaded; see serve.log"
    fi

    # step 10 [W]: start and supervise the web server (the herdr Web Studio), when the web terminal is on
    if [ "${SWARMBOX_WEB:-1}" = 0 ]; then
        log "step 10: WEB=0, no web terminal and no supervisor"
    else
        log "step 10: starting the web supervisor"
        supervise_one web "web terminal keeps crashing; see web-terminal.log" "$SB_STATE_DIR/web-terminal.log" "swarmbox-web restart" "" \
            swarmbox-web run &
        SUP=$!
        printf '%s\n' "$SUP" > "$SB_RUN_DIR/web-supervisor.pid"
    fi

    # the log trimmer (not a numbered step: it only keeps the logs from growing for ever)
    log_trimmer &
    JANITOR=$!

    # step 11 [W]: the readiness marker (ok, or warnings=<n>)
    local marker=ok
    [ "$WARNINGS" -eq 0 ] || marker="warnings=$WARNINGS"
    log "step 11: ready ($marker); pid $$"   # logged first: the marker is what other programs wait for
    if ! { printf '%s\n' "$marker" > "$SB_RUN_DIR/ready.tmp" && mv -f "$SB_RUN_DIR/ready.tmp" "$SB_RUN_DIR/ready"; }; then
        warn "could not write the readiness marker $SB_RUN_DIR/ready"
    fi

    # step 12 [W]: in the background, install the addons listed in WITH, one after another, output to serve.log
    local -a with=()
    local t
    IFS=', ' read -r -a with <<< "${SWARMBOX_WITH:-}"
    if [ "${#with[@]}" -eq 0 ]; then
        log "step 12: WITH is empty, nothing to install, skipped"
    else
        log "step 12: installing ${with[*]} in the background"
        (
            for t in "${with[@]}"; do
                [ -n "$t" ] || continue
                if swarmbox-addon install "$t" >> "$SERVE_LOG" 2>&1; then
                    log "installed $t"
                else
                    health_add "installing $t failed (the next call of it retries); see serve.log"
                    log "WARNING: installing $t failed"
                fi
            done
        ) &
        INST=$!
    fi

    # Block on a background sleep, so that a signal handler runs at once (a foreground sleep would delay it).
    while :; do
        sleep infinity &
        wait $!
    done
}

# ---------------------------------------------------------------------------------------------------------------------

# forward <program> [args...]: replace this process with a program of the image (an exec: the exit status and the signals are
# the program's own). A missing program is 127, named, so a build that lacks it fails loudly.
forward() {
    local prog=$1
    shift
    if ! command -v "$prog" > /dev/null 2>&1; then
        echo "swarmbox-entrypoint: $prog not found on PATH" >&2
        exit 127
    fi
    exec "$prog" "$@"
}

# host-helper: the helper archive as a tar archive on stdout, nothing else on stdout. `swarmbox setup` and `swarmbox update`
# save it to a file and unpack it on the host; owner 0 and the file modes are kept, so `swarmbox-host` stays executable.
host_helper() {
    local dir=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}
    if [ $# -ne 0 ]; then
        echo "usage: swarmbox-entrypoint host-helper" >&2
        exit 64
    fi
    if [ ! -d "$dir" ]; then
        echo "swarmbox-entrypoint host-helper: the helper folder $dir does not exist in this image" >&2
        exit 1
    fi
    exec tar --owner=0 --group=0 --numeric-owner -C "$dir" -cf - .
}

case "${1:-}" in
    serve)
        serve
        ;;
    attach|install|pubkey|addon|bus|tabs|pins|worktree)
        sub=$1
        shift
        case "$sub" in
            attach) forward swarmbox-attach "$@" ;;
            install) forward swarmbox-install "$@" ;;
            pubkey) forward swarmbox-pubkey "$@" ;;
            addon) forward swarmbox-addon "$@" ;;
            bus) forward swarmbox-bus "$@" ;;
            tabs) forward swarmbox-tabs "$@" ;;
            pins) forward swarmbox-pins "$@" ;;
            worktree) forward swarmbox-worktree "$@" ;;
        esac
        ;;
    host-helper)
        shift
        host_helper "$@"
        ;;
    "")
        echo "swarmbox-entrypoint: no command given" >&2
        exit 64
        ;;
    *)
        exec "$@"
        ;;
esac
