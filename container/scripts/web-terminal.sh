#!/bin/bash
# Starts the web terminal (ttyd -> tmux) when the container was created with --web
# (SWARMBOX_WEB is set). Idempotent and safe to call concurrently (init.sh and
# start.sh both call it).
#
# ttyd listens on all interfaces *inside* the container, which is what lets the
# outer port forwarder reach it. start.sh publishes it on the host's 127.0.0.1 only.
#   -W  writable (ttyd is read-only by default)
#   -O  refuse websockets whose Origin differs from the Host: keeps a random web page
#       from driving the terminal through localhost
# Authentication is NOT done here: put it in front (Cloudflare Access).

[ -n "$SWARMBOX_WEB" ] || exit 0

SWARMBOX_DIR="$HOME/.swarmbox"
mkdir -p "$SWARMBOX_DIR"

# Serialize concurrent callers
exec 9>"$SWARMBOX_DIR/web-terminal.lock"
flock 9

if pgrep -u "$(id -u)" -f '^(/usr/local/bin/)?ttyd ' >/dev/null 2>&1; then
    exit 0
fi

# 9>&- keeps ttyd from inheriting (and holding) the lock
nohup setsid ttyd -p 7681 -W -O \
    -t fontSize=14 -t cursorBlink=true -t titleFixed=SwarmBox \
    tmux new -A -s main \
    >"$SWARMBOX_DIR/web-terminal.log" 2>&1 </dev/null 9>&- &
exit 0
