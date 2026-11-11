# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/).

## [2.0.0-beta.2] - Unreleased

Second prerelease of 2.0.0, tagged `2.0.0-beta.2` only. Install it with `sh install.sh --version 2.0.0-beta.2`, or move from a
beta.1 box with `swarmbox update --to 2.0.0-beta.2`. Changes since beta.1:

- Fixed: with `BROWSER_URL` set, the Chrome DevTools MCP now attaches to that browser. `swarmbox-mcp` read a variable the host never
  passes (`BROWSER_URL`) instead of `SWARMBOX_BROWSER_URL`, so the generated MCP file kept the headless Chromium of the box.
- The web terminal treats Option as Meta on a Mac, so Option+1..9 and Option+N change and open tmux windows (`macOptionIsMeta=false`
  in `web-terminal.conf` brings the special characters back).
- The `tmux` status bar stays visible in the browser, so every window is listed.
- macOS test and CI fixes (macos-15 runner, tests run one by one).

## [2.0.0-beta.1] - Unreleased

First public prerelease of 2.0.0, for testing before the final release. The image is tagged `2.0.0-beta.1` only (never `2.0` or
`latest`) and the GitHub release is marked as a prerelease. Install it with `sh install.sh --version 2.0.0-beta.1`;
`swarmbox update` follows the `2.0` series, which exists only once 2.0.0 is out, so until then move between betas with
`swarmbox update --to TAG`. The feature list is the one of 2.0.0 below. Changes while preparing it: the base image is
`node:24-trixie-slim` (Debian 13) with Podman 5.4; `criu` and its `python3-protobuf` are removed from the image; the Go
standard library findings that Debian 13 has not fixed yet are listed, with the reasons, in `.grype.yaml`.

## [2.0.0] - Unreleased

First public version. Not released: it stays "Unreleased" until the maintainer creates the tag `v2.0.0`.

### Features

- One persistent rootless Podman box per workspace; every terminal tab and the browser join the same tmux session.
- A small neutral image (`node:24-trixie-slim`, user `agent`, about 1.75 GB) with no agent inside. Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry
  install on first use from manifests, through shims, with pinned versions and checksums where the vendor publishes them.
- The workspace is one folder of your machine and holds projects, logins, the SSH key and installed tools; the box can be recreated without loss (`swarmbox reset`).
- One executable POSIX `sh` script, `swarmbox`, on the `PATH` (no shell function, no startup file): `up`, `stop`, `reset`, `url`, `update`, `config`, `env`, `pubkey`, `tool`, `remote`, `fingerprint`, `version`; any other word runs in the box.
- Two ways to install it, with the same result: `podman run --rm IMAGE install [--with TOOLS] | sh`, and `install.sh`, which downloads `swarmbox` from a release and checks its sha256. The release attaches `swarmbox`, `swarmbox.sha256` and `install.sh`.
- `swarmbox <command>` runs a command in the box and returns its exit status; `--plain` skips tmux.
- Creation settings in one host file, compared on every entry by a fingerprint; variables are passed by name at creation and never written to disk.
- Nested Podman, always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- A web terminal (ttyd and tmux) on `127.0.0.1`, supervised inside the box; optional remote access with Cloudflare Tunnel and Access (`swarmbox remote setup|status|off|token`),
  with the credentials and the connector on the host.
- Chrome DevTools MCP with Chromium in the image, written to the MCP configuration of the agents.
- `swarmbox update [--to TAG]` refreshes the script from the new image (never by an older one) and uses an exact local tag, so a later `reset` works offline and a rollback is one command.
- No telemetry; logs stay on your machine.
- XDG-aware paths on the host and in the box.
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, a CI workflow and a signed multi-arch release workflow.

### Known limits

macOS, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are not verified, and the image is not published yet. A container shares the host kernel:
see [SECURITY.md](SECURITY.md) and [docs/microvm.md](docs/microvm.md).

[2.0.0]: https://github.com/feroult/swarmbox/commits/opensource
