#!/bin/bash

# Messaging utilities - sober design
msg() { echo -e "\033[0;37m${1}\033[0m"; }
msg_detail() { echo -e "\033[0;90m  ${1}\033[0m"; }
msg_warn() { echo -e "\033[0;90m${1}\033[0m"; }

# Podman-only runtime (Docker support removed)
RUNTIME="podman"

# Directory of this script (the build context), regardless of the current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
IMAGE_NAME="swarmbox"
CONTAINER_NAME="swarmbox"
WORK_DIR="$(pwd)/.work"
PORTS=""
IPORTS=""
RESET=false
CUSTOM_NAME=""
CUSTOM_IMAGE=""
CUSTOM_HOSTNAME="swarmbox"
HOSTNAME_GIVEN=false
NO_SHELL=false
HOST_NETWORK=false
ENV_KEYS=""
BROWSER_URL=""
CLASP=false
WEB=false
WEB_PORT=7681
WEB_PORT_GIVEN=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --ports)
            PORTS="$2"
            shift 2
            ;;
        --iports)
            IPORTS="$2"
            shift 2
            ;;
        --reset)
            RESET=true
            shift
            ;;
        --name)
            CUSTOM_NAME="$2"
            shift 2
            ;;
        --image)
            CUSTOM_IMAGE="$2"
            shift 2
            ;;
        --hostname)
            CUSTOM_HOSTNAME="$2"
            HOSTNAME_GIVEN=true
            shift 2
            ;;
        --no-shell)
            NO_SHELL=true
            shift
            ;;
        --host-network)
            HOST_NETWORK=true
            shift
            ;;
        --env-keys)
            ENV_KEYS="$2"
            shift 2
            ;;
        --remote-browser)
            if [[ -n "$2" && "$2" != --* ]]; then
                BROWSER_URL="$2"
                shift 2
            else
                BROWSER_URL="9222"
                shift
            fi
            ;;
        --clasp)
            CLASP=true
            shift
            ;;
        --web)
            WEB=true
            if [[ "$2" =~ ^[0-9]+$ ]]; then
                WEB_PORT="$2"
                WEB_PORT_GIVEN=true
                shift 2
            else
                shift
            fi
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,...] [--iports port:host_port,...] [--reset] [--name container-name] [--image image-name] [--hostname hostname] [--no-shell] [--host-network] [--env-keys KEY1,KEY2,...] [--remote-browser PORT] [--web [PORT]]"
            echo ""
            echo "Options:"
            echo "  --ports: Comma-separated list of port mappings, published on 127.0.0.1 only (e.g., 3000,8080:80,9000:3000)"
            echo "           Use a full ip:host:container form to choose the bind address (e.g., 0.0.0.0:3000:3000 exposes it on the network)"
            echo "  --iports: Comma-separated list of inverse port mappings to host.podman.internal (e.g., 3000,8080:80)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            echo "  --name: Custom container name (default: swarmbox)"
            echo "  --image: Custom image name (default: swarmbox)"
            echo "  --hostname: Custom hostname (default: swarmbox)"
            echo "  --no-shell: Don't attach to container shell (useful for testing/automation)"
            echo "  --host-network: Use host network namespace (container shares host network, ignores --ports)"
            echo "  --env-keys: Comma-separated list of environment variable keys to pass from host to container (e.g., KEY1,KEY2,KEY3)"
            echo "  --remote-browser: Connect chrome-devtools MCP to an existing Chrome instance (default port: 9222, e.g., --remote-browser, --remote-browser 1234, --remote-browser 192.168.1.100:9222)"
            echo "  --web: Serve a web terminal (ttyd + tmux) on 127.0.0.1:PORT of the host (default 7681); put Cloudflare Access/a tunnel in front to reach it remotely (see README)"
            echo "  --clasp: Expose port 43323 for clasp (Google Apps Script CLI) OAuth login callback"
            echo ""
            echo "Environment Variables:"
            echo "  MEMORY=<db_name>: Enable MCP memory service with specified database name (automatically passed if set)"
            echo "    Example: MEMORY=personal ./start.sh"
            echo "    Example: MEMORY=project1 ./start.sh"
            exit 1
            ;;
    esac
