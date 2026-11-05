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

---

## Containers inside SwarmBox (nested Podman)

Agents have `sudo` and a full rootless Podman **inside** the container, so they can
provision databases, APIs, etc. without any path to the host's Podman. There is no flag
for it: it is always on.

```bash
podman run -d --name mongo --network dev -p 27017:27017 mongo:7   # inside SwarmBox
```

- **Reach them from the host**: `start.sh` registers a Podman connection named after the
  container (default `swarmbox`) and starts the API service inside. From your host shell:
  ```bash
  podman -c swarmbox ps
  podman -c swarmbox logs mongo
  ```
  (Linux/WSL2 only; unix sockets do not cross the macOS VM.)
- **Publish ports to the host in two hops**: declare the port when starting
  (`./start.sh --ports 27017`) and publish it inside (`-p 27017:27017`; do not bind it to
  `127.0.0.1` inside, or the outer forwarder cannot reach it). `--ports` publishes on the
  host's `127.0.0.1` only; to expose a port on the network, give the full form
  (`--ports 0.0.0.0:27017:27017`).
- **Container-to-container**: create a network (`podman network create dev`) and use the
  container name as hostname.
- **Storage** lives in a named volume (`<container-name>-containers`), not in `.work/`
  (its files are owned by sub-UIDs your user cannot delete). To wipe it:
  `podman volume rm swarmbox-containers`.
- **User IDs**: SwarmBox has ~64k user IDs, so an image whose default user has a higher ID
  (distroless `nonroot` 65532, some `nobody` 65534 images) can be pulled but not run as that
  user: run it with `--user root` (inside SwarmBox that is your own user, not host root).
- **Limits**: nested containers share SwarmBox's hostname (`utsns=host`), and `start.sh`
  needs `/dev/net/tun` and an unmasked `/proc` to create the container. Flags such as
  `--ports` only apply when the container is created, so use `--reset` to change them.

---

## Web terminal (`--web`)

`./start.sh --reset --web` serves the container's shell in a browser (ttyd + tmux, so
sessions survive closing the tab) on `http://127.0.0.1:7681` of your machine. Use
`--web 7682` for a second container.

**That local port has no login.** It is published on `127.0.0.1` only (and ttyd refuses
cross-origin websockets), but anything running on your machine can open it, and the shell
has `sudo`. To reach it from elsewhere, put Cloudflare Access in front of it. Do not use
`--host-network` with `--web` (refused), and do not publish the port on `0.0.0.0`.

### Remote access: Cloudflare Tunnel + Access (email one-time code)

```
browser ── https://swarmbox.example.com ──> Cloudflare Access (email code) ──> tunnel
                                                                         │ outbound only
                                          cloudflared (Podman, this host) ┘──> localhost:7681
```

`cloudflared` runs **on the host, not in the container**, so the tunnel credentials are
never inside the agent's reach. It only makes outbound connections: no router port, no
public IP. Free plan (Zero Trust, up to 50 users); a card may be requested to activate it.

`cloudflare-setup.py` provisions all of it and is **idempotent** (run it again and it only
changes what differs). Python 3.8+, no dependencies:

```bash
export CLOUDFLARE_API_TOKEN=...        # or just run it and paste when asked (input hidden)
./cloudflare-setup.py --domain example.com --email you@example.com
SWARMBOX_WEB_DOMAIN=example.com ./start.sh --reset --web
# open https://swarmbox.example.com and log in with the e-mail code
```

You need a domain on Cloudflare and a one-time **API token**
(<https://dash.cloudflare.com/profile/api-tokens> → Create Custom Token):

| Scope   | Permission                                            | Level |
|---------|-------------------------------------------------------|-------|
| Account | Cloudflare Tunnel                                     | Edit  |
| Account | Access: Apps and Policies                             | Edit  |
| Account | Access: Organizations, Identity Providers, and Groups | Edit  |
| Zone    | DNS                                                   | Edit  |
| Zone    | Zone                                                  | Read  |

Include your account and the zone in the token's resources, and activate Zero Trust once
at <https://one.dash.cloudflare.com>. The token is only read from the environment/prompt:
it is never stored or printed, and you can delete it when the script finishes.

What it sets up, in this order (the login always exists before anything is routable):

1. an *Access policy* allowing only your e-mail(s), and an *Access application* for
   `<name>.<domain>` that offers only the One-time PIN login (session 4h by default);
2. one *Tunnel* per account (`swarmbox`), shared by all your containers, with the route
   `<name>.<domain>` -> `http://localhost:<port>`. The route makes `cloudflared` itself
   require the Access token, so even a mistake in the Access policy cannot expose the shell;
3. the proxied *DNS* record (it refuses to overwrite a non-CNAME record);
4. the `cloudflared` connector as a Podman container (`swarmbox-cloudflared`, restarted
   automatically; rootless Podman restarts it after a reboot only if
   `podman-restart.service` is enabled);
5. a check that the hostname redirects to the Cloudflare login (and a loud error if it
   answers without one).

```bash
./cloudflare-setup.py --dry-run          # read-only: what would change (also checks your token)
./cloudflare-setup.py status             # read-only report + login check
./cloudflare-setup.py --name second --port 7682    # another container: second.example.com
./cloudflare-setup.py remove --name second --yes   # undo one hostname (route first, login last)
./cloudflare-setup.py --help             # --session, --tunnel, --hostname, --no-connector, ...
```

Your domain and e-mails are remembered in `~/.config/swarmbox/cloudflare.json`, so later
runs need no flags. `--domain` is the Cloudflare *zone* (`example.com`), not a subdomain. To
serve a specific name such as `tty.example.com`, add `--hostname tty.example.com` (and start with
`SWARMBOX_WEB_HOSTNAME=tty.example.com` so `start.sh` prints that URL). Keep names
one level below the zone: Cloudflare's free certificate does not cover `a.b.example.com`. To run `cloudflared` yourself (e.g. as a
systemd service), use `--no-connector --print-token`.

Tests (a fake Cloudflare API, no network): `python3 tests/test_cloudflare_setup.py`.

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
