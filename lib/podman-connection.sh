# Sourced by start.sh (needs msg_detail/msg_warn from ui.sh, and CONTAINER_NAME, WORK_DIR).
# Start the nested Podman API service and make sure the host has a connection to it,
# so `podman -c <container-name> ps` works from the host shell.
register_podman_connection() {
    # Unix sockets do not cross the macOS VM boundary
    [[ "$OSTYPE" == "darwin"* ]] && return
    local uri="unix://$WORK_DIR/.swarmbox/podman.sock"
    local current
    current=$(podman system connection list --format '{{.Name}} {{.URI}}' 2>/dev/null \
        | awk -v n="$CONTAINER_NAME" '$1==n {print $2}')
    if [ "$current" = "$uri" ]; then
        return
    fi
    if [ -n "$current" ]; then
        podman system connection remove "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    if podman system connection add "$CONTAINER_NAME" "$uri" >/dev/null 2>&1; then
        msg_detail "Podman connection registered: podman -c $CONTAINER_NAME ps"
    else
        msg_warn "Could not register podman connection '$CONTAINER_NAME'"
    fi
}
