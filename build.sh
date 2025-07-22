#!/bin/bash

# Source the container runtime configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"

# Configuration
IMAGE_NAME="swarm-box"
CONTAINER_NAME="swarm-box"
RESET=false
NO_CACHE=false
RUNTIME_ARG=""
CUSTOM_NAME=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --reset)
            RESET=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--reset] [--no-cache] [--runtime docker|podman] [--name image-name]"
            echo "  --reset: Remove container, image, and .work directory for fresh installation"
            echo "  --no-cache: Build the container image without using cache"
            echo "  --runtime: Specify container runtime (docker or podman). Default: docker"
            echo "  --name: Custom image name (default: swarm-box)"
            exit 1
            ;;
    esac
done

# Detect and set runtime
detect_runtime "$RUNTIME_ARG"
echo "Using container runtime: $RUNTIME"

# Set image name
if [ -n "$CUSTOM_NAME" ]; then
    IMAGE_NAME="$CUSTOM_NAME"
    CONTAINER_NAME="$CUSTOM_NAME"
fi
echo "Image name: $IMAGE_NAME"

# Handle reset option
if [ "$RESET" = true ]; then
    echo "Performing complete reset..."
    
    # Stop and remove container if exists
    if [ "$($RUNTIME ps -a -q -f name=$CONTAINER_NAME)" ]; then
        echo "Stopping and removing container..."
        $RUNTIME stop $CONTAINER_NAME 2>/dev/null || true
        $RUNTIME rm $CONTAINER_NAME 2>/dev/null || true
    fi
    
    # Remove image if exists
    if [[ "$($RUNTIME images -q $IMAGE_NAME 2> /dev/null)" != "" ]]; then
        echo "Removing container image..."
        $RUNTIME rmi $IMAGE_NAME:latest
    fi
    
    echo "Reset complete!"
    echo ""
fi

# Build the container image
echo "Building Swarm Box container image..."

BUILD_COMMAND="$(get_build_command)"
if [ "$NO_CACHE" = true ]; then
    BUILD_COMMAND="$BUILD_COMMAND --no-cache"
fi

# Pass the host user's UID and GID as build arguments
# The get_build_command function already includes HOST_OS
eval "$BUILD_COMMAND" -t $IMAGE_NAME .

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "You can now run ./start.sh to begin"
else
    echo "Build failed!"
    exit 1
fi