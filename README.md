# Swarm Box

Containerized development environment with Claude CLI. Supports Docker and Podman.

## Quick Start

```bash
./build.sh              # Build image
./start.sh              # Start container
yolo                    # Inside container: authenticate and use Claude
```

## Build Options

```bash
./build.sh [OPTIONS]
  --runtime docker|podman    # Default: podman, falls back to docker
  --name IMAGE_NAME          # Default: swarmbox
  --no-cache                 # Build without cache
  --reset                    # Remove existing containers/images first
```

## Start Options

```bash
./start.sh [OPTIONS]
  --runtime docker|podman    # Default: podman, falls back to docker
  --name CONTAINER_NAME      # Default: swarmbox
  --image IMAGE_NAME         # Default: swarmbox
  --hostname HOSTNAME        # Default: swarmbox
  --ports PORT_LIST          # e.g., --ports 3000,8080:80
  --iports PORT_LIST         # Inverse mappings to host.docker.internal
  --reset                    # Reset container, keep persistent data
  --no-shell                 # Don't attach to shell (automation/testing)
```

## Testing

```bash
./test.sh
```

## What's Included

- Claude CLI with chrome-devtools MCP server
- Node.js 20, Python 3, Poetry
- Git, Docker CLI, Chrome
- Standard development tools

## Workspace

`./.work/` is mounted at `/home/agent` inside the container.
