# SwarmBox

**A safe, isolated environment to run AI agents with full tool access and auto-approve mode.**

SwarmBox is a containerized workspace where AI assistants can execute freely without breaking your host system. Built on Podman with an opinionated set of MCP servers and tools that work out of the box—no configuration needed.

**Key Features:**
- 🔒 **Safe Isolation**: AI agents run in a container, protecting your host machine
- ⚡ **YOLO Mode**: Auto-approve workflows (dangerously-skip-permissions) for uninterrupted AI execution
- 🧰 **Batteries Included**: Chrome DevTools MCP, persistent memory service, and dev tools pre-configured
- 🚀 **Seamless DevEx**: Single mount point (`.work/`) with host user permissions—no permission headaches
- 🧠 **Persistent Memory**: Optional semantic memory that remembers context across sessions
- 🔌 **Extensible**: Modular MCP architecture—drop in new servers with zero code changes

---

## Quick Start

```bash
./build.sh                    # Build container
./start.sh                    # Launch without memory
MEMORY=myproject ./start.sh   # Launch with persistent memory
```

Inside the container:
```bash
claude      # Claude Code with auto-approve + MCP servers
gemini      # Gemini CLI with auto-approve
```

---

## Memory Service

Enable **persistent memory** across Claude sessions:

```bash
MEMORY=personal ./start.sh    # Personal knowledge base
MEMORY=work ./start.sh        # Work projects
MEMORY=research ./start.sh    # Research notes
```

Each database is isolated and persists in `.work/.swarmbox/memory/`.

**Web Dashboard**: http://localhost:8889 (when memory is enabled)

---

## Architecture

### Container Structure

```
container/
├── scripts/
│   ├── init.sh              # Orchestrator
│   └── banner.sh
└── mcp/
    ├── chrome-devtools/     # Browser automation MCP
    │   └── config.json
    └── memory/              # Persistent memory MCP
        ├── config.json
        ├── init.sh          # Memory-specific setup
        ├── hooks-config.json
        └── settings.json
```

### Built-in MCP Servers

- **chrome-devtools**: Browser automation and testing
- **memory** (optional): Persistent AI memory with semantic search

### Adding New MCPs

1. Create `container/mcp/your-mcp/config.json`
2. (Optional) Add `container/mcp/your-mcp/init.sh` for custom setup
3. Rebuild: `./build.sh`

Each MCP is self-contained with its own configuration and initialization logic.

---

## Authentication

Pass API keys from your host:

```bash
export GEMINI_API_KEY="your-key"
export CLAUDE_CODE_OAUTH_TOKEN="your-token"

./start.sh --env-keys GEMINI_API_KEY,CLAUDE_CODE_OAUTH_TOKEN
```

Optional model selection:
```bash
export GEMINI_MODEL="gemini-2.0-flash-exp"
export ANTHROPIC_MODEL="claude-sonnet-4-5"

./start.sh --env-keys GEMINI_API_KEY,CLAUDE_CODE_OAUTH_TOKEN,GEMINI_MODEL,ANTHROPIC_MODEL
```

---

## What's Inside

- **AI Assistants**: Claude Code, Gemini CLI (both auto-approve)
- **Memory Service**: mcp-memory-service with sqlite-vec
- **Development Stack**: Node.js 20, Python 3.11 (venv), Poetry, uv
- **Tools**: Git, Podman CLI, Chromium, jq, standard dev tools
- **MCP Framework**: Modular, extensible architecture

---

## Build Options

```bash
./build.sh [OPTIONS]
  --name IMAGE_NAME    # Custom image name (default: swarmbox)
  --no-cache           # Build without cache
  --reset              # Remove existing container/image first
```

---

## Start Options

```bash
./start.sh [OPTIONS]
  --name CONTAINER_NAME              # Custom container name
  --image IMAGE_NAME                 # Custom image name
  --hostname HOSTNAME                # Custom hostname
  --ports PORT_LIST                  # e.g., 3000,8080:80
  --iports PORT_LIST                 # Inverse port mappings
  --env-keys KEY1,KEY2,...           # Pass environment variables
  --reset                            # Recreate container
  --no-shell                         # Don't attach (automation)
  --host-network                     # Use host networking
  --with-unsafe-podman               # Mount host Podman socket ⚠️
```

---

## Workspace

`./work/` is mounted at `/home/agent` inside the container.

All work persists between sessions.

---

## Requirements

- **Podman** (Docker not supported)
  - Linux: `sudo apt install podman` or `sudo dnf install podman`
  - macOS: `brew install podman`

---

## Advanced

### Memory Service Features

- **Semantic search** with sqlite-vec embeddings
- **Quality scoring** with LLM-based evaluation
- **Tag-based organization** for knowledge categorization
- **Natural language retrieval** ("recall what I stored last week")
- **HTTP API** on port 8889 for external access

### MCP Extensibility

Each MCP server:
- Lives in `container/mcp/<name>/`
- Contains `config.json` with server configuration
- Can optionally have `init.sh` for custom initialization
- Automatically integrated by main orchestrator

No code changes needed to add new MCP servers—just drop in config files.

---

Built with ❤️ for AI-assisted development
