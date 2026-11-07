# SwarmBox design

Status: **proposal** for the open-source version. Sections say whether something **exists today** (as of tag `v0.1.0`)
or is **proposed**. Nothing proposed here is implemented yet.

SwarmBox is a disposable, safe-by-default sandbox for running coding agents in auto-approve ("YOLO") mode on your own
machine. The agent gets full tool access inside a rootless Podman container; your host only sees the project folder
and one persistent volume.

---

## 1. Goals and non-goals

Goals
- A new user is productive with one install command and one command per project.
- The image is **neutral**: it ships no agent. Claude Code, Gemini CLI, OpenCode and others are installed on demand.
- The user can read everything that will run on their host before it runs.
- Every optional capability (web terminal, remote access, nested Podman, cloud CLIs) is a module they turn on.
- Versions are pinned and reproducible; updating is a choice.

Non-goals
- It does not make an agent trustworthy. It reduces the blast radius (section 9); it does not remove it.
- Windows without WSL2, and macOS without a Podman machine, are not supported targets at first.
- Docker is not supported (the nested-Podman and user-namespace features are Podman's).

## 2. Principles

1. **Neutral image, tools on demand.** The image holds the shell environment. Agents and large CLIs (gcloud, clasp, Go...)
   are installed the first time they are needed, into the persistent home volume.
2. **Small core, opt-in modules.** The core builds/runs the container and keeps a workspace. Everything else is a module
   in its own folder with a manifest.
3. **Data over code.** A tool, an agent or an MCP server is a directory with a manifest and, if needed, an install script.
   Adding one needs no change to the core. (`container/mcp/<name>/` already works this way.)
4. **One trust anchor.** The image is the only artifact a user must trust. The shell snippet that wraps it is *printed by
   the image* (`init`), so it is versioned, signed and readable before it is installed.
5. **Transparent by default.** What gets added to the user's shell is a short block they can read. No hidden downloads on
   the host.
6. **Persist in one place.** Everything that must survive (login, SSH key, installed tools, config) lives under
   `/home/agent`, which is a named volume (or `.work/` with `start.sh`). The container itself stays disposable.
7. **Honest security.** The threat model is written down (section 9) and defaults are conservative: nothing published
   beyond `127.0.0.1`, no remote login without Access in front.
8. **Pinned and reproducible.** Every download has a version, and a checksum where the publisher provides one. "latest"
   is an explicit choice, never an accident of layer caching.
9. **Progressive disclosure.** Simple path: an alias. Next: a generated shell function with host-side flags. Advanced:
   `start.sh` for a persistent named container, web terminal and Cloudflare.

## 3. User model (proposed)

Install, once:

```bash
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude          # prints the snippet; read it first
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude >> ~/.bashrc
```

Use, in any project:

```bash
cd my-project
swarmbox            # opens a SHELL in the project folder (not an agent)
claude              # first call installs Claude Code into the volume, then runs it
yolo                # starts the default agent in auto-approve mode
swarmbox claude     # shortcut: shell entry, then run the agent
swarmbox pubkey     # SSH public key for git (deploy keys)
```

- `init --with a,b` records `SWARMBOX_WITH=a,b` in the snippet. The first `swarmbox` run installs the listed tools that are
  missing (progress on stderr), then opens the shell. Later runs only check.
- `init --shell zsh|fish` prints the right syntax. `init --nested`, `--web` add the matching host flags (generated as a
  function instead of an alias, section 3.1).
- Updating: pull the new tag and run `init` again; the snippet sits between markers so it is replaced, not duplicated.

### 3.1 The generated snippet

Level 0, an alias (only the flags a container needs):

```bash
# >>> swarmbox 1.2.0 >>>
alias swarmbox='podman run -it --rm --userns=keep-id:uid=1000,gid=1000 \
  -v swarmbox-home:/home/agent -v "$PWD":/workspace \
  -e SWARMBOX_WITH=claude ghcr.io/<org>/swarmbox:1.2.0'
# <<< swarmbox 1.2.0 <<<
```

- `--userns=keep-id:uid=1000,gid=1000` maps the host user to the image's fixed user (UID 1000), so one image serves every
  host UID. The agent user must not be root: Claude Code refuses auto-approve as root.
- `"$PWD"` is resolved when the alias is *used*, so each project mounts its own folder.
- Anything typed after `swarmbox` is passed to the image's entrypoint (section 6), so subcommands (`pubkey`, `shell`,
  `claude`, `tool ...`) need no host logic.

