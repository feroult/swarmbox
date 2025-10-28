# Swarm Box

Containerized development environment with Claude Code and Gemini CLI running on Podman.

## Quick Start

```bash
./build.sh              # Build image
./start.sh              # Start container
claude                  # Claude Code with auto-approve
gemini                  # Gemini CLI with auto-approve
```

## Authentication

Pass your API keys and tokens to pre-authenticate both AI assistants:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
export CLAUDE_CODE_OAUTH_TOKEN="your-claude-oauth-token"
export GEMINI_MODEL="gemini-2.0-flash-exp"          # Optional
export ANTHROPIC_MODEL="claude-sonnet-4-5"          # Optional

./start.sh --env-keys GEMINI_API_KEY,CLAUDE_CODE_OAUTH_TOKEN,GEMINI_MODEL,ANTHROPIC_MODEL
```

Or do it in one line:

```bash
./start.sh --env-keys GEMINI_API_KEY,CLAUDE_CODE_OAUTH_TOKEN,GEMINI_MODEL,ANTHROPIC_MODEL
```

The `--env-keys` flag passes environment variables from your host into the container.

## What's Inside

- **Claude Code** - Auto-approve mode, chrome-devtools MCP server
- **Gemini CLI** - Auto-approve mode (yolo)
- **Development Stack** - Node.js 20, Python 3.11, Poetry
- **Tools** - Git, Podman CLI, Chromium, standard dev tools

## Build Options

```bash
./build.sh [OPTIONS]
  --name IMAGE_NAME    # Custom image name (default: swarmbox)
  --no-cache           # Build without cache
  --reset              # Remove existing container/image first
```

## Start Options

```bash
./start.sh [OPTIONS]
  --name CONTAINER_NAME              # Custom container name (default: swarmbox)
  --image IMAGE_NAME                 # Custom image name (default: swarmbox)
  --hostname HOSTNAME                # Custom hostname (default: swarmbox)
  --ports PORT_LIST                  # e.g., --ports 3000,8080:80
  --iports PORT_LIST                 # Inverse port mappings to host
  --env-keys KEY1,KEY2,...           # Pass environment variables from host
  --reset                            # Recreate container, keep .work data
  --no-shell                         # Don't attach to shell (automation)
  --with-unsafe-podman               # Mount host Podman socket (USE WITH CAUTION)
```

## Workspace

Your work directory `./.work/` is mounted at `/home/agent` inside the container. All files persist between sessions.

## Requirements

- Podman (Docker support removed)
  - **Linux**: `sudo apt install podman` or `sudo dnf install podman`
  - **macOS**: `brew install podman`
