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
- `init --image REF` records `IMAGE` (8.2) and is also the image the function's first extraction uses. The default is `ghcr.io/<org>/swarmbox:<version>`, so an install from any other registry (the local registry of `docs/local-registry.md`) needs `--image`: `init` runs in a container and cannot know where it was pulled from. `init --shell bash|zsh|fish` prints the right syntax. Without `--shell`, `init` uses the basename of the `SHELL` variable it receives: the install line passes the host's
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
| `stop`, `reset`, `up`, `url`, `update`, `config`, `env`, `remote`, `fingerprint`, `version` | host only (the host helper, 3.7) | as in 3.2; `fingerprint` and `version` are the helper's own subcommands (3.7.2); none of them needs the box to be running, except that `url` and `remote status` read its labels | 0 ok; helper codes of 3.7.2 |
| `--plain` (option) | host, then forwarded | the function parses it and forwards `attach --plain` | as `attach` |
| *(nothing)* or `attach` | forwarded: `swarmbox-entrypoint attach` | open a new window of tmux session `main` through a grouped session (3.4); wait for the readiness marker first (4.2) | the shell's: 0 normally; 6 if not ready after 60 s (the box exiting while waiting is detected by `up` only, 4.2) |
| `pubkey` | forwarded: `swarmbox-entrypoint pubkey`, run without `-t` when standard output is not a terminal | print the public key | 0 |
| `tool ...` | forwarded: `swarmbox-entrypoint tool ...` | run `swarmbox-tool` (6.2) | its own |
| `<command> [args...]` (any other word) | forwarded: `swarmbox-entrypoint attach <command> [args...]` | see below | the command's own |

`swarmbox <command> [args...]` `[new]`, mechanism [verified: spike tests/spikes/spike_b13_run_command.py, tmux 3.3a in a throwaway container, a prototype wrapper; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img:1 (node:24-slim + tmux); reduced: the grouped client used script(1) as its terminal, no ttyd or host terminal] (B13; closed by the product test of slice 2.3, see the end of this section and Part B)
- **Why the mechanism must change.** v0.1.0's `lib/attach-session.sh` ends with `exec tmux new-session ...` (line 9) `[today]`: the shell is replaced by tmux, so nothing after that line can read an exit
  code. A command that returns its status therefore cannot go through that `exec`.