Level 1, a function, only when host-side flags are needed (`--web` publishes `127.0.0.1:PORT`, `--nested` adds
`--device /dev/net/tun --security-opt unmask=/proc/*`, `update` pulls). Same container flags, plus a small `case`.

Per-project defaults: a `.swarmbox.env` file in the project folder, passed with `--env-file`.

## 4. Tools, agents and shims (proposed)

### 4.1 Definitions

- A **tool** is a program SwarmBox can install on demand (gcloud, clasp, Go, Poetry...).
- An **agent** is a tool with `KIND=agent`: it also has auto-approve flags and may use the MCP configuration.
- A **shim** is a symbolic link on `PATH`, named after a command a tool provides, that points to **one shared dispatcher**
  (`swarmbox-shim`). It exists from the start; the real program does not. The dispatcher learns which command was called
  from the name it was invoked with (`basename "$0"`), looks it up in an index (`command -> tool`), makes sure the tool is
  installed, then replaces itself (`exec`) with the real program. There is no per-tool shim code: **adding a shim means
  creating a link and one index line**, both generated from the manifests.
- A **manifest level** is where manifests are read from (image, user, project; section 4.2). Higher levels win.

### 4.2 Layout

In the repository (versioned; this is where a tool is defined):

```
container/
├── tools/<name>/
│   ├── tool.conf        # manifest (4.3)
│   ├── install.sh       # how to install it (4.4)
│   └── shell.sh         # optional: aliases/functions sourced by the interactive shell (4.6)
└── scripts/
    ├── swarmbox-tool.sh # list | install | update | remove | run | link | validate | new
    └── swarmbox-shim.sh # the single dispatcher every shim links to
```

Shims and the index are **not** in git: `swarmbox-tool link` generates them.

Manifest levels, from highest precedence to lowest:

| Level | Manifests | Generated shims and index | Who uses it |
|---|---|---|---|
| Project | `.swarmbox/tools/<name>/` in the project folder | `~/.local/share/swarmbox/shims/`, `.../index` | whoever clones the project (see 4.10) |
| User | `~/.config/swarmbox/tools/<name>/` (the volume) | the same directory | the user, no rebuild |
| Image | `/usr/local/lib/swarmbox/tools/<name>/` (copied from `container/tools/`, read-only) | `/usr/local/lib/swarmbox/shims/`, `.../index` | everyone |

`swarmbox-tool link --system` runs at image build for the image level. `swarmbox-tool link --user` runs at every container
start (from the entrypoint), is idempotent, and rebuilds the user-level shims from the user and project manifests.

In the image:

```
/usr/local/bin/swarmbox-tool                # the manager
/usr/local/bin/swarmbox-shim                # the dispatcher
/usr/local/lib/swarmbox/tools/<name>/...    # image-level manifests and install scripts, read-only
/usr/local/lib/swarmbox/shims/<command>     # symlink -> /usr/local/bin/swarmbox-shim
/usr/local/lib/swarmbox/index               # "command tool" per line
```

In the volume (persistent, per workspace):

```
~/.local/share/swarmbox/tools/<name>/<version>/   # the installed program ($TOOL_PREFIX)
~/.local/share/swarmbox/tools/<name>/current      # symlink to the active version
~/.local/share/swarmbox/tools/.lock               # flock, so two shells do not install at once
~/.local/share/swarmbox/shims/, .../index         # user- and project-level shims
~/.config/swarmbox/tools/<name>/                  # user-level manifests
```

`PATH` order: user-level shims, image-level shims, then `~/.local/share/swarmbox/tools/*/current/bin`. After install the real
binary is found before the shim, so there is no per-call overhead. (Checked: a symlink invoked as `gcloud` or `clasp` into
one script gets its own name in `$0` and its own arguments.)

