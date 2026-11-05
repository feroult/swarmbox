#!/bin/bash
# Starts the nested Podman API service on a unix socket inside the (bind-mounted) home,
# so the host can drive it with `podman -c <container-name> ...`.
# Idempotent and safe to call concurrently (init.sh and start.sh both call it).

SWARMBOX_DIR="$HOME/.swarmbox"
SOCK="$SWARMBOX_DIR/podman.sock"
mkdir -p "$SWARMBOX_DIR"

# Serialize concurrent callers
exec 9>"$SWARMBOX_DIR/podman-service.lock"
flock 9

# Already running?
if pgrep -u "$(id -u)" -f '^(/usr/bin/)?podman system service' >/dev/null 2>&1; then
    exit 0
fi

# Remove a stale socket from a previous run, then start detached.
# 9>&- keeps the service from inheriting (and holding) the lock.
rm -f "$SOCK"
unset CONTAINER_HOST
nohup setsid podman system service --time=0 "unix://$SOCK" \
    >"$SWARMBOX_DIR/podman-service.log" 2>&1 </dev/null 9>&- &
exit 0
