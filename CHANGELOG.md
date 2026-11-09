# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/).

## [2.0.0] - Unreleased

First public version. Not released: it stays "Unreleased" until the maintainer creates the tag `v2.0.0`.

### Features

- One persistent rootless Podman box per workspace; every terminal tab and the browser join the same tmux session.
- A small neutral image (`node:24-slim`, user `agent`, about 1.75 GB) with no agent inside. Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry
  install on first use from manifests, through shims, with pinned versions and checksums where the vendor publishes them.
- The workspace is one folder of your machine and holds projects, logins, the SSH key and installed tools; the box can be recreated without loss (`swarmbox reset`).
- A shell function for bash, zsh and fish, printed by `init`, and a POSIX `sh` host helper: `up`, `stop`, `reset`, `url`, `update`, `config`, `env`, `pubkey`, `tool`, `remote`, `fingerprint`, `version`.
- `swarmbox <command>` runs a command in the box and returns its exit status; `--plain` skips tmux.
- Creation settings in one host file, compared on every entry by a fingerprint; variables are passed by name at creation and never written to disk.
- Nested Podman, always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- A web terminal (ttyd and tmux) on `127.0.0.1`, supervised inside the box; optional remote access with Cloudflare Tunnel and Access (`swarmbox remote setup|status|off|token`),
  with the credentials and the connector on the host.
- Chrome DevTools MCP with Chromium in the image, written to the MCP configuration of the agents.
- `swarmbox update [--to TAG]` with an exact local tag, so a later `reset` works offline and a rollback is one command.
- No telemetry; logs stay on your machine.
- XDG-aware paths on the host and in the box.
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, a CI workflow and a signed multi-arch release workflow.

### Known limits

macOS, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are not verified, and the image is not published yet. A container shares the host kernel:
see [SECURITY.md](SECURITY.md) and [docs/microvm.md](docs/microvm.md).

[2.0.0]: https://github.com/feroult/swarmbox/commits/opensource