### 4.3 Manifest: `tool.conf`

A shell-sourceable `KEY=VALUE` file: no parser dependency (the image has no TOML/YAML tool by design).

```sh
# container/tools/claude/tool.conf
SCHEMA=1
NAME=claude
KIND=agent                                   # agent | tool
PROVIDES="claude"                            # commands that get a shim
VERSION=latest                               # or a pinned version; see "Pinning"
YOLO_FLAGS="--dangerously-skip-permissions"  # agents only
MCP_FLAGS="--mcp-config $HOME/.claude/mcp-servers.json"
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
- `SCHEMA`: manifest format version (currently `1`). Unknown keys are ignored, so later versions can add fields without
  breaking older manifests.
- `NAME`: directory name and volume folder. `PROVIDES`: shim names. `KIND`: `agent` tools also get the aliases in 4.6.
- `VERSION`: `latest` resolves at first install and is then recorded; anything else is installed as written.
- `SHA256_<arch>`: verified before use when present. Required for tools with a published hash.
- Conflicts: two manifests that provide the same command are resolved by level (project, then user, then image); two at the
  same level are an error reported by `link` and `validate`.

### 4.4 Install contract: `install.sh`

Called by `swarmbox-tool install <name>` with:

| Variable | Meaning |
|---|---|
| `TOOL_PREFIX` | Directory to install into (a `bin/` inside it is put on `PATH`). |
| `TOOL_VERSION` | The version to install (already resolved). |
| `TOOL_ARCH` | `amd64` or `arm64`. |

Rules: idempotent; writes only under `$TOOL_PREFIX` (and its own temp dir); prints progress to **stderr** only (stdout
belongs to the tool being run); exits non-zero on any failure and leaves no half-installed `current` link. npm-based tools
use `npm install -g --prefix "$TOOL_PREFIX"` and **clean the npm cache in the same step**.

Examples

```bash
#!/bin/bash
# container/tools/clasp/install.sh (and claude: same shape, with its package name)
set -euo pipefail
npm install -g --prefix "$TOOL_PREFIX" "@google/clasp@${TOOL_VERSION}" >&2
npm cache clean --force >&2
```

`container/tools/gcloud/install.sh` would download Google's tarball for `$TOOL_ARCH`, verify the manifest's `SHA256_<arch>`,
extract it into `$TOOL_PREFIX` and link the binaries into `$TOOL_PREFIX/bin`. The exact download URL and where the checksum
comes from are **not verified yet** (open question 4).

### 4.5 Lifecycle of a shim call

1. The shim (a link to `swarmbox-shim`) finds its tool in the index and runs `swarmbox-tool run <name> <command> -- "$@"`.
2. If `current` exists, `exec` the real command. Done.
3. Otherwise take the lock, print `Installing <name> (first use)...` to stderr, run `install.sh`, move `current`.
4. `exec` the real command. If the install fails, print the reason, exit non-zero, and the next call retries.

Failure modes: offline (clear message, nothing installed), checksum mismatch (install aborted, files removed),
concurrent shells (second waits on the lock, then finds it installed).

### 4.6 Agents: aliases and `yolo`

For every installed or declared agent, the shell gets an alias built from the manifest, e.g.
`alias claude='claude --dangerously-skip-permissions --mcp-config ...'`, so `claude` is auto-approve by default inside the
sandbox. The flags live only in the manifest: when a release changes one, there is one place to fix.

- `yolo` runs the **default agent** in auto-approve mode. The default is `SWARMBOX_AGENT`, else the first agent in
  `SWARMBOX_WITH`.
- `command claude` bypasses the alias (normal prompts). `SWARMBOX_YOLO=0` disables all the aliases.
- An agent without a verified auto-approve flag gets no alias. (OpenCode's flag is **unverified**; confirm in its docs first.)

`shell.sh` is the optional place for anything else a tool needs in the interactive shell. It is sourced from the shell
configuration for every installed or declared tool. Today's example is the `clasp` function that adds
`--redirect-port 43323` to `clasp login`: it moves from the image's `bashrc` into `container/tools/clasp/shell.sh`, next to the
tool that needs it. The generated aliases from the manifest (above) are produced before `shell.sh` runs, so `shell.sh` can
extend or override them.

### 4.7 Pinning and updating

- Manifests pin versions; `SWARMBOX_WITH` and `tool install` honor them.
- `swarmbox-tool update <name>` re-resolves `latest` (or the manifest's newer pin) and installs side by side, then moves
  `current`. Old versions are removed with `swarmbox-tool remove <name> --old`.
- The Claude Code auto-updater stays disabled (`DISABLE_AUTOUPDATER=true`); updating is `tool update`. Open question 3.

### 4.8 Build-time preinstall

The same manifests drive an optional build argument, for people who bake tools into their own image:

```bash
podman build --build-arg WITH_TOOLS=claude,gcloud .
```

The Dockerfile runs `swarmbox-tool install` for each name into `/opt/swarmbox/tools` instead of the home volume. One
installer, two triggers.

### 4.9 Adding a tool, and keeping the model extensible

To add a tool to the repository:

1. Create `container/tools/<name>/` with `tool.conf` and `install.sh` (and `shell.sh` if it needs shell setup). Or run
   `swarmbox-tool new <name>` to create the skeleton.
2. Run `swarmbox-tool validate` (CI runs it): required fields, a known `KIND`, unique command names across levels, an
   executable `install.sh`, a checksum for every architecture when one is declared.
3. Rebuild. **No file of the core changes**: the Dockerfile copies the whole directory and `link --system` generates the shims.

Without a rebuild, put the same directory under `~/.config/swarmbox/tools/<name>/` (user level) or `.swarmbox/tools/<name>/`
(project level); the next container start links it.

Rules that keep this extensible: manifests are data (`SCHEMA` versioned, unknown keys ignored); the core never names a
specific tool; shims are links to one dispatcher; every manifest is covered by `validate` and by installer tests that use a
fake installer (the same approach the existing tests take for Podman and Cloudflare).

### 4.10 Project-level tools and trust

A `.swarmbox/tools/` directory that arrives with a cloned repository contains an `install.sh`, which runs code in the sandbox
with network access and any keys that were passed in. The sandbox limits the damage to the host, not to those keys. So a
project-level tool is **never installed automatically**: the first time one appears, SwarmBox lists it and asks the user to
accept it, and records the accepted manifest's hash; a changed manifest asks again. (Proposal; not designed in detail yet.)

## 5. Repository structure

Existing paths are kept where they work. **New** marks proposed additions.

```
.
├── Dockerfile                       # the image (section 6)
├── README.md                        # 15-second pitch, install, first use
├── LICENSE                          # new
├── SECURITY.md                      # new: threat model, how to report
├── CONTRIBUTING.md  CODE_OF_CONDUCT.md  CHANGELOG.md        # new
├── THIRD_PARTY_NOTICES.md           # new: ttyd, starship, tmux, ...
├── build.sh  start.sh  lib/         # host side, advanced path (persistent container, web terminal)
├── cloudflare-setup.py              # module: remote access (host side)
├── container/                       # everything copied into the image
│   ├── entrypoint.sh                # new: init, install SWARMBOX_WITH, then exec "$@"
│   ├── scripts/                     # init.sh, banner.sh, messages.sh, podman-service.sh, ssh-key.sh (swarmbox-pubkey),
│   │                                #   swarmbox-init (new: prints the shell snippet),
│   │                                #   swarmbox-tool.sh and swarmbox-shim.sh (new: manager and dispatcher, section 4)
│   ├── config/                      # static configuration files: tmux, starship, ssh_config.d, bashrc fragment
│   ├── web/                         # web terminal assets: web-terminal.sh, ttyd-clipboard.js, ttyd-style.css
│   ├── mcp/<name>/config.json       # MCP servers wired into agents (chrome-devtools today)
│   └── tools/<name>/                # new: tool.conf + install.sh + optional shell.sh (section 4)
├── docs/                            # design.md (this file), web-terminal.md, cloudflare.md, nested-podman.md
├── tests/                           # helpers.py + one test file per behavior; fakes for podman, Cloudflare, installers
└── .github/workflows/               # new: ci.yml (tests), release.yml (build, scan, sign, publish)
```

File types

| Kind | Where | Who reads it | When |
|---|---|---|---|
| Dockerfile | root | the builder | image build |
| Entrypoint, scripts | `container/entrypoint.sh`, `container/scripts/` | the container | container start |
| Dispatcher and manager | `container/scripts/swarmbox-shim.sh`, `swarmbox-tool.sh` | every shim, `swarmbox-tool` | every tool call |
| Static config | `container/config/` | tmux, starship, ssh, bash | shell start |
| Web assets | `container/web/` | `swarmbox-web-terminal` | `--web` |
| MCP definition | `container/mcp/<name>/config.json` | `init.sh` | container start |
| Tool manifest and installer | `container/tools/<name>/{tool.conf,install.sh}` | `swarmbox-tool` | first use, or build with `WITH_TOOLS` |
| Tool shell setup | `container/tools/<name>/shell.sh` | the interactive shell | shell start |
| Generated shims and index | image `/usr/local/lib/swarmbox/{shims,index}`; volume `~/.local/share/swarmbox/{shims,index}` | the dispatcher | every command call (not in git) |
| Host scripts | `start.sh`, `build.sh`, `lib/`, `cloudflare-setup.py` | the user's shell | on the host |
| Tests | `tests/` | CI and contributors | every change |
| Docs | `README.md`, `docs/` | people | always |

Rules: no file outside `container/` is copied into the image; no script on the host reads from `container/` except to
build; every download has a pinned version.

## 6. How the Dockerfile behaves (proposed target)

What the image contains
- Base `node:24-slim` (Node is needed by agent installers; the base is still Debian 12). Node version is an `ARG`.
- System packages: git, openssh-client, python3 + venv, build tools, curl, jq, tmux, vim, podman and its network deps.
- Pinned, checksum-verified downloads: ttyd, starship (as today).
- The tool infrastructure: `swarmbox-tool`, `swarmbox-shim`, `swarmbox-init`, the manifests, and the shims and index that
  `swarmbox-tool link --system` generates.
- Config files and scripts from `container/`.

What it does **not** contain: any agent (Claude Code, Gemini CLI, OpenCode), gcloud, clasp, Go, Poetry. They arrive on demand
(or with `WITH_TOOLS`). The memory service was already removed before `v0.1.0` and stays out.

Behavior
- **User:** fixed `agent`, UID/GID 1000. No `USER_UID`/`HOST_OS` build arguments; the host user is mapped at run time
  (`keep-id`). `sudo` without a password is intentional: the container is the sandbox.
- **Directories:** `WORKDIR /workspace` (project mount); `/home/agent` is the persistent volume.
- **Startup:** `ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]`, `CMD ["bash", "-l"]`. The entrypoint runs `init.sh`,
  installs the missing tools in `SWARMBOX_WITH`, then `exec "$@"`. Arguments such as `pubkey`, `init`, `tool`, or any
  command run through it.
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
  `swarmbox-shim`, and writes the index. At container start the entrypoint runs `swarmbox-tool link --user` for the user
  and project levels.
- **Layer hygiene:** every `RUN` that downloads cleans up in the same `RUN` (apt lists, npm cache, temp files), because a
  later `rm` does not shrink an image. Files that must be user-writable are created with the right owner, not `chown -R`
  afterwards, which duplicates them in a new layer.
- **Pinning:** every version is an `ARG` with a default; checksums are verified when published.
- **Size budget:** the neutral image should stay under about 2.5 GB. Today's image is about 4.2 GB, of which agents, gcloud,
  clasp, Go and Poetry are roughly 2 GB. These figures come from layer measurements, not from the proposed build.
- **Flavors (optional):** CI may also publish `-claude`-style tags built with `WITH_TOOLS`, for users who want zero first-run wait.
- **Environment:** `LANG=C.UTF-8`, `NPM_CONFIG_CACHE` outside the home, `BROWSER=none`. Chromium is still installed for the
  chrome-devtools MCP; making it optional is open question 5.

## 7. Configuration model (proposed)

Precedence, highest first: command-line flag, environment variable, project `.swarmbox.env`, built-in default.

| Variable | Meaning | Default |
|---|---|---|
| `SWARMBOX_WITH` | Tools to have ready (comma list) | empty |
| `SWARMBOX_AGENT` | Agent started by `yolo` | first agent in `SWARMBOX_WITH` |
| `SWARMBOX_YOLO` | `0` disables the auto-approve aliases | `1` |
| `SWARMBOX_TOOLS_DIR` | Where tools install | `~/.local/share/swarmbox/tools` |
| `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, ... | Passed through only when set | unset |