- **Intended mechanism.** For a command, `swarmbox-attach` does **not** `exec` tmux. It (1) picks an id and creates the command's window in session `main`, detached, with a wrapper as the window's command:
  the command runs through an **interactive** shell (`bash -ic '<quoted command>'`, so the aliases, including the agent auto-approve flag, and the `PATH` additions of the shell fragment `container/config/bashrc.sh` apply, 6.6),
  and when it ends the wrapper writes its status to `box:/tmp/swarmbox/exit.<id>` (written to a temporary name and renamed, so a reader never sees half a number) and signals a tmux `wait-for` channel (`tmux wait-for -S swarmbox-<id>`; a signal sent before the waiter arrives is not lost: 30 instant commands in a row all returned). The wrapper is passed to `new-window` as separate arguments (`bash -c '<wrapper>' wrapper '<quoted command>' '<status file>' '<channel>'`), not as one string, which adds no quoting layer. **The wrapper must trap SIGHUP and SIGTERM**: `tmux kill-window` ends the window without running the wrapper's last lines, and without a trap `tmux wait-for` blocks forever (measured); with `trap 'echo 129 > "$status"; tmux wait-for -S "$channel"' HUP TERM` the waiter returns and the status is 129. A wrapper killed with SIGKILL cannot run a trap, but its window disappears, so the waiter also polls `tmux list-windows` for its window id (about once a second) as a fallback `[unverified]` (the fallback loop itself is not built; only that the window disappears was measured); (2) starts the grouped session of 3.4 as a child process (not
  `exec`), selected on that window; (3) waits on the channel (`tmux wait-for swarmbox-<id>`, or an equivalent wrapper) and, when it fires, ends the grouped session so the client returns even if other windows exist;
  (4) reads the status file, deletes it and exits with that status. `swarmbox false` fails and `swarmbox true` succeeds. A command killed by a signal gives `128 + signal` (the shell's own status).
  A window killed from elsewhere gives 129 (the trap); a missing status file (the tmux server died, or the wrapper was killed with SIGKILL) gives exit 1 and a message.
- **Quoting.** The function passes each argument separately to `podman exec` (`"$@"`). `attach` builds one string for the window's shell command, with each argument quoted by `printf %q`, so spaces, quotes and `$` reach the command unchanged.
- **No terminal.** When standard output is not a terminal (`swarmbox pubkey > file`, `swarmbox cmd | less`), the function runs `podman exec` **without** `-t` (only `-i`; the same when only standard input is not a terminal, because `podman exec -t` needs both, 3.6 "3.5 state"), so the output has no CR/LF translation (measured: `a\nb\n` arrives byte for byte). A tmux client needs a terminal, so
  in that case `attach` runs the command directly (as `--plain` does) and its output and status are the command's own. **It does not use `bash -ic` for this**: an interactive bash without a terminal prints
  `bash: cannot set terminal process group (-1): Inappropriate ioctl for device` and `bash: no job control in this shell` on standard error (measured; its status is right). It runs
  `SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; . <the fragment>; eval "$1"' bash '<quoted command>'` instead, sourcing the fragment file `container/config/bashrc.sh` as installed in the image **directly, not through `/etc/bash.bashrc`** (Debian's `/etc/bash.bashrc` begins with `[ -z "$PS1" ] && return`, so a non-interactive shell leaves it at once: checked by reading the file in the image `[verified: head of /etc/bash.bashrc; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]`), and the fragment `container/config/bashrc.sh` opens with
  `case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return;; esac`, so an interactive shell is unchanged and a command run this way gets the aliases and the `PATH` additions with a clean standard error
  (measured with a stand-in fragment: alias, `PATH`, exit status 9 and an empty standard error). The real fragment, in a container from the image: `swarmbox-entrypoint attach alias fakeagent` printed the generated alias, `attach printenv PATH` began with the user shim directory, no banner appeared, and an empty standard error `[verified: tests/test_bashrc_container.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-s24a; reduced: nested Podman service off]`.
- `swarmbox --plain <command>` runs the command directly (no tmux) in the exec session, by the same non-interactive form when it has no terminal and through `bash -ic` when it has one.
- A command that has the same name as a host-handled word cannot be run this way; run it with `swarmbox bash -c '<command>'`.
- What the spike showed (B13): the call returns when the command ends, with its exit code (0, 1, 130, 7, 127 for a missing command, 137 and 143 for SIGKILL and SIGTERM), in about 7 ms for `true`; 17 awkward
  arguments (space, both quotes, `$`, backslash, glob, newline, an empty argument, `-n`, `~`, a backtick, `;`, `&`, `!`, a non-ASCII letter, a tab) arrived byte for byte and none ran as a command; an alias and a `PATH`
  addition of an interactive-only fragment were in effect in the window, and not in a plain `bash -c` (the control); the grouped session ended by itself when the wait finished, with another window still open.
  What the product test (Phase 2) must still show: the same with the real `swarmbox-attach`, the real fragment and ttyd attached.
- **What the 2.3 implementation does and fixes** (`container/scripts/swarmbox-attach.sh`, tests `tests/test_attach_command.py` and `tests/test_attach_container.py`; decisions under [2.3] in `docs/decision-log.md`):
  - Interface: `swarmbox-attach [--plain] [--] [command [args...]]`; `swarmbox-entrypoint attach ...` forwards all its arguments (exit 127 when the program is missing). Readiness is waited for first, in every mode (60 s, exit 6, message "the box is not ready; run `podman logs <name>` on the host", the name from `SWARMBOX_NAME`, default `swarmbox`).
  - Modes: a command **and** a terminal on both standard input and output gives the tmux mechanism; no terminal, or `--plain`, or no `tmux` gives the direct forms; no command with a terminal is the grouped session; no command and no terminal, or `--plain` alone, is a plain `bash` (interactive only with a terminal).
  - The wrapper runs `bash -ic` as a **background** job and `wait`s for it (a foreground child would delay the HUP/TERM trap until the child ended), and hands the terminal's standard input to that job explicitly (`exec 3<&0 ... <&3`): a background job of a non-interactive shell would otherwise read `/dev/null`. Measured with real tmux: a command that does `read` receives what is typed.
  - The waiter blocks on `tmux wait-for <channel>` as a background child and checks, every `SWARMBOX_TEST_POLL_INTERVAL` seconds (1 by default), whether the window id is still listed and whether the grouped client is alive. A window that is gone with no status file, after a 1 s grace for a status that is on its way, gives exit 1 and "the command's status is lost". If only the **client** ended (the user detached with the command still running), the call prints "detached; the command keeps running in window <id>" and exits 0.
  - The grouped client of a command is started with a name (`swarmbox-cmd-<id>`) so that it can be ended with `kill-session -t =<name>`; `=` makes the match exact (a prefix match could hit `main-1`). A SIGHUP or SIGTERM to the call ends the client and leaves the command window running.
  - **The command path does not close the idle window** (decision [2.3]): when the command ends its window closes, and with the idle window gone `main` would have no window and tmux would end the session and the server, so the browser's `tmux attach -t main` would fail. Only the interactive path closes it.
  - The no-terminal form is `SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; [ -r "$2" ] && . "$2"; unset SWARMBOX_CMD; eval -- "$1"' bash '<quoted command>' <fragment>`: `eval --` because a command that begins with `-` made `eval` itself fail with status 2 (found by the test), and `unset SWARMBOX_CMD` so that the command does not inherit the switch. A missing fragment file is not an error (it is `/etc/swarmbox/bashrc.sh` in the image; the fragment was built in slice 2.4, see 6.6).
  - **Requirement for the fragment slice:** the command window runs an interactive shell, so the banner and the other interactive output of `container/config/bashrc.sh` must be skipped when the shell was started with `-c` (`[ -n "${BASH_EXECUTION_STRING:-}" ]`), or every `swarmbox <command>` would print the banner before its own output. The real fragment does this (6.6).
  - Found while writing the container test: when the host-side `podman exec -it` is killed (a closed terminal, SIGHUP to the client), the tmux client inside the box keeps running with its grouped session `[verified: tests/test_attach_container.py probe; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-s23a]`; leaving by the detach key ends it normally. The same `podman exec` mechanism is used today `[today]`, but v0.1.0 was not run to compare `[unverified]`. A cleaner cleanup (for example a reaper in `serve`) is not part of 2.0 and is listed in the decision log.

One entrypoint name is used everywhere: `box:/usr/local/bin/swarmbox-entrypoint` (source `container/entrypoint.sh`). `attach` is a **subcommand** of it;
the program that implements it is `swarmbox-attach` (9.3). Inside a running box the host function only ever calls `swarmbox-entrypoint` (through `podman exec`);
before a box exists it runs the same program as the image's entry point (`podman run --rm <image> host-helper`, `init`, `serve`; 3.6, 10.2).

### 3.4 One session for every entry point

- The first `swarmbox` creates a container named `swarmbox`, detached, and enters it.
- `serve` creates the session `main` with **one idle window** (step 9 of 4.1), so the session exists before the first tab. Entering adds a new window and, when the only other window is that idle one, closes the idle window
  (v0.1.0's `attach-session.sh` instead reuses the session's first window for the first tab `[today]`); the idle window is recognized by its **name**, `idle` (`serve` creates it with `tmux new-session -d -s main -n idle`, which also fixes the name against automatic renaming): it is closed only when it is the only window of the session, still named `idle`, has one pane, and that pane's current command is a shell (bash, zsh, sh, dash or fish). A window the user typed a command into (`vim`, `sleep`), split or renamed is therefore never closed `[verified: tests/test_attach_command.py and tests/test_attach_container.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); tmux 3.3a; swarmbox-test-img-s23a]` (B36). A user who typed text without pressing Enter, or ran a command that already finished, is not detected: the window is closed, which is the cost of the rule `[unverified: not decided by anything but the name and the shell test]`. Only the interactive path closes it; the command path leaves it (3.3).
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
- **Host-side state of the helper**: `host:~/.local/state/swarmbox/` holds the `up` lock folders (3.7.2), the file `notices` (3.7.5) and, only when the workspace path is long, the symlink `<name>.sock-dir` to the workspace's state folder (the short-path fallback of the socket, 3.5 and 3.7.2; B5). They are small and safe to delete when no `swarmbox` command is running.
- **Files regenerated at every start**: `box:/tmp/swarmbox/` (the assembled web page, the OpenCode config, locks, the readiness marker). It is a memory-backed
  folder (`--tmpfs`, 3.6) that is empty at every start. These files are not in the workspace so they do not clutter it or a backup; a reset or a stop discards them and the next start recreates them.
- **The container's own filesystem**: anything installed with `apt` or written to `box:/usr`, `box:/etc`, `box:/opt`, plus running
  processes and tmux sessions. A `reset` discards them (6.11).

Two things to watch with this layout:
- Cache directories of other programs under `<workspace>/.cache` (for example pip's, Go's build cache) also live in the workspace and keep growing; they
  are safe to delete. SwarmBox itself keeps nothing there.
- The host reaches nested Podman through a unix socket (`podman -c <name>`). Today it is `<workspace>/.swarmbox/podman.sock`; with the XDG
  layout it is `<workspace>/.local/state/swarmbox/podman.sock`, 12 characters longer. A unix socket path holds at most **107 characters**
  (`sun_path` is 108 bytes including the terminating NUL; the same on a tmpfs and on disk, and inside a container); a 108-character path is refused by
  `bind()` and `connect()`, and `podman -c` then fails with `connect: invalid argument`. The default `host:~/swarmbox` (about 54 characters
  for `/home/alice/swarmbox`) is far from that limit. **The fallback rule:** the helper measures the host-side path of the socket (the workspace
  path plus `/.local/state/swarmbox/podman.sock`, 34 characters, so the workspace path itself may have 66) and, **when it is longer than 100 characters**
  (the limit minus a margin, because macOS and the BSDs allow only 104 bytes), connects through a short symlink instead: the helper creates
  `host:~/.local/state/swarmbox/<name>.sock-dir` pointing at the folder `<workspace>/.local/state/swarmbox/` (a symlink to the folder, so the
  service inside the box still binds its own short container path and nothing in the box changes) and registers the connection with
  `<that link>/podman.sock`. Measured: the service bound the container path (45 characters) while the host path was 131, the host connected through
  the 45-character symlink path, and the path through the symlink is what counts, not where it leads. If even the symlink path is longer than 100 characters, `up`
  exits 4 with "swarmbox: cannot make a short path to the Podman socket". `[verified: spike_b5_socket_len.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); python:3.11-slim-bookworm; reduced: a Python stand-in for the nested Podman service, no macOS]` (B5). The connection is registered on Linux and WSL only; unix sockets do not cross the macOS VM.

#### Edge cases `[new]`

| Case | Behavior |
|---|---|
| `WORKSPACE` is changed in the config while a box exists | Nothing moves and nothing is deleted. The box keeps its old mount. The fingerprint (3.7.4) differs, so every entry prints "the workspace in the config is X, this box uses Y; run `swarmbox reset` to switch". The old folder is left as it is. |
| The workspace folder is missing | Created at the first start, with one message. A missing parent folder is created too. |
| The workspace is not writable by you | The helper stops before creating the box: exit 4, "swarmbox: workspace X is not writable by this user". `serve` checks again inside the box and stops if it cannot write (4.1). |
| macOS: the workspace is outside the folders shared with the Podman machine | The mount would be empty or refused. The helper checks with a throwaway container that mounts the folder and writes one file, and stops with exit 4 and the message "swarmbox: X is not shared with the Podman machine; choose a folder under your home or share it with `podman machine`". `[unverified]` (B6). |
| The workspace is already used by another box | Before creating a box, the helper looks for any container with the label `swarmbox.workspace` equal to this path and a different name; if one exists it stops with exit 5, "swarmbox: workspace X is already used by box 'other'". Two boxes on one home would share `.claude`, the SSH key and the tool installs. v0.1.0 containers have no labels and are not found by this check (3.8 covers them). |
| WSL2: the workspace is on a Windows drive (D34) | A workspace path under `/mnt/<letter>/` (for example `/mnt/c/Users/me/swarmbox`) is refused by `up` and `create-flags` before anything is created: exit 4, "swarmbox: workspace X is on a Windows drive; WSL2 is supported only with the workspace on the Linux filesystem (for example ~/swarmbox)". Permissions, ownership and `keep-id` do not behave on a Windows drive. The helper reads `/proc/version` (a kernel string with `microsoft`, any case, means WSL), refuses `/mnt/<one letter>` and `/mnt/<one letter>/...` (either case of the letter), also when a symlink on the way or the real path of an existing folder lands there, and does not refuse `/mnt/wsl`, `/mnt/data` or a Linux path on a machine that is not WSL: [verified: tests/test_host_create_flags.py WorkspaceTest; 2026-11-08; no Podman involved, Debian 12 (bookworm) host; no image; reduced: a fake /proc/version and fake paths, never a real WSL or a real Windows drive] (B32, slice 3.2). That the real WSL mounts are exactly these paths, and that a real WSL machine behaves so, is `[unverified]` (Phase 6). |
| Creation fails (a published port is in use on the host, for example 7681; Podman rejects an option) | `podman run` fails. `up` removes **only the container this call created**, found by the ID that `podman run --cidfile` wrote (Podman does leave it in state `Created` when the failure is a port in use, and the cidfile then holds its full ID: `[verified: spike tests/spikes/spike_b18_port_in_use.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` B18; that the same holds for other failures is `[unverified]` B33); a container that merely has the box's name and was not created by this call is never removed (measured: `podman run --name X` when X exists exits 125, writes no cidfile and leaves the old container running, so there is nothing to remove). `podman run` exits 126 for the busy port, with `Error: rootlessport listen tcp 127.0.0.1:<port>: bind: address already in use` on standard error, and exits 125 when the `--cidfile` path already exists (`container id file exists`), so each call uses a fresh path (the code in 3.6 does). It prints the message of 3.8 ("could not create the box") and exits 7. The configuration is not changed: fix the cause, for example with `swarmbox config set WEB_PORT 7682`, and run `swarmbox` again. The workspace and the volume `<name>-containers` are untouched. |
| Second box | A box is a name: `SWARMBOX_NAME=other` (with its own `SWARMBOX_WORKSPACE` and `SWARMBOX_WEB_PORT`) in the terminal that runs `swarmbox`. `config` and `env` act on the config file of that name, so the variable list and the fingerprint refer to the right box. The config of a second box is `host:~/.config/swarmbox/<name>/config`; the default box keeps `host:~/.config/swarmbox/config` (D31). A throwaway `--once` mode is not in 2.0: a second box is the way to get another container (D19). |

### 3.6 The generated function

What `init` prints for bash, shown as shipped (`container/host/templates/bash` with the placeholders filled in for `init --with claude`; the zsh and fish variants have the same shape and are
described after it). It stays thin: anything with more than a few lines is in the host helper (3.7). Status: `[new]`.

```bash
# >>> swarmbox 2.0.0 >>>
swarmbox() {
  local dir host name tmp hv="" lowest="" msg="" last="" prc=0 need=0 skew=0
  local -a sa pe
  local version='2.0.0'
  local image='ghcr.io/<org>/swarmbox:2.0.0'
  local seed_with='claude' seed_ws='' seed_image=''   # seed values of `swarmbox init` (design 3.7.5)
  dir=${XDG_DATA_HOME:-$HOME/.local/share}
  case $dir in /*) ;; *) dir=$HOME/.local/share ;; esac
  dir=$dir/swarmbox/host
  host=$dir/swarmbox-host
  # the helper's version; empty when it is missing, not executable, or prints something that is not a version
  if [ -x "$host" ]; then
    hv=$("$host" version 2>/dev/null | head -n 1)
    case $hv in
      *[!0-9A-Za-z.+-]*) hv="" ;;
      [0-9]*.[0-9]*.[0-9]*) ;;
      *) hv="" ;;
    esac
  fi
  # bootstrap (D33): extract only when there is no usable helper or it is older than this block (sort -V: 2.0.10 is newer than
  # 2.0.9); a newer helper is kept with a one-line notice; when sort has no -V there is no answer and the helper is kept
  if [ -z "$hv" ]; then
    need=1
  elif [ "$hv" != "$version" ]; then
    lowest=$(printf '%s\n%s\n' "$hv" "$version" | sort -V 2>/dev/null | head -n 1)
    if [ -n "$lowest" ]; then
      if [ "$lowest" = "$hv" ]; then need=1; else skew=1; fi
    fi
  fi
  if [ "$need" = 1 ]; then
    if ! command -v podman >/dev/null 2>&1; then
      echo "swarmbox: Podman is not installed." >&2
      echo "Linux: sudo apt install podman (Debian/Ubuntu) or sudo dnf install podman (Fedora/RHEL)" >&2
      echo "macOS: brew install podman" >&2
      return 3
    fi
    mkdir -p "${dir%/*}" 2>/dev/null && tmp=$(mktemp -d "$dir.new.XXXXXX" 2>/dev/null) && [ -d "$tmp" ] || {
      echo "swarmbox: cannot make a temporary folder next to $dir." >&2
      return 3
    }
    # no pipe: a pipe's status is the last command's, and pipefail is not in bash 3.2, zsh or fish. The archive goes to a file, is
    # unpacked, and the result is tested.
    if command podman run --rm "$image" host-helper > "$tmp/helper.tar" 2> "$tmp/podman.err"; then
      if tar -x -C "$tmp" -f "$tmp/helper.tar" >/dev/null 2>&1 && [ -x "$tmp/swarmbox-host" ]; then
        msg=""
      else
        msg="the image has no usable host helper"
      fi
    else
      prc=$?
      last=$(tail -n 1 "$tmp/podman.err" 2>/dev/null)
      msg=${last:-"podman exited with status $prc"}
    fi
    if [ -n "$msg" ]; then
      rm -rf "$tmp"
      echo "swarmbox: cannot pull $image: $msg. Check the network, or set SWARMBOX_IMAGE to an image you already have." >&2
      return 3
    fi
    rm -f "$tmp/helper.tar" "$tmp/podman.err"
    rm -rf "$dir.old"
    if [ -e "$dir" ] || [ -L "$dir" ]; then
      mv "$dir" "$dir.old" || { rm -rf "$tmp"; echo "swarmbox: cannot replace the helper in $dir." >&2; return 3; }
    fi
    if ! mv "$tmp" "$dir"; then
      mv "$dir.old" "$dir" 2>/dev/null
      rm -rf "$tmp"
      echo "swarmbox: cannot replace the helper in $dir." >&2
      return 3
    fi
    rm -rf "$dir.old"
  elif [ "$skew" = 1 ]; then
    echo "swarmbox: the helper ($hv) is newer than this function ($version); kept" >&2
  fi
  # seeds (D20, 3.7.5): given as arguments, never as SWARMBOX_* variables (those would override the file on every call); a relative
  # workspace is made absolute here, on the host, against the folder of this call
  case $seed_ws in ""|/*|"~"|"~/"*) ;; *) seed_ws=$(pwd)/${seed_ws#./} ;; esac
  sa=(config seed)
  [ -n "$seed_with" ] && sa=("${sa[@]}" --with "$seed_with")
  [ -n "$seed_ws" ] && sa=("${sa[@]}" --workspace "$seed_ws")
  [ -n "$seed_image" ] && sa=("${sa[@]}" --image "$seed_image")
  if [ "${#sa[@]}" -gt 2 ]; then
    "$host" "${sa[@]}" || return $?
  fi
  case "${1-}" in                                   # words handled on the host (3.3)
    stop|reset|up|url|update|config|env|remote|fingerprint|version) "$host" "$@"; return $? ;;
  esac
  "$host" up || return $?                           # create if needed, start, check, wait until ready
  name=$("$host" config get NAME) || return $?
  pe=(exec -i)
  if [ -t 0 ] && [ -t 1 ]; then pe=(exec -it); fi   # -t only with a terminal on both ends (3.3, "No terminal")
  pe=("${pe[@]}" -e TERM -e COLORTERM "$name" swarmbox-entrypoint)
  case "${1-}" in                                   # words forwarded as they are (3.3)
    pubkey|tool) command podman "${pe[@]}" "$@"; return $? ;;
    attach) shift ;;                                # a leading "attach" is a prefix, not an argument
  esac
  command podman "${pe[@]}" attach "$@"             # nothing, --plain, or any other command; the status is the command's
  return $?
}
# <<< swarmbox 2.0.0 <<<
```

**3.5 state (what the shipped function does and where it differs from the earlier sketch; decision log `[3.5]`).** The text above is the real template. The bootstrap block runs before the helper exists, so it can use only `podman`, `tar`, `mktemp`, `mv`, `rm`, `printf`, `sort`, `head` and `tail`; the image reference
it uses is the seed value embedded in the block, because the configuration file does not exist yet (it never reads `IMAGE`; the helper's `up` does, D17). `<org>` stands for the registry organization,
a placeholder until the name and license are settled (D32, 10.4). The helper's `version` subcommand (3.7.2) prints the version of the image it was extracted from.
- **zsh** (`templates/zsh`) is the bash text with one more line, `emulate -L zsh`, as the first line of the function: the user's `KSH_ARRAYS`, `SH_WORD_SPLIT` and `NO_UNSET` cannot change what it does. **fish** (`templates/fish`) is written in fish: `set -l` variables, lists instead of arrays, `test -t`, `string match` for the version shape, and `$status` returned explicitly; it keeps the same order of steps and the same messages. A case table (`tests/function_cases.py`) drives all three, plus `bash --posix`, with the same expectations.
- **Where the helper lives.** `${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox/host`; a relative `XDG_DATA_HOME` is ignored, as everywhere else in the host side.
- **The version probe.** The function runs `<helper> version` once per call and keeps only a first line made of `[0-9A-Za-z.+-]` that has the shape `X.Y.Z`; anything else counts as "no version" and re-extracts. If `sort -V` gives no answer (an old `sort`), the helper is kept and nothing is printed: it never claims "newer" without having compared.
- **`config seed` only with seeds.** The call is made only when the block holds at least one seed (`--with`, `--workspace` or `--image` was given to `init`), in the order with, workspace, image. A relative workspace is made absolute against `$(pwd)`; `~` and `~/...` pass unchanged (the helper expands them against `HOME`; the first sketch would have turned `~/x` into `<cwd>/~/x`).
- **Terminal.** `-t` is added only when standard input **and** standard output are terminals (`podman exec -t` fails with "the input device is not a TTY" when stdin is a pipe, and `swarmbox pubkey > file` typed at a prompt must have no CR/LF translation: 3.3). 3.3 said "output only"; the stricter rule is the one that works for every combination.
- **Errors.** The function never uses `set -e`, a pipe status or an option of the user's shell. A failed extraction prints ``swarmbox: cannot pull <image>: <last line of Podman's message, or "podman exited with status N", or "the image has no usable host helper">. Check the network, or set SWARMBOX_IMAGE to an image you already have.`` and returns 3; the temporary folder is removed and the previous helper is left; if the last `mv` fails the previous folder is moved back.
- Host words in the function are `stop reset up url update config env remote fingerprint version` (the table of 3.3 plus `fingerprint` and `version`); `connection` is not routed (it is the helper's own step 6, run by `up`).
- Not checked here: macOS `/bin/bash` 3.2 (the template passes `bash --posix` and a lint that rejects bash 4 constructs, which is only a guard), arm64, and a real `podman exec -t` attach to a box (the pty tests prove the arguments, not the terminal).

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
and takes the fast path. That `mkdir` is atomic on the supported hosts, that the stale rule never removes a live lock, and that `--cidfile` is written when `podman run` fails after creating the container are `[verified: tests/test_host_up.py LockTest (eight real processes at once for ten rounds, SIGTERM, SIGINT, SIGKILL, stale by dead pid and by missing pid file, a live holder never removed) and tests/smoke_image.py up-busy-port (a real busy port: the cidfile held the ID, `podman rm -f <id>` removed the container, a container with the box's name was untouched); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-3-img (dev build of the 2.0 Dockerfile); reduced: development box, fake podman for the races, no macOS]` (B33). Failures other than a busy port (a rejected option) take the same code path, but only the busy port was run for real `[unverified]`. The 3.3 implementation differs in details from this sketch (3.7.2, "3.3 state"): the stale lock is renamed and re-read before it is deleted, `create-flags` is a program run in the background, and the signals end the call with 129, 130 and 143.

- `create-flags` prints one argument per line for every creation-time setting (8): the workspace mount, `--hostname`, `--tz`, `--init` (only when the resolved `INIT` is 1: `up` resolves `auto` to 0 or 1 and passes the resolved value, so `create-flags` stays a pure function and starts no container),
  `--pids-limit=16384`, a `-p` per published port (the user's `PORTS`, plus the ports that `tool-ports` lists for each tool in `WITH`: 6.3), the memory-backed folder for the
  regenerated files (`--tmpfs /tmp/swarmbox`, so the readiness marker cannot survive a restart: 4.1 step 0, 4.2), the nested-Podman flags (always: `--device /dev/net/tun`,
  `--security-opt unmask=/proc/*`, `-v <name>-containers:/home/agent/.local/share/containers`), `-e SWARMBOX_<KEY>=value` for every non-secret
  key the box reads (8.1), `-e NAME` per listed variable (7), the labels (3.7.4), and the user namespace. On macOS it adds
  `--security-opt label=disable` (and nothing else: the `keep-id` line stays `uid=1000,gid=1000` because the image's user is fixed; decision `[3.2]`; the switch for tests is `SWARMBOX_TEST_OS=Darwin`). Among them, `--userns=keep-id:uid=1000,gid=1000` maps the host
  user to the image's fixed user (UID 1000), so one image serves every host UID. The agent user must not be root: Claude Code refuses auto-approve
  as root. `[verified: spike_b12_keepid.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; reduced: the host UID is 1000, so only a same-UID mapping ran]`: `podman run` accepted the option; inside, the process is uid 1000 and gid 1000
  and the uid map sends container uid 1000 alone to the invoking user; a file written there is owned by the host user. `podman inspect` reports the mode as `private`, not `keep-id`, on Podman 4.3.1, so a test must read `/proc/self/uid_map`, not the
  inspect field. A host UID other than 1000 has not been tested `[unverified]` (B7). Today the image is built with the host UID instead (`start.sh` and `build.sh`, `[today]`).
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
  | `VERSION` | one line `X.Y.Z`: the version of the image the helper was extracted from. `swarmbox-host version` prints it; a missing or malformed `VERSION` makes every command exit 3 (a corrupted archive). In the repository it is `container/host/VERSION` (`2.0.0` until a release sets it from the tag, Phase 7); the helper reads it from the folder it runs from (decision [3.1]) |
  | `cloudflare-setup.py` | the Cloudflare script that `swarmbox remote` runs (5.2) |
  | `templates/` | the function templates for bash, zsh and fish (the same files `init` prints from, 3.7.5) |
  | `tool-ports` | one line `<tool><TAB><port>` per port that an image-level tool manifest declares with `PORTS` (6.3). Generated at image build by `swarmbox-tool link --system`, so the host can add a tool's ports at creation without reading the image. The build **always** writes it, as an empty file when no manifest declares ports; so a missing `tool-ports` means a corrupted or incomplete helper archive (exit 3), never a normal state |
- Language (D16): POSIX `sh` for everything except `remote`, which stays Python as `cloudflare-setup.py` and is the only place that needs `python3` on the host (3.8). That the
  helper runs unchanged under dash, `bash --posix`, busybox `sh`, zsh in `sh` emulation and the system `/bin/sh` of Debian is `[verified: tests/test_host_shells.py; 2026-11-08; no Podman involved, Debian 12 (bookworm) host with dash 0.5.12, bash 5.2.15, busybox 1.35.0, zsh 5.9; no image]` (B23, slice 3.1); that it runs under macOS's `/bin/sh` (bash 3.2 in POSIX mode) is `[unverified]` (Phase 6).
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
| `connection` | none | the registered URI `unix://<path>` (step 6 of `up` on its own; nothing on macOS) | 0; 4 workspace too deep for a short socket path, or something that is not a symlink at `<name>.sock-dir` (3.5) |
| `url` | none | the local URL, and the public one when configured (two lines) | 0; 1 when the web terminal is off (`WEB=0`) |
| `up` | none | nothing | 0 ready; 3 prerequisite or network; 4 workspace (not writable, not shared with the Podman machine, on a Windows drive under WSL (D34), or a workspace path so long that no short socket path can be made, 3.5); 5 conflict with another box or a v0.1.0 container (3.8); 6 not ready after 60 s, or the box exited while waiting (`up` only: it also reads the container state and prints `podman logs --tail`, 4.2), or another `up` held the lock for more than 90 s; 7 creation failed (3.8) |
| `update [--to TAG]` | `--to TAG` or `--to=TAG` | one line, `updated to X.Y.Z; run `swarmbox reset` to use it (running sessions end)`; "pulling ..." on standard error | 0; 2 invalid tag, an `IMAGE` with no series for a plain `update`, usage; 3 pull failed, no usable helper or version in the image, or the local tag could not be created (nothing changed); 1 the config could not be written (after the helper was replaced) (3.8) |
| `reset` | none | nothing | the codes of `up`: 0 ready; 3, 4, 5, 6, 7 as in `up`; 1 if removing the old container failed. Exit 5 also when the container exists without the label `swarmbox.managed` (see below) |
| `stop` | none | nothing | 0 (also when there is no such box); 1 podman failed; 5 the container with that name was not made by this design (3.3 state) |
| `remote setup\|status\|off\|token` | options of 5.2 | as `cloudflare-setup.py` | 0; the script's code; 3 if `python3` is missing |

**3.1 state (the configuration surface).** `container/host/swarmbox-host` implements `version`, `config get|set|list|seed` and `env add|rm|list` and nothing that touches Podman; `remote` prints "not implemented in this build" and exits 70 until its slice (`update` since 3.6) (`create-flags` and `fingerprint` since 3.2, `up`, `reset`, `stop` and `url` since 3.3, below). Details the table leaves open, decided in slice 3.1 (decision log `[3.1]`):
- `config list` prints `KEY=VALUE<TAB>source` for `NAME` and every key of the file in the order of 8.2, 16 lines; a key with no default has an empty value and source `default`; the token is `set` or `unset`, never the value. `config get` prints the token's value (the remote script needs it) when it comes from the environment or from a file with mode 600; exit 1 and no output for an unset key, and for the token when the file mode is not 600.
- An empty environment value does not override: precedence looks at non-empty values only (as the file does).
- `config set` writes nothing and exits 1 when `chmod 600` on the temporary file fails, for every key, not only for the token (the token message says so); the new file replaces the old one by `mv`, so a symlinked config is replaced by a regular file. A relative or `~/` `WORKSPACE` is made absolute at `set` and at `seed` (against the current directory); a trailing slash is dropped; a `:` in the path is refused (it would break `-v`).
- `config seed` prints, on standard error, `swarmbox: WORKSPACE recorded as <absolute path>` when it records a workspace; its standard output stays empty (the table's rule). The notice of 3.7.5 compares the seed with the file's value, or the default when the file has no line for the key, and ignores the environment.
- The box name (`SWARMBOX_NAME`) must start with a letter or digit, use letters, digits, `.`, `_` and `-`, and not be `config`: the default box keeps its file at `<config>/config`, so a second box named `config` would need a folder with the same name (exit 2).
- A config file that is not readable exits 1 with one message.

**3.2 state (`create-flags` and `fingerprint`).** Nothing here calls Podman. Details the table leaves open, decided in slice 3.2 (decision log `[3.2]`):
- `create-flags [--browser-url VALUE]` prints, one argument per line and in this order: `--userns=keep-id:uid=1000,gid=1000`, `--pids-limit=16384`, `--security-opt` `label=disable` (macOS only), `--hostname` `<h>`, `-v` `<workspace>:/home/agent`, `--init` (only when `INIT` is 1), `--tz=<zone>` (`local` needs the host's local time file, `SWARMBOX_LOCALTIME_FILE` or `/etc/localtime`; without it no `--tz` and a warning; `off` gives none), `--tmpfs` `/tmp/swarmbox`, `--device` `/dev/net/tun`, `--security-opt` `unmask=/proc/*`, `-v` `<name>-containers:/home/agent/.local/share/containers`, `--add-host` `host.containers.internal:host-gateway` (only with `HOST_ACCESS=1`), one `-p` per user port then per tool port, `-p 127.0.0.1:<WEB_PORT>:7681` (only with `WEB=1`), `-e` `<NAME>` for each `ENV_KEYS` name that is set (the value is never in the output: Podman reads it from its own environment), then `-e SWARMBOX_NAME=<name>`, `SWARMBOX_WEB`, `SWARMBOX_YOLO` (always) and `SWARMBOX_WITH`, `SWARMBOX_AGENT`, `SWARMBOX_BROWSER_URL` (when not empty), then the six labels. A flag and its value are two lines (`-p`, then the mapping), except the flags written with `=`. The image and `serve` are not part of it: `up` adds them (3.6). The golden files are `tests/fixtures/create-flags.default.golden` and `create-flags.full.golden`.
- `INIT=auto` is exit 2 (`up` resolves it); the environment values are validated by the same rules as `config set` (exit 2 names the rule); a stricter address rule applies to `PORTS` since 3.2 (four numbers from 0 to 255). `--browser-url ''` (an empty value, given explicitly) means port 9222, the parity with `--remote-browser` without a value; there is no such form in the config (an empty `BROWSER_URL` is "none").
- Exit codes: 2 usage or invalid value, 3 no `tool-ports` (the message says to run `swarmbox update`), or neither `sha256sum` nor `shasum`; 4 workspace (WSL drive, not a folder, cannot be created, not writable), 70 if a line would be `--network...`, `--privileged` and the like (never built by any path: D7).
- A port the user already publishes (same host port, any address) is not added again from `tool-ports`; the same host port from two tools is added once. `swarmbox.ports` and the `PORTS` line of the fingerprint hold the normalized comma list `ADDRESS:HOST:CONTAINER` of the user's and the tools' ports (not the web port, which is `WEB_PORT`).
- `fingerprint [--explain] [--label NAME=VALUE]...` prints the hash (64 hex digits). The input is the sorted lines `KEY=value` of `AGENT`, `BROWSER_URL` (normalized), `ENV_KEYS` (names), `HOSTNAME`, `HOST_ACCESS`, `IMAGE`, `INIT`, `NAME`, `PORTS` (normalized, tools included), `TZ` (resolved: `local` without a local time file counts as `off`), `WEB`, `WEB_PORT`, `WITH`, `WORKSPACE` (absolute), `YOLO` and `env-hash=<hash>`; empty values are written as `KEY=`. `INIT` is the configured value (`auto` stays `auto`): at entry `up` must give it the value the box was created with (read from the inspect output), as it does for creation. With labels, exit 0 when `swarmbox.fingerprint` equals the hash and 1 when not; `--explain` adds lines in the wording of D30 for `swarmbox.image`, `swarmbox.workspace`, `swarmbox.ports` and `swarmbox.env-hash` when they differ, and, because the other keys have no label of their own, one generic line ("another creation setting changed...") when the hash differs and none of those explains it. Without labels it prints the hash and exits 0; `--explain` without labels is exit 5 (no box). Reading the labels from the box is `up`'s job.

**3.3 state (`up`, `reset`, `stop`, `url`).** Details the text below leaves open, decided in slice 3.3 (decision log `[3.3]`):
- **One lookup.** `podman container inspect --format '<f>' <name>` with `<f>` = `state|name|image ID|HostConfig.Init|swarmbox.managed|swarmbox.image|swarmbox.ports|swarmbox.env-hash|swarmbox.fingerprint|swarmbox.workspace` (the workspace last, because a path may hold `|`; a missing label prints empty). The box exists only if the printed name equals the box's name; a failure whose message says `no such container` means "no box"; any other failure of the call is exit 3. The fast path (a running box) makes **two** calls: that one, then `podman image inspect --format '{{.Id}}' <the box's image label>` for the stale-image comparison; nothing else (B35, measured in 3.7.2 step 4). The Podman version (`podman version --format '{{.Client.Version}}'`, compared as numbers, so 4.10 is newer than 4.3; an unreadable version is a warning, not a failure) and `/dev/net/tun` are checked only when the box is created or started, not on the fast path: a box that exists was made when they held, and the two calls are the budget.
- **Order of a creation**, all before anything is changed: Podman present (`command -v`; exit 3 with the install advice), the config validated (exit 2), the lock, the lookup; then the version (exit 3), `/dev/net/tun` (exit 3; macOS and `SWARMBOX_TEST_NO_NESTED=1` skip it), the image (`podman image exists`, else `podman pull -q`; a failure is exit 3 "cannot pull <image>: <last line>"), the workspace conflict (`podman ps -a --filter label=swarmbox.workspace=<path> --format '{{.Names}}'`; another name is exit 5), `INIT=auto` (the probe `podman run --rm --init --name <box>-init-probe-<pid> --entrypoint true <image>`: success is 1, failure is 0 with one warning), then `create-flags` run as a program with `SWARMBOX_INIT` set to the resolved value, its output captured in a file and its status checked (its exit code, 2, 3 or 4, is `up`'s; `podman run` is not reached), then `mkdir -p <workspace>/.local/share/containers` as the user, then `podman run -d --name <box> --cidfile <state>/cid.<pid> <flags> <image> serve`. The helper makes the mount point because, if Podman made it, `.local` and `.local/share` would be owned by the container's root and `serve` could not create its folders (found by the real throwaway box of slice 3.3).
- **A failed `podman run`** removes only the container whose full ID is in the cidfile (`podman rm -f <id>`, quiet, its own failure ignored), then prints `swarmbox: could not create the box:` with the last three lines of Podman's error (indented) and ``swarmbox: If a port is in use, change WEB_PORT or PORTS with `swarmbox config set`.``, and exits 7 (two messages, not one line as 3.8 shows). A failed `podman start` of a stopped box is also exit 7, removes nothing and says the box is still there.
- **Readiness.** `podman exec <name> cat /tmp/swarmbox/ready` (the content is the marker, `ok` or `warnings=<n>`; a count is repeated as one line), polled every second, 60 times. Only when the read fails is the state read (`podman container inspect --format '{{.State.Status}}'`): `running`, `created`, `configured`, `initialized` and `paused` keep waiting; anything else, or a failed read, is "gone", and `up` prints `swarmbox: the box exited while starting (state: X); the last lines of its log:` with `podman logs --tail 20`, and exits 6 at once. On timeout: ``swarmbox: the box did not become ready in 60 s; see `podman logs <name>` ``, exit 6.
- **The lock** is as in 3.6 with three differences. A stale lock is not removed with `rm -rf` at once (two waiters that both saw the dead pid could delete the lock that the first of them had just made): the folder is renamed (`mv`, atomic) to `up-<name>.lock.stale.<pid>`, the pid file in it is read again, and it is deleted only if that is still the dead pid (or still absent); otherwise it is put back. The residual window (a second `mkdir` between the rename and the put-back) is not closed `[unverified]`; it needs three calls inside a few microseconds. `HUP`, `INT` and `TERM` end the call with 129, 130 and 143 through an `EXIT` trap that removes the lock (only a lock this call made) and the temporary files of this call; `create-flags` and every pause run in the background and are waited for, so a signal acts at once (a foreground child would delay a trap until it ended). A call killed with `SIGKILL` leaves its lock (found stale by the dead pid) and its `flags.<pid>`, `cid.<pid>` and `err.<pid>` files; the next call removes them under the lock when their pid is gone. A pid that another process reused looks alive and keeps the lock until it ends (not handled).
- **Warnings** (never blocking, D30), on a running or a stopped box, one line each with the prefix `swarmbox:`: the lines of `fingerprint --explain` (3.2) for the labels `swarmbox.image`, `swarmbox.workspace`, `swarmbox.ports` and `swarmbox.env-hash`, or the generic line; and, when the box's image reference now points to another image ID, ``the image <ref> is newer than the one this box runs; run `swarmbox reset` to use it (running sessions end).`` With `INIT=auto` the fingerprint takes the value the box has (`HostConfig.Init`).
- **`reset`** captures and checks everything `up` would (version, tun, image, conflict, INIT, `create-flags`) **before** `podman rm -f <name>`: a workspace or prerequisite problem leaves the old box in place (the list below puts the removal first; the order here is safer, and for a good configuration the result is the same). If the removal fails: exit 1 and nothing is created. The volume and the workspace are not touched (no `podman volume` call exists in the helper).
- **`stop`** looks the box up by exact name first (Podman resolves ID prefixes): no box is a message and exit 0; a container without the label is the v0.1.0 message and exit 5; otherwise `podman stop <name>` (exit 1 if Podman fails). It takes no lock.
- **`url`** prints `http://127.0.0.1:<WEB_PORT>`, then `https://<host>` when `SWARMBOX_WEB_HOSTNAME` is set, or else `<name>.<domain>` for the domain of `SWARMBOX_WEB_DOMAIN` or of `cloudflare.json` (its `"domain"` line, read with `sed`; `cloudflare-setup.py` writes indented JSON). A host name or domain with a character other than letters, digits, `.` and `-` is ignored with a line. No Podman call exists in its code path.
- **Not in this slice.** Step 6 of "What `up` does" (the connection `podman -c <name>` and the short-symlink fallback of 3.5) was built in slice 3.4 (below); the call budget above excludes it (the connection step adds one `system connection list` on the fast path). The tests-only switches are `SWARMBOX_TEST_TUN`, `SWARMBOX_TEST_NAP`, `SWARMBOX_TEST_READY_TRIES`, `SWARMBOX_TEST_LOCK_TRIES`, `SWARMBOX_TEST_LOCK_PIDWAIT`, `SWARMBOX_TEST_CREATE_FLAGS` and `SWARMBOX_TEST_NO_NESTED`; the last one also removes `--device /dev/net/tun`, `--security-opt unmask=/proc/*` and `--hostname` from `create-flags` and passes `-e SWARMBOX_TEST_NO_NESTED=1` (the nested level of the development box has `utsns=host` and no tun, so the real throwaway box of the smoke test cannot take them).

**3.4 state (the host connection).** Decided in slice 3.4 (decision log `[3.4]`):
- **Subcommand.** `swarmbox-host connection` runs step 6 on its own (no lock, no box, no Podman service needed) and prints the registered URI (`unix://<path>`); on macOS it prints nothing and exits 0. `up` and `reset` call the same code.
- **Measure.** The path is counted in **bytes** (`wc -c`, the same in every locale), because `sun_path` is 108 bytes: 100 bytes is registered directly, 101 gets the symlink, and a workspace name with multibyte characters counts each byte. The link is `<STATE_DIR>/<name>.sock-dir` (`STATE_DIR` follows `XDG_STATE_HOME`, as every other host-side file); the rule is purely length-based, so the default workspace never gets a link unless `HOME` itself is longer than the limit allows.
- **Link.** A correct symlink stays; a symlink with another target (or a dangling one) is replaced; anything else at that path (a file or a folder) is refused with exit 4 and left where it is. An old link is left alone when the path is short again. The link is made before a box is created (so a workspace too deep exits 4 before any `podman run`), and checked again at the end.
- **Registration.** Only the connection named like the box is read, replaced or removed: one `podman system connection list --format '{{.Name}} {{.URI}}'`, nothing more when the address is the same, otherwise `remove <name>` (when it exists) and `add <name> unix://<path>`. A failed list or add is one warning and the exit code is unchanged (the box works without the connection). The tests run it with `CONTAINERS_CONF`, `XDG_CONFIG_HOME` and `HOME` in a mktemp folder.
- `[verified: tests/test_host_socket.py (27 tests: 100 bytes direct, 101 symlink, over-limit exit 4 with the 3.8 text, the default workspace, UTF-8 names, link refresh and refusal, idempotence, the v0.1.0 address replaced, a foreign connection kept, the real `podman system connection` in an isolated config, a stand-in socket server in a throwaway container reached through the helper's link for a 131-character workspace, the isolation guard on the real files and the real connection list); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); python:3.11-slim-bookworm; reduced: no real nested Podman service, no macOS, no arm64]` (B5).

**What `up` does** `[new]`, in order:
1. Prerequisite and workspace checks (3.8), including the refusal of a workspace under `/mnt/<letter>/` on WSL (D34).
2. Take the host lock (3.6): an atomic `mkdir` of `host:~/.local/state/swarmbox/up-<name>.lock`, removed on every exit, with the stale-lock rule of 3.6.
3. **Find the box with an exact name match.** One `podman container inspect --format '<state>|<name>|<labels>' <name>` gives the state and the labels (`swarmbox.managed`, `swarmbox.image`, the fingerprint inputs) together, and the helper
   compares the printed name with the box's name, because Podman also resolves ID prefixes. The helper never uses `podman ps -a -q -f name=<name>`: that filter matches substrings, and v0.1.0 uses it (`start.sh` around lines 395 and 443 `[today]`),
   so `swarmbox` would match `swarmbox-cloudflared`. Where a listing is needed it uses `podman container exists <name>` or a filter anchored as `^<name>$`.
4. **Fast path: the box exists and is running.** Nothing else is called: the labels from step 3 give the fingerprint, image and workspace comparison (3.7.4), the warnings are printed, the lock is released and the function enters; `attach` itself waits for the
   readiness marker inside the box (4.2). The budget is at most two Podman calls before the function attaches (the inspect, plus at most one more); slice 3.3 uses both, for the inspect and the image-ID comparison, and measured two calls, 0.09 s, against 0.11 s for one `podman exec <box> true` `[verified: tests/test_host_up.py FastPathTest (fake podman: at most 2 calls, one inspect, no run) and tests/smoke_image.py up-lifecycle (a recording wrapper around the real podman); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-3-img (dev build of the 2.0 Dockerfile); reduced: development box, no nested Podman in the box, the connection step of item 6 not built yet]` (B35).
5. A stopped box is started (`podman start`) and waited for. A missing box is created: `INIT=auto` is resolved to 0 or 1 here (today's `start.sh` detects `--init` support by running a throwaway container, around line 386 `[today]`), the flags are captured and
   checked (3.6), `podman run -d --cidfile` creates it, and `up` waits for the marker (4.2). A v0.1.0 container or a box of another workspace stops `up` with exit 5 (3.5, 3.8).
6. **The connection (Linux and WSL).** The helper measures the host-side socket path. At most 100 characters: it registers `podman -c <name>` with that path. Longer: it creates or refreshes the symlink `host:~/.local/state/swarmbox/<name>.sock-dir` to `<workspace>/.local/state/swarmbox/` and registers `<that link>/podman.sock`; if that path is still over 100 characters, it exits 4 with the message of 3.8 (3.5, B5). The same comparison and re-registration as in 12.4 applies when the address changes. Built in slice 3.4 (the `3.4 state` paragraph below); it runs last, under the lock, after the box is ready (and on the fast path too, where it costs one `podman system connection list` call, B35).
7. The lock is released on exit, whatever the exit.

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
  ("the config file holds the tunnel token but its mode is X; run `chmod 600 <file>`") and goes on without it. On Linux this is checked: the token is ignored with the one-line message for every mode other than 600 (640, 644, 666, 400, 700, 601, with the setuid and sticky bits too), `config set` refuses to write when `chmod` fails, and the typed token never reaches the terminal, `argv` or the output `[verified: tests/test_host_config.py TokenTest and ModeCheckTest; 2026-11-08; no Podman involved, Debian 12 (bookworm) host; no image]` (B22, Linux part, slice 3.1). Whether it holds on macOS and a WSL home on a Windows drive is `[unverified]` (Phase 6). The token is read with `stty -echo` after `stty -g` and restored on every exit path (a `trap` on INT, TERM and HUP); standard input must be a terminal, or the command exits 2 (decision `[3.1]`).
  **The mode check does not parse a directory listing** (the text of `ls`; macOS prints `-rw-------@` when the file has extended attributes, so a text comparison would fail): the helper reads the mode as an octal number, with `stat -c %a` on Linux, `stat -f %Lp` on macOS, or, where neither works,
  `find <file> -perm 600` combined with a test for any other permission bit. On Linux the three forms give the same answer for modes 600, 644, 640, 400, 666, 4755 and 1777 (the `find` form also for 2755, 7777 and 1600), for a file with an extended attribute, and with a fake `ls` that prints `-rw-------@` (never called) `[verified: tests/test_host_config.py ModeCheckTest; 2026-11-08; no Podman involved, Debian 12 (bookworm) host; no image]` (B34, Linux part); `stat -f %Lp` is only simulated by a shim that answers like BSD `stat` (reduced), so real macOS and a WSL home on a Windows drive stay `[unverified]` (Phase 6). The `find` form builds the number bit by bit with `find <file> -perm -<bits>`.
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
("`PORTS` changed: box has 127.0.0.1:3000:3000, config has 127.0.0.1:3000:3000,127.0.0.1:8080:8080; run `swarmbox reset` to apply"; slice 3.2 writes the ports in their normalized form, and only the four keys that have a label of their own can be named, the rest get one generic line) and continues. It only warns (D30): it never offers to run `reset`, which ends sessions and must be explicit. Warnings never block entering.
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
| Short path to the Podman socket (Linux and WSL; 3.5, B5): the host-side socket path `<workspace>/.local/state/swarmbox/podman.sock` is at most 100 characters, or the helper makes the symlink `host:~/.local/state/swarmbox/<name>.sock-dir` and that path is at most 100 | `swarmbox: cannot make a short path to the Podman socket (workspace X is too deep). Choose a shorter workspace path with `swarmbox config set WORKSPACE`.` (the text is a proposal) | 4 |
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
   that the helper extracted from that image reports (step 3). With `--to TAG`, the target is exactly that tag (any series, older or newer). The series is read from the tag of `IMAGE` (`2.0.1` and `2.0` give `2.0`; `3.4.5-rc1` gives `3.4`);
   an `IMAGE` that is pinned by a digest, has no tag, or has a tag that does not start with two numbers (`dev`, `latest`) has no series: a plain `update` exits 2 and says to use `--to TAG`, before any Podman call. A tag that Podman would not accept
   (letters, digits, `_`, `.`, `-`, at most 128 characters, not starting with `.` or `-`) is exit 2, also before any Podman call. The repository is everything before the tag, so a registry with a port (`localhost:5000/org/swarmbox`) is kept whole.
   Pulling the `X.Y` tag and reading the version from the helper works [verified: tests/e2e_registry.py against registry:2 in a throwaway container on 127.0.0.1 with the placeholder organization `placeholder-org`, and tests/test_host_update.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-36-img (dev build of the 2.0 Dockerfile) with one-layer derived versions 2.0.1 and 2.1.0; reduced: boxes without nested Podman, bash 5.2.15, zsh 5.9, fish 3.6.0, real registry (ghcr.io) is Phase 7, macOS and arm64 not run] (B20).
2. Pull it (`podman pull -q <repo>:<tag>`). If this fails (offline, registry error) **nothing changes**: the old helper, the old config and the running box stay; exit 3.
3. Extract the helper from the new image into a temporary folder next to the helper folder (`podman run --rm <repo>:<tag> host-helper`, saved to a file and unpacked, as in 3.7.1), check that `swarmbox-host` is executable, and read the exact `X.Y.Z` from that
   helper's `version`. A helper that is not executable or reports no version is exit 3 with nothing changed. When `TAG` is itself an exact `X.Y.Z` the helper must report that same version, or it is exit 3 (the local tag would otherwise name a different version).
4. Create a local tag for the exact version, `podman tag <repo>:X.Y <repo>:X.Y.Z` (D35; skipped when the pulled tag already is `X.Y.Z`), **then** rename the temporary folder over the old helper folder, **then** write `IMAGE=<repo>:X.Y.Z` into the host config (D17).
   This order (decision `[3.6]`) means that a failing `podman tag` leaves the old helper as well as the old config: nothing has changed (exit 3). The exact tag is what the box's label and a later `reset` use, so a `reset` works offline and
   does not follow a moving tag: with the registry stopped, `reset` made no `pull` call and the new box's label was the `X.Y.Z` reference `[verified: the offline step of tests/e2e_registry.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); registry:2 stopped in its throwaway container; reduced: boxes without nested Podman]`.
   No shell startup file is edited: the function block keeps its marker and seed. Then print "updated to X.Y.Z; run `swarmbox reset` to use it (running sessions end)" on standard output
   (a progress line, "pulling <image> ...", goes to standard error). If `SWARMBOX_IMAGE` is set, it overrides the written `IMAGE` and `update` says so. `update` only pulls and tells you to run `reset`; it never asks and never recreates the box (D27):
   its Podman calls are `pull`, `run --rm ... host-helper` and `tag`, nothing else.
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
in that folder. Then run `swarmbox config set WORKSPACE <that path>` (or, on a fresh install before the first `swarmbox` call, `init --workspace <that path>`) to keep using it." and exits 5. The nested Podman volume `swarmbox-containers` is reused by name.

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
| 9 | Start the tmux server with session `main`, created with **one idle window** named `idle` (`tmux new-session -d -s main -n idle`; `attach` adds a window and closes the idle one when it is the only other, 3.4) | W |
| 10 | Start and supervise ttyd, when `WEB=1` (5.1) | W |
| 11 | Write the readiness marker (4.2) | W |
| 12 | In the background, install the tools listed in `WITH` (6.7), one after another, output to `serve.log` | W per tool; the next shim call retries |

**`serve` is PID 1** (or the child of the small init that `--init` puts first). It installs handlers for SIGTERM and SIGINT, so `podman stop` ends the box promptly instead of waiting for the kill timeout: on a signal it stops its children
(the ttyd supervisor and ttyd, the nested Podman service), leaves the tmux server to end with the container, and exits. After step 12 it blocks in `wait` on a background `sleep infinity` (so the handler runs at once, which a foreground `sleep` would not allow); with `WEB=0` there is
no ttyd supervisor, and this `sleep` is all it blocks on. Measured with the prototype (B3): the handlers run as PID 1 and as the child of `--init` (Podman's init is `/run/podman-init`; serve was its child), `podman stop -t 10` took 0.14 s for each of `INIT=0`, `--init` and `WEB=0`, with exit status 143 (SIGTERM) and 130 (SIGINT sent by `podman kill --signal INT`, also under `--init`), and ttyd was gone when serve left. Controls: a PID 1 with no handler, and one that waits in a *foreground* `sleep infinity`, both ran into the kill timeout (3.14 s for `-t 3`, exit 137), which is why the handlers and the background `sleep` are required, not optional.

Installing `WITH` tools happens **after** the readiness marker, so a slow download never keeps you waiting at the door; the entry banner says "installing claude...".

**What the 2.2 implementation does and fixes** (`container/entrypoint.sh`, tests `tests/test_serve_steps.py`; decisions in `docs/decision-log.md` under [2.2]):

- Steps 4, 6, 7 and 12 call programs that other slices write (`swarmbox-migrate` exists since 2.6): `swarmbox-migrate`, and `swarmbox-tool` with `link --user`, `prepare` and `install <tool>`. A program that is not on `PATH` makes its step a logged no-op ("skipped" in `serve.log`, no health line, not counted as a warning). One that exists and fails is a W. Step 7 runs `swarmbox-mcp generate` (4.4, built in 4b.1); a missing program is a logged no-op.
- Settings read by `serve`: `SWARMBOX_WEB` (`0` turns the supervisor off, anything else is on) and `SWARMBOX_WITH` (comma or blank separated). Logs: `serve.log`, `podman-service.log` and `web-terminal.log` in `<workspace>/.local/state/swarmbox/`; the lines of steps 0 to 2 are held until step 3 has made the folder.
- The marker's `warnings=<n>` counts the W failures of steps 1 to 11 (step 2 counts only under the test switch). Health lines added later (ttyd giving up, a failed `WITH` install) are in the health file but not in the marker.
- **The interface of the web terminal, for the `swarmbox-web` slice.** The supervisor runs `swarmbox-web run` (a foreground command that assembles the page and the options and `exec`s ttyd), or `ttyd -W -p 7681 tmux attach -t main` when `swarmbox-web` is not installed yet. `swarmbox-web restart` reads the supervisor's PID from `box:/tmp/swarmbox/web-supervisor.pid` and sends it `USR1`.
- **The nested service check** (step 8): `serve` starts `podman system service --time=0 unix://<state>/podman.sock` itself, as its own child, and waits up to 10 s for the socket, then runs `podman --url unix://<socket> version`. No socket, or no answer, is the W line "nested Podman service did not start" or "did not answer". Starting it as a child (not through `swarmbox-podman-service`, which still uses the v0.1.0 `~/.swarmbox` paths) is what lets the signal handler stop it.
- Found while writing the tests: in the supervisor a signal that arrives between the start of a `sleep` and the moment its PID is stored is lost, and the supervisor then sleeps out the whole backoff (or forever when idle) with `podman stop` waiting on it. The flags are checked right after the PID is stored.

### 4.2 Readiness, health warnings and restart `[new]`

- **Readiness marker.** `serve` writes `box:/tmp/swarmbox/ready` at step 11, containing `ok` or `warnings=<n>`. Two programs wait for it, and they do not see the same things:
  - **Host `up`** (3.7.2) polls, for at most 60 s, `podman exec <name> cat /tmp/swarmbox/ready` (the content is the marker, so a warnings count can be reported; slice 3.3) **and** the container state (`podman inspect`). If the container has exited (for example `serve` stopped on a
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
  manager and is not part of 2.0. What B16 found: `--restart` alone does **not** survive a reboot (Podman 4.3.1's `--restart` documentation: "restart will not restart containers after a system reboot"); Podman's package ships a **user** unit,
  `/usr/lib/systemd/user/podman-restart.service` (`WantedBy=default.target`, so `systemctl --user enable podman-restart.service`), that runs `podman start --all --filter restart-policy=always`, and on 4.3.1 that filter matches
  `--restart=always` only: a container created with `--restart=unless-stopped` (documented as "identical to always") is **not** listed by it, so a reboot would not restart it. A later Podman's unit also covers `unless-stopped` (its documentation says so) `[unverified]` for versions after 4.3.1.
  Whether the unit then starts at boot for a rootless user without a login (it needs the user's service manager running, which on systemd means lingering, `loginctl enable-linger`) was not tried, because the sandbox has no systemd `[unverified]` (B16)
  [verified: spike_b16_restart_policy.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); debian:bookworm-slim; reduced: no systemd here, so no reboot and no `systemctl --user enable` was tried]. (The Cloudflare connector is created with `--restart=always` `[today]`, the one policy that unit covers; Podman brings it back after a host reboot only if the user enabled `podman-restart.service`,
  as `docs/cloudflare.md` says today `[today]`. If a future box ever gets `--restart`, it must be `always`, not `unless-stopped`, on 4.3.x.)

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
   `XDG_DATA_HOME` and `XDG_STATE_HOME`; tests point those at temporary folders. It defines `SB_CONFIG_DIR`, `SB_DATA_DIR`, `SB_TOOLS_DIR`, `SB_SHIMS_DIR`, `SB_STATE_DIR`, `SB_LOG_DIR`, `SB_HEALTH_FILE`,
   `SB_PODMAN_SOCK` and `SB_RUN_DIR` (`/tmp/swarmbox`); an empty or relative XDG value is ignored, as the XDG specification says; sourcing creates nothing (`tests/test_dirs.py`).

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
  in the image at build (see "Version of the MCP server" below). That the installed package provides a program named `chrome-devtools-mcp` that accepts these same options holds for the pinned 1.12.0: `--version` prints 1.12.0, `--help` lists `--executablePath`, `--headless`, `--chromeArg` and `--browserUrl`, and started with the registry's arguments the server answered `initialize` and `tools/list` over stdio (32 tools; no page was opened) [verified: container run of the built image swarmbox-test-img-<rand> (tests/test_image_build.py and an MCP stdio client on tools/list); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-ba9849 built from the 2.1 Dockerfile] (B24).
- `browserUrlArgs` (optional): when `BROWSER_URL` is non-empty, these `args` replace the server's `args`, with `${BROWSER_URL}` replaced by the value. This is how chrome-devtools
  switches from a local headless Chromium to a remote Chrome: today `build_base_mcp_config` does the same in code, with `args = ["-y","chrome-devtools-mcp@latest","--browserUrl=<url>"]` `[today]`.
- **All entries are enabled by default.** The per-server off switch is a file `<workspace>/.config/swarmbox/mcp/<name>/config.json` containing `{"enabled": false}`; user-level files with the same
  name override the image's fields. It takes effect at the next start of the box.

**Generated files.** `serve` writes `<workspace>/.claude/mcp-servers.json`:

```json
{ "mcpServers": { "chrome-devtools": { "command": "chrome-devtools-mcp", "args": ["--executablePath=/usr/bin/chromium", "..."] } } }
```

(`{"mcpServers": {"<name>": <entry>}}` with `browserUrlArgs` and `enabled` removed. `[today]` for the one server, with `npx` as its command.)

**4b.1 state (the generator).** `container/scripts/swarmbox-mcp.sh` (installed as `swarmbox-mcp`; `swarmbox-mcp [generate] [--output FILE]`) is the generator and uses `jq`, which the image has (python3 is there too; jq was chosen because the OpenCode mirror of v0.1.0 already uses it). It reads `/etc/swarmbox/mcp/<name>/config.json` and `$SB_CONFIG_DIR/mcp/<name>/config.json`, merges the two shallowly per server (a user field replaces the image field), drops a server with `{"enabled": false}`, applies `browserUrlArgs` when `BROWSER_URL` is not empty (the value is inserted literally), removes `browserUrlArgs` and `enabled`, skips an entry with no `command`, and writes `<workspace>/.claude/mcp-servers.json` through a temporary file and `mv`. A bad file gives one line on stderr and is skipped; the other servers are still written and the exit status is 1 (serve: one W line, "generating the MCP configuration failed or was incomplete"); a write failure is exit 2 and leaves the old file. `serve` step 7 still leaves `{"mcpServers": {}}` when no file exists afterwards, because `claude --mcp-config` refuses a missing file. `container/mcp/chrome-devtools/config.json` now has the shape above (`chrome-devtools-mcp`, no `npx`, no `@latest`). The OpenCode mirror is not part of 4b.1. [verified: tests/test_mcp_registry.py, tests/test_serve_steps.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); no container needed, reduced: the generator was not run in a built image]

**OpenCode mirror.** An agent whose manifest says `MCP_FORMAT=opencode` gets its own copy. v0.1.0 (`sync_opencode_mcp`) maps each server `s` to
`.mcp[name] = { "type": "local", "command": [s.command] + s.args, "enabled": true }` plus `"environment": s.env` when `env` is present, inside the OpenCode config file; 2.0 keeps this mapping, now in
`container/tools/opencode/prepare.sh` (function `sync_opencode_mcp`), which `serve` runs at step 7 after it has written the MCP file above (4.1, 6.3, 6.6). The file it writes is `box:/tmp/swarmbox/opencode.json`. **4b.2 state:** done, see the 4b.2 paragraph in 6.6 (the mapping is unchanged and a test compares it with the v0.1.0 function on the same fixtures). The mirror also tolerates a file with no `mcpServers` key (an empty `mcp` object) where v0.1.0 failed.

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
- **What the 2.5 implementation does** (`container/scripts/swarmbox-web.sh`, installed as `swarmbox-web`; tests `tests/test_web_build.py`, `tests/test_web_container.py`; decisions under [2.5]). `swarmbox-web run` (what the supervisor of 4.2 runs) renders `box:/tmp/swarmbox/index.html` from the built page with `sed` (padding 0 to 99 else 10 with a message; only the word `false` turns `ctrlVPaste` or `ctrlCCopy` off; a page that lacks a placeholder is refused), turns every other key of `web-terminal.conf` into a `-t key=value` option, and `exec`s `ttyd -p 7681 -W -O --index ... swarmbox-attach` (or `tmux attach -t main` when `swarmbox-attach` is missing), on every interface inside the box. `swarmbox-web render` only renders; `swarmbox-web restart` sends `USR1` to the PID in `web-supervisor.pid` and refuses a missing, non-numeric, dead or pid-1-or-lower PID. The page is built at image build and holds exactly the three placeholders. [verified: tests/test_web_container.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-s25a; reduced: development box, no nested Podman in the box] In a throwaway container the built page was in the image, `/tmp/swarmbox/index.html` had the user's padding and switch, ttyd (random port, `-i lo`, inside the container's own namespace) served that page, the other options reached ttyd as `-t` arguments, and `swarmbox-web restart` gave a new ttyd and a new page with the box up.
- Font, theme and size do not live in the HTML: ttyd passes them to the page through its `-t key=value` options, built from
  `web-terminal.conf` at start.
- `web-terminal.conf` is `<workspace>/.config/swarmbox/web-terminal.conf` (`<workspace>/.swarmbox/web-terminal.conf` today). Logs go to
  `<workspace>/.local/state/swarmbox/`.
- Limit: ttyd serves a **single file** as the page (`--index`). Measured (B4): with `--index` pointing at a page that references `style.css` and `app.js` beside it, `GET /` returns the page
  and `GET /style.css`, `/app.js`, `/other.txt` and even `/index.html` all return 404; only ttyd's own `/token` endpoint and its websocket answer. ttyd's `--help` documents the option only as "Custom index.html path". A page that grows into
  several files would have to be inlined into that one file (as `build-index.sh` does), or a small server put in front (B4) [verified: spike_b4_ttyd_index.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); the box's ttyd 1.7.7-40e79c7 on a random 127.0.0.1 port, no container; reduced: no container].

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

**4a.2 state (`link`).** `link --system` and `link --user` read the manifests of their one level, decide everything first and write after. Shims are symlinks to exactly `/usr/local/bin/swarmbox-shim`, one per `PROVIDES` entry. The index is the file `index` next to the shim folder (`/usr/local/lib/swarmbox/index`, `<workspace>/.local/share/swarmbox/index`), one line `<command> <tool>`, sorted bytewise by command, always written (empty when there are no tools). `tool-ports` (image level only) holds `<tool><TAB><port>` per `PORTS` word, sorted by tool then in manifest order, and is written **before** the shims, always, empty when no manifest declares a port, so a failed run never leaves the helper archive without it; a `PORTS` word that is not a number is skipped with a warning. A command listed by two manifests of the same level is an error: `link` names both on stderr, writes nothing at that level and exits 1; the same command at both levels is fine (user wins by `PATH` order). Links are made under a temporary name and renamed over (`mv -T`), the index and `tool-ports` through a temporary file and `mv`, and stale links are removed last, so a reader (an `attach` racing `serve`) never finds a needed shim missing. A stale shim is a symlink in the folder whose target is exactly the dispatcher path and whose command is no longer provided; every other entry is left alone, and a command name already taken by something that is not such a link is reported and skipped (exit 0). A manifest that does not source, has an unreadable `SCHEMA` or lists a `PROVIDES` entry with a slash is skipped with a warning (`validate` is where it fails). The folders are created by `link` (root at image build, the agent user for the user level, which lives entirely in the workspace). The dispatcher `swarmbox-shim` is described under 6.5 (4a.4 state).

**4a.5 state (the image).** The Dockerfile copies `container/tools/` to `/usr/local/lib/swarmbox/tools/`, `swarmbox-tool.sh` and `swarmbox-shim.sh` to `/usr/local/bin/`, makes the tree readable and every `*.sh` under the tools folder executable (`chmod 755` on both programs and `find ... -name '*.sh'`), and then runs `swarmbox-tool link --system` in the same `RUN`; it sets `ENV PATH=/usr/local/lib/swarmbox/shims:$PATH`, so the image shims are found by every process of the box, and `bashrc.sh` puts the user shims and the tools' `current/bin` in front of them. No agent is installed (D2). In the built image `swarmbox-tool validate` reports `1 manifest(s) checked, 0 with errors`, `shims/claude` is a link to `/usr/local/bin/swarmbox-shim`, the index is the single line `claude claude`, `host/tool-ports` exists and is empty, `curl` and `flock` are present, and neither a `claude` program nor `~/.local` exists. `serve` steps 6, 7 and 12 call `link --user`, `prepare` and `install <tool>` (in the background, after the readiness marker); a failed install is the health line `installing <tool> failed (the next call of it retries); see serve.log`. **Not in the design: `serve` step 7 leaves `<workspace>/.claude/mcp-servers.json` containing `{"mcpServers": {}}` when the file does not exist**, because the `claude` alias passes `--mcp-config` with that path and `claude` refuses a missing file (`Error: Invalid MCP configuration: MCP config file not found`); the registry of 4.4 (4b.1) writes the real list and overwrites it; the empty file is now only the fallback when the generator is missing or fails before writing. [verified: tests/test_serve_steps.py; tests/test_bashrc_container.py; manual run in a throwaway box; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-4a5-img; reduced: development box, no nested Podman in the box] With an empty `mcp-servers.json`, `claude --dangerously-skip-permissions --mcp-config <it> -p hi` got past the MCP check and stopped at `Not logged in`. First real call in the same throwaway box: the shim ran the installer, the native installer downloaded Claude Code 2.1.319 (325 MB under `~/.local/share/claude`), the first call took about 13 s, the second printed the version at once, and `command -v claude` found the image shim; the image size grew by 343,292 bytes against the 2.1 build (1,751,732,768 against 1,751,389,476 bytes), so the tools wiring costs nothing measurable.

The install lock is `box:/tmp/swarmbox/tools.lock` (an `flock`, so two shells do not install at once).

`PATH` order: user-level shims, image-level shims, then `<workspace>/.local/share/swarmbox/tools/*/current/bin`. After install the real
binary is found before the shim, so there is no per-call overhead. `[verified: a shell experiment with a symlink named gcloud and one named clasp pointing at one script; each saw its own name in $0 and its own arguments; re-recorded by spike_b12_symlink_arg0.sh; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); no image involved; reduced: run on the box with its own dash, bash, zsh and busybox sh, not in a throwaway container]`. Per shell, as a script run by its shebang (the shim case, also when found through `PATH`): dash, bash, zsh and busybox sh all give `$0` = the path as invoked (the symlink's own path), so `basename "$0"` is the command name. **Not the same when a file is sourced** (the function of 3.6): `$0` inside a function defined in a sourced file is `/usr/bin/dash` in dash, `/usr/bin/bash` in bash, the function name in zsh and `sh` in busybox, so the generated function must not locate anything with `$0`; it calls the helper at its fixed location (3.6), and the helper, run as a script, may use `$0`.

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
MCP_FORMAT=opencode                          # gets its own copy of the MCP server list
YOLO_FLAGS="--auto"                          # verified (B2); only valid at the start of the command line, not before a subcommand
YOLO_ALIAS=0                                 # so `yolo` uses the flags but no `alias opencode=...` is generated (6.6)
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
- `YOLO_FLAGS`, `YOLO_ALIAS`: agents only. `YOLO_FLAGS` is the auto-approve flag set (6.6). `YOLO_ALIAS` (default `1`) says whether an alias is generated from it; `0` means only `yolo` uses the flags. `[new]`, introduced for OpenCode (B2), whose flag is not accepted before a subcommand.
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

**4b.2 state (`prepare`).** `swarmbox-tool prepare` is real. It lists the tool folders of both levels in the order of the tool names (C locale; the user level wins over the image level for the same name), and runs `prepare.sh` of each tool that has one and is installed (as `list` decides it) or is named in `SWARMBOX_WITH` (commas or blanks). The script is run with `bash <file>` (no executable bit needed) in `$HOME`, with standard input closed, standard output sent to standard error, `SWARMBOX_TOOL_NAME` and `SWARMBOX_TOOL_DIR` exported, under `timeout` (default 60 s, `SWARMBOX_PREPARE_TIMEOUT` for tests; a hang is a failure and its process group is killed). A tool that fails, times out, or has a broken manifest while shipping a `prepare.sh` gives one line `prepare-failed: <tool>: <reason>` on standard error and exit status 1 at the end; the other tools still run. `serve` step 7 turns each such line into one W line (one health line each, counted in the marker), and a failure with no such line into one generic W line. `swarmbox-tool install` and the first-use install of `run` call the same code for that one tool after a successful install; a failure there prints the line but never fails the install. `validate` now rejects an `MCP_FORMAT` that is not `claude` or `opencode` (empty is allowed). `[verified: tests/test_tool_prepare.py, tests/test_serve_steps.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); no container needed, reduced: not run in a built image]`

### 6.4 Install contract: `install.sh`

Called by `swarmbox-tool install <name>` with:

| Variable | Meaning |
|---|---|
| `TOOL_PREFIX` | Directory to install into (a `bin/` inside it is put on `PATH`). |
| `TOOL_VERSION` | The version to install (already resolved). |
| `TOOL_ARCH` | `amd64` or `arm64`. |
| `TOOL_SHA256` | `[new]` The manifest's `SHA256_<TOOL_ARCH>`, only when it declares one (never inherited from the caller's environment). The installer verifies its download against it and exits non-zero on a mismatch (4a.3 state, 6.5). |

Rules: idempotent; writes only under `$TOOL_PREFIX` (and its own temp dir); prints progress to **stderr** only (stdout
belongs to the tool being run); exits non-zero on any failure and leaves no half-installed `current` link. npm-based tools
use `npm install -g --prefix "$TOOL_PREFIX"` and **clean or redirect the npm cache in the same step**. The image sets `NPM_CONFIG_CACHE=/opt/npm-cache` (v0.1.0's `Dockerfile` line 144 `[today]`), outside the prefix, so an unmodified
install writes its cache there, not under `$TOOL_PREFIX`. The installer therefore either runs `npm cache clean --force` afterwards or passes `--cache` pointing at its own temporary folder; and `/opt/npm-cache` must be owned by `agent` (10.2): v0.1.0's Dockerfile comment
(lines 332 to 334) documents that root-owned cache entries make a later `npm` as `agent` fail with `EACCES` `[today]`.

Hard rules, because a box can be recreated (section 6.11): an installer **never** uses `apt` or `sudo`, never writes outside
`$TOOL_PREFIX` (not in `/usr`, `/etc`, `/opt`, and not in the user's shell startup files such as `<workspace>/.bashrc`; the one exception is an `UPDATE=self` tool, which may write the paths of its own installer inside the workspace home, listed in 6.7), and never needs
a system package that the image does not already have. A tool that needs one belongs in the image, or in the build-time
preinstall (6.8), not in an on-demand install. Anything an installer is allowed to leave behind (a cache, including `/opt/npm-cache`) must be safe to lose; the cache is the one place outside `$TOOL_PREFIX` an installer may touch, and only through npm's own cache setting.

**Where the rule is enforced** `[new]`: statically by `swarmbox-tool validate`, which refuses an `install.sh` that mentions `apt`, `apt-get` or `sudo`, or writes to a path outside
`$TOOL_PREFIX` or its temp directory in the ways it can detect (it is a lint, not a guarantee); and dynamically by the "no side effects" CI test (13). At run time nothing enforces it: the agent has `sudo` (11).

Examples

```bash
#!/bin/bash
# container/tools/clasp/install.sh (the npm shape; claude is not this shape, see below)
set -euo pipefail
npm install -g --prefix "$TOOL_PREFIX" "@google/clasp@${TOOL_VERSION}" >&2
npm cache clean --force >&2
```

`container/tools/claude/install.sh` is **not** this shape (B1, 6.7): it runs the vendor's native installer, `curl -fsSL https://claude.ai/install.sh | bash -s <version>` (version `latest` is passed as no argument), as `agent` with `HOME` the workspace.
That installer writes only inside the home (verified, 6.7), but not under `$TOOL_PREFIX`: the hard rule below has one explicit exception for `UPDATE=self` tools, and the installer needs `curl`, which the image's package list has (10.2) and the `node:24-slim` base does not (it was added with apt in the spike).

`container/tools/opencode/install.sh` has the npm shape plus one step: `@opencode/cli` (the package v0.1.0 installs) ships four platform builds of about 250 MB each and hard-links
the right one into its `bin/`, so the installer removes the other builds (`rm -rf <prefix>/lib/node_modules/@opencode/cli/node_modules/@opencode`)
and checks that `opencode --version` still runs. That saves about 720 MB per workspace
`[verified: spike_b10_opencode_prefix.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` under `--prefix` too (B10): `@opencode/cli` 2.2.6 measured 992 MB before and 247 MB after, a saving of **745 MB**, and `opencode --version` still runs, because `bin/opencode.exe` is a hard link (link count 2) to the kept `cli-linux-x64` build, so the file survives the `rm`. 
The other npm name, `opencode-ai` 1.19.5, installs only two builds on glibc and saves 204 MB (409 MB to 205 MB). The two packages are different release lines, and they must not be swapped silently: running `opencode-ai` 1.19.5 in a home that `@opencode/cli` 2.2.6 had used failed with "Database is not empty and has no session table". The saving depends on the version and on the architecture: the installer prunes by looking at what is there (it keeps the build that `bin/opencode.exe` is linked to), never by a fixed list of names.

`container/tools/gcloud/install.sh` would download Google's tarball for `$TOOL_ARCH`, verify the manifest's `SHA256_<arch>`,
extract it into `$TOOL_PREFIX` and link the binaries into `$TOOL_PREFIX/bin`. The checksums are recorded in the manifest at release time (D29): a maintainer script, run when the
pinned version is bumped, downloads the archive for each architecture and writes `SHA256_amd64` and `SHA256_arm64` into `tool.conf` (the script is not written yet). What B11 found: the download URLs are
`https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-<version>-linux-x86_64.tar.gz` (`$TOOL_ARCH=amd64`) and `...-linux-arm.tar.gz` (`arm64`: Google's name for 64-bit Arm is `arm`), with the version in the file name
(the same names without `<version>-` always name the newest release). Google's install page (`https://docs.cloud.google.com/sdk/docs/install-sdk`, Linux table, column "SHA256 Checksum") publishes a checksum, but **only for the
unversioned file name** (`google-cloud-cli-linux-x86_64.tar.gz`, today `16fda6058d66e4ec29e8575e2b6e19b0d03cea7b091e6730f7e8361209e6955f`, and `google-cloud-cli-linux-arm.tar.gz`, today
`cc584dabf7b1f7ba79354744027b6de654ff6876c03dffb2174c1b1e3c0c6956`, both release 592.0.0), and it moves with every release; the computed values of both downloads matched the page. The version-pinned archives
(`google-cloud-cli-592.0.0-linux-x86_64.tar.gz`, 94,620,306 bytes; `...-linux-arm.tar.gz`, 90,645,329 bytes) are **different bytes** with other checksums (`2d841a23a681ab94486af6841e5f1cd123cd300fb8c4be6ba5b51350fca3d50b` and
`ba588759c4c42122a8c14536009738c0f0030989ca75788235f9956555e44f4d`) although every file inside has identical content (35,442 and 35,438 regular files compared). So the page's checksum cannot be copied into a manifest that pins a
versioned URL. The maintainer script of D29 therefore downloads the **pinned** URL for each architecture and records the checksum it computes (trust on first use, as D29 says); where the release it bumps to is still the newest, it can
cross-check by comparing the extracted content with the unversioned archive's, but there is no publisher checksum for the versioned file (B11) [verified: spike_b11_b25_checksums.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); HTTPS reads and downloads, no container; gcloud 592.0.0; reduced: no container]. (`components-2.json` in the same folder lists checksums of the SDK's
individual components, not of the whole archive, and is not used.)

Go (B25) publishes a checksum for every file, including the versioned ones, which is what the same maintainer script copies instead of computing: go.dev's JSON listing `https://go.dev/dl/?mode=json` (an array of releases, newest
first, each with `files[]` of `filename`, `os`, `arch`, `sha256`, `size`, `kind`; add `&include=all` for older releases, not tried) and the download `https://go.dev/dl/<filename>`. For go1.27.3 the entries are
`go1.27.3.linux-amd64.tar.gz` with `SHA256_amd64=65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40` and `go1.27.3.linux-arm64.tar.gz` with `SHA256_arm64=a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49`;
the computed checksums of both downloads matched the listing (B25) [verified: spike_b11_b25_checksums.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); HTTPS reads and downloads, no container; go1.27.3; reduced: no container]

### 6.5 Lifecycle of a shim call

1. The shim (a link to `swarmbox-shim`) finds its tool in the index and runs `swarmbox-tool run <name> <command> -- "$@"`.
2. If the tool is installed (a `current` link, or the `self` directory), `exec` the real command. Done.
3. Otherwise take the lock, print `Installing <name> (first use)...` to stderr, run `install.sh`, move `current`.
4. `exec` the real command. If the install fails, print the reason, exit non-zero, and the next call retries.

Failure modes: offline (clear message, nothing installed), checksum mismatch (install aborted, files removed),
concurrent shells (second waits on the lock, then finds it installed), and an installed tool whose recorded environment no
longer matches the image (section 6.11).

**4a.3 state (`install`, `run`, `list`, `update`).** `swarmbox-tool run <name> <command> [-- args]` checks that `<command>` is in the manifest's `PROVIDES`, then that the tool is installed, without the lock; if not it takes the lock, **checks again** (a shell that waited finds the work done), prints `Installing <name> (first use)...` on stderr, runs the installer, and `exec`s the real program with the arguments untouched, stdin and the caller's directory kept, the lock released first. `swarmbox-tool install <name> [--version X] [--force]` does the same install explicitly (message `Installing <name>...`); a second `install` of an installed tool does nothing and says "already installed".
- *Lock:* `flock` (util-linux, an essential Debian package, so always in the image) on `/tmp/swarmbox/tools.lock`; it waits up to 900 s and says it is waiting; the installer does not inherit the descriptor, so a daemon it leaves behind cannot hold the lock.
- *Installer call:* `install.sh` runs with `HOME` as the workspace and as its working directory, stdin closed, **stdout redirected to stderr** (so a run's stdout is only the tool's), a private `TMPDIR` that is removed afterwards, and `TOOL_PREFIX`, `TOOL_VERSION`, `TOOL_ARCH` (`uname -m`: `x86_64` or `amd64` is `amd64`, `aarch64` or `arm64` is `arm64`; anything else is refused before the installer runs) and `TOOL_SHA256`.
- *Managed layout:* `tools/<name>/<version>/` is the `TOOL_PREFIX`, installed in place (an installer may write absolute paths, so it is not moved afterwards); the version directory is *complete* when `.swarmbox-env` (the fingerprint of 6.11: `ARCH`, `NODE_MAJOR`, `LIBC`, `VERSION`) exists and every `PROVIDES` command is executable in `bin/`. `current` is a relative link moved by an atomic rename, and only after the install is complete. On any failure the version directory is removed, `current` stays where it was, and folders the call created are removed again, so the tool tree is byte-identical to before. `--version X` installs side by side and moves `current`; when `X` is already installed only the link moves. A manifest `VERSION=latest` on a managed tool is used as the directory name `latest` (no resolver yet: [unverified], decision log [4a.3]). The tool runs with `tools/<name>/current/bin` first on `PATH`.
- *`UPDATE=self` layout:* the installer gets a staging folder as `TOOL_PREFIX`, which becomes `tools/<name>/self/` (SwarmBox's record: `.swarmbox-env` plus whatever the installer wrote there) only after the installer succeeded and every `PROVIDES` command resolves in `~/.local/bin`. **Installed means: the record exists AND the command resolves** to an executable that is not the shim; a deleted binary with a stale record, or a binary with no record, is installed again. `--version X` reinstalls that version and prints a note that the tool will update itself. The program is found explicitly at `~/.local/bin/<command>`, never through `PATH`, and a launcher whose real path is `swarmbox-shim` is refused (it would call itself forever).
- *Exit codes:* the tool's own exit status passes through `run` (it is `exec`). A failed install exits **69** from `run` and `install`, so it cannot be mistaken for a tool that exited 1, and says "Nothing was installed; the next call retries". Usage errors exit 64; `use`, `remove`, `doctor`, `new` and `update` of a managed tool exit 70 with "later phase".
- *`list`* prints one row per tool of both levels (user wins): name, kind, update mode, level and state (`not installed`, `installed (<version>)`, `installed (self)`, `needs reinstall`). *`update <name>`* for `UPDATE=self` runs the manifest's `UPDATE_CMD`, its first word resolved to the real program, and passes its exit status.
- The image copy of `container/tools` is the next slice.

**4a.4 state (`swarmbox-shim`).** `container/scripts/swarmbox-shim.sh` is installed as `/usr/local/bin/swarmbox-shim`, the target of every generated link. It is **POSIX `sh`** (shebang `#!/bin/sh`, shellcheck `-s sh`), not bash: dash starts faster and the same text runs under bash and busybox sh (decision log [4a.4]). The call: (1) the command is `basename "$0"`; called as `swarmbox-shim` itself it explains what it is and exits 64. (2) The tool comes from one pass over the **user index** (`<workspace>/.local/share/swarmbox/index`, located through `dirs.sh`) and then the **image index** (`/usr/local/lib/swarmbox/index`): first match of an exact command name wins, so the user level overrides the image. (3) No match: `<command>: command not found (...)` on stderr, exit **127**. (4) `exec swarmbox-tool run <tool> <command> -- "$@"`; everything else (install, the lock, the real program, its exit status, 69 for a failed install, 64 when the manifest no longer provides the command) is `run`'s, see above. The shim never sources a manifest and starts nothing but the manager, so a manifest broken after `link` does not slow or break the lookup (the manifest is read by `run` only). A missing manager exits 70. *Loop guards, two layers:* `run` refuses a real command whose path ends in `swarmbox-shim` (or `swarmbox-shim.sh`, the repository name) or is `/usr/local/bin/swarmbox-shim`, exit 69; and the shim counts its own nested calls in `SWARMBOX_SHIM_DEPTH` and stops at 16 with exit 70, which catches a loop the path check cannot see (a wrapper script around the shim). Once a tool is installed the real binary is found before the shim on `PATH` (managed: `tools/<name>/current/bin`; `UPDATE=self`: `~/.local/bin`) and the shim is not run at all. `[verified: tests/test_tool_shim.py, shebang shell, dash, bash and busybox sh, by symlink path and by PATH lookup; 2026-11-08; Podman 4.3.1 on the box, Debian 12 (bookworm), Podman not used by the test; no image involved]`

### 6.6 Agents: aliases and `yolo`

For every installed or declared agent, the shell gets an alias built from the manifest, e.g.
`alias claude='claude --dangerously-skip-permissions --mcp-config ...'`, so `claude` is auto-approve by default inside the
sandbox (today this alias is written by hand in the image's `bashrc`, `[today]`). The flags live only in the manifest: when a release changes one, there is one place to fix. The file named by
`MCP_FLAGS` is generated by `serve` from the MCP registry (4.4), not written by hand.

- `yolo` runs the **default agent** in auto-approve mode. The default is `SWARMBOX_AGENT`, else the first agent in
  `SWARMBOX_WITH`.
- `command claude` bypasses the alias (normal prompts). `SWARMBOX_YOLO=0` disables all the aliases.
- An agent without a verified auto-approve flag gets no alias. OpenCode's flag is `--auto` (B2): `[verified: spike_b2_opencode_flag.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; @opencode/cli 2.2.6 and opencode-ai 1.19.5]` it is listed by `opencode --help` and `opencode run --help` as "Auto-approve permissions that are not explicitly denied", so deny rules still apply (it is weaker than Claude Code's flag, which skips every check). OpenCode's documentation pages (`/docs/cli/`, `/docs/permissions/`) do not mention the flag: the source is the program's own help.
  **But OpenCode still gets no alias.** The flag is accepted on `opencode` and on `opencode run`, **not** before a subcommand: `opencode --auto run "..."` fails with "Unrecognized flag: --auto in command opencode run" (2.2.6), so an alias `opencode --auto` would break `opencode run`, `opencode mcp` and the other subcommands. The manifest therefore says `YOLO_FLAGS="--auto"` and `YOLO_ALIAS=0` (new key, 6.3): the flags are used by `yolo` (which always starts the interactive program) and by nothing else; `opencode run --auto "..."` is spelled out by whoever wants it. `yolo` starting `opencode --auto` interactively is `[unverified]` (no terminal in the spike).
- OpenCode is a shim like Claude Code (D4): an on-demand agent with its own manifest. Its local-LLM support moves from `init.sh` into its tool directory, split between two optional files
  (6.3). **`container/tools/opencode/prepare.sh` is the one owner of the rendering**: `serve` runs it at step 7 of every start (4.1), and it holds `build_opencode_config`, which renders
  the config from `LOCAL_LLM_*` (off unless set) using the template `container/tools/opencode/local-llm.json` into `box:/tmp/swarmbox/opencode.json`, and `sync_opencode_mcp`, which
  mirrors the MCP list (`MCP_FORMAT=opencode`, 4.4) into the same file. **`shell.sh` renders nothing**: it only exports `OPENCODE_CONFIG=/tmp/swarmbox/opencode.json` for the interactive shell,
  instead of the `ENV` in today's Dockerfile `[today]`. The `LOCAL_LLM_*` variables are ordinary
  `ENV_KEYS` entries (7, 8.2): the opencode tool documents that it wants them, and nothing forwards them specially. Today they are forwarded automatically when set on the host, and have defaults (a model
  name and `host.containers.internal:8000`) `[today]`; both go away (12.2). **The template.** v0.1.0 keeps it at `container/opencode/local-llm.json` and the image copies it to
  `/etc/swarmbox/opencode/local-llm.json`, where `build_opencode_config` reads it `[today]`. In 2.0 it moves to `container/tools/opencode/local-llm.json` and is installed with the image-level manifests
  (`/usr/local/lib/swarmbox/tools/opencode/local-llm.json`, 6.2); `prepare.sh` reads it from there. The old `container/opencode/` folder is removed (**in Phase 6**: `Dockerfile.v0.1.0` still copies it, so 4b.2 keeps an identical copy, and a test checks that the two agree).

**4b.2 state (the opencode tool).** `container/tools/opencode/` has `tool.conf` (`KIND=agent`, `PROVIDES="opencode"`, `VERSION=latest`, `UPDATE` left at `managed`, `MCP_FORMAT=opencode`, `YOLO_FLAGS="--auto"`, `YOLO_ALIAS=0`, no `PORTS`), `install.sh`, `prepare.sh`, `shell.sh` and `local-llm.json`. **Package.** The name is the one variable `PACKAGE="@opencode/cli"` at the top of `install.sh` (not a manifest key: the manifest is not visible to the installer); it is the package v0.1.0 installs and the one B10 measured, and the other name is `opencode-ai` (decision log `[4b.2]`). **Prune.** After `npm install -g --prefix "$TOOL_PREFIX" <package>@<version>` and `npm cache clean --force`, the installer keeps every platform build that contains a file hard-linked to `bin/opencode.exe`, removes the others, and never removes a build whose name ends in `-linux-<x64|arm64>` for the current `TOOL_ARCH`; if no build is the linked one nothing is removed; finally `opencode --version` must run or the install fails. **Render.** `prepare.sh` writes `box:/tmp/swarmbox/opencode.json` (mode 600, through a temporary file and `mv`): the template, then for `LOCAL_LLM_URL` set and non-empty plus `LOCAL_LLM_MODEL` the filled `provider.local` and `model`; with the URL unset or empty the `provider` key is removed altogether; a URL without a model, or a context or output that is not a whole number, leaves the provider out, prints one line and exits 1 (one health line); `LOCAL_LLM_KEY` defaults to `sk-local` and the context and output to 65536 and 8192 (the v0.1.0 values); the model name has no default any more. Then the MCP mirror of 4.4. A mirror failure (not JSON) is reported, exit 1, and the file is still written without `mcp`. **The 2.x background server** (found in 0.3: 2.x starts a shared background service per user account; `--standalone` avoids it) is **not exercised** here: how it behaves under `serve` and across a `reset` is `[unverified]` and belongs to the real install of 4b.7. `[verified: tests/test_tool_opencode.py with a fake npm and a fake package tree (reduced: the real package and npm are not run here); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); no container]`

`shell.sh` is the optional place for what a tool needs in the interactive shell (files to render at start belong in `prepare.sh`). It is sourced from the shell
configuration for every installed or declared tool. Today's example is the `clasp` function that adds
`--redirect-port 43323` to `clasp login` `[today]`: it moves from the image's `bashrc` into `container/tools/clasp/shell.sh`, next to the
tool that needs it. The generated aliases from the manifest are produced before `shell.sh` runs, so `shell.sh` can extend or
override them.

**What the 2.4 implementation does (`container/config/bashrc.sh`, installed as `/etc/swarmbox/bashrc.sh`).** The image's `/etc/bash.bashrc` ends with `[ -r /etc/swarmbox/bashrc.sh ] && . /etc/swarmbox/bashrc.sh` (Debian's file returns at once for a non-interactive shell, so this line is reached by interactive shells only); `swarmbox-attach` sources the fragment directly for the no-terminal form (3.3).
- Guard: interactive shell, or `SWARMBOX_CMD=1`; any other shell returns at once and prints nothing.
- Order: `dirs.sh`, the Python venv (`/opt/flow`), the `PATH` additions (user shims, image shims, the tools' `current/bin`, `~/.local/bin`, in front of the old `PATH`, each only if absent), the `ls` and `grep` aliases and `uuid` (moved from the echo lines of v0.1.0), the generated agent aliases, `yolo`, each tool's `shell.sh`, and last, in an interactive shell that was not started with `-c`, the banner (`banner.sh`, then one line per line of the health file, including the stale-image line) and Starship. The banner and the prompt appear once per shell; sourcing again changes nothing.
- Manifests are read from `<config>/tools/<name>/tool.conf` (user level) and `/usr/local/lib/swarmbox/tools/<name>/tool.conf` (image level); the user level wins for the same name. Each file is sourced in a subshell, so its variables never reach the shell, and one that does not load is skipped. An agent (`KIND=agent`) with `YOLO_FLAGS` and `YOLO_ALIAS` other than `0` gets `alias <first PROVIDES word>='<it> <YOLO_FLAGS> <MCP_FLAGS>'`; `SWARMBOX_YOLO=0` generates none. With no manifest there are no aliases.
- `yolo [args]` runs the program (not the alias, so no flag is given twice) of the default agent with `YOLO_FLAGS` and `MCP_FLAGS`. The default is `SWARMBOX_AGENT`, else the first agent of `SWARMBOX_WITH`, else the first agent manifest by name `[new]` (not in this section's first version). With no agent manifest it prints "yolo: no agent installed ..." on standard error and returns 1; an agent name without a manifest returns 1 with a message. `yolo` keeps working with `SWARMBOX_YOLO=0` and for `YOLO_ALIAS=0` agents. The flags are split on blanks: a flag value with a space is not supported.
- Not done here: the one-line SSH fingerprint (10.3) is not shown by the banner; the stale-image and fingerprint lines are shown because they are lines of the health file, but nothing writes them until the helper of Phase 3.

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
- **How it is installed (B1, decided).** `container/tools/claude/install.sh` runs the vendor's **native installer**, not npm. `[verified: spike_b1_claude_update.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; Claude Code 2.1.314 updated to 2.1.319]` Measured in two throwaway containers with an empty home, each installing release 2.1.314 and running `claude update`:
  - *npm under `--prefix`*: the updater does **not** work with npm's default settings. It runs `npm install -g` against npm's own global prefix (`/usr/local`, not writable by `agent`), prints "Can't auto-update: npm global folder isn't writable" and "Error: Insufficient permissions to install update", and leaves 2.1.314 in place. It works only when `NPM_CONFIG_PREFIX` names the prefix in the environment of the running `claude` ("Successfully updated from 2.1.314 to version 2.1.319", in place, no second copy). That setting would have to come from the shim and would also redirect every `npm install -g` the agent runs inside that session into SwarmBox's prefix: rejected.
  - *native installer* (`curl -fsSL https://claude.ai/install.sh | bash -s 2.1.314`, reachable from the nested container, no login): `claude update` works with no setting ("Successfully updated"), `~/.claude.json` records `"installMethod": "native"`, and nothing was written in `/usr`, `/etc`, `/var`, `/root` or `/opt` (the npm cache aside). Everything lands in the home: `~/.local/bin/claude` (a symlink to the current version), `~/.local/share/claude/versions/<version>` (285 to 325 MB each), `~/.local/state/claude/`, `~/.cache/claude/`, and `~/.claude/`, `~/.claude.json`. Both versions stay on disk after an update (2.1.314 and 2.1.319: 610 MB for two). `XDG_DATA_HOME`, `XDG_STATE_HOME` and `XDG_CACHE_HOME` are honored by the installer and the updater, but the launcher link stays in `~/.local/bin`, and exporting those variables to the tool would redirect everything Claude Code starts, so the install does not redirect them.
  - *Consequences.* The installer's own paths are the **exception to the hard rule of 6.4** for an `UPDATE=self` tool: `~/.local/bin/claude`, `~/.local/share/claude`, `~/.local/state/claude`, `~/.cache/claude` (`~/.claude` and `~/.claude.json` are Claude Code's own: the vendor installer creates both, `install.sh` never writes them, and `remove` never deletes them). All are inside the workspace, so they survive `reset` (6.11). `tools/claude/self/` then holds only SwarmBox's record of the install (the fingerprint, 6.11); `swarmbox-tool remove claude` deletes the four paths above and keeps the user's data.
  - **4a.6 state (measured end to end through the shim).** `[verified: tests/test_tool_claude_real.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); the 4a-5 image (swarmbox-test-4a6-img), Claude Code 2.1.319, empty named volume as /home/agent, no login]` The first `claude --version` printed "Installing claude (first use)..." on stderr, then one stdout line `2.1.319 (Claude Code)` (about 13 s); a second call printed nothing on stderr; `~/.local/bin/claude` is a link into `~/.local/share/claude/versions/2.1.319`; `swarmbox-tool update claude` exits 0 ("Claude Code is up to date"; it warns that `~/.local/bin` is not on `PATH` in a non-interactive exec, which the image's `bashrc.sh` fixes for terminals); a before/after listing of `/usr /etc /opt /var /root` differs only under `/opt/npm-cache`; under `/home/agent` only `.local`, `.cache`, `.config` and `.claude*` appear, and `~/.local/share` holds `claude` and `swarmbox` only. With `--network=none` the first call exits non-zero with no stdout, leaves no record, link or version directory, and a later online call on the same volume installs. **Correction:** the vendor installer itself (run alone, before any `claude` call) creates `~/.claude/` and `~/.claude.json` (`"installMethod": "native"`, a machine and user id, and `"autoUpdates": false` with `"autoUpdatesProtectedForNative": true`, no login); the earlier text said the paths of the user's login were never touched, which is true of `install.sh` but not of the vendor script. Whether Claude Code's background update runs despite `"autoUpdates": false` was not observed [unverified]. Not measured: a second `update` that finds a newer version (only the 4a-0.3 spike did, 2.1.314 to 2.1.319, on node:24-slim). The shim finds the program through `~/.local/bin/claude`, which the updater repoints. The old versions are never pruned by Claude Code in the observed run: `swarmbox-tool doctor` may point out their size `[unverified]` (not measured over more than one update). Pinning a version is possible (`install.sh <version>`, and the updater then moves it anyway, which is what `UPDATE=self` means). The installer verifies its own download against the vendor's manifest; SwarmBox records no checksum for it (section 11).

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
   **4a.1 state** (`swarmbox-tool validate [DIR]`; `DIR` checks only that folder as one level, which is how CI checks `container/tools`; exit 0 all good, 1 a manifest failed, 64 usage). It reports every problem of every manifest, not only the first. Beyond the rules above it checks that `NAME` equals the folder name and is a plain lowercase word, that each `PROVIDES` entry is a plain command name (no `/`, so a shim cannot point outside its folder), that `UPDATE` is `managed` or `self`, and that a `SHA256_<arch>` is 64 hexadecimal digits. A manifest is loaded by **sourcing it in a subshell** with the known keys unset first: it is shell, so it runs arbitrary commands, which is why only the image and user levels are read (D18). A manifest that does not source (a syntax error, or a call to `exit`) fails `validate`; `link` reports it on stderr and skips it. The `install.sh` lint skips full-line comments, looks for the words `apt`, `apt-get` and `sudo`, and checks the destination of redirections and of `mkdir`, `touch`, `chmod`, `chown`, `rm`, `rmdir`, `tee` and the last argument of `cp`, `mv`, `ln` and `install`: a system path (`/usr`, `/etc`, `/opt`, `/var`...), a shell startup file, or a home path is refused; an `UPDATE=self` tool may write only `~/.local/bin`, `~/.local/share/<name>`, `~/.local/state/<name>` and `~/.cache/<name>`. It does not understand quoting, variables or sub-shells: **it is a lint, not a security check**.
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

For Claude Code installed with `npm install -g --prefix <dir in the home>`: the install wrote the prefix (325 MB, all in the home) and the npm cache (156 MB). The cache did **not** go into the prefix: the image sets
`NPM_CONFIG_CACHE=/opt/npm-cache` (v0.1.0's `Dockerfile` line 144 `[today]`), so it was written to `box:/opt/npm-cache`, in the container's own filesystem. Nothing was written in `/usr` or `/etc`. A reset therefore keeps the tool, and loses only that
cache, which is safe to lose; the installer rule (clean or redirect the cache; `/opt/npm-cache` owned by `agent`) is in 6.4 and 10.2.
`[verified: spike_b12_npm_sizes.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; Claude Code 2.1.319 from the npm registry, installed as uid 1000 with `NPM_CONFIG_CACHE=/opt/npm-cache`]`: prefix 325 MB, `/opt/npm-cache` 156 MB, `/home/agent/.npm` absent, no file in `/usr` or `/etc` newer than the prefix, and the installed `claude --version` runs. The sizes move with the version (the earlier 157 MB was the same measurement on an older release). The earlier reading "nothing in `/opt`" was wrong for the cache. The vendor's native installer, measured in the same way (B1, 6.7): 325 MB for 2.1.319 in `~/.local/share/claude/versions/`, written in the home (`~/.local/share`, `~/.local/state`, `~/.cache`, `~/.claude`, `~/.local/bin`), nothing in `/usr` or `/etc`, and a few `/opt/npm-cache` entries (npm's own log and update-notifier files; which process ran npm was not traced). The tool table below uses it for `claude`.

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
| `claude` | the vendor's native installer into the home (B1, 6.7); not npm | `claude` | `self` | none | `--dangerously-skip-permissions`, in v0.1.0's alias `[today]` | image content today |
| `gemini` | `npm install -g --prefix` of `@google/gemini-cli` | `gemini` | `managed`, `latest` | none | `--yolo`, in v0.1.0's alias `[today]` | image content today (npm global) |
| `opencode` | npm (`@opencode/cli`) under `$TOOL_PREFIX`, then prune the other platform builds, which saves 745 MB (6.4, B10) | `opencode` | `managed`, `latest` | `OPENCODE_CONFIG` (the config itself is rendered by `prepare.sh` from `LOCAL_LLM_*`) | `--auto` (B2), only for `yolo` (`YOLO_ALIAS=0`): no alias, because the flag fails before a subcommand | image content today |
| `gcloud` | Google's version-pinned tarball for `$TOOL_ARCH` (`x86_64` or `arm`), checksum computed and recorded in the manifest at release time (D29, B11: Google publishes one only for the unversioned name) | `gcloud gsutil bq` | `managed`, pinned | none | not an agent | image content today (apt package, `/usr`) |
| `clasp` | `npm install -g --prefix` of `@google/clasp` | `clasp` | `managed`, pinned | the `clasp` function adding `--redirect-port 43323` to `login`; `PORTS=43323` | not an agent | image content today (npm global) |
| `go` | official tarball from go.dev (`https://go.dev/dl/go<version>.linux-<arch>.tar.gz`, `amd64` or `arm64`) extracted under `$TOOL_PREFIX`, `SHA256_<arch>` copied from go.dev's JSON listing (B25) | `go gofmt` | `managed`, pinned | `GOPATH=$HOME/go`, `GOCACHE=$HOME/.cache/go-build` (Go's defaults, now under the home), `$GOPATH/bin` on `PATH` | not an agent | image content today (`/usr/local/go`, `GOPATH=/opt/go`) |
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
- *Pass the host value on every entry* (`podman exec -e NAME`): works for host tabs `[verified: spike_b12_exec_env.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` (three entries with `alpha`, `beta` and the variable unset: each saw the current host value, an unset variable gave an empty value, neither value was in `podman inspect` or in PID 1's environment) (the value follows a change on
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
├── Dockerfile.v0.1.0                # new: today's image, kept for build.sh until Phase 6 (decision [2.1])
├── dev/dev-build.sh                 # new: builds the image in the development box (apt override in a scratch copy)
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
| Helper archive | built in the image at `box:/usr/local/share/swarmbox/host/` (`swarmbox-host`, `VERSION`, `cloudflare-setup.py`, `templates/`, `tool-ports`); written on stdout by `host-helper` | the function, at bootstrap and `update` | first call, version change, `swarmbox update` |
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

**The helper archive.** The entrypoint's `host-helper` subcommand writes, as a tar archive on stdout, the contents of `box:/usr/local/share/swarmbox/host/`: `swarmbox-host`, `VERSION`, `cloudflare-setup.py`, `templates/` (bash, zsh, fish) and `tool-ports`
(generated at image build, 6.3). The function unpacks it into a temporary folder and checks that `swarmbox-host` is executable before renaming the folder into place (3.7.1). **3.5 state:** the Dockerfile copies `container/host/` (`swarmbox-host`, executable; `VERSION`; `templates/` with bash, zsh and fish) into the folder, next to `cloudflare-setup.py` and the generated `tool-ports`, and installs `swarmbox-init` as `box:/usr/local/bin/swarmbox-init`; `host-helper` tars the folder with owner 0 and the file modes kept and writes nothing else on stdout. The archive of the real image unpacks with plain `tar`, `swarmbox-host version` equals the image's `VERSION`, and `init` prints the same text from the unpacked templates as from the image's own `[verified: tests/test_entrypoint.py HostHelper, tests/test_dockerfile.py HostHelperArchive and the real image run by hand, see Part B 3.5; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-35-img (dev build of the 2.0 Dockerfile)]`. `swarmbox-tool` is the real program since Phase 4a (6.2; the `tool` subcommand forwards to it by `exec`): `tool-ports` is written by `link --system` at image build and stays empty until a manifest declares `PORTS` (the shipped `claude` declares none); `use`, `remove`, `doctor` and `new` exit 70 until Phase 4b.

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
  (`podman run --rm node:24-slim id node` prints `uid=1000(node) gid=1000(node)`; the built image has `id agent` = 1000 and no user `node` [verified: tests/test_image_build.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim and swarmbox-test-img-ba9849], B26). The Dockerfile renames it instead of adding a second user:
  `usermod -l agent node`, `groupmod -n agent node`, `usermod -d /home/agent -m agent`, `usermod -s /bin/bash agent`, and `agent ALL=(ALL) NOPASSWD: ALL` appended to `/etc/sudoers`.
  v0.1.0 does the same when the requested UID already exists (its `USER_UID` defaults to 1000) and otherwise creates the user with `groupadd` and `useradd` `[today]`; 2.0 keeps only the rename branch.
- **Directories:** `WORKDIR /home/agent`, which is the workspace mounted from the host.
- **Startup:** `ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]`, `CMD ["serve"]`. Subcommands:
  `serve` (the box's main process; the ordered steps and their failure behavior are in 4.1),
  `attach` (join the tmux session; what the host function runs on every entry, after linking the user tools),
  `init` (print the host function), `host-helper` (write the host helper archive on stdout), `pubkey`, `tool ...`, and any other command, which is run as given. `attach`, `init`, `pubkey` and `tool` replace the entrypoint by `exec` with the program's own exit status; a missing program is 127 (`init` is `swarmbox-init`, written in slice 3.5) `[verified: tests/test_entrypoint.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); fake programs on PATH]`. There is no `init.sh`: 10.3 says
  where its duties go.
- **Layer order:** stable first (system packages, Podman, pinned downloads), volatile last (scripts, manifests). A change
  to a manifest never invalidates the system layers.
- **Wiring the tools** (near the end, with the other volatile layers):

  ```dockerfile
  COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool
  COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim
  COPY container/tools/                   /usr/local/lib/swarmbox/tools/
  COPY container/host/ cloudflare-setup.py /usr/local/share/swarmbox/host/     # the helper archive, 9.3
  RUN chmod 755 /usr/local/bin/swarmbox-tool /usr/local/bin/swarmbox-shim && \
      chmod -R a+rX /usr/local/lib/swarmbox/tools && find /usr/local/lib/swarmbox/tools -name '*.sh' -exec chmod 755 {} + && \
      swarmbox-tool link --system   # also writes .../host/tool-ports
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
  clasp, Go and Poetry are roughly 2 GB `[verified: layer sizes of the v0.1.0 image on the maintainer's machine; command, date, Podman version and OS not recorded]`. B12 could not re-record this: no SwarmBox image exists in the build box, and rebuilding the owner's image was out of bounds; only parts were measured (the `node:24-slim` base is 225 MB and Claude Code under `--prefix` is 325 MB plus a 156 MB cache), so the 4.2 GB figure stays as recorded `[unverified]` (B12). The 2.5 GB figure is a budget. The 2.1 build measured **1.75 GB** (`podman image inspect` size 1751389476 bytes); per layer: base `node:24-slim` about 232 MB, system packages 617 MB, Podman and its network packages 102 MB, Chromium 689 MB, uv 53 MB, the Python venv 16 MB, `chrome-devtools-mcp` 13 MB, ttyd 1.4 MB, the rest (configuration, scripts, the page, Starship) under 25 MB. Chromium is the biggest single item (D24) [verified: podman image inspect and podman history; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-ba9849 built from the 2.1 Dockerfile, which has no tool preinstalled and a placeholder entrypoint] (B27).
- **Flavors (optional):** CI may also publish `-claude`-style tags built with `WITH_TOOLS`, for users who want zero first-run wait.
- **npm cache:** the image creates `box:/opt/npm-cache` owned by `agent` (created with the right owner, not `chown -R` afterwards) and sets `NPM_CONFIG_CACHE=/opt/npm-cache`. It must be owned by `agent`, because an `npm` run as root at build leaves root-owned entries
  that make a later `npm` as `agent` fail with `EACCES` (v0.1.0's `Dockerfile` comment around lines 332 to 334 `[today]`). Installers clean or redirect it (6.4). Found by the 2.1 image test: `npm cache clean --force` is not enough, it leaves a root-owned `_logs` folder and a stamp file in the cache, so the build's own `npm install -g` as root uses a separate cache (`--cache /tmp/npm-build-cache`) that it removes in the same `RUN`.
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
  administrator revoke sessions. Per Cloudflare's session-management documentation (`https://developers.cloudflare.com/cloudflare-one/identity/users/session-management/`, read 2026-11-08): for one application,
  Zero Trust > Access controls > Applications > the application > Edit > "Revoke existing tokens"; for one user across all applications, Zero Trust > Team & Resources > Users > select the user > Action > Revoke. Revoking does not block the user,
  who can log in again while the identity provider still accepts them; to cut access, disable the account at the identity provider first. Read from the documentation only, not tried in a dashboard (no Cloudflare account is used here)
  `[unverified]` (B14: documentation read, not tried; the dashboard's menu names change).
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
removes and re-adds it with `podman system connection` (Linux and WSL; today's `lib/podman-connection.sh` already replaces a connection whose address changed `[today]`). `[verified: tests/test_host_socket.py RegistrationTest (a connection at the old `<workspace>/.swarmbox/podman.sock` address is removed and added again at the new address, other names untouched) and RealPodmanIsolationTest (the same with the real `podman system connection` in a mktemp config); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: no real v0.1.0 box]`.

The migration is `container/scripts/swarmbox-migrate.sh` (installed as `swarmbox-migrate`), which `serve` runs as step 4 `[verified: tests/test_migration.py; 2026-11-08; fixture built from the v0.1.0 code in a mktemp workspace, not a real v0.1.0 workspace; Podman 4.3.1, Debian 12 (bookworm)]` (B29). How it behaves, where the table above leaves room:

- It runs at every start and acts only when `<workspace>/.swarmbox/` is a real directory (a link to one is not followed). It prints nothing when there is nothing to do.
- **Settings.** If `<workspace>/.claude/settings.json` is a link into `.swarmbox/` (the v0.1.0 link), it is replaced by a copy (written next to it, then renamed over the link). A real file that already exists is never overwritten: identical content lets the old copy go, different content keeps `.swarmbox/settings.json` and prints a line (merge by hand). A link that points elsewhere is the user's choice and stays. A link into `.swarmbox/` whose target is gone is removed, because Claude Code would otherwise write through it into the old folder.
- **`web-terminal.conf`** is moved only when the destination does not exist; otherwise both stay and a line says so. Only the exact name is moved: "any copies" of the table is read as files with other names, which are listed and left alone.
- **Deleted without following links:** `ttyd-index.html`, `opencode-local.json`, `podman.sock` (a file or a real socket) and every `*.log` and `*.lock` of the old folder. No recursive removal exists in the script.
- **`memory/`** is left with its content and mentioned in one line at every start while it exists. Any other file is listed in one line and left, so `.swarmbox/` stays.
- `.swarmbox/` is removed with `rmdir`, so only when empty.
- **Failure.** A step that fails (a read-only folder, a full disk) is reported on stderr, the other rows still run, the exit status is 1 and `serve` writes one health line ("layout migration failed ...") and goes on (W). Nothing is lost: the next start finishes the job (every row is idempotent).

No real v0.1.0 workspace was migrated: the fixture is derived from the v0.1.0 files (`init.sh`, `podman-service.sh`, `web-terminal.sh`, the `Dockerfile`), so a file those scripts did not write is not covered. The owner migrates a real workspace in Phase 6 (plan section 9), on a copy first.

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
| `helpers.py` | only `ROOT`, the repository root (4 lines); there are no shared fakes: each test writes its stubs inline (for example `STUB`, a fake `podman`, in `test_start_attach.py`) | **created** as the shared home of the fakes: `FakePodman` (built in Phase 1.3: a context manager that puts a fake `podman` first on `PATH`, records every call as a JSON line, and answers per subcommand with an exit code, stdout such as `create-flags` lines, stderr and an optional `--cidfile` write; unconfigured subcommands exit 0 silently; tested by `test_helpers.py`) and `FakeHostHelper` (built in Phase 1.4: a fake `swarmbox-host` in its own folder, called by absolute path; its `version` output is set by the test or printed as nothing, it can be missing or non-executable, it records calls in the same JSON-lines form and answers per command with exit code, stdout and stderr; an unconfigured command exits 64; `test_helpers.py` also holds a labeled prototype of the D33 bootstrap condition as an sh stub, not product code, to be replaced by the real function tests of Phase 3) |
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
   and the page is built. It **never touches a running box**: it uses its own names and workspace folder, and on a developer machine is run with an explicit opt-in. The file is `tests/smoke_image.py`; it runs in two modes. **Full** (`SWARMBOX_SMOKE_FULL=1`, CI or the owner's host) gives the box the nested-Podman flags and runs a container inside it. **Reduced** (`SWARMBOX_IMAGE_BUILD=1`, the development box, which is itself a container and cannot offer a third nesting level) starts the box with the test-only switch `SWARMBOX_TEST_NO_NESTED=1` and skips the nested steps (reported `SKIP`, never `PASS`); every reduced result carries the tag `[reduced: development box, no nested Podman in the box]`. Without either variable nothing runs. The steps that exist today are in the table of the results of slice 2.7 (Part B); the host-side checks of this layer arrive with Phase 3, when the helper exists: since slice 3.3 the steps `up-lifecycle` (up creates, a second up is the fast path with at most two podman calls, `url` calls no podman, reset replaces the container and keeps the volume and a workspace file, stop, then up starts the same container) and `up-busy-port` (exit 7 and nothing left behind; a container without the label refused with exit 5 for `up` and `reset` and still there) run against the real Podman with a recording `podman` wrapper. The exit-6 cases (a box that exits while starting, a marker that never appears) are checked with the fake `podman` of `tests/test_host_up.py`; the real exit 6 with the log lines was seen once, by accident, when `serve` stopped on a fatal error.
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

`[unverified]` whether the CI provider's macOS runner provides Podman for the function test; the function test uses a fake Podman, so it does not need it (B30). Slice 1.6 wrote `.github/workflows/ci.yml` with the probe step (the `macos` job, step "Probe for B30"); it is `[unverified]` until that job runs on a real macOS runner, and the first CI run closes it. Slice 2.7 added the job `smoke` (image build with the real `Dockerfile`, `tests/smoke_image.py` with `SWARMBOX_SMOKE_FULL=1`, the container tests on the same image, removal of the image by its exact name `swarmbox-test-img-ci`); it has never run (`[unverified]`: B28, the nested step and the full result of the whole smoke test wait for the first CI run). The migration test runs with the other unit tests. Slice 4a.7 made the `swarmbox-tool validate` step real (linux job), and slice 3.5 added the zsh and fish function tests. **Slice 3.7 added the rest of the Phase 3 jobs** (none of them has run; they are validated by `tests/test_ci_workflow.py` and `actionlint` only): the `arm64` job (`runs-on: ubuntu-24.04-arm`, the label GitHub documents for its hosted arm64 runners; a native build with `dev/dev-build.sh --tag swarmbox-test-img-ci-arm64`, with no QEMU and no `--platform`; it fails at once when `uname -m` is not `aarch64`; then `SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py`, where a skipped step fails the job; the image is removed by its exact name; nothing is pushed, no registry login, no port) which is B31 and stays `[unverified]` until its first run; a linux step that fails when `zsh`, `fish`, `dash` or `busybox` is missing (so a missing shell cannot turn a test into a skip) and a step that runs `tests/test_host_shells.py` and `tests/test_host_create_flags.py` under dash and busybox (B23); and, in the `macos` job, a probe that fails unless `/bin/bash` is a bash 3.x and `tests/test_function_bash.py` run with `SWARMBOX_TEST_BASH=/bin/bash`, which makes the function test use the macOS system bash 3.2 instead of the first `bash` in `PATH` (B19, B30). If the account cannot use the arm64 label the job stays queued or fails and the owner decides (decision log, slice 3.7).

## 14. Open questions

No design decision is open: all are taken and listed in the table "Decisions already taken" in the Overview (D1 to D39). Part B lists facts nobody has checked, each with the test that closes it. The body cites them as B1, B2... and the decisions as D1 to D39.

### Part B. Facts to verify

Each test below is run in a throwaway container or with fakes, never on the box that holds live sessions.

| ID | Fact | Test that closes it | Where cited |
|---|---|---|---|
| B1 | **Closed in 0.3 (6.7 carries the result).** Which Claude Code install method keeps its updater working (npm under `--prefix`, or the vendor's native installer into the home), and whether the native installer writes outside the home | In a throwaway container with an empty home: install each way, run `claude update`, compare a file listing of `/usr`, `/etc`, `/opt` and the home before and after | 6.7, 6.11, 6.12 |
| B2 | **Closed in 0.3 (6.6 carries the result).** OpenCode's auto-approve flag | Read OpenCode's documentation and `opencode --help` for the installed version; run it with the flag against a trivial prompt | 6.6, 6.12 |
| B3 | **Spiked in 0.1 (4.1, 5.1 carry the result); product test written in 2.2 and closed-reduced (results of slice 2.2), rechecked in 2.7 by the reduced smoke test; the full smoke test (nested Podman) stays `[unverified]` until CI.** `serve` works as the container's main process, and `swarmbox-web restart` restarts ttyd without stopping the box; `serve` as PID 1 handles SIGTERM and SIGINT (stops its children and exits), with and without `--init`, and with `WEB=0` blocks without ttyd | Run a test image with a throwaway name and workspace; kill ttyd; check the box stays up and the supervisor restarts it; `podman stop` time (well under the 10 s kill timeout) with `INIT=0`, `INIT=1` and `WEB=0`; send SIGINT with `podman kill --signal INT` | 4.1, 5.1 |
| B4 | **Closed in 0.4 (5.1 carries the result).** ttyd serves a single-file page only | Read ttyd's documentation for `--index`; try a page that references a second file | 5.1 |
| B5 | **Closed in 3.4 (3.5 carries the limit measured in 0.2; 3.7.2 "3.4 state" carries the helper's boundary tests).** The unix socket path limit and the helper's fallback | Create workspaces with paths of increasing length, start the Podman service, find where the connection fails (Linux; macOS if applicable) | 3.5 |
| B6 | The whole design on macOS (Podman machine): workspace sharing, `keep-id`, tun, the socket not crossing the VM | Run install, enter, reset, web terminal on a Mac; record every failure as a documented limit | 3.5, 3.6 |
| B7 | A host UID other than 1000 works with `keep-id:uid=1000,gid=1000` | Create a user with another UID, run a box, write files in the workspace, check ownership on the host | 3.6 |
| B8 | The lowest Podman version that works (4.3 is only the version observed) | Run the smoke test on 4.0, 4.3, 4.9 and the latest | 3.8 |
| B9 | **Closed in 0.1 (7.3 carries the result).** How tmux passes its environment to new windows, so browser and host tabs see the same variables | In a test image, start tmux with a variable, change the client's variable, open a window, print both | 7.3 |
| B10 | **Closed in 0.3 (6.4 carries the result).** The OpenCode size saving of about 720 MB also holds under `--prefix` | Install with `--prefix` in a throwaway container; measure before and after pruning | 6.4 |
| B11 | **Closed in 0.4 (6.4 carries the result and a correction: Google's published checksum is for the unversioned name only).** The gcloud download URL for both architectures, and whether Google publishes a checksum to compare the maintainer script's result with (D29) | Read Google's install documentation; download both archives; compare the computed checksum with any published value | 6.4, 6.12, D29 |
| B12 | **Re-recorded in 0.2, except the 4.2 GB image size (reduced, still `[unverified]`).** Re-record the checks whose setup was not recorded: `keep-id` option acceptance, the 325 MB and 157 MB install measurement, the image size of 4.2 GB, the symlink `$0` behavior, the host-value `podman exec -e` check | Repeat each in a throwaway container and note date, Podman version, OS, image | 3.6, 6.2, 6.11, 7.3, 10.2 |
| B13 | **Spiked in 0.1; closed in 2.3 (3.3 carries the result and the corrections).** `swarmbox <command>` (no `exec` of tmux; a window started detached with a `wait-for` channel and a status file): the call returns when the command ends, with its exit code; quoting survives; the aliases (including the agent auto-approve flag) and the `PATH` additions of the shell fragment apply in the command window; with standard output not a terminal, `podman exec` runs without `-t` and the output has no CRLF | Fake tmux test, then real tmux in a throwaway container: commands with spaces, quotes, `$`, exit codes 0, 1, 130 and a signal; `alias` and `PATH` check inside the window; `swarmbox pubkey > file` and a command piped through `od -c` look for `\r` | 3.3, 3.4, 13.3 |
| B14 | **Checked in 0.4, documentation only (11 carries the result); stays `[unverified]` until tried in a real dashboard.** Where Cloudflare Access sessions are revoked in the dashboard | Read Cloudflare's documentation and find the screen | 11 |
| B15 | Whether `python3` is present on a clean macOS. With a POSIX `sh` helper (D16) it matters only for `swarmbox remote` | Check a fresh macOS install; run `swarmbox remote status` on it | 3.8, 5.2 |
| B16 | **Partly checked in 0.4 (4.2 carries the result): the unit exists and covers `always` only on 4.3.1; the reboot itself is `[unverified]`.** Restarting a container created with `--restart` (the box would be one; the Cloudflare connector already is, `--restart=always`) after a host reboot works for rootless Podman and under what service (`podman-restart.service` for the user, which must be enabled) | Read Podman's documentation; test `podman-restart.service` for the user | 4.2 |
| B17 | **Closed in 0.1 (4.1 step 0 carries the result).** A `--tmpfs /tmp/swarmbox` mount is empty after `podman stop` and `podman start`, is writable by the `agent` user (with the `keep-id` mapping), and its default options (Podman may add `noexec`) do not break `serve` or the shells | Throwaway box with the flag: write a file, stop, start, list the folder, write as `agent` | 3.6, 4.1, 4.2 |
| B18 | **Closed in 0.1 (3.5 carries the result).** When `podman run -d` fails because a published port is in use, whether a container is left behind (state `Created`) and what exit status and message Podman gives | Throwaway box on a port that the test binds first; run `podman ps -a`, read the status and stderr | 3.5, 3.8 |
| B19 | **Linux part closed in 3.5 (3.6 "3.5 state" carries the result); macOS's `sort`, bash 3.2 and the CI images stay open for Phase 6.** `sort -V` exists and orders versions as the bootstrap needs (`2.0.9` before `2.0.10`) in macOS's `sort`, in the `sort` of the Linux distributions used, and when called from bash 3.2 and zsh (D33) | On a Mac and on each CI image run `printf '2.0.10\n2.0.9\n2.0.0\n' \| sort -V` and compare with the expected order; run the function test of 13.3 on the macOS runner | 3.6, 13.3 |
| B20 | **Closed in 3.6 against a local registry (3.8 carries the result); the real registry is rechecked in Phase 7.** Pulling the moving `X.Y` tag and reading the version from the extracted helper gives the exact `X.Y.Z` to record as `IMAGE`; `podman tag <repo>:X.Y <repo>:X.Y.Z` makes a local tag that a later `reset` uses with no network; `update --to TAG` pulls a given tag (D17, D33, D35) | In a test registry publish `2.0.0`, `2.0.1` and `X.Y`; run `swarmbox update` and `update --to 2.0.0`; read the config and the helper's `version`; disconnect the network and run `swarmbox reset` | 3.8 |
| B21 | **Linux part closed in 3.5 (3.1 and 3.7.5 carry the result); macOS through the Podman machine stays open for Phase 6.** The install line's `podman run --rm -e SHELL <image> init` delivers the host's `SHELL` to `init` (so `init` prints the right syntax by its basename, D20), including on macOS through the Podman machine, and a value that is not bash, zsh or fish gives bash | On a Mac (zsh) and a Linux host (bash, and with `SHELL=/usr/bin/fish` if fish is installed) run the install line without `--shell` and read the printed syntax; run it with `SHELL` unset | 3.1, 3.7.5 |
| B22 | **Linux part checked in 3.1 (3.7.3 carries the result); macOS and a WSL home stay open for Phase 6.** The helper keeps the config file at mode 600 whenever it holds the tunnel token, and refuses a looser mode, on Linux, macOS and a WSL home on a Windows drive (D28) | Fake helper test with `stat`; then on each platform: `config set CLOUDFLARE_TUNNEL_TOKEN`, read the mode, `chmod 644`, run `remote status`, check the warning and that the token is ignored | 3.7.3 |
| B23 | **Linux part checked in 3.1 (3.7.1 carries the result): dash, `bash --posix`, busybox, zsh in `sh` emulation and `/bin/sh`; macOS `/bin/sh` and bash 3.2 stay open for Phase 6.** The POSIX `sh` helper runs unchanged under macOS `/bin/sh`, dash and busybox `sh` (D16) | Run the helper's unit tests with each shell as the interpreter | 3.7.1 |
| B24 | **Closed in 2.1 (4.4, 10.1 carry the result).** The package `chrome-devtools-mcp`, installed with `npm install -g` at build, provides a program of that name that accepts today's options without `npx` (D23) | In a throwaway container install the pinned version, run `chrome-devtools-mcp --help`, start it with the registry's arguments and list its tools from an MCP client | 4.4, 10.1 |
| B25 | **Closed in 0.4 (6.12 carries the result).** Go's official tarball has a publisher checksum that the same maintainer script as gcloud's (D29) can record | Read go.dev's download page and its JSON listing; download both architectures; compare with the computed checksum | 6.12 |
| B26 | **Closed in 2.1 (10.2 carries the result).** The base image `node:24-slim` has a user `node` with UID and GID 1000 that the Dockerfile can rename to `agent` | `podman run --rm node:24-slim id node`; build the image and run `id agent` | 10.2 |
| B27 | **Closed in 2.1 (10.2 carries the result; the size is 1.75 GB).** The neutral image stays under about 2.5 GB | Build the image; `podman images` and `podman history`; record the size per layer | 10.2 |
| B28 | **Open after 2.7: the check is written (smoke step `nested-cgroup`, which also reads the engine settings of the image and prints the systemd-manager result) and runs only in CI (`SWARMBOX_SMOKE_FULL=1`, job `smoke` of `ci.yml`); `[unverified]` until that run.** The cgroup manager `cgroupfs` and the file event logger are the right settings for Podman inside the box (the reason is not written in v0.1.0's Dockerfile) | In a throwaway box run a nested container with the settings, then with the systemd manager, and read the errors | 10.5 |
| B29 | **Closed in 2.6 on a fixture (12.4 carries the result); the run on a copy of a real v0.1.0 workspace is left to Phase 6.** The layout migration (`.swarmbox/` to the XDG layout, every file of the table in 12.4) works and never overwrites an existing destination | The migration test of 13.3 layer 3 on a fixture workspace, then once on a copy of a real v0.1.0 workspace | 12.4, 13.3 |
| B30 | **Prepared in 1.6, still `[unverified]` until the first real run of `ci.yml`: the probe step of its `macos` job prints `/bin/bash --version` and `command -v podman`; no evidence tag is claimed.** The CI provider's macOS runner exists for the function tests (bash 3.2) and whether it provides Podman | Run a trivial workflow on the macOS runner: `/bin/bash --version`, `command -v podman` | 13.4 |
| B31 | **Open: the `arm64` job exists in `ci.yml` since 3.7 and has never run; `[unverified]` until its first CI run (then Phase 6 reads it).** The image builds for arm64 and the smoke test passes on an arm64 runner (nested Podman, `keep-id`, Chromium, the tools' `SHA256_arm64`) | The arm64 CI job of 13.4 (or `podman build --platform linux/arm64` under emulation, then the smoke test) | 10.4, 13.4 |
| B32 | **Refusal logic closed-reduced in 3.2 (3.5 carries the result); the real WSL run is Phase 6.** Which paths WSL2 mounts from Windows drives (`/mnt/<letter>/`) and that the refusal of D34 catches them (and does not refuse a Linux path such as `/mnt/data` that is not a Windows drive) | On a WSL2 machine run `findmnt -t 9p,drvfs`; `swarmbox up` with a workspace under `/mnt/c/...`, a `~/swarmbox` workspace and a bind-mounted `/mnt/<other>` | 3.5, 3.8 |
| B33 | **Closed-reduced in 3.3 (3.5 and 3.6 carry the result).** `up`'s lock and cleanup: `mkdir` is atomic and the stale rule never removes a live lock; `podman run --cidfile` leaves the ID of a container created by a failed run (or nothing) so that removal by ID removes only that container; two terminals at once create one box | The two-terminals test of 13.3 layer 5, with the fake `podman` and then a throwaway real box; B18 for the failed-run state | 3.5, 3.6, 13.3 |
| B34 | **Linux part checked in 3.1 (3.7.3 carries the result; the BSD form is simulated); macOS and a WSL home stay open for Phase 6.** The portable mode check (`stat -c %a`, `stat -f %Lp`, or `find -perm`) returns the octal mode on Linux, macOS and a WSL home, including for a file with extended attributes (`-rw-------@` on macOS) | On each host: create a file with mode 600 and 644, add an extended attribute on macOS, run each form, compare | 3.7.3 |
| B35 | **Closed in 3.3 (3.7.2 carries the result; the connection step of 3.4 adds one `podman system connection list` on the fast path, outside the two calls counted here).** The fast path of `up` (box exists and runs) needs at most two Podman calls before attaching, and costs little | Run `swarmbox` with a fake `podman` that counts calls (at most two before `attach`), then time it on a real box against `podman exec` alone | 3.7.2 |
| B36 | **Closed in 2.3 (3.4 carries the result).** `serve` creates `main` with one idle window that `attach` can recognize and close when it is the only other window, without closing a window a user created | Real tmux in a throwaway container: start `main` with the idle window, attach twice, list windows; type in a window before the second attach | 3.4, 4.1 |

#### Results of the Phase 0 spikes (slices 0.1 to 0.4; the state of each fact is in the outcome table after it)

Scripts are in `tests/spikes/` (not run in CI); each prints one `RESULT` line with its evidence tag and exits 1 if a claim of this design is contradicted. The shared image `swarmbox-test-spikes-img` is `node:24-slim` plus tmux 3.3a, procps and the box's pinned ttyd 1.7.7 binary (copied from the live box's `/usr/local/bin/ttyd`, a static executable of the same release).

| Fact | Result | Evidence |
|---|---|---|
| B5 | Closed. The AF_UNIX limit is **107 characters** (108 bytes with the NUL): identical on `/dev/shm` (tmpfs), on disk and inside a container; a 108-character path is refused (`AF_UNIX path too long` from Python, `connect: invalid argument` from `podman --url`). A service inside a container bound its 45-character container path while the host path was 131 characters; the host connected through a 45-character symlink to the same folder. **Rule (now in 3.5, new):** fall back to a short symlink to the state folder when the host-side socket path is longer than **100 characters**; the default workspace (about 54) is far below it, and 66 characters of workspace path fit before the fallback. | `[verified: spike_b5_socket_len.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); python:3.11-slim-bookworm; reduced: a Python stand-in for the Podman service, no macOS]` The helper's own tests (slice 3.4) assert 100 bytes direct, 101 symlink, and exit 4 beyond: `[verified: tests/test_host_socket.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); python:3.11-slim-bookworm; reduced: stand-in server, no real nested Podman service, no macOS]` |
| B12 keep-id | Re-recorded. `--userns=keep-id:uid=1000,gid=1000` is accepted; uid and gid 1000 inside, file ownership maps to the host user. `podman inspect` shows `private`, not `keep-id`: tests read `/proc/self/uid_map` (container 1000 to the invoking user, length 1). Host UID other than 1000 not tested (B7). | `[verified: spike_b12_keepid.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; reduced: host UID is 1000]` |
| B12 npm | Re-recorded. Claude Code 2.1.319 under `--prefix` in the home: 325 MB; npm cache 156 MB in `/opt/npm-cache` (not in the home); nothing in `/usr` or `/etc`; the binary runs. The 4.2 GB image was **not** re-measured (no SwarmBox image here; never rebuild the owner's); base `node:24-slim` is 225 MB. | `[verified: spike_b12_npm_sizes.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; reduced for the image size]` |
| B12 `$0` | Re-recorded per shell. Script run by shebang through a symlink, directly or via `PATH`: dash, bash, zsh, busybox sh all give the symlink's own name. Sourced file: `$0` in a function is `/usr/bin/dash`, `/usr/bin/bash`, the function name (zsh) or `sh` (busybox): the function must not use `$0` to find the helper. fish was not tested (not a POSIX shell; the fish wrapper is generated separately). | `[verified: spike_b12_symlink_arg0.sh; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); no image; reduced: on the box, not in a container]` |
| B12 exec -e | Re-recorded. `podman exec -e NAME` passes the host's value at each entry (a changed value follows, an unset variable gives an empty value) and the value is in neither `podman inspect` nor PID 1's environment. | `[verified: spike_b12_exec_env.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B17 | Closed. `--tmpfs /tmp/swarmbox` with `--userns=keep-id:uid=1000,gid=1000`: mounted `rw,nosuid,nodev,relatime` (**no `noexec`** on this Podman), writable by uid 1000 (mode 1777), empty after `podman stop` and `podman start`; a file outside the tmpfs survived (so the tmpfs is what clears the marker). Whether Podman versions other than 4.3.1 add `noexec` is B8's matter; nothing in the design executes from that folder, and the scripts there are run through an interpreter, which also worked. | `[verified: spike_b17_tmpfs.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B18 | Closed. A busy host port: `podman run -d` exits **126**, standard error `Error: rootlessport listen tcp 127.0.0.1:<port>: bind: address already in use`; the container is **left in state `Created`**; the `--cidfile` holds its 64-character ID; `podman rm -f <ID>` removed exactly that container and a bystander container stayed up. A name already in use: exit **125**, `the container name "X" is already in use by <id>`, **no cidfile**, the old container untouched. A `--cidfile` path that exists: exit 125, `container id file exists`. | `[verified: spike_b18_port_in_use.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B1 | Closed. Native installer: `claude update` works unconfigured (2.1.314 to 2.1.319), writes only in the home, keeps both versions (285 and 325 MB). npm under `--prefix`: `claude update` fails ("npm global folder isn't writable") unless `NPM_CONFIG_PREFIX` names the prefix. XDG variables are honored except for the launcher link. **Decision (6.7, new): `UPDATE=self` installs with the native installer.** | `[verified: spike_b1_claude_update.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]`Re-checked in 4a.6 through the shim in the 4a-5 image (first call installs, second does not, `update` exit 0, offline failure clean): `[verified: tests/test_tool_claude_real.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); the 4a-5 image]`. The vendor installer does create `~/.claude` and `~/.claude.json` (6.7 corrected). |
| B2 | Closed. `--auto` ("Auto-approve permissions that are not explicitly denied") on `opencode` and `opencode run` in `@opencode/cli` 2.2.6 and `opencode-ai` 1.19.5; not in the documentation pages fetched; **rejected before a subcommand** (`opencode --auto run` fails), so no alias: `YOLO_FLAGS` for `yolo` only. `run --auto` ran once with the free built-in model, no credentials (2.2.6 answered; 1.19.5 failed on a shared-home database error unrelated to the flag). | `[verified: spike_b2_opencode_flag.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim; reduced: TUI start with the flag not run (no terminal)]` |
| B10 | Closed. `@opencode/cli` 2.2.6 under `--prefix`: 992 MB, 247 MB after pruning (saved 745 MB), binary runs (hard link). `opencode-ai` 1.19.5: 409 MB to 205 MB (saved 204 MB). npm cache for both: 863 MB in `/opt/npm-cache`. | `[verified: spike_b10_opencode_prefix.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim]` |
| B9 | Closed. Windows get the **server's** environment whichever client asks (see 7.3); `update-environment` is the one setting that changes that. | `[verified: spike_b9_tmux_env.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img]` |
| B13 | Spiked, not closed (the real `swarmbox-attach` does not exist yet). Confirmed: exit codes, quoting, alias and `PATH`, no lost wake-up, grouped client ends by itself, no CRLF without `-t`. **Two corrections to the first design, now in 3.3**: the wrapper needs a HUP/TERM trap (else killing the window leaves the caller blocked forever), and the no-terminal path must not use `bash -ic` (it prints job-control errors) but a non-interactive bash that sources the fragment, whose guard accepts `SWARMBOX_CMD=1`. | `[verified: spike_b13_run_command.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: script(1) as the client terminal]` |
| B3 | Spiked, not closed (the real `serve` does not exist yet). Confirmed with a prototype: PID 1 with and without `--init`, `WEB=0`, stop in 0.14 s, SIGTERM exit 143 and SIGINT exit 130, ttyd restart and hand restart, crash loop gives up after 5 and the box stays up. **One correction, now in 4.2**: the supervisor must stay alive after it gives up, or the hand restart has nothing to reach. | `[verified: spike_b3_serve_pid1.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-spikes-img; reduced: bash stand-in for serve, the nested Podman service is a sleep]` |
| B4 | Closed. With `--index` on a page that references `style.css` and `app.js`: `GET /` serves the page, every sibling path (`/style.css`, `/app.js`, `/other.txt`, `/index.html`) is 404; ttyd's `/token` still answers. See 5.1. | `[verified: spike_b4_ttyd_index.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); the box's ttyd 1.7.7-40e79c7 on a random 127.0.0.1 port, no container; reduced: no container]` |
| B11 | Closed. URLs `https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli[-<version>]-linux-{x86_64,arm}.tar.gz`; Google's install page publishes sha256 for the **unversioned** names only (matched the computed values); the version-pinned archives are other bytes with other checksums but identical content, so the maintainer script computes the pinned file's checksum. See 6.4. | `[verified: spike_b11_b25_checksums.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); HTTPS reads and downloads, no container; gcloud 592.0.0; reduced: no container]` |
| B25 | Closed. go.dev's JSON listing `https://go.dev/dl/?mode=json` gives a sha256 per file; go1.27.3 linux-amd64 and linux-arm64 matched the computed values. See 6.4 and 6.12. | `[verified: spike_b11_b25_checksums.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); HTTPS reads and downloads, no container; go1.27.3; reduced: no container]` |
| B14 | Checked in documentation only: Zero Trust > Access controls > Applications > the application > Edit > "Revoke existing tokens" (one application), or Zero Trust > Team & Resources > Users > the user > Action > Revoke (one user). Not tried in a dashboard. See 11. | `[unverified]` (documentation read 2026-11-08, `developers.cloudflare.com/cloudflare-one/identity/users/session-management/`) |
| B16 | Partly checked. `--restart` alone does not survive a reboot (4.3.1 documentation); a user unit `podman-restart.service` exists (`WantedBy=default.target`) and selects `restart-policy=always` only: `unless-stopped` is **not** matched on 4.3.1 although documented as identical. The reboot itself and lingering are not tried (no systemd). See 4.2. | `[verified: spike_b16_restart_policy.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); debian:bookworm-slim; reduced: no systemd here, so no reboot and no `systemctl --user enable` was tried]` |

#### Phase 0 outcome (slice 0.5)

State of every Phase 0 fact, who closes what is left, and what could not be done here. "Closed" means a tagged result above and nothing left to check in Phase 0. "Reduced" means checked with a stand-in or in part. "Open" names the phase or person that closes it. The Part B table above is the authority for the wording of each fact.

| Fact | State | Owner | Note |
|---|---|---|---|
| B1 | Closed | none | Native installer for `UPDATE=self` (6.7). One update only; the npm route works only with `NPM_CONFIG_PREFIX`. |
| B2 | Closed | none | `--auto`, no alias, `YOLO_FLAGS` and `YOLO_ALIAS=0` (6.6). The package choice (`@opencode/cli` or `opencode-ai`) is the owner's, plan section 12. |
| B3 | Reduced | Phase 2 | Spiked with a bash prototype of `serve`; the real `serve` closes it. |
| B4 | Closed | none | 5.1. |
| B5 | Closed | Closed in 3.4 (the helper's tests; the spike of 0.2 fed it) | Limit 107 characters; the container half used a stand-in service, no macOS (the macOS part is B6). |
| B9 | Closed | none | 7.3. |
| B10 | Closed | none | 745 MB saved for `@opencode/cli`. |
| B11 | Closed | none | Correction: Google's checksum covers the unversioned URL only, D29 computes the pinned one. |
| B12 | Reduced | none left in Phase 2 (B27 closed in 2.1: the new image is 1.75 GB) | The 4.2 GB size of the v0.1.0 image stays unmeasured and `[unverified]` (never rebuild the box's); keep-id with host UID 1000 only (B7); fish not tested for `$0`. |
| B13 | Closed in 2.3 | none | Spiked in 0.1 with a stand-in; the real `swarmbox-attach` closes it (results of slice 2.3 below). |
| B14 | Open | owner | Documentation only, `[unverified]` until tried in a real Cloudflare dashboard (needs an account; not touched here). |
| B16 | Reduced | owner, on a host with systemd | Unit and policy checked on 4.3.1; the reboot itself is `[unverified]` (no systemd here). |
| B17 | Closed | Phase 2 rechecks it in the smoke test | 4.1 step 0. |
| B18 | Closed | Phase 3 uses it (B33) | 3.5. |
| B25 | Closed | none | 6.12. |
| B6 | Open, not doable here | owner, on a Mac, before M3 (Phase 6) | Needs macOS and a Podman machine. |
| B7 | Open, not doable here | owner or a CI matrix (Phase 6) | Needs a host UID other than 1000; this box is UID 1000 only. |
| B8 | Open, not doable here | owner or a CI matrix (Phase 6) | Needs older Podman versions (4.0, 4.9, latest); only 4.3.1 is installed and no registry change is allowed. |
| B15 | Open, not doable here | owner, on a clean Mac (Phase 6) | Needs a clean macOS. |

Also not doable here, rechecked later: the macOS parts of B19, B21, B22, B23 and B34 (Phase 6, after their Linux parts close in Phase 3) and the real-registry run of B20 (Phase 7). The spike scripts and how they become tests are listed in `tests/spikes/README.md`.

#### Results of Phase 2 (slice 2.1: the image)

| Fact | Result | Evidence |
|---|---|---|
| B24 | Closed. `chrome-devtools-mcp` 1.12.0 installed with `npm install -g` provides the program of that name; `--help` lists the registry's options; started with the registry's arguments it answered `initialize` and `tools/list` over stdio with 32 tools. Not tested: opening a page in Chromium (needs the box's run-time flags; Phase 5 or the smoke test). | [verified: tests/test_image_build.py plus an MCP stdio client; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-ba9849] |
| B26 | Closed. `node:24-slim` (Debian 12, Node 24.22.2) has `uid=1000(node) gid=1000(node)`; the rename gives `agent` UID and GID 1000 and no `node`. | [verified: tests/test_image_build.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); node:24-slim and swarmbox-test-img-ba9849] |
| B27 | Closed. 1.75 GB against the 2.5 GB budget (layers in 10.2). Chromium 689 MB and the base packages 617 MB dominate. | [verified: podman image inspect and history; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-ba9849] |

#### Results of Phase 2 (slice 2.2: serve)

| Fact | Result | Evidence |
|---|---|---|
| 2.2 B3 | Closed-reduced. The real `serve` (not the spike's stand-in) as PID 1 of a container from the 2.1 image: handlers give exit 143 (`podman stop -t 10`) and 130 (`podman kill --signal INT`), also under `--init`; `WEB=0` runs no ttyd; a killed ttyd comes back; the restart signal replaces ttyd; the crash loop, idle supervisor and hand restart are tested with fakes (`tests/test_serve_steps.py`). Reduced: no nested Podman in the box (`SWARMBOX_TEST_NO_NESTED=1`, so step 2 and step 8 are warnings), and the real `swarmbox-web` does not exist yet. | [verified: tests/test_serve_container.py and tests/test_serve_steps.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-s22a built from the 2.2 tree; reduced: development box, no nested Podman in the box (SWARMBOX_TEST_NO_NESTED=1), real swarmbox-web not written yet] (`podman stop -t 10` took 0.14 s, exit 143; marker `warnings=2`: the missing tun and the service not started) |
| 2.2 B17 | Rechecked with the real serve: a file written in `box:/tmp/swarmbox` is gone after `podman stop` and `podman start`, a file in the workspace stays. | [verified: tests/test_serve_container.py test_lifecycle_ready_stop_start_and_tmpfs; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-s22a; reduced: development box, no nested Podman in the box] |
| 2.2 B36 | Not closed in 2.2 (closed in 2.3, next table). `serve` creates `main` with `tmux new-session -d -s main` (one window); the idle window is a plain default window, not yet recognizable by `attach`, which is slice 2.3 or later; the check belongs to the `attach` slice (the idle window is recorded there). | [unverified] |

#### Results of Phase 2 (slice 2.3: swarmbox-attach)

| Fact | Result | Evidence |
|---|---|---|
| 2.3 B13 | Closed. The real `swarmbox-attach` with real tmux: exit codes 0, 1, 7, 127, 130, 137 and 143; a window killed from elsewhere gives 129 through the wrapper's trap; a wrapper killed with SIGKILL is noticed by the window-id poll and gives exit 1 with a message; 8 instant commands in a row lose no wake-up; 17 awkward arguments arrive byte for byte; an alias and a `PATH` addition of an interactive-only fragment apply in the command window; typed input reaches a command that reads; the command starts in the caller's directory; without a terminal tmux is not used, output has no CR (`od -c`) and standard error is empty; the grouped client ends by itself and no grouped session is left. In a container from the image, `attach false` exits 1, `attach true` 0, `attach sh -c 'exit 7'` 7, with and without a terminal. Reduced: the terminal is a pty made by the test, not a host terminal or ttyd; the real shell fragment does not exist yet, so alias and `PATH` were checked with a test fragment (`bashrc.sh` arrives in a later slice and must skip its banner for `bash -c`). | [verified: tests/test_attach_command.py (48 tests, isolated tmux -L swarmbox-test-<random>) and tests/test_attach_container.py (5 tests); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); tmux 3.3a; swarmbox-test-img-s23a; reduced: pty as terminal, test fragment] |
| 2.3 B36 | Closed. `serve` names the first window `idle`; two interactive `attach` calls in a box from the image give two windows of one session group (`main`, `main-1`, `main-2`) and no `idle` window; the windows outlive the tabs. A window that has a running command, was split or renamed is not closed. Command calls leave the idle window alone. | [verified: tests/test_attach_container.py test_two_attach_calls_share_one_session_as_two_windows_and_the_idle_window_is_gone and tests/test_attach_command.py b36 tests; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); tmux 3.3a; swarmbox-test-img-s23a] |

#### Results of Phase 2 (slice 2.6: layout migration)

| Fact | Result | Evidence |
|---|---|---|
| 2.6 B29 | Closed on a fixture. Every row of the table in 12.4 behaves as written; an existing destination (`web-terminal.conf`, a real `settings.json`, a link elsewhere) is never overwritten; `memory/` and unknown files stay and keep `.swarmbox/`; a second run changes nothing; a workspace without `.swarmbox/` is untouched and silent; an unwritable folder gives exit 1, one message, one health line from `serve`, no lost data, and the next run finishes the job. Not covered: a real v0.1.0 workspace (the fixture is derived from the v0.1.0 scripts and may miss a file they did not write). A real Unix socket as `podman.sock` is tested in a mktemp folder. | [verified: tests/test_migration.py (27 tests, including serve step 4 with the real script and a failing case); 2026-11-08; fixture, not a real v0.1.0 workspace; Podman 4.3.1, Debian 12 (bookworm); the script runs directly, no image needed] |

#### Results of Phase 2 (slice 2.7: smoke test and close-out)

`tests/smoke_image.py` has eight steps: `ready`, `tmpfs-restart`, `page-built`, `tool-validate`, `attach-session`, `no-agent` (reduced-capable) and `nested-podman`, `nested-cgroup` (full only). The reduced run in the development box passed 6 steps and skipped 2.

| Fact | Result | Evidence |
|---|---|---|
| 2.7 B3 | Rechecked, closed-reduced (unchanged state). In a box from the image: PID 1 is `swarmbox-entrypoint serve`, `podman stop -t 10` gives exit 143 in under 3 s, the supervised ttyd answers. The full run (nested Podman, readiness `ok`) is not done. | [verified: tests/smoke_image.py steps ready and tmpfs-restart; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-<random> built by dev/dev-build.sh; reduced: development box, no nested Podman in the box] |
| 2.7 B17 | Rechecked by the smoke test, as planned. A file in `box:/tmp/swarmbox` is gone after `podman stop` and `podman start`; the workspace file stays; the new run's marker appears. | [verified: tests/smoke_image.py step tmpfs-restart; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-<random>; reduced: development box, no nested Podman in the box] |
| 2.7 B13, B36 | Rechecked by the smoke test: `attach false` exits 1 and `attach true` 0; two terminal `attach` calls give two windows of one session group and no `idle` window; the tabs end with the tmux detach key. Both stay closed from 2.3. | [verified: tests/smoke_image.py step attach-session; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-img-<random>; reduced: development box, no nested Podman in the box] |
| 2.7 B24, B26, B27, B29 | No new check in 2.7; each stays closed on the evidence of 2.1 (B24, B26, B27) and 2.6 (B29, on a fixture only). The smoke step `no-agent` and the built-page step add a check that the image is neutral and the page is built. | see the results of slices 2.1 and 2.6 |
| 2.7 B28 | **Open.** The nested step `nested-cgroup` is written and skipped in the development box (a nested container needs `/dev/net/tun` and an unmasked `/proc` at the third level). It checks that `podman info` in the box reports `cgroupfs` and `file`, and prints the result of running a container with the systemd manager for the record. | [unverified] |

#### Results of Phase 3 (slice 3.1: the host helper core)

| Fact | Result | Evidence |
|---|---|---|
| 3.1 B22 | Linux part closed-reduced. With a file that holds `CLOUDFLARE_TUNNEL_TOKEN`, every mode other than 600 makes `config get`, `config list` and `env` ignore the token and print one line naming the mode and `chmod 600 <file>`; mode 600 accepts it; the environment value still wins; `config set` types the token on a pseudo-terminal with no echo (the terminal never shows it), refuses it on the command line and without a terminal, restores the terminal, and writes nothing when `chmod` fails (a fake `chmod` first in `PATH`). macOS and a WSL home on a Windows drive are not tested. | [verified: tests/test_host_config.py TokenTest; 2026-11-08; Debian 12 (bookworm) host; no Podman involved; reduced: Linux only] |
| 3.1 B23 | Linux part closed-reduced. The same scenario of about 40 helper calls (config set, get, list, seed, env, the token mode rule, a second box) passes under `dash`, `bash --posix`, `busybox sh`, `/bin/sh` and `zsh --emulate sh`, and under bash started as `sh` (a symlink); `shellcheck -s sh` reports nothing; a grep test rules out `local`, `echo -e`, `read -s`, `[[ ]]`, arrays, `source` and `$'...'`. macOS `/bin/sh` (bash 3.2 in POSIX mode) and a real bash 3.2 are not here. | [verified: tests/test_host_shells.py; 2026-11-08; Debian 12 (bookworm) host; dash, bash 5.2, busybox, zsh 5.9; reduced: no macOS, no bash 3.2] |
| 3.1 B34 | Linux part closed-reduced. `stat -c %a`, the BSD form `stat -f %Lp` (simulated by a shim) and `find -perm` give the same octal mode for 600, 644, 640, 400, 666, 4755 and 1777 (`find` also 2755, 7777 and 1600); a file with a user extended attribute is read as 600 by all three; a fake `ls` printing `-rw-------@` is never called. | [verified: tests/test_host_config.py ModeCheckTest; 2026-11-08; Debian 12 (bookworm) host; reduced: BSD `stat` simulated, no real macOS, no WSL home] |

#### Results of Phase 3 (slice 3.2: create-flags, fingerprint and the workspace checks)

| Fact | Result | Evidence |
|---|---|---|
| 3.2 B32 | Closed-reduced. With `/proc/version` faked as a WSL2 kernel string, `/mnt/c/...`, `/mnt/d/x`, `/mnt/C/...`, `/mnt/c` and `/mnt/z/...` are refused with exit 4 and the exact text of D34 before anything is created; `/mnt/wsl/...`, `/mnt/data/...`, `/mntx/c` and `/mnt/cc` are not refused; with a kernel string without `microsoft`, `/mnt/c/...` is not refused; a symlink to a Windows path is refused. The helper reads the real `/proc/version` when no override is given (the box this ran in is itself a WSL2 machine, and that case agrees with the probe). Nothing under `/mnt` was created. A real WSL machine with a real Windows drive was not available: the exact set of paths WSL mounts, and the behavior of a workspace on `\\wsl$`, stay `[unverified]`. | [verified: tests/test_host_create_flags.py WorkspaceTest; 2026-11-08; no Podman involved, Debian 12 (bookworm) host; no image; reduced: a fake /proc/version and fake paths, never a real WSL or a real Windows drive] |
| 3.2 B7, B12 | No change: the flag `--userns=keep-id:uid=1000,gid=1000` is emitted as the golden file says; a host UID other than 1000 is still not tested (Phase 6 or a CI matrix). | `[unverified]` as before |

#### Results of Phase 3 (slice 3.3: up, reset, stop, url)

| Fact | Result | Evidence |
|---|---|---|
| 3.3 B33 | Closed-reduced. `mkdir` made exactly one box in ten rounds of eight real processes started together (the others took the fast path and exited 0); `SIGTERM` and `SIGINT` removed the lock and left no `podman run` (exit 143 and 130); `SIGKILL` left the lock and the next call removed it by the dead pid; a lock without a pid file went stale after the tuned wait; a live holder was waited for, then exit 6 naming the lock, and the lock stayed. With the real Podman, a busy `WEB_PORT` made `up` exit 7, the cidfile held the ID, `podman rm -f <id>` removed the `Created` container and no container with the name was left; a container named like the box without the label was refused with exit 5 for `up` and `reset` and was still there. | [verified: tests/test_host_up.py LockTest and CreateTest, tests/smoke_image.py up-busy-port; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-3-img (dev build of the 2.0 Dockerfile); reduced: development box, fake podman for the races, no macOS] |
| 3.3 B35 | Closed. Fast path: two Podman calls (`container inspect`, `image inspect`), 0.09 s, against 0.11 s for one `podman exec <box> true`. | [verified: tests/test_host_up.py FastPathTest, tests/smoke_image.py up-lifecycle; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-3-img (dev build of the 2.0 Dockerfile); reduced: development box, no nested Podman in the box] |
| 3.3 B18 | Reused for the cleanup. A rejected option other than a busy port was not run for real. | `[unverified]` for the other causes |
| 3.3 finding | The nested-storage mount point must be made by the helper: Podman made `.local` and `.local/share` owned by the container's root and `serve` stopped with "cannot create the SwarmBox folders". With the helper making `<workspace>/.local/share/containers` first, the real box reached readiness. | [verified: tests/smoke_image.py up-lifecycle (failed before the fix, passed after) and a manual `podman run` with the same flags; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-3-img; reduced: nested level of the development box] |

#### Results of Phase 3 (slice 3.5: swarmbox-init, the templates and the function)

| Fact | Result | Evidence |
|---|---|---|
| 3.5 B21 | Linux part closed. `podman run --rm -e SHELL <image> init` printed the fish text with `SHELL=/usr/bin/fish`, the zsh text with `/bin/zsh`, and the bash text with `/bin/dash`, with an empty `SHELL` and with `SHELL` unset (`-e SHELL` of an unset variable passes nothing); an explicit unknown `--shell tcsh` exited 2 with the text of 3.8. macOS through the Podman machine is not here. | [verified: `podman run --rm -e SHELL swarmbox-test-35-img init` by hand and tests/test_init_output.py (Shell); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-35-img (dev build of the 2.0 Dockerfile); reduced: Linux host only] |
| 3.5 B19 | Linux part closed. `printf '2.0.10\n2.0.9\n2.0.0\n' \| sort -V` gives `2.0.0 2.0.9 2.0.10` with GNU coreutils 9.1 on the development box and inside the image. The function keeps the helper, with no notice and no error output, when `sort` has no `-V` (a shim that rejects it), under bash, `bash --posix`, zsh and fish. Not run: macOS `sort`, the `ubuntu-latest` and `macos` CI images, bash 3.2 (only `bash --posix` and a lint). | [verified: tests/function_cases.py (sort cases), the image run above; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); swarmbox-test-35-img; reduced: no macOS, no CI image] |
| 3.5 bootstrap | The real function (bash, `bash --posix`, zsh, fish) extracted the helper from the real image on a first call with an empty data folder (a `podman run --rm <image> host-helper` through a temporary folder), then `swarmbox version` printed the image's `2.0.0` and the second call made no extraction. The fake-Podman table covers missing, non-executable, no-version, old, equal, newer (2.0.10 against 2.0.9), a failing `tar`, an empty, corrupt, truncated and helper-less archive, offline, podman absent, update-then-next-call and rollback. | [verified: tests/test_function_bash.py, test_function_zsh.py, test_function_fish.py (130, 65 and 64 tests) and the by-hand run on swarmbox-test-35-img; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm), bash 5.2.15, zsh 5.9, fish 3.6.0; reduced: bash 3.2 and macOS not run] |

#### Results of Phase 3 (slice 3.6: update and the local registry)

| Fact | Result | Evidence |
|---|---|---|
| 3.6 B20 | Closed against a local registry. With `2.0.0` and the moving `2.0` published, then `2.0.1` published and `2.0` moved: `swarmbox update` pulled `<repo>:2.0`, read `2.0.1` from the extracted helper's `version`, made the local tag `<repo>:2.0.1` (same image ID as `2.0`; no local `2.0.1` existed before), wrote `IMAGE=<repo>:2.0.1`, left the running box untouched (same container ID, label still `2.0.0`) and printed the exact line of 3.8. With the registry stopped: `update` exited 3 with the config, the helper and the box unchanged, and `reset` exited 0 with no `pull` call and a box labelled `<repo>:2.0.1`. `update --to 2.0.0` (lower) and `--to 2.1.0` (higher, other series) wrote the exact version and the matching helper; `--to 'bad tag'` exit 2; `--to 9.9.9` (absent) exit 3, nothing changed. Same result in bash, zsh and fish. | [verified: tests/e2e_registry.py (opt-in, SWARMBOX_E2E=1; 40 steps PASS) and tests/test_host_update.py (34 tests); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); registry:2 in a throwaway container on 127.0.0.1, placeholder org `placeholder-org`; swarmbox-test-36-img (dev build of the 2.0 Dockerfile) plus derived 2.0.1 and 2.1.0; reduced: boxes without nested Podman, no real registry, no macOS or arm64]
| 3.6 install line | The line of 3.1 (`podman run --rm -e SHELL <image> init --with claude >> rc`, the registry substituted and `--image` added) printed the function; the first call pulled the image from the registry, extracted the helper and created the box; a second call took the fast path (two Podman calls before the exec, 0.2 s through the function); two terminals started at once made exactly one container (in every shell, also when started before the helper existed: one trial each, not asserted); two real terminals (ptys) shared the session `main` of one box; `stop` then the next call started the same container. | [verified: tests/e2e_registry.py (opt-in, SWARMBOX_E2E=1; 40 steps PASS) and tests/test_host_update.py (34 tests); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); registry:2 in a throwaway container on 127.0.0.1, placeholder org `placeholder-org`; swarmbox-test-36-img (dev build of the 2.0 Dockerfile) plus derived 2.0.1 and 2.1.0; reduced: boxes without nested Podman, no real registry, no macOS or arm64]
| 3.6 finding | The `registries.conf` of a scratch `XDG_CONFIG_HOME` is not read by Podman 4.3.1 for an insecure registry (it looks under `$HOME/.config/containers/`); `CONTAINERS_REGISTRIES_CONF` works. A scratch `XDG_DATA_HOME` makes Podman look for its image store there: the e2e writes a `containers/storage.conf` into the scratch `XDG_CONFIG_HOME` that points at the real store (`CONTAINERS_STORAGE_CONF` is not read by rootless 4.3.1). | [verified: by hand and in tests/e2e_registry.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); registry:2 and swarmbox-test-36-img] |
| 3.6 B35 | Re-measured on a real throwaway box through the function: the fast path made two Podman calls before the `exec` (plus the connection list), 0.20 to 0.23 s for the whole `swarmbox echo` call. | [verified: tests/e2e_registry.py (opt-in, SWARMBOX_E2E=1; 40 steps PASS) and tests/test_host_update.py (34 tests); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); registry:2 in a throwaway container on 127.0.0.1, placeholder org `placeholder-org`; swarmbox-test-36-img (dev build of the 2.0 Dockerfile) plus derived 2.0.1 and 2.1.0; reduced: boxes without nested Podman, no real registry, no macOS or arm64]

#### Results of Phase 3 (slice 3.7: close-out)

One row per Part B fact that Phase 3 closes, with the slice that carries the evidence. The evidence tags are the ones of the slices named; this table adds the state and, for B31, the job that waits for a runner. The Linux parts are what the development box can run (Podman 4.3.1, Debian 12 (bookworm), a container with no nested Podman at the third level, no macOS, no arm64).

| Fact | State | Where | Evidence |
|---|---|---|---|
| 3.7 B5 | closed | 3.4: `tests/test_host_socket.py`, the limit of 0.2 (107 characters) and the fallback above 100 | [verified: tests/test_host_socket.py (27 tests); 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: no macOS (B6, Phase 6)] |
| 3.7 B19 | reduced (Linux closed) | 3.5: `sort -V` in the function's bootstrap, `tests/test_function_bash.py` and the zsh and fish files; 3.7 added `/bin/bash` 3.2 to the macOS job | [verified: tests/test_function_bash.py; 2026-11-08; Debian 12 (bookworm), GNU sort; reduced: Linux only] [unverified: macOS `sort`, bash 3.2 and the CI images, Phase 6] |
| 3.7 B20 | closed against a local registry | 3.6: `tests/test_host_update.py` and the opt-in `tests/e2e_registry.py` (40 steps) | [verified: tests/test_host_update.py and tests/e2e_registry.py against registry:2 on 127.0.0.1; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: no real registry] [unverified: the real registry, Phase 7] |
| 3.7 B21 | reduced (Linux closed) | 3.5: `-e SHELL` reaches `init` (`tests/test_init_output.py`, the install line of the e2e) | [verified: tests/test_init_output.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: Linux only] [unverified: macOS through the Podman machine, Phase 6] |
| 3.7 B22 | reduced (Linux closed) | 3.1: `TokenTest`; 3.7 added `TokenJourneyTest`, one story from `config set` on a pty through the environment value and the 644 refusal back to 600 | [verified: tests/test_host_config.py TokenTest and TokenJourneyTest; 2026-11-08; Debian 12 (bookworm) host; no Podman involved; reduced: Linux only] [unverified: macOS and a WSL home on a Windows drive, Phase 6] |
| 3.7 B23 | reduced (Linux closed) | 3.1: `tests/test_host_shells.py` under dash, `bash --posix`, busybox, zsh in `sh` emulation and `/bin/sh`; 3.7 made CI fail when dash or busybox is missing | [verified: tests/test_host_shells.py; 2026-11-08; Debian 12 (bookworm) host; dash, bash 5.2, busybox, zsh 5.9; reduced: no macOS] [unverified: macOS `/bin/sh` and bash 3.2, Phase 6] |
| 3.7 B31 | open | the `arm64` job of `.github/workflows/ci.yml` (3.7), written and checked by `tests/test_ci_workflow.py` and actionlint 1.7.12, never run; waits for the first CI run on an arm64 runner | [unverified] |
| 3.7 B32 | reduced (logic closed) | 3.2: `tests/test_host_create_flags.py` WorkspaceTest with a fake `/proc/version` | [verified: tests/test_host_create_flags.py; 2026-11-08; Debian 12 (bookworm) host; reduced: fake `/proc/version`] [unverified: a real WSL machine and a Windows-drive workspace, Phase 6] |
| 3.7 B33 | reduced (closed-reduced) | 3.3: `tests/test_host_up.py` lock tests, ten rounds of eight real processes, and the e2e's two terminals | [verified: tests/test_host_up.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: fake Podman and boxes without nested Podman] |
| 3.7 B34 | reduced (Linux closed) | 3.1: `ModeCheckTest` with the BSD `stat` form simulated | [verified: tests/test_host_config.py ModeCheckTest; 2026-11-08; Debian 12 (bookworm) host; reduced: BSD `stat` simulated] [unverified: a real macOS and a WSL home, Phase 6] |
| 3.7 B35 | closed | 3.3: two Podman calls on the fast path; re-measured through the function in 3.6 | [verified: tests/test_host_up.py and tests/e2e_registry.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: no macOS] |

Not tested here, and where it goes: arm64 (the `arm64` job, B31); macOS bash 3.2 (the `macos` job, B19, B30); macOS `sh`, `stat` and `sort` (Phase 6, B19, B23, B34); a real WSL path and a Windows-drive workspace (Phase 6, B32, B22); a host UID other than 1000 (B7, Phase 6); Podman older than 4.3 (B8, Phase 6); the real registry and the install line against it (B20, Phase 7); the third nesting level, so the nested container and `nested-cgroup` (B28, CI smoke job).

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
