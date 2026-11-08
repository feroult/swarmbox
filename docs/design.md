# SwarmBox design

Status: **proposal** for the open-source version. Sections say whether something **exists today** (as of tag `v0.1.0`)
or is **proposed**. Nothing proposed here is implemented yet, and nothing proposed has been tested unless it says so.

SwarmBox is a persistent, safe-by-default sandbox for running coding agents in auto-approve ("YOLO") mode on your own
machine. It is one long-lived rootless Podman container with a workspace folder on your host. You enter it from any
terminal tab or from a browser, and every entry lands in the same session. The agent gets full tool access inside the box;
your host only sees the workspace folder.

**Paths in this document.** `host:~/...` is a path on your machine. `<workspace>/...` is a path inside the workspace folder; inside the
box the workspace is `/home/agent`, so `<workspace>/.config/swarmbox/` is seen there as `~/.config/swarmbox/`. `box:/...` is a path in the
container's own filesystem, which does not survive a `reset`. A bare `~` is not used for documented paths.

---

## 1. Goals and non-goals

Goals
- A new user is productive with one install command and one command to enter the box.
- The box is **persistent**: it keeps running, and every terminal tab and browser tab shares the same tmux session.
- The image is **neutral**: it ships no agent. Claude Code, Gemini CLI, OpenCode and others are installed on demand.
- Remote access (browser, from anywhere) is part of the product, through Cloudflare, with one setup command.
- The user can read everything that will run on their host before it runs.
- Every optional capability (remote access, remote browser, cloud CLIs) is a module they turn on. Nested Podman is not optional: it is always on, as today.
- Versions are pinned and reproducible; updating is a choice. The exception is a tool that updates itself by design
  (Claude Code): that is explicit in its manifest (`UPDATE=self`, section 5.7).

Non-goals
- It does not make an agent trustworthy. It reduces the blast radius (section 10); it does not remove it.
- It is not a multi-user server: one box belongs to one person.
- Windows without WSL2 is not a target. macOS (through a Podman machine) is in scope for the first release; its support is written
  from the code and has not been run on a Mac yet.
