#!/bin/bash

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
WITH_UNSAFE_PODMAN=false
HOST_NETWORK=false
ENV_KEYS=""

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
        --with-unsafe-podman)
            WITH_UNSAFE_PODMAN=true
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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,...] [--iports port:host_port,...] [--reset] [--name container-name] [--image image-name] [--hostname hostname] [--no-shell] [--host-network] [--with-unsafe-podman] [--env-keys KEY1,KEY2,...]"
            echo "  --ports: Comma-separated list of port mappings (e.g., 3000,8080:80,9000:3000)"
            echo "  --iports: Comma-separated list of inverse port mappings to host.podman.internal (e.g., 3000,8080:80)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            echo "  --name: Custom container name (default: swarmbox)"
            echo "  --image: Custom image name (default: swarmbox)"
            echo "  --hostname: Custom hostname (default: swarmbox)"
            echo "  --no-shell: Don't attach to container shell (useful for testing/automation)"
            echo "  --host-network: Use host network namespace (container shares host network, ignores --ports)"
            echo "  --with-unsafe-podman: Mount host Podman socket (UNSAFE - gives container access to host Podman)"
            echo "  --env-keys: Comma-separated list of environment variable keys to pass from host to container (e.g., KEY1,KEY2,KEY3)"
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

echo "Using Podman container runtime"

# Handle Podman socket mounting (if --with-unsafe-podman is set)
PODMAN_SOCKET_MOUNT=""
PODMAN_HOST_ENV=""
if [ "$WITH_UNSAFE_PODMAN" = true ]; then
    echo ""
    echo "WARNING: --with-unsafe-podman enabled!"
    echo "This gives the container access to the host Podman daemon."
    echo "The container can create/destroy containers and images on the host."
    echo ""

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - Podman runs in a VM with socket forwarding
        # Try multiple socket locations in order of preference:
        # 1. Docker-compatible socket from podman-mac-helper
        # 2. Podman machine API socket (direct, no helper needed)
        if [ -S "/var/run/docker.sock" ]; then
            PODMAN_SOCKET="/var/run/docker.sock"
        elif [ -S "$HOME/.docker/run/docker.sock" ]; then
            PODMAN_SOCKET="$HOME/.docker/run/docker.sock"
        else
            # Try to find the Podman machine API socket directly
            MACHINE_NAME=$(podman machine list --format "{{.Name}}" --noheading | head -n1)
            if [ -n "$MACHINE_NAME" ]; then
                # Get socket path from podman machine inspect
                PODMAN_SOCKET=$(podman machine inspect "$MACHINE_NAME" --format "{{.ConnectionInfo.PodmanSocket.Path}}")
                if [ ! -S "$PODMAN_SOCKET" ]; then
                    echo "ERROR: Podman socket not found at: $PODMAN_SOCKET"
                    echo "Please ensure Podman machine is running:"
                    echo "  podman machine start"
                    exit 1
                fi
            else
                echo "ERROR: No Podman machine found."
                echo "Please create and start a Podman machine:"
                echo "  podman machine init"
                echo "  podman machine start"
                exit 1
            fi
        fi
        # Mount to Podman-specific path inside container
        PODMAN_SOCKET_MOUNT="-v $PODMAN_SOCKET:/run/podman/podman.sock"
        PODMAN_HOST_ENV="-e CONTAINER_HOST=unix:///run/podman/podman.sock"
        echo "Mounting Podman socket: $PODMAN_SOCKET -> /run/podman/podman.sock"
    else
        # Linux - Try rootless Podman socket first
        PODMAN_SOCKET="/run/user/$(id -u)/podman/podman.sock"
        if [ ! -S "$PODMAN_SOCKET" ]; then
            # Fall back to rootful socket
            PODMAN_SOCKET="/run/podman/podman.sock"
            if [ ! -S "$PODMAN_SOCKET" ]; then
                echo "ERROR: Podman socket not found. Start Podman socket service:"
                echo "  systemctl --user enable --now podman.socket  (rootless)"
                echo "  or"
                echo "  sudo systemctl enable --now podman.socket     (rootful)"
                exit 1
            fi
        fi
        # Mount to Podman-specific path inside container
        PODMAN_SOCKET_MOUNT="-v $PODMAN_SOCKET:/run/podman/podman.sock"
        PODMAN_HOST_ENV="-e CONTAINER_HOST=unix:///run/podman/podman.sock"
        echo "Mounting Podman socket: $PODMAN_SOCKET -> /run/podman/podman.sock"
    fi
    echo ""
