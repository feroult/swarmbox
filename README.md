# SwarmBox

<p align="center"><img src="docs/img/swarmbox-banner.gif" alt="The SwarmBox banner in a browser window: the word SWARMBOX glowing in purple, and the prompt" width="760"></p>

**A box where your AI agent works with freedom, and a shell you can reach from anywhere.**

Give your coding agent (Claude Code, Gemini CLI, OpenCode) a box of its own. Inside it the agent runs without approval prompts: it installs tools, builds and runs
containers, and gets on with the job. The box keeps running while you are away, and you step into the same shell and the same session from any terminal tab or from a
browser, on your machine or from your phone.

- **Freedom to work.** Auto-approve mode, nested Podman, and a browser the agent can drive (Chrome DevTools MCP).
- **One session, from anywhere.** Every terminal tab and the browser share one tmux session. Remote access with Cloudflare Tunnel and an e-mail code.
- **Persistent.** Projects, logins and tools live in one workspace folder: delete and recreate the box and lose nothing.
- **Tools on demand.** Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry install the first time you use them.
- **No telemetry.**

## Quick start

You need Podman 4.3 or newer, on Linux or Windows with WSL2.

```bash
curl -fsSL https://github.com/feroult/swarmbox/releases/latest/download/install.sh | sh -s -- --with claude
swarmbox          # the first time: pulls the image, creates the box and opens a shell in it
claude            # inside the box: installs Claude Code on first use, asks you to log in, runs in auto-approve mode
```

Run `swarmbox` in a second tab to join the same session, and `swarmbox url` for the browser address. To log in with an API key instead: `export ANTHROPIC_API_KEY=...`, then
`swarmbox env add ANTHROPIC_API_KEY` and `swarmbox reset`.

## Everyday commands

```bash
swarmbox update             # a newer image, and the swarmbox command refreshed from it
swarmbox reset              # recreate the box so a changed setting applies; the workspace is kept
swarmbox env add NAME       # pass one of your variables into the box
swarmbox config list        # show the settings
swarmbox tool list          # show the tools you can install
swarmbox remote setup       # remote access from a browser, with Cloudflare (docs/cloudflare.md)
```

## Security

SwarmBox is rootless Podman and the agent sees one workspace folder, not the rest of your machine, but it is **not complete isolation**: like any container it shares the kernel with your machine.
The agent can change everything in the workspace, use `sudo` in the box, reach the network and read every token you pass in, so pass scoped tokens. For a stronger boundary run it inside a virtual machine
([docs/microvm.md](docs/microvm.md)). More in [SECURITY.md](SECURITY.md).

## Documentation

[Web terminal](docs/web-terminal.md) · [Theme](docs/theme.md) · [Remote access](docs/cloudflare.md) · [Nested Podman](docs/nested-podman.md) · [Uninstall](docs/uninstall.md) · [Design](docs/design.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Apache-2.0](LICENSE)