- Docker is not supported (the nested-Podman and user-namespace features are Podman's).
- There is no host-network mode (dropped on purpose; section 3.9).

## 2. Principles

1. **One persistent box.** The container keeps running between uses. Entering it never creates a second one: a second tab
   joins the existing session. The box can be recreated (`reset`) without losing the workspace.
2. **Neutral image, tools on demand.** The image holds the shell environment. Agents and large CLIs (gcloud, clasp, Go...)
   are installed the first time they are needed, into the home folder, which is the workspace.
3. **Small core, opt-in modules.** The core runs the box and keeps a workspace. Everything else is a module in its own
   folder with a manifest.
4. **Data over code.** A tool, an agent or an MCP server is a directory with a manifest and, if needed, an install script.
   Adding one needs no change to the core. (MCP servers are not there yet: today `init.sh` names chrome-devtools in code;
   3.8 makes them a registry.)
5. **One trust anchor.** The image is the only artifact a user must trust. The shell function that drives it is *printed by
   the image* (`init`), so it is versioned, signed and readable before it is installed.
6. **Transparent by default.** What gets added to the user's shell is a short block they can read. No hidden downloads on
   the host.
7. **Persist in one place.** Everything inside the box that must survive (projects, login, SSH key, installed tools, in-box
   config) lives in the workspace folder, mounted as `/home/agent`. The container is replaceable; the workspace is not.
   Settings that belong to the host (the creation-time configuration, optional secrets) live in `host:~/.config/swarmbox/`.
8. **Credentials that reach the internet stay on the host.** The Cloudflare tunnel connector and its credentials run outside
   the box, so an agent in the box cannot read them.
9. **Honest security.** The threat model is written down (section 10) and defaults are conservative: nothing published
   beyond `127.0.0.1`, no remote login without Cloudflare Access in front.
10. **Pinned and reproducible.** Every download has a version, and a checksum where the publisher provides one. "latest"
    is an explicit choice, never an accident of layer caching. A tool may opt out by declaring `UPDATE=self`; that is
    written in its manifest and listed in the security model.
11. **Progressive disclosure.** Default: one function, `swarmbox`. More: settings in one config file (3.8), written by
    `init` flags. Extra: a throwaway mode (`swarmbox --once`). There is no second entry point: `start.sh` and `build.sh` are
    retired once the function reaches parity (3.9).

## 3. User model (proposed)

This is what `start.sh` already does today: a persistent container and a shared tmux session (with or without `--web`), plus
the web terminal and optional Cloudflare access with `--web`. The proposal replaces the scripts with one function and a public
image, and keeps every feature that section 3.9 does not list as a proposed removal.

### 3.1 Install, once

```bash
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude          # prints the function; read it first
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude >> ~/.bashrc
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude --workspace ~/code/box >> ~/.bashrc   # choosing the workspace folder
```

- `init --with a,b` records `SWARMBOX_WITH=a,b`: tools to have ready. They are installed the first time the box starts.
- `init --workspace DIR` chooses the workspace folder (3.4). Without it, the workspace is `host:~/swarmbox`. The path is made absolute and
  written to the host config as `WORKSPACE`; the folder is created on the first start.
- `init --shell zsh|fish` prints the right syntax.
- The function sits between markers (`# >>> swarmbox 1.2.0 >>>` ... `# <<< swarmbox 1.2.0 <<<`), so a later `init` replaces
  it instead of duplicating it.

### 3.2 Use

```bash
swarmbox                 # enter the box: create and start it if needed, otherwise join the running one
claude                   # inside: first call installs Claude Code into the home, then runs it
yolo                     # inside: start the default agent in auto-approve mode
swarmbox claude          # enter and run the agent directly
swarmbox url             # where the browser reaches the box (local, and remote when configured)
swarmbox remote setup    # one-time Cloudflare setup (section 4)
swarmbox remote status   # is the tunnel up, which URL, how long the login lasts
swarmbox remote off      # stop exposing the box
swarmbox stop            # stop the box; nothing is deleted
swarmbox reset           # recreate the box; the workspace is kept, running sessions end
swarmbox update          # pull the newest image, then reset when you say so
swarmbox up              # create and start the box without entering it (automation; replaces --no-shell)
swarmbox --plain         # enter with plain bash instead of the tmux session (replaces SWARMBOX_ATTACH=shell)
swarmbox config set|get|list   # the host configuration (section 3.8)
swarmbox pubkey          # SSH public key for git (deploy keys)
swarmbox env add NAME    # pass the host variable NAME into the box (applies when the box is created; section 3.7)
swarmbox env rm NAME     # stop passing it
swarmbox env list        # the names being passed, and whether each is set in this terminal (never the values)
swarmbox env set NAME    # optional: store a value on the host as a fallback for creation (section 3.7)
swarmbox --once          # throwaway container for the current folder, removed on exit (no session sharing)
```

### 3.3 One session for every entry point

- The first `swarmbox` creates a container named `swarmbox`, detached, and enters it.
- Entering uses a new window of the tmux session `main` through a *grouped* session: every terminal tab, and the browser, is a
  window of the same session. Each side keeps its own current window. The grouped session ends when a tab closes; the windows
  and what runs in them stay until their shells exit. This is `lib/attach-session.sh` today.
- A host terminal tab has no tmux status bar (so a host that already runs tmux does not show tabs inside tabs); the browser
  keeps it.
- Closing every tab, or the browser, does not stop anything. `swarmbox stop` does.

### 3.4 The workspace

- One box has one workspace: a folder on the host, mounted as `/home/agent` (called the *home* when seen from inside the box).
- It is chosen once, at install, with `init --workspace DIR`; without it, `host:~/swarmbox`. The path is stored in the host config
  (`WORKSPACE`), so where you run `swarmbox` no longer matters. (Today it is `.work/` in the current directory.)
- Creation-time options (workspace, ports, hostname, time zone, variables...) apply when the box is created; to change them,
  `swarmbox reset`.
- A second box is possible with `SWARMBOX_NAME=other SWARMBOX_WORKSPACE=...`, with its own web port.

What is inside the workspace. Everything the box must keep lives there, because it is the home. The tool and agent dotfiles are whatever
those programs create; the `swarmbox` folders follow the XDG layout (3.8):

```
host:~/swarmbox/                       # the workspace = /home/agent in the box
├── my-project/                        # your projects
├── .ssh/                              # the SSH key (id_ed25519, id_ed25519.pub)
├── .claude/, .claude.json             # Claude Code: login, settings, history
├── .gitconfig                         # if you set a git identity inside the box
├── .config/swarmbox/                  # config you edit: web-terminal.conf, user-level tool manifests
├── .local/share/swarmbox/             # data: tools/ (claude, gcloud...), shims/
├── .local/state/swarmbox/             # state: logs, podman.sock
└── .local/share/containers/           # empty here: the nested Podman storage is a volume (below)
```

What is **not** in the workspace folder:
- **The host configuration**, on your machine: `host:~/.config/swarmbox/config`, `host:~/.config/swarmbox/cloudflare.json` and the optional
  `host:~/.config/swarmbox/secrets/env`, plus the host helper in `host:~/.local/share/swarmbox/host/`. They share names with
  `<workspace>/.config/swarmbox/` because both follow XDG, but they are different places: the host one is read before the box exists (it
  holds `WORKSPACE` itself), the other lives inside the workspace.
- **The nested Podman storage**: the volume `<name>-containers`, mounted at `<workspace>/.local/share/containers`. It appears as an empty
  folder in the workspace; its contents live in the Podman volume, because they are owned by subuid-mapped IDs that the host user could
  not delete and they grow large.
- **Files regenerated at every start**: `box:/tmp/swarmbox/` (the assembled web page, the OpenCode config, locks). They are not in the
  workspace so they do not clutter it or a backup; a reset discards them and the next start recreates them.
- **The container's own filesystem**: anything installed with `apt` or written to `box:/usr`, `box:/etc`, `box:/opt`, plus running
  processes and tmux sessions. A `reset` discards them (5.11).

Two things to watch with this layout:
- Cache directories of other programs under `<workspace>/.cache` (for example pip's) also live in the workspace and keep growing; they
  are safe to delete. SwarmBox itself keeps nothing there.
- The host reaches nested Podman through a unix socket (`podman -c <name>`). Today it is `<workspace>/.swarmbox/podman.sock`; with the XDG
  layout it is `<workspace>/.local/state/swarmbox/podman.sock`, about 14 characters longer. Unix socket paths are limited to roughly
  108 bytes, so a very deep workspace path could break the connection. The default `host:~/swarmbox` is far from that limit; the function
  should check the length and fall back to a short symlink if needed. (Not measured.)

### 3.5 The generated function

A simplified sketch of what `init` prints (the real one also handles `remote`, `url`, `update`, `--once`, and the shell
variants):

```bash
# >>> swarmbox 1.2.0 >>>
swarmbox() {
  local name="${SWARMBOX_NAME:-swarmbox}" img="ghcr.io/<org>/swarmbox:1.2.0"
  case "$1" in
    stop)  podman stop "$name"; return ;;
    reset) podman rm -f "$name" ;;
  esac
  podman container exists "$name" || podman run -d --name "$name" \
    $(swarmbox-create-flags) "$img" serve     # every creation-time flag, from the host config (3.8)
  podman start "$name" >/dev/null
  podman exec -it -e TERM -e COLORTERM "$name" swarmbox-attach "$@"
}
# <<< swarmbox 1.2.0 <<<
```

- `swarmbox-create-flags` prints one flag per creation-time setting (3.8): the workspace mount, `--hostname`, `--tz`, `--init`,
  `--pids-limit=16384`, a `-p` per published port, the nested-Podman flags (always), `-e NAME` per listed variable (3.7), the fingerprint
  labels, and the user namespace. On macOS it adds `--security-opt label=disable` and an explicit
  `keep-id:uid=<host>,gid=<host>` (a platform adapter, in scope for the first release; to be tested on a Mac). Among them, `--userns=keep-id:uid=1000,gid=1000` maps the host user to the image's fixed user (UID 1000), so one image serves every host
  UID. The agent user must not be root: Claude Code refuses auto-approve as root. (Accepted by Podman 4.3 here; a host UID other
  than 1000 has not been tested.)
- `serve` is the container's main process (section 7); `swarmbox-attach` is what joins the tmux session (3.3). Anything typed
  after `swarmbox` that is not a host-side command (`stop`, `reset`, `url`, `remote`, `update`) reaches `swarmbox-attach`,
  so `claude`, `pubkey`, `tool ...` need no host logic.

### 3.6 Host-side configuration

Host-side settings live in `host:~/.config/swarmbox/config` (`KEY=VALUE`), written by `init` and `remote setup`. Environment
variables override it. Nothing about Cloudflare is ever passed into the box.

### 3.7 Environment variables and keys (proposed; same behavior as `start.sh --env-keys` today)

Keys and settings the box needs (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, a model name...) are passed **when the box is created**,
and only then. The first `swarmbox`, the one that creates the box, takes the values from its own environment at that moment;
a box that already exists keeps what it was created with, and other terminals that enter it pass nothing. To pick up a change,
recreate it: `swarmbox reset`.

How it works
- The **names** are stored on the host, in `host:~/.config/swarmbox/config` (`ENV_KEYS=ANTHROPIC_API_KEY,GEMINI_API_KEY`), not typed
  on every command. At creation the function turns each name into `-e NAME` without a value, so Podman reads it from the
  environment of the terminal that runs `swarmbox`. Today `start.sh` puts `-e NAME=value` on the command line (the value shows
  in `ps`, and a value with spaces breaks the unquoted expansion); `-e NAME` keeps the value off the command line. This file
  holds no values.
- `swarmbox env add NAME`, `env rm NAME` and `env list` edit and show the list. `list` prints each name and whether it is
  `set` or `not set` in the current terminal; never the value.
- **Names listed but not set:** if a listed name is not set in the terminal that creates the box, the function warns before
  creating it ("ANTHROPIC_API_KEY is listed but not set in this terminal; the box will start without it"). Podman would pass
  nothing and say nothing.
- A name must look like an environment variable. Names that belong to the host side are refused: anything starting with
  `SWARMBOX_CLOUDFLARE_` (the tunnel token must never enter the box; today `start.sh` refuses only the exact name
  `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN`, so this is stricter).
- On creation the function stores a hash of the passed values as a label on the container (`swarmbox.env-hash`, one part of the creation fingerprint of 3.8). On every
  entry it recomputes the hash from the host and, if it differs, prints one line: "the variables changed on the host; run
  `swarmbox reset` to apply them". The values themselves are never stored for this; only the hash is.

Where the values come from, and the gap
- By default the source is the host environment, so it is up to the user to keep the variables exported (a shell startup file,
  a password manager, a tool such as direnv). SwarmBox stores nothing.
- The gap: `swarmbox reset` re-reads the host environment. If a variable is no longer exported in that terminal, the new box starts
  without it. Claude Code's own login is not affected: it lives in `<workspace>/.claude` in the workspace and survives a reset.
- **Optional fallback (proposed, undecided: open question 15):** `swarmbox env set NAME` asks for the value without echoing it and
  writes it to `host:~/.config/swarmbox/secrets/env`, a plain `NAME=value` file, one per line, no `export`, no quotes, mode `600`:

  ```
  ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
  GEMINI_API_KEY=AIzaxxxxxxxxxxxx
  ```

  At creation, for each listed name the value is the host environment's if set, otherwise this file's. The function hands it to
  Podman through the environment of the `podman` process, not on the command line, so it does not show in `ps`. The file is
  read only at creation; it is not mounted into the box. It keeps the keys in plain text on the host, readable by the user,
  and must never be shared or committed. Unlike exporting keys from a shell startup file, it does not put them in the environment
  of every terminal the user opens.

What stays as it is today, stated so nobody assumes more:
- The values live in the container's configuration (`podman inspect` shows them) and in the environment of every process in
  the box. The agent can read them. Scoped, minimal tokens are the user's protection, not the sandbox.
- A tool does not get its own subset: every process sees every listed name.
- The browser terminal and the host tabs should see the same values: all windows are created by the tmux server that started
  inside the box with the environment it was created with. (Expected from how process environments are inherited; not
  measured, see the tmux note below.)

Alternatives considered, and why they are not the default:
- *Pass the host value on every entry* (`podman exec -e NAME`): works for host tabs (checked: the value follows a change on
  the host, and does not appear in `podman inspect`), but browser windows and remote access come from the tmux server, not from
  the entering command, so they would not follow it. How tmux inherits the environment for new windows was **not** measured
  (an attempt was run against the wrong tmux server and is void).
- *A secrets file mounted into the box* and *Podman secrets*: keep values out of `podman inspect`, but add machinery for
  a property the model above already gives up on purpose (the agent reads the keys either way).
- *A credential proxy on the host* that adds authentication to requests so the box never holds the key: the only option that
  protects the key from the agent; it is a larger piece of work and is listed in the roadmap as optional.

### 3.8 Features and configuration, normalized

Every capability is classified once and configured one way. The rules:

1. **Three layers.** *Image*: what is installed. *Creation*: what the box is created with (mounts, ports, hostname, time zone,
   environment...). *Runtime*: what changes inside without recreating the box (tools, in-box config files). A
   feature lives in exactly one layer; a creation-layer feature changes with `swarmbox reset`, a runtime one does not.
2. **One configuration surface.** The host file `host:~/.config/swarmbox/config` (keys below). `init` flags only write keys;
   `swarmbox config set|get|list` edit them; an environment variable `SWARMBOX_<KEY>` overrides a key. No feature has a flag
   syntax of its own.
3. **One creation fingerprint.** At creation the function stores the creation-layer settings as labels on the container
   (`swarmbox.fingerprint`, plus readable labels for the image, workspace and ports). Every entry compares the current config with
   them and says what differs. This replaces today's separate warnings (creation flags ignored on an existing box, stale image,
   different workspace mount) and the env hash of 3.7.
4. **One layout (XDG), and one question per file: must it survive a reset, and must the host reach it?**
   - Survives, and you edit it: `<workspace>/.config/swarmbox/` (`web-terminal.conf`, user-level tool manifests).
   - Survives, and was installed: `<workspace>/.local/share/swarmbox/` (`tools/`, `shims/`).
   - Survives, or the host must reach it: `<workspace>/.local/state/swarmbox/` (logs, and `podman.sock`, the one file the host has to reach).
   - Regenerated at every start, so it does not need to survive: `box:/tmp/swarmbox/` (the assembled web page, the OpenCode config, locks).
   There is no `.cache/swarmbox`. The layout replaces `<workspace>/.swarmbox/`; the first start of the new image migrates the old files
   (section 11). Every script reads these paths from one file, `container/scripts/dirs.sh`, which honors `XDG_CONFIG_HOME`,
   `XDG_DATA_HOME` and `XDG_STATE_HOME`; tests point those at temporary folders. All the `<workspace>` paths sit inside the workspace (3.4).
5. **One registry for MCP servers.** `container/mcp/<name>/config.json`. `serve` generates `<workspace>/.claude/mcp-servers.json` from every
   enabled server (today it names chrome-devtools in code). `BROWSER_URL` swaps chrome-devtools from a local headless Chromium to
   a remote Chrome. An agent manifest can ask for a mirrored copy in its own format (`MCP_FORMAT=opencode` replaces today's
   `sync_opencode_mcp`).

Creation-time keys (host config), with what each replaces:

| Key | Default | Replaces today |
|---|---|---|
| `NAME` | `swarmbox` | `--name` |
| `WORKSPACE` | `host:~/swarmbox` (set with `init --workspace DIR`) | `.work/` in the current directory |
| `HOSTNAME` | `swarmbox` | `--hostname` |
| `TZ` | `local` (or `off`, or `Area/City`) | `SWARMBOX_TZ` |
| `INIT` | `auto` (or `0`, `1`) | `SWARMBOX_INIT` (the `--init` that reaps zombies) |
| `PORTS` | empty | `--ports`: bound to `127.0.0.1` unless an address is given, with a warning for `0.0.0.0` |
| `HOST_ACCESS` | `0` | `--iports` (today the port numbers are ignored: it only adds `host.containers.internal:host-gateway`) |
| `WEB`, `WEB_PORT` | `1`, `7681` | `--web [PORT]` |
| `BROWSER_URL` | empty | `--remote-browser [PORT\|HOST:PORT]` (a bare number means `host.containers.internal:PORT`) |
| `ENV_KEYS` | empty | `--env-keys` (3.7) |
| `WITH` | empty | tools to have ready (5) |
| `PORTS` from manifests | none | `--clasp` (the clasp manifest declares `PORTS=43323`) |
| `LOCAL_LLM_URL`, `_MODEL`, `_KEY`, `_CONTEXT`, `_OUTPUT` | unset | the same variables today; read by the `opencode` tool's `shell.sh` (5.6) |

Always applied, not configurable: the user namespace (`keep-id`), `--pids-limit=16384`, `-e TERM -e COLORTERM` on every entry, and
nested Podman: `--device /dev/net/tun`, `--security-opt unmask=/proc/*`, the volume `<name>-containers` for its storage, and the host
connection `podman -c <name>` that the function registers (Linux and WSL only; unix sockets do not cross the macOS VM). If the host has
no `/dev/net/tun`, creation stops with a clear message, as `start.sh` does today.
Runtime: `SWARMBOX_STARSHIP=0` (plain prompt) and `swarmbox --plain` (plain bash instead of tmux).

Feature catalog: what each capability is, and where it lives.

| Area | Feature | Class | Layer |
|---|---|---|---|
| Box | Persistent container, enter-or-create, stop, reset, update, up | core | creation |
| Box | Shared tmux session for host tabs and browser; no status bar on host tabs | core | runtime |
| Box | Workspace mount, fixed user with `sudo`, `--init`, pids limit, hostname, time zone, UTF-8 locale | core | creation |
| Box | Creation fingerprint, stale-image and startup-health warnings | core | creation |
| Box | Environment variables and keys (3.7) | core | creation |
| Shell | Starship, banner, aliases (`ls`, `ll`, `la`, `l`, `grep`), `<workspace>/.local/bin` on `PATH`, `/opt/flow` venv with the `(swarmbox)` prompt, `uv` | core | image |
| Shell | tmux configuration and the Alt shortcuts, clipboard bridge | core | image |
| Git | SSH key, `swarmbox pubkey`, trust on first use for GitHub, GitLab, Bitbucket | core | runtime |
| Web | Web terminal (ttyd), on by default on `127.0.0.1` | module | creation |
| Web | Remote access through Cloudflare (`swarmbox remote ...`), host side | module | host |
| Containers | Nested Podman (always on), with the host connection | core | creation |
| Browser | chrome-devtools MCP: local headless Chromium, or a remote Chrome (`BROWSER_URL`) | module | creation |
| Network | Published ports, host access | module | creation |
| Tools | claude (self-updating), gemini, opencode (with its local-LLM hook), gcloud, clasp, Go, Poetry | tool | runtime |

### 3.9 Proposed removals (to validate together)

Nothing here is applied until it is agreed. Each row says what goes, what replaces it, and why.

| Item | Proposal | Reason |
|---|---|---|
| `--host-network` | Remove | Decided. It conflicts with `--web` (refused today), removes the network isolation, and `PORTS` covers publishing. |
| `start.sh`, `build.sh`, `lib/` | Retire after parity | The function replaces them. Two entry points double the tests and the docs. Parity is checked row by row against 3.8. The image is built with `podman build` (documented in `CONTRIBUTING.md`). |
| `USER_UID`, `USER_GID`, `HOST_OS` build arguments, the darwin `chmod -R 777` | Remove | Replaced by `keep-id` at run time (3.5). |
| `--update-harness`, `OPENCODE_VERSION`, `CLAUDE_CODE_CACHEBUST` | Remove | The agents are no longer in the image. |
| `--clasp` | Replace | The clasp manifest declares its port (`PORTS`, 5.3). |
| `--iports` port numbers | Simplify to `HOST_ACCESS` | The numbers are ignored today. |
| `--no-shell` | Replace with `swarmbox up` | Same use (automation), clearer name. |
| `claude-mcp` wrapper | Remove | Nothing references it; the `claude` alias already passes `--mcp-config`. |
| `uuid()` shell function | Remove | A personal convenience, not part of a neutral image. |
| `ANTHROPIC_MODEL=sonnet` in the image | Remove | A personal default; users set a model through `ENV_KEYS`. |
| OpenCode's local-LLM defaults (the model name and `host.containers.internal:8000`) | Remove the defaults, keep `LOCAL_LLM_*` | Neutral defaults; the feature stays opt-in. |
| `<workspace>/.claude/settings.json` symlink into `<workspace>/.swarmbox/` | Remove after migration | The home is already the workspace, so `<workspace>/.claude` persists by itself. The first start of the new image replaces the link with a copy of the file (section 11). |
| `<workspace>/.swarmbox/` | Replace with the XDG layout (3.8); decided | One predictable layout, consistent with the tool folders. |
| `container/scripts/init.sh` | Remove; its duties are split (7.1) | The new model has no init script. |
| `cloudflare-setup.py`: `--connector-image` | Replace | The connector image is pinned in the helper; `SWARMBOX_CLOUDFLARED_IMAGE` stays for overrides. |
| Image packages `software-properties-common`, `lsb-release`, `apt-transport-https` | Remove after a build test | Candidates only; nothing checked depends on them. `procps` stays (`pgrep` is used by the web-terminal and Podman-service scripts). |

Kept on purpose, so nobody reads them as removals: `--remote-browser` (as `BROWSER_URL`), `--ports`, `--hostname`, the time zone, `--init`,
the SSH key, the nested Podman volume and host connection, the Cloudflare options `token`, `--print-token`, `--no-connector`, `--dry-run`,
`--tunnel`, `--no-verify` (they pass through `swarmbox remote setup`, outside the main flow).

## 4. Web terminal and remote access (proposed packaging of what exists)

```
browser ─ https://swarmbox.example.com ─► Cloudflare Access (e-mail code) ─► cloudflared ─► 127.0.0.1:7681 ─► ttyd ─► tmux
                                                                            (HOST)                         (inside the box)
```

### 4.1 Inside the box
- ttyd (pinned and checksummed), tmux (from the distribution) and the clipboard bridge are part of the image (a few MB).
- `serve` runs the web terminal (ttyd running tmux) and is the container's main process, so the box lives as long as it. Today the web
  terminal is started in the background by `init.sh` when the container was created with `SWARMBOX_WEB=1`. Making `serve` the main process
  has not been tested.
- It is on by default and listens only on `127.0.0.1:<WEB_PORT>` of the host (inside the box it is always port 7681). `WEB=0` turns it off.
- `serve` supervises ttyd instead of being it, so restarting the web terminal after editing `web-terminal.conf` is
  `swarmbox-web restart` inside the box, and does not end the box. Today the documented way is `pkill ttyd; swarmbox-web-terminal`,
  which would stop a box whose main process was ttyd. (Untested.)
- **The page is built into the image.** `container/web/build-index.sh`, run at image build, assembles ttyd's own page (`ttyd-stock.html`,
  saved at build), `ttyd-clipboard.js` and `ttyd-style.css` into `box:/usr/local/share/swarmbox/web/index.html`, with placeholders for
  the three user settings: the padding and the two switches `ctrlVPaste` and `ctrlCCopy`. At every start `swarmbox-web` copies it to
  `box:/tmp/swarmbox/index.html` substituting those three values from `web-terminal.conf` (a plain text substitution: no Python at runtime
  and no hash). Today the whole assembly runs at every start (`web-terminal.sh`, with Python). Building it at image build means the
  page, however sophisticated it becomes, is versioned, tested in CI and covered by the image's signature.
