#!/bin/bash
# swarmbox-web (installed as /usr/local/bin/swarmbox-web).
#
#   swarmbox-web run       what the web supervisor of `serve` runs: the herdr Web Studio (container/web/herdr/server.mjs) on the web port,
#                          through the multiplexer backend (mux_web_run in container/scripts/mux/herdr.sh)
#   swarmbox-web restart   make the supervisor start the web server again (SIGUSR1 to the PID in box:/tmp/swarmbox/web-supervisor.pid);
#                          the box and its terminals stay up
#
# The web server listens on every interface INSIDE the box (the published port is what limits it to the host's 127.0.0.1), port 7681.
#
# The voice front. When the `voice` addon is really installed (`swarmbox-addon where voice swarmbox-voice`, which is false for the bare
# shim) and SWARMBOX_VOICE_WEB is not 0 (the setting voice.web), `run` execs `swarmbox-voice front` in front of the web server: the front owns
# the web port, serves /voice/health and /voice/audio itself (the microphone of the Web Studio) and pipes everything else to the server on
# 127.0.0.1:7680. Otherwise the web server is on the web port.
#
# Test-only variables (not in the configuration table): SWARMBOX_TEST_LIB (folder with dirs.sh), SWARMBOX_TEST_MUX_DIR (folder with mux.sh),
# SWARMBOX_TEST_RUN_DIR (replaces /tmp/swarmbox), SWARMBOX_TEST_WEB_PORT (replaces 7681), SWARMBOX_TEST_WEB_IFACE (the address the web
# server, or the front, listens on), SWARMBOX_TEST_WEB_SERVER_PORT (the port of the web server behind the front, default 7680),
# SWARMBOX_TEST_VOICE_PORT (the port of the voice service, default 17682).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}

usage() { echo "usage: swarmbox-web run | restart" >&2; exit 64; }
die() { echo "swarmbox-web: $*" >&2; exit "${2:-1}"; }

[ $# -eq 1 ] || usage
case "$1" in run|restart) ;; *) usage ;; esac
MODE=$1

# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || die "cannot read $SB_LIB/dirs.sh"
SB_RUN_DIR=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}

# ---------------------------------------------------------------------------------------------------------------------
if [ "$MODE" = restart ]; then
    pidfile=$SB_RUN_DIR/web-supervisor.pid
    [ -r "$pidfile" ] || die "no web terminal supervisor is running (no $pidfile; is the web terminal off, WEB=0, or is serve not running?)"
    read -r pid < "$pidfile"
    case "$pid" in
        ''|*[!0-9]*) die "$pidfile does not hold a process number" ;;
    esac
    [ "$pid" -gt 1 ] || die "$pidfile holds $pid, which is not a supervisor"
    kill -0 "$pid" 2>/dev/null || die "the web terminal supervisor (process $pid) is not running"
    kill -USR1 "$pid" 2>/dev/null || die "could not signal the web terminal supervisor (process $pid)"
    echo "swarmbox-web: asked the supervisor (process $pid) to restart the web terminal"
    exit 0
fi

# voice_front_bin: prints the real swarmbox-voice when the front is to be used, else nothing. One place for the rule: the setting is on and
# the addon is installed (swarmbox-addon decides, with the same logic as everywhere else) and carries the front.
voice_front_bin() {
    [ "${SWARMBOX_VOICE_WEB:-1}" = 0 ] && return 0
    local real prefix
    real=$(swarmbox-addon where voice swarmbox-voice 2>/dev/null) || return 0
    prefix=${real%/bin/swarmbox-voice}
    [ "$prefix" != "$real" ] || return 0
    [ -f "$prefix/lib/swarmbox_voice/front.py" ] || return 0
    printf '%s' "$real"
}
VOICE_BIN=$(voice_front_bin)

# Load the multiplexer backend (herdr): its mux_web_run owns the web server.
for _sb_mc in "${SWARMBOX_TEST_MUX_DIR:-}" "$SB_LIB/mux" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mux"; do
    [ -n "$_sb_mc" ] || continue
    if [ -r "$_sb_mc/mux.sh" ]; then
        # shellcheck source=/dev/null
        . "$_sb_mc/mux.sh" || exit $?
        break
    fi
done
unset _sb_mc

# UTF-8 locale: shells and web terminals need it so accented characters are never dropped.
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
    *)
        export LANG=C.UTF-8
        [ -n "${LC_ALL:-}" ] && export LC_ALL=C.UTF-8
        ;;
esac

declare -F mux_web_run > /dev/null 2>&1 || die "the multiplexer backend has no web server (mux_web_run)" 127
mux_web_run "${SWARMBOX_TEST_WEB_PORT:-7681}" "${SWARMBOX_TEST_WEB_IFACE:-0.0.0.0}" "$VOICE_BIN"
exit $?

