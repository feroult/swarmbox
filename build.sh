#!/bin/bash

# Configuration
IMAGE_NAME="claude-flow"
CONTAINER_NAME="claude-flow-session"
RESET=false
NO_CACHE=false

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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--reset] [--no-cache]"
            echo "  --reset: Remove container, image, and .work directory for fresh installation"
            echo "  --no-cache: Build the Docker image without using cache"
            exit 1
            ;;
    esac
done

# Handle reset option
if [ "$RESET" = true ]; then
    echo "Performing complete reset..."
    
    # Stop and remove container if exists
    if [ "$(docker ps -a -q -f name=$CONTAINER_NAME)" ]; then
        echo "Stopping and removing container..."
        docker stop $CONTAINER_NAME 2>/dev/null || true
        docker rm $CONTAINER_NAME 2>/dev/null || true
    fi
    
    # Remove image if exists
    if [[ "$(docker images -q $IMAGE_NAME 2> /dev/null)" != "" ]]; then
        echo "Removing Docker image..."
        docker rmi $IMAGE_NAME:latest
    fi
    
    echo "Reset complete!"
    echo ""
fi

# Build the Docker image
echo "Building Claude Flow Docker image..."

DOCKER_BUILD_COMMAND="docker build"
if [ "$NO_CACHE" = true ]; then
    DOCKER_BUILD_COMMAND="$DOCKER_BUILD_COMMAND --no-cache"
fi

# Pass the host user's UID and GID as build arguments
$DOCKER_BUILD_COMMAND -t $IMAGE_NAME \
    --build-arg USER_UID=$(id -u) \
    --build-arg USER_GID=$(id -g) \
    .

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "You can now run ./start.sh to begin"
else
    echo "Build failed!"
    exit 1
fi