- Font, theme and size do not live in the HTML: ttyd passes them to the page through its `-t key=value` options, built from
  `web-terminal.conf` at start.
- `web-terminal.conf` is `<workspace>/.config/swarmbox/web-terminal.conf` (`<workspace>/.swarmbox/web-terminal.conf` today). Logs go to
  `<workspace>/.local/state/swarmbox/`.
- Limit: ttyd serves a **single file** as the page (`--index`), as far as this repository uses it. A page that grows into several files would have
  to be inlined into that one file, or a small server put in front. This was not checked against ttyd's documentation (open question 21).

### 4.2 Remote access: `swarmbox remote`
- `remote setup` asks for a Cloudflare domain, an e-mail and an API token (hidden input, never stored), then provisions:
  the Access application with the one-time-code login, one tunnel per account, the DNS record, and the connector as a Podman
  container **on the host** (`swarmbox-cloudflared`, restarted automatically). Options: `--session` (login length),
  `--hostname`, `--port`. It is the existing `cloudflare-setup.py`, which stays idempotent and dependency-free.
- `remote status` reports the connector, the hostname, the login check and the session length. `remote off` removes what
  `cloudflare-setup.py remove` removes today (the DNS record, the tunnel route, the Access application and its policy) and also stops
  the connector when no other hostname uses the tunnel. Today `remove` leaves the connector running, so this is a change. `swarmbox url` prints the local and the remote URL.
