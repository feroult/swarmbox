# SwarmBox

**A persistent Podman box where AI coding agents run in auto-approve mode, with the damage of a mistake limited to one folder of your machine.**

- **One box, shared.** Every terminal tab and the browser join the same box and the same tmux session. Entering never creates a second box.
- **The workspace is one folder on your machine.** Projects, logins, the SSH key and installed tools live there. You can delete and recreate the box and lose nothing.
- **Auto-approve, with a smaller blast radius.** The agent runs without approval prompts, and a mistake is limited to that folder (see Security below for what that does and does not mean).
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

## Security: what you really get

SwarmBox reduces the damage of a mistake. It is not a virtual machine, and it does not make untrusted code safe to run.

**The honest limit.** A container shares the kernel with your machine. Its isolation comes from user namespaces,
cgroups and a seccomp profile, not from a hypervisor. A vulnerability in the kernel or in the container runtime, or a
misconfiguration, can let code inside the box escape to your machine. Do not run code in SwarmBox that you would not run on
your own machine with the same care, unless you put SwarmBox inside a virtual machine or on a dedicated machine.

**What protects you:**

- The box is a rootless Podman container. Even root inside it is an unprivileged user of your machine.
- Your machine's Podman socket is never mounted into the box.
- The agent sees only the workspace folder of your machine.
- The web terminal listens only on `127.0.0.1`. Its own port has no login.
- Cloudflare credentials and the Cloudflare connector run on your machine, outside the box.

**What the agent can do inside the box:**

- Change or delete everything in the workspace, which holds your projects, logins and SSH key.
- Use `sudo` inside the box.
- Reach the network.
- Read every variable and token you pass in, and use the SSH key.
- Keep running while you are away, until you stop the box.

**What weakens isolation on purpose:**

- Nested Podman is always on. It needs `/dev/net/tun` and an unmasked `/proc`, so the box is less isolated than a plain container.
- With remote access on, a browser session is a shell with `sudo`. The login length you choose is the time a stolen or forgotten session stays usable.

**Practical advice:**

- For untrusted work, use a virtual machine or a dedicated machine.
- Pass scoped tokens, not tokens that can do everything your account can.
- Use a deploy key for each repository, not your account key.
- Keep Podman and the kernel up to date.
- Do not expose the web port yourself. Use `swarmbox remote setup` if you need access from outside.
- Look at what the agent changes in the workspace, for example with `git diff`.

More detail is in [SECURITY.md](SECURITY.md) and in the security model of [docs/design.md](docs/design.md).

## Quick start

Requirements: Linux, macOS through a Podman machine, or WSL2 with the workspace on the Linux filesystem; Podman 4.3 or newer.
Docker is not supported.

The image is not published yet, so today you build it locally. In the repository (zsh; for bash use `~/.bashrc`):

```bash
podman build -t localhost/swarmbox-dev:local .
podman run --rm -e SHELL localhost/swarmbox-dev:local init --image localhost/swarmbox-dev:local --with claude      # read what it prints
podman run --rm -e SHELL localhost/swarmbox-dev:local init --image localhost/swarmbox-dev:local --with claude >> ~/.zshrc
```

Open a new terminal. If port 7681 is busy, run `swarmbox config set WEB_PORT 7682`. Then run `swarmbox`.

## Everyday commands

```bash
swarmbox                    # create the box if needed, then open a shell in it
swarmbox claude             # run a command in the box from your machine
swarmbox url                # print the address of the web terminal
swarmbox stop               # stop the box; nothing is deleted
swarmbox reset              # recreate the box so a changed setting applies; the workspace is kept
swarmbox update             # fetch a newer image
swarmbox env add NAME       # pass one of your variables into the box
swarmbox config list        # show the settings
swarmbox tool list          # show the tools you can install
swarmbox remote setup       # set up remote access with Cloudflare
```

## Status

Version 2.0 is a design and an implementation built and tested in a development box with fakes. It has not run on a real host yet,
and it is not published. macOS and Podman older than 4.3 are unverified.
See [docs/design.md](docs/design.md) and [docs/implementation-plan.md](docs/implementation-plan.md).

## Migrating from v0.1.0

v0.1.0 used `start.sh` and `build.sh`, which are gone. **Back up your workspace first**, then follow [docs/migration.md](docs/migration.md).

## Privacy

SwarmBox sends **no telemetry**. It makes no network call of its own except to pull the image, to install a tool you asked for,
to check for a tool update, and, with `swarmbox remote`, to reach Cloudflare. Logs stay on your machine:
`<workspace>/.local/state/swarmbox/` holds `serve.log`, `health` and `web-terminal.log`; on the host only `~/.local/state/swarmbox/` exists (locks and `notices`).

## More

[docs/web-terminal.md](docs/web-terminal.md), [docs/cloudflare.md](docs/cloudflare.md), [docs/nested-podman.md](docs/nested-podman.md),
[docs/uninstall.md](docs/uninstall.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [CHANGELOG.md](CHANGELOG.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md),
and [LICENSE](LICENSE) (Apache-2.0).
