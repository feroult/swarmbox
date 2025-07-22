#!/bin/bash

# Source the container runtime configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"

# Configuration
IMAGE_NAME="swarm-box"
CONTAINER_NAME="swarm-box"
WORK_DIR="$(pwd)/.work"
PORTS=""
RESET=false
RUNTIME_ARG=""
CUSTOM_NAME=""
CUSTOM_IMAGE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --ports)
            PORTS="$2"
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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,port:inner_port,...] [--reset] [--runtime docker|podman] [--name container-name] [--image image-name]"
            echo "  --ports: Comma-separated list of port mappings (e.g., 3000,8080:80,9000:3000)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            echo "  --runtime: Specify container runtime (docker or podman). Default: docker"
            echo "  --name: Custom container name (default: swarm-box)"
            echo "  --image: Custom image name (default: swarm-box)"
            exit 1
            ;;
    esac
done

# Detect and set runtime
detect_runtime "$RUNTIME_ARG"
echo "Using container runtime: $RUNTIME"

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
            -v "$WORK_DIR:/home/agent" \
            $CONTAINER_PORTS \
            "$IMAGE_NAME"
    else
        # Linux - use privileged mode
        eval "$RUN_COMMAND" -d \
            --privileged \
            --name "$CONTAINER_NAME" \
            -v "$WORK_DIR:/home/agent" \
            $CONTAINER_PORTS \
            "$IMAGE_NAME"
    fi
    
    
    # Connect to the container
    "$RUNTIME" exec -it "$CONTAINER_NAME" bash -c "
        echo 'Welcome to Swarm Box Container Environment!'
        echo '==========================================='
        echo ''
        echo 'First time setup:'
        echo '1. Run: claude --dangerously-skip-permissions'
        echo '2. Follow the authentication link'
        echo '3. Your auth will be saved in the persistent volume'
        echo ''
        echo 'Initialize Claude Flow:'
        echo 'claude-flow init --force'
        echo ''
        exec bash
    "
else
    # Normal operation: check if container already exists
    if [ "$("$RUNTIME" ps -a -q -f name="$CONTAINER_NAME")" ]; then
        echo "Container already exists. Connecting to it..."
        "$RUNTIME" start "$CONTAINER_NAME" 2>/dev/null || true
        "$RUNTIME" exec -it "$CONTAINER_NAME" bash
    else
        echo "Creating new container..."
        # Create and start container
        RUN_COMMAND="$(get_run_command)"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS - run without privileged mode which causes issues
            eval "$RUN_COMMAND" -d \
                --name "$CONTAINER_NAME" \
                -v "$WORK_DIR:/home/agent" \
                $CONTAINER_PORTS \
                "$IMAGE_NAME"
        else
            # Linux - use privileged mode
            eval "$RUN_COMMAND" -d \
                --privileged \
                --name "$CONTAINER_NAME" \
                -v "$WORK_DIR:/home/agent" \
                $CONTAINER_PORTS \
                "$IMAGE_NAME"
        fi
        
        # No runtime ownership adjustments - handled at build time
        
        # Connect to the container
        "$RUNTIME" exec -it "$CONTAINER_NAME" bash -c "
            echo 'Welcome to Swarm Box Container Environment!'
            echo '==========================================='
            echo ''
            echo 'First time setup:'
            echo '1. Run: claude --dangerously-skip-permissions'
            echo '2. Follow the authentication link'
            echo '3. Your auth will be saved in the persistent volume'
            echo ''
            echo 'Initialize Claude Flow:'
            echo 'npx claude-flow@alpha init --force'
            echo ''
            exec bash
        "
    fi
fi