#!/bin/bash

# Configuration
IMAGE_NAME="claude-flow"
CONTAINER_NAME="claude-flow-session"
WORK_DIR="$(pwd)/.work"
PORTS=""
RESET=false

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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--ports port:inner_port,port:inner_port,...] [--reset]"
            echo "  --ports: Comma-separated list of port mappings (e.g., 3000,8080:80,9000:3000)"
            echo "  --reset: Stop and remove existing container, keeping persistent folders"
            exit 1
            ;;
    esac
done

# Parse port mappings
DOCKER_PORTS=""
if [ -n "$PORTS" ]; then
    IFS=',' read -ra PORT_ARRAY <<< "$PORTS"
    for port_mapping in "${PORT_ARRAY[@]}"; do
        if [[ $port_mapping == *":"* ]]; then
            # Format: port:inner_port
            DOCKER_PORTS="$DOCKER_PORTS -p $port_mapping"
        else
            # Format: port (port == inner_port)
            DOCKER_PORTS="$DOCKER_PORTS -p $port_mapping:$port_mapping"
        fi
    done
fi

# Create directories if they don't exist
mkdir -p "$WORK_DIR"

# Build image if it doesn't exist
if [[ "$(docker images -q $IMAGE_NAME 2> /dev/null)" == "" ]]; then
    echo "Building Docker image..."
    docker build -t $IMAGE_NAME .
fi

# Handle reset option
if [ "$RESET" = true ]; then
    if [ "$(docker ps -a -q -f name=$CONTAINER_NAME)" ]; then
        echo "Resetting container (keeping persistent folders)..."
        echo "Stopping container and killing all connected shells..."
        docker stop $CONTAINER_NAME 2>/dev/null || true
        docker rm $CONTAINER_NAME 2>/dev/null || true
        echo "Container reset complete."
    else
        echo "No existing container found to reset."
    fi
fi

# Check if container already exists
if [ "$(docker ps -a -q -f name=$CONTAINER_NAME)" ]; then
    echo "Container already exists. Connecting to it..."
    docker start $CONTAINER_NAME 2>/dev/null || true
    docker exec -it $CONTAINER_NAME bash
else
    echo "Creating new container..."
    # Create and start container
    docker run -d \
        --name $CONTAINER_NAME \
        -v "$WORK_DIR:/home/agent" \
        $DOCKER_PORTS \
        $IMAGE_NAME
    
    # Connect to the container
    docker exec -it $CONTAINER_NAME bash -c "
        echo 'Welcome to Claude Flow Docker Environment!'
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