- After setup, every `swarmbox` entry makes sure the connector is up (created, started or recreated with the tunnel token),
  as `start.sh --web` does today. The tunnel token lives in the host's environment or config, never in the box.
- The login length defaults to a conservative value and is changed with `--session` (for example `168h`). Rerunning the
  setup without `--session` must keep the value already configured instead of resetting it to the default. (Today the script
  resets it to 4h; this is a change to make.)

- The script's other options stay reachable and are not part of the main flow: `swarmbox remote setup --dry-run`, `--tunnel`,
  `--no-connector`, `--print-token`, `--no-verify`, and `swarmbox remote token` (prints the tunnel token for people who run
  `cloudflared` themselves).

### 4.3 Host helper
The host-side Cloudflare logic is Python, too long for the shell function. `init` and `update` extract it from the image into
`host:~/.local/share/swarmbox/host/` (version-matched), and the function calls it only when remote access is configured. The image
stays the single trust anchor, and the script runs on the host with the user's privileges, which is why it is small, has no
dependencies, and is readable there.

## 5. Tools, agents and shims (proposed)

### 5.1 Definitions

- A **tool** is a program SwarmBox can install on demand (gcloud, clasp, Go, Poetry...).
- An **agent** is a tool with `KIND=agent`: it also has auto-approve flags and may use the MCP configuration.
- A **shim** is a symbolic link on `PATH`, named after a command a tool provides, that points to **one shared dispatcher**
  (`swarmbox-shim`). It exists from the start; the real program does not. The dispatcher learns which command was called
  from the name it was invoked with (`basename "$0"`), looks it up in an index (`command -> tool`), makes sure the tool is
  installed, then replaces itself (`exec`) with the real program. There is no per-tool shim code: **adding a shim means
  creating a link and one index line**, both generated from the manifests.
- A **manifest level** is where manifests are read from (image, user, project; section 5.2). Higher levels win.

### 5.2 Layout

In the repository (versioned; this is where a tool is defined):

```
container/
├── tools/<name>/
│   ├── tool.conf        # manifest (5.3)
│   ├── install.sh       # how to install it (5.4)
│   └── shell.sh         # optional: aliases/functions sourced by the interactive shell (5.6)
└── scripts/
    ├── swarmbox-tool.sh # list | install | update | use | remove | run | link | validate | doctor | new
    └── swarmbox-shim.sh # the single dispatcher every shim links to
```

Shims and the index are **not** in git: `swarmbox-tool link` generates them.

Manifest levels, from highest precedence to lowest:

| Level | Manifests | Generated shims and index | Who uses it |
|---|---|---|---|
| Project | `.swarmbox/tools/<name>/` in the directory where `swarmbox-tool link` runs (the one `swarmbox` is entered from) | `<workspace>/.local/share/swarmbox/shims/`, `.../index` | whoever clones the project (see 5.10) |
| User | `<workspace>/.config/swarmbox/tools/<name>/` (in the workspace) | the same directory | the user, no rebuild |
| Image | `/usr/local/lib/swarmbox/tools/<name>/` (copied from `container/tools/`, read-only) | `/usr/local/lib/swarmbox/shims/`, `.../index` | everyone |

`swarmbox-tool link --system` runs at image build for the image level. `swarmbox-tool link --user` runs at every container
start and at every entry (`swarmbox-attach`), is idempotent, and rebuilds the user-level shims from the user and project
manifests.

In the image:

```
/usr/local/bin/swarmbox-tool                # the manager
/usr/local/bin/swarmbox-shim                # the dispatcher
/usr/local/lib/swarmbox/tools/<name>/...    # image-level manifests and install scripts, read-only
/usr/local/lib/swarmbox/shims/<command>     # symlink -> /usr/local/bin/swarmbox-shim
/usr/local/lib/swarmbox/index               # "command tool" per line
```

In the workspace (persistent, mounted as `/home/agent`):

```
<workspace>/.local/share/swarmbox/tools/<name>/<version>/   # the installed program ($TOOL_PREFIX)
<workspace>/.local/share/swarmbox/tools/<name>/current      # symlink to the active version (UPDATE=managed)
<workspace>/.local/share/swarmbox/tools/<name>/self/        # the single install of an UPDATE=self tool, updated by the tool
<workspace>/.local/share/swarmbox/shims/, .../index         # user- and project-level shims
<workspace>/.config/swarmbox/tools/<name>/                  # user-level manifests
```

The install lock is `box:/tmp/swarmbox/tools.lock` (an `flock`, so two shells do not install at once).

`PATH` order: user-level shims, image-level shims, then `<workspace>/.local/share/swarmbox/tools/*/current/bin`. After install the real
binary is found before the shim, so there is no per-call overhead. (Checked: a symlink invoked as `gcloud` or `clasp` into
one script gets its own name in `$0` and its own arguments.)

### 5.3 Manifest: `tool.conf`

