# Swarm Box

A containerized development environment for AI-powered coding with Claude, supporting both Docker and Podman.

## Features

- 🐳 **Multi-runtime**: Supports Docker and Podman with automatic detection
- 🔒 **Isolated environment** for safe AI development 
- 💾 **Persistent workspace** that survives container restarts
- 🤖 **Claude integration** with MCP (Model Context Protocol) support
- 🎭 **Playwright automation** for browser testing and interaction
- 🛠️ **Complete toolchain**: Git, Node.js, Python, and essential development tools

## Quick Start

### 1. Build the Image

```bash
./build.sh                    # Uses Podman by default, falls back to Docker
./build.sh --runtime docker   # Force Docker instead
```

### 2. Start Container

```bash
./start.sh                    # Uses Podman by default, falls back to Docker
./start.sh --name my-project  # Custom container name
./start.sh --runtime docker   # Force Docker instead
```

### 3. Setup Claude (Inside Container)

```bash
# Authenticate with Claude
claude --dangerously-skip-permissions

# Initialize your project
flow_init  # Alias for: npx claude-flow@alpha init --force
```

## Configuration Options

### Build Script
```bash
./build.sh [OPTIONS]
  --runtime docker|podman    # Container runtime (default: podman)
  --name IMAGE_NAME          # Custom image name (default: swarm-box)
  --no-cache                 # Build without cache
  --reset                    # Remove existing containers/images first
```

### Start Script
```bash
./start.sh [OPTIONS]
  --runtime docker|podman    # Container runtime (default: podman)
  --name CONTAINER_NAME      # Custom container name (default: swarm-box)
  --image IMAGE_NAME         # Custom image name (default: swarm-box)
  --ports PORT_LIST          # Port mappings (e.g., --ports 3000,8080:80)
  --reset                    # Reset container before starting
```

## Built-in Tools

- **AI Development**: Claude CLI, claude-flow, MCP servers
- **Browser Automation**: Playwright, Chromium
- **Development**: Git, Node.js, Python, build tools
- **System**: vim, htop, jq, curl, and essential Linux utilities

## Testing

Run the test suite to verify both Docker and Podman work correctly:

```bash
./test.sh
```

## Workspace

Your work directory (`./.work/`) is mounted inside the container at `/home/agent`, ensuring files persist between container restarts.