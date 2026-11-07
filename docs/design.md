# SwarmBox design

Status: **proposal** for the open-source version. Sections say whether something **exists today** (as of tag `v0.1.0`)
or is **proposed**. Nothing proposed here is implemented yet, and nothing proposed has been tested unless it says so.

SwarmBox is a persistent, safe-by-default sandbox for running coding agents in auto-approve ("YOLO") mode on your own
machine. It is one long-lived rootless Podman container with a workspace folder on your host. You enter it from any
terminal tab or from a browser, and every entry lands in the same session. The agent gets full tool access inside the box;
your host only sees the workspace folder.

---

## 1. Goals and non-goals

Goals
- A new user is productive with one install command and one command to enter the box.
- The box is **persistent**: it keeps running, and every terminal tab and browser tab shares the same tmux session.
- The image is **neutral**: it ships no agent. Claude Code, Gemini CLI, OpenCode and others are installed on demand.
- Remote access (browser, from anywhere) is part of the product, through Cloudflare, with one setup command.
- The user can read everything that will run on their host before it runs.
- Every optional capability (nested Podman, remote access, cloud CLIs) is a module they turn on.
- Versions are pinned and reproducible; updating is a choice. The exception is a tool that updates itself by design
  (Claude Code): that is explicit in its manifest (`UPDATE=self`, section 5.7).

Non-goals
- It does not make an agent trustworthy. It reduces the blast radius (section 10); it does not remove it.
- It is not a multi-user server: one box belongs to one person.
- Windows without WSL2, and macOS without a Podman machine, are not supported targets at first.
- Docker is not supported (the nested-Podman and user-namespace features are Podman's).

## 2. Principles

1. **One persistent box.** The container keeps running between uses. Entering it never creates a second one: a second tab
   joins the existing session. The box can be recreated (`reset`) without losing the workspace.
2. **Neutral image, tools on demand.** The image holds the shell environment. Agents and large CLIs (gcloud, clasp, Go...)
   are installed the first time they are needed, into the home folder, which is the workspace.
3. **Small core, opt-in modules.** The core runs the box and keeps a workspace. Everything else is a module in its own
   folder with a manifest.
4. **Data over code.** A tool, an agent or an MCP server is a directory with a manifest and, if needed, an install script.
   Adding one needs no change to the core. (`container/mcp/<name>/` already works this way.)
5. **One trust anchor.** The image is the only artifact a user must trust. The shell function that drives it is *printed by
   the image* (`init`), so it is versioned, signed and readable before it is installed.
6. **Transparent by default.** What gets added to the user's shell is a short block they can read. No hidden downloads on
   the host.
7. **Persist in one place.** Everything that must survive (projects, login, SSH key, installed tools, config) lives in the
   workspace folder, mounted as `/home/agent`. The container is replaceable; the workspace is not.
8. **Credentials that reach the internet stay on the host.** The Cloudflare tunnel connector and its credentials run outside
   the box, so an agent in the box cannot read them.
9. **Honest security.** The threat model is written down (section 10) and defaults are conservative: nothing published
   beyond `127.0.0.1`, no remote login without Cloudflare Access in front.
10. **Pinned and reproducible.** Every download has a version, and a checksum where the publisher provides one. "latest"
    is an explicit choice, never an accident of layer caching. A tool may opt out by declaring `UPDATE=self`; that is
    written in its manifest and listed in the security model.
11. **Progressive disclosure.** Default: one function, `swarmbox`. More: flags chosen at install (`--nested`, `--web-port`).
    Extra: a throwaway mode (`swarmbox --once`) and `start.sh` for people who want the raw script.

## 3. User model (proposed)

This is what `start.sh --web` already does today (persistent container, shared tmux session, optional Cloudflare). The
proposal packages it as one function, with a public image.

### 3.1 Install, once

```bash
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude          # prints the function; read it first
podman run --rm ghcr.io/<org>/swarmbox:1.2.0 init --with claude >> ~/.bashrc
```

- `init --with a,b` records `SWARMBOX_WITH=a,b`: tools to have ready. They are installed the first time the box starts.
- `init --shell zsh|fish` prints the right syntax. `init --nested` adds the Podman-in-Podman flags at creation.
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
swarmbox pubkey          # SSH public key for git (deploy keys)
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

- One box has one workspace: a folder on the host, mounted as `/home/agent`. Projects live inside it
  (`~/swarmbox/my-project`), together with the login, the SSH key, the installed tools and the config.
- Today this is `.work/` in the current directory. Proposed: `SWARMBOX_WORKSPACE`, default `~/swarmbox` (open question 9), so
  where you run `swarmbox` no longer matters.
- Creation-time options (workspace, ports, nested Podman) apply when the box is created; to change them, `swarmbox reset`.
- A second box is possible with `SWARMBOX_NAME=other SWARMBOX_WORKSPACE=...`, with its own web port.

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
    --userns=keep-id:uid=1000,gid=1000 \
    -v "${SWARMBOX_WORKSPACE:-$HOME/swarmbox}":/home/agent \
    -p 127.0.0.1:"${SWARMBOX_WEB_PORT:-7681}":7681 \
    -e SWARMBOX_WITH=claude "$img" serve
  podman start "$name" >/dev/null
  podman exec -it "$name" swarmbox-attach "$@"
}
# <<< swarmbox 1.2.0 <<<
```

- `--userns=keep-id:uid=1000,gid=1000` maps the host user to the image's fixed user (UID 1000), so one image serves every host
  UID. The agent user must not be root: Claude Code refuses auto-approve as root. (Accepted by Podman 4.3 here; a host UID other
  than 1000 has not been tested.)
- `serve` is the container's main process (section 7); `swarmbox-attach` is what joins the tmux session (3.3). Anything typed
  after `swarmbox` that is not a host-side command (`stop`, `reset`, `url`, `remote`, `update`) reaches `swarmbox-attach`,
  so `claude`, `pubkey`, `tool ...` need no host logic.

### 3.6 Host-side configuration

Host-side settings live in `~/.config/swarmbox/config` (`KEY=VALUE`), written by `init` and `remote setup`. Environment
variables override it. Nothing about Cloudflare is ever passed into the box.

## 4. Web terminal and remote access (proposed packaging of what exists)

```
browser ─ https://swarmbox.example.com ─► Cloudflare Access (e-mail code) ─► cloudflared ─► 127.0.0.1:7681 ─► ttyd ─► tmux
                                                                            (HOST)                         (inside the box)