A shell-sourceable `KEY=VALUE` file: no parser dependency (the image has no TOML/YAML tool by design).

```sh
# container/tools/claude/tool.conf
SCHEMA=1
NAME=claude
KIND=agent                                   # agent | tool
PROVIDES="claude"                            # commands that get a shim
VERSION=latest                               # or a pinned version; see 5.7
UPDATE=self                                  # the tool updates itself (auto-update stays ON); default is "managed"
UPDATE_CMD="claude update"                   # what `swarmbox-tool update claude` runs for an UPDATE=self tool
YOLO_FLAGS="--dangerously-skip-permissions"  # agents only
MCP_FLAGS="--mcp-config $HOME/.claude/mcp-servers.json"
```

```sh
# container/tools/opencode/tool.conf
SCHEMA=1
NAME=opencode
KIND=agent
PROVIDES="opencode"
VERSION=latest
MCP_FORMAT=opencode                          # gets its own copy of the MCP server list; no YOLO_FLAGS until the flag is verified
```

```sh
# container/tools/clasp/tool.conf
SCHEMA=1
NAME=clasp
KIND=tool
PROVIDES="clasp"
VERSION=latest
```

```sh
# container/tools/gcloud/tool.conf
SCHEMA=1
NAME=gcloud
KIND=tool
PROVIDES="gcloud gsutil bq"
VERSION=<pinned>
SHA256_amd64=<checksum>
SHA256_arm64=<checksum>
```

Fields
- `SCHEMA`: the version of the manifest *format* (currently `1`), not of the tool. `swarmbox-tool` reads the formats it knows;
  a manifest with a newer `SCHEMA` is refused with "update SwarmBox" instead of being misread. Within one `SCHEMA`, unknown keys
  are ignored, so a newer manifest with extra fields still works on a slightly older SwarmBox.
- `NAME`: directory name and install folder. `PROVIDES`: shim names. `KIND`: `agent` tools also get the aliases in 5.6.
- `VERSION`: `latest` resolves at first install and is then recorded; anything else is installed as written.
- `UPDATE`: `managed` (default, SwarmBox keeps versions side by side) or `self` (the tool updates itself). `UPDATE_CMD`:
  required for `self`; the command that updates it now. See 5.7.
