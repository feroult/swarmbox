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
| `test_attach_command.py` | `container/scripts/swarmbox-attach.sh`: fake tmux, then real tmux isolated with `-L swarmbox-test-<random>`, ptys as terminals |
| `test_attach_container.py` | `attach` in a throwaway container from the image (skipped unless `SWARMBOX_IMAGE_BUILD=1`) |
| `test_bashrc_container.py` | the shell fragment in a throwaway container from the image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; reduced: no nested Podman) |
| `test_bashrc_fragment.py` | `container/config/bashrc.sh`: aliases and `yolo` from fake manifests, banner and health lines, `PATH`, `SWARMBOX_CMD=1` (bash, fixture trees in mktemp) |
| `test_build_index.py` | `container/web/build-index.sh`, the web page assembled at image build |
| `test_ci_workflow.py` | static checks of `.github/workflows/ci.yml` (parsed with PyYAML; runs actionlint when `ACTIONLINT` or PATH has it) |
| `test_clipboard_bridge.py` | the clipboard bridge page script (needs a browser; about 40 s) |
| `test_cloudflare_setup.py` | `cloudflare-setup.py` against a fake Cloudflare API |
| `test_design_partb.py` | the shape of Part B of the design |
| `test_dev_build.py` | `dev/dev-build.sh`, the dev image build with the apt override in a scratch copy (fake `podman`) |
| `test_dirs.py` | `container/scripts/dirs.sh`, the XDG-aware path file (sh, dash, bash) |
| `test_dockerfile.py` | static checks of the 2.0 `Dockerfile` (no build) |
| `test_docs_consistency.py` | cross-references, D and B numbers and code fences of the design and the plan |
| `test_entrypoint.py` | the subcommands of `container/entrypoint.sh` (serve aside): dispatch with arguments kept, `host-helper` archive, any other command, fake programs on `PATH` |
| `test_helpers.py` | the fake `podman` of `tests/helpers.py` |
| `test_history_audit.py` | the history scanner `tests/audit_history.py` and the shape of `docs/history-audit.md` |
| `test_image_build.py` | the built image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; builds `swarmbox-test-img-<rand>` and removes it) |
| `test_migration.py` | `container/scripts/swarmbox-migrate.sh` (the layout migration, serve step 4) on a fixture workspace built from the v0.1.0 code in mktemp, and `serve` running it |
| `test_pubkey_ensure.py` | `swarmbox-pubkey --ensure` (`container/scripts/ssh-key.sh`): once, idempotent, never overwrites, only under the test `HOME` |
| `test_repo_files.py` | `LICENSE`, `THIRD_PARTY_NOTICES.md` and this file |
| `test_serve_container.py` | `serve` in a throwaway container from the image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; reduced: no nested Podman) |
| `test_serve_steps.py` | `container/entrypoint.sh serve`: steps, failures, readiness marker, signals and the ttyd supervisor, with fakes on `PATH` |
| `test_spikes_common.py` | the safety helpers of the spike scripts |
| `test_ssh_key.py` | the SSH key handling in `start.sh` |
| `test_starship.py` | the Starship prompt setup |
| `test_start_attach.py` | attaching to the box |
| `test_start_fake_podman.py` | `start.sh` against the shared fake `podman` |
| `test_start_init.py` | `container/scripts/init.sh` |
| `test_start_timezone.py` | the timezone handling |
| `test_start_web_connector.py` | the web terminal connector in `start.sh` |
| `test_tool_manifest.py` | `swarmbox-tool` manifest loading and `validate` (every rule of design 6.9, the install.sh lint, no project level) and the `claude` manifest and installer (fake `curl`) |
| `test_tool_stub.py` | the parts of `container/scripts/swarmbox-tool.sh` that are still stubs (`link`, `prepare`, the exit 70) and the empty `tool-ports` file |
| `test_tmux_browser_keys.py` | the browser key bindings of tmux (real tmux on a private socket; about 60 s) |
| `test_web_build.py` | `container/scripts/swarmbox-web.sh` against a fake ttyd, with `serve`, and the browser tests rerun on the page it renders (needs a browser for those) |
| `test_smoke_skeleton.py` | the structure of `tests/smoke_image.py` (steps, tags, names, forbidden verbs); starts no container |
| `test_web_container.py` | the web terminal, `pubkey`, `tool validate` and `host-helper` in a throwaway container (skipped unless `SWARMBOX_IMAGE_BUILD=1`; reduced: no nested Podman) |
| `test_web_style.py` | the web terminal style (needs a browser) |
| `test_web_terminal.py` | the web terminal wrapper |

Run them all with `for f in tests/test_*.py; do python3 "$f" || break; done`. Shared helpers (the repository root, the fake `podman`, and later the
fake host helper) are in `tests/helpers.py`. Write a test first, with fakes; use a real container only for a smoke
test, with a `swarmbox-test-` name. The image smoke test is `tests/smoke_image.py` (not a `test_*.py`): `SWARMBOX_IMAGE_BUILD=1 python3 tests/smoke_image.py` is the reduced run for a development box (every result tagged `[reduced: development box, no nested Podman in the box]`, the nested steps skipped), `SWARMBOX_SMOKE_FULL=1` the full run for CI or your own host. The spike scripts in `tests/spikes/` are experiments, not part of the normal run (see `tests/spikes/README.md`).

## Building the image locally

The 2.0 image is the root `Dockerfile`. In a development box (nested Podman) build it with

```
sh dev/dev-build.sh            # tag swarmbox-test-img-<random>; then: podman rmi <that exact tag>
```

which builds from a scratch copy of the `Dockerfile` that carries the apt override (see below); the product file is never changed.
`SWARMBOX_IMAGE_BUILD=1 python3 tests/test_image_build.py` builds and inspects it. `build.sh` still builds the v0.1.0 image from
`Dockerfile.v0.1.0` until Phase 6:

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
