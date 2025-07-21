#!/bin/bash

# Container runtime configuration script
# This script detects and sets up the container runtime (Docker or Podman)

# Default to Podman
RUNTIME="podman"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to detect and validate runtime
detect_runtime() {
    local requested_runtime="$1"
    
    if [ -n "$requested_runtime" ]; then
        # User specified a runtime
        case "$requested_runtime" in
            docker|podman)
                if command_exists "$requested_runtime"; then
                    RUNTIME="$requested_runtime"
                else
                    echo "Error: Requested runtime '$requested_runtime' is not installed"
                    exit 1
                fi
                ;;
            *)
                echo "Error: Invalid runtime '$requested_runtime'. Use 'docker' or 'podman'"
                exit 1
                ;;
        esac
    else
        # Auto-detect runtime (prefer Podman, fallback to Docker)
        if command_exists podman; then
            RUNTIME="podman"
        elif command_exists docker; then
            RUNTIME="docker"
        else
            echo "Error: Neither Podman nor Docker is installed"
            exit 1
        fi
    fi
}

# Function to get runtime-specific commands
get_runtime_command() {
    echo "$RUNTIME"
}

# Function to handle runtime-specific differences
get_build_command() {
    case "$RUNTIME" in
        podman)
            # Podman-specific build options can be added here
            echo "podman build"
            ;;
        docker)
            echo "docker build"
            ;;
    esac
}

get_run_command() {
    case "$RUNTIME" in
        podman)
            # Podman-specific run options
            echo "podman run"
            ;;
        docker)
            echo "docker run"
            ;;
    esac
}

# Export functions for use in other scripts
export -f command_exists
export -f detect_runtime
export -f get_runtime_command
export -f get_build_command
export -f get_run_command