- `SHA256_<arch>`: verified before use when present. Required for tools with a published hash.
- `PORTS`: optional; ports the tool needs published on `127.0.0.1` (clasp's `login` callback uses `43323`). Creation-time: they are added to
  the box's `PORTS` when the tool is in `WITH` at creation. For a tool installed later, add it to `WITH` and `swarmbox reset`.
- `MCP_FORMAT`: agents only; how the MCP server list reaches the agent. `claude` reads the generated `<workspace>/.claude/mcp-servers.json`
  directly; `opencode` gets a mirrored copy in its own format.
- Conflicts: two manifests that provide the same command are resolved by level (project, then user, then image); two at the
  same level are an error reported by `link` and `validate`.

### 5.4 Install contract: `install.sh`

Called by `swarmbox-tool install <name>` with:

| Variable | Meaning |
|---|---|
| `TOOL_PREFIX` | Directory to install into (a `bin/` inside it is put on `PATH`). |
| `TOOL_VERSION` | The version to install (already resolved). |
| `TOOL_ARCH` | `amd64` or `arm64`. |

Rules: idempotent; writes only under `$TOOL_PREFIX` (and its own temp dir); prints progress to **stderr** only (stdout
belongs to the tool being run); exits non-zero on any failure and leaves no half-installed `current` link. npm-based tools
use `npm install -g --prefix "$TOOL_PREFIX"` and **clean the npm cache in the same step**.

Hard rules, because a box can be recreated (section 5.11): an installer **never** uses `apt` or `sudo`, never writes outside
`$TOOL_PREFIX` (not in `/usr`, `/etc`, `/opt`, and not in the user's shell startup files such as `<workspace>/.bashrc`), and never needs
a system package that the image does not already have. A tool that needs one belongs in the image, or in the build-time
preinstall (5.8), not in an on-demand install. Anything an installer is allowed to leave behind (a cache) must be safe to lose.

Examples

```bash
#!/bin/bash
# container/tools/clasp/install.sh (and claude: same shape, with its package name)
set -euo pipefail
npm install -g --prefix "$TOOL_PREFIX" "@google/clasp@${TOOL_VERSION}" >&2
npm cache clean --force >&2
```

`container/tools/opencode/install.sh` has the same shape plus one step: OpenCode ships four platform builds of about 240 MB each and hard-links
the right one into its `bin/`, so the installer removes the other builds (`rm -rf <prefix>/lib/node_modules/@opencode/cli/node_modules/@opencode`)
and checks that `opencode --version` still runs. That saves about 720 MB per workspace; it was measured in the v0.1.0 image, and the same layout is
expected under `--prefix` but has not been measured there.

`container/tools/gcloud/install.sh` would download Google's tarball for `$TOOL_ARCH`, verify the manifest's `SHA256_<arch>`,
extract it into `$TOOL_PREFIX` and link the binaries into `$TOOL_PREFIX/bin`. The exact download URL and where the checksum
comes from are **not verified yet** (open question 4).

### 5.5 Lifecycle of a shim call

1. The shim (a link to `swarmbox-shim`) finds its tool in the index and runs `swarmbox-tool run <name> <command> -- "$@"`.
2. If the tool is installed (a `current` link, or the `self` directory), `exec` the real command. Done.
3. Otherwise take the lock, print `Installing <name> (first use)...` to stderr, run `install.sh`, move `current`.
4. `exec` the real command. If the install fails, print the reason, exit non-zero, and the next call retries.

Failure modes: offline (clear message, nothing installed), checksum mismatch (install aborted, files removed),
concurrent shells (second waits on the lock, then finds it installed), and an installed tool whose recorded environment no
longer matches the image (section 5.11).

### 5.6 Agents: aliases and `yolo`

For every installed or declared agent, the shell gets an alias built from the manifest, e.g.
`alias claude='claude --dangerously-skip-permissions --mcp-config ...'`, so `claude` is auto-approve by default inside the
sandbox. The flags live only in the manifest: when a release changes one, there is one place to fix. The file named by
`MCP_FLAGS` is generated by `serve` from the MCP registry (3.8), not written by hand.

- `yolo` runs the **default agent** in auto-approve mode. The default is `SWARMBOX_AGENT`, else the first agent in
  `SWARMBOX_WITH`.
- `command claude` bypasses the alias (normal prompts). `SWARMBOX_YOLO=0` disables all the aliases.
- An agent without a verified auto-approve flag gets no alias. (OpenCode's flag is **unverified**; confirm in its docs first.)
- OpenCode is a shim like Claude Code: an on-demand agent with its own manifest. Its local-LLM support moves from `init.sh` into
  `container/tools/opencode/shell.sh`: `build_opencode_config` renders the config from `LOCAL_LLM_*` (off unless set), `sync_opencode_mcp`
  mirrors the MCP list (`MCP_FORMAT=opencode`), and `OPENCODE_CONFIG` is exported there instead of being an `ENV` in the Dockerfile.

`shell.sh` is the optional place for anything else a tool needs in the interactive shell. It is sourced from the shell
configuration for every installed or declared tool. Today's example is the `clasp` function that adds
`--redirect-port 43323` to `clasp login`: it moves from the image's `bashrc` into `container/tools/clasp/shell.sh`, next to the
tool that needs it. The generated aliases from the manifest are produced before `shell.sh` runs, so `shell.sh` can extend or
override them.

### 5.7 Pinning and updating

Each tool says how it is updated, with `UPDATE` in its manifest.

**`UPDATE=managed` (the default): SwarmBox owns the versions.**
- Manifests pin a version (or say `latest`); `SWARMBOX_WITH` and `tool install` honor them.
- `swarmbox-tool update <name>` re-resolves the version, installs it side by side, then moves `current`. Old versions stay
  until `swarmbox-tool remove <name> --old`.
- `swarmbox-tool use <name> <version>` moves `current` to an installed version. Rolling back is one instant command, because
  `current` is only a link.
- On entry, at most once a day and only when online, a one-line notice if a newer version exists ("gcloud 4xx installed, 4yy
  available: swarmbox-tool update gcloud"). `SWARMBOX_UPDATE_CHECK=0` turns it off.
- If a manifest pins a version different from the installed one (typically after an image update), the entry says so:
  "manifest wants X, installed Y".
- Running processes keep the version they started with; the next launch uses the new one.

**`UPDATE=self`: the tool updates itself. Claude Code is the first.**
- SwarmBox installs it once, into `tools/<name>/self/`, and then leaves it alone: no side-by-side versions, no `current` link,
  no pin, no outdated notice (the tool has its own). `VERSION` must be `latest`; `validate` rejects anything else.
- The tool's auto-update stays **on**: `DISABLE_AUTOUPDATER` is not set. This changes `v0.1.0`, which disabled it because
  rebuilding the image was the update path.
- `swarmbox-tool update <name>` runs the manifest's `UPDATE_CMD` (`claude update`), for anyone who does not want to wait for
  the background update.
- There is no `use`: to go back, reinstall the version wanted (`swarmbox-tool install <name> --version X`), knowing the tool
  will update itself again unless its updater is turned off by hand.
- The cost is reproducibility. Two workspaces can run different Claude Code versions, and a new vendor release runs inside the
  box with no SwarmBox pin or checksum (section 10).
- **Not verified:** that Claude Code's updater works for the install method `install.sh` uses (open question 3). It decides
  between an npm install under `--prefix` and the vendor's native installer into the home; test it before writing the script.

Updating *tools* never needs a new image or a new box. Updating the *image* (`swarmbox update`) does, and recreating the box
ends the running tmux sessions, so `update` asks before it does that.

### 5.8 Build-time preinstall

The same manifests drive an optional build argument, for people who bake tools into their own image:

```bash
podman build --build-arg WITH_TOOLS=claude,gcloud .
```

The Dockerfile runs `swarmbox-tool install` for each name into `/opt/swarmbox/tools` instead of the workspace. One installer,
two triggers.

### 5.9 Adding a tool, and keeping the model extensible

To add a tool to the repository:

1. Create `container/tools/<name>/` with `tool.conf` and `install.sh` (and `shell.sh` if it needs shell setup). Or run
   `swarmbox-tool new <name>` to create the skeleton.
2. Run `swarmbox-tool validate` (CI runs it): required fields, a known `KIND`, unique command names across levels, an
   executable `install.sh`, a checksum for every architecture when one is declared, and for `UPDATE=self` a `VERSION=latest`
   and an `UPDATE_CMD`.
3. Rebuild. **No file of the core changes**: the Dockerfile copies the whole directory and `link --system` generates the shims.

Without a rebuild, put the same directory under `<workspace>/.config/swarmbox/tools/<name>/` (user level) or `.swarmbox/tools/<name>/`
(project level); the next entry links it.

Rules that keep this extensible: manifests are data (`SCHEMA` versioned, unknown keys ignored); the core never names a
specific tool; shims are links to one dispatcher; every manifest is covered by `validate` and by installer tests that use a
fake installer (the same approach the existing tests take for Podman and Cloudflare).

CI also runs, for every tool in `container/tools/` (these use the real installer and the network, so they run on a schedule or
before a release, not on every push):
- **No side effects:** install in a clean container and check that nothing changed outside `$TOOL_PREFIX` except an allowed
  cache directory. This enforces the hard rules of 5.4.
- **Survives a reset:** install, recreate the box on the same workspace, and run the tool.

### 5.10 Project-level tools and trust

A `.swarmbox/tools/` directory that arrives with a cloned repository contains an `install.sh`, which runs code in the sandbox
with network access and any keys that were passed in. The sandbox limits the damage to the host, not to those keys. So a
project-level tool is **never installed automatically**: the first time one appears, SwarmBox lists it and asks the user to
accept it, and records the accepted manifest's hash; a changed manifest asks again. (Proposal; not designed in detail yet.)

### 5.11 Surviving a reset and an image update

What lives where decides what a `reset` (or `swarmbox update`) can break.

| Lives in | Survives `reset` | Survives an image update | Examples |
|---|---|---|---|
| Workspace (`/home/agent`) | yes | yes | projects, login, SSH key, `<workspace>/.claude`, installed tools, user manifests |
| The container's own filesystem | **no** | no | anything installed with `apt`, files in `/usr`, `/etc`, `/opt`, caches outside the home, running processes, tmux sessions |
| The image | recreated | replaced | system packages, Node, shims and index of the image level, image manifests |

Measured, for Claude Code installed with `npm install -g --prefix <dir in the home>` in a throwaway container: the install wrote
only the prefix (325 MB, all in the home) and the npm cache (157 MB), and nothing in `/usr`, `/etc` or `/opt`. A reset
therefore does not touch it. (The vendor's native installer was not tested.)

What can still break a tool after a reset or an image update, and what the design does about it:

1. **The installer wrote outside the prefix.** Forbidden by the hard rules in 5.4 and caught by the "no side effects" CI test.
2. **The tool needs a system package.** Not allowed on demand; such a tool goes in the image or in `WITH_TOOLS`.
3. **The environment under the tool changed.** A tool installed under one Node major, CPU architecture or libc can fail under
   another (native Node modules; a workspace moved from amd64 to arm64). Each install records a fingerprint,
   `NODE_MAJOR`, `ARCH` and `LIBC`, in a small file next to it (`<prefix>/.swarmbox-env`). At every entry `link --user` compares it
   with the running image:
   - different `ARCH`: the shim refuses to run it and says to reinstall, because it cannot work;
   - different `NODE_MAJOR` or `LIBC`: it warns once per entry and runs the tool anyway, since it may still work;
   - `swarmbox-tool install <name> --force` reinstalls; `swarmbox-tool doctor` lists every tool as `ok`, `needs reinstall`
     or `missing`, and `swarmbox-tool doctor --fix` reinstalls the ones that need it.
4. **An `UPDATE=self` tool moved on by itself.** Its fingerprint is checked the same way; the tool's own updater keeps its files
   current inside the prefix.

## 6. Repository structure

Existing paths are kept where they work. **New** marks proposed additions.

```
.
├── Dockerfile                       # the image (section 7)
├── README.md                        # 15-second pitch, install, first use
├── LICENSE                          # new
├── SECURITY.md                      # new: threat model, how to report
├── CONTRIBUTING.md  CODE_OF_CONDUCT.md  CHANGELOG.md        # new
├── THIRD_PARTY_NOTICES.md           # new: ttyd, starship, tmux, ...
│                                    # (build.sh, start.sh and lib/ exist today and are retired once the function reaches parity: 3.9)
├── cloudflare-setup.py              # host side: remote access; also shipped inside the image for `swarmbox remote`
├── container/                       # everything copied into the image
│   ├── entrypoint.sh                # new: subcommands serve | attach | init | pubkey | tool | <any command>
│   ├── scripts/                     # banner.sh, messages.sh, podman-service.sh, ssh-key.sh (swarmbox-pubkey),
│   │                                #   dirs.sh (new: every path, XDG-aware; sourced by the others),
│   │                                #   swarmbox-init (new: prints the shell function),
│   │                                #   swarmbox-web (new: starts and restarts the web terminal; replaces web-terminal.sh),
│   │                                #   swarmbox-attach (new: joins the tmux session; today lib/attach-session.sh),
│   │                                #   swarmbox-tool.sh and swarmbox-shim.sh (new: manager and dispatcher, section 5)
│   ├── config/                      # static configuration files: tmux, starship, ssh_config.d, bashrc fragment
│   ├── web/                         # web terminal: ttyd-clipboard.js, ttyd-style.css, build-index.sh (new, runs at image build)
│   ├── mcp/<name>/config.json       # MCP servers wired into agents (chrome-devtools today)
│   └── tools/<name>/                # new: tool.conf + install.sh + optional shell.sh (section 5)
├── docs/                            # design.md (this file), web-terminal.md, cloudflare.md, nested-podman.md
├── tests/                           # helpers.py + one test file per behavior; fakes for podman, Cloudflare, installers
└── .github/workflows/               # new: ci.yml (tests), release.yml (build, scan, sign, publish)
```

File types

| Kind | Where | Who reads it | When |
|---|---|---|---|
| Dockerfile | root | the builder | image build |
| Entrypoint, scripts | `container/entrypoint.sh`, `container/scripts/` | the container | container start and every entry |
| Dispatcher and manager | `container/scripts/swarmbox-shim.sh`, `swarmbox-tool.sh` | every shim, `swarmbox-tool` | every tool call |
| Static config | `container/config/` | tmux, starship, ssh, bash | shell start |
| Web assets | `container/web/` | `build-index.sh` at image build; `swarmbox-web` at start | image build, container start |
| MCP definition | `container/mcp/<name>/config.json` | `serve` | container start |
| Paths | `container/scripts/dirs.sh` | every script | always |
| Tool manifest and installer | `container/tools/<name>/{tool.conf,install.sh}` | `swarmbox-tool` | first use, or build with `WITH_TOOLS` |
| Tool shell setup | `container/tools/<name>/shell.sh` | the interactive shell | shell start |
| Generated shims and index | image `/usr/local/lib/swarmbox/{shims,index}`; workspace `<workspace>/.local/share/swarmbox/{shims,index}` | the dispatcher | every command call (not in git) |
| Host script | `cloudflare-setup.py` (and, until retired, `start.sh`, `build.sh`, `lib/`) | the user's shell | on the host |
| Generated host function | the user's `host:~/.bashrc` (between markers) | the user's shell | every terminal |
| Host config | `host:~/.config/swarmbox/config`, `host:~/.config/swarmbox/cloudflare.json` | the host function and helper | every entry, `remote` |
| Host secrets (optional, mode 600) | `host:~/.config/swarmbox/secrets/env` | the host function, at creation only | box creation |
| Tests | `tests/` | CI and contributors | every change |
| Docs | `README.md`, `docs/` | people | always |

Rules: no file outside `container/` is copied into the image, except `cloudflare-setup.py`, which the image ships for the host
helper; nothing from Cloudflare (credentials, tunnel token) is ever copied into or passed to the box; every download has a
pinned version.

## 7. How the Dockerfile behaves (proposed target)

What the image contains
- Base `node:24-slim` (Node is needed by agent installers; the base is still Debian 12). Node version is an `ARG`.
- System packages: git, openssh-client, python3 + venv, build tools, curl, jq, tmux, vim, podman and its network deps.
- Pinned, checksum-verified downloads: ttyd, starship (as today).
- The tool infrastructure: `swarmbox-tool`, `swarmbox-shim`, `swarmbox-init`, `swarmbox-attach`, the manifests, and the shims
  and index that `swarmbox-tool link --system` generates.
- Config files and scripts from `container/`, and `cloudflare-setup.py` for the host helper.
- Kept from today's image: the Python venv at `/opt/flow` (the `(swarmbox)` prompt) and `uv`, the shell aliases, `<workspace>/.local/bin` on
  `PATH`, Starship (opt-out `SWARMBOX_STARSHIP=0`), the banner, and Chromium with its environment.

What it does **not** contain: any agent (Claude Code, Gemini CLI, OpenCode), gcloud, clasp, Go, Poetry. They arrive on demand
(or with `WITH_TOOLS`). The memory service was already removed before `v0.1.0` and stays out. `cloudflared` is not in the
image either: it runs from its own image, on the host.

Behavior
- **User:** fixed `agent`, UID/GID 1000. No `USER_UID`/`HOST_OS` build arguments; the host user is mapped at run time
  (`keep-id`). `sudo` without a password is intentional: the box is the sandbox.
- **Directories:** `WORKDIR /home/agent`, which is the workspace mounted from the host.
- **Startup:** `ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]`, `CMD ["serve"]`. Subcommands:
  `serve` (the box's main process: create the folders of `dirs.sh`, migrate an old layout, ensure the SSH key, link the tools, generate the
  MCP configuration, start the nested Podman service, install the tools listed in `SWARMBOX_WITH`, and supervise the web terminal),
  `attach` (join the tmux session; what the host function runs on every entry, after linking the user and project tools),
  `init` (print the host function), `pubkey`, `tool ...`, and any other command, which is run as given. There is no `init.sh`: 7.1 says
  where its duties go.
- **Layer order:** stable first (system packages, Podman, pinned downloads), volatile last (scripts, manifests). A change
  to a manifest never invalidates the system layers.
- **Wiring the tools** (near the end, with the other volatile layers):

  ```dockerfile
  COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool
  COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim
  COPY container/tools/                   /usr/local/lib/swarmbox/tools/
  RUN chmod 755 /usr/local/bin/swarmbox-tool /usr/local/bin/swarmbox-shim && swarmbox-tool link --system
  ENV PATH=/usr/local/lib/swarmbox/shims:$PATH
  ```

  `link --system` reads every manifest, creates one symlink per command in `/usr/local/lib/swarmbox/shims/` pointing at
  `swarmbox-shim`, and writes the index. At container start and at every entry, `swarmbox-tool link --user` does the same for
  the user and project levels.
- **Layer hygiene:** every `RUN` that downloads cleans up in the same `RUN` (apt lists, npm cache, temp files), because a
  later `rm` does not shrink an image. Files that must be user-writable are created with the right owner, not `chown -R`
  afterwards, which duplicates them in a new layer.
- **Pinning:** every version is an `ARG` with a default; checksums are verified when published.
- **Size budget:** the neutral image should stay under about 2.5 GB. Today's image is about 4.2 GB, of which agents, gcloud,
  clasp, Go and Poetry are roughly 2 GB. These figures come from layer measurements, not from the proposed build.
- **Flavors (optional):** CI may also publish `-claude`-style tags built with `WITH_TOOLS`, for users who want zero first-run wait.
- **Environment:** `LANG=C.UTF-8`, `NPM_CONFIG_CACHE` outside the home, `BROWSER=none`, `CHROME_BIN` and `PUPPETEER_*` (kept: the
  chrome-devtools MCP needs them with the local Chromium). `ANTHROPIC_MODEL` is no longer set in the image. Chromium is still installed for the
  chrome-devtools MCP; making it optional is open question 5.

### 7.1 What `init.sh` does today, and where it goes

| Today (`container/scripts/init.sh`, run from `bashrc` in every interactive shell) | New home |
|---|---|
| Creates `<workspace>/.claude`, `settings.json` and its link | Gone: Claude Code's own `<workspace>/.claude/settings.json` is used directly (migrated, section 11) |
| Creates `<workspace>/.swarmbox/` | `serve`, from `dirs.sh` (the XDG folders) |
| Ensures the SSH key | `serve` runs `swarmbox-pubkey --ensure`; the shell prints the one-line fingerprint |
| Generates `mcp-servers.json` (chrome-devtools by name) | `serve`, from the MCP registry (3.8) |
| Renders the OpenCode config and mirrors the MCP list | `container/tools/opencode/shell.sh` |
| Starts the nested Podman service and the web terminal | `serve` |
| Prints the banner and messages in every shell | A light fragment sourced from `box:/etc/bash.bashrc` (`container/config/bashrc.sh`): banner, aliases, `PATH`, Starship, and each tool's `shell.sh` |
| Re-links the tool shims | `swarmbox-attach` (`swarmbox-tool link --user`) |

The heavy work leaves the per-shell path: a new shell no longer runs a script that regenerates files; `serve` does it once per start.

## 8. Configuration model (proposed)

Precedence, highest first: environment variable, `host:~/.config/swarmbox/config` (host), built-in default. Variables marked
*host* are read by the host function and helper only and are never passed into the box. The creation-time keys are listed in 3.8
and are not repeated here.

| Variable | Meaning | Default |
|---|---|---|
| `SWARMBOX_NAME` | Name of the box (container) | `swarmbox` |
| `SWARMBOX_WORKSPACE` | Host folder mounted as `/home/agent` (*host*) | `host:~/swarmbox` |
| `SWARMBOX_WITH` | Tools to have ready (comma list) | empty |
| `SWARMBOX_AGENT` | Agent started by `yolo` | first agent in `SWARMBOX_WITH` |
| `SWARMBOX_YOLO` | `0` disables the auto-approve aliases | `1` |
| `SWARMBOX_WEB` | `0` turns the web terminal off | `1` |
| `SWARMBOX_WEB_PORT` | Host port of the web terminal, on `127.0.0.1` (*host*) | `7681` |
| `SWARMBOX_TOOLS_DIR` | Where tools install | `<workspace>/.local/share/swarmbox/tools` |
| `SWARMBOX_UPDATE_CHECK` | `0` turns off the once-a-day "newer version" notice for managed tools | `1` |
| `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` | The tunnel's own token (*host*, never passed into the box) | unset |
| `SWARMBOX_WEB_DOMAIN`, `SWARMBOX_WEB_HOSTNAME` | Used to print the public URL (*host*) | from `cloudflare.json` |
| `ENV_KEYS` (in the host config file) | Names of host variables passed into the box at creation (3.7) | empty |

Defaults must be neutral: no personal hosts or model names (the current local-LLM default for OpenCode is removed or off).

## 9. Distribution and versioning (proposed)

- Image `ghcr.io/<org>/swarmbox`, multi-arch (amd64, arm64), tags `X.Y.Z` and `X.Y`. `latest` exists but docs always show a
  version. Digests are published in the release notes.
- Release pipeline: build, run tests, vulnerability scan, sign (cosign), publish, attach the SBOM.
- Semantic versioning; `CHANGELOG.md`. `v0.1.0` is the last release of the private design.
- A Dependabot/Renovate config bumps the pinned versions and the base image.

## 10. Security model

What the sandbox protects: the host's files and processes outside the workspace folder, and the host's Podman socket (it is
never mounted).

What it does not protect, and must say so:
- The agent can change or delete everything in the workspace, which holds all the projects, the login and the SSH key.
- Variables passed in (3.7) are stored in the container's configuration and visible to every process in the box, including
  to `podman inspect` on the host.
- The container has `sudo`, open outbound network, and can read its environment: API keys passed in are visible to the agent.
- Nested Podman is always on and needs `/dev/net/tun` and an unmasked `/proc`, which weakens the box's isolation compared with a plain
  container. It is a deliberate trade-off: agents can build and run their own containers without any path to the host's Podman.
- The box is persistent: an agent keeps running (and keeps those keys) while you are away, until you stop the box.
- The SSH key lives in the workspace: anything running in the box can use it. Use per-repository deploy keys.
- The web terminal has no login on its own port. It is bound to `127.0.0.1`; remote access goes only through Cloudflare Access.
- Remote access means a browser session is a shell with `sudo`. The login length (`--session`) is the exposure window of a
  stolen or forgotten browser session: 4 hours by default today; a week is a deliberate choice. Cloudflare lets an
  administrator revoke sessions (where in the dashboard has not been checked).
- Installing tools on demand means the agent triggers downloads. Versions are pinned and checksums verified where published.
- A tool with `UPDATE=self` (Claude Code) updates itself in the background: new vendor code runs inside the box without a
  SwarmBox pin or checksum, and two workspaces can differ. It is limited to the box, but it has the same keys the agent has.

Defaults: no published ports beyond `127.0.0.1`, no host-network mode, tunnel credentials stay on the host
(the connector runs outside the box), `cloudflare-setup.py` never stores the API token, and the tunnel token is never passed
into the box.

## 11. Migration from `v0.1.0`

| Today (`v0.1.0`) | Proposed |
|---|---|
| `start.sh` creates/enters the persistent container | The `swarmbox` function does the same, from a public image |
| `./start.sh --web` plus `cloudflare-setup.py` plus token variables | Web terminal on by default; `swarmbox remote setup/status/off` |
| `.work/` in the current directory | `SWARMBOX_WORKSPACE`, default `host:~/swarmbox` |
| Agents baked into the image | Installed on demand (`SWARMBOX_WITH`) |
| `./start.sh --env-keys A,B` on every creation | The names live in the host config; `swarmbox env add/rm/list`; same creation-time behavior |
| `./build.sh --update-harness`; `DISABLE_AUTOUPDATER=true` | Claude Code updates itself (`UPDATE=self`); other agents: `swarmbox-tool update <agent>` |
| Image built locally with the host UID | One public image, `keep-id` at run time |
| `claude` alias in `bashrc` | Generated from the agent manifest |
| `cloudflare-setup.py` resets the login length to 4h on rerun | Keeps the configured value |
| `start.sh`, `build.sh`, `lib/` | Retired; the `swarmbox` function replaces them (3.9) |
| `--ports`, `--iports`, `--host-network` | `PORTS`, `HOST_ACCESS`; the host-network mode is removed |
| `--remote-browser` | `BROWSER_URL` |
| `--hostname`, `SWARMBOX_TZ`, `SWARMBOX_INIT` | `HOSTNAME`, `TZ`, `INIT` |
| `--clasp` | The clasp manifest's `PORTS` |
| `--no-shell`, `SWARMBOX_ATTACH=shell` | `swarmbox up`, `swarmbox --plain` |
| Nested Podman always on | Unchanged: always on |
| `<workspace>/.swarmbox/` | The XDG layout (3.8); migrated at the first start |
| `container/scripts/init.sh` | Split across `serve`, `swarmbox-attach`, the tools' `shell.sh` and a light bash fragment (7.1) |

An existing `.work/` can be used as the workspace as is: point `SWARMBOX_WORKSPACE` at it (`init --workspace <path to .work>`).

Layout migration. At the first start of the new image, `serve` moves files that exist, and only when the destination does not:
- `<workspace>/.swarmbox/web-terminal.conf` (and any copies of it) to `<workspace>/.config/swarmbox/web-terminal.conf`.
- `<workspace>/.claude/settings.json`, when it is a link to `<workspace>/.swarmbox/settings.json`: the link is replaced by a copy of the file.
- Logs and `podman.sock` are recreated under `<workspace>/.local/state/swarmbox/` and the old ones removed. The host function registers the
  new socket address with `podman system connection` (the current code already replaces a connection whose address changed).
- Generated files (`ttyd-index.html`, `opencode-local.json`) and locks are deleted; they are regenerated in `box:/tmp/swarmbox/`.
- `<workspace>/.swarmbox/memory/`, left by the removed memory service, is not touched; `swarmbox` mentions it once and the user can delete it.
- `<workspace>/.swarmbox/` itself is removed when it is empty.

This is a one-way change: an older image looks for `<workspace>/.swarmbox/`, so back up the workspace first. The migration has not been written or
tested.

## 12. Open questions

1. Agents on first install: always latest, or a version pinned in the manifest? (Latest is simpler; two users may then differ.)
2. Name of the option that lists tools: `--with` or `--agents`?
3. Claude Code's self-update is decided (on, `UPDATE=self`). Open: which install method does its updater support, an npm
   install under `--prefix` or the vendor's native installer into the home? Not verified; test before writing `install.sh`.
4. How to obtain a checksum for gcloud reliably and programmatically (not yet checked).
5. Chromium: keep in the image, or make it optional? (There is no Chrome-for-Testing build for Linux arm64.)
6. OpenCode's auto-approve flag (not verified).
7. License (MIT or Apache-2.0), and the project name's availability.
8. Keep the full git history when going public, or start clean? The history must first be audited for secrets and personal data.
9. *Decided:* the workspace is chosen at install with `init --workspace DIR`, and defaults to `host:~/swarmbox`.
10. Project-level tools (5.10): how the acceptance prompt works non-interactively, and which directory counts as "the project"
    in a box with many projects.
11. `serve` as the main process (4.1) and `swarmbox-attach` replacing `lib/attach-session.sh`: untested.
12. Running the Cloudflare helper extracted from the image on the host (4.3): acceptable trust, or ship it as a separately
    signed release asset?
13. `swarmbox update` while sessions are running: ask before recreating, or keep the old box until the user resets it?
14. Does the vendor's native installer for Claude Code leave anything outside the home (it was not tested), and is its updater
    happier with it than with an npm install under `--prefix`? Answer together with question 3.
15. Fallback source for keys (3.7): store values in a `600` file on the host (`env set`), or leave the source entirely to the user's
    own shell/password manager? Related: the same question for the Cloudflare tunnel token, which is only needed to create or
    recreate the connector.
16. *Decided:* nested Podman stays always on, as today. It is no longer a configuration key.
17. *Decided:* OpenCode is an on-demand agent, a shim like Claude Code (5.6), with its local-LLM hook in its own `shell.sh`.
18. *Decided:* the XDG layout (3.8), with a migration at the first start (section 11). There is no cache folder in the workspace.
19. *Decided:* there is no `init.sh`. Its duties are split (7.1); the per-shell part is a light bash fragment, and the heavy part runs once per start in `serve`.
20. *Decided:* macOS is in scope for the first release, through the platform adapter in `swarmbox-create-flags` (`label=disable`,
    explicit `keep-id`). It has not been run on a Mac; it will be tested there, and anything that fails becomes a documented limit.
21. ttyd serves a single file as the page (4.1): check this against ttyd's documentation before planning a page of several files.

## 13. Roadmap

1. Pre-launch cleanup: license, remove personal defaults, audit history, CI with the existing tests.
2. `container/tools/`, `swarmbox-tool`, shims; move gcloud and clasp first, then the agents.
3. `entrypoint.sh` with `serve` and `attach`, `dirs.sh` and the layout migration, the page built at image build, fixed UID, `swarmbox-init`,
   `swarmbox-create-flags` and the host config; image published to the registry.
4. Feature parity: one test per row of the catalog (3.8) against the function; then retire `start.sh`, `build.sh` and `lib/`.
5. `swarmbox remote` (setup, status, off) over the existing Cloudflare script, with the login length preserved on rerun.
6. `swarmbox env`, `swarmbox config`, the creation fingerprint, `swarmbox --once`.
7. Optional: egress allowlist for the box's network, and a host-side credential proxy so the box never holds API keys.
