# Contributing to SwarmBox

SwarmBox is a Podman-based sandbox for running AI coding agents in auto-approve mode. The design is in `docs/design.md`
and the build order in `docs/implementation-plan.md`. Progress is in `docs/implementation-status.md` and the reasons for
choices in `docs/decision-log.md`. Contributions are accepted under the Apache License 2.0 (`LICENSE`).

## Safety first: never touch a live box

Tests and experiments run on a machine where someone may have a real SwarmBox running. Never touch the live box.

- Create only containers, volumes, networks and images whose names start with `swarmbox-test-` and remove them by their exact name.
  Never use `podman system prune`, `rm -a`, `stop -a` or a similar command that matches by anything but a name.
- Never run `tmux kill-server` or any other tmux command against the running server. Use a private socket
  (`unset TMUX; tmux -L swarmbox-test-<id> -f /dev/null`) and stop it by that exact name.
- Never kill processes by name or pattern (`pkill`, `killall`). Test services bind `127.0.0.1` on a random high port, never on `0.0.0.0`.
- Use `mktemp -d` directories for workspaces, `HOME` and the `XDG_*` variables. Never write to `~/.config/swarmbox`,
  `~/.local/share/swarmbox`, `~/.swarmbox` or the default workspace.

## Running the tests

Tests are Python `unittest` scripts that need only Python 3 and the standard library. Run one file at a time from anywhere:

```
python3 tests/test_docs_consistency.py
```

| File | What it covers |
|------|----------------|
| `test_clipboard_bridge.py` | the clipboard bridge page script (needs a browser; about 40 s) |
| `test_cloudflare_setup.py` | `cloudflare-setup.py` against a fake Cloudflare API |
| `test_design_partb.py` | the shape of Part B of the design |
| `test_dirs.py` | `container/scripts/dirs.sh`, the XDG-aware path file (sh, dash, bash) |
| `test_docs_consistency.py` | cross-references, D and B numbers and code fences of the design and the plan |
| `test_repo_files.py` | `LICENSE`, `THIRD_PARTY_NOTICES.md` and this file |
| `test_spikes_common.py` | the safety helpers of the spike scripts |
| `test_ssh_key.py` | the SSH key handling in `start.sh` |
| `test_starship.py` | the Starship prompt setup |
| `test_start_attach.py` | attaching to the box |
| `test_start_init.py` | `container/scripts/init.sh` |
| `test_start_timezone.py` | the timezone handling |
| `test_start_web_connector.py` | the web terminal connector in `start.sh` |
| `test_tmux_browser_keys.py` | the browser key bindings of tmux (real tmux on a private socket; about 60 s) |
| `test_web_style.py` | the web terminal style (needs a browser) |
| `test_web_terminal.py` | the web terminal wrapper |

Run them all with `for f in tests/test_*.py; do python3 "$f" || break; done`. Shared helpers (the repository root, and later the
fake `podman` and fake host helper) are in `tests/helpers.py`. Write a test first, with fakes; use a real container only for a smoke
test, with a `swarmbox-test-` name. The spike scripts in `tests/spikes/` are experiments, not part of the normal run (see `tests/spikes/README.md`).

## Building the image locally

```
./build.sh
```

`build.sh` runs `podman build` with `--build-arg USER_UID`, `USER_GID` and `HOST_OS`, and tags the image `swarmbox`. [unverified: a
full `./build.sh` was not run for this file; the command was read from `build.sh`.] Do not run it on a machine where the live
box uses the image name `swarmbox` unless you mean to replace that image: pass `--name swarmbox-test-<id>` to build under a test name,
and remove that image by its exact name afterwards.

Caveats when building inside a SwarmBox (nested rootless Podman 4.3.1):

- Only about 64,000 user IDs are available, so a base image with very high UIDs can fail to unpack.
- `apt` inside a nested build fails with a `setgroups` error unless `APT::Sandbox::User "root";` is set. Put that line in a
  configuration file of a scratch copy of the `Dockerfile`, never in the product `Dockerfile`.
- A container cannot start another Podman that needs `/dev/net/tun` or an unmasked `/proc` (a third nesting level): test that
  part with a fake or a test-only switch and say so in the test.
- Builds take minutes and the image is several GB; run them in the background and give them a long timeout.

See `docs/nested-podman.md` for the nested engine in detail.

## Branches and commits

- Work on a branch, not on `main`. Do not rewrite history or move tags.
- One logical change per commit. Start the message with a type: `feat:`, `fix:`, `test:`, `docs:`, `refactor:` or `build:`.
- Add only the files you changed (no `git add -A`).
- Keep `docs/design.md` and `docs/implementation-plan.md` consistent in the same commit as the change; mark anything you could
  not check as `[unverified]`.
- Code, comments and docs are in English.
