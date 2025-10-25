#!/bin/bash

# Podman-only runtime (Docker support removed)
RUNTIME="podman"

# Configuration
IMAGE_NAME="swarmbox"
CONTAINER_NAME="swarmbox"
RESET=false
NO_CACHE=false
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
        --name)
            CUSTOM_NAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--reset] [--no-cache] [--name image-name]"
            echo "  --reset: Remove container, image, and .work directory for fresh installation"
            echo "  --no-cache: Build the container image without using cache"
            echo "  --name: Custom image name (default: swarmbox)"
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

echo "Using container runtime: podman"

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
    if [ "$(podman ps -a -q -f name=$CONTAINER_NAME)" ]; then
        echo "Stopping and removing container..."
        podman stop $CONTAINER_NAME 2>/dev/null || true
        podman rm $CONTAINER_NAME 2>/dev/null || true
    fi

    # Remove image if exists
    if [[ "$(podman images -q $IMAGE_NAME 2> /dev/null)" != "" ]]; then
        echo "Removing container image..."
        podman rmi $IMAGE_NAME:latest
    fi

    echo "Reset complete!"
    echo ""
fi

# Build the container image
echo "Building Swarm Box container image..."

# Detect OS and set build arguments
if [[ "$OSTYPE" == "darwin"* ]]; then
    BUILD_COMMAND="podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=darwin"
else
    BUILD_COMMAND="podman build --build-arg USER_UID=$(id -u) --build-arg USER_GID=$(id -g) --build-arg HOST_OS=linux"
fi

if [ "$NO_CACHE" = true ]; then
    BUILD_COMMAND="$BUILD_COMMAND --no-cache"
fi

eval "$BUILD_COMMAND" -t $IMAGE_NAME .

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "You can now run ./start.sh to begin"
else
    echo "Build failed!"
    exit 1
fi