done

# The tunnel token must stay on the host: passing it to the container would hand it to the agent
case ",${ENV_KEYS// /}," in
    *,SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN,*)
        echo "ERROR: SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN must not be passed to the container with --env-keys:"
        echo "it is read by this script on the host to run the Cloudflare connector, and nothing inside needs it."
        exit 1
        ;;
esac

# Ports the user asked for (PORTS is later extended automatically for --clasp / MEMORY)
USER_PORTS="$PORTS"

# Check that Podman is installed
if ! command -v podman &> /dev/null; then
    echo "ERROR: Podman is not installed."
    echo "Please install Podman:"
    echo "  - Linux: sudo apt install podman (Debian/Ubuntu) or sudo dnf install podman (Fedora/RHEL)"
    echo "  - macOS: brew install podman"
    exit 1
fi

# Set container and image names
if [ -n "$CUSTOM_IMAGE" ]; then
    IMAGE_NAME="$CUSTOM_IMAGE"
fi
if [ -n "$CUSTOM_NAME" ]; then
    CONTAINER_NAME="$CUSTOM_NAME"
fi

msg "Starting SwarmBox..."
msg_detail "Image: $IMAGE_NAME"
msg_detail "Container: $CONTAINER_NAME"
msg_detail "Workspace: $WORK_DIR -> /home/agent"

# Automatically expose port 43323 for clasp OAuth login callback when --clasp is set
if [ "$CLASP" = "true" ]; then
    if [[ ! "$PORTS" =~ (^|,)43323(:|,|$) ]] && [ "$HOST_NETWORK" = "false" ]; then
        if [ -z "$PORTS" ]; then
            PORTS="43323"
        else
            PORTS="$PORTS,43323"
        fi
    fi
    msg_detail "clasp: OAuth port 43323 exposed"
fi

# Automatically expose port 8889 for memory web dashboard when MEMORY is set
if [ -n "${MEMORY+x}" ]; then
    if [[ ! "$PORTS" =~ (^|,)8889(:|,|$) ]] && [ "$HOST_NETWORK" = "false" ]; then
        if [ -z "$PORTS" ]; then
            PORTS="8889"
        else
            PORTS="$PORTS,8889"
        fi
    fi
    msg_detail "Memory: ${MEMORY} (dashboard on :8889)"
fi

# Parse port mappings. Published on 127.0.0.1 unless a bind address is given:
#   3000            -> 127.0.0.1:3000:3000
#   8080:80         -> 127.0.0.1:8080:80
#   0.0.0.0:3000:3000 (ip:host:container) -> used as is
CONTAINER_PORTS=""
if [ -n "$PORTS" ]; then
    IFS=',' read -ra PORT_ARRAY <<< "$PORTS"
    for port_mapping in "${PORT_ARRAY[@]}"; do
        colons="${port_mapping//[^:]/}"
        case ${#colons} in
            0) mapping="127.0.0.1:$port_mapping:$port_mapping" ;;
            1) mapping="127.0.0.1:$port_mapping" ;;
            *) mapping="$port_mapping" ;;
        esac
        CONTAINER_PORTS="$CONTAINER_PORTS -p $mapping"
        case "$mapping" in
            0.0.0.0:*|:*|\[::\]:*) msg_warn "Port $mapping is exposed on all network interfaces" ;;
            *) msg_detail "Port: $mapping" ;;
        esac
    done
fi

# Parse inverse port mappings (container can connect to host services)
CONTAINER_EXTRA_HOSTS=""
if [ -n "$IPORTS" ]; then
    IFS=',' read -ra IPORT_ARRAY <<< "$IPORTS"
    for port_mapping in "${IPORT_ARRAY[@]}"; do
        if [[ $port_mapping == *":"* ]]; then
            # Format: container_port:host_port
            IFS=':' read -ra PORT_SPLIT <<< "$port_mapping"
            container_port="${PORT_SPLIT[0]}"
            host_port="${PORT_SPLIT[1]}"
            CONTAINER_EXTRA_HOSTS="$CONTAINER_EXTRA_HOSTS --add-host=host.containers.internal:host-gateway"
        else
            # Format: port (container_port == host_port)
            CONTAINER_EXTRA_HOSTS="$CONTAINER_EXTRA_HOSTS --add-host=host.containers.internal:host-gateway"
        fi
    done
    # Remove duplicates by only adding once
    CONTAINER_EXTRA_HOSTS="--add-host=host.containers.internal:host-gateway"