fi

# Set container and image names
if [ -n "$CUSTOM_IMAGE" ]; then
    IMAGE_NAME="$CUSTOM_IMAGE"
fi
if [ -n "$CUSTOM_NAME" ]; then
    CONTAINER_NAME="$CUSTOM_NAME"
fi
echo "Image name: $IMAGE_NAME"
echo "Container name: $CONTAINER_NAME"

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

# Parse environment keys and build environment variable flags
CONTAINER_ENV_VARS=""
if [ -n "$ENV_KEYS" ]; then
    IFS=',' read -ra ENV_KEY_ARRAY <<< "$ENV_KEYS"
    for key in "${ENV_KEY_ARRAY[@]}"; do
        # Trim whitespace from key
        key=$(echo "$key" | xargs)
        if [ -n "${!key+x}" ]; then
            # Variable exists in host environment
            CONTAINER_ENV_VARS="$CONTAINER_ENV_VARS -e $key=${!key}"
            echo "Passing environment variable: $key"
        else
            echo "Warning: Environment variable '$key' not found in host environment, skipping."
        fi
    done
fi

# Set network mode
NETWORK_FLAG=""
if [ "$HOST_NETWORK" = true ]; then
    NETWORK_FLAG="--net=host"
    echo "Using host network namespace"
    if [ -n "$PORTS" ] || [ -n "$IPORTS" ]; then
        echo "Warning: --ports and --iports are ignored when using --host-network"
    fi
fi

# Create directories if they don't exist
mkdir -p "$WORK_DIR"

# Build image if it doesn't exist
if [[ "$(podman images -q "$IMAGE_NAME" 2> /dev/null)" == "" ]]; then
    echo "Building container image..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=darwin -t "$IMAGE_NAME" .
    else
        podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=linux -t "$IMAGE_NAME" .
    fi
fi

# Handle reset option
if [ "$RESET" = true ]; then
    if [ "$(podman ps -a -q -f name="$CONTAINER_NAME")" ]; then
        echo "Resetting container (keeping persistent folders)..."
        echo "Stopping container and killing all connected shells..."
        podman stop "$CONTAINER_NAME" 2>/dev/null || true
        podman rm "$CONTAINER_NAME" 2>/dev/null || true
        echo "Container reset complete."
    fi
    # After reset, force creation of new container
    echo "Creating new container..."

    # Create and start container
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - run with security-opt and userns options
        podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $PODMAN_SOCKET_MOUNT \
            $PODMAN_HOST_ENV \
            $CONTAINER_ENV_VARS \
            $NETWORK_FLAG \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME"
    else
        # Linux - run with userns option
        podman run --userns=keep-id -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $PODMAN_SOCKET_MOUNT \
            $PODMAN_HOST_ENV \
            $CONTAINER_ENV_VARS \
            $NETWORK_FLAG \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME"
    fi

    # Connect to the container (unless --no-shell is set)
    if [ "$NO_SHELL" = false ]; then
        podman exec -it "$CONTAINER_NAME" bash
    fi
else
    # Normal operation: check if container already exists
    if [ "$(podman ps -a -q -f name="$CONTAINER_NAME")" ]; then
        echo "Container already exists. Connecting to it..."
        podman start "$CONTAINER_NAME" 2>/dev/null || true
        if [ "$NO_SHELL" = false ]; then
            podman exec -it "$CONTAINER_NAME" bash
        fi
    else
        echo "Creating new container..."
        # Create and start container
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS - run with security-opt and userns options
            podman run --security-opt label=disable --userns=keep-id:uid=$(id -u),gid=$(id -g) -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $PODMAN_SOCKET_MOUNT \
                $PODMAN_HOST_ENV \
                $CONTAINER_ENV_VARS \
                $NETWORK_FLAG \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME"
        else
            # Linux - run with userns option
            podman run --userns=keep-id -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $PODMAN_SOCKET_MOUNT \
                $PODMAN_HOST_ENV \
                $CONTAINER_ENV_VARS \
                $NETWORK_FLAG \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME"
        fi

        # Connect to the container (unless --no-shell is set)
        if [ "$NO_SHELL" = false ]; then
            podman exec -it "$CONTAINER_NAME" bash
        fi
    fi
fi