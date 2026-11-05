#!/bin/bash

# Messaging utilities - sober design
msg() { echo -e "\033[0;37m${1}\033[0m"; }
msg_detail() { echo -e "\033[0;90m  ${1}\033[0m"; }
msg_warn() { echo -e "\033[0;90m${1}\033[0m"; }

# Podman-only runtime (Docker support removed)
RUNTIME="podman"

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
NO_SHELL=false
HOST_NETWORK=false
ENV_KEYS=""
BROWSER_URL=""
CLASP=false

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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,...] [--iports port:host_port,...] [--reset] [--name container-name] [--image image-name] [--hostname hostname] [--no-shell] [--host-network] [--env-keys KEY1,KEY2,...] [--remote-browser PORT]"
            echo ""
            echo "Options:"
            echo "  --ports: Comma-separated list of port mappings (e.g., 3000,8080:80,9000:3000)"
            echo "  --iports: Comma-separated list of inverse port mappings to host.podman.internal (e.g., 3000,8080:80)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            echo "  --name: Custom container name (default: swarmbox)"
            echo "  --image: Custom image name (default: swarmbox)"
            echo "  --hostname: Custom hostname (default: swarmbox)"
            echo "  --no-shell: Don't attach to container shell (useful for testing/automation)"
            echo "  --host-network: Use host network namespace (container shares host network, ignores --ports)"
            echo "  --env-keys: Comma-separated list of environment variable keys to pass from host to container (e.g., KEY1,KEY2,KEY3)"
            echo "  --remote-browser: Connect chrome-devtools MCP to an existing Chrome instance (default port: 9222, e.g., --remote-browser, --remote-browser 1234, --remote-browser 192.168.1.100:9222)"
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

# Parse port mappings
CONTAINER_PORTS=""
if [ -n "$PORTS" ]; then
    IFS=',' read -ra PORT_ARRAY <<< "$PORTS"
    for port_mapping in "${PORT_ARRAY[@]}"; do
        if [[ $port_mapping == *":"* ]]; then
            # Format: port:inner_port
            CONTAINER_PORTS="$CONTAINER_PORTS -p $port_mapping"
        else
            # Format: port (port == inner_port)
            CONTAINER_PORTS="$CONTAINER_PORTS -p $port_mapping:$port_mapping"
        fi
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
mkdir -p "$WORK_DIR"

# Build image if it doesn't exist
if [[ "$(podman images -q "$IMAGE_NAME" 2> /dev/null)" == "" ]]; then
    echo ""
    msg "Building image..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=darwin -t "$IMAGE_NAME" .
    else
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=linux -t "$IMAGE_NAME" .
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

post_start() {
    podman exec -d "$CONTAINER_NAME" /usr/local/bin/swarmbox-podman-service >/dev/null 2>&1 || true
    register_podman_connection
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

# Handle reset option
if [ "$RESET" = "true" ]; then
    if [ "$(podman ps -a -q -f name="$CONTAINER_NAME")" ]; then
        msg_detail "Resetting container..."
        podman stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        podman rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
    # After reset, force creation of new container
    echo ""

    # Create and start container
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - run with security-opt and userns options
        podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) --pids-limit=16384 -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $NESTED_PODMAN_OPTS \
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
        echo ""
        podman start "$CONTAINER_NAME" 2>/dev/null || true
        post_start
        if [ "$NO_SHELL" = "false" ]; then
            podman exec -it -e TERM="${TERM:-xterm-256color}" -e COLORTERM="${COLORTERM:-truecolor}" "$CONTAINER_NAME" bash
        fi
    else
        echo ""
        # Create and start container
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS - run with security-opt and userns options
            podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) --pids-limit=16384 -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $NESTED_PODMAN_OPTS \
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