Defaults must be neutral: no personal hosts or model names (the current local-LLM default for OpenCode is removed or off).

## 8. Distribution and versioning (proposed)

- Image `ghcr.io/<org>/swarmbox`, multi-arch (amd64, arm64), tags `X.Y.Z` and `X.Y`. `latest` exists but docs always show a
  version. Digests are published in the release notes.
- Release pipeline: build, run tests, vulnerability scan, sign (cosign), publish, attach the SBOM.
- Semantic versioning; `CHANGELOG.md`. `v0.1.0` is the last release of the private design.
- A Dependabot/Renovate config bumps the pinned versions and the base image.

## 9. Security model

What the sandbox protects: the host's files and processes outside the mounted project and the volume, and the host's Podman
socket (it is never mounted).

What it does not protect, and must say so:
- The agent can change or delete everything in the mounted project.
- The container has `sudo`, open outbound network, and can read the environment: API keys passed in are visible to the agent.
- The SSH key lives in the volume: anything running in the container can use it. Use per-repository deploy keys.
- The web terminal has no login on its own port. It is bound to `127.0.0.1`; remote access goes only through Cloudflare Access.
- Installing tools on demand means the agent triggers downloads. Versions are pinned and checksums verified where published.

Defaults: no published ports, no host networking with the web terminal, tunnel credentials stay on the host (the connector
runs outside the container), `cloudflare-setup.py` never stores the API token.

