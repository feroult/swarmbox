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

**Same tabs in the browser and in your terminal**: the shell `start.sh` opens in your host terminal is a new
window of the same tmux session (`main`) the browser shows, through a grouped session, so each host tab is also a
tab in the browser and the other way round; each side keeps its own current window, and the grouped session goes
away when you close the host tab (the window stays until its shell exits). Nested tmux: if your host terminal also
runs tmux, give it another prefix (SwarmBox uses `C-a`) or press `C-a a` to send the prefix inside.
`SWARMBOX_ATTACH=shell ./start.sh` gives the plain bash instead.

**Font, size, theme**: out of the box the terminal is dark (Windows Terminal's Campbell colors), size 21, with a
Nerd Font list (JetBrainsMono, Cascadia). To change any of it, put `key=value` lines (xterm.js options) in `.work/.swarmbox/web-terminal.conf`
(`~/.swarmbox/web-terminal.conf` inside), e.g. `fontFamily='JetBrainsMono Nerd Font', Consolas, monospace`.
`padding=5` is the space (px) around the terminal, and the scrollbar is a thin translucent one (both are CSS in
`container/ttyd-style.css`, injected into ttyd's page). A `theme` line replaces the whole default theme. No rebuild: run `pkill ttyd; swarmbox-web-terminal` inside to apply (tmux sessions survive). The font is
the *browser's*, so it must be installed on the machine that opens the page.

**tmux.** The image ships a complete default config, `container/tmux.conf` (installed as `/etc/tmux.conf`): prefix
`Ctrl+A`, windows and panes numbered from 1, mouse, 50,000 lines of history, true color, a dark status bar, splits
and new windows in the current directory, and the browser shortcuts below. It stands alone: nothing in your
workspace is needed. Your own `~/.tmux.conf` (`.work/.tmux.conf` on the host) is read *after* it, so add to it or
override anything there (`unbind -n M-n`, `set -g prefix C-b`, another theme).

Ctrl+T/N/W and Ctrl+Shift+T belong to the browser (and xterm.js sends nothing, or only the plain control
character, for most other Ctrl combinations), so `container/tmux-browser-keys.conf` (loaded by the default config)
binds **Alt** instead, without the prefix:
`Alt+N` new window, `Alt+W` close (asks), `Alt+H`/`Alt+L` previous/next, `Alt+1..9`/`Alt+0` jump/last,
`Alt+Shift+H`/`Alt+Shift+L` move, `Alt+R` rename, `Alt+G` list; panes: `Alt+\` and `Alt+-` split, `Alt+arrows` focus,
`Alt+Shift+arrows` resize, `Alt+Z` zoom, `Alt+X` close (asks); and a green **+** button in the status bar creates a
window. Use the left Alt: the right one is AltGr on an international layout. If you use your own tmux config
without ours, add `source-file /path/to/tmux-browser-keys.conf` to it (it needs `set -g base-index 1` so
`Alt+1..9` match the status bar).

**Copy and paste.** With the mouse on, tmux owns the mouse: a selection is copied into tmux's own buffer and
sent to the terminal as OSC 52, but ttyd 1.7.7 ignores OSC 52, so nothing reached the browser clipboard, and
xterm.js sends Ctrl+V to the shell as `^V` instead of pasting. `swarmbox-web-terminal` therefore serves ttyd's
own page with a small script injected (`container/ttyd-clipboard.js`, built from `ttyd-stock.html` in the image):
- a selection (or `tmux set-buffer -w`) **reaches the browser clipboard**. Only *writes* are honoured: a
  clipboard *read* request (`OSC 52 ; ... ; ?`) is never answered, so nothing in the terminal can read what you
  copied elsewhere;
- **`Ctrl+V` pastes** (as `Ctrl+Shift+V` already did), with bracketed paste when the program asked for it;
- **`Ctrl+C` copies while text is selected in the terminal** (`Shift`+drag selects when tmux has the mouse) and
  does not interrupt; with no selection it is still `^C`.
- **Right click** opens only tmux's menu while tmux captures the mouse (the browser's menu used to open on top of
  it). `Shift`+right-click still opens the browser's, and in a plain shell (no mouse capture) the right click keeps
  the browser's menu, so copy and paste stay there.
Set `ctrlVPaste=false` and/or `ctrlCCopy=false` in `web-terminal.conf` to keep `^V` (vim block mode, readline
quoted-insert) or to let `Ctrl+C` always interrupt, then `pkill ttyd; swarmbox-web-terminal`. Tested in Chromium; a
browser that only allows clipboard writes from a user gesture (Firefox) may need the click to be recent.

The image sets `LANG=C.UTF-8` (and `swarmbox-web-terminal` enforces a UTF-8 locale): without one, bash
drops an accented character typed on its own (a dead key + letter) instead of inserting it.

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

**Two different credentials.** The *API token* above is powerful and only needed to provision: delete it
once the script finishes. The connector needs only the tunnel's own, much narrower *tunnel token*.

**Bring the tunnel up with `--web`, using only the tunnel token.** Put the tunnel's token in an environment
variable **on the host** (the Cloudflare dashboard shows it: Networking -> Tunnels -> your tunnel; in older
UIs Zero Trust -> Networks -> Tunnels. Or
`./cloudflare-setup.py token`, which prints **only** that token, so it can be used in `$(...)`; it still needs the
API token once, so run it *before* deleting the API token):

```bash
export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN='...'     # e.g. in ~/.zshrc or ~/.bashrc
# or: export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN="$(./cloudflare-setup.py token --domain example.com)"
./start.sh --web
```

`--web` is only needed to *create* the container (together with `--reset`). Once it exists, both `./start.sh`
and `./start.sh --web` recognise it as a web container (it carries `SWARMBOX_WEB=1` and publishes the
terminal port), accept the flag, use the port it really publishes, and make sure the terminal and the tunnel
are up, for instance after the machine restarted. A container created *without* `--web` still refuses it
(the port could not be added), and its connector is never looked at.

Every time, the tunnel is brought up with no API token:
a missing `swarmbox-cloudflared` container is **created**, a stopped one is **started**, and one holding a
different token (after you rotate it) is **recreated**. Without the variable, an existing connector is just
started if it is stopped. The connector is a Podman container on your host (not inside SwarmBox); the token
goes to Podman through the environment (never a command line), is never printed, and is **never passed to
SwarmBox**: `--env-keys SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` is refused, because the token lets whoever holds
it join your tunnel and receive requests that already passed the login. `SWARMBOX_CLOUDFLARED_IMAGE`
overrides the `cloudflared` image.

**Rotating the tunnel token.** On the tunnel's page in the dashboard, the refresh-token button invalidates the
current token and generates a new one (every connector must then use the new token). Put the new value in
`SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` and run `./start.sh --web`: it notices that the connector holds a different
token and recreates it. Rotate if the token may have been exposed, e.g. if it ever ran inside SwarmBox.

Tests (a fake Cloudflare API and a fake podman, no network):
`python3 tests/test_cloudflare_setup.py`, `python3 tests/test_start_web_connector.py`.

---

## Prompt (Starship)

Interactive bash shells in SwarmBox use [Starship](https://starship.rs): a pinned release (`STARSHIP_VERSION` in the
Dockerfile; static binaries for amd64 and arm64) whose published SHA-256 is verified during the build, with the
config in `container/starship.toml` (installed as `/etc/swarmbox/starship.toml`).

- **Layout:** Starship's "Gruvbox Rainbow" powerline preset, on a single line closed by an arrow (no separate
  prompt symbol: add `$line_break$character` to `format` if you want one and the red/green exit-status color).
- **Colors:** a deliberately *cool* palette (violet, teal, indigo, pastel blue, slate) unlike the warm Gruvbox one, so a
  SwarmBox shell is never mistaken for your own. Every color is a role name (`color_user`, `color_path`,
  `color_vcs`, ...) defined once in `[palettes.swarmbox]`: recolor there. The tests check that the text stays
  legible on every segment and that no color is hard-coded outside the palette.
- **Icons:** the prompt uses powerline arrows and Nerd Font glyphs, so the terminal needs a Nerd Font (in the
  browser terminal it is the browser's font, see above).
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
