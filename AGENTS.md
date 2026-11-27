# SwarmBox agent notes

## Test workflow
- Inner loop (changed files + guards, fail-fast): `sh tests/run.sh loop` (or `--since <ref>`)
- Targeted area: `sh tests/run.sh --area <name>` (`guards`, `herdr`, `sysop`, `voice`, `host`, `tabs`, `bus`, `worktree`, `addons`, `release`, `runner`)
- Before committing (full fast suite): `sh tests/run.sh commit` (alias of `fast`; `sh dev/check.sh` also runs shellcheck)
- Real Podman / PTY / image integration: `sh tests/run.sh smoke` (alias of `slow`; prefer `sh dev/test-slow.sh`)

## Safety: never touch a live box
- Name test containers, volumes, networks, and images `swarmbox-test-*` only, and remove them by exact name (never `podman system prune`, `rm -a`, or `stop -a`).
- Never run `hc` against a running daemon or kill processes by name (`pkill`, `killall`); bind test services to `127.0.0.1` on a random port.
- Use `mktemp -d` for workspaces, `HOME`, and `XDG_*`; never write to `~/.config/swarmbox`, `~/.local/share/swarmbox`, or `~/.swarmbox`.

More detail: `tests/README.md` and `CONTRIBUTING.md`.