## 10. Migration from `v0.1.0`

| Today (`v0.1.0`) | Proposed |
|---|---|
| Agents baked into the image | Installed on demand (`SWARMBOX_WITH`) |
| `./build.sh --update-harness` | `swarmbox-tool update <agent>` |
| Image built locally with the host UID | One public image, `keep-id` at run time |
| `claude` alias in `bashrc` | Generated from the agent manifest |
| `start.sh` is the only entry point | `start.sh` stays as the advanced path; alias/function is the default |

## 11. Open questions

1. Agents on first install: always latest, or a version pinned in the manifest? (Latest is simpler; two users may then differ.)
2. Name of the option that lists tools: `--with` or `--agents`?
3. Claude Code's own auto-updater: keep it disabled and use `tool update`, or enable it now that the home persists?
4. How to obtain a checksum for gcloud reliably and programmatically (not yet checked).
5. Chromium: keep in the image, or make it optional? (There is no Chrome-for-Testing build for Linux arm64.)
6. OpenCode's auto-approve flag (not verified).
7. License (MIT or Apache-2.0), and the project name's availability.
8. Keep the full git history when going public, or start clean? The history must first be audited for secrets and personal data.
9. Project-level tools (4.10): how the acceptance prompt works non-interactively (CI, `swarmbox claude` from a script).

## 12. Roadmap

1. Pre-launch cleanup: license, remove personal defaults, audit history, CI with the existing tests.
2. `container/tools/`, `swarmbox-tool`, shims; move gcloud and clasp first, then the agents.
3. `entrypoint.sh`, fixed UID, `swarmbox-init`; image published to the registry.
4. Per-project `.swarmbox.env`, module flags (`--web`, `--nested`) in the generated function.
5. Optional: egress allowlist for the container's network.