fi

# Nested Podman (always on): Podman runs rootless inside the container, with no host
# socket mounted, so the agent has no path to the host Podman.
# Needs a tun device (slirp4netns) and a writable /proc/sys (crun).
# The nested image/layer store goes in a named volume, not in the bind-mounted
# $WORK_DIR: its files are owned by subuid-mapped IDs the host user cannot delete,
# and it grows large. Everything else under /home/agent stays in $WORK_DIR.
NESTED_PODMAN_OPTS="--device /dev/net/tun --security-opt unmask=/proc/* -v ${CONTAINER_NAME}-containers:/home/agent/.local/share/containers"

# Parse environment keys and build environment variable flags
CONTAINER_ENV_VARS=""

# Automatically pass MEMORY environment variable if it's set
if [ -n "${MEMORY+x}" ]; then
    CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e MEMORY=${MEMORY}"
fi

# Pass BROWSER_URL if set, normalizing to a full URL
if [ -n "$BROWSER_URL" ]; then
    if [[ "$BROWSER_URL" =~ ^[0-9]+$ ]]; then
        # bare port → use host.containers.internal
        BROWSER_URL="http://host.containers.internal:${BROWSER_URL}"
    elif [[ "$BROWSER_URL" != http://* && "$BROWSER_URL" != https://* ]]; then
        # host:port with no scheme → add http://
        BROWSER_URL="http://${BROWSER_URL}"
    fi
    CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e BROWSER_URL=${BROWSER_URL}"
    msg_detail "Browser URL: ${BROWSER_URL}"
fi

# Pass local LLM settings (OpenCode) if set in the host environment
for key in LOCAL_LLM_URL LOCAL_LLM_KEY LOCAL_LLM_MODEL LOCAL_LLM_CONTEXT LOCAL_LLM_OUTPUT; do
    if [ -n "${!key}" ]; then
        CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e $key=${!key}"
    fi
done

if [ -n "$ENV_KEYS" ]; then
    IFS=',' read -ra ENV_KEY_ARRAY <<< "$ENV_KEYS"
    for key in "${ENV_KEY_ARRAY[@]}"; do
        # Trim whitespace from key
        key=$(echo "$key" | xargs)
        # Skip MEMORY if already added
        if [ "$key" = "MEMORY" ]; then
            continue
        fi
        if [ -n "${!key+x}" ]; then
            # Variable exists in host environment
            CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e $key=${!key}"
        else
            msg_warn "Environment variable '$key' not found, skipping"
        fi
    done
fi

# Web terminal: ttyd inside the container, published on the host's 127.0.0.1 only.
# It gives a shell with no login of its own, so it must never end up on a public interface.
if [ "$WEB" = "true" ]; then
    if [ "$HOST_NETWORK" = "true" ]; then
        msg_warn "--web cannot be combined with --host-network (the terminal would listen on every host interface)"
        exit 1
    fi
    CONTAINER_PORTS="$CONTAINER_PORTS -p 127.0.0.1:${WEB_PORT}:7681"
    CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e SWARMBOX_WEB=1"
fi

# Set network mode
NETWORK_FLAG=""
if [ "$HOST_NETWORK" = "true" ]; then
    NETWORK_FLAG="--net=host"
    msg_detail "Using host network"
    if [ -n "$PORTS" ] || [ -n "$IPORTS" ]; then
        msg_warn "Port mappings ignored with host network"
    fi
fi

# Create directories if they don't exist
if [ ! -d "$WORK_DIR" ]; then
    msg_warn "Workspace $WORK_DIR does not exist: creating a new, empty one."
    msg_warn "To reuse an existing workspace, run this from the directory that contains your .work"
fi
mkdir -p "$WORK_DIR"

# Build image if it doesn't exist
if [[ "$(podman images -q "$IMAGE_NAME" 2> /dev/null)" == "" ]]; then
    echo ""
    msg "Building image..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=darwin -t "$IMAGE_NAME" "$SCRIPT_DIR"
    else
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=linux -t "$IMAGE_NAME" "$SCRIPT_DIR"
    fi
    echo ""
fi

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

post_start() {
    podman exec -d "$CONTAINER_NAME" /usr/local/bin/swarmbox-podman-service >/dev/null 2>&1 || true
    register_podman_connection
    start_web_terminal
    # Surface a missing service (e.g. image not rebuilt) instead of failing silently later
    if [[ "$OSTYPE" != "darwin"* ]]; then
        local sock="$WORK_DIR/.swarmbox/podman.sock" i
        for i in 1 2 3 4 5 6 7 8 9 10; do
            # A stale socket file can survive a container restart, so check it answers
            [ -S "$sock" ] && podman --url "unix://$sock" version >/dev/null 2>&1 && return
            sleep 0.5
        done
        msg_warn "Nested Podman service did not start (is the image up to date? run ./build.sh and --reset)"
    fi
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

# Reattaching to an existing container applies none of the creation-time options, and the
# container may predate a rebuild or mount a different workspace. Say so instead of
# silently doing something other than what was asked.
check_existing_container() {
    local ignored=""
    [ -n "$USER_PORTS" ] && ignored="$ignored --ports"
    [ -n "$IPORTS" ] && ignored="$ignored --iports"
    [ "$HOST_NETWORK" = "true" ] && ignored="$ignored --host-network"
    [ "$HOSTNAME_GIVEN" = "true" ] && ignored="$ignored --hostname"
    [ -n "$CUSTOM_IMAGE" ] && ignored="$ignored --image"
    [ -n "$ENV_KEYS" ] && ignored="$ignored --env-keys"
    [ -n "$BROWSER_URL" ] && ignored="$ignored --remote-browser"
    [ "$CLASP" = "true" ] && ignored="$ignored --clasp"
    [ "$WEB" = "true" ] && ! container_has_web && ignored="$ignored --web"
    if [ -n "$ignored" ]; then
        msg_warn "Container '$CONTAINER_NAME' already exists, so these options would be ignored:$ignored"
        msg_warn "They only apply when the container is created. Re-run with --reset to apply them"
        msg_warn "(the workspace is kept), or drop them to just reattach."
        exit 1
    fi

    local ct_image cur_image ct_mount
    ct_image=$(podman inspect -f '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null)
    cur_image=$(podman image inspect -f '{{.Id}}' "$IMAGE_NAME" 2>/dev/null)
    if [ -n "$ct_image" ] && [ -n "$cur_image" ] && [ "$ct_image" != "$cur_image" ]; then
        msg_warn "This container was created from an older '$IMAGE_NAME' image (rebuilt since). Use --reset to recreate it."
    fi
    ct_mount=$(podman inspect -f '{{range .Mounts}}{{if eq .Destination "/home/agent"}}{{.Source}}{{end}}{{end}}' "$CONTAINER_NAME" 2>/dev/null)
    if [ -n "$ct_mount" ] && [ "$ct_mount" != "$WORK_DIR" ]; then
        msg_warn "This container's workspace is $ct_mount (not $WORK_DIR, from the current directory)."
    fi
}

# Time zone. The image has none of its own (it runs in UTC), so the container's clock (the prompt's time, date,
# logs) would be hours off from yours. By default the container follows this machine's zone (--tz=local, which
# needs /etc/localtime). SWARMBOX_TZ=<Area/City> picks another zone and SWARMBOX_TZ=off keeps the image's UTC.
# (With a podman machine on macOS "local" is the VM's zone: set SWARMBOX_TZ there.)
TZ_FLAG=""
case "${SWARMBOX_TZ:-}" in
    "")
        [ -e "${SWARMBOX_LOCALTIME_FILE:-/etc/localtime}" ] && TZ_FLAG="--tz=local"
        ;;
    off|OFF|none|NONE)
        ;;
    *)
        if [[ "$SWARMBOX_TZ" =~ ^[A-Za-z0-9_+/-]+$ ]]; then
            TZ_FLAG="--tz=$SWARMBOX_TZ"
        else
            msg_warn "Ignoring SWARMBOX_TZ: '$SWARMBOX_TZ' is not a time zone name (e.g. America/Sao_Paulo)"
        fi
        ;;
esac

# PID 1 of the container is `tail -f /dev/null`, which never reaps children that exit (a browser launched in
# a test, nested containers, ...): they pile up as zombies. --init puts a tiny init (catatonit) in front.
# SWARMBOX_INIT=1 forces it and SWARMBOX_INIT=0 turns it off; by default it is used when this podman can run
# it (a throwaway `podman run --init` of the image answers that, without assuming where catatonit lives).
# Only needed when a container is created: an existing one keeps what it was created with (use --reset).
INIT_FLAG=""
detect_init() {
    case "${SWARMBOX_INIT:-auto}" in
        0|false|no) return 0 ;;
        1|true|yes) INIT_FLAG="--init"; return 0 ;;
    esac
    if podman run --rm --init "$IMAGE_NAME" true >/dev/null 2>&1; then
        INIT_FLAG="--init"
    else
        msg_detail "podman cannot run --init here (is catatonit installed?): exited processes will not be reaped"
    fi
}

