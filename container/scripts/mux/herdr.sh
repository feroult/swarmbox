#!/bin/bash
# herdr.sh: the herdr-core (hc) multiplexer backend for SwarmBox (loaded by mux.sh; the only backend).
#
# All herdr-core lifecycle, config seeding, terminal attach, command wrapper and native web gateway
# dispatch live here so the core scripts never invoke hc or herdr directly.

_SB_HERDR_HC=${SWARMBOX_TEST_HC_BIN:-hc}
_SB_HERDR_WEB=${SWARMBOX_TEST_HERDR_WEB:-/usr/local/share/swarmbox/herdr-web/server.mjs}
_SB_HERDR_COCKPIT=${SWARMBOX_TEST_HERDR_COCKPIT:-/usr/local/share/swarmbox/herdr-web/cockpit.mjs}
_SB_HERDR_THEME_SRC=${SWARMBOX_TEST_HERDR_CONFIG:-/etc/swarmbox/herdr.toml}

mux_available() {
    command -v "$_SB_HERDR_HC" > /dev/null 2>&1
}

_herdr_config_root() {
    local cfg=${XDG_CONFIG_HOME:-}
    case "$cfg" in
        /*) printf '%s' "${cfg%/}" ;;
        *)  printf '%s' "${HOME}/.config" ;;
    esac
}

# Seed default Purple Glow config for herdr TUI and clean defaults for herdr-core once,
# never overwriting existing user files.
_herdr_seed_config() {
    local cfg_root herdr_dir core_dir
    cfg_root=$(_herdr_config_root)
    herdr_dir="$cfg_root/herdr"
    core_dir="$cfg_root/herdr-core"
    if [ -r "$_SB_HERDR_THEME_SRC" ] && [ ! -e "$herdr_dir/config.toml" ]; then
        mkdir -p "$herdr_dir" 2>/dev/null || true
        cp "$_SB_HERDR_THEME_SRC" "$herdr_dir/config.toml" 2>/dev/null || true
    fi
    if [ ! -e "$core_dir/config.toml" ]; then
        mkdir -p "$core_dir" 2>/dev/null || true
        cat > "$core_dir/config.toml" 2>/dev/null <<'EOF' || true
# SwarmBox herdr-core defaults. Edit freely; SwarmBox never overwrites this file.
notes = false
shell = ["/bin/bash", "-l"]
EOF
    fi
}

_herdr_ensure_server() {
    "$_SB_HERDR_HC" server status --json > /dev/null 2>&1 && return 0
    "$_SB_HERDR_HC" server start > /dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        "$_SB_HERDR_HC" server status --json > /dev/null 2>&1 && return 0
        sleep 0.15
    done
    return 1
}

_herdr_live_count() {
    local out sysop_out total hidden count
    out=$("$_SB_HERDR_HC" ls --json 2>/dev/null) || { printf '0'; return 0; }
    total=$(printf '%s' "$out" | grep -o '"state"[[:space:]]*:[[:space:]]*"live"' | wc -l | tr -d '[:space:]')
    sysop_out=$("$_SB_HERDR_HC" ls --json --label swarmbox.role=sysop 2>/dev/null) || sysop_out=""
    hidden=$(printf '%s' "$sysop_out" | grep -o '"state"[[:space:]]*:[[:space:]]*"live"' | wc -l | tr -d '[:space:]')
    count=$(( ${total:-0} - ${hidden:-0} ))
    [ "$count" -lt 0 ] && count=0
    printf '%s' "$count"
}

_herdr_extract_address() {
    # Extract "address":"t1" from a single JSON object on stdin without requiring jq.
    sed -n 's/.*"address"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

_herdr_record_active() {
    local addr=$1 run_dir=${SB_RUN_DIR:-/tmp/swarmbox}
    [ -n "$addr" ] || return 0
    mkdir -p "$run_dir" 2>/dev/null || true
    printf '%s\n' "$addr" > "$run_dir/herdr-active-tab" 2>/dev/null || true
}

_herdr_ensure_initial_tab() {
    local count cwd json addr pins_bin pins_out has_pins=0 boot_flag=${1:-}
    pins_bin=${SWARMBOX_TEST_PINS_BIN:-swarmbox-pins}
    if command -v "$pins_bin" > /dev/null 2>&1; then
        if [ "$boot_flag" = "--boot" ]; then
            pins_out=$("$pins_bin" restore --boot 2>/dev/null) || pins_out=""
        else
            pins_out=$("$pins_bin" restore 2>/dev/null) || pins_out=""
        fi
        case "$pins_out" in
            *'"total_pins": 0'*|*'"total_pins":0'*|'') ;;
            *'"total_pins"'*) has_pins=1 ;;
        esac
    fi
    count=$(_herdr_live_count)
    # Only spawn a fallback login shell when no terminals are live AND the user has no saved pins
    # (when pinned sessions exist and are all parked, stay at 0 shells so waking a pin leaves no stray shell).
    if [ "${count:-0}" -eq 0 ] && [ "$has_pins" -eq 0 ]; then
        cwd=${HOME:-/home/agent}
        json=$("$_SB_HERDR_HC" run --bg --keep --no-parent --name shell --cwd "$cwd" -- /bin/bash -l 2>/dev/null) || true
        addr=$(printf '%s' "$json" | _herdr_extract_address)
        [ -n "$addr" ] && _herdr_record_active "$addr"
    fi
}

mux_serve_init() {
    local rc
    log "step 9: starting herdr-core daemon"
    _herdr_seed_config
    if have "$_SB_HERDR_HC"; then
        run_logged "$_SB_HERDR_HC" server start
        rc=$?
        if [ "$rc" != 0 ] && ! _herdr_ensure_server; then
            warn "herdr-core did not start (exit $rc); see serve.log"
            return 0
        fi
        _herdr_ensure_initial_tab --boot
    else
        warn "hc (herdr-core) not found; background terminal daemon was not started"
    fi
}

mux_serve_shutdown_note() {
    log "leaving the herdr-core daemon to end with the container"
}

# mux_web_run PORT IFACE VOICE_BIN: launch the native SwarmBox × herdr-core Web Gateway.
# When the voice addon is installed, swarmbox-voice front sits in front of server.mjs,
# serving /voice/* and piping all other HTTP and WebSocket traffic byte-for-byte.
mux_web_run() {
    local port=$1 iface=$2 voice_bin=$3
    _herdr_seed_config
    _herdr_ensure_server || die "herdr-core server is not answering" 1
    _herdr_ensure_initial_tab
    [ -x "$_SB_HERDR_WEB" ] || die "herdr web gateway not found or not executable at $_SB_HERDR_WEB" 127
    if [ -n "$voice_bin" ]; then
        local -a front_args=(front --listen "$iface:$port" --server-port "${SWARMBOX_TEST_WEB_SERVER_PORT:-7680}")
        [ -n "${SWARMBOX_TEST_VOICE_PORT:-}" ] && front_args+=(--service-listen "127.0.0.1:$SWARMBOX_TEST_VOICE_PORT")
        exec "$voice_bin" "${front_args[@]}" -- "$_SB_HERDR_WEB" -p "$port" -i "$iface"
    fi
    exec "$_SB_HERDR_WEB" -p "$port" -i "$iface"
}

mux_attach_web() {
    _herdr_seed_config
    _herdr_ensure_server || die "herdr-core could not start"
    _herdr_ensure_initial_tab
    export SWARMBOX_WEB_CLIENT=1
    exec "$_SB_HERDR_HC" attach
}

mux_attach_interactive() {
    _herdr_seed_config
    _herdr_ensure_server || die "herdr-core could not start"
    _herdr_ensure_initial_tab
    if [ "${SWARMBOX_HERDR_RAW:-0}" != "1" ] && [ -x "$_SB_HERDR_COCKPIT" ]; then
        exec "$_SB_HERDR_COCKPIT"
    fi
    local json addr
    json=$("$_SB_HERDR_HC" run --bg --keep --no-parent --cwd "$PWD" -- /bin/bash -l 2>/dev/null) || die "herdr-core could not open a terminal"
    addr=$(printf '%s' "$json" | _herdr_extract_address)
    [ -n "$addr" ] || die "herdr-core did not return a terminal address"
    _herdr_record_active "$addr"
    exec "$_SB_HERDR_HC" attach "$addr"
}

# Command wrapper run inside a herdr-core terminal: preserves interactive TTY and records exit code.
read -r -d '' _SB_HERDR_WRAPPER <<'EOF' || true
sb_status=$2
trap 'kill "$sb_pid" 2>/dev/null; echo 129 > "$sb_status.tmp" && mv "$sb_status.tmp" "$sb_status"; exit 129' HUP TERM
exec 3<&0
bash -ic "$1" <&3 3<&- &
sb_pid=$!
wait "$sb_pid"
sb_rc=$?
trap - HUP TERM
echo "$sb_rc" > "$sb_status.tmp" && mv "$sb_status.tmp" "$sb_status"
exit "$sb_rc"
EOF

mux_attach_command() {
    local cmd_q=$1
    local run_dir=${SB_RUN_DIR:-/tmp/swarmbox}
    local id status json addr rc
    _herdr_seed_config
    _herdr_ensure_server || die "herdr-core could not start"
    mkdir -p "$run_dir" 2>/dev/null || true
    id="$(date +%s%N)p$$"
    status="$run_dir/herdr-exit.$id"
    rm -f "$status" "$status.tmp"
    json=$("$_SB_HERDR_HC" run --bg --no-parent --cwd "$PWD" -- bash -c "$_SB_HERDR_WRAPPER" wrapper "$cmd_q" "$status" 2>/dev/null) \
        || die "herdr-core could not open a terminal"
    addr=$(printf '%s' "$json" | _herdr_extract_address)
    [ -n "$addr" ] || die "herdr-core did not return a terminal address"
    _herdr_record_active "$addr"

    "$_SB_HERDR_HC" attach "$addr" || true

    # Wait briefly for the status file to flush if the command just finished.
    for _ in 1 2 3 4 5; do
        [ -s "$status" ] && break
        sleep 0.1
    done
    if [ ! -s "$status" ]; then
        rm -f "$status" "$status.tmp"
        echo "swarmbox: detached; the command keeps running in terminal $addr" >&2
        exit 0
    fi
    rc=$(cat "$status" 2>/dev/null)
    rm -f "$status" "$status.tmp"
    "$_SB_HERDR_HC" rm "$addr" > /dev/null 2>&1 || true
    case "$rc" in
        ''|*[!0-9]*) die "the command's status is lost; exit status unknown" 1 ;;
    esac
    exit "$rc"
}
