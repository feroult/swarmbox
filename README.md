# SwarmBox

**A box where your AI agent works with freedom, and a shell you can reach from anywhere.**

Give your coding agent (Claude Code, Gemini CLI, OpenCode) a box of its own. Inside it the agent runs in auto-approve mode: it installs
tools, builds and runs containers, and gets on with the job without asking at every step. A mistake stays inside one folder of your machine.
The box keeps running, and you step in from any terminal tab or from a browser, on your machine or away from it, into the same shell and the same session.

- **Freedom to work.** No approval prompts. The agent can install tools, run its own containers (nested Podman) and drive a browser (Chrome DevTools MCP is built in).
- **A shell you can reach from anywhere.** Every terminal tab and the browser join the same box and the same tmux session, and every tab you open shows up as a tab in the browser. Optional remote access goes through Cloudflare Tunnel and Access, with an e-mail code.
- **Contained.** Rootless Podman, and the agent sees one workspace folder of your machine, not the rest (see [Security](#security)).
- **Persistent.** The box stays up while you are away. Projects, logins, the SSH key and installed tools live in the workspace folder, so you can delete and recreate the box and lose nothing.
- **A neutral image, tools on demand.** Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry are installed the first time you use them.
- **A git SSH key.** The box has one that you can hand out as a deploy key.

## How it feels

```bash
# install once (see Quick start), then, in any terminal:
swarmbox        # creates the box the first time, joins it afterwards
claude          # inside the box: installs Claude Code on first use, then runs it in auto-approve mode
```

Open a second tab, run `swarmbox` again, and you are in the same session. Open `http://127.0.0.1:7681` (`swarmbox url` prints it) and the same tabs are there. In the browser, `Alt+1..9` (`Option` on a Mac) switches tab and `Alt+N` opens a new one ([web terminal](docs/web-terminal.md)).

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
podman build -t localhost/swarmbox:local .
podman run --rm localhost/swarmbox:local install --with claude --image localhost/swarmbox:local        # read what it prints
podman run --rm localhost/swarmbox:local install --with claude --image localhost/swarmbox:local | sh
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

SwarmBox 2.0.0-beta.1 is the first public prerelease of 2.0.0. The image is built and tested in CI on Linux (amd64 and arm64, with nested Podman and the
web terminal), and the `swarmbox` script is tested under macOS's `/bin/sh` with a fake Podman. It is still a beta: macOS with a real Podman machine, WSL with real Windows
drives, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are unverified. Docker is not supported.
To install the beta from its release: `sh install.sh --version 2.0.0-beta.1` (`install.sh` is attached to the GitHub release). `swarmbox update` follows the `2.0` series,
which exists only once 2.0.0 is out; until then move between betas with `swarmbox update --to 2.0.0-beta.2`.
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
