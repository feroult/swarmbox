# SwarmBox

**A persistent, rootless Podman box where AI coding agents run in auto-approve mode and have room to work, with a mistake limited to one folder of your machine.**

Give an agent a box of its own: it can install tools and build and run containers, and you keep your machine, your Podman and your credentials out of reach.
Open any terminal tab or the browser and you are in the same box and the same session.

- **One box, shared.** Every terminal tab and the browser join the same box and the same tmux session. Entering never creates a second box.
- **The workspace is one folder on your machine.** Projects, logins, the SSH key and installed tools live there. You can delete and recreate the box and lose nothing.
- **Auto-approve, with a smaller blast radius.** The agent runs without approval prompts, and a mistake is limited to that folder (see [Security](#security)).
- **A neutral image, tools on demand.** Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry are installed the first time you use them.
- **Containers inside the box.** Agents can build and run their own containers with nested Podman, with no path to your Podman.
- **A browser inside the box.** Chrome DevTools MCP is built in.
- **A web terminal.** It listens on your machine only. Optional remote access goes through Cloudflare Tunnel and Access, with an e-mail code.
- **A git SSH key.** The box has one that you can hand out as a deploy key.

## How it feels

```bash
# install once (see Quick start), then, in any terminal:
swarmbox        # creates the box the first time, joins it afterwards
claude          # inside the box: installs Claude Code on first use, then runs it in auto-approve mode
```

Open a second tab, run `swarmbox` again, and you are in the same session.

## Security

SwarmBox is a persistent box for letting an agent work on its own: it can install tools, build and run containers (nested Podman) and
create whatever it needs, while a mistake stays inside one workspace folder. It is rootless Podman, and it is **not complete isolation**: like any
container it shares the kernel with your machine and has the known limits of that model. If you need a stronger boundary, run SwarmBox inside a
virtual machine, a microVM or a dedicated machine (see [docs/microvm.md](docs/microvm.md)).

**What the box gives you:**

- A rootless container: even root inside it is an unprivileged user of your machine.
- The agent sees only the workspace folder, not the rest of your files.
- Your machine's Podman socket is never mounted into the box.
- The web terminal listens only on `127.0.0.1`.
- Cloudflare credentials and the connector stay on your machine, outside the box.
- The box is disposable: delete and recreate it and the workspace stays.

**What the agent can do inside it:**

- Change or delete everything in the workspace (projects, logins, SSH key).
- Use `sudo` in the box and reach the network.
- Read every token you pass in and use the SSH key.
- Keep running while you are away, until you stop the box.

Nested Podman and remote access trade some isolation for capability. Nested Podman is always on and needs `/dev/net/tun` and an unmasked `/proc`.
With remote access on, whoever passes the Cloudflare login has the same control as the agent.

**Practical advice:** pass scoped tokens, use a deploy key per repository, review changes with `git diff`, do not expose the web port yourself
(use `swarmbox remote setup` for access from outside), and keep Podman and the kernel up to date.

More in [SECURITY.md](SECURITY.md) and the security model of [docs/design.md](docs/design.md).

## Quick start

Requirements: Podman 4.3 or newer on Linux, or WSL2 with the workspace on the Linux filesystem (macOS through a Podman machine is unverified).
Docker is not supported.

The image is not published yet, so today you build it locally. In the repository:

```bash
podman build -t localhost/swarmbox-dev:local .
podman run --rm localhost/swarmbox-dev:local install --with claude --image localhost/swarmbox-dev:local        # read what it prints
podman run --rm localhost/swarmbox-dev:local install --with claude --image localhost/swarmbox-dev:local | sh
```

This writes one script, `swarmbox`, to `~/.local/bin` (set `SWARMBOX_BIN_DIR` to use another folder), and records the image and the tools in
`~/.config/swarmbox/config`. It edits no startup file; if `~/.local/bin` is not in your `PATH` it says how to add it. Open a new terminal and
run `swarmbox`. If port 7681 is busy, run `swarmbox config set WEB_PORT 7682` first.

If you used an earlier version that put a `swarmbox` function in `~/.bashrc`, `~/.zshrc` or `~/.config/fish/config.fish`, delete that block (it starts with
`# >>> swarmbox`): a shell function wins over the script, and the installer warns when it finds one.

## Everyday commands

```bash
swarmbox                    # create the box if needed, then open a shell in it
swarmbox help               # list the commands
swarmbox claude             # run a command in the box from your machine
swarmbox url                # print the address of the web terminal
swarmbox stop               # stop the box; nothing is deleted
swarmbox reset              # recreate the box so a changed setting applies; the workspace is kept
swarmbox update             # fetch a newer image and refresh the swarmbox command from it
swarmbox env add NAME       # pass one of your variables into the box
swarmbox config list        # show the settings
swarmbox tool list          # show the tools you can install
swarmbox remote setup       # set up remote access with Cloudflare
```

## Tools

Tools install on first use and live in the workspace: Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry. Run `swarmbox tool list` to see them.
The installer's `--with` option installs some up front.

## Status and limits

Version 2.0.0 is the first public version and is not tagged yet. Its image was built and run end to end in a development box (box, web terminal, tools),
but it has not run on a real host yet and is not published. macOS, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are unverified.
Docker is not supported. `install.sh`, which installs from a release, works only once a release exists; until then use the Quick start.
The architecture is in [docs/design.md](docs/design.md).

## Privacy

SwarmBox sends **no telemetry**. It makes no network call of its own except to pull the image, to install a tool you asked for,
to check for a tool update, and, with `swarmbox remote`, to reach Cloudflare. Logs stay on your machine:
`<workspace>/.local/state/swarmbox/` holds `serve.log`, `health` and `web-terminal.log`; on the host only `~/.local/state/swarmbox/` exists (locks and `notices`).

## Documentation

- [docs/web-terminal.md](docs/web-terminal.md): the browser terminal
- [docs/cloudflare.md](docs/cloudflare.md): remote access with Cloudflare Tunnel and Access (`swarmbox remote setup`)
- [docs/nested-podman.md](docs/nested-podman.md): containers inside the box
- [docs/uninstall.md](docs/uninstall.md): remove SwarmBox
- [docs/microvm.md](docs/microvm.md): stronger isolation with a VM or microVM
- [docs/design.md](docs/design.md) and [docs/security-review.md](docs/security-review.md): architecture and the review of the host script
- [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## Contributing and license

Contributions are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md) and the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
SwarmBox is licensed under Apache-2.0, see [LICENSE](LICENSE).
