# SwarmBox 2.0 design

Status: **proposal** for the open-source version, SwarmBox 2.0. Nothing described as `[new]` is implemented yet. Every design decision is
taken (the Overview lists them as D1 to D39). This file is meant to be read alone: it defines its own terms (Overview), describes the code
that exists today (Today in brief), and ends with the facts that still have to be verified, each with the test that closes it (section 14).

---

## Overview

### What SwarmBox 2.0 is, who it is for, and why it redesigns v0.1.0

SwarmBox is a persistent, safe-by-default sandbox for running AI coding agents in auto-approve ("YOLO") mode on your own machine. It is
one long-lived, rootless Podman container, the **box**, with one folder of your machine, the **workspace**, mounted as its home. You enter
the box from any terminal tab or from a browser, and every entry lands in the same tmux session. The agent has full tool access inside the box;
your machine only exposes the workspace folder to it.

It is for a developer who wants to let an agent (Claude Code, Gemini CLI, OpenCode...) run without approval prompts, and wants the damage
of a mistake limited to one folder, with the same shell reachable from several terminals and from a phone or another computer.

SwarmBox 2.0 redesigns the private first version, **v0.1.0** (section "Today in brief"), because that version works only from a clone of
the repository: it builds a large image locally with the host user's UID, bakes three agents and several CLIs into it (about 4.2 GB), keeps the
workspace in `.work/` of whatever directory you are in, and drives everything with scripts (`start.sh`, `build.sh`) that must be run from the
clone. 2.0 turns it into something one can install with one command from a public image, with a small neutral image and tools installed when
first needed.

### The core idea

- **One persistent box.** The container keeps running between uses. Every terminal tab and the browser join one tmux session, `main`, in
  that one box. Entering never creates a second box.
- **A neutral image, tools on demand.** The image holds the shell environment only. Agents and CLIs (Claude Code, Gemini CLI, OpenCode,
  gcloud, clasp, Go, Poetry) are installed the first time their command is typed, through a **shim**, into the workspace.
- **The workspace is the home, and it is the only thing that must survive.** The box can be deleted and recreated (`swarmbox reset`) with
  nothing lost: projects, logins, the SSH key and installed tools are all in the workspace folder on your machine.
- **A thin host half.** A short shell function (`swarmbox`) plus a small host helper drive Podman. Cloudflare credentials and the Cloudflare
  connector stay on the host, outside the box.
- **One configuration surface.** Settings that decide how the box is created (workspace, ports, variables...) live in one host file, are applied
  when the box is created, and are compared on every entry so a stale box is reported, not silently kept.

### The pieces

```
 HOST (your machine)                                             IMAGE  ghcr.io/<org>/swarmbox:X.Y.Z
 +-------------------------------------------+                   neutral: shell environment, tmux, ttyd,
 | shell function `swarmbox`  (your rc file) |   podman run/     Podman, Node, swarmbox-tool, tool manifests
 | host helper  host:~/.local/share/         |   exec            (no agent inside)
 |              swarmbox/host/               | ------------------------+
 | config       host:~/.config/swarmbox/     |                         | the box is created from it
 | Cloudflare connector (a container, host)  |                         v
 +----------+--------------------------------+          BOX  one container named `swarmbox`
            |  127.0.0.1:7681                           +----------------------------------------------+
            +------------------------------------------>| serve  (the box's main process)              |
                                                        |  +- tmux server, session `main`  <- every tab |
 WORKSPACE  host:~/swarmbox   ===== mounted as =======> |  +- ttyd -> tmux   (the web terminal)         |
 (projects, .ssh, .claude, tools, in-box config)        |  +- nested Podman service                     |
                  /home/agent  (the home)               |  +- tools, reached through shims, installed   |
                                                        |     into the workspace on first use           |
                                                        +----------------------------------------------+
 browser ---> https://swarmbox.example.com ---> Cloudflare Access ---> connector ---> 127.0.0.1:7681 (section 5.2)
```

### Glossary

| Term | Meaning |
|---|---|
| **box** | The one long-lived Podman container (name `swarmbox` by default) in which agents and tools run. It can be deleted and recreated; its own filesystem is then lost. |
| **image** | The read-only template the box is created from: `ghcr.io/<org>/swarmbox:X.Y.Z`. It is neutral: it contains no agent. |
| **workspace** | A folder on your machine (default `host:~/swarmbox`) that holds everything that must survive: projects, logins, the SSH key, installed tools, in-box configuration. Chosen at install with `init --workspace DIR`. |
| **home** | The workspace as seen from inside the box: `/home/agent`. `<workspace>/x` and `~/x` in the box are the same file. |
| **host function** | The `swarmbox` shell function printed by `init` and placed in your shell startup file. It is the only thing you type. |
| **host helper** | A small program extracted from the image into `host:~/.local/share/swarmbox/host/`. The function calls it for everything that needs more than a few lines (configuration, creation flags, fingerprint, Cloudflare). Section 3.7. |
| **tool** | A program SwarmBox can install on demand (gcloud, clasp, Go, Poetry, an agent...), described by a directory under `container/tools/`. |
| **agent** | A tool with `KIND=agent`: a coding agent with auto-approve flags (Claude Code, Gemini CLI, OpenCode). |
| **shim** | A symbolic link on `PATH`, named after a command a tool provides, pointing to one shared dispatcher. It exists before the tool does; the first call installs the tool and runs it. Section 6. |
| **manifest** | A tool's `tool.conf` file: name, commands it provides, version, update mode, flags. Section 6.3. |
| **creation-time vs runtime** | A *creation-time* setting is fixed when the box is created (mounts, ports, hostname, variables...); changing it needs `swarmbox reset`. A *runtime* setting changes inside the running box (installing a tool, editing a config file). Section 4.3. |
| **session** | The tmux session `main` inside the box. Every terminal tab and the browser are windows of it. |
| **XDG layout** | The folder convention of the XDG Base Directory specification, applied inside the workspace: `.config/swarmbox/` (you edit), `.local/share/swarmbox/` (installed), `.local/state/swarmbox/` (logs, socket). Section 4.3. |
| **fingerprint** | A hash of the creation-time settings, stored as a label on the box when it is created, and compared with the current configuration on every entry. Section 3.7.4. |
| **today** | The git tag `v0.1.0`, the last release of the first design. "Exists today" means: read from the code at that tag (`git show v0.1.0:<path>`). |

Paths in this document. `host:~/...` is a path on your machine. `<workspace>/...` is a path inside the workspace folder; inside the box the
workspace is `/home/agent`, so `<workspace>/.config/swarmbox/` is seen there as `~/.config/swarmbox/`. `box:/...` is a path in the
container's own filesystem, which does not survive a `reset`. A bare `~` is not used for documented paths.

### Status and evidence legend

| Tag | Meaning |
|---|---|
| `[today]` | Exists in v0.1.0, read from the code at that tag. |
| `[new]` | Proposed for 2.0. Not implemented. |
| `[verified: how; date; Podman and OS; image]` | Observed. The tag says how it was observed. A field that was not recorded says "not recorded"; such items are re-checked in Part B of section 14. |
| `[unverified]` | Not checked. Each one is listed in Part B of section 14 with the test that closes it. |

A statement without a tag in a section that describes the proposal is `[new]`; in "Today in brief" and section 12 it is `[today]`.

### Reading map

| If you want to know... | Read |
|---|---|
| What v0.1.0 is, and the files this document names | "Today (v0.1.0) in brief" |
| The aims and the rules the design follows | 1, 2 |
| How a user installs and uses it, and how the host half works | 3 |
| What the box does at start, readiness and failures | 4 |
| The web terminal and Cloudflare access | 5 |
| Tools, agents and shims | 6 |
| Environment variables and keys | 7 |
| Every setting in one table | 8 |
| The repository layout and what each file is for | 9 |
| The Dockerfile, the image, distribution | 10 |
| What the sandbox does and does not protect | 11 |
| What is kept, changed, removed; migration from v0.1.0 | 12 |
| Tests and CI | 13 |
| Facts still to verify, each with its test | 14 |
| What comes in which order | 15 |

### Decisions already taken

These were decided by the project owner. No decision is open.

| # | Decision | Where it applies |
|---|---|---|
| D1 | One persistent box that every terminal tab and the browser share through one tmux session. | 3.4, 4 |
| D2 | A neutral image with no agent baked in. Tools and agents (Claude Code, Gemini CLI, OpenCode, gcloud, clasp...) are installed on demand through shims. | 6, 10 |
| D3 | Claude Code updates itself (`UPDATE=self`). | 6.7 |
| D4 | OpenCode is a shim like Claude Code; its local-LLM support moves into its tool directory. | 6.6, 6.12 |
| D5 | Nested Podman is always on; it is not a setting. | 8.3, 11 |
| D6 | macOS is in scope, through a Podman machine; to be tested on a Mac later. | 3.6, 14 (B6) |
| D7 | No host-network mode. | 12.2 |
| D8 | `start.sh`, `build.sh` and `lib/` are retired once the function has parity (every catalog row passes a test against the function, section 13). | 12, 13 |
| D9 | There is no `init.sh` in the new model; its duties are split. | 10.3 |
| D10 | XDG layout inside the workspace; files regenerated at every start live in `box:/tmp/swarmbox`. | 4.3 |
| D11 | The workspace is chosen at install with `init --workspace DIR`; default `host:~/swarmbox`. | 3.1, 3.5 |
| D12 | Environment variables are passed only when the box is created; their names are in the host config, their values come from the host environment. | 7 |
| D13 | The ttyd page is built into the image. | 5.1 |
| D14 | Cloudflare credentials and the connector stay on the host. | 5.2, 11 |
| D15 | The installer prints a shell function (not a one-line alias). | 3.1, 3.6 |
| D16 | The host helper is POSIX `sh` for everything except `remote`, which stays Python as `cloudflare-setup.py`. | 3.7.1, 3.8, 9 |
| D17 | `swarmbox update` pulls the newest tag of the same `X.Y` series and writes `IMAGE=<ref>` into the host config (the exact tag form is D35); the function reads `IMAGE`; no shell startup file is edited. | 3.8, 8.2 |
| D18 | The project level of tools is dropped in 2.0: tools exist at image and user levels only. | 6.2, 6.10 |
| D19 | No throwaway container mode in 2.0; a second box is made with `SWARMBOX_NAME`. | 2 (principle 11), 3.5 |
| D20 | The seed design: `init` prints seed values and changes nothing; the function creates the host config (from the seeds, only when the file does not exist) and extracts the helper on first use. `init` prints the right syntax for the host shell: it runs in a container and cannot tell the host's operating system, so the install line passes the host's shell name (`podman run -e SHELL ...`) and `init` uses its basename (bash, zsh or fish), else bash; `--shell` overrides. | 3.1, 3.7.1, 3.7.5 |
| D21 | Agents install `latest`; every other tool is pinned. | 6.3, 6.7, 6.12 |
| D22 | The option that lists the tools to have ready is `--with`. | 3.1 |
| D23 | `chrome-devtools-mcp` is pinned in the image, installed at build, and the installed program is run (no `npx`, no `@latest`). | 2 (principle 10), 4.4, 10.1 |
| D24 | Chromium stays in the image in 2.0; revisit when the size is measured. | 10.2 |
| D25 | The license is Apache-2.0. Checking that the name SwarmBox is available is a task to finish before the first public release. | 9.1, 15 |
| D26 | The host helper is accepted as coming from the signed image; a separately signed asset only if users ask. | 2 (principle 5), 11 |
| D27 | `swarmbox update` only pulls and tells the user to run `reset`; it never recreates the box. | 3.8, 6.7 |
| D28 | No fallback secrets file for variables in 2.0 (no `swarmbox env set`). The Cloudflare tunnel token may live in the host config, only with mode 600. | 3.7.3, 5.2, 7.3, 8.2 |
| D29 | gcloud's checksum is recorded in the manifest at release time by a maintainer script. | 6.4, 6.12 |
| D30 | On a fingerprint mismatch at entry, `up` only warns. | 3.7.4 |
| D31 | The config of a second box is `host:~/.config/swarmbox/<name>/config`; the default box keeps `host:~/.config/swarmbox/config`. | 3.5, 3.7.3 |
| D32 | The first public version is `2.0.0`; `<org>` stays a documented placeholder until the name and license are settled. | 3.1, 3.6, 10.4 |
| D33 | The bootstrap re-extracts the helper only when it is missing, not executable, or older than the function marker (compared with `sort -V`); a newer helper is kept and a one-line skew notice is printed. Rollback is `swarmbox update --to <tag>`, or replacing the function block and removing the helper folder. | 3.6, 3.7.1, 3.8, 13.3 |
| D34 | WSL2 is supported only with the workspace on the Linux filesystem, never on a Windows drive (`/mnt/c...`). `up` and `create-flags` refuse a workspace under `/mnt/<letter>/` with a clear message and the workspace exit code (4). Windows without WSL2, rootful Podman and Docker are not supported. | 1, 3.5, 3.8 |
| D35 | `swarmbox update` pulls the moving `X.Y` tag, reads the exact `X.Y.Z`, creates a local tag `<repo>:<X.Y.Z>` with `podman tag`, and writes `IMAGE=<repo>:<X.Y.Z>`, so a later `reset` works offline. | 3.8 |
| D36 | There is no `swarmbox uninstall` command in 2.0. The manual steps are documented in section 12.5 (and in the README, Phase 6 of the plan). | 12.5 |
| D37 | The audit of the git history for secrets and personal data (a scan such as gitleaks) happens in Phase 1 of the plan, and the GitHub repository stays private until the release milestone M4. | 15, implementation plan |
| D38 | The image owner is the project owner's account `feroult` on `ghcr.io`, so the image is `ghcr.io/feroult/swarmbox`. Examples keep `<org>` until the name check of D25 passes, because a different name would change the path. | 10.4 |
| D39 | The scope of 2.0.0 is the whole feature catalog (8.4), including Cloudflare remote access (`swarmbox remote`): no capability of v0.1.0 is dropped except those listed as removed in section 12. | 5.2, 8.4, 12 |

---

## Today (v0.1.0) in brief

The document cites these artifacts of the code that exists at tag `v0.1.0`.

- **`start.sh`** (492 lines): the only entry point. It checks that Podman exists, builds the image locally if it is missing, creates or starts
  one container named `swarmbox` with the workspace `.work/` of the **current directory** mounted as `/home/agent`, and enters it. When the
  container already exists it warns that creation-time options are ignored, and warns if the container was made from an older image or
  mounts a different workspace.
- **Its flags:** `--ports`, `--iports`, `--reset`, `--name`, `--image`, `--hostname`, `--no-shell`, `--host-network`, `--env-keys`,
  `--remote-browser`, `--clasp`, `--web [PORT]`. `--env-keys A,B` names host variables to pass into the container (as `-e NAME=value`).
  `--iports` only adds `host.containers.internal`; the port numbers are not used. `--image` names the image to use (default `swarmbox`).
  `--web` publishes the web terminal on `127.0.0.1` and brings up the Cloudflare connector.
- **`build.sh`**: builds the image locally, passing the host UID and GID as build arguments, with `--update-harness` to refresh the agents.
- **`lib/`**: `attach-session.sh` (what runs inside the container for every terminal that `start.sh` opens: a new window of tmux session
  `main` through a grouped session), `podman-connection.sh` (registers `podman -c <name>` on the host), `ui.sh` (messages), `web.sh`
  (web terminal and connector start).
- **`container/scripts/init.sh`**: run from the image's `bashrc` in every interactive shell. It creates `.swarmbox/` and `.claude/` folders,
  makes `<workspace>/.claude/settings.json` a link into `<workspace>/.swarmbox/`, ensures the SSH key, writes the MCP configuration
  (`build_base_mcp_config`), renders the OpenCode configuration (`build_opencode_config`, `sync_opencode_mcp`), and starts the nested Podman
  service and the web terminal.
- **`cloudflare-setup.py`**: a dependency-free Python script on the host with the commands `apply`, `status`, `remove`, `token`. It provisions
  the Cloudflare Access application, the tunnel and the DNS record, and runs the connector (`swarmbox-cloudflared`, image
  `docker.io/cloudflare/cloudflared:latest`, `--restart=always --network=host`).
- **`.work/`**: the workspace folder, in the directory where `start.sh` is run. Inside it, `.swarmbox/` holds SwarmBox's own files
  (section 12.4).
- **Baked-in agents and CLIs:** Claude Code, Gemini CLI, OpenCode, clasp, gcloud (apt), Go and Poetry (under `/opt` and `/usr/local`), `uv`.
  Claude Code's auto-updater is disabled in the image (`DISABLE_AUTOUPDATER=true`).
- **Tests:** 12 files under `tests/` (section 13).

Section 12 compares each of these with the proposal.

---

## 1. Goals and non-goals

Goals
- A new user is productive with one install command and one command to enter the box.
- The box is **persistent**: it keeps running, and every terminal tab and browser tab shares the same tmux session.
- The image is **neutral**: it ships no agent. Claude Code, Gemini CLI, OpenCode and others are installed on demand.
- Remote access (browser, from anywhere) is part of the product, through Cloudflare, with one setup command.
- The user can read everything that will run on their host before it runs.
- Every optional capability (remote access, remote browser, cloud CLIs) is a module they turn on. Nested Podman is not optional: it is always on, as today.
- Versions are pinned and reproducible; updating is a choice. The exceptions are listed in principle 10 (a tool that updates itself by design:
  Claude Code, `UPDATE=self`, section 6.7).

Non-goals
- It does not make an agent trustworthy. It reduces the blast radius (section 11); it does not remove it.
- It is not a multi-user server: one box belongs to one person.
- Windows without WSL2 is not a target. macOS (through a Podman machine) is in scope for the first release; its support is written
  from the code and has not been run on a Mac yet (B6).
