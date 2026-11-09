# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows semantic versioning (the first public version is 2.0.0, decision D32).

## [2.0.0] - Unreleased

The entry stays "Unreleased" until the tag `v2.0.0` is created by the owner.

### Added

- A slim neutral image (`node:24-slim`, fixed user `agent` with UID 1000) published signed, with an SBOM, as
  `ghcr.io/feroult/swarmbox` for amd64 and arm64 (design 10, [docs/design.md](docs/design.md)).
- A host helper in POSIX sh, installed by one line and a generated shell function for bash, zsh and fish (`swarmbox init`):
  `up`, `stop`, `reset`, `url`, `config`, `env`, `update`, `update --to`, `rollback`, `fingerprint`, `version`.
- Nested Podman always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- One shared session (tmux) for every client (`swarmbox attach`, `swarmbox <command>`), an ordered `serve` startup with readiness and
  health files, and a ttyd web terminal supervised inside the box.
- `swarmbox-tool`: agent CLIs and developer tools installed on first use from manifests, with shims and locks: Claude Code,
  OpenCode, Gemini CLI, clasp, Poetry, Go and gcloud (pinned versions, checksums where published). `use`, `remove`, `new` and `doctor` subcommands.
- A generated MCP server registry (`mcp-servers.json`) with Chrome DevTools MCP, mirrored into OpenCode.
- Remote access with `swarmbox remote setup|status|off|token` (Cloudflare tunnel and Access), the connector started on every `up`.
- XDG-aware paths on the host and in the box.
- A feature-parity test suite (one test per catalog row), a CI workflow (`ci.yml`) and a release workflow (`release.yml`), owner
  checklists for hardware checks ([docs/owner-checks.md](docs/owner-checks.md)).
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md` and `CODE_OF_CONDUCT.md`.

### Changed

- Agents and tools are no longer baked into the image: the image is about 1.75 GB instead of about 4.2 GB.
- The login and tool state live in the workspace (`<workspace>/.local/...`); the host keeps only config and a small state folder.
- No telemetry and local logs only: see [SECURITY.md](SECURITY.md).

### Removed

- `start.sh`, `build.sh`, `lib/` and the v0.1.0 image file. There is no `swarmbox uninstall`; the README lists the manual steps (D36).

### Deferred to 2.1

- Items the design marks as not needed for parity or a decision: see the risk table of [docs/implementation-plan.md](docs/implementation-plan.md)
  and [docs/decision-log.md](docs/decision-log.md). Known open points: the OpenCode package choice (`@opencode/cli` 2.x versus `opencode-ai`
  1.x), a separately signed host helper asset (only if users ask, D26), and the facts of Part B that need real hardware (macOS, a real WSL, a host UID other than 1000, Podman older than 4.3).

[2.0.0]: https://github.com/feroult/swarmbox/compare/v0.1.0...HEAD
