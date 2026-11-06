# Sourced by start.sh: the web terminal (--web) and its Cloudflare connector
# (needs ui.sh, and CONTAINER_NAME, WEB, WEB_PORT, WEB_PORT_GIVEN).
# Make sure the Cloudflare tunnel is up for --web. The connector is a Podman container on THIS host (never
# inside SwarmBox, so the tunnel token stays out of the agent's reach). Keep the name and flags in sync
# with cloudflare-setup.py (CONNECTOR_NAME, step_connector).
#   - SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN set (the tunnel's own token, from the Cloudflare dashboard): that
#     is the source of truth. A missing connector is created, a stopped one started, and one that holds a
#     different token (e.g. after rotating it) is recreated.
#   - not set: an existing connector is only started if stopped (e.g. one that cloudflare-setup.py made).
# No API token is ever needed here. The token travels in the environment, never on a command line, and is
# never printed.
ensure_web_connector() {
    local name="swarmbox-cloudflared" image="${SWARMBOX_CLOUDFLARED_IMAGE:-docker.io/cloudflare/cloudflared:latest}"
    local token="$SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN" state have_token
    state=$(podman inspect -f '{{.State.Status}}' "$name" 2>/dev/null) || state=""

    if [ -n "$state" ] && [ -n "$token" ]; then
        have_token=$(podman inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$name" 2>/dev/null \
            | grep -x -F "TUNNEL_TOKEN=$token" || true)
        if [ -z "$have_token" ]; then
            msg_detail "Cloudflare connector holds a different token: recreating it"
            podman rm -f "$name" >/dev/null 2>&1 || true
            state=""
        fi
    fi

    case "$state" in
        running)
            msg_detail "Cloudflare connector: running"
            ;;
        "")
            if [ -n "$token" ]; then
                local out
                if out=$(TUNNEL_TOKEN="$token" podman run -d --name "$name" --restart=always --network=host \
                        --user root -e TUNNEL_TOKEN "$image" tunnel --no-autoupdate run 2>&1); then
                    msg_detail "Cloudflare connector: created and started ($name)"
                else
                    msg_warn "Could not create the Cloudflare connector '$name':"
                    printf '%s\n' "$out" | tail -n 3 | sed 's/^/    /' >&2
                fi
            elif [ -n "$SWARMBOX_WEB_HOSTNAME$SWARMBOX_WEB_DOMAIN" ]; then
                # only mention it to people who seem to be using remote access
                msg_detail "No Cloudflare connector '$name' on this host: set SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN"
                msg_detail "(the tunnel's token, from the Cloudflare dashboard) or run ./cloudflare-setup.py once"
            fi
            ;;
        *)
            if podman start "$name" >/dev/null 2>&1; then
                msg_detail "Cloudflare connector: started ($name)"
            else
                msg_warn "Could not start the Cloudflare connector '$name' (podman logs $name)"
            fi
            ;;
    esac
}

# Start the web terminal (when requested) and wait until it answers on the published port.
start_web_terminal() {
    [ "$WEB" = "true" ] || return 0
    podman exec -d "$CONTAINER_NAME" /usr/local/bin/swarmbox-web-terminal >/dev/null 2>&1 || true
    ensure_web_connector
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if (exec 3<>"/dev/tcp/127.0.0.1/$WEB_PORT") 2>/dev/null; then
            msg_detail "Web terminal: http://127.0.0.1:$WEB_PORT (no login here; reach it remotely only through Cloudflare Access)"
            # The URL cloudflare-setup.py provisioned: an explicit hostname, or <container>.<domain>
            local public_host="${SWARMBOX_WEB_HOSTNAME:-${SWARMBOX_WEB_DOMAIN:+$CONTAINER_NAME.$SWARMBOX_WEB_DOMAIN}}"
            [ -n "$public_host" ] && msg_detail "Public URL: https://$public_host (once the tunnel routes it to localhost:$WEB_PORT)"
            return 0
        fi
        sleep 0.5
    done
    msg_warn "Web terminal did not start (is the image up to date? run ./build.sh and --reset)"
}

# Was the existing container created with --web? (it carries SWARMBOX_WEB=1 and publishes 7681)
container_has_web() {
    podman inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER_NAME" 2>/dev/null | grep -qx 'SWARMBOX_WEB=1'
}

# Host port the existing container publishes the web terminal on (empty if none)
container_web_port() {
    podman inspect -f '{{with index .HostConfig.PortBindings "7681/tcp"}}{{(index . 0).HostPort}}{{end}}' \
        "$CONTAINER_NAME" 2>/dev/null
}

# For an existing container that has the web terminal, --web is not an "ignored creation option": it is
# what the container already is. Treat the container as a web one even without the flag, so reattaching
# also makes sure the terminal and the Cloudflare tunnel are up (e.g. after the machine restarted), and
# use the port it really publishes.
adopt_existing_web() {
    container_has_web || return 0
    local port
    port=$(container_web_port)
    if [ "$WEB_PORT_GIVEN" = "true" ] && [ -n "$port" ] && [ "$port" != "$WEB_PORT" ]; then
        msg_warn "This container already publishes the web terminal on port $port (not $WEB_PORT); using $port."
        msg_warn "To change it, re-run with --reset."
    fi
    [ -n "$port" ] && WEB_PORT="$port"
    WEB=true
}
