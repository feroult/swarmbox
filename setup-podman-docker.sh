#!/bin/bash

# Setup script for Podman on macOS to work with Docker API
# This script configures Podman machine for rootful mode and sets up docker group

set -e

echo "=== Podman Docker API Setup for macOS ==="
echo ""

# Check if Podman is installed
if ! command -v podman &> /dev/null; then
    echo "ERROR: Podman is not installed."
    echo "Install it with: brew install podman"
    exit 1
fi

# Get machine name (default to podman-machine-default)
MACHINE_NAME="${1:-podman-machine-default}"
echo "Using Podman machine: $MACHINE_NAME"
echo ""

# Check if machine exists
if ! podman machine list --format "{{.Name}}" | grep -q "^${MACHINE_NAME}$"; then
    echo "Machine '$MACHINE_NAME' does not exist."
    echo "Creating new Podman machine..."
    podman machine init "$MACHINE_NAME"
fi

# Check if machine is running
MACHINE_RUNNING=$(podman machine list --format "{{.Name}} {{.Running}}" | grep "^${MACHINE_NAME}" | awk '{print $2}')

# Stop machine if it's running and not rootful
MACHINE_ROOTFUL=$(podman machine inspect "$MACHINE_NAME" --format '{{.Rootful}}')
if [ "$MACHINE_ROOTFUL" != "true" ]; then
    echo "Machine is not in rootful mode. Configuring..."

    if [ "$MACHINE_RUNNING" == "true" ]; then
        echo "Stopping machine..."
        podman machine stop "$MACHINE_NAME"
    fi

    echo "Setting machine to rootful mode..."
    podman machine set --rootful "$MACHINE_NAME"

    echo "Starting machine..."
    podman machine start "$MACHINE_NAME"
else
    echo "Machine is already in rootful mode."

    if [ "$MACHINE_RUNNING" != "true" ]; then
        echo "Starting machine..."
        podman machine start "$MACHINE_NAME"
    fi
fi

echo ""
echo "Configuring socket permissions in Podman VM..."

# Make socket world-writable (666) for local dev use
# This allows any container to access the socket without group setup
podman machine ssh "$MACHINE_NAME" "sudo chmod 666 /run/podman/podman.sock"

# Verify permissions
SOCKET_PERMS=$(podman machine ssh "$MACHINE_NAME" "sudo stat -c '%a' /run/podman/podman.sock")

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Summary:"
echo "  - Podman machine '$MACHINE_NAME' is running in rootful mode"
echo "  - Socket permissions: $SOCKET_PERMS (world-writable)"
echo "  - Socket path: /run/podman/podman.sock"
echo ""
echo "Security Note:"
echo "  The socket is world-writable for convenience in local development."
echo "  Any container in the Podman VM can access the Docker API."
echo "  This is acceptable for single-user local dev environments."
echo ""
echo "To use with containers:"
echo "  - Just mount the socket: -v /var/run/docker.sock:/var/run/docker.sock"
echo "  - No Dockerfile changes or runtime setup needed!"
echo ""
