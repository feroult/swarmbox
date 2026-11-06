# SwarmBox

**A safe, isolated environment to run AI agents with full tool access and auto-approve mode.**

SwarmBox is a containerized workspace where AI assistants can execute freely without breaking your host system. Built on Podman with an opinionated set of MCP servers and tools that work out of the box—no configuration needed.

**Key Features:**
- 🔒 **Safe Isolation**: AI agents run in a container, protecting your host machine (no host Podman socket is ever mounted)
- 📦 **Nested Podman**: Agents can build and run their own containers inside SwarmBox, isolated from the host
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
start.sh  build.sh  Dockerfile       # host entry points (start.sh sources lib/)
cloudflare-setup.py                  # remote-access provisioning (host)
lib/                                 # start.sh helpers: ui, podman connection, web terminal, attach-session
docs/                                # nested Podman, web terminal, Cloudflare
container/
├── scripts/                         # init.sh (orchestrator), banner, messages, podman-service, starship-init
├── config/                          # tmux.conf, tmux-browser-keys.conf, starship.toml
├── web/                             # web-terminal.sh, ttyd-clipboard.js, ttyd-style.css
├── agents/  opencode/
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
- **Tools**: Git, Podman (nested, rootless), Chromium, jq, standard dev tools
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
  --ports PORT_LIST                  # e.g., 3000,8080:80 (published on 127.0.0.1 only;
                                     #  use ip:host:container, e.g. 0.0.0.0:3000:3000, to expose)
  --iports PORT_LIST                 # Inverse port mappings
  --env-keys KEY1,KEY2,...           # Pass environment variables
  --reset                            # Recreate container
  --no-shell                         # Don't attach (automation)
  --host-network                     # Use host networking
  --web [PORT]                       # Web terminal (ttyd + tmux) on 127.0.0.1:PORT (default 7681)
```

Environment: `SWARMBOX_INIT=0` turns off, and `SWARMBOX_INIT=1` forces, the `--init` that `start.sh` gives new
containers (a tiny init as PID 1 that reaps exited processes, so they do not pile up as zombies). By default it
is used when your podman can run it. It only applies when a container is created, so use `--reset` to get it.

Time zone: the image itself runs in UTC, so a new container follows your machine's zone (`--tz=local`, which needs
`/etc/localtime`): the clock in the prompt and `date` match yours. `SWARMBOX_TZ=America/Sao_Paulo` picks another zone
and `SWARMBOX_TZ=off` keeps UTC (with a podman machine on macOS "local" is the VM's zone, so set `SWARMBOX_TZ`).
Like `--init`, it applies when a container is created. To fix a running container without recreating it:
`sudo ln -sf /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime`.

---

## Containers inside SwarmBox (nested Podman)

Agents have `sudo` and a full rootless Podman **inside** the container (always on, no host socket). From your host,
`podman -c swarmbox ps` reaches it. Ports, networks, storage and limits: [docs/nested-podman.md](docs/nested-podman.md).

---

## Web terminal (`--web`)

`./start.sh --reset --web` serves the container's shell in a browser (ttyd + tmux, sessions survive closing the tab) on
`http://127.0.0.1:7681`. Style, tmux shortcuts, copy/paste: [docs/web-terminal.md](docs/web-terminal.md). **That local port has no login**;
to reach it from elsewhere use Cloudflare Tunnel + Access (e-mail one-time code), provisioned by `cloudflare-setup.py`:
[docs/cloudflare.md](docs/cloudflare.md).

---

## Prompt (Starship)

Interactive bash shells in SwarmBox use [Starship](https://starship.rs): a pinned release (`STARSHIP_VERSION` in the
Dockerfile; static binaries for amd64 and arm64) whose published SHA-256 is verified during the build, with the
config in `container/config/starship.toml` (installed as `/etc/swarmbox/starship.toml`).

- **Layout:** Starship's "Gruvbox Rainbow" powerline preset, on a single line closed by an arrow (no separate
  prompt symbol: add `$line_break$character` to `format` if you want one and the red/green exit-status color).
- **Colors:** a deliberately *cool* palette (violet, teal, indigo, pastel blue, slate) unlike the warm Gruvbox one, so a
  SwarmBox shell is never mistaken for your own. Every color is a role name (`color_user`, `color_path`,
  `color_vcs`, ...) defined once in `[palettes.swarmbox]`: recolor there. The tests check that the text stays
  legible on every segment and that no color is hard-coded outside the palette.
- **Icons:** the prompt uses powerline arrows and Nerd Font glyphs, so the terminal needs a Nerd Font (in the
  browser terminal it is the browser's font, see [docs/web-terminal.md](docs/web-terminal.md)).
- **Your own prompt:** a `~/.config/starship.toml` (`.work/.config/starship.toml` on the host) is used *instead* of
  ours, and so is an `STARSHIP_CONFIG` you set. `SWARMBOX_STARSHIP=0` turns Starship off (plain bash prompt).

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