- Docker is not supported (the nested-Podman and user-namespace features are Podman's). Rootful Podman is not supported either (the design relies on rootless user namespaces and `keep-id`).
- WSL2 is supported only with the workspace on the Linux filesystem, never on a Windows drive such as `/mnt/c` (D34).
- There is no host-network mode (dropped on purpose; section 12.2).

## 2. Principles

1. **One persistent box.** The container keeps running between uses. Entering it never creates a second one: a second tab
   joins the existing session. The box can be recreated (`reset`) without losing the workspace.
2. **Neutral image, tools on demand.** The image holds the shell environment. Agents and large CLIs (gcloud, clasp, Go...)
   are installed the first time they are needed, into the home folder, which is the workspace.
3. **Small core, opt-in modules.** The core runs the box and keeps a workspace. Everything else is a module in its own
   folder with a manifest.
4. **Data over code.** A tool, an agent or an MCP server is a directory with a manifest and, if needed, an install script.
   Adding one needs no change to the core. (MCP servers are registry entries too: section 4.4.)
5. **One trust anchor.** The image is the only artifact a user must trust. The shell function that drives it is *printed by
   the image* (`init`), so it is versioned, signed and readable before it is installed. The host helper comes from the same signed image: D26.
6. **Transparent by default.** What gets added to the user's shell is a short block they can read. No hidden downloads on
   the host.
7. **Persist in one place.** Everything inside the box that must survive (projects, login, SSH key, installed tools, in-box
   config) lives in the workspace folder, mounted as `/home/agent`. The container is replaceable; the workspace is not.
   Settings that belong to the host (the creation-time configuration, the Cloudflare files) live in `host:~/.config/swarmbox/`.
8. **Credentials that reach the internet stay on the host.** The Cloudflare tunnel connector and its credentials run outside
   the box, so an agent in the box cannot read them.
9. **Honest security.** The threat model is written down (section 11) and defaults are conservative: nothing published
   beyond `127.0.0.1`, no remote login without Cloudflare Access in front.
10. **Pinned and reproducible.** Every download has a version, and a checksum where the publisher provides one. "latest"
    is an explicit choice, never an accident of layer caching. Agents install `latest` by explicit choice (D21), and a tool that declares `UPDATE=self`
    (written in its manifest and listed in section 11) updates itself. `chrome-devtools-mcp` is pinned in the image and installed at build (D23, section 4.4).
11. **Progressive disclosure.** Default: one function, `swarmbox`. More: settings in one config file (section 8), written by
    `init` flags and `swarmbox config`. There is no second entry point: `start.sh` and `build.sh` are retired once the function reaches parity
    (section 12.2). A throwaway mode (a container removed on exit) is not in 2.0 (D19); a second box is made with `SWARMBOX_NAME` (3.5).

## 3. User model

A persistent container and a shared tmux session already exist today (`start.sh`; see "Today in brief"). The proposal replaces the scripts
with one function and a public image, and keeps every feature that section 12.2 does not list as a removal.

### 3.1 Install, once

`[new]`

```bash
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude          # prints the function; read it first
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude >> ~/.bashrc
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude --workspace ~/code/box >> ~/.bashrc   # choosing the workspace folder
podman run --rm ghcr.io/<org>/swarmbox:2.0.0 init --with claude --shell zsh >> ~/.zshrc                        # naming the shell explicitly
```

- `init --with a,b` (the option is `--with`, D22) records `WITH=a,b` (host config key; environment override `SWARMBOX_WITH`): tools to have ready. They are installed the first
  time the box starts.
- `init --workspace DIR` chooses the workspace folder (3.5). Without it, the workspace is `host:~/swarmbox`. The path is recorded as `WORKSPACE`; the folder is created on the first start. `init` runs in a
  container and cannot make a relative path absolute, so a relative `DIR` stays relative in the printed seed and the function's bootstrap makes it absolute on the host (3.6, 3.7.5). Use an absolute path or `~/...`
  (your shell expands `~` before `podman` sees it).
- `init --image REF` records `IMAGE` (8.2). `init --shell bash|zsh|fish` prints the right syntax. Without `--shell`, `init` uses the basename of the `SHELL` variable it receives: the install line passes the host's
  shell with `-e SHELL`, and a name that is not bash, zsh or fish gives bash (D20). `init` runs in a container and cannot tell the host's operating system by itself, which is why the shell name is passed in.
  That `-e SHELL` reaches `init`, on macOS through the Podman machine in particular, is `[unverified]` (B21); `--shell` always overrides.
- Supported hosts: Linux, macOS (through a Podman machine) and WSL2 with the workspace on the Linux filesystem (D34, 3.5). Windows without WSL2, rootful Podman and Docker are not supported.
- The first public version is `2.0.0`; `<org>` is a placeholder for the registry organization until the name and license are settled (D32, 10.4).
- `init` prints on stdout and changes nothing on the machine. What it prints, and what happens when it is run twice, is specified in 3.7.5.
- The function sits between markers (`# >>> swarmbox 2.0.0 >>>` ... `# <<< swarmbox 2.0.0 <<<`), so a person or script can find and remove it.

### 3.2 Daily use

Status is relative to v0.1.0: `[today]` means the same capability exists there (the last column says how).

| Command | What it does | Status | v0.1.0 equivalent |
|---|---|---|---|
| `swarmbox` | Enter the box: create and start it if needed, otherwise join the running one | `[new]` | `./start.sh` |
| `claude` (inside) | First call installs Claude Code into the home, then runs it | `[new]` | `claude` baked in the image |
| `yolo` (inside) | Start the default agent in auto-approve mode | `[today]` as a `claude` alias; `[new]` as "default agent" | `alias yolo='claude'` |
| `swarmbox claude` | Enter and run the agent in a new window (3.3) | `[new]` | none |
| `swarmbox url` | Print the local, and the remote when configured, address of the web terminal | `[new]` | `start.sh --web` prints both at start |
| `swarmbox remote setup` | One-time Cloudflare setup (5.2) | `[new]` front end for `[today]` script | `./cloudflare-setup.py apply` |
| `swarmbox remote status` | Tunnel up, URL, login length | `[new]` front end | `./cloudflare-setup.py status` |
| `swarmbox remote off` | Stop exposing the box | `[new]` front end | `./cloudflare-setup.py remove` (leaves the connector) |
| `swarmbox remote token` | Print the tunnel token, for people who run `cloudflared` themselves | `[new]` front end | `./cloudflare-setup.py token` / `--print-token` |
| `swarmbox remote setup --dry-run` | Read from Cloudflare and show what would change | `[new]` front end | `./cloudflare-setup.py apply --dry-run` |
| `swarmbox stop` | Stop the box; nothing is deleted | `[new]` | `podman stop swarmbox` by hand |
| `swarmbox reset` | Remove and recreate the box and wait until it is ready, without entering; the workspace and the nested-Podman volume are kept, running sessions end (3.7.2) | `[new]` | `./start.sh --reset` |
| `swarmbox update [--to TAG]` | Pull the newest tag of the same `X.Y` series (or `TAG`), record it as `IMAGE`, refresh the helper, then tell you to reset (3.8) | `[new]` | `./build.sh` then `--reset` |
| `swarmbox up` | Create and start the box without entering it; wait until it is ready | `[new]` | `./start.sh --no-shell` |
| `swarmbox --plain` | Enter with plain bash instead of the tmux session | `[new]` | `SWARMBOX_ATTACH=shell ./start.sh` |
| `swarmbox config set\|get\|list` | The host configuration (8) | `[new]` | none (flags on every call) |
| `swarmbox pubkey` | The box's SSH public key, for git deploy keys | `[today]` inside as `swarmbox-pubkey`; `[new]` as a forwarded word | `podman exec ... swarmbox-pubkey` |
| `swarmbox env add NAME` | Pass the host variable NAME into the box (applies when the box is created; 7) | `[new]` | `--env-keys NAME` |
| `swarmbox env rm NAME` | Stop passing it | `[new]` | none |
| `swarmbox env list` | The names passed, and whether each is set in this terminal (never values) | `[new]` | none |
| `swarmbox tool ...` | Manage tools inside the box (6) | `[new]` | none |

There is no `swarmbox uninstall` in 2.0 (D36); the manual steps are in 12.5.

### 3.3 Command contract

Every `swarmbox <word>` is either handled on the host or forwarded into the box. The first word decides; host-handled words win, so they are
reserved.

| Word | Where | Behavior | Exit code |
|---|---|---|---|
| `stop`, `reset`, `up`, `url`, `update`, `config`, `env`, `remote` | host only (the host helper, 3.7) | as in 3.2; none of them needs the box to be running, except that `url` and `remote status` read its labels | 0 ok; helper codes of 3.7.2 |
| `--plain` (option) | host, then forwarded | the function parses it and forwards `attach --plain` | as `attach` |
| *(nothing)* or `attach` | forwarded: `swarmbox-entrypoint attach` | open a new window of tmux session `main` through a grouped session (3.4); wait for the readiness marker first (4.2) | the shell's: 0 normally; 6 if not ready after 60 s (the box exiting while waiting is detected by `up` only, 4.2) |
| `pubkey` | forwarded: `swarmbox-entrypoint pubkey`, run without `-t` when standard output is not a terminal | print the public key | 0 |
| `tool ...` | forwarded: `swarmbox-entrypoint tool ...` | run `swarmbox-tool` (6.2) | its own |
| `<command> [args...]` (any other word) | forwarded: `swarmbox-entrypoint attach <command> [args...]` | see below | the command's own |

`swarmbox <command> [args...]` `[new]`, mechanism [verified: spike tests/spikes/spike_b13_run_command.py, tmux 3.3a in a throwaway container, a prototype wrapper; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img:1 (node:24-slim + tmux); reduced: the grouped client used script(1) as its terminal, no ttyd or host terminal] (B13; the product test in Phase 2 closes it)
- **Why the mechanism must change.** v0.1.0's `lib/attach-session.sh` ends with `exec tmux new-session ...` (line 9) `[today]`: the shell is replaced by tmux, so nothing after that line can read an exit
  code. A command that returns its status therefore cannot go through that `exec`.
- **Intended mechanism.** For a command, `swarmbox-attach` does **not** `exec` tmux. It (1) picks an id and creates the command's window in session `main`, detached, with a wrapper as the window's command:
  the command runs through an **interactive** shell (`bash -ic '<quoted command>'`, so the aliases, including the agent auto-approve flag, and the `PATH` additions of the shell fragment `container/config/bashrc.sh` apply, 6.6),
  and when it ends the wrapper writes its status to `box:/tmp/swarmbox/exit.<id>` (written to a temporary name and renamed, so a reader never sees half a number) and signals a tmux `wait-for` channel (`tmux wait-for -S swarmbox-<id>`; a signal sent before the waiter arrives is not lost: 30 instant commands in a row all returned). The wrapper is passed to `new-window` as separate arguments (`bash -c '<wrapper>' wrapper '<quoted command>' '<status file>' '<channel>'`), not as one string, which adds no quoting layer. **The wrapper must trap SIGHUP and SIGTERM**: `tmux kill-window` ends the window without running the wrapper's last lines, and without a trap `tmux wait-for` blocks forever (measured); with `trap 'echo 129 > "$status"; tmux wait-for -S "$channel"' HUP TERM` the waiter returns and the status is 129. A wrapper killed with SIGKILL cannot run a trap, but its window disappears, so the waiter also polls `tmux list-windows` for its window id (about once a second) as a fallback `[unverified]` (the fallback loop itself is not built; only that the window disappears was measured); (2) starts the grouped session of 3.4 as a child process (not
  `exec`), selected on that window; (3) waits on the channel (`tmux wait-for swarmbox-<id>`, or an equivalent wrapper) and, when it fires, ends the grouped session so the client returns even if other windows exist;
  (4) reads the status file, deletes it and exits with that status. `swarmbox false` fails and `swarmbox true` succeeds. A command killed by a signal gives `128 + signal` (the shell's own status).
  A window killed from elsewhere gives 129 (the trap); a missing status file (the tmux server died, or the wrapper was killed with SIGKILL) gives exit 1 and a message.
- **Quoting.** The function passes each argument separately to `podman exec` (`"$@"`). `attach` builds one string for the window's shell command, with each argument quoted by `printf %q`, so spaces, quotes and `$` reach the command unchanged.
- **No terminal.** When standard output is not a terminal (`swarmbox pubkey > file`, `swarmbox cmd | less`), the function runs `podman exec` **without** `-t` (only `-i`), so the output has no CR/LF translation (measured: `a\nb\n` arrives byte for byte). A tmux client needs a terminal, so
  in that case `attach` runs the command directly (as `--plain` does) and its output and status are the command's own. **It does not use `bash -ic` for this**: an interactive bash without a terminal prints
  `bash: cannot set terminal process group (-1): Inappropriate ioctl for device` and `bash: no job control in this shell` on standard error (measured; its status is right). It runs
  `SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; . <the fragment>; eval "$1"' bash '<quoted command>'` instead, sourcing the fragment file `container/config/bashrc.sh` as installed in the image **directly, not through `/etc/bash.bashrc`** (Debian's `/etc/bash.bashrc` begins with `[ -z "$PS1" ] && return`, so a non-interactive shell leaves it at once: checked by reading the file in the image `[verified: head of /etc/bash.bashrc; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]`), and the fragment `container/config/bashrc.sh` opens with
  `case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return;; esac`, so an interactive shell is unchanged and a command run this way gets the aliases and the `PATH` additions with a clean standard error
  (measured with a stand-in fragment: alias, `PATH`, exit status 9 and an empty standard error). The real fragment, once it exists, is checked in Phase 2 `[unverified]`.
- `swarmbox --plain <command>` runs the command directly (no tmux) in the exec session, by the same non-interactive form when it has no terminal and through `bash -ic` when it has one.
- A command that has the same name as a host-handled word cannot be run this way; run it with `swarmbox bash -c '<command>'`.
- What the spike showed (B13): the call returns when the command ends, with its exit code (0, 1, 130, 7, 127 for a missing command, 137 and 143 for SIGKILL and SIGTERM), in about 7 ms for `true`; 17 awkward
  arguments (space, both quotes, `$`, backslash, glob, newline, an empty argument, `-n`, `~`, a backtick, `;`, `&`, `!`, a non-ASCII letter, a tab) arrived byte for byte and none ran as a command; an alias and a `PATH`
  addition of an interactive-only fragment were in effect in the window, and not in a plain `bash -c` (the control); the grouped session ended by itself when the wait finished, with another window still open.
  What the product test (Phase 2) must still show: the same with the real `swarmbox-attach`, the real fragment and ttyd attached.

One entrypoint name is used everywhere: `box:/usr/local/bin/swarmbox-entrypoint` (source `container/entrypoint.sh`). `attach` is a **subcommand** of it;
the program that implements it is `swarmbox-attach` (9.3). Inside a running box the host function only ever calls `swarmbox-entrypoint` (through `podman exec`);
before a box exists it runs the same program as the image's entry point (`podman run --rm <image> host-helper`, `init`, `serve`; 3.6, 10.2).

### 3.4 One session for every entry point

- The first `swarmbox` creates a container named `swarmbox`, detached, and enters it.
- `serve` creates the session `main` with **one idle window** (step 9 of 4.1), so the session exists before the first tab. Entering adds a new window and, when the only other window is that idle one, closes the idle window
  (v0.1.0's `attach-session.sh` instead reuses the session's first window for the first tab `[today]`); how the idle window is recognized (for example by its name) is `[unverified]` (B36).
- Entering uses a new window of the tmux session `main` through a *grouped* session: every terminal tab, and the browser, is a
  window of the same session. Each side keeps its own current window. The grouped session ends when a tab closes; the windows
  and what runs in them stay until their shells exit. `[today]` as `lib/attach-session.sh`; `[new]` as `swarmbox-attach`.
- A host terminal tab has no tmux status bar (so a host that already runs tmux does not show tabs inside tabs); the browser
  keeps it. `[today]` (`set-option status off` on the grouped session).
- Closing every tab, or the browser, does not stop anything. `swarmbox stop` does.

### 3.5 The workspace

- One box has one workspace: a folder on the host, mounted as `/home/agent` (called the *home* when seen from inside the box).
- It is chosen once, at install, with `init --workspace DIR`; without it, `host:~/swarmbox`. The path is stored in the host config
  (`WORKSPACE`), so where you run `swarmbox` no longer matters. (Today it is `.work/` in the current directory.) The box's working directory is
  `/home/agent`; the host's current directory is not carried in.
- Creation-time options (workspace, ports, hostname, time zone, variables...) apply when the box is created; to change them,
  `swarmbox reset`.
- A second box is possible: see "Second box" below.

What is inside the workspace. Everything the box must keep lives there, because it is the home. The tool and agent dotfiles are whatever
those programs create; the `swarmbox` folders follow the XDG layout (4.3):

```
host:~/swarmbox/                       # the workspace = /home/agent in the box
├── my-project/                        # your projects
├── .ssh/                              # the SSH key (id_ed25519, id_ed25519.pub)
├── .claude/, .claude.json             # Claude Code: login, settings, history
├── .gitconfig                         # if you set a git identity inside the box
├── .config/swarmbox/                  # config you edit: web-terminal.conf, user-level tool manifests
├── .local/share/swarmbox/             # data: tools/ (claude, gcloud...), shims/
├── .local/state/swarmbox/             # state: logs, health, podman.sock
└── .local/share/containers/           # empty here: the nested Podman storage is a volume (below)
```

What is **not** in the workspace folder:
- **The host configuration**, on your machine: `host:~/.config/swarmbox/config` and `host:~/.config/swarmbox/cloudflare.json` (and
  `host:~/.config/swarmbox/<name>/config` for each second box, D31), plus the host helper in `host:~/.local/share/swarmbox/host/`. They share names with
  `<workspace>/.config/swarmbox/` because both follow XDG, but they are different places: the host one is read before the box exists (it
  holds `WORKSPACE` itself), the other lives inside the workspace.
- **The nested Podman storage**: the volume `<name>-containers`, mounted at `<workspace>/.local/share/containers`. It appears as an empty
  folder in the workspace; its contents live in the Podman volume, because they are owned by subuid-mapped IDs that the host user could
  not delete and they grow large. `[today]` (`start.sh` mounts `${CONTAINER_NAME}-containers`).
- **Host-side state of the helper**: `host:~/.local/state/swarmbox/` holds the `up` lock folders (3.7.2) and the file `notices` (3.7.5). They are small and safe to delete when no `swarmbox` command is running.
- **Files regenerated at every start**: `box:/tmp/swarmbox/` (the assembled web page, the OpenCode config, locks, the readiness marker). It is a memory-backed
  folder (`--tmpfs`, 3.6) that is empty at every start. These files are not in the workspace so they do not clutter it or a backup; a reset or a stop discards them and the next start recreates them.
- **The container's own filesystem**: anything installed with `apt` or written to `box:/usr`, `box:/etc`, `box:/opt`, plus running
  processes and tmux sessions. A `reset` discards them (6.11).

Two things to watch with this layout:
- Cache directories of other programs under `<workspace>/.cache` (for example pip's, Go's build cache) also live in the workspace and keep growing; they
  are safe to delete. SwarmBox itself keeps nothing there.
- The host reaches nested Podman through a unix socket (`podman -c <name>`). Today it is `<workspace>/.swarmbox/podman.sock`; with the XDG
  layout it is `<workspace>/.local/state/swarmbox/podman.sock`, 12 characters longer. Unix socket paths are limited to roughly
  108 bytes, so a very deep workspace path could break the connection. The default `host:~/swarmbox` is far from that limit; the helper
  should check the length and fall back to a short symlink if needed. `[unverified]` (B5). The connection is registered on Linux and WSL only; unix sockets do not cross the macOS VM.

#### Edge cases `[new]`

| Case | Behavior |
|---|---|
| `WORKSPACE` is changed in the config while a box exists | Nothing moves and nothing is deleted. The box keeps its old mount. The fingerprint (3.7.4) differs, so every entry prints "the workspace in the config is X, this box uses Y; run `swarmbox reset` to switch". The old folder is left as it is. |
| The workspace folder is missing | Created at the first start, with one message. A missing parent folder is created too. |
| The workspace is not writable by you | The helper stops before creating the box: exit 4, "swarmbox: workspace X is not writable by this user". `serve` checks again inside the box and stops if it cannot write (4.1). |
| macOS: the workspace is outside the folders shared with the Podman machine | The mount would be empty or refused. The helper checks with a throwaway container that mounts the folder and writes one file, and stops with exit 4 and the message "swarmbox: X is not shared with the Podman machine; choose a folder under your home or share it with `podman machine`". `[unverified]` (B6). |
| The workspace is already used by another box | Before creating a box, the helper looks for any container with the label `swarmbox.workspace` equal to this path and a different name; if one exists it stops with exit 5, "swarmbox: workspace X is already used by box 'other'". Two boxes on one home would share `.claude`, the SSH key and the tool installs. v0.1.0 containers have no labels and are not found by this check (3.8 covers them). |
| WSL2: the workspace is on a Windows drive (D34) | A workspace path under `/mnt/<letter>/` (for example `/mnt/c/Users/me/swarmbox`) is refused by `up` and `create-flags` before anything is created: exit 4, "swarmbox: workspace X is on a Windows drive; WSL2 is supported only with the workspace on the Linux filesystem (for example ~/swarmbox)". Permissions, ownership and `keep-id` do not behave on a Windows drive; the refusal is `[unverified]` as to the exact paths WSL mounts (B32). |
| Creation fails (a published port is in use on the host, for example 7681; Podman rejects an option) | `podman run` fails. `up` removes **only the container this call created**, found by the ID that `podman run --cidfile` wrote (Podman does leave it in state `Created` when the failure is a port in use, and the cidfile then holds its full ID: `[verified: spike tests/spikes/spike_b18_port_in_use.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` B18; that the same holds for other failures is `[unverified]` B33); a container that merely has the box's name and was not created by this call is never removed (measured: `podman run --name X` when X exists exits 125, writes no cidfile and leaves the old container running, so there is nothing to remove). `podman run` exits 126 for the busy port, with `Error: rootlessport listen tcp 127.0.0.1:<port>: bind: address already in use` on standard error, and exits 125 when the `--cidfile` path already exists (`container id file exists`), so each call uses a fresh path (the code in 3.6 does). It prints the message of 3.8 ("could not create the box") and exits 7. The configuration is not changed: fix the cause, for example with `swarmbox config set WEB_PORT 7682`, and run `swarmbox` again. The workspace and the volume `<name>-containers` are untouched. |
| Second box | A box is a name: `SWARMBOX_NAME=other` (with its own `SWARMBOX_WORKSPACE` and `SWARMBOX_WEB_PORT`) in the terminal that runs `swarmbox`. `config` and `env` act on the config file of that name, so the variable list and the fingerprint refer to the right box. The config of a second box is `host:~/.config/swarmbox/<name>/config`; the default box keeps `host:~/.config/swarmbox/config` (D31). A throwaway `--once` mode is not in 2.0: a second box is the way to get another container (D19). |

### 3.6 The generated function

A simplified sketch of what `init` prints for bash (the zsh and fish variants have the same shape). It stays thin: anything with more than a
few lines is in the host helper (3.7). Status: `[new]`.

```bash
# >>> swarmbox 2.0.0 >>>
swarmbox() {
  local dir="$HOME/.local/share/swarmbox/host" host name tmp hv="" tty=-i
  local image="ghcr.io/<org>/swarmbox:2.0.0" version="2.0.0"   # seed values written by init (3.7.5); the marker version is the second
  local seed_with="claude" seed_ws=""                          # more seeds, one per init flag that was given (--workspace, --image, 3.7.5)
  host="$dir/swarmbox-host"
  [ -x "$host" ] && hv=$("$host" version 2>/dev/null)          # the helper's version; empty when it cannot be read
  # bootstrap (D33, 3.7.1): extract only when the helper is missing, not executable, or older than the marker (sort -V); a newer helper is kept
  if [ ! -x "$host" ] || { [ "$hv" != "$version" ] && [ "$(printf '%s\n%s\n' "$hv" "$version" | sort -V | head -n 1)" = "$hv" ]; }; then
    command -v podman >/dev/null || { echo "swarmbox: Podman is not installed." >&2; return 3; }   # full text: 3.8
    mkdir -p "${dir%/*}" && tmp=$(mktemp -d "$dir.new.XXXXXX") || return 3
    # not a pipe: a pipe's status is tar's, and pipefail is not available in bash 3.2, zsh or fish; so write the archive to a file, unpack it, then test the result
    if ! { podman run --rm "$image" host-helper > "$tmp/helper.tar" && tar -x -C "$tmp" -f "$tmp/helper.tar" && [ -x "$tmp/swarmbox-host" ]; }; then
      rm -rf "$tmp"; echo "swarmbox: cannot pull $image ..." >&2; return 3   # exit 3, previous helper untouched; full text: 3.8
    fi
    rm -f "$tmp/helper.tar"
    rm -rf "$dir.old"; { [ ! -e "$dir" ] || mv "$dir" "$dir.old"; } && mv "$tmp" "$dir" || { rm -rf "$tmp"; return 3; }
    rm -rf "$dir.old"                               # a failure before this line leaves the previous helper in place
  elif [ "$hv" != "$version" ]; then                # the helper is newer than this block, typically after `swarmbox update`: keep it, say so
    echo "swarmbox: the helper ($hv) is newer than this function ($version); kept" >&2   # one line, 3.8 (update flow, step 5)
  fi
  # seeds (D20, 3.7.5): a relative --workspace is made absolute here, on the host, against the directory of this call; the helper writes the seeds into the config only if it does not exist yet
  case "$seed_ws" in ""|/*) ;; *) seed_ws="$(pwd)/${seed_ws#./}" ;; esac
  "$host" config seed ${seed_with:+--with "$seed_with"} ${seed_ws:+--workspace "$seed_ws"} || return   # flags, not SWARMBOX_* variables: those would override the file
  case "${1-}" in                                   # words handled on the host (3.3)
    stop|reset|up|url|update|config|env|remote) "$host" "$@"; return ;;
  esac
  "$host" up || return                              # create if needed, start, check, wait until ready
  name=$("$host" config get NAME) || return         # NAME comes from SWARMBOX_NAME or the default; it is not a key of the file (8.2)
  [ -t 1 ] && tty=-it                               # no -t when standard output is not a terminal: `swarmbox pubkey > file` must have no CRLF (3.3)
  case "${1-}" in                                   # words forwarded as they are (3.3)
    pubkey|tool) podman exec $tty -e TERM -e COLORTERM "$name" swarmbox-entrypoint "$@"; return ;;
    attach) shift ;;                                # a leading "attach" is a prefix, not an argument
  esac
  podman exec $tty -e TERM -e COLORTERM "$name" swarmbox-entrypoint attach "$@"   # nothing, --plain, or any other command; the exit status is the command's (3.3)
}
# <<< swarmbox 2.0.0 <<<
```

The sketch is abbreviated (no zsh or fish variants, no `--shell` handling, simplified error text) but follows the command contract of 3.3, which is
normative. The bootstrap block runs before the helper exists, so it can use only `podman`, `tar`, `mktemp`, `mv`, `rm`, `printf`, `sort` and `head`; the image reference
it uses is the seed value embedded in the block, because the configuration file does not exist yet (it never reads `IMAGE`; the helper's `up` does, D17). `<org>` stands for the registry organization,
a placeholder until the name and license are settled (D32, 10.4). The helper's `version` subcommand (3.7.2) prints the version of the image it was extracted from.

**The bootstrap condition (D33).** The function extracts the helper only when it is missing, not executable, or older than the marker `version`, the comparison being made with `sort -V`
(so `2.0.10` is newer than `2.0.9`). When the helper is **newer** than the marker (after `swarmbox update` the helper comes from a newer image while the block keeps its old marker), the function keeps it
and prints a one-line skew notice on standard error; it never re-extracts the older helper, so an update is not undone by the next call. If `sort -V` is not available the comparison gives no answer and the helper is kept;
whether macOS's `sort` has `-V` is `[unverified]` (B19). Rollback is in 3.8.

How the helper's `up` assembles the creation command. The arguments are collected in an **array** and expanded quoted; an unquoted `$(...)` would split
on spaces and break any value that contains one (the defect 7.1 describes for today's code). The helper is POSIX shell (D16); the sketch
is POSIX shell, where the positional parameters are the array. Three rules shape it: `up` takes a host lock, so two terminals that start at once create one box; it captures the flags **before** it runs
`podman`, and checks the status of `create-flags`, so a helper failure never reaches `podman run`; and on a failed create it removes only the container this call created.

```sh
state="${XDG_STATE_HOME:-$HOME/.local/state}/swarmbox"; mkdir -p "$state" || exit 4
lock="$state/up-$name.lock"; n=0
until mkdir "$lock" 2>/dev/null; do                  # mkdir is atomic: exactly one caller wins
  # stale lock: the holder's pid does not answer `kill -0`, or no pid file appeared within 5 s of the folder
  p=$(cat "$lock/pid" 2>/dev/null)
  { [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; } && { rm -rf "$lock"; continue; }
  n=$((n+1)); [ "$n" -gt 90 ] && { echo "swarmbox: another 'up' holds $lock" >&2; exit 6; }
  sleep 1
done
echo $$ > "$lock/pid"; trap 'rm -rf "$lock"' EXIT; trap 'exit 1' INT TERM     # removed on every way out
# ... fast path: one `podman container inspect` (3.7.2); if the box exists and runs, check labels and return ...
flags="$state/flags.$$"
create_flags > "$flags" || { rc=$?; rm -f "$flags"; exit "$rc"; }   # the status is checked here; reading `$(create_flags)` through a here-document would discard it
set --
while IFS= read -r line; do set -- "$@" "$line"; done < "$flags"   # a redirect, not a pipe: the loop runs in this shell
rm -f "$flags"
cid="$state/cid.$$"; rm -f "$cid"
if ! podman run -d --name "$name" --cidfile "$cid" "$@" "$image" serve; then   # "$@" quoted: each line stays one argument
  [ -s "$cid" ] && podman rm -f "$(cat "$cid")" >/dev/null 2>&1   # only the container this call created, by ID; never one that merely has the name
  rm -f "$cid"; echo "swarmbox: could not create the box: ..." >&2; exit 7   # message of 3.8
fi
rm -f "$cid"
```

`create-flags` prints one argument per line; no argument can contain a newline (the config grammar forbids it, 3.7.3). The lock is a folder, not a file with `flock`, because `flock` is not part of macOS. A stale lock is
one whose pid is gone, or that has no pid file after 5 s; a live holder is waited for, up to 90 s, then `up` exits 6. The lock is held until the box is ready or creation has failed, so the second terminal waits, then finds the box
and takes the fast path. That `mkdir` is atomic on the supported hosts, that the stale rule never removes a live lock, and that `--cidfile` is written when `podman run` fails after creating the container are `[unverified]` (B33) except for one failure, a busy host port, where it is written and holds the ID (B18, 3.5).

- `create-flags` prints one argument per line for every creation-time setting (8): the workspace mount, `--hostname`, `--tz`, `--init` (only when the resolved `INIT` is 1: `up` resolves `auto` to 0 or 1 and passes the resolved value, so `create-flags` stays a pure function and starts no container),
  `--pids-limit=16384`, a `-p` per published port (the user's `PORTS`, plus the ports that `tool-ports` lists for each tool in `WITH`: 6.3), the memory-backed folder for the
  regenerated files (`--tmpfs /tmp/swarmbox`, so the readiness marker cannot survive a restart: 4.1 step 0, 4.2), the nested-Podman flags (always: `--device /dev/net/tun`,
  `--security-opt unmask=/proc/*`, `-v <name>-containers:/home/agent/.local/share/containers`), `-e SWARMBOX_<KEY>=value` for every non-secret
  key the box reads (8.1), `-e NAME` per listed variable (7), the labels (3.7.4), and the user namespace. On macOS it adds
  `--security-opt label=disable` and an explicit `keep-id:uid=<host>,gid=<host>`. Among them, `--userns=keep-id:uid=1000,gid=1000` maps the host
  user to the image's fixed user (UID 1000), so one image serves every host UID. The agent user must not be root: Claude Code refuses auto-approve
  as root. `[verified: podman run accepted the option, no container inspection; date not recorded; Podman 4.3, Linux; image not recorded]`. A host UID
  other than 1000 has not been tested `[unverified]` (B7). Today the image is built with the host UID instead (`start.sh` and `build.sh`, `[today]`).
- `serve` is the container's main process (4.1); the function never starts anything else in the box except `attach`.

### 3.7 Host-side components

The host half is: the shell function (3.6), one host helper, the host configuration, and the optional Cloudflare connector (a container on the host, 5.2).

#### 3.7.1 The host helper `[new]`

- Installed in the folder `host:~/.local/share/swarmbox/host/`, extracted from the image. It is extracted **by the function itself**, in the
  bootstrap step of 3.6, on the first call that finds it missing, not executable, or older than the version in the function's marker (compared with `sort -V`), and by `swarmbox update` (3.8). A helper that is
  **newer** than the marker is kept and a one-line skew notice is printed (D33). The command is
  `podman run --rm <image> host-helper`: `host-helper` is a subcommand of the image's entry point (10.2) and writes a tar archive on stdout, which the function saves to a file in a temporary
  folder and unpacks there. The function does **not** rely on the exit status of a pipe (it would be `tar`'s, and `pipefail` cannot be assumed in bash 3.2, zsh or fish). It treats the
  extraction as failed unless `podman run` exited 0, `tar` exited 0 **and** `[ -x "<temporary folder>/swarmbox-host" ]` is true. **The function verifies that the helper is executable before renaming**; on any
  failure it deletes the temporary folder, prints the message of 3.8 and exits 3, and the previous helper is left as it was. Only after the check is the temporary folder renamed into place. On the
  first call `<image>` is the seed value embedded in the function block (3.7.5); `update` uses the image it has just pulled. If `podman` is absent or the image cannot be pulled, the call
  exits 3 with the matching message of 3.8. This is the seed design (D20): `init` only prints; the function extracts the helper and the helper creates the config.
- **Contents of the archive** (proposed; the files come from `box:/usr/local/share/swarmbox/host/` in the image, 9.3):

  | File in the archive | What it is |
  |---|---|
  | `swarmbox-host` | the helper program, a POSIX `sh` script (executable; its location is fixed because the function tests it) |
  | `cloudflare-setup.py` | the Cloudflare script that `swarmbox remote` runs (5.2) |
  | `templates/` | the function templates for bash, zsh and fish (the same files `init` prints from, 3.7.5) |
  | `tool-ports` | one line `<tool><TAB><port>` per port that an image-level tool manifest declares with `PORTS` (6.3). Generated at image build by `swarmbox-tool link --system`, so the host can add a tool's ports at creation without reading the image. The build **always** writes it, as an empty file when no manifest declares ports; so a missing `tool-ports` means a corrupted or incomplete helper archive (exit 3), never a normal state |
- Language (D16): POSIX `sh` for everything except `remote`, which stays Python as `cloudflare-setup.py` and is the only place that needs `python3` on the host (3.8). That the
  helper runs unchanged under macOS's `/bin/sh`, dash and busybox `sh` is `[unverified]` (B23).
- The function and the helper are the only host code. Everything else runs in the image.

#### 3.7.2 CLI contract

`swarmbox-host <subcommand> [args]`. Standard output carries data only; messages and warnings go to standard error.

| Subcommand | Input | stdout | Exit codes |
|---|---|---|---|
| `create-flags` | the resolved configuration (with `INIT` already resolved to 0 or 1 by `up`); the environment; the file `tool-ports` next to the helper (3.7.1) | one argument per line (3.6) | 0; 2 usage; 4 workspace problem, including a workspace under `/mnt/<letter>/` on WSL (D34); 3 prerequisite missing, including a missing `tool-ports` (a corrupted helper archive, 3.7.1) |
| `version` | none | the version of the image the helper was extracted from (compared with the function's marker by `sort -V`, 3.6) | 0 |
| `config get KEY` | key name (without `SWARMBOX_`) | the resolved value (environment, then file, then default). `NAME` comes from `SWARMBOX_NAME` or the default only: it selects the config folder, so it is not a key of the file (8.2) | 0; 2 unknown key; 1 key unset and no default |
| `config seed [--with L] [--workspace DIR] [--image REF]` | the seed values the function holds (3.7.5) | nothing | 0; 2 invalid value. Writes the config file from the seeds only when the file does not exist; otherwise changes nothing and prints, once per key, the notice of 3.7.5 for a seed that differs from the file |
| `config set KEY VALUE` | key (not `NAME`) and value; for `CLOUDFLARE_TUNNEL_TOKEN` the value is read from the terminal without echo, never from the command line (3.7.3) | nothing | 0; 2 unknown key or invalid value (names the grammar rule) |
| `config list` | none | `KEY=VALUE` per line, with the source (`env`, `file`, `default`) as a third tab-separated field; the value of `CLOUDFLARE_TUNNEL_TOKEN` is never printed (`set` or `unset` instead) | 0 |
| `env add NAME` / `env rm NAME` | a variable name | nothing | 0; 2 invalid name or a name starting `SWARMBOX_CLOUDFLARE_` (7.2) |
| `env list` | none | `NAME<TAB>set` or `NAME<TAB>not set`, never a value | 0 |
| `fingerprint` | the resolved configuration | the hash, and with `--explain` the lines that differ from the box's labels | 0 same; 1 different; 5 no box |
| `url` | none | the local URL, and the public one when configured | 0 |
| `up` | none | nothing | 0 ready; 3 prerequisite or network; 4 workspace (not writable, not shared with the Podman machine, or on a Windows drive under WSL, D34); 5 conflict with another box or a v0.1.0 container (3.8); 6 not ready after 60 s, or the box exited while waiting (`up` only: it also reads the container state and prints `podman logs --tail`, 4.2), or another `up` held the lock for more than 90 s; 7 creation failed (3.8) |
| `update [--to TAG]` | none | nothing | 0; 2 invalid tag; 3 pull failed or the local tag could not be created (nothing changed) (3.8) |
| `reset` | none | nothing | the codes of `up`: 0 ready; 3, 4, 5, 6, 7 as in `up`; 1 if removing the old container failed. Exit 5 also when the container exists without the label `swarmbox.managed` (see below) |
| `stop` | none | nothing | 0; 1 podman failed |
| `remote setup\|status\|off\|token` | options of 5.2 | as `cloudflare-setup.py` | 0; the script's code; 3 if `python3` is missing |

**What `up` does** `[new]`, in order:
1. Prerequisite and workspace checks (3.8), including the refusal of a workspace under `/mnt/<letter>/` on WSL (D34).
2. Take the host lock (3.6): an atomic `mkdir` of `host:~/.local/state/swarmbox/up-<name>.lock`, removed on every exit, with the stale-lock rule of 3.6.
3. **Find the box with an exact name match.** One `podman container inspect --format '<state>|<name>|<labels>' <name>` gives the state and the labels (`swarmbox.managed`, `swarmbox.image`, the fingerprint inputs) together, and the helper
   compares the printed name with the box's name, because Podman also resolves ID prefixes. The helper never uses `podman ps -a -q -f name=<name>`: that filter matches substrings, and v0.1.0 uses it (`start.sh` around lines 395 and 443 `[today]`),
   so `swarmbox` would match `swarmbox-cloudflared`. Where a listing is needed it uses `podman container exists <name>` or a filter anchored as `^<name>$`.
4. **Fast path: the box exists and is running.** Nothing else is called: the labels from step 3 give the fingerprint, image and workspace comparison (3.7.4), the warnings are printed, the lock is released and the function enters; `attach` itself waits for the
   readiness marker inside the box (4.2). The budget is at most two Podman calls before the function attaches (the inspect, plus at most one more, for example the connection check); this has not been measured `[unverified]` (B35).
5. A stopped box is started (`podman start`) and waited for. A missing box is created: `INIT=auto` is resolved to 0 or 1 here (today's `start.sh` detects `--init` support by running a throwaway container, around line 386 `[today]`), the flags are captured and
   checked (3.6), `podman run -d --cidfile` creates it, and `up` waits for the marker (4.2). A v0.1.0 container or a box of another workspace stops `up` with exit 5 (3.5, 3.8).
6. The lock is released on exit, whatever the exit.

**What `reset` does** `[new]`, in order:
1. Look for a container with the box's name. If one exists **without** the label `swarmbox.managed` (a v0.1.0 container), do nothing to it: print the v0.1.0 message of 3.8 and exit 5. A container that was not created by this design is never removed.
2. Otherwise, if a container exists, run `podman rm -f <name>`. Its processes and tmux sessions end; the volume `<name>-containers` and the workspace are kept. If the removal fails, exit 1.
3. Run the same steps as `up` (the prerequisite and workspace checks, creation with a fresh `create-flags`, start, wait for the readiness marker; 3.6, 4.2), without entering. It returns after readiness with `up`'s exit code.
4. The next `swarmbox` enters the new box. If no container existed, `reset` simply creates one.

#### 3.7.3 Configuration file grammar

- File: `host:~/.config/swarmbox/config` for the default box; `host:~/.config/swarmbox/<name>/config` for a second box started with `SWARMBOX_NAME=<name>` (D31). One `KEY=VALUE` per line. Everything after the first `=` is the value, taken **literally**: no quoting, no escapes,
  no variable expansion, leading and trailing blanks trimmed. A value cannot contain a newline.
- Lines starting with `#` (after optional blanks) and blank lines are ignored.
- List values are comma separated with no spaces (`WITH=claude,gcloud`, `ENV_KEYS=ANTHROPIC_API_KEY,GEMINI_API_KEY`).
- An empty value (`PORTS=`) means "use the default". A key that is absent means the same.
- **Unknown keys:** reading ignores them with one warning on standard error (so a file from a newer SwarmBox still works); `config set` refuses them.
- **`NAME` is not a key of the file.** It selects which config folder is read (D31), so it can only come from `SWARMBOX_NAME` (default `swarmbox`); a `NAME=` line in the file is an unknown key.
- A later line for the same key replaces an earlier one. Keys are upper case, `[A-Z][A-Z0-9_]*`. The file holds no secret except one: the Cloudflare tunnel token (key `CLOUDFLARE_TUNNEL_TOKEN`, 5.2, 8.2), and only with mode 600 (D28).
  **How the helper enforces the mode** `[new]`: it creates the file under `umask 077` and runs `chmod 600` on it after every write; `config set CLOUDFLARE_TUNNEL_TOKEN` reads the value from the terminal without echo
  and refuses to write it if the `chmod` fails (exit 1); on every read, when the file holds the token key and its mode is not exactly 600 (checked portably, see below), the helper ignores the token, prints one line
  ("the config file holds the tunnel token but its mode is X; run `chmod 600 <file>`") and goes on without it. Whether this holds on every host (macOS, a WSL home on a Windows drive) is `[unverified]` (B22).
  **The mode check does not parse a directory listing** (the text of `ls`; macOS prints `-rw-------@` when the file has extended attributes, so a text comparison would fail): the helper reads the mode as an octal number, with `stat -c %a` on Linux, `stat -f %Lp` on macOS, or, where neither works,
  `find <file> -perm 600` combined with a test for any other permission bit. That each form works on every supported host is `[unverified]` (B34).
  Variables for the box never go in this file (7.3, D28).
- Precedence, highest first: environment variable `SWARMBOX_<KEY>`, this file, built-in default.

#### 3.7.4 Labels and the fingerprint

At creation the box gets these labels. They are the only state the host keeps about the box.

| Label | Value |
|---|---|
| `swarmbox.managed` | `2` (marks a box made by this design; v0.1.0 containers do not have it) |
| `swarmbox.image` | the image reference used (`IMAGE`) |
| `swarmbox.workspace` | the absolute workspace path |
| `swarmbox.ports` | the published ports, including those the helper added from `tool-ports` for the tools in `WITH` (6.3) |
| `swarmbox.env-hash` | hash of the passed variables (7.1) |
| `swarmbox.fingerprint` | SHA-256 over the sorted lines `KEY=value` of every creation-time key of 8.2 (resolved values, workspace absolute, `TZ` resolved, the ports from `tool-ports` for the tools in `WITH` included) plus the line `env-hash=<hash>`; secrets and Cloudflare keys are not included |

On every entry `up` recomputes the fingerprint from the current configuration and compares: when it differs it prints one line per differing key
("`PORTS` changed: box has 3000, config has 3000,8080; run `swarmbox reset` to apply") and continues. It only warns (D30): it never offers to run `reset`, which ends sessions and must be explicit. Warnings never block entering.
This replaces v0.1.0's separate warnings (options ignored on an existing container, older image, different workspace).

#### 3.7.5 What `init` prints, and running it twice `[new]`

- `init` prints, on stdout only: a comment line naming the version, the marker block with the function of 3.6 for the chosen shell, and, inside the
  block, the values given as flags (`--with`, `--workspace`, `--image`) as **seed** values. Nothing is written to the machine.
- The seed values also drive the first-run bootstrap (3.6): the function's own image reference and version are used to extract the host helper before
  any configuration exists. On the first call the function first extracts the helper (3.7.1); then it calls `swarmbox-host config seed` with the seeds as **arguments**, and the helper, finding no config file, creates it from them.
  **Seeds are written into the host config only when the file is created. They are never passed as `SWARMBOX_*` environment variables**, because those override the file on every call. Once the file exists the seed is not applied again: when a seed
  value differs from the file the helper prints once per key "init asked for `WITH=a`, the config says `WITH=b`; run `swarmbox config set WITH a` to change it".
- **Relative `--workspace`.** `init` runs in a container and cannot make a relative path absolute. The function's bootstrap does it on the host, with `$(pwd)`, against the directory of the call that creates the config, and the helper prints the
  absolute path it recorded; an absolute path or `~/...` (expanded by the shell at install) avoids the question.
- **"Prints once per key" needs state.** The helper keeps `host:~/.local/state/swarmbox/notices`, one line per key already announced, in the form `<box name>:<KEY>`; a notice is printed only when its line is absent, and the line is added after printing.
  `swarmbox config set KEY ...` removes that key's line, so a later difference is announced again. The file is host state, not configuration: deleting it only repeats notices.
- **Flags after the first call.** Once the config file exists, `init --workspace`, `--with` and `--image` only change the seed in the printed block; they do
  not change the file. Use `swarmbox config set KEY VALUE` (3.7.2) instead.
- **Running `init` twice.** Appending the second block with `>>` leaves two blocks. They define the same function, so the later definition replaces
  the earlier one and the shell works; the markers make the old block easy to delete. A second run **with different flags** therefore changes the function
  (for example another version) but not the config file; the notes above say how to change the keys.
- This is the seed design (D20): `init` prints seed values and changes nothing; the function creates the host config and extracts the helper on first use. The same rules apply to the config file of a second box (D31).

### 3.8 Install, upgrade and failure behavior `[new]`

Prerequisite checks run in the function's bootstrap step (Podman and image, 3.6), in `up` (all of them) and in `init --shell` (the shell name). Each failure stops with
the exit code shown and one message, and changes nothing. **First-run sequence**, the same in 3.6, 3.7.1, 3.7.5 and here: (1) `init` prints the function; (2) on the first call, which finds no helper, the function checks that
`podman` exists (exit 3), (3) runs `podman run --rm <image> host-helper`, which pulls the image if needed, saves the archive to a file in a temporary folder, unpacks it and requires `[ -x <folder>/swarmbox-host ]` (exit 3 on any failure, previous helper untouched; 3.7.1),
(4) renames the folder into place, (5) calls the helper, which creates the config file from the seed (3.7.5) and runs `up` with the remaining checks below.

| Check | Message | Exit |
|---|---|---|
| Known shell (only for an explicit `--shell`; a `SHELL` value that is not bash, zsh or fish silently gives bash, D20) | `swarmbox init: unknown shell 'X'. Use --shell bash, zsh or fish.` | 2 |
| Workspace not on a Windows drive (WSL, D34) | `swarmbox: workspace X is on a Windows drive; WSL2 is supported only with the workspace on the Linux filesystem (for example ~/swarmbox).` | 4 |
| Podman installed (also checked by the function's bootstrap) `[today]` text, reworded | `swarmbox: Podman is not installed.` then `Linux: sudo apt install podman (Debian/Ubuntu) or sudo dnf install podman (Fedora/RHEL)` and `macOS: brew install podman` | 3 |
| Podman version at least 4.3 (the version where the `keep-id` form was observed; the true minimum is B8) | `swarmbox: Podman X.Y found, 4.3 or newer is required. Upgrade Podman and try again.` | 3 |
| `python3` present, checked only by `swarmbox remote` (the helper is POSIX `sh`, D16) | `swarmbox: python3 is needed for 'swarmbox remote' and was not found.` | 3 |
| Image present, or pullable, and its helper archive usable (also checked by the function's bootstrap, before the helper exists; if Podman succeeded but the archive holds no executable `swarmbox-host`, `<Podman's message>` is replaced by "the image has no usable host helper") | `swarmbox: cannot pull <image>: <Podman's message>. Check the network, or set SWARMBOX_IMAGE to an image you already have.` | 3 |
| `/dev/net/tun` exists (Linux and WSL; on macOS `serve` checks inside the Podman machine) | `swarmbox: /dev/net/tun is missing on this host. Nested Podman needs it. On Linux try: sudo modprobe tun` | 3 |
| Create fails (port in use, rejected option) | ``swarmbox: could not create the box: <last lines of Podman's error>. If a port is in use, change WEB_PORT or PORTS with `swarmbox config set`.`` `up` first removes the partly created container this call made, by its ID, never another one of that name (3.5, 3.6). | 7 |
| Writable shell startup file | `init` never writes it (3.7.5). If the redirect `>> ~/.bashrc` fails, the shell prints its own error and the function is not installed; `init` prints a one-line hint to standard error when its output is a terminal ("append this to your shell startup file"). | 0 for `init` |

Today only the Podman check exists, with the same advice (`start.sh`); there is no tun, version or network check `[today]`.

**Image handling.** A missing image is **pulled**, never built, by the function. v0.1.0 builds locally when the image is missing; that is dropped (12.3).
To run a locally built image: `podman build -t swarmbox:dev .` then `SWARMBOX_IMAGE=swarmbox:dev swarmbox` (8.2, key `IMAGE`).

**Update flow.** `swarmbox update`:
1. Resolve the target (D17, D35). Without options, it is the newest tag of the same `X.Y` series as the current `IMAGE`: the helper pulls the moving `X.Y` tag (10.4), and the exact `X.Y.Z` is the version
   that the helper extracted from that image reports (step 3). With `--to TAG`, the target is exactly that tag (any series, older or newer). Pulling the `X.Y` tag and reading the version from the helper is `[unverified]` (B20).
2. Pull it. If this fails (offline, registry error) **nothing changes**: the old helper, the old config and the running box stay; exit 3.
3. Extract the helper from the new image into a temporary folder, check that `swarmbox-host` is executable, and rename it over the old one (3.7.1).
4. Create a local tag for the exact version, `podman tag <repo>:X.Y <repo>:X.Y.Z` (D35), and write `IMAGE=<repo>:X.Y.Z` into the host config (D17). The exact tag is what the box's label and a later `reset` use, so a `reset` works offline and
   does not follow a moving tag. If `podman tag` fails, nothing is written (exit 3). No shell startup file is edited: the function block keeps its marker and seed. Then print "updated to X.Y.Z; run `swarmbox reset` to use it (running sessions end)".
   `update` only pulls and tells you to run `reset`; it never asks and never recreates the box (D27).
5. **The next call does not undo the update (D33).** The helper is now newer than the function's marker, so the bootstrap (3.6) keeps it and prints one line, "the helper (X.Y.Z) is newer than this function (A.B.C); kept". The line goes
   away when the block is replaced by a newer one (`init` from the new tag, appended or substituted by hand); nothing else needs to change.

**Version skew.** The function carries its version (the marker); the box carries `swarmbox.image`. On every entry the helper compares the image the config asks for
with the box's label. If they differ it prints "this box was created from <A>; the config asks for <B>; run `swarmbox reset`". When the reference is the same
but the local image has been replaced since (a new pull of the same tag) it prints the stale-image warning, as v0.1.0 does by comparing image IDs `[today]`.
Neither warning blocks entering.

**Rollback (D33).** Two ways, then `swarmbox reset` for the box:
- `swarmbox update --to <tag>` pulls that tag, extracts its helper and writes `IMAGE`. Because the bootstrap re-extracts a helper that is older than the function's marker, this works when `<tag>` is not older than the marker
  of the function block in the shell startup file; below that marker the function would re-extract the helper from its own seed image on the next call.
- Replace the function block with the one printed by the previous tag (`podman run --rm ghcr.io/<org>/swarmbox:<old> init ...`) and remove the helper folder `host:~/.local/share/swarmbox/host/`; the next call
  extracts the helper of that block's image. This works for any older tag.

The workspace is kept, so projects, logins and tools are intact. Rolling back across the v0.1.0 layout migration is not possible (12.4); between 2.x versions it is, as long as
the older image understands the layout.

**An existing v0.1.0 container named `swarmbox`.** Found by name without the label `swarmbox.managed`. The function does not adopt, start or remove it: it (from `up` and from `reset`, 3.7.2) prints
"A container named 'swarmbox' made by SwarmBox v0.1.0 exists (workspace: <path read from its mounts>). Stop and remove it with `podman rm -f swarmbox`; your files stay
in that folder. Then run `swarmbox config set WORKSPACE <that path>` (or, on a fresh install before any function call, `init --workspace <that path>`) to keep using it." and exits 5. The nested Podman volume `swarmbox-containers` is reused by name.

## 4. The box

### 4.1 Startup: `serve` and its step order `[new]`

`serve` is the container's main process (`CMD ["serve"]` of the entrypoint, 10.2): the box lives as long as it does. Today there is no such process. In v0.1.0 the nested Podman service and the web terminal are started from `container/scripts/init.sh`, which `bashrc` runs in every interactive shell
(`init.sh` lines 89 and 92), and also by `start.sh` after the container starts (`podman exec -d ... swarmbox-podman-service`, `start.sh` line 307) and by `lib/web.sh` (`podman exec -d ... swarmbox-web-terminal`, line 60) `[today]`. Making `serve` the main process works in a prototype `[verified: spike tests/spikes/spike_b3_serve_pid1.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img (node:24-slim, tmux 3.3a, ttyd 1.7.7); reduced: bash stand-in for the entrypoint's serve, the nested Podman service is a sleep, no tmux client]` (B3; the product test in Phase 2 closes it).

Steps, in order, starting with step 0. **F** = failure is fatal (`serve` prints the reason and exits 1; the box stops and `podman logs` shows it). **W** = warn and continue: the failure is
logged in `<workspace>/.local/state/swarmbox/serve.log`, one line is added to `<workspace>/.local/state/swarmbox/health`, and the entry banner shows it.

| # | Step | On failure |
|---|---|---|
| 0 | Delete `box:/tmp/swarmbox/ready` and every `box:/tmp/swarmbox/exit.*` file, before anything else. This is the **second** defense. The first is that `box:/tmp/swarmbox` is a `--tmpfs` mount (3.6), which Podman empties at every start `[verified: spike tests/spikes/spike_b17_tmpfs.py: a file, a folder and exit.1 written, podman stop, podman start, listing empty, while a file outside the tmpfs survived; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` (B17). Without the tmpfs, the container filesystem would survive `podman stop` and `podman start`, and from `podman start` until this step runs the old marker would still exist: `up` could read it and return before `serve` has done anything | not applicable (an absent file is fine) |
| 1 | Check the workspace: `/home/agent` is a directory and the agent user can create a file in it | F |
| 2 | Check `/dev/net/tun` exists | F ("nested Podman needs /dev/net/tun") |
| 3 | Create the XDG folders and `box:/tmp/swarmbox` (from `dirs.sh`) | F (the same cause as 1) |
| 4 | Migrate an old `.swarmbox/` layout (12.4) | W |
| 5 | Ensure the SSH key (`swarmbox-pubkey --ensure`) | W |
| 6 | `swarmbox-tool link --user` (6.2) | W |
| 7 | Generate the MCP configuration (4.4); then run `prepare.sh` (6.3) of every tool that is installed or declared in `WITH`, image or user level. For OpenCode this renders its configuration and mirrors the MCP list (6.6) | W per file or tool (one health line each; the others still run) |
| 8 | Start the nested Podman service | W |
| 9 | Start the tmux server with session `main`, created with **one idle window** (`attach` adds a window and closes the idle one when it is the only other, 3.4) | W |
| 10 | Start and supervise ttyd, when `WEB=1` (5.1) | W |
| 11 | Write the readiness marker (4.2) | W |
| 12 | In the background, install the tools listed in `WITH` (6.7), one after another, output to `serve.log` | W per tool; the next shim call retries |

**`serve` is PID 1** (or the child of the small init that `--init` puts first). It installs handlers for SIGTERM and SIGINT, so `podman stop` ends the box promptly instead of waiting for the kill timeout: on a signal it stops its children
(the ttyd supervisor and ttyd, the nested Podman service), leaves the tmux server to end with the container, and exits. After step 12 it blocks in `wait` on a background `sleep infinity` (so the handler runs at once, which a foreground `sleep` would not allow); with `WEB=0` there is
no ttyd supervisor, and this `sleep` is all it blocks on. Measured with the prototype (B3): the handlers run as PID 1 and as the child of `--init` (Podman's init is `/run/podman-init`; serve was its child), `podman stop -t 10` took 0.14 s for each of `INIT=0`, `--init` and `WEB=0`, with exit status 143 (SIGTERM) and 130 (SIGINT sent by `podman kill --signal INT`, also under `--init`), and ttyd was gone when serve left. Controls: a PID 1 with no handler, and one that waits in a *foreground* `sleep infinity`, both ran into the kill timeout (3.14 s for `-t 3`, exit 137), which is why the handlers and the background `sleep` are required, not optional.

Installing `WITH` tools happens **after** the readiness marker, so a slow download never keeps you waiting at the door; the entry banner says "installing claude...".

### 4.2 Readiness, health warnings and restart `[new]`

- **Readiness marker.** `serve` writes `box:/tmp/swarmbox/ready` at step 11, containing `ok` or `warnings=<n>`. Two programs wait for it, and they do not see the same things:
  - **Host `up`** (3.7.2) polls, for at most 60 s, `podman exec <name> test -f /tmp/swarmbox/ready` **and** the container state (`podman inspect`). If the container has exited (for example `serve` stopped on a
    fatal error, 4.1), it stops waiting at once, prints the last lines of `podman logs --tail <name>` and exits 6, instead of hiding the cause behind the timeout. On timeout it prints
    "swarmbox: the box did not become ready in 60 s; see `podman logs <name>`" and exits 6.
  - **`swarmbox-attach`** runs inside the box and cannot see that the container has exited. It only polls the marker, for 60 s; then it prints "swarmbox: the box is not ready; run `podman logs <name>` on the host" and exits 6.
  
  The marker of a previous run cannot be read: `box:/tmp/swarmbox` is a tmpfs, empty at every start (3.6), and `serve` deletes any marker again as its step 0 (4.1). So `up` and `attach` can only ever see the marker
  written by the current run. The function enters right after `up` returns, so in the normal case `attach` finds the marker at once. (Today `start.sh` polls for the nested Podman socket for 5 s and warns `[today]`.)
- **Startup-health warnings** are exactly these three kinds of line, shown by the banner when a shell opens and by `swarmbox up`: (1) the lines of
  `<workspace>/.local/state/swarmbox/health` that `serve` wrote for failed W steps, cleared at every start; (2) "the nested Podman socket does not answer" (the host
  helper checks it after `up`, as `start.sh` does today `[today]`); (3) the fingerprint and stale-image lines of 3.7.4 and 3.8.
- **ttyd restart policy.** The supervisor restarts ttyd when it exits, after 1, 2, 4, ... up to 30 seconds. After 5 exits within 60 seconds it stops restarting and records a health line
  ("web terminal keeps crashing; see web-terminal.log"), **but the supervisor stays alive, idle**, so that `swarmbox-web restart` (inside the box, which sends it a signal) can still reach it: it restarts ttyd by hand, resets the count and clears the health line. The box does not stop when ttyd does.
  The spike found this: its first prototype let the supervisor exit when it gave up, and then nothing could restart ttyd. Measured (B3): killing ttyd gave a new ttyd within the 1 s backoff and the page answered again; the restart signal gave a new ttyd; after 5 quick kills the supervisor gave up, the box stayed up, and the restart signal started ttyd again `[verified: spike_b3_serve_pid1.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: the backoff was scaled to 0 s for the crash-loop case]`.
- **Container restart policy.** The box is created **without** `--restart`, which is Podman's default (never restart). After a host reboot the box is stopped and its tmux sessions are
  gone (they lived in the container); the next `swarmbox` starts it again from the same container, so nothing in the workspace is lost. Restarting automatically needs a user service
  manager for rootless Podman `[unverified]` (B16) and is not part of 2.0. (The Cloudflare connector is created with `--restart=always` `[today]`, but Podman brings it back after a host reboot only if the user's Podman restart service is enabled (`podman-restart.service`;
  `docs/cloudflare.md` says so today `[today]`); whether that works for rootless Podman is `[unverified]` (B16).)

### 4.3 Layers, fingerprint and layout

1. **Three layers.** *Image*: what is installed. *Creation*: what the box is created with (mounts, ports, hostname, time zone, environment...). *Runtime*: what changes inside without recreating the
   box (tools, in-box config files). A feature lives in exactly one layer; a creation-layer feature changes with `swarmbox reset`, a runtime one does not.
2. **One configuration surface.** The host file `host:~/.config/swarmbox/config` (8). `init` flags only seed keys; `swarmbox config set|get|list` edit them; an environment variable `SWARMBOX_<KEY>` overrides a key.
   No feature has a flag syntax of its own.
3. **One creation fingerprint** (3.7.4).
4. **One layout (XDG), and one question per file: must it survive a reset, and must the host reach it?**
   - Survives, and you edit it: `<workspace>/.config/swarmbox/` (`web-terminal.conf`, user-level tool manifests, user-level MCP entries).
   - Survives, and was installed: `<workspace>/.local/share/swarmbox/` (`tools/`, `shims/`).
   - Survives, or the host must reach it: `<workspace>/.local/state/swarmbox/` (logs, `health`, and `podman.sock`, the one file the host has to reach).
   - Regenerated at every start, so it does not need to survive: `box:/tmp/swarmbox/`, a tmpfs (the assembled web page, the OpenCode config, locks, `ready`).

   There is no `.cache/swarmbox`. The layout replaces `<workspace>/.swarmbox/` (12.4). Every script reads these paths from one file, `container/scripts/dirs.sh`, which honors `XDG_CONFIG_HOME`,
   `XDG_DATA_HOME` and `XDG_STATE_HOME`; tests point those at temporary folders.

### 4.4 MCP servers

An MCP server is a tool that an agent can call (here: a browser controller). 

**Registry `[new]`** (today: `container/mcp/chrome-devtools/config.json` is read by name from `init.sh` `[today]`). One directory per server, `container/mcp/<name>/config.json`:

```json
{
  "command": "chrome-devtools-mcp",
  "args": ["--executablePath=/usr/bin/chromium", "--headless",
           "--chromeArg=--no-sandbox", "--chromeArg=--disable-setuid-sandbox",
           "--chromeArg=--disable-dev-shm-usage", "--chromeArg=--disable-gpu"],
  "env": {},
  "browserUrlArgs": ["--browserUrl=${BROWSER_URL}"]
}
```

- `command`, `args`, `env`: as an MCP client expects (`env` optional). The browser options in `args` are today's file; what changes (D23) is that `npx -y` and `@latest` are gone and `command` is the program installed
  in the image at build (see "Version of the MCP server" below). That the installed package provides a program named `chrome-devtools-mcp` that accepts these same options is `[unverified]` (B24).
- `browserUrlArgs` (optional): when `BROWSER_URL` is non-empty, these `args` replace the server's `args`, with `${BROWSER_URL}` replaced by the value. This is how chrome-devtools
  switches from a local headless Chromium to a remote Chrome: today `build_base_mcp_config` does the same in code, with `args = ["-y","chrome-devtools-mcp@latest","--browserUrl=<url>"]` `[today]`.
- **All entries are enabled by default.** The per-server off switch is a file `<workspace>/.config/swarmbox/mcp/<name>/config.json` containing `{"enabled": false}`; user-level files with the same
  name override the image's fields. It takes effect at the next start of the box.

**Generated files.** `serve` writes `<workspace>/.claude/mcp-servers.json`:

```json
{ "mcpServers": { "chrome-devtools": { "command": "chrome-devtools-mcp", "args": ["--executablePath=/usr/bin/chromium", "..."] } } }
```

(`{"mcpServers": {"<name>": <entry>}}` with `browserUrlArgs` and `enabled` removed. `[today]` for the one server, with `npx` as its command.)

**OpenCode mirror.** An agent whose manifest says `MCP_FORMAT=opencode` gets its own copy. v0.1.0 (`sync_opencode_mcp`) maps each server `s` to
`.mcp[name] = { "type": "local", "command": [s.command] + s.args, "enabled": true }` plus `"environment": s.env` when `env` is present, inside the OpenCode config file; 2.0 keeps this mapping, now in
`container/tools/opencode/prepare.sh` (function `sync_opencode_mcp`), which `serve` runs at step 7 after it has written the MCP file above (4.1, 6.3, 6.6). The file it writes is `box:/tmp/swarmbox/opencode.json`.

**Version of the MCP server (D23).** Today `chrome-devtools-mcp@latest` is fetched by `npx` at run time, unpinned `[today]`, which conflicts with principle 10. In 2.0 the Dockerfile installs a pinned version at build
(`npm install -g chrome-devtools-mcp@<pinned>`, the version an `ARG`, 10.1) and the registry `command` runs the installed program, so nothing is downloaded when the browser MCP starts. There is no exception to principle 10 for it.

## 5. Web terminal and remote access

```
browser ─ https://swarmbox.example.com ─► Cloudflare Access (e-mail code) ─► cloudflared ─► 127.0.0.1:7681 ─► ttyd ─► tmux
                                                                            (HOST)                         (inside the box)
```

### 5.1 Inside the box

- ttyd (pinned and checksummed), tmux (from the distribution) and the clipboard bridge are part of the image (a few MB). `[today]` (the Dockerfile fetches ttyd 1.7.7 with a checksum).
- `serve` runs the web terminal (ttyd running tmux) and supervises it (4.1, 4.2). Today ttyd is started in the background by `init.sh` when the container was created with `SWARMBOX_WEB=1` `[today]`.
- It is on by default and listens only on `127.0.0.1:<WEB_PORT>` of the host (inside the box it is always port 7681). `WEB=0` turns it off. `[today]` for `--web [PORT]`, off by default; `[new]` for on by default.
- `serve` supervises ttyd instead of being it, so restarting the web terminal after editing `web-terminal.conf` is `swarmbox-web restart` inside the box, and does not end the box. Today the documented way is
  `pkill ttyd; swarmbox-web-terminal` `[today]`, which would stop a box whose main process was ttyd. The new command works in the prototype: its stand-in (a USR1 signal to the supervisor) gave a new ttyd that answered over the published `127.0.0.1` port, with the box up and PID 1 unchanged `[verified: spike_b3_serve_pid1.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: not the real swarmbox-web]` (B3).
- **The page is built into the image** (D13). `container/web/build-index.sh`, run at image build, assembles ttyd's own page (`ttyd-stock.html`,
  saved at build), `ttyd-clipboard.js` and `ttyd-style.css` into `box:/usr/local/share/swarmbox/web/index.html`, with placeholders for
  the three user settings: the padding and the two switches `ctrlVPaste` and `ctrlCCopy`. At every start `swarmbox-web` copies it to
  `box:/tmp/swarmbox/index.html` substituting those three values from `web-terminal.conf` (a plain text substitution: no Python at runtime
  and no hash). Today the whole assembly runs at every start (`web-terminal.sh`, with Python) `[today]`. Building it at image build means the
  page, however sophisticated it becomes, is versioned, tested in CI and covered by the image's signature.
- Font, theme and size do not live in the HTML: ttyd passes them to the page through its `-t key=value` options, built from
  `web-terminal.conf` at start.
- `web-terminal.conf` is `<workspace>/.config/swarmbox/web-terminal.conf` (`<workspace>/.swarmbox/web-terminal.conf` today). Logs go to
  `<workspace>/.local/state/swarmbox/`.
- Limit: ttyd serves a **single file** as the page (`--index`), as far as this repository uses it. A page that grows into several files would have
  to be inlined into that one file, or a small server put in front. Not checked against ttyd's documentation `[unverified]` (B4).

### 5.2 Remote access: `swarmbox remote`

- `remote setup` asks for a Cloudflare domain, an e-mail and an API token (hidden input, never stored), then provisions:
  the Access application with the one-time-code login, one tunnel per account, the DNS record, and the connector as a Podman
  container **on the host** (`swarmbox-cloudflared`, restarted automatically). Options: `--session` (login length),
  `--hostname`, `--port`. It is the existing `cloudflare-setup.py` `[today]`, which stays idempotent and dependency-free; `swarmbox remote setup` is the `apply` command.
- `remote status` reports the connector, the hostname, the login check and the session length. `remote off` removes what
  `cloudflare-setup.py remove` removes today (the DNS record, the tunnel route, the Access application and its policy) and also stops
  the connector when no other hostname uses the tunnel. Today `remove` leaves the connector running `[today]`, so this is a change. `swarmbox url` prints the local and the remote URL.
- After setup, every `swarmbox` entry makes sure the connector is up (created, started or recreated with the tunnel token),
  as `start.sh --web` does today `[today]`. **The tunnel token is read on the host only**, never from the box: from the host environment (`SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN`) or, as the key `CLOUDFLARE_TUNNEL_TOKEN`, from the host config,
  which is accepted only with mode 600 (D28; how the helper enforces it: 3.7.3). The environment wins (precedence, 3.7.3). It is the only secret the host config may hold.
- The login length defaults to a conservative value and is changed with `--session` (for example `168h`). Rerunning the
  setup without `--session` must keep the value already configured instead of resetting it to the default. (Today the script
  resets it to 4h `[today]`; this is a change to make.)
- The script's other options stay reachable and are not part of the main flow: `swarmbox remote setup --dry-run`, `--tunnel`,
  `--no-connector`, `--no-verify`, and `swarmbox remote token` (prints the tunnel token for people who run `cloudflared` themselves; today `token` and `--print-token`).
- The connector image is `docker.io/cloudflare/cloudflared:latest` today (`cloudflare-setup.py`, `DEFAULT_CONNECTOR_IMAGE`; `lib/web.sh` honors `SWARMBOX_CLOUDFLARED_IMAGE`). Pinning a version is a change (12.3).

## 6. Tools, agents and shims

Everything in this section is `[new]` unless tagged; today these programs are part of the image (10.1).

### 6.1 Definitions

- A **tool** is a program SwarmBox can install on demand (gcloud, clasp, Go, Poetry...).
- An **agent** is a tool with `KIND=agent`: it also has auto-approve flags and may use the MCP configuration.
- A **shim** is a symbolic link on `PATH`, named after a command a tool provides, that points to **one shared dispatcher**
  (`swarmbox-shim`). It exists from the start; the real program does not. The dispatcher learns which command was called
  from the name it was invoked with (`basename "$0"`), looks it up in an index (`command -> tool`), makes sure the tool is
  installed, then replaces itself (`exec`) with the real program. There is no per-tool shim code: **adding a shim means
  creating a link and one index line**, both generated from the manifests.
- A **manifest level** is where manifests are read from (image and user; section 6.2). The user level wins. There is no project level in 2.0 (D18, 6.10).

### 6.2 Layout

In the repository (versioned; this is where a tool is defined):

```
container/
├── tools/<name>/
│   ├── tool.conf        # manifest (6.3)
│   ├── install.sh       # how to install it (6.4)
│   ├── shell.sh         # optional: aliases/functions sourced by the interactive shell (6.6)
│   ├── prepare.sh       # optional: run by `serve` at every start (step 7 of 4.1) to render files the tool needs in box:/tmp/swarmbox (6.3)
│   └── ...               # optional data files a tool needs, e.g. opencode/local-llm.json (6.6); installed with the image-level manifests
└── scripts/
    ├── swarmbox-tool.sh # list | install | update | use | remove | run | link | validate | doctor | new
    └── swarmbox-shim.sh # the single dispatcher every shim links to
```

Shims and the index are **not** in git: `swarmbox-tool link` generates them.

Manifest levels, from highest precedence to lowest:

| Level | Manifests | Generated shims and index | Who uses it |
|---|---|---|---|
| User | `<workspace>/.config/swarmbox/tools/<name>/` (in the workspace) | `<workspace>/.local/share/swarmbox/shims/`, `.../index` | the user, no rebuild |
| Image | `/usr/local/lib/swarmbox/tools/<name>/` (copied from `container/tools/`, read-only) | `/usr/local/lib/swarmbox/shims/`, `.../index` | everyone |

`swarmbox-tool link --system` runs at image build for the image level; besides the shims and the index it writes `box:/usr/local/share/swarmbox/host/tool-ports` (6.3). `swarmbox-tool link --user` runs at every container
start (step 6 of 4.1) and at every entry (`swarmbox-attach`), is idempotent, and rebuilds the user-level shims from the user-level
manifests. The box's working directory is `/home/agent`; the host's current directory is not carried in, so "the directory `swarmbox` is run from" does not exist in 2.0.

In the image:

```
/usr/local/bin/swarmbox-tool                # the manager
/usr/local/bin/swarmbox-shim                # the dispatcher
/usr/local/lib/swarmbox/tools/<name>/...    # image-level manifests and install scripts, read-only
/usr/local/lib/swarmbox/shims/<command>     # symlink -> /usr/local/bin/swarmbox-shim
/usr/local/lib/swarmbox/index               # "command tool" per line
/usr/local/share/swarmbox/host/tool-ports   # "tool<TAB>port" per line, from the PORTS of image-level manifests; shipped in the helper archive (3.7.1)
```

In the workspace (persistent, mounted as `/home/agent`):

```
<workspace>/.local/share/swarmbox/tools/<name>/<version>/   # the installed program ($TOOL_PREFIX)
<workspace>/.local/share/swarmbox/tools/<name>/current      # symlink to the active version (UPDATE=managed)
<workspace>/.local/share/swarmbox/tools/<name>/self/        # the single install of an UPDATE=self tool, updated by the tool
<workspace>/.local/share/swarmbox/shims/, .../index         # user-level shims
<workspace>/.config/swarmbox/tools/<name>/                  # user-level manifests
```

The install lock is `box:/tmp/swarmbox/tools.lock` (an `flock`, so two shells do not install at once).

`PATH` order: user-level shims, image-level shims, then `<workspace>/.local/share/swarmbox/tools/*/current/bin`. After install the real
binary is found before the shim, so there is no per-call overhead. `[verified: a shell experiment with a symlink named gcloud and one named clasp pointing at one script; each saw its own name in $0 and its own arguments; date, Podman and OS not recorded; no image involved]`.

### 6.3 Manifest: `tool.conf`

A shell-sourceable `KEY=VALUE` file: no parser dependency (the image has no TOML/YAML tool by design).

```sh
# container/tools/claude/tool.conf
SCHEMA=1
NAME=claude
KIND=agent                                   # agent | tool
PROVIDES="claude"                            # commands that get a shim
VERSION=latest                               # agents: latest; every other tool: a pinned version (D21); see 6.7
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
MCP_FORMAT=opencode                          # gets its own copy of the MCP server list; no YOLO_FLAGS until the flag is verified (B2)
```

```sh
# container/tools/clasp/tool.conf
SCHEMA=1
NAME=clasp
KIND=tool
PROVIDES="clasp"
VERSION=<pinned>
PORTS=43323
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
- `NAME`: directory name and install folder. `PROVIDES`: shim names. `KIND`: `agent` tools also get the aliases in 6.6.
- `VERSION`: `latest` resolves at first install and is then recorded; anything else is installed as written. Agents (`KIND=agent`) use `latest`, because they move fast; every other tool
  pins a version (D21). A pinned version changes only with a release of SwarmBox.
- `UPDATE`: `managed` (default, SwarmBox keeps versions side by side) or `self` (the tool updates itself). `UPDATE_CMD`:
  required for `self`; the command that updates it now. See 6.7.
- `SHA256_<arch>`: verified before use when present. Required for tools with a published hash.
- `PORTS`: optional; ports the tool needs published on `127.0.0.1` (clasp's `login` callback uses `43323`; `[today]` as `--clasp`). Creation-time, and read **on the host**, where the manifests are not
  (they are in the image). So the image build writes the file `tool-ports` (one `<tool><TAB><port>` line per `PORTS` entry of every image-level manifest; `swarmbox-tool link --system` generates it) and the helper archive carries it
  (3.7.1). At creation the helper adds, for each tool in `WITH`, its ports from `tool-ports` as `127.0.0.1:<port>:<port>`, skipping a port that `PORTS` already lists as an entry starting with that number
  (today's `--clasp` does the same check, `start.sh` `[today]`). A name in `WITH` that `tool-ports` does not list adds nothing and is not an error. The file itself always exists: the image build writes it even when no manifest declares ports (an empty file), so a missing `tool-ports` is a corrupted helper archive and `create-flags` exits 3 (3.7.1). **User-level manifests do not add ports at creation**: the helper reads nothing
  inside the workspace; to publish a port for such a tool, put it in `PORTS`. The added ports are part of the fingerprint and of the label `swarmbox.ports` (3.7.4). For a tool that was not in `WITH` at creation,
  add it to `WITH` and run `swarmbox reset`.
- `MCP_FORMAT`: agents only; how the MCP server list reaches the agent. `claude` reads the generated `<workspace>/.claude/mcp-servers.json`
  directly; `opencode` gets a mirrored copy in its own format (4.4).
- Conflicts: two manifests that provide the same command are resolved by level (user, then image); two at the
  same level are an error reported by `link` and `validate`.

Optional files next to the manifest (`[new]`):
- `shell.sh`: sourced by every interactive shell, for each installed or declared tool; aliases, functions and exported variables (6.6).
- `prepare.sh`: **run by `serve` at step 7 of every start (4.1)**, for every tool that is installed or listed in `WITH`, at image or user level, in the order of the tool names. It renders files the tool needs under `box:/tmp/swarmbox/`
  (a tool's configuration that depends on environment variables or on the MCP list). It runs as the agent user, sources `container/scripts/dirs.sh` for the paths, may read the MCP file that step 7 has just written
  (`<workspace>/.claude/mcp-servers.json`, 4.4) and the creation settings in its environment, writes only below `box:/tmp/swarmbox/`, must be idempotent, and prints on stderr. A non-zero exit is a **W** failure: one health line
  naming the tool, and the other tools still run. `swarmbox-tool install` also runs it once after a successful install, so a tool installed later is ready without a restart `[new]`. The only `prepare.sh` shipped is OpenCode's (6.6).

### 6.4 Install contract: `install.sh`

Called by `swarmbox-tool install <name>` with:

| Variable | Meaning |
|---|---|
| `TOOL_PREFIX` | Directory to install into (a `bin/` inside it is put on `PATH`). |
| `TOOL_VERSION` | The version to install (already resolved). |
| `TOOL_ARCH` | `amd64` or `arm64`. |

Rules: idempotent; writes only under `$TOOL_PREFIX` (and its own temp dir); prints progress to **stderr** only (stdout
belongs to the tool being run); exits non-zero on any failure and leaves no half-installed `current` link. npm-based tools
use `npm install -g --prefix "$TOOL_PREFIX"` and **clean or redirect the npm cache in the same step**. The image sets `NPM_CONFIG_CACHE=/opt/npm-cache` (v0.1.0's `Dockerfile` line 144 `[today]`), outside the prefix, so an unmodified
install writes its cache there, not under `$TOOL_PREFIX`. The installer therefore either runs `npm cache clean --force` afterwards or passes `--cache` pointing at its own temporary folder; and `/opt/npm-cache` must be owned by `agent` (10.2): v0.1.0's Dockerfile comment
(lines 332 to 334) documents that root-owned cache entries make a later `npm` as `agent` fail with `EACCES` `[today]`.

Hard rules, because a box can be recreated (section 6.11): an installer **never** uses `apt` or `sudo`, never writes outside
`$TOOL_PREFIX` (not in `/usr`, `/etc`, `/opt`, and not in the user's shell startup files such as `<workspace>/.bashrc`), and never needs
a system package that the image does not already have. A tool that needs one belongs in the image, or in the build-time
preinstall (6.8), not in an on-demand install. Anything an installer is allowed to leave behind (a cache, including `/opt/npm-cache`) must be safe to lose; the cache is the one place outside `$TOOL_PREFIX` an installer may touch, and only through npm's own cache setting.

**Where the rule is enforced** `[new]`: statically by `swarmbox-tool validate`, which refuses an `install.sh` that mentions `apt`, `apt-get` or `sudo`, or writes to a path outside
`$TOOL_PREFIX` or its temp directory in the ways it can detect (it is a lint, not a guarantee); and dynamically by the "no side effects" CI test (13). At run time nothing enforces it: the agent has `sudo` (11).

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
and checks that `opencode --version` still runs. That saves about 720 MB per workspace
`[verified: measured on the v0.1.0 image's global npm install; command, date and Podman version not recorded]`; the same layout is
expected under `--prefix` but has not been measured there `[unverified]` (B10).

`container/tools/gcloud/install.sh` would download Google's tarball for `$TOOL_ARCH`, verify the manifest's `SHA256_<arch>`,
extract it into `$TOOL_PREFIX` and link the binaries into `$TOOL_PREFIX/bin`. The checksums are recorded in the manifest at release time (D29): a maintainer script, run when the
pinned version is bumped, downloads the archive for each architecture and writes `SHA256_amd64` and `SHA256_arm64` into `tool.conf` (the script is not written yet). The exact download URL, and whether Google
publishes a checksum to compare the script's result with, are `[unverified]` (B11).

### 6.5 Lifecycle of a shim call

1. The shim (a link to `swarmbox-shim`) finds its tool in the index and runs `swarmbox-tool run <name> <command> -- "$@"`.
2. If the tool is installed (a `current` link, or the `self` directory), `exec` the real command. Done.
3. Otherwise take the lock, print `Installing <name> (first use)...` to stderr, run `install.sh`, move `current`.
4. `exec` the real command. If the install fails, print the reason, exit non-zero, and the next call retries.

Failure modes: offline (clear message, nothing installed), checksum mismatch (install aborted, files removed),
concurrent shells (second waits on the lock, then finds it installed), and an installed tool whose recorded environment no
longer matches the image (section 6.11).

### 6.6 Agents: aliases and `yolo`

For every installed or declared agent, the shell gets an alias built from the manifest, e.g.
`alias claude='claude --dangerously-skip-permissions --mcp-config ...'`, so `claude` is auto-approve by default inside the
sandbox (today this alias is written by hand in the image's `bashrc`, `[today]`). The flags live only in the manifest: when a release changes one, there is one place to fix. The file named by
`MCP_FLAGS` is generated by `serve` from the MCP registry (4.4), not written by hand.

- `yolo` runs the **default agent** in auto-approve mode. The default is `SWARMBOX_AGENT`, else the first agent in
  `SWARMBOX_WITH`.
- `command claude` bypasses the alias (normal prompts). `SWARMBOX_YOLO=0` disables all the aliases.
- An agent without a verified auto-approve flag gets no alias. OpenCode's flag is `[unverified]` (B2); confirm in its documentation first.
- OpenCode is a shim like Claude Code (D4): an on-demand agent with its own manifest. Its local-LLM support moves from `init.sh` into its tool directory, split between two optional files
  (6.3). **`container/tools/opencode/prepare.sh` is the one owner of the rendering**: `serve` runs it at step 7 of every start (4.1), and it holds `build_opencode_config`, which renders
  the config from `LOCAL_LLM_*` (off unless set) using the template `container/tools/opencode/local-llm.json` into `box:/tmp/swarmbox/opencode.json`, and `sync_opencode_mcp`, which
  mirrors the MCP list (`MCP_FORMAT=opencode`, 4.4) into the same file. **`shell.sh` renders nothing**: it only exports `OPENCODE_CONFIG=/tmp/swarmbox/opencode.json` for the interactive shell,
  instead of the `ENV` in today's Dockerfile `[today]`. The `LOCAL_LLM_*` variables are ordinary
  `ENV_KEYS` entries (7, 8.2): the opencode tool documents that it wants them, and nothing forwards them specially. Today they are forwarded automatically when set on the host, and have defaults (a model
  name and `host.containers.internal:8000`) `[today]`; both go away (12.2). **The template.** v0.1.0 keeps it at `container/opencode/local-llm.json` and the image copies it to
  `/etc/swarmbox/opencode/local-llm.json`, where `build_opencode_config` reads it `[today]`. In 2.0 it moves to `container/tools/opencode/local-llm.json` and is installed with the image-level manifests
  (`/usr/local/lib/swarmbox/tools/opencode/local-llm.json`, 6.2); `prepare.sh` reads it from there. The old `container/opencode/` folder is removed.

`shell.sh` is the optional place for what a tool needs in the interactive shell (files to render at start belong in `prepare.sh`). It is sourced from the shell
configuration for every installed or declared tool. Today's example is the `clasp` function that adds
`--redirect-port 43323` to `clasp login` `[today]`: it moves from the image's `bashrc` into `container/tools/clasp/shell.sh`, next to the
tool that needs it. The generated aliases from the manifest are produced before `shell.sh` runs, so `shell.sh` can extend or
override them.

### 6.7 Pinning and updating

Each tool says how it is updated, with `UPDATE` in its manifest.

**`UPDATE=managed` (the default): SwarmBox owns the versions.**
- Manifests pin a version, except agents, which say `latest` (D21); `SWARMBOX_WITH` and `tool install` honor them.
- `swarmbox-tool update <name>` re-resolves the version, installs it side by side, then moves `current`. Old versions stay
  until `swarmbox-tool remove <name> --old`.
- `swarmbox-tool use <name> <version>` moves `current` to an installed version. Rolling back is one instant command, because
  `current` is only a link.
- On entry, at most once a day and only when online, a one-line notice if a newer version exists ("gcloud 4xx installed, 4yy
  available: swarmbox-tool update gcloud"). `SWARMBOX_UPDATE_CHECK=0` turns it off.
- If a manifest pins a version different from the installed one (typically after an image update), the entry says so:
  "manifest wants X, installed Y".
- Running processes keep the version they started with; the next launch uses the new one.

**`UPDATE=self`: the tool updates itself. Claude Code is the first (D3).**
- SwarmBox installs it once, into `tools/<name>/self/`, and then leaves it alone: no side-by-side versions, no `current` link,
  no pin, no outdated notice (the tool has its own). `VERSION` must be `latest`; `validate` rejects anything else.
- The tool's auto-update stays **on**: `DISABLE_AUTOUPDATER` is not set. This changes v0.1.0, which disabled it because
  rebuilding the image was the update path `[today]`.
- `swarmbox-tool update <name>` runs the manifest's `UPDATE_CMD` (`claude update`), for anyone who does not want to wait for
  the background update.
- There is no `use`: to go back, reinstall the version wanted (`swarmbox-tool install <name> --version X`), knowing the tool
  will update itself again unless its updater is turned off by hand.
- The cost is reproducibility. Two workspaces can run different Claude Code versions, and a new vendor release runs inside the
  box with no SwarmBox pin or checksum (section 11).
- **Not verified:** that Claude Code's updater works for the install method `install.sh` uses `[unverified]` (B1). It decides
  between an npm install under `--prefix` and the vendor's native installer into the home; test it before writing the script.

Updating *tools* never needs a new image or a new box. Updating the *image* (`swarmbox update`, 3.8) does, and recreating the box
ends the running tmux sessions; `update` therefore only pulls and tells you to run `reset` (D27).

### 6.8 Build-time preinstall

The same manifests drive an optional build argument, for people who bake tools into their own image. `WITH_TOOLS` is a **build-time** argument; it is not the same thing as the creation-time setting `WITH` (8.2):

```bash
podman build --build-arg WITH_TOOLS=claude,gcloud .
```

The Dockerfile runs `swarmbox-tool install` for each name into `/opt/swarmbox/tools` instead of the workspace. One installer,
two triggers.

### 6.9 Adding a tool, and keeping the model extensible

To add a tool to the repository:

1. Create `container/tools/<name>/` with `tool.conf` and `install.sh` (and `shell.sh` if it needs shell setup, `prepare.sh` if it needs a file rendered at start). Or run
   `swarmbox-tool new <name>` to create the skeleton.
2. Run `swarmbox-tool validate` (CI runs it): required fields, a known `KIND`, unique command names across levels, an
   executable `install.sh`, a checksum for every architecture when one is declared, and for `UPDATE=self` a `VERSION=latest`
   and an `UPDATE_CMD`.
3. Rebuild. **No file of the core changes**: the Dockerfile copies the whole directory and `link --system` generates the shims.

Without a rebuild, put the same directory under `<workspace>/.config/swarmbox/tools/<name>/` (user level); the next entry links it.

Rules that keep this extensible: manifests are data (`SCHEMA` versioned, unknown keys ignored); the core never names a
specific tool; shims are links to one dispatcher; every manifest is covered by `validate` and by installer tests that use a
fake installer (the same approach the existing tests take for Podman and Cloudflare).

CI also runs, for every tool in `container/tools/` (these use the real installer and the network, so they run on a schedule or
before a release, not on every push; section 13):
- **No side effects:** install in a clean container and check that nothing changed outside `$TOOL_PREFIX` except an allowed
  cache directory. This enforces the hard rules of 6.4.
- **Survives a reset:** install, recreate the box on the same workspace, and run the tool.

### 6.10 Not in 2.0: project-level tools

Tools exist at the image and user levels only (D18). A `.swarmbox/tools/` folder that arrives with a cloned repository is not read: the box's working directory is `/home/agent` and holds many projects, so "the
project" is undefined, and an `install.sh` from a clone would run with network access and any keys that were passed in. A tool a project needs is added at the user level (6.9).

### 6.11 Surviving a reset and an image update

What lives where decides what a `reset` (or `swarmbox update`) can break.

| Lives in | Survives `reset` | Survives an image update | Examples |
|---|---|---|---|
| Workspace (`/home/agent`) | yes | yes | projects, login, SSH key, `<workspace>/.claude`, installed tools, user manifests |
| The container's own filesystem | **no** | no | anything installed with `apt`, files in `/usr`, `/etc`, `/opt`, caches outside the home, running processes, tmux sessions |
| The image | recreated | replaced | system packages, Node, shims and index of the image level, image manifests |

For Claude Code installed with `npm install -g --prefix <dir in the home>`: the install wrote the prefix (325 MB, all in the home) and the npm cache (157 MB). The cache did **not** go into the prefix: the image sets
`NPM_CONFIG_CACHE=/opt/npm-cache` (v0.1.0's `Dockerfile` line 144 `[today]`), so it was written to `box:/opt/npm-cache`, in the container's own filesystem. Nothing was written in `/usr` or `/etc`. A reset therefore keeps the tool, and loses only that
cache, which is safe to lose; the installer rule (clean or redirect the cache; `/opt/npm-cache` owned by `agent`) is in 6.4 and 10.2.
`[verified: throwaway container, file listing before and after; date not recorded; Podman version and OS not recorded; image: v0.1.0]` for the sizes; the earlier reading "nothing in `/opt`" was wrong for the cache and is re-recorded by B12. The vendor's native installer was not tested `[unverified]` (B1).

What can still break a tool after a reset or an image update, and what the design does about it:

1. **The installer wrote outside the prefix.** Forbidden by the hard rules in 6.4 and caught by the "no side effects" CI test.
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

### 6.12 Tools shipped in `container/tools/`

All seven directories are `[new]`; the programs themselves are image content today (last column).

| Tool | Install method | PROVIDES | UPDATE | Environment set by `shell.sh` | Auto-approve flag | Status |
|---|---|---|---|---|---|---|
| `claude` | npm under `$TOOL_PREFIX` or the vendor's native installer (B1) | `claude` | `self` | none | `--dangerously-skip-permissions`, in v0.1.0's alias `[today]` | image content today |
| `gemini` | `npm install -g --prefix` of `@google/gemini-cli` | `gemini` | `managed`, `latest` | none | `--yolo`, in v0.1.0's alias `[today]` | image content today (npm global) |
| `opencode` | npm under `$TOOL_PREFIX`, then prune the other platform builds (6.4) | `opencode` | `managed`, `latest` | `OPENCODE_CONFIG` (the config itself is rendered by `prepare.sh` from `LOCAL_LLM_*`) | `[unverified]` (B2): no alias | image content today |
| `gcloud` | Google's tarball for `$TOOL_ARCH`, checksum recorded in the manifest at release time (D29, B11) | `gcloud gsutil bq` | `managed`, pinned | none | not an agent | image content today (apt package, `/usr`) |
| `clasp` | `npm install -g --prefix` of `@google/clasp` | `clasp` | `managed`, pinned | the `clasp` function adding `--redirect-port 43323` to `login`; `PORTS=43323` | not an agent | image content today (npm global) |
| `go` | official tarball from go.dev extracted under `$TOOL_PREFIX` (checksum source `[unverified]`, B25) | `go gofmt` | `managed`, pinned | `GOPATH=$HOME/go`, `GOCACHE=$HOME/.cache/go-build` (Go's defaults, now under the home), `$GOPATH/bin` on `PATH` | not an agent | image content today (`/usr/local/go`, `GOPATH=/opt/go`) |
| `poetry` | the official installer with its home set to `$TOOL_PREFIX`, version pinned | `poetry` | `managed`, pinned | none | not an agent | image content today (`/opt/poetry`) |

Go and Poetry install under `$TOOL_PREFIX`; today's `/opt/go`, `/opt/go-cache`, `/opt/poetry` and `/usr/local/go` locations disappear with the image content. The old reason to keep `GOPATH` and `GOCACHE`
out of the home (nothing installed into `/home/agent`) no longer applies: the home is the workspace and is meant to hold them.

## 7. Environment variables and keys

Same behavior as `start.sh --env-keys` today, with changes listed in 7.2 and 12.3. Pointer: what the box does and does not protect here is in section 11.

Keys and settings the box needs (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, a model name...) are passed **when the box is created**,
and only then (D12). The first `swarmbox`, the one that creates the box, takes the values from its own environment at that moment;
a box that already exists keeps what it was created with, and other terminals that enter it pass nothing. To pick up a change,
recreate it: `swarmbox reset`.

### 7.1 How it works

- The **names** are stored on the host, in `host:~/.config/swarmbox/config` (`ENV_KEYS=ANTHROPIC_API_KEY,GEMINI_API_KEY`), not typed
  on every command. At creation the helper turns each name into `-e NAME` without a value, so Podman reads it from the
  environment of the terminal that runs `swarmbox`. Today `start.sh` puts `-e NAME=value` on the command line `[today]` (the value shows
  in `ps`, and a value with spaces breaks the unquoted expansion); `-e NAME` keeps the value off the command line. This file
  holds no values.
- `swarmbox env add NAME`, `env rm NAME` and `env list` edit and show the list. `list` prints each name and whether it is
  `set` or `not set` in the current terminal; never the value.
- **Names listed but not set:** if a listed name is not set in the terminal that creates the box, the helper warns before
  creating it ("ANTHROPIC_API_KEY is listed but not set in this terminal; the box will start without it"). Today `start.sh` warns "Environment variable 'X' not found, skipping" `[today]`;
  `-e NAME` alone would pass nothing and say nothing.
- On creation the helper stores a hash of the passed values as the label `swarmbox.env-hash` (one part of the fingerprint, 3.7.4): `NAME=value` for each set name, `NAME` for each unset one, sorted, hashed with SHA-256. On every
  entry it recomputes the hash from the host and, if it differs, prints one line: "the variables changed on the host; run
  `swarmbox reset` to apply them". The values themselves are never stored for this; only the hash is.

### 7.2 Which names are accepted

A name must look like an environment variable. Names that belong to the host side are refused: anything starting with
`SWARMBOX_CLOUDFLARE_` (the tunnel token must never enter the box; today `start.sh` refuses only the exact name
`SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` `[today]`, so this is stricter).

**LOCAL_LLM_\* and BROWSER_URL.** The five `LOCAL_LLM_*` variables (`LOCAL_LLM_URL`, `_MODEL`, `_KEY`, `_CONTEXT`, `_OUTPUT`) are ordinary `ENV_KEYS` entries with no special forwarding; the `opencode` tool documents that it wants them.
v0.1.0 forwarded them automatically when they were set on the host `[today]`, so **a user who relies on them must run `swarmbox env add LOCAL_LLM_URL` (and the others) after upgrading**. `BROWSER_URL` is not a secret: it is a creation key (8.2) that the
helper passes as a plain `-e SWARMBOX_BROWSER_URL=<value>`, normalized as today: a bare number `N` becomes `http://host.containers.internal:N`, `host:port` gets `http://` `[today]`.

### 7.3 Where the values come from, and the gap

- The source is the host environment, so it is up to the user to keep the variables exported (a shell startup file,
  a password manager, a tool such as direnv). SwarmBox stores nothing.
- The gap: `swarmbox reset` re-reads the host environment. If a variable is no longer exported in that terminal, the new box starts
  without it. Claude Code's own login is not affected: it lives in `<workspace>/.claude` in the workspace and survives a reset.
- **No fallback file in 2.0 (D28).** SwarmBox has no `swarmbox env set` and no host file that stores values (a `secrets/env` file is not in 2.0). The source of every value is the host environment, and keeping it
  there is the user's own business: their shell, a password manager, or a tool such as direnv. SwarmBox never writes a variable's value to disk. The one secret the host config may hold is the Cloudflare tunnel token,
  with mode 600 (3.7.3); it is not a variable of the box and never enters it (5.2).

What stays as it is today, stated so nobody assumes more:
- The values live in the container's configuration (`podman inspect` shows them) and in the environment of every process in
  the box. The agent can read them. Scoped, minimal tokens are the user's protection, not the sandbox.
- A tool does not get its own subset: every process sees every listed name.
- The browser terminal and the host tabs should see the same values: all windows are created by the tmux server that started
  inside the box with the environment it was created with. Measured: a tmux server started with `X=1` gave `X=1` to a window requested by a client with `X=2`, whether that client was attached (grouped session, as 3.4), unattached, or the server's own `run-shell`; the global environment held `X=1` `[verified: spike tests/spikes/spike_b9_tmux_env.py, tmux 3.3a; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img]` (B9). The guarantee depends on one tmux setting: `update-environment` must not list the user's variables. Its default list is only `DISPLAY`, `SSH_*`-type and similar names, and with `update-environment X` an *attached* client's value did travel (`X=3` seen), while an unattached client's did not; `container/config/tmux.conf` does not set it today, and must not.

Alternatives considered, and why they are not the default:
- *Pass the host value on every entry* (`podman exec -e NAME`): works for host tabs `[verified: one entry run with a changed host value, then podman inspect; date, Podman and OS not recorded; image not recorded]` (the value follows a change on
  the host, and does not appear in `podman inspect`), but browser windows and remote access come from the tmux server, not from
  the entering command, so they would not follow it. How tmux inherits the environment for new windows is measured in B9 (above): from the server, not from the client.
- *A secrets file mounted into the box* and *Podman secrets*: keep values out of `podman inspect`, but add machinery for
  a property the model above already gives up on purpose (the agent reads the keys either way).
- *A credential proxy on the host* that adds authentication to requests so the box never holds the key: the only option that
  protects the key from the agent; it is a larger piece of work and is listed in the roadmap as optional.

## 8. Configuration reference

### 8.1 Rules

- Every setting has **one name**: the key (`WITH`), the host-config name is the key, and the environment override is `SWARMBOX_<KEY>` (`SWARMBOX_WITH`). `WITH_TOOLS` is a different thing: a **build-time**
  argument of the Dockerfile (6.8).
- Precedence, highest first: environment variable, `host:~/.config/swarmbox/config`, built-in default. File grammar: 3.7.3.
- Side *host*: read by the function and helper only and never passed into the box. Side *box*: read inside the box.
- Layer *creation*: fixed when the box is created (`reset` to change); *runtime*: read while the box runs.
- **How settings reach the box:** every non-secret creation key the box itself needs is passed at creation as `-e SWARMBOX_<KEY>=value` (the keys marked "passed" in the table). Keys that only shape Podman's flags (workspace, ports,
  hostname, time zone) are consumed on the host.
- A *secret* is never passed on a command line, and never written in the config file, with one exception: the Cloudflare tunnel token, stored only with mode 600 (3.7.3, D28). Values of `ENV_KEYS` are never stored.

### 8.2 The table

| Key | Host-config name | Environment override | Side | Layer | Default | Secret | Notes |
|---|---|---|---|---|---|---|---|
| `NAME` | none (not a key of the file) | `SWARMBOX_NAME` | host | creation | `swarmbox` | no | Container name; also names the volume `<name>-containers` and selects the config folder (D31), so it cannot live inside the file it selects (`--name` today). |
| `WORKSPACE` | `WORKSPACE` | `SWARMBOX_WORKSPACE` | host | creation | `host:~/swarmbox` | no | Set by `init --workspace DIR`; `.work/` of the current directory today. |
| `HOSTNAME` | `HOSTNAME` | `SWARMBOX_HOSTNAME` | host | creation | `swarmbox` | no | `--hostname` today. |
| `TZ` | `TZ` | `SWARMBOX_TZ` | host | creation | `local` (or `off`, or `Area/City`) | no | `--tz` flag; `SWARMBOX_TZ` today. |
| `INIT` | `INIT` | `SWARMBOX_INIT` | host | creation | `auto` (or `0`, `1`) | no | `--init`, which reaps zombies; `SWARMBOX_INIT` today. `up` resolves `auto` to 0 or 1 (it tests `--init` support) and hands `create-flags` the resolved value (3.7.2). |
| `PORTS` | `PORTS` | `SWARMBOX_PORTS` | host | creation | empty | no | Bound to `127.0.0.1` unless an address is given; a warning for `0.0.0.0`; the image-level manifests of the tools in `WITH` add theirs, from `tool-ports` (6.3). `--ports` today. |
| `HOST_ACCESS` | `HOST_ACCESS` | `SWARMBOX_HOST_ACCESS` | host | creation | `0` | no | Adds `host.containers.internal:host-gateway`. `--iports` today (the port numbers it takes are ignored). |
| `BROWSER_URL` | `BROWSER_URL` | `SWARMBOX_BROWSER_URL` | box (passed) | creation | empty | no | Remote Chrome for chrome-devtools (4.4); bare number or `HOST:PORT` accepted. `--remote-browser` today. |
| `WEB` | `WEB` | `SWARMBOX_WEB` | box (passed) | creation | `1` | no | `0` turns the web terminal off. |
| `WEB_PORT` | `WEB_PORT` | `SWARMBOX_WEB_PORT` | host | creation | `7681` | no | Host port on `127.0.0.1`; inside the box it is always 7681. |
| `WITH` | `WITH` | `SWARMBOX_WITH` | box (passed) | creation | empty | no | Tools to install at start (comma list). In the host config: `WITH=a,b`. |
| `AGENT` | `AGENT` | `SWARMBOX_AGENT` | box (passed) | creation | first agent in `WITH` | no | The agent `yolo` starts. |
| `YOLO` | `YOLO` | `SWARMBOX_YOLO` | box (passed) | creation | `1` | no | `0` disables the auto-approve aliases. |
| `ENV_KEYS` | `ENV_KEYS` | `SWARMBOX_ENV_KEYS` | host | creation | empty | no (names only) | Names of host variables passed at creation (7). `LOCAL_LLM_URL`, `_MODEL`, `_KEY`, `_CONTEXT`, `_OUTPUT` are ordinary entries of this list. |
| `IMAGE` | `IMAGE` | `SWARMBOX_IMAGE` | host | creation | `ghcr.io/<org>/swarmbox:<function version>` | no | Also `init --image`, and written by `swarmbox update` (D17, 3.8). The helper's `up` reads it; the function block only seeds the first extraction. A missing image is pulled, never built (3.8). `--image` today. |
| `LOCAL_LLM_*` | none | the variable itself, through `ENV_KEYS` | box | creation | unset | the key `LOCAL_LLM_KEY` is | Read by the `opencode` tool's `prepare.sh` (6.6). |
| `CLOUDFLARE_TUNNEL_TOKEN` | `CLOUDFLARE_TUNNEL_TOKEN` (optional, mode 600) | `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` | host | runtime | unset | **yes** | Never passed into the box. May also be stored in the host config as `CLOUDFLARE_TUNNEL_TOKEN`, only with mode 600 (3.7.3, D28); the environment wins. |
| `WEB_DOMAIN`, `WEB_HOSTNAME` | read from `cloudflare.json` | `SWARMBOX_WEB_DOMAIN`, `SWARMBOX_WEB_HOSTNAME` | host | runtime | from `cloudflare.json` | no | Used to print the public URL. |
| `CLOUDFLARED_IMAGE` | none | `SWARMBOX_CLOUDFLARED_IMAGE` | host | runtime | pinned in the helper (12.3) | no | `docker.io/cloudflare/cloudflared:latest` today. |
| `STARSHIP` | none | `SWARMBOX_STARSHIP` | box | runtime | `1` | no | `0` gives a plain prompt. Set it in the box's shell. |
| `UPDATE_CHECK` | none | `SWARMBOX_UPDATE_CHECK` | box | runtime | `1` | no | `0` turns off the daily "newer version" notice (6.7). |
| `TOOLS_DIR` | none | `SWARMBOX_TOOLS_DIR` | box | runtime | `<workspace>/.local/share/swarmbox/tools` | no | Where tools install. |
| `ENV_KEYS` values | none | the named variables | host | creation | n/a | **yes** (values) | Read from the terminal that creates the box (7). |

Defaults must be neutral: no personal hosts or model names (OpenCode's local-LLM defaults and `ANTHROPIC_MODEL=sonnet` are removed, 12.2).

### 8.3 Always applied, not configurable

The user namespace (`keep-id`), `--pids-limit=16384`, `--tmpfs /tmp/swarmbox` (the regenerated files and the readiness marker, empty at every start: 4.1 step 0), `-e TERM -e COLORTERM` on every entry, and nested Podman: `--device /dev/net/tun`,
`--security-opt unmask=/proc/*`, the volume `<name>-containers` for its storage, and the host connection `podman -c <name>` that the helper registers
(Linux and WSL only; unix sockets do not cross the macOS VM). These match what `start.sh` does today for the Podman options and connection `[today]`.
If the host has no `/dev/net/tun`, creation stops with a clear message (3.8); `start.sh` does not check this `[today]`.

Runtime: `SWARMBOX_STARSHIP=0` (plain prompt) and `swarmbox --plain` (plain bash instead of tmux).

### 8.4 Feature catalog

What each capability is, and where it lives. This is the proposed model only; section 12.3 maps each row to v0.1.0. Parity (D8) means every row has a passing test against the function (13).

| Area | Feature | Class | Layer | Status |
|---|---|---|---|---|
| Box | Persistent container, enter-or-create, stop, reset, update, up | core | creation | `[today]` as `start.sh`; commands `[new]` |
| Box | Shared tmux session for host tabs and browser; no status bar on host tabs | core | runtime | `[today]` |
| Box | Workspace mount, fixed user with `sudo`, `--init`, pids limit, hostname, time zone, UTF-8 locale | core | creation | `[today]` except the fixed UID `[new]` |
| Box | Creation fingerprint, stale-image and startup-health warnings | core | creation | stale image `[today]`; the rest `[new]` |
| Box | Environment variables and keys (7) | core | creation | `[today]` as `--env-keys`; config-file names `[new]` |
| Shell | Starship, banner, aliases (`ls`, `ll`, `la`, `l`, `grep`), `<workspace>/.local/bin` on `PATH`, `/opt/flow` venv with the `(swarmbox)` prompt, `uv` | core | image | `[today]` |
| Shell | tmux configuration and the Alt shortcuts, clipboard bridge | core | image | `[today]` |
| Git | SSH key, `swarmbox pubkey`, trust on first use for GitHub, GitLab, Bitbucket | core | runtime | key and `swarmbox-pubkey` `[today]`; the forwarded word `[new]` |
| Web | Web terminal (ttyd), on by default on `127.0.0.1` | module | creation | `[today]` off by default; on by default `[new]` |
| Web | Remote access through Cloudflare (`swarmbox remote ...`), host side | module | host | `[today]` as `cloudflare-setup.py`; front end `[new]` |
| Containers | Nested Podman (always on), with the host connection | core | creation | `[today]` |
| Browser | chrome-devtools MCP: local headless Chromium, or a remote Chrome (`BROWSER_URL`) | module | creation | `[today]`; registry `[new]` |
| Network | Published ports, host access | module | creation | `[today]` |
| Tools | claude (self-updating), gemini, opencode (with its local-LLM hook), gcloud, clasp, Go, Poetry (6.12) | tool | runtime | image content `[today]`; on demand `[new]` |

## 9. Repository layout

### 9.1 The tree

Existing paths are kept where they work. **New** marks proposed additions.

```
.
├── Dockerfile                       # the image (section 10)
├── README.md                        # 15-second pitch, install, first use
├── LICENSE                          # new: Apache-2.0 (D25)
├── SECURITY.md                      # new: threat model, how to report
├── CONTRIBUTING.md  CODE_OF_CONDUCT.md  CHANGELOG.md        # new
├── THIRD_PARTY_NOTICES.md           # new: ttyd, starship, tmux, ...
│                                    # (build.sh, start.sh and lib/ exist today and are retired once the function reaches parity: 12.2)
├── cloudflare-setup.py              # host side: remote access; also shipped inside the image, from which the host helper is extracted
├── container/                       # everything copied into the image
│   ├── entrypoint.sh                # new: installed as swarmbox-entrypoint; subcommands serve | attach | init | host-helper | pubkey | tool | <any command>
│   ├── scripts/                     # banner.sh, messages.sh, podman-service.sh, ssh-key.sh (swarmbox-pubkey),
│   │                                #   dirs.sh (new: every path, XDG-aware; sourced by the others),
│   │                                #   swarmbox-init.sh (new: prints the shell function),
│   │                                #   swarmbox-web.sh (new: starts and restarts the web terminal; replaces web-terminal.sh),
│   │                                #   swarmbox-attach.sh (new: joins the tmux session; today lib/attach-session.sh),
│   │                                #   swarmbox-tool.sh and swarmbox-shim.sh (new: manager and dispatcher, section 6)
│   ├── host/                        # new: the host helper (swarmbox-host) and the function templates for bash, zsh, fish; with cloudflare-setup.py and the generated tool-ports it forms the helper archive (3.7.1, 9.3)
│   ├── config/                      # static configuration files: tmux, starship, ssh_config.d, bashrc fragment
│   ├── web/                         # web terminal: ttyd-clipboard.js, ttyd-style.css, build-index.sh (new, runs at image build)
│   ├── mcp/<name>/config.json       # MCP servers wired into agents (chrome-devtools today; registry format in 4.4)
│   └── tools/<name>/                # new: tool.conf + install.sh + optional shell.sh, prepare.sh and tool data files, e.g. tools/opencode/local-llm.json (section 6)
├── docs/                            # design.md (this file), web-terminal.md, cloudflare.md, nested-podman.md
├── tests/                           # helpers.py + one test file per behavior; fakes for podman, Cloudflare, installers (section 13)
└── .github/workflows/               # new: ci.yml (tests), release.yml (build, scan, sign, publish)
```

### 9.2 File types

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
| Tool start-up rendering | `container/tools/<name>/prepare.sh` | `serve` (step 7 of 4.1), and `swarmbox-tool install` | container start |
| Generated shims and index | image `/usr/local/lib/swarmbox/{shims,index}`; workspace `<workspace>/.local/share/swarmbox/{shims,index}` | the dispatcher | every command call (not in git) |
| Host helper | `container/host/swarmbox-host` in the repository; `host:~/.local/share/swarmbox/host/swarmbox-host` once extracted | the function | every `swarmbox` call |
| Helper archive | built in the image at `box:/usr/local/share/swarmbox/host/` (`swarmbox-host`, `cloudflare-setup.py`, `templates/`, `tool-ports`); written on stdout by `host-helper` | the function, at bootstrap and `update` | first call, version change, `swarmbox update` |
| Host script | `cloudflare-setup.py` (and, until retired, `start.sh`, `build.sh`, `lib/`) | the helper; the user's shell | on the host |
| Generated host function | the user's shell startup file, e.g. `host:~/.bashrc` (between markers) | the user's shell | every terminal |
| Host config | `host:~/.config/swarmbox/config` (a second box: `host:~/.config/swarmbox/<name>/config`), `host:~/.config/swarmbox/cloudflare.json`; the config holds the tunnel token only with mode 600 (3.7.3) | the host function and helper | every entry, `remote` |
| Tests | `tests/` | CI and contributors | every change |
| Docs | `README.md`, `docs/` | people | always |

Rules: no file outside `container/` is copied into the image, except `cloudflare-setup.py`, which the image ships for the host
helper; nothing from Cloudflare (credentials, tunnel token) is ever copied into or passed to the box; every download has a
pinned version (exceptions: principle 10).

### 9.3 Commands and where they are installed

All `[new]` except `swarmbox-pubkey`, which is today's `ssh-key.sh` installed under that name `[today]`. File names keep the `.sh` suffix in the repository; the installed command has none.

| Command | Source file | Installed path | Called by |
|---|---|---|---|
| `swarmbox-entrypoint` | `container/entrypoint.sh` | `box:/usr/local/bin/swarmbox-entrypoint` | the container runtime (`serve`); the host function through `podman exec` (`attach`, `pubkey`, `tool`); `podman run --rm <image> host-helper` and `init` (as the image's entry point) |
| `swarmbox-init` | `container/scripts/swarmbox-init.sh` | `box:/usr/local/bin/swarmbox-init` | the entrypoint's `init` subcommand (printed by `podman run --rm <image> init`) |
| `swarmbox-attach` | `container/scripts/swarmbox-attach.sh` | `box:/usr/local/bin/swarmbox-attach` | the entrypoint's `attach` subcommand |
| `swarmbox-web` | `container/scripts/swarmbox-web.sh` | `box:/usr/local/bin/swarmbox-web` | `serve`; the user inside the box (`swarmbox-web restart`) |
| `swarmbox-tool` | `container/scripts/swarmbox-tool.sh` | `box:/usr/local/bin/swarmbox-tool` | the entrypoint's `tool` subcommand; every shim; the user |
| `swarmbox-shim` | `container/scripts/swarmbox-shim.sh` | `box:/usr/local/bin/swarmbox-shim`; shims are links to it | every shim |
| `swarmbox-pubkey` | `container/scripts/ssh-key.sh` | `box:/usr/local/bin/swarmbox-pubkey` | `serve` (`--ensure`); the entrypoint's `pubkey` subcommand; the user |
| `swarmbox-host` | `container/host/swarmbox-host` | `box:/usr/local/share/swarmbox/host/swarmbox-host` (image); `host:~/.local/share/swarmbox/host/swarmbox-host` (after extraction) | the host function |
| `swarmbox` (function) | printed by `swarmbox-init` from `container/host/` templates | the user's shell startup file | the user |

**The helper archive.** The entrypoint's `host-helper` subcommand writes, as a tar archive on stdout, the contents of `box:/usr/local/share/swarmbox/host/`: `swarmbox-host`, `cloudflare-setup.py`, `templates/` (bash, zsh, fish) and `tool-ports`
(generated at image build, 6.3). The function unpacks it into a temporary folder and checks that `swarmbox-host` is executable before renaming the folder into place (3.7.1).

## 10. Dockerfile and image

### 10.1 What the image contains `[new]` (target)

- Base `node:24-slim` (Node is needed by agent installers; the base is still Debian 12). Node version is an `ARG`. `[today]` for the base.
- System packages: git, openssh-client, python3 + venv, build tools, curl, jq, tmux, vim, podman and its network deps.
- Pinned, checksum-verified downloads: ttyd, starship (as today).
- `chrome-devtools-mcp`, installed at build at a pinned version (an `ARG`) with `npm install -g`, so the registry runs the installed program and never `npx` (D23, 4.4).
- The tool infrastructure: `swarmbox-tool`, `swarmbox-shim`, `swarmbox-init`, `swarmbox-attach`, the manifests, and the shims
  and index that `swarmbox-tool link --system` generates.
- Config files and scripts from `container/`, and `cloudflare-setup.py` for the host helper.
- Nested Podman set up for the fixed user: 10.5 lists every setting and why it is there.
- Kept from today's image: the Python venv at `/opt/flow` (the `(swarmbox)` prompt) and `uv`, the shell aliases, `<workspace>/.local/bin` on
  `PATH`, Starship (opt-out `SWARMBOX_STARSHIP=0`), the banner, and Chromium with its environment.

What it does **not** contain: any agent (Claude Code, Gemini CLI, OpenCode), gcloud, clasp, Go, Poetry. They arrive on demand
(or with `WITH_TOOLS`). The memory service was already removed before v0.1.0 and stays out. `cloudflared` is not in the
image either: it runs from its own image, on the host.

### 10.2 Behavior

- **User:** fixed `agent`, UID/GID 1000. No `USER_UID`/`HOST_OS` build arguments; the host user is mapped at run time
  (`keep-id`, 3.6). `sudo` without a password is intentional: the box is the sandbox. **How the user is made.** The base image `node:24-slim` already has a user `node` with UID and GID 1000
  (expected from Node's official images; not checked for this tag here `[unverified]`, B26, to be confirmed by the image build test). The Dockerfile renames it instead of adding a second user:
  `usermod -l agent node`, `groupmod -n agent node`, `usermod -d /home/agent -m agent`, `usermod -s /bin/bash agent`, and `agent ALL=(ALL) NOPASSWD: ALL` appended to `/etc/sudoers`.
  v0.1.0 does the same when the requested UID already exists (its `USER_UID` defaults to 1000) and otherwise creates the user with `groupadd` and `useradd` `[today]`; 2.0 keeps only the rename branch.
- **Directories:** `WORKDIR /home/agent`, which is the workspace mounted from the host.
- **Startup:** `ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]`, `CMD ["serve"]`. Subcommands:
  `serve` (the box's main process; the ordered steps and their failure behavior are in 4.1),
  `attach` (join the tmux session; what the host function runs on every entry, after linking the user tools),
  `init` (print the host function), `host-helper` (write the host helper archive on stdout), `pubkey`, `tool ...`, and any other command, which is run as given. There is no `init.sh`: 10.3 says
  where its duties go.
- **Layer order:** stable first (system packages, Podman, pinned downloads), volatile last (scripts, manifests). A change
  to a manifest never invalidates the system layers.
- **Wiring the tools** (near the end, with the other volatile layers):

  ```dockerfile
  COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool
  COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim
  COPY container/tools/                   /usr/local/lib/swarmbox/tools/
  COPY container/host/ cloudflare-setup.py /usr/local/share/swarmbox/host/     # the helper archive, 9.3
  RUN chmod 755 /usr/local/bin/swarmbox-tool /usr/local/bin/swarmbox-shim && swarmbox-tool link --system   # also writes .../host/tool-ports
  ENV PATH=/usr/local/lib/swarmbox/shims:$PATH
  ```

  `link --system` reads every manifest, creates one symlink per command in `/usr/local/lib/swarmbox/shims/` pointing at
  `swarmbox-shim`, and writes the index. At container start and at every entry, `swarmbox-tool link --user` does the same for
  the user level.
- **Layer hygiene:** every `RUN` that downloads cleans up in the same `RUN` (apt lists, npm cache, temp files), because a
  later `rm` does not shrink an image. Files that must be user-writable are created with the right owner, not `chown -R`
  afterwards, which duplicates them in a new layer.
- **Pinning:** every version is an `ARG` with a default; checksums are verified when published.
- **Size budget:** the neutral image should stay under about 2.5 GB. Today's image is about 4.2 GB, of which agents, gcloud,
  clasp, Go and Poetry are roughly 2 GB `[verified: layer sizes of the v0.1.0 image on the maintainer's machine; command, date, Podman version and OS not recorded]`. The 2.5 GB figure is a budget, not a
  measurement of the proposed build `[unverified]` (B27).
- **Flavors (optional):** CI may also publish `-claude`-style tags built with `WITH_TOOLS`, for users who want zero first-run wait.
- **npm cache:** the image creates `box:/opt/npm-cache` owned by `agent` (created with the right owner, not `chown -R` afterwards) and sets `NPM_CONFIG_CACHE=/opt/npm-cache`. It must be owned by `agent`, because an `npm` run as root at build leaves root-owned entries
  that make a later `npm` as `agent` fail with `EACCES` (v0.1.0's `Dockerfile` comment around lines 332 to 334 `[today]`). Installers clean or redirect it (6.4).
- **Environment:** `LANG=C.UTF-8`, `NPM_CONFIG_CACHE` outside the home, `BROWSER=none`, `CHROME_BIN` and `PUPPETEER_*` (kept: the
  chrome-devtools MCP needs them with the local Chromium). `ANTHROPIC_MODEL` is no longer set in the image. Chromium stays in the image
  in 2.0 for the chrome-devtools MCP (D24); that is revisited when its size is measured. `chrome-devtools-mcp` is installed at build at a pinned version (D23, 4.4).
- **MCP base file:** v0.1.0 generates `/etc/claude/mcp-servers-base.json` at image build from `container/mcp/chrome-devtools/config.json` `[today]`. In 2.0 that build step is gone: the registry (4.4) replaces it and `serve` writes the MCP file at start.

### 10.3 What `init.sh` does today, and where it goes

| Today (`container/scripts/init.sh`, run from `bashrc` in every interactive shell) `[today]` | New home `[new]` |
|---|---|
| Creates `<workspace>/.claude`, `settings.json` and its link | Gone: Claude Code's own `<workspace>/.claude/settings.json` is used directly (migrated, 12.4) |
| Creates `<workspace>/.swarmbox/` | `serve`, from `dirs.sh` (the XDG folders) |
| Ensures the SSH key | `serve` runs `swarmbox-pubkey --ensure`; the shell prints the one-line fingerprint |
| Generates `mcp-servers.json` (chrome-devtools by name) | `serve`, from the MCP registry (4.4) |
| Renders the OpenCode config and mirrors the MCP list | `container/tools/opencode/prepare.sh`, run by `serve` at step 7 (4.1); it reads the template `container/tools/opencode/local-llm.json` (moved from `container/opencode/`); `shell.sh` only exports `OPENCODE_CONFIG` |
| Starts the nested Podman service and the web terminal | `serve` |
| Prints the banner and messages in every shell | A light fragment sourced from `box:/etc/bash.bashrc` (`container/config/bashrc.sh`): banner, aliases, `PATH`, Starship, and each tool's `shell.sh` |
| Re-links the tool shims | `swarmbox-attach` (`swarmbox-tool link --user`) |

The heavy work leaves the per-shell path: a new shell no longer runs a script that regenerates files; `serve` does it once per start.

### 10.4 Distribution and versioning

- Image `ghcr.io/<org>/swarmbox`, multi-arch (amd64, arm64), tags `X.Y.Z` and `X.Y`. `latest` exists but docs always show a
  version. Digests are published in the release notes. The first public version is `2.0.0`; `<org>` is a documented placeholder until the name and license are settled (D32). The license is Apache-2.0;
  checking that the name SwarmBox is available is a task to finish before the first public release (D25, 15).
- Release pipeline: build, run tests, vulnerability scan, sign (cosign), publish, attach the SBOM (13).
- Semantic versioning; `CHANGELOG.md`. `v0.1.0` is the last release of the private design.
- A Dependabot/Renovate config bumps the pinned versions and the base image.

### 10.5 Nested Podman inside the image (kept from today)

Podman runs rootless **inside** the box so agents can build and run containers with no path to the host's Podman (11). It works only because of the settings below, all taken from v0.1.0's Dockerfile `[today]` and kept
unchanged in 2.0 (read from `git show v0.1.0:Dockerfile`; each reason is the one written there). `docs/nested-podman.md` explains the same setup with the test commands; this table is the complete list, so an implementer needs
nothing else to rebuild a working image. The run-time half (the device, the unmasked `/proc`, the volume) is in 3.6 and 8.3.

| Setting in the image | Why |
|---|---|
| Packages `podman`, `netavark`, `aardvark-dns`, `iptables`, `uidmap` (provides `newuidmap` and `newgidmap`), `libcap2-bin` (provides `setcap`) | Podman itself; netavark and aardvark-dns give nested containers DNS by name; `uidmap` and `setcap` are needed by the next two rows |
| `chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap`, then `setcap cap_setuid+ep /usr/bin/newuidmap` and `setcap cap_setgid+ep /usr/bin/newgidmap`: file capabilities instead of the setuid bit | A setuid-root binary does not work in an unprivileged container (the write to `uid_map` fails with `EPERM`); file capabilities do. The official `quay.io/podman/stable` image does the same |
| `/etc/subuid` and `/etc/subgid` each contain `agent:1001:64535` | The base image's user was renamed from `node` to `agent`, which leaves a stale range for `node`. The range 1001 to 65535 works both with `--userns=keep-id` and with the default user namespace |
| `/etc/containers/storage.conf`: `driver = "overlay"` and, under `[storage.options.overlay]`, `ignore_chown_errors = "true"` | Native overlay works because the home is a bind mount of a real file system (overlay on the container's own overlay root would not work; `vfs` is the slow fallback). The box has only about 64 thousand user IDs, so image layers whose files are owned by a higher ID (65534 `nobody`, 65532 distroless `nonroot`: busybox, cloudflared...) cannot be extracted without `ignore_chown_errors`; those files become root-owned |
| `/etc/containers/containers.conf`: `[containers] utsns = "host"` | The nested `crun` cannot call `sethostname` without `CAP_SYS_ADMIN` |
| the same file: `[engine] cgroup_manager = "cgroupfs"` and `events_logger = "file"` | There is no systemd inside the box, so Podman cannot use the systemd cgroup manager or the journal (the reason is not written in v0.1.0's Dockerfile; this is the usual cause `[unverified]`, B28) |
| the same file: `[network] network_backend = "netavark"` | Selects netavark, needed for DNS between nested containers |

Neither configuration file lives under the home, because the home is a bind mount and nothing in it could come from the image.

## 11. Security model

What the sandbox protects: the host's files and processes outside the workspace folder, and the host's Podman socket (it is
never mounted).

What it does not protect, and must say so:
- The agent can change or delete everything in the workspace, which holds all the projects, the login and the SSH key.
- Variables passed in (7) are stored in the container's configuration and visible to every process in the box, including
  to `podman inspect` on the host.
- The container has `sudo`, open outbound network, and can read its environment: API keys passed in are visible to the agent.
- Nested Podman is always on and needs `/dev/net/tun` and an unmasked `/proc`, which weakens the box's isolation compared with a plain
  container. It is a deliberate trade-off: agents can build and run their own containers without any path to the host's Podman.
- The box is persistent: an agent keeps running (and keeps those keys) while you are away, until you stop the box.
- The SSH key lives in the workspace: anything running in the box can use it. Use per-repository deploy keys.
- The web terminal has no login on its own port. It is bound to `127.0.0.1`; remote access goes only through Cloudflare Access.
- Remote access means a browser session is a shell with `sudo`. The login length (`--session`) is the exposure window of a
  stolen or forgotten browser session: 4 hours by default today; a week is a deliberate choice. Cloudflare lets an
  administrator revoke sessions; where in the dashboard has not been checked `[unverified]` (B14).
- Installing tools on demand means the agent triggers downloads. Versions are pinned and checksums verified where published; agents install `latest` (D21).
- A tool with `UPDATE=self` (Claude Code) updates itself in the background: new vendor code runs inside the box without a
  SwarmBox pin or checksum, and two workspaces can differ. It is limited to the box, but it has the same keys the agent has.
- The host helper runs on the host with the user's privileges. It is accepted as coming from the signed image the user already trusts; a separately signed asset is published only if users ask (D26).
- The Cloudflare tunnel token may be stored in the host config, readable by the user, with mode 600 (3.7.3, D28); it never enters the box.
- The redistributed image includes Debian, Chromium and other third-party software, each under its own license; they are listed in `THIRD_PARTY_NOTICES.md`, which a release must keep complete.

Defaults: no published ports beyond `127.0.0.1`, no host-network mode, tunnel credentials stay on the host
(the connector runs outside the box), `cloudflare-setup.py` never stores the API token, and the tunnel token is never passed
into the box.

## 12. Comparison with v0.1.0 and migration

### 12.1 Kept, changed, removed

| Kept as it is | Changed | Removed |
|---|---|---|
| One persistent container and the shared tmux session `main` | One function and a public image replace `start.sh` and a local build | `--host-network` |
| Nested Podman, always on, and the host connection | Workspace chosen at install, not `.work/` of the current directory | `build.sh`, `lib/`, `start.sh` (after parity) |
| The SSH key and `swarmbox-pubkey` | Agents installed on demand instead of baked in | `--update-harness`, `OPENCODE_VERSION`, `CLAUDE_CODE_CACHEBUST` |
| ttyd and the clipboard bridge | Web terminal on by default | `USER_UID`, `USER_GID`, `HOST_OS`, the darwin `chmod -R 777` |
| `--ports`, `--hostname`, time zone, `--init`, `--remote-browser` (as config keys) | Environment names in a config file instead of `--env-keys` on every call | `claude-mcp`, `uuid()`, `ANTHROPIC_MODEL=sonnet` |
| The Cloudflare script and its options | The XDG layout replaces `<workspace>/.swarmbox/` | OpenCode's local-LLM defaults |
| Starship, banner, aliases, `/opt/flow`, `uv` | Claude Code auto-update on (`UPDATE=self`) | `container/scripts/init.sh` |
| The nested Podman volume `<name>-containers` | `--image` and the build-if-missing step become `IMAGE` and pull-only (12.3) | `--iports` port numbers, `--clasp`, `--no-shell` as separate flags |

### 12.2 Removals and replacements (decisions D7, D8, D9 are taken)

| Item | Proposal | Reason |
|---|---|---|
| `--host-network` | Remove (D7) | It conflicts with `--web` (refused today), removes the network isolation, and `PORTS` covers publishing. |
| `start.sh`, `build.sh`, `lib/` | Retire after parity (D8) | The function replaces them. Two entry points double the tests and the docs. Parity is checked row by row against 8.4. The image is built with `podman build` (documented in `CONTRIBUTING.md`). |
| `USER_UID`, `USER_GID`, `HOST_OS` build arguments, the darwin `chmod -R 777` | Remove | Replaced by `keep-id` at run time (3.6). |
| `--update-harness`, `OPENCODE_VERSION`, `CLAUDE_CODE_CACHEBUST` | Remove | The agents are no longer in the image. |
| `--clasp` | Replace | The clasp manifest declares its port (`PORTS`, 6.3); the helper adds it from `tool-ports` when `clasp` is in `WITH`. |
| `--iports` port numbers | Simplify to `HOST_ACCESS` | The numbers are ignored today. |
| `--no-shell` | Replace with `swarmbox up` | Same use (automation), clearer name. |
| `claude-mcp` wrapper | Remove | Nothing references it; the `claude` alias already passes `--mcp-config`. |
| `uuid()` shell function | Remove | A personal convenience, not part of a neutral image. |
| `ANTHROPIC_MODEL=sonnet` in the image | Remove | A personal default; users set a model through `ENV_KEYS`. |
| OpenCode's local-LLM defaults (the model name and `host.containers.internal:8000`) and the automatic forwarding of `LOCAL_LLM_*` | Remove the defaults and the forwarding; keep `LOCAL_LLM_*` as ordinary `ENV_KEYS` entries | Neutral defaults; the feature stays opt-in. Users run `swarmbox env add` (7.2). |
| `<workspace>/.claude/settings.json` symlink into `<workspace>/.swarmbox/` | Remove after migration | The home is already the workspace, so `<workspace>/.claude` persists by itself. The first start of the new image replaces the link with a copy of the file (12.4). |
| `<workspace>/.swarmbox/` | Replace with the XDG layout (4.3; D10) | One predictable layout, consistent with the tool folders. |
| `container/scripts/init.sh` | Remove; its duties are split (10.3; D9) | The new model has no init script. |
| `cloudflare-setup.py`: `--connector-image` | Replace | The connector image is pinned in the helper; `SWARMBOX_CLOUDFLARED_IMAGE` stays for overrides. |
| Image packages `software-properties-common`, `lsb-release`, `apt-transport-https` | Remove after a build test | Candidates only; nothing checked depends on them. `procps` stays (`pgrep` is used by the web-terminal and Podman-service scripts). |

Kept on purpose, so nobody reads them as removals: `--remote-browser` (as `BROWSER_URL`; today `--remote-browser` with no argument means port 9222, `start.sh` lines 75 to 80 `[today]`, and a bare number or `host:port` is accepted, 7.2), `--ports`, `--hostname`, the time zone, `--init`,
the SSH key, the nested Podman volume and host connection, the Cloudflare options `token`, `--print-token`, `--no-connector`, `--dry-run`,
`--tunnel`, `--no-verify` (they pass through `swarmbox remote setup`, outside the main flow).

### 12.3 Mapping of today's behavior to the proposal

| Today (v0.1.0) `[today]` | Proposed `[new]` |
|---|---|
| `start.sh` creates/enters the persistent container | The `swarmbox` function does the same, from a public image |
| `./start.sh --web` plus `cloudflare-setup.py` plus token variables | Web terminal on by default; `swarmbox remote setup/status/off` |
| `.work/` in the current directory | `WORKSPACE`, default `host:~/swarmbox` |
| Agents baked into the image | Installed on demand (`WITH`) |
| `./start.sh --env-keys A,B` on every creation | The names live in the host config; `swarmbox env add/rm/list`; same creation-time behavior |
| `LOCAL_LLM_*` forwarded automatically; `BROWSER_URL` passed as `-e BROWSER_URL` | `LOCAL_LLM_*` through `ENV_KEYS` (users run `env add`); `BROWSER_URL` as `-e SWARMBOX_BROWSER_URL` |
| `./build.sh --update-harness`; `DISABLE_AUTOUPDATER=true` | Claude Code updates itself (`UPDATE=self`); other agents: `swarmbox-tool update <agent>` |
| Image built locally with the host UID; **`--image NAME` chooses the image, and a missing image is built by `start.sh`** | One public image, `keep-id` at run time; **`IMAGE` / `SWARMBOX_IMAGE` / `init --image` choose it; a missing image is pulled, never built; a local build is run with `podman build -t swarmbox:dev .` and `SWARMBOX_IMAGE=swarmbox:dev` (3.8)** |
| `claude` alias in `bashrc` | Generated from the agent manifest |
| `cloudflare-setup.py` resets the login length to 4h on rerun | Keeps the configured value |
| Connector image `docker.io/cloudflare/cloudflared:latest` (`cloudflare-setup.py:36`) | Pinned in the helper; `SWARMBOX_CLOUDFLARED_IMAGE` still overrides. Pinning is a change |
| `start.sh`, `build.sh`, `lib/` | Retired; the `swarmbox` function replaces them (12.2) |
| `--ports`, `--iports`, `--host-network` | `PORTS`, `HOST_ACCESS`; the host-network mode is removed |
| `--remote-browser` | `BROWSER_URL` |
| `--hostname`, `SWARMBOX_TZ`, `SWARMBOX_INIT` | `HOSTNAME`, `TZ`, `INIT` |
| `--clasp` | The clasp manifest's `PORTS` |
| `--no-shell`, `SWARMBOX_ATTACH=shell` | `swarmbox up`, `swarmbox --plain` |
| Nested Podman always on | Unchanged: always on |
| `<workspace>/.swarmbox/` | The XDG layout (4.3); migrated at the first start |
| `container/scripts/init.sh` | Split across `serve`, `swarmbox-attach`, the tools' `prepare.sh` and `shell.sh`, and a light bash fragment (10.3) |
| Options given to `start.sh` for an existing container are refused with a warning | The fingerprint comparison on every entry (3.7.4); warns, does not block |

### 12.4 Migration steps

1. **Back up the workspace.** The layout migration is one-way: an older image looks for `<workspace>/.swarmbox/`.
2. Stop and remove the v0.1.0 container (`podman rm -f swarmbox`); the workspace folder and the volume `swarmbox-containers` stay (3.8).
3. Install 2.0 with `init --workspace <path to .work>`: an existing `.work/` is used as the workspace as is. Keep this order: remove the old container (step 2), run `init --workspace` and add its output to the shell startup file, with **no `swarmbox` call in between**, then enter. A call before `init` has recorded the workspace would create the config file with the default workspace `host:~/swarmbox` (3.7.5) and stop on the v0.1.0 container (3.8). Once the config file exists, `swarmbox config set WORKSPACE <path to .work>` is the remedy.
4. `swarmbox env add` for every name that was in `--env-keys`, and for `LOCAL_LLM_*` if used (7.2). `swarmbox config set PORTS ...` / `BROWSER_URL ...` for the other flags.
5. If remote access was configured, run `swarmbox remote status`; the Cloudflare configuration is read from the same files as before.
6. The first `swarmbox` creates the box; `serve` runs the layout migration below.

**What `.swarmbox/` holds at v0.1.0 and what happens to each item.** `serve` acts only on files that exist, and never overwrites an existing destination.

| File in `<workspace>/.swarmbox/` | Verb | Destination |
|---|---|---|
| `settings.json` (Claude settings; `<workspace>/.claude/settings.json` is a link to it) | copied, then removed | the link is replaced by a real file at `<workspace>/.claude/settings.json` holding the same content; then `.swarmbox/settings.json` is deleted |
| `web-terminal.conf` (and any copies) | moved | `<workspace>/.config/swarmbox/web-terminal.conf` |
| `ttyd-index.html` | deleted | regenerated as `box:/tmp/swarmbox/index.html` at every start |
| `opencode-local.json` | deleted | regenerated as `box:/tmp/swarmbox/opencode.json` by the opencode tool's `prepare.sh` |
| `podman.sock` | deleted | the service recreates it at `<workspace>/.local/state/swarmbox/podman.sock` |
| logs (for example `web-terminal.log`) | deleted | new logs go under `<workspace>/.local/state/swarmbox/` |
| locks | deleted | locks live in `box:/tmp/swarmbox/` |
| `memory/` (left by the removed memory service) | left alone | `serve` mentions it once; the user may delete it |

`<workspace>/.swarmbox/` is removed only when it is empty afterwards. **It stays when `memory/` exists.**

**The host-side step.** The Podman connection `podman -c <name>` points at the old socket address. On every `up`, the helper compares the registered connection with the new address and, when they differ,
removes and re-adds it with `podman system connection` (Linux and WSL; today's `lib/podman-connection.sh` already replaces a connection whose address changed `[today]`).

The migration has not been written or tested `[unverified]` (B29); a migration test on a fixture workspace is planned (13).

### 12.5 Uninstall, telemetry and logs

**There is no `swarmbox uninstall` in 2.0 (D36).** The manual steps, in this order (the README repeats them, Phase 6 of the plan):
1. Remove the function block from the shell startup file: everything between the markers `# >>> swarmbox 2.0.0 >>>` and `# <<< swarmbox 2.0.0 <<<` (the version in the markers is the one you installed; a second `init` run leaves a second block).
2. Stop and remove the box: `podman rm -f swarmbox` (or the name given with `SWARMBOX_NAME`; repeat for each second box).
3. Remove the host helper folder: `rm -rf ~/.local/share/swarmbox/host`, and the host state folder `~/.local/state/swarmbox` (locks and `notices`).
4. Remove the host config folder `~/.config/swarmbox` (the config, `cloudflare.json`, the folders of second boxes). It may hold the tunnel token: remove it too.
5. If remote access was set up: `swarmbox remote off` first (before step 1) removes the DNS record, the route and the Access application; then remove the connector container, `podman rm -f swarmbox-cloudflared`.
6. Optionally, the workspace folder (`~/swarmbox` by default: your projects, logins and tools; back up what you need), and the nested Podman volume `podman volume rm swarmbox-containers` (`<name>-containers`).
7. Optionally, the image: `podman rmi ghcr.io/<org>/swarmbox:<tag>`.

**Telemetry and logs.** SwarmBox sends no telemetry and makes no network call of its own except to pull the image, to install a tool you asked for, to check for a tool update (6.7) and, with `remote`, to reach Cloudflare. Logs stay on your machine:
`<workspace>/.local/state/swarmbox/` (`serve.log`, `health`, the web terminal log), and on the host only the small state folder `host:~/.local/state/swarmbox/` (locks, `notices`).

## 13. Tests and CI

### 13.1 From v0.1.0's test files to 2.0

v0.1.0 has 12 files under `tests/`: `helpers.py` and 11 `test_*.py` files.

| File | What it covers today `[today]` | 2.0 target `[new]` |
|---|---|---|
| `helpers.py` | only `ROOT`, the repository root (4 lines); there are no shared fakes: each test writes its stubs inline (for example `STUB`, a fake `podman`, in `test_start_attach.py`) | **created** as the shared home of the fakes: a fake `podman` that records its calls and `create-flags` output, and a fake host helper (a target, not an extension of something that exists) |
| `test_clipboard_bridge.py` | the clipboard bridge in a real browser, page built by `web-terminal.sh` | kept; the page now comes from `build-index.sh` |
| `test_cloudflare_setup.py` | `cloudflare-setup.py` against a fake Cloudflare API | kept; adds `--session` preserved on rerun and `remote` wrappers |
| `test_ssh_key.py` | `swarmbox-pubkey` (`ssh-key.sh`) | kept |
| `test_starship.py` | the Starship prompt and its Dockerfile wiring | kept; the Dockerfile assertions rewritten for the new image |
| `test_start_attach.py` | what `start.sh` opens: window of session `main`, grouped session, `SWARMBOX_ATTACH=shell` | rewritten against `swarmbox-attach` (real tmux, no container) and the function's `--plain` |
| `test_start_init.py` | `--init` handling in `start.sh` | rewritten against `create-flags` (key `INIT`) |
| `test_start_timezone.py` | time zone handling in `start.sh` | rewritten against `create-flags` (key `TZ`) |
| `test_start_web_connector.py` | how `start.sh --web` brings up the connector | rewritten against the helper's connector logic in `up` |
| `test_tmux_browser_keys.py` | `tmux-browser-keys.conf` with real tmux | kept |
| `test_web_style.py` | the look of the web terminal, in a browser | kept; page from `build-index.sh` |
| `test_web_terminal.py` | how `web-terminal.sh` builds the ttyd command line | rewritten against `swarmbox-web` |

New tests: `create-flags` for every key of 8.2 (quoting, a value with spaces, a list) and for the ports taken from `tool-ports` (a fixture file with the line `clasp<TAB>43323`; see below), the config grammar (3.7.3) including the mode-600 rule for the tunnel token, `env` commands, the fingerprint and labels, the exit codes of 3.7.2, the prerequisite
messages of 3.8, `serve` step failures (4.1), `swarmbox-tool` and the installers with a fake installer, MCP generation, the OpenCode mirror and `prepare.sh` (4.4, 6.3).

`create-flags` cases for tool ports (6.3), with a fake `tool-ports` and no container:
- `WITH=clasp`, empty `PORTS`: the output contains `-p` and `127.0.0.1:43323:43323` once. This is the parity case for v0.1.0's `--clasp` (12.2).
- `WITH=clasp` and `PORTS=43323`, and `PORTS=43323:9000`: no second mapping for 43323 (today's rule: an entry that starts with the number).
- `WITH=clasp,gcloud`: only the ports that `tool-ports` lists (gcloud has none).
- `WITH=mytool` where `mytool` is only a user-level manifest, or is not in `tool-ports`: no port added, exit 0.
- `WITH` empty: no tool port. A `tool-ports` file that is missing: exit 3 with a message to run `swarmbox update` or re-extract the helper (the image build always writes the file, empty when no manifest declares ports, so a missing file means a corrupted helper archive, 3.7.1). An **empty** `tool-ports` is a normal state: no port added, exit 0.
- The fingerprint and `swarmbox.ports` change when `clasp` is added to `WITH`.

### 13.2 Parity

**Parity** (D8) means: every row of the feature catalog (8.4) has a test that passes against the function (with a fake Podman where possible). Only then are `start.sh`, `build.sh` and `lib/` deleted.

### 13.3 Test layers

1. **Unit tests with fakes**: Python and shell tests with a fake `podman`, a fake Cloudflare API and fake installers. They never run a real container.
2. **Image smoke test**: builds the image and runs throwaway containers (`podman run --rm`, names that are never `swarmbox`) to check that `serve` reaches readiness, `swarmbox-tool validate` passes
   and the page is built. It **never touches a running box**: it uses its own names and workspace folder, and on a developer machine is run with an explicit opt-in.
   It also **restarts a stopped throwaway box** (`podman stop`, `podman start` on its own container, never the user's box) and checks that `box:/tmp/swarmbox` is empty right after `podman start`
   (the tmpfs, B17), that the old `ready` marker is gone, and that `up` does not return until the marker of the **new** run exists (a `serve` held back at step 0 must keep `up` waiting). It also checks that a `serve` made to fail
   fatally makes host `up` exit 6 at once with the `podman logs --tail` lines, not after 60 s, and that `swarmbox-attach` run inside a box whose marker never appears prints
   "the box is not ready; run `podman logs <name>` on the host" and exits 6 after its 60 s (`attach` cannot see the container state, so it does not exit sooner). It also checks `reset` on a throwaway box:
   the container is replaced, the volume and workspace survive, `reset` returns only after readiness with `up`'s exit code, and a throwaway container **without** the label `swarmbox.managed` is refused with exit 5 and still exists afterwards.
   A creation that fails (a throwaway box whose `WEB_PORT` is already bound by the test) exits 7 with the message of 3.8 and leaves no container that this call created (B18, B33); a second throwaway container that already has the box's name, created by the test beforehand, is **still there** afterwards (cleanup removes only by the ID in the `--cidfile`).
3. **Migration test** on a fixture workspace with a v0.1.0 `.swarmbox/` (every file of 12.4), checking each verb and that `memory/` stays.
4. **Function test** in bash, zsh and fish, including macOS bash 3.2 (the macOS runner's `/bin/bash`), with a fake `swarmbox-host` and a fake `podman`: word routing (3.3), array quoting of arguments with spaces, exit-code propagation. The **bootstrap** (3.6, 3.7.1) is tested with the same fakes:
   offline with no image gives exit 3 with the 3.8 message and the previous helper intact; a fake `podman` that exits non-zero, one that exits 0 but writes an empty or corrupt archive, and one whose archive has no executable `swarmbox-host`
   each give exit 3 with the previous helper intact and no temporary folder left; a good archive replaces the previous helper. None of these cases relies on a pipe status, so they behave the same in bash 3.2, zsh and fish.
   The **bootstrap condition** (D33, 3.6) is tested with a fake `swarmbox-host` whose `version` output is set by the test and a fake `podman` that records its calls, with the function marker at `2.0.0`:
   a missing or non-executable helper, one that prints no version, and one that prints `1.9.0` (below the marker) are each re-extracted (the fake `podman` records one `run ... host-helper`); a helper that prints `2.0.0` is kept
   with no `podman` call and no notice; `2.0.10` against a marker of `2.0.9` is treated as newer (the `sort -V` order, not a text order). The **update-then-next-call case**: run `swarmbox update` with the fake helper reporting that
   it has extracted `2.0.1` (so the fake host now holds a helper of `2.0.1` and the config says `IMAGE=...:2.0.1`), then make a second call with the unchanged `2.0.0` block: the second call does **not** run `podman run ... host-helper`,
   keeps the `2.0.1` helper, prints the one-line skew notice on standard error and routes the word as usual; a third call with a block whose marker is `2.0.1` prints no notice. The rollback case: `update --to` a tag at or above
   the marker keeps working across the next call, and removing the helper folder after replacing the block with an older one re-extracts from that block's image (3.8).

5. **Two terminals at once** (`up`'s lock and cleanup, 3.6, B33), with a fake `podman` that records its calls and a `create-flags` made to take a second, then with a throwaway real box: start two `swarmbox up` calls at the same moment (two background
   processes). Expected: exactly one `podman run` is recorded; the other call waits on the lock, then takes the fast path and exits 0 with the same readiness; both exit 0. Variants: the first call is killed while it holds the lock (the lock folder is
   removed by the trap, or, after `kill -9`, found stale by its dead pid on the next call and removed); `create-flags` exits 4 (a workspace problem) and no `podman run` is recorded; the fake `podman run` fails and writes a cidfile (only that ID is removed,
   exit 7) and a foreign container with the same name is not touched; a lock that a live process holds for more than 90 s gives exit 6.
6. **`swarmbox <command>`** (3.3, B13), with real tmux in a throwaway container: `true`, `false`, `sh -c 'exit 130'`, a command with spaces, quotes and `$`, a command killed by a signal (exit `128 + n`), an alias and a `PATH` addition defined in the shell fragment
   (visible to the command), a window killed from outside (`tmux kill-window`; the call returns 129 and does not hang), and `swarmbox pubkey > file` with standard output redirected (the file has no CR; `podman exec` was run without `-t`; standard error stays empty, no job-control messages).

### 13.4 What `ci.yml` and `release.yml` run

| When | What |
|---|---|
| Every push and pull request (`ci.yml`) | unit tests, `swarmbox-tool validate`, the migration test, the function tests in bash, zsh and fish on Linux and bash 3.2 on macOS (with a fake Podman), the image build and smoke test (not pushed). The Linux runner image must ship Podman 4.3 or newer (the Ubuntu 22.04 image ships Podman 3.4, which is too old) or the job installs Podman itself |
| From Phase 3 of the plan, if the CI provider allows | an arm64 job: build the image for arm64 and run the smoke test on an arm64 runner (B31) |
| On release (`release.yml`) | multi-arch build, tests, vulnerability scan, signing, publish, SBOM |
| On a schedule (weekly) | the real-installer tests for every tool: "no side effects" and "survives a reset" (6.9), the browser tests against the freshly built image |

`[unverified]` whether the CI provider's macOS runner provides Podman for the function test; the function test uses a fake Podman, so it does not need it (B30).

## 14. Open questions

No design decision is open: all are taken and listed in the table "Decisions already taken" in the Overview (D1 to D39). Part B lists facts nobody has checked, each with the test that closes it. The body cites them as B1, B2... and the decisions as D1 to D37.

### Part B. Facts to verify

Each test below is run in a throwaway container or with fakes, never on the box that holds live sessions.

| ID | Fact | Test that closes it | Where cited |
|---|---|---|---|
| B1 | Which Claude Code install method keeps its updater working (npm under `--prefix`, or the vendor's native installer into the home), and whether the native installer writes outside the home | In a throwaway container with an empty home: install each way, run `claude update`, compare a file listing of `/usr`, `/etc`, `/opt` and the home before and after | 6.7, 6.11, 6.12 |
| B2 | OpenCode's auto-approve flag | Read OpenCode's documentation and `opencode --help` for the installed version; run it with the flag against a trivial prompt | 6.6, 6.12 |
| B3 | **Spiked in 0.1 (4.1, 5.1 carry the result); closed by the product test in Phase 2.** `serve` works as the container's main process, and `swarmbox-web restart` restarts ttyd without stopping the box; `serve` as PID 1 handles SIGTERM and SIGINT (stops its children and exits), with and without `--init`, and with `WEB=0` blocks without ttyd | Run a test image with a throwaway name and workspace; kill ttyd; check the box stays up and the supervisor restarts it; `podman stop` time (well under the 10 s kill timeout) with `INIT=0`, `INIT=1` and `WEB=0`; send SIGINT with `podman kill --signal INT` | 4.1, 5.1 |
| B4 | ttyd serves a single-file page only | Read ttyd's documentation for `--index`; try a page that references a second file | 5.1 |
| B5 | The unix socket path limit and the helper's fallback | Create workspaces with paths of increasing length, start the Podman service, find where the connection fails (Linux; macOS if applicable) | 3.5 |
| B6 | The whole design on macOS (Podman machine): workspace sharing, `keep-id`, tun, the socket not crossing the VM | Run install, enter, reset, web terminal on a Mac; record every failure as a documented limit | 3.5, 3.6 |
| B7 | A host UID other than 1000 works with `keep-id:uid=1000,gid=1000` | Create a user with another UID, run a box, write files in the workspace, check ownership on the host | 3.6 |
| B8 | The lowest Podman version that works (4.3 is only the version observed) | Run the smoke test on 4.0, 4.3, 4.9 and the latest | 3.8 |
| B9 | **Closed in 0.1 (7.3 carries the result).** How tmux passes its environment to new windows, so browser and host tabs see the same variables | In a test image, start tmux with a variable, change the client's variable, open a window, print both | 7.3 |
| B10 | The OpenCode size saving of about 720 MB also holds under `--prefix` | Install with `--prefix` in a throwaway container; measure before and after pruning | 6.4 |
| B11 | The gcloud download URL for both architectures, and whether Google publishes a checksum to compare the maintainer script's result with (D29) | Read Google's install documentation; download both archives; compare the computed checksum with any published value | 6.4, 6.12, D29 |
| B12 | Re-record the checks whose setup was not recorded: `keep-id` option acceptance, the 325 MB and 157 MB install measurement, the image size of 4.2 GB, the symlink `$0` behavior, the host-value `podman exec -e` check | Repeat each in a throwaway container and note date, Podman version, OS, image | 3.6, 6.2, 6.11, 7.3, 10.2 |
| B13 | **Spiked in 0.1 (3.3 carries the result and two corrections); closed by the product test in Phase 2.** `swarmbox <command>` (no `exec` of tmux; a window started detached with a `wait-for` channel and a status file): the call returns when the command ends, with its exit code; quoting survives; the aliases (including the agent auto-approve flag) and the `PATH` additions of the shell fragment apply in the command window; with standard output not a terminal, `podman exec` runs without `-t` and the output has no CRLF | Fake tmux test, then real tmux in a throwaway container: commands with spaces, quotes, `$`, exit codes 0, 1, 130 and a signal; `alias` and `PATH` check inside the window; `swarmbox pubkey > file` and a command piped through `od -c` look for `\r` | 3.3, 3.4, 13.3 |
| B14 | Where Cloudflare Access sessions are revoked in the dashboard | Read Cloudflare's documentation and find the screen | 11 |
| B15 | Whether `python3` is present on a clean macOS. With a POSIX `sh` helper (D16) it matters only for `swarmbox remote` | Check a fresh macOS install; run `swarmbox remote status` on it | 3.8, 5.2 |
| B16 | Restarting a container created with `--restart` (the box would be one; the Cloudflare connector already is, `--restart=always`) after a host reboot works for rootless Podman and under what service (`podman-restart.service` for the user, which must be enabled) | Read Podman's documentation; test `podman-restart.service` for the user | 4.2 |
| B17 | **Closed in 0.1 (4.1 step 0 carries the result).** A `--tmpfs /tmp/swarmbox` mount is empty after `podman stop` and `podman start`, is writable by the `agent` user (with the `keep-id` mapping), and its default options (Podman may add `noexec`) do not break `serve` or the shells | Throwaway box with the flag: write a file, stop, start, list the folder, write as `agent` | 3.6, 4.1, 4.2 |
| B18 | **Closed in 0.1 (3.5 carries the result).** When `podman run -d` fails because a published port is in use, whether a container is left behind (state `Created`) and what exit status and message Podman gives | Throwaway box on a port that the test binds first; run `podman ps -a`, read the status and stderr | 3.5, 3.8 |
| B19 | `sort -V` exists and orders versions as the bootstrap needs (`2.0.9` before `2.0.10`) in macOS's `sort`, in the `sort` of the Linux distributions used, and when called from bash 3.2 and zsh (D33) | On a Mac and on each CI image run `printf '2.0.10\n2.0.9\n2.0.0\n' \| sort -V` and compare with the expected order; run the function test of 13.3 on the macOS runner | 3.6, 13.3 |
| B20 | Pulling the moving `X.Y` tag and reading the version from the extracted helper gives the exact `X.Y.Z` to record as `IMAGE`; `podman tag <repo>:X.Y <repo>:X.Y.Z` makes a local tag that a later `reset` uses with no network; `update --to TAG` pulls a given tag (D17, D33, D35) | In a test registry publish `2.0.0`, `2.0.1` and `X.Y`; run `swarmbox update` and `update --to 2.0.0`; read the config and the helper's `version`; disconnect the network and run `swarmbox reset` | 3.8 |
| B21 | The install line's `podman run --rm -e SHELL <image> init` delivers the host's `SHELL` to `init` (so `init` prints the right syntax by its basename, D20), including on macOS through the Podman machine, and a value that is not bash, zsh or fish gives bash | On a Mac (zsh) and a Linux host (bash, and with `SHELL=/usr/bin/fish` if fish is installed) run the install line without `--shell` and read the printed syntax; run it with `SHELL` unset | 3.1, 3.7.5 |
| B22 | The helper keeps the config file at mode 600 whenever it holds the tunnel token, and refuses a looser mode, on Linux, macOS and a WSL home on a Windows drive (D28) | Fake helper test with `stat`; then on each platform: `config set CLOUDFLARE_TUNNEL_TOKEN`, read the mode, `chmod 644`, run `remote status`, check the warning and that the token is ignored | 3.7.3 |
| B23 | The POSIX `sh` helper runs unchanged under macOS `/bin/sh`, dash and busybox `sh` (D16) | Run the helper's unit tests with each shell as the interpreter | 3.7.1 |
| B24 | The package `chrome-devtools-mcp`, installed with `npm install -g` at build, provides a program of that name that accepts today's options without `npx` (D23) | In a throwaway container install the pinned version, run `chrome-devtools-mcp --help`, start it with the registry's arguments and list its tools from an MCP client | 4.4, 10.1 |
| B25 | Go's official tarball has a publisher checksum that the same maintainer script as gcloud's (D29) can record | Read go.dev's download page and its JSON listing; download both architectures; compare with the computed checksum | 6.12 |
| B26 | The base image `node:24-slim` has a user `node` with UID and GID 1000 that the Dockerfile can rename to `agent` | `podman run --rm node:24-slim id node`; build the image and run `id agent` | 10.2 |
| B27 | The neutral image stays under about 2.5 GB | Build the image; `podman images` and `podman history`; record the size per layer | 10.2 |
| B28 | The cgroup manager `cgroupfs` and the file event logger are the right settings for Podman inside the box (the reason is not written in v0.1.0's Dockerfile) | In a throwaway box run a nested container with the settings, then with the systemd manager, and read the errors | 10.5 |
| B29 | The layout migration (`.swarmbox/` to the XDG layout, every file of the table in 12.4) works and never overwrites an existing destination | The migration test of 13.3 layer 3 on a fixture workspace, then once on a copy of a real v0.1.0 workspace | 12.4, 13.3 |
| B30 | The CI provider's macOS runner exists for the function tests (bash 3.2) and whether it provides Podman | Run a trivial workflow on the macOS runner: `/bin/bash --version`, `command -v podman` | 13.4 |
| B31 | The image builds for arm64 and the smoke test passes on an arm64 runner (nested Podman, `keep-id`, Chromium, the tools' `SHA256_arm64`) | The arm64 CI job of 13.4 (or `podman build --platform linux/arm64` under emulation, then the smoke test) | 10.4, 13.4 |
| B32 | Which paths WSL2 mounts from Windows drives (`/mnt/<letter>/`) and that the refusal of D34 catches them (and does not refuse a Linux path such as `/mnt/data` that is not a Windows drive) | On a WSL2 machine run `findmnt -t 9p,drvfs`; `swarmbox up` with a workspace under `/mnt/c/...`, a `~/swarmbox` workspace and a bind-mounted `/mnt/<other>` | 3.5, 3.8 |
| B33 | `up`'s lock and cleanup: `mkdir` is atomic and the stale rule never removes a live lock; `podman run --cidfile` leaves the ID of a container created by a failed run (or nothing) so that removal by ID removes only that container; two terminals at once create one box | The two-terminals test of 13.3 layer 5, with the fake `podman` and then a throwaway real box; B18 for the failed-run state | 3.5, 3.6, 13.3 |
| B34 | The portable mode check (`stat -c %a`, `stat -f %Lp`, or `find -perm`) returns the octal mode on Linux, macOS and a WSL home, including for a file with extended attributes (`-rw-------@` on macOS) | On each host: create a file with mode 600 and 644, add an extended attribute on macOS, run each form, compare | 3.7.3 |
| B35 | The fast path of `up` (box exists and runs) needs at most two Podman calls before attaching, and costs little | Run `swarmbox` with a fake `podman` that counts calls (at most two before `attach`), then time it on a real box against `podman exec` alone | 3.7.2 |
| B36 | `serve` creates `main` with one idle window that `attach` can recognize and close when it is the only other window, without closing a window a user created | Real tmux in a throwaway container: start `main` with the idle window, attach twice, list windows; type in a window before the second attach | 3.4, 4.1 |

#### Results of the Phase 0 spikes (slice 0.1)

Scripts are in `tests/spikes/` (not run in CI); each prints one `RESULT` line with its evidence tag and exits 1 if a claim of this design is contradicted. The shared image `swarmbox-test-spikes-img` is `node:24-slim` plus tmux 3.3a, procps and the box's pinned ttyd 1.7.7 binary (copied from the live box's `/usr/local/bin/ttyd`, a static executable of the same release).

| Fact | Result | Evidence |
|---|---|---|
| B17 | Closed. `--tmpfs /tmp/swarmbox` with `--userns=keep-id:uid=1000,gid=1000`: mounted `rw,nosuid,nodev,relatime` (**no `noexec`** on this Podman), writable by uid 1000 (mode 1777), empty after `podman stop` and `podman start`; a file outside the tmpfs survived (so the tmpfs is what clears the marker). Whether Podman versions other than 4.3.1 add `noexec` is B8's matter; nothing in the design executes from that folder, and the scripts there are run through an interpreter, which also worked. | `[verified: spike_b17_tmpfs.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B18 | Closed. A busy host port: `podman run -d` exits **126**, standard error `Error: rootlessport listen tcp 127.0.0.1:<port>: bind: address already in use`; the container is **left in state `Created`**; the `--cidfile` holds its 64-character ID; `podman rm -f <ID>` removed exactly that container and a bystander container stayed up. A name already in use: exit **125**, `the container name "X" is already in use by <id>`, **no cidfile**, the old container untouched. A `--cidfile` path that exists: exit 125, `container id file exists`. | `[verified: spike_b18_port_in_use.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B9 | Closed. Windows get the **server's** environment whichever client asks (see 7.3); `update-environment` is the one setting that changes that. | `[verified: spike_b9_tmux_env.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img]` |
| B13 | Spiked, not closed (the real `swarmbox-attach` does not exist yet). Confirmed: exit codes, quoting, alias and `PATH`, no lost wake-up, grouped client ends by itself, no CRLF without `-t`. **Two corrections to the first design, now in 3.3**: the wrapper needs a HUP/TERM trap (else killing the window leaves the caller blocked forever), and the no-terminal path must not use `bash -ic` (it prints job-control errors) but a non-interactive bash that sources the fragment, whose guard accepts `SWARMBOX_CMD=1`. | `[verified: spike_b13_run_command.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: script(1) as the client terminal]` |
| B3 | Spiked, not closed (the real `serve` does not exist yet). Confirmed with a prototype: PID 1 with and without `--init`, `WEB=0`, stop in 0.14 s, SIGTERM exit 143 and SIGINT exit 130, ttyd restart and hand restart, crash loop gives up after 5 and the box stays up. **One correction, now in 4.2**: the supervisor must stay alive after it gives up, or the hand restart has nothing to reach. | `[verified: spike_b3_serve_pid1.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: bash stand-in for serve, the nested Podman service is a sleep]` |

## 15. Roadmap

The phases, in short form. The order, the tests of each phase, its exit criteria and the table that places every decision, catalog row, command and Part B fact in a phase are in [implementation-plan.md](implementation-plan.md).

| Phase | What |
|---|---|
| 0 | Spikes and documentation reads: close the facts of Part B that can change the design (nested throwaway containers) |
| 1 | Foundations: Apache-2.0 license (D25), CI with the existing tests, the audit of the git history (D37), `dirs.sh`, test helpers |
| 2 | The box (M1): slim image, `entrypoint.sh` with `serve` and `attach`, `swarmbox <command>`, layout migration, the page built at image build, fixed UID, pinned `chrome-devtools-mcp` |
| 4a | Minimal tool slice: manifest parsing, `link --system`, `swarmbox-shim`, the claude manifest, an empty `tool-ports` |
| 3 | The host half: helper (`create-flags`, `up`, host config), generated function, `swarmbox-init`, variables, a local registry for the install test |
| 4b | The other tools, the MCP registry, `prepare.sh`, the environment fingerprint, `doctor`, `WITH_TOOLS`; in parallel with Phase 3 and after it |
| 5 | `swarmbox remote` (setup, status, off, token) over the existing Cloudflare script, login length preserved on rerun |
| 6 | Parity (M3): one test per row of the catalog (8.4); retire `start.sh`, `build.sh`, `lib/`, `init.sh`; documentation and the manual uninstall (D36) |
| 7 | Release (M4): registry, signing, name check (D25), security review of the helper, licensing of the image, `v2.0.0` |

Phase 4a comes right after Phase 2 and before Phase 3. Optional, after 2.0: an egress allowlist for the box's network, and a host-side credential proxy so the box never holds API keys.
