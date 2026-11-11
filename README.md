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

## Quick start: from zero to Claude Code in a box

Five steps, about ten minutes (most of it is the image download, about 1.75 GB). You need Linux, or Windows with WSL2. Docker is not supported, and macOS through a Podman machine is unverified.

**1. Install Podman 4.3 or newer.**

```bash
sudo apt install podman uidmap       # Debian 12/13, Ubuntu 24.04 or newer, and WSL2 with one of them
sudo dnf install podman              # Fedora
```

Ubuntu 22.04 ships Podman 3.4, which is too old: use 24.04. On WSL2 keep everything on the Linux filesystem (your home, not `/mnt/c`). Check that it works as your own user, not as root:

```bash
podman --version                     # 4.3 or newer
podman run --rm docker.io/library/alpine echo ok
ls /dev/net/tun                      # must exist: the box runs Podman inside itself
```

**2. Install SwarmBox with Claude Code as the default agent.**

```bash
curl -fsSL https://github.com/feroult/swarmbox/releases/latest/download/install.sh | sh -s -- --with claude
```

It downloads the `swarmbox` script of the release, checks its sha256, writes it to `~/.local/bin/swarmbox` (set `SWARMBOX_BIN_DIR` to use another folder) and records the image and `claude` in `~/.config/swarmbox/config`.
It also writes `sx`, a short name for the same command (`sx up`, `sx claude`), unless some other `sx` already exists on your machine; `SWARMBOX_NO_SX=1` skips it.
It edits no startup file. If `~/.local/bin` is not in your `PATH` it says how to add it; then open a new terminal. To read the installer first, save `install.sh` from the same address and run `sh install.sh --with claude`.
The other way, with no `curl`: `podman run --rm ghcr.io/feroult/swarmbox:2.0.0 install --with claude | sh`.

**3. Open the box.**

```bash
swarmbox
```

The first time it pulls the image, creates the box and opens a shell in it. You are the user `agent`, and your home there is the workspace folder `~/swarmbox` of your machine. If port 7681 is busy, run
`swarmbox config set WEB_PORT 7682` and `swarmbox reset` first.

**4. Run Claude Code and log in.**

```bash
mkdir hello && cd hello              # inside the box; it is ~/swarmbox/hello on your machine
claude                               # the first run installs Claude Code, then it asks you to log in
```

`claude` runs in auto-approve mode (`--dangerously-skip-permissions`), which is the point of the box; `yolo` starts your default agent the same way. Log in with your Claude account (open the address it prints in a browser on your machine), or give it an API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # in the terminal where you run swarmbox, not inside the box
swarmbox env add ANTHROPIC_API_KEY
swarmbox reset                       # keys are passed when the box is created; the workspace is kept
```

The login lives in `~/swarmbox/.claude` and survives `swarmbox reset`. Prefer a scoped key: the agent can read every variable you pass in.

**5. Come back from anywhere.** Open a second terminal tab and run `swarmbox` again: it joins the same tmux session. `swarmbox url` prints the address of the web terminal (`http://127.0.0.1:7681`), which shows the same tabs. To reach it from your phone or another machine, see [Remote access](#remote-access-the-same-session-from-anywhere).

`swarmbox pubkey` prints the box's SSH public key; add it as a deploy key to let the agent push to a repository.

If something stops: `swarmbox up` exits 3 when Podman is older than 4.3 or `/dev/net/tun` is missing, and 4 when the workspace is on a Windows drive (`/mnt/c/...`) or not writable.
If you used an earlier version that put a `swarmbox` function in `~/.bashrc`, `~/.zshrc` or `~/.config/fish/config.fish`, delete that block (it starts with
`# >>> swarmbox`): a shell function wins over the script, and the installer warns when it finds one. To remove SwarmBox, see [docs/uninstall.md](docs/uninstall.md).

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

## Remote access: the same session from anywhere

Everything you start in the box keeps running while you are away, and every way in lands in the same tmux session (`main`). Two ways to reach it from outside.

**A. A browser, from any device (Cloudflare Tunnel and Access).** No router port and no public IP: a connector on your machine makes an outbound connection, and Cloudflare asks for an e-mail code before it shows the terminal.
You need a free Cloudflare account, a domain on Cloudflare, and Zero Trust activated once at <https://one.dash.cloudflare.com>.

1. Create an API token at <https://dash.cloudflare.com/profile/api-tokens> (Create Custom Token) with these permissions, for your account and your domain's zone:

   | Scope | Permission | Level |
   |---|---|---|
   | Account | Cloudflare Tunnel | Edit |
   | Account | Access: Apps and Policies | Edit |
   | Account | Access: Organizations, Identity Providers, and Groups | Edit |
   | Zone | DNS | Edit |
   | Zone | Zone | Read |

2. Set it up, on your machine (not in the box). Only the e-mails you list can log in:

   ```bash
   export CLOUDFLARE_API_TOKEN=...      # or leave it out and paste it when asked
   swarmbox remote setup --domain example.com --email you@example.com
   swarmbox url                         # prints the local and the public address
   ```

   The public address is `https://swarmbox.example.com` (`--hostname tty.example.com` picks another one-level name).
3. Open it, type your e-mail, type the code you receive. You are in the tmux session you left. Delete the API token in the dashboard when the command finishes; it is never stored.
4. Keep the connector alive: when `setup` offers to store the tunnel token, say yes (or run `swarmbox config set CLOUDFLARE_TUNNEL_TOKEN` and paste the output of `swarmbox remote token`).
   After that every `swarmbox` entry makes sure the connector is running, so after a reboot a single `swarmbox up` brings the public address back.
5. Check or undo it: `swarmbox remote status` reports the login and the connector, and `swarmbox remote off` removes the hostname, the login and the connector. A longer login: `--session 168h`.

Whoever passes that login has the same control as the agent, a shell with `sudo`: list only your own e-mail and keep the session short. More in [docs/cloudflare.md](docs/cloudflare.md).

**B. A terminal, over SSH to your machine.** If you can already SSH to the machine that runs the box, you need nothing else: `ssh you@your-machine`, then `swarmbox`. You join the same tmux session, and closing the connection leaves it running.

**Moving around the session.** In the browser, `Alt+1..9` (`Option` on a Mac) switches window, `Alt+N` opens one, `Alt+W` closes, and the green **+** in the status bar also opens one (the way to do it on a phone, where there is no Alt key). In a terminal the tmux prefix is `Ctrl+A`
(`Ctrl+A d` detaches and leaves everything running; if your own terminal also runs tmux, press `Ctrl+A a` to send the prefix inside). Font, size, theme and your own tmux config are in [docs/web-terminal.md](docs/web-terminal.md).

## Tools

Tools install on first use and live in the workspace: Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry. Run `swarmbox tool list` to see them.
The installer's `--with` option installs some up front.

## Status and limits

SwarmBox 2.0.0 is the first stable version. The image is built, scanned, signed and tested in CI on Linux (amd64 and arm64, with nested Podman and the web terminal), and the `swarmbox` script is tested under macOS's `/bin/sh` with a fake Podman.
Not verified on real machines: macOS with a Podman machine, WSL with real Windows drives, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup end to end. Docker is not supported.
`swarmbox update` fetches the newest image of the `2.0` series and refreshes the `swarmbox` command from it; `swarmbox update --to 2.0.0` pins a version. The architecture is in [docs/design.md](docs/design.md).

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