# Handle reset option
if [ "$RESET" = "true" ]; then
    if [ "$(podman ps -a -q -f name="$CONTAINER_NAME")" ]; then
        msg_detail "Resetting container..."
        podman stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        podman rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    # After reset, force creation of new container
    echo ""

    detect_init
    # Create and start container
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - run with security-opt and userns options
        podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) --pids-limit=16384 -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $NESTED_PODMAN_OPTS \
            $INIT_FLAG \
            $TZ_FLAG \
            $CONTAINER_ENV_VARS \
            $NETWORK_FLAG \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME" >/dev/null
    else
        # Linux - run with userns option
        podman run --userns=keep-id --pids-limit=16384 -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $NESTED_PODMAN_OPTS \
            $INIT_FLAG \
            $TZ_FLAG \
            $CONTAINER_ENV_VARS \
            $NETWORK_FLAG \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME" >/dev/null
    fi

    post_start

    # Connect to the container (unless --no-shell is set)
    if [ "$NO_SHELL" = "false" ]; then
        podman exec -it -e TERM="${TERM:-xterm-256color}" -e COLORTERM="${COLORTERM:-truecolor}" "$CONTAINER_NAME" bash
    fi
else
    # Normal operation: check if container already exists
    if [ "$(podman ps -a -q -f name="$CONTAINER_NAME")" ]; then
        check_existing_container
        adopt_existing_web
        echo ""
        podman start "$CONTAINER_NAME" 2>/dev/null || true
        post_start
        if [ "$NO_SHELL" = "false" ]; then
            podman exec -it -e TERM="${TERM:-xterm-256color}" -e COLORTERM="${COLORTERM:-truecolor}" "$CONTAINER_NAME" bash
        fi
    else
        echo ""
        detect_init
        # Create and start container
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS - run with security-opt and userns options
            podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) --pids-limit=16384 -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $NESTED_PODMAN_OPTS \
                $INIT_FLAG \
                $TZ_FLAG \
                $CONTAINER_ENV_VARS \
                $NETWORK_FLAG \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME" >/dev/null
        else
            # Linux - run with userns option
            podman run --userns=keep-id --pids-limit=16384 -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $NESTED_PODMAN_OPTS \
                $INIT_FLAG \
                $TZ_FLAG \
                $CONTAINER_ENV_VARS \
                $NETWORK_FLAG \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME" >/dev/null
        fi

        post_start

        # Connect to the container (unless --no-shell is set)
        if [ "$NO_SHELL" = "false" ]; then
            podman exec -it -e TERM="${TERM:-xterm-256color}" -e COLORTERM="${COLORTERM:-truecolor}" "$CONTAINER_NAME" bash
        fi
    fi
fi