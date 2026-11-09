# SwarmBox

**Run AI coding agents with full tool access and auto-approve ("YOLO") mode inside a Podman container, so your host stays safe.**

```bash
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude >> ~/.bashrc    # then open a new terminal and run: swarmbox
```

Read what it prints first (leave out the `>> ~/.bashrc`). `<org>` is a placeholder until the first release; details are under [Install](#install) and in [docs/design.md](docs/design.md).

- **Isolated:** the agent runs in a rootless Podman container; no host Podman socket is mounted.
- **One command:** `swarmbox` creates the box on first use and joins it afterwards. Every terminal shares one tmux session.
- **Agents on demand:** `claude` is installed on first use, into your workspace, not into the image. Gemini, OpenCode, `clasp`, Go, gcloud and Poetry are tools you choose.
- **Nested Podman:** agents can build and run their own containers inside the box.
- **MCP built in:** headless Chromium through the chrome-devtools MCP.
- **Web terminal:** a browser shell on `127.0.0.1`, with an optional Cloudflare Tunnel for remote access.

## Requirements

Linux, macOS (through a Podman machine) or WSL2 with the workspace on the Linux filesystem, and Podman 4.3 or newer (Docker is not supported):
`sudo apt install podman`, `sudo dnf install podman` or `brew install podman`. macOS, WSL and Podman older than 4.3 are
[unverified] here; the status is in [docs/design.md](docs/design.md), Part B.

## Install

One line, once. It prints a shell function; read it first, then append it to your shell startup file (the example is bash; for zsh use `~/.zshrc`, for fish `~/.config/fish/config.fish`):

```bash
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude            # print the function
podman run --rm -e SHELL ghcr.io/<org>/swarmbox:2.0.0 init --with claude >> ~/.bashrc
```

`<org>` is a **placeholder**: the image is not published yet, so the line does not work until a release names the real registry.
To try it today, use a local registry ([docs/local-registry.md](docs/local-registry.md)) and add `--image <ref>`.
`init` only prints; it changes nothing on your machine. Add `--workspace ~/code/box` to choose the workspace folder (default `~/swarmbox`).

## First use

Open a new terminal, so the function exists, and run:

```bash
swarmbox            # the first call pulls the image, creates the box, and opens a shell in it
```

Inside, `claude` installs Claude Code on its first call and runs it with auto-approve (`yolo` starts your default agent the same way).
`init --with claude` recorded `WITH=claude`, so the install starts when the box does. Tools: `swarmbox tool list`.

```bash
swarmbox --plain                      # plain bash instead of the tmux session
swarmbox claude                       # run a command in the box from the host; its exit status is yours
swarmbox config list                  # the host configuration
swarmbox config set WITH claude,gemini
swarmbox env add CLAUDE_CODE_OAUTH_TOKEN   # pass a host variable into the box (names only are stored)
swarmbox reset                        # recreate the box so a changed setting applies; the workspace is kept
swarmbox stop                         # stop the box; nothing is deleted
```

- **Web terminal:** on by default. `swarmbox url` prints the address, `http://127.0.0.1:7681` unless you set `WEB_PORT`. That port has no login.
  [docs/web-terminal.md](docs/web-terminal.md) has the style and the tmux shortcuts.
- **Remote access:** `swarmbox remote setup` puts Cloudflare Tunnel and Access in front of it. See [docs/cloudflare.md](docs/cloudflare.md).
- **Containers inside the box:** [docs/nested-podman.md](docs/nested-podman.md). From the host: `podman -c swarmbox ps`.
- **Update and roll back:** `swarmbox update` pulls the newest image of your `X.Y` series and tells you to run `swarmbox reset`;
  `swarmbox update --to 2.0.0` goes to an exact tag, also an older one.
- **A second box:** `SWARMBOX_NAME=dev` names it, and it has its own configuration. Give it its own folder and port:

```bash
SWARMBOX_NAME=dev swarmbox config set WORKSPACE ~/code/dev
SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682
SWARMBOX_NAME=dev swarmbox
```

## Migrating from v0.1.0

v0.1.0 started the box with `start.sh` and built it with `build.sh`; both are gone, and the layout inside `.work/` changed.
**Back up your workspace first** (with the old container stopped, `cp -a .work .work.backup`), then follow
[docs/migration.md](docs/migration.md): the exact order, the commands, and a way to try the migration on a copy of your workspace first.
The old files stay in the git tag `v0.1.0`.

## Uninstall

There is no `swarmbox uninstall` command. Do these by hand, in this order (`sed -i.bak` keeps a copy of the file it edits):

1. Remove the function block from your startup file: the one-line comment above it and every line from `# >>> swarmbox 2.0.0 >>>` to `# <<< swarmbox 2.0.0 <<<`. The version in the markers is the one you installed, and a second `init` run leaves a second block. For bash: `sed -i.bak -e '/^# swarmbox [0-9.]*: the shell function printed/d' -e '/^# >>> swarmbox /,/^# <<< swarmbox /d' ~/.bashrc` (use `~/.zshrc` for zsh, `~/.config/fish/config.fish` for fish).
2. Stop and remove the box: `podman rm -f swarmbox`, and the host connection `podman system connection rm swarmbox` (an error that none exists can be ignored). For a second box give its `SWARMBOX_NAME` instead of `swarmbox`, one box at a time.
3. Remove the host helper and its state: `rm -rf ~/.local/share/swarmbox/host`, and `rm -rf ~/.local/state/swarmbox` (locks and notices).
4. Remove the host configuration: `rm -rf ~/.config/swarmbox` (the config, `cloudflare.json`, the folders of second boxes; it may hold the tunnel token).
5. If you set up remote access, run `swarmbox remote off` **before step 1**: it removes the DNS record, the route and the Access application. Then remove the connector: `podman rm -f swarmbox-cloudflared`.
6. Optional: the workspace folder `~/swarmbox` (your projects, logins and tools; back up what you need) and the nested Podman volume, `podman volume rm swarmbox-containers` (`<name>-containers` for a second box).
7. Optional: the image, `podman rmi ghcr.io/<org>/swarmbox:<tag>`.

## Privacy

SwarmBox sends **no telemetry**. It makes no network call of its own except to pull the image, to install a tool you asked for,
to check for a tool update, and, with `swarmbox remote`, to reach Cloudflare. Logs stay on your machine:
`<workspace>/.local/state/swarmbox/` holds `serve.log`, `health` and `web-terminal.log`; on the host only `~/.local/state/swarmbox/` exists (locks and `notices`).

## More

[docs/design.md](docs/design.md) (what it is and why), [docs/implementation-plan.md](docs/implementation-plan.md),
[docs/decision-log.md](docs/decision-log.md), [CONTRIBUTING.md](CONTRIBUTING.md), [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [SECURITY.md](SECURITY.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [CHANGELOG.md](CHANGELOG.md).
