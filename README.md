# SwarmBox

**Run AI agents with full tool access and auto-approve ("YOLO") mode inside a Podman container, so your host stays safe.**

- **Isolated:** agents run in a rootless Podman container; no host Podman socket is mounted.
- **Auto-approve:** `claude` and `gemini` are aliased to their skip-permissions / `--yolo` modes. OpenCode is installed too.
- **Nested Podman:** agents can build and run their own containers inside the box.
- **MCP built in:** headless Chromium via the chrome-devtools MCP.
- **One workspace:** `.work/` is your agents' home directory, owned by your host user, kept between sessions.
- **Web terminal:** optional browser shell (ttyd + tmux), with a Cloudflare Tunnel setup for remote access.

## Quick Start

```bash
./build.sh        # build the image
./start.sh        # create the container and open a shell in it
claude            # inside: Claude Code with auto-approve (or: gemini)
```

## Authentication

Pass keys from your host with `--env-keys`:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="your-token"
export GEMINI_API_KEY="your-key"
./start.sh --env-keys CLAUDE_CODE_OAUTH_TOKEN,GEMINI_API_KEY
```

Any variable can be passed this way (for example `ANTHROPIC_MODEL` or `GEMINI_MODEL`).

## Build options

| `./build.sh` flag | Effect |
|---|---|
| `--name NAME` | Image name (default `swarmbox`) |
| `--no-cache` | Build without cache |
| `--update-harness` | Keep the cache, but reinstall the latest Claude Code and OpenCode |
| `--reset` | Remove the existing container and image first (`.work/` is kept) |

## Start options

| `./start.sh` flag | Effect |
|---|---|
| `--name NAME` / `--image NAME` | Container / image name (default `swarmbox`) |
| `--hostname NAME` | Container hostname |
| `--ports LIST` | Publish ports, e.g. `3000,8080:80`. Bound to `127.0.0.1`; use `0.0.0.0:3000:3000` to expose |
| `--iports LIST` | Inverse mappings: container reaches host ports via `host.podman.internal` |
| `--env-keys K1,K2` | Pass host environment variables into the container |
| `--remote-browser [PORT\|HOST:PORT]` | Point chrome-devtools MCP at an existing Chrome (default port 9222) |
| `--clasp` | Expose port 43323 for the `clasp` OAuth callback |
| `--web [PORT]` | Web terminal on `127.0.0.1:PORT` (default 7681) |
| `--host-network` | Share the host network (ignores `--ports`) |
| `--no-shell` | Do not attach (automation) |
| `--reset` | Recreate the container; `.work/` is kept |

Environment variables (read on the host; they apply when a container is created, so add `--reset` to change an existing one):

| Variable | Effect |
|---|---|
| `SWARMBOX_INIT=0` / `1` | Turn off / force the `--init` process (reaps zombies). Default: on if your podman supports it |
| `SWARMBOX_TZ=Area/City` / `off` | Pick a time zone / keep UTC. Default: your machine's zone (on macOS set it explicitly) |
| `SWARMBOX_ATTACH=shell` | Open plain bash instead of a tmux session |
| `SWARMBOX_STARSHIP=0` | Inside the container: plain bash prompt instead of [Starship](https://starship.rs) |

## Web terminal and remote access

`./start.sh --reset --web` serves the shell at `http://127.0.0.1:7681`. Sessions survive closing the tab. **This local port has no login.** To reach it remotely, use Cloudflare Tunnel + Access, set up by `cloudflare-setup.py`.

- [docs/web-terminal.md](docs/web-terminal.md): style, tmux shortcuts, copy/paste
- [docs/cloudflare.md](docs/cloudflare.md): remote access

## Nested Podman

Agents have `sudo` and rootless Podman inside the container, always on. From the host, `podman -c swarmbox ps` reaches it. Details: [docs/nested-podman.md](docs/nested-podman.md).

## Workspace

`.work/` in the directory where you run `start.sh` is mounted at `/home/agent`. Run `start.sh` from the same directory to reuse a workspace.

## Requirements

- Podman (Docker is not supported): `sudo apt install podman`, `sudo dnf install podman` or `brew install podman`

## Architecture

```
start.sh  build.sh  Dockerfile       # host entry points (start.sh sources lib/)
cloudflare-setup.py                  # remote-access provisioning (host)
lib/                                 # start.sh helpers: ui, podman connection, web terminal, attach-session
docs/                                # nested Podman, web terminal, Cloudflare
container/
├── scripts/                         # init.sh (orchestrator), banner, messages, podman-service, starship-init
├── config/                          # tmux.conf, tmux-browser-keys.conf, starship.toml
├── web/                             # web-terminal.sh, ttyd-clipboard.js, ttyd-style.css
├── opencode/                        # local-LLM config template for OpenCode
└── mcp/
    └── chrome-devtools/     # Browser automation MCP
        └── config.json
```

## Adding an MCP

1. Create `container/mcp/your-mcp/config.json` (the server definition, same shape as `chrome-devtools/config.json`).
2. Optional: add an `init.sh` for setup.
3. Rebuild with `./build.sh`.

Note: `container/scripts/init.sh` currently wires in only chrome-devtools by name, so a new MCP also needs a hook there.
