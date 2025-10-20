#!/bin/bash

# Source the container runtime configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"

# Configuration
IMAGE_NAME="swarmbox"
CONTAINER_NAME="swarmbox"
WORK_DIR="$(pwd)/.work"
PORTS=""
IPORTS=""
RESET=false
RUNTIME_ARG=""
CUSTOM_NAME=""
CUSTOM_IMAGE=""
CUSTOM_HOSTNAME="swarmbox"
NO_SHELL=false
WITH_UNSAFE_DOCKER=false
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
        --runtime)
            RUNTIME_ARG="$2"
            shift 2
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
        --with-unsafe-docker)
            WITH_UNSAFE_DOCKER=true
            shift
            ;;
        --env-keys)
            ENV_KEYS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,port:inner_port,...] [--iports port:host_port,port:host_port,...] [--reset] [--runtime docker|podman] [--name container-name] [--image image-name] [--hostname hostname] [--no-shell] [--with-unsafe-docker] [--env-keys KEY1,KEY2,...]"
            echo "  --ports: Comma-separated list of port mappings (e.g., 3000,8080:80,9000:3000)"
            echo "  --iports: Comma-separated list of inverse port mappings to host.docker.internal (e.g., 3000,8080:80)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            echo "  --runtime: Specify container runtime (docker or podman). Default: docker"
            echo "  --name: Custom container name (default: swarmbox)"
            echo "  --image: Custom image name (default: swarmbox)"
            echo "  --hostname: Custom hostname (default: swarmbox)"
            echo "  --no-shell: Don't attach to container shell (useful for testing/automation)"
            echo "  --with-unsafe-docker: Mount host container socket (UNSAFE - gives container access to host daemon)"
            echo "  --env-keys: Comma-separated list of environment variable keys to pass from host to container (e.g., KEY1,KEY2,KEY3)"
            exit 1
            ;;
    esac
done

# Detect and set runtime
detect_runtime "$RUNTIME_ARG"
echo "Using container runtime: $RUNTIME"

# Handle Docker socket mounting (if --with-unsafe-docker is set)
DOCKER_SOCKET_MOUNT=""
DOCKER_HOST_ENV=""
if [ "$WITH_UNSAFE_DOCKER" = true ]; then
    echo ""
    echo "WARNING: --with-unsafe-docker enabled!"
    echo "This gives the container access to the host container daemon."
    echo "The container can create/destroy containers and images on the host."
    echo ""

    # Detect socket path based on runtime
    if [ "$RUNTIME" = "podman" ]; then
        # Try rootless Podman socket first
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
        DOCKER_SOCKET_MOUNT="-v $PODMAN_SOCKET:/var/run/docker.sock"
        DOCKER_HOST_ENV="-e DOCKER_HOST=unix:///var/run/docker.sock"
        echo "Mounting Podman socket: $PODMAN_SOCKET -> /var/run/docker.sock"
    elif [ "$RUNTIME" = "docker" ]; then
        DOCKER_SOCKET="/var/run/docker.sock"
        if [ ! -S "$DOCKER_SOCKET" ]; then
            echo "ERROR: Docker socket not found at $DOCKER_SOCKET"
            exit 1
        fi
        DOCKER_SOCKET_MOUNT="-v $DOCKER_SOCKET:/var/run/docker.sock"
        DOCKER_HOST_ENV="-e DOCKER_HOST=unix:///var/run/docker.sock"
        echo "Mounting Docker socket: $DOCKER_SOCKET -> /var/run/docker.sock"
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
            CONTAINER_EXTRA_HOSTS="$CONTAINER_EXTRA_HOSTS --add-host=host.docker.internal:host-gateway"
        else
            # Format: port (container_port == host_port)
            CONTAINER_EXTRA_HOSTS="$CONTAINER_EXTRA_HOSTS --add-host=host.docker.internal:host-gateway"
        fi
    done
    # Remove duplicates by only adding once
    CONTAINER_EXTRA_HOSTS="--add-host=host.docker.internal:host-gateway"
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

# Create directories if they don't exist
mkdir -p "$WORK_DIR"

# Build image if it doesn't exist
if [[ "$("$RUNTIME" images -q "$IMAGE_NAME" 2> /dev/null)" == "" ]]; then
    echo "Building container image..."
    BUILD_COMMAND="$(get_build_command)"
    eval "$BUILD_COMMAND" -t "$IMAGE_NAME" .
fi

# Handle reset option
if [ "$RESET" = true ]; then
    if [ "$("$RUNTIME" ps -a -q -f name="$CONTAINER_NAME")" ]; then
        echo "Resetting container (keeping persistent folders)..."
        echo "Stopping container and killing all connected shells..."
        "$RUNTIME" stop "$CONTAINER_NAME" 2>/dev/null || true
        "$RUNTIME" rm "$CONTAINER_NAME" 2>/dev/null || true
        echo "Container reset complete."
    fi
    # After reset, force creation of new container
    echo "Creating new container..."
    
    # Create and start container
    RUN_COMMAND="$(get_run_command)"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS - run without privileged mode which causes issues
        eval "$RUN_COMMAND" -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $DOCKER_SOCKET_MOUNT \
            $DOCKER_HOST_ENV \
            $CONTAINER_ENV_VARS \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME"
    else
        # Linux - run without privileged mode
        eval "$RUN_COMMAND" -d \
            --name "$CONTAINER_NAME" \
            --hostname "$CUSTOM_HOSTNAME" \
            -v "$WORK_DIR:/home/agent" \
            $DOCKER_SOCKET_MOUNT \
            $DOCKER_HOST_ENV \
            $CONTAINER_ENV_VARS \
            $CONTAINER_PORTS \
            $CONTAINER_EXTRA_HOSTS \
            "$IMAGE_NAME"
    fi


    # Connect to the container (unless --no-shell is set)
    if [ "$NO_SHELL" = false ]; then
        "$RUNTIME" exec -it "$CONTAINER_NAME" bash
    fi
else
    # Normal operation: check if container already exists
    if [ "$("$RUNTIME" ps -a -q -f name="$CONTAINER_NAME")" ]; then
        echo "Container already exists. Connecting to it..."
        "$RUNTIME" start "$CONTAINER_NAME" 2>/dev/null || true
        if [ "$NO_SHELL" = false ]; then
            "$RUNTIME" exec -it "$CONTAINER_NAME" bash
        fi
    else
        echo "Creating new container..."
        # Create and start container
        RUN_COMMAND="$(get_run_command)"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS - run without privileged mode which causes issues
            eval "$RUN_COMMAND" -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $DOCKER_SOCKET_MOUNT \
                $DOCKER_HOST_ENV \
                $CONTAINER_ENV_VARS \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME"
        else
            # Linux - run without privileged mode
            eval "$RUN_COMMAND" -d \
                --name "$CONTAINER_NAME" \
                --hostname "$CUSTOM_HOSTNAME" \
                -v "$WORK_DIR:/home/agent" \
                $DOCKER_SOCKET_MOUNT \
                $DOCKER_HOST_ENV \
                $CONTAINER_ENV_VARS \
                $CONTAINER_PORTS \
                $CONTAINER_EXTRA_HOSTS \
                "$IMAGE_NAME"
        fi

        # No runtime ownership adjustments - handled at build time

        # Connect to the container (unless --no-shell is set)
        if [ "$NO_SHELL" = false ]; then
            "$RUNTIME" exec -it "$CONTAINER_NAME" bash
        fi
    fi
fi