```

### 4.1 Inside the box
- ttyd, tmux and the clipboard bridge are part of the image (a few MB, pinned and checksummed).
- `serve` starts the web terminal (ttyd running tmux) in the foreground as the container's main process, so the box lives as
  long as it. Today `init.sh` starts it in the background when the container was created with `SWARMBOX_WEB=1`. Making it the
  main process has not been tested.
- It is on by default and listens only on `127.0.0.1:7681` of the host. `SWARMBOX_WEB=0` turns it off.
- Appearance and behavior (font, theme, padding, Ctrl+C/V) come from `~/.swarmbox/web-terminal.conf` in the workspace, as today.

### 4.2 Remote access: `swarmbox remote`
- `remote setup` asks for a Cloudflare domain, an e-mail and an API token (hidden input, never stored), then provisions:
  the Access application with the one-time-code login, one tunnel per account, the DNS record, and the connector as a Podman
  container **on the host** (`swarmbox-cloudflared`, restarted automatically). Options: `--session` (login length),
  `--hostname`, `--port`. It is the existing `cloudflare-setup.py`, which stays idempotent and dependency-free.
- `remote status` reports the connector, the hostname, the login check and the session length. `remote off` removes the route
  and stops the connector. `swarmbox url` prints the local and the remote URL.
- After setup, every `swarmbox` entry makes sure the connector is up (created, started or recreated with the tunnel token),
  as `start.sh --web` does today. The tunnel token lives in the host's environment or config, never in the box.
- The login length defaults to a conservative value and is changed with `--session` (for example `168h`). Rerunning the
  setup without `--session` must keep the value already configured instead of resetting it to the default. (Today the script
  resets it to 4h; this is a change to make.)

### 4.3 Host helper
The host-side Cloudflare logic is Python, too long for the shell function. `init` and `update` extract it from the image into
`~/.local/share/swarmbox/host/` (version-matched), and the function calls it only when remote access is configured. The image
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
| Project | `.swarmbox/tools/<name>/` in the directory where `swarmbox-tool link` runs (the one `swarmbox` is entered from) | `~/.local/share/swarmbox/shims/`, `.../index` | whoever clones the project (see 5.10) |
| User | `~/.config/swarmbox/tools/<name>/` (in the workspace) | the same directory | the user, no rebuild |
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
~/.local/share/swarmbox/tools/<name>/<version>/   # the installed program ($TOOL_PREFIX)
~/.local/share/swarmbox/tools/<name>/current      # symlink to the active version (UPDATE=managed)
~/.local/share/swarmbox/tools/<name>/self/        # the single install of an UPDATE=self tool, updated by the tool
~/.local/share/swarmbox/tools/.lock               # flock, so two shells do not install at once
~/.local/share/swarmbox/shims/, .../index         # user- and project-level shims
~/.config/swarmbox/tools/<name>/                  # user-level manifests
```

`PATH` order: user-level shims, image-level shims, then `~/.local/share/swarmbox/tools/*/current/bin`. After install the real
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
`$TOOL_PREFIX` (not in `/usr`, `/etc`, `/opt`, and not in the user's shell startup files such as `~/.bashrc`), and never needs
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
sandbox. The flags live only in the manifest: when a release changes one, there is one place to fix.

- `yolo` runs the **default agent** in auto-approve mode. The default is `SWARMBOX_AGENT`, else the first agent in
  `SWARMBOX_WITH`.
- `command claude` bypasses the alias (normal prompts). `SWARMBOX_YOLO=0` disables all the aliases.
- An agent without a verified auto-approve flag gets no alias. (OpenCode's flag is **unverified**; confirm in its docs first.)

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

Without a rebuild, put the same directory under `~/.config/swarmbox/tools/<name>/` (user level) or `.swarmbox/tools/<name>/`
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
| Workspace (`/home/agent`) | yes | yes | projects, login, SSH key, `~/.claude`, installed tools, user manifests |
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
├── build.sh  start.sh  lib/         # host side: today's entry point; stays as the raw-script path
├── cloudflare-setup.py              # host side: remote access; also shipped inside the image for `swarmbox remote`
├── container/                       # everything copied into the image
│   ├── entrypoint.sh                # new: subcommands serve | attach | init | pubkey | tool | <any command>
│   ├── scripts/                     # init.sh, banner.sh, messages.sh, podman-service.sh, ssh-key.sh (swarmbox-pubkey),
│   │                                #   swarmbox-init (new: prints the shell function),
│   │                                #   swarmbox-attach (new: joins the tmux session; today lib/attach-session.sh),
│   │                                #   swarmbox-tool.sh and swarmbox-shim.sh (new: manager and dispatcher, section 5)
│   ├── config/                      # static configuration files: tmux, starship, ssh_config.d, bashrc fragment
│   ├── web/                         # web terminal assets: web-terminal.sh, ttyd-clipboard.js, ttyd-style.css
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
| Web assets | `container/web/` | `serve` (the web terminal) | container start |
| MCP definition | `container/mcp/<name>/config.json` | `init.sh` | container start |
| Tool manifest and installer | `container/tools/<name>/{tool.conf,install.sh}` | `swarmbox-tool` | first use, or build with `WITH_TOOLS` |
| Tool shell setup | `container/tools/<name>/shell.sh` | the interactive shell | shell start |
| Generated shims and index | image `/usr/local/lib/swarmbox/{shims,index}`; workspace `~/.local/share/swarmbox/{shims,index}` | the dispatcher | every command call (not in git) |
| Host scripts | `start.sh`, `build.sh`, `lib/`, `cloudflare-setup.py` | the user's shell | on the host |
| Generated host function | the user's `~/.bashrc` (between markers) | the user's shell | every terminal |
| Host config | `~/.config/swarmbox/config`, `~/.config/swarmbox/cloudflare.json` | the host function and helper | every entry, `remote` |
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

What it does **not** contain: any agent (Claude Code, Gemini CLI, OpenCode), gcloud, clasp, Go, Poetry. They arrive on demand
(or with `WITH_TOOLS`). The memory service was already removed before `v0.1.0` and stays out. `cloudflared` is not in the
image either: it runs from its own image, on the host.

Behavior
- **User:** fixed `agent`, UID/GID 1000. No `USER_UID`/`HOST_OS` build arguments; the host user is mapped at run time
  (`keep-id`). `sudo` without a password is intentional: the box is the sandbox.
- **Directories:** `WORKDIR /home/agent`, which is the workspace mounted from the host.
- **Startup:** `ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]`, `CMD ["serve"]`. Subcommands:
  `serve` (the box's main process: run `init.sh`, install the missing tools in `SWARMBOX_WITH`, start the web terminal),
  `attach` (join the tmux session; what the host function runs on every entry), `init` (print the host function),
  `pubkey`, `tool ...`, and any other command, which is run as given.
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
- **Environment:** `LANG=C.UTF-8`, `NPM_CONFIG_CACHE` outside the home, `BROWSER=none`. Chromium is still installed for the
  chrome-devtools MCP; making it optional is open question 5.

## 8. Configuration model (proposed)

Precedence, highest first: environment variable, `~/.config/swarmbox/config` (host), built-in default. Variables marked
*host* are read by the host function and helper only and are never passed into the box.

| Variable | Meaning | Default |
|---|---|---|
| `SWARMBOX_NAME` | Name of the box (container) | `swarmbox` |
| `SWARMBOX_WORKSPACE` | Host folder mounted as `/home/agent` (*host*) | `~/swarmbox` |
| `SWARMBOX_WITH` | Tools to have ready (comma list) | empty |
| `SWARMBOX_AGENT` | Agent started by `yolo` | first agent in `SWARMBOX_WITH` |
| `SWARMBOX_YOLO` | `0` disables the auto-approve aliases | `1` |
| `SWARMBOX_WEB` | `0` turns the web terminal off | `1` |
| `SWARMBOX_WEB_PORT` | Host port of the web terminal, on `127.0.0.1` (*host*) | `7681` |
| `SWARMBOX_TOOLS_DIR` | Where tools install | `~/.local/share/swarmbox/tools` |
| `SWARMBOX_UPDATE_CHECK` | `0` turns off the once-a-day "newer version" notice for managed tools | `1` |
| `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` | The tunnel's own token (*host*, never passed into the box) | unset |
| `SWARMBOX_WEB_DOMAIN`, `SWARMBOX_WEB_HOSTNAME` | Used to print the public URL (*host*) | from `cloudflare.json` |
| `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, ... | Passed through only when set | unset |

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
- The container has `sudo`, open outbound network, and can read its environment: API keys passed in are visible to the agent.
- The box is persistent: an agent keeps running (and keeps those keys) while you are away, until you stop the box.
- The SSH key lives in the workspace: anything running in the box can use it. Use per-repository deploy keys.
- The web terminal has no login on its own port. It is bound to `127.0.0.1`; remote access goes only through Cloudflare Access.
- Remote access means a browser session is a shell with `sudo`. The login length (`--session`) is the exposure window of a
  stolen or forgotten browser session: 4 hours by default today; a week is a deliberate choice. Cloudflare lets an
  administrator revoke sessions (where in the dashboard has not been checked).
- Installing tools on demand means the agent triggers downloads. Versions are pinned and checksums verified where published.
- A tool with `UPDATE=self` (Claude Code) updates itself in the background: new vendor code runs inside the box without a
  SwarmBox pin or checksum, and two workspaces can differ. It is limited to the box, but it has the same keys the agent has.

Defaults: no published ports beyond `127.0.0.1`, no host networking with the web terminal, tunnel credentials stay on the host
(the connector runs outside the box), `cloudflare-setup.py` never stores the API token, and the tunnel token is never passed
into the box.

## 11. Migration from `v0.1.0`

| Today (`v0.1.0`) | Proposed |
|---|---|
| `start.sh` creates/enters the persistent container | The `swarmbox` function does the same, from a public image |
| `./start.sh --web` plus `cloudflare-setup.py` plus token variables | Web terminal on by default; `swarmbox remote setup/status/off` |
| `.work/` in the current directory | `SWARMBOX_WORKSPACE`, default `~/swarmbox` |
| Agents baked into the image | Installed on demand (`SWARMBOX_WITH`) |
| `./build.sh --update-harness`; `DISABLE_AUTOUPDATER=true` | Claude Code updates itself (`UPDATE=self`); other agents: `swarmbox-tool update <agent>` |
| Image built locally with the host UID | One public image, `keep-id` at run time |
| `claude` alias in `bashrc` | Generated from the agent manifest |
| `cloudflare-setup.py` resets the login length to 4h on rerun | Keeps the configured value |
| `start.sh` is the only entry point | `start.sh` stays as the raw-script path |

An existing `.work/` can be used as the workspace as is: point `SWARMBOX_WORKSPACE` at it.

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
9. Default workspace path: `~/swarmbox`, or keep today's `.work/` in the current directory?
10. Project-level tools (5.10): how the acceptance prompt works non-interactively, and which directory counts as "the project"
    in a box with many projects.
11. `serve` as the main process (4.1) and `swarmbox-attach` replacing `lib/attach-session.sh`: untested.
12. Running the Cloudflare helper extracted from the image on the host (4.3): acceptable trust, or ship it as a separately
    signed release asset?
13. `swarmbox update` while sessions are running: ask before recreating, or keep the old box until the user resets it?
14. Does the vendor's native installer for Claude Code leave anything outside the home (it was not tested), and is its updater
    happier with it than with an npm install under `--prefix`? Answer together with question 3.

## 13. Roadmap

1. Pre-launch cleanup: license, remove personal defaults, audit history, CI with the existing tests.
2. `container/tools/`, `swarmbox-tool`, shims; move gcloud and clasp first, then the agents.
3. `entrypoint.sh` with `serve` and `attach`, fixed UID, `swarmbox-init`; image published to the registry.
4. `swarmbox remote` (setup, status, off) over the existing Cloudflare script, with the login length preserved on rerun.
5. Module flags at install (`--nested`, `--web-port`), host config file, `swarmbox --once`.
6. Optional: egress allowlist for the box's network.
