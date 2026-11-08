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
| `test_function_bash.py` | the generated function in bash (the shared case table of `tests/function_cases.py`: word routing, quoting, exit codes, the bootstrap, seeds) with fake `podman` and fake helper; the same table under `bash --posix`; a lint for bash 4 constructs (bash 3.2 itself is not run here) |
| `test_function_fish.py` | the same case table in fish |
| `test_function_zsh.py` | the same case table in zsh |
| `test_helpers.py` | the fake `podman` of `tests/helpers.py` |
| `test_history_audit.py` | the history scanner `tests/audit_history.py` and the shape of `docs/history-audit.md` |
| `test_host_config.py` | `container/host/swarmbox-host`: `version`, `config get\|set\|list\|seed`, `env add\|rm\|list`, the token and the portable mode check (stat shims, a fake `ls`), all in mktemp homes with a pty for the token |
| `test_host_connector.py` | the connector logic of `up` (`connector_ensure`): create, start, recreate on a changed token, the pinned image kept equal to `cloudflare-setup.py`, failures only warn, the token only in the environment of the fake `podman` |
| `test_host_remote.py` | `remote setup\|status\|off\|token` of the helper over `cloudflare-setup.py` (a stub script and the real one for usage errors), `url` and `remote status` host lines, the tunnel token (precedence, mode 600, the terminal offer) |
| `test_host_remote_e2e_fake.py` | `remote setup`, `status`, rerun, `token` and `off` end to end: the real wrapper and the real script against the fake Cloudflare API (loopback, random port) and a fake podman |
| `test_host_create_flags.py` | `create-flags` (a golden file per configuration under `tests/fixtures/`, one test per key of 8.2, framing, tool ports, ports and `BROWSER_URL` parity, no `--network=host` in any combination), `fingerprint [--explain]` and the workspace checks (WSL refusal with a fake `/proc/version`, not writable, created once); the helper runs under dash, `bash --posix` and busybox sh |
| `test_host_shells.py` | the same helper under dash, `bash --posix`, busybox sh, zsh in sh emulation and bash named `sh`; no bashisms; `shellcheck -s sh` |
| `test_host_socket.py` | the host connection `podman -c <name>` of `container/host/swarmbox-host` (`connection`, step 6 of `up`): the 100/101 byte boundary, the short symlink and its refusals, idempotent registration with a stateful fake `podman`, the real `podman system connection` in an isolated config, a stand-in socket server in a throwaway container, and a guard on the real Podman files |
| `test_host_up.py` | `up`, `reset`, `stop` and `url` of the helper against the shared fake `podman` (rules and answers in sequence): the exact-name lookup, the fast path call budget, warnings, prerequisites, creation and cleanup by `--cidfile`, readiness, conflicts, the lock with real processes (two at once, SIGTERM, SIGKILL, stale, live holder), reset, stop, url |
| `test_host_update.py` | `update [--to TAG]` of the helper against the shared fake `podman` and a fake image archive: the series, `--to`, invalid tags and images with no series, every failure leaving the helper, the config and the box unchanged, the local `X.Y.Z` tag, `reset` offline after `update`, the next function call keeping the new helper |
| `test_registry_e2e.py` | opt-in (`SWARMBOX_E2E=1`, skipped otherwise): runs `tests/e2e_registry.py`, the install line, first call, joining, two terminals at once, `update` and `reset` offline and `update --to` against a `registry:2` throwaway container, in bash, zsh and fish (`docs/local-registry.md`) |
| `test_image_build.py` | the built image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; builds `swarmbox-test-img-<rand>` and removes it) |
| `test_image_with_tools.py` | `WITH_TOOLS` on a real image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; the real claude install needs `SWARMBOX_TEST_NETWORK=1`; builds `swarmbox-test-4b6-img` and removes it) |
| `test_init_output.py` | `container/scripts/swarmbox-init.sh` and the templates: one marker pair per shell, seeds only for flags given, quoting, `--shell` and `SHELL`, idempotent output, nothing written, the hint on a terminal, `bash -n`, `zsh -n`, `fish --no-execute` |
| `test_mcp_registry.py` | `container/scripts/swarmbox-mcp.sh` (the MCP registry generator, serve step 7) on a temp HOME and a copy of `container/mcp`: shape, `BROWSER_URL`, off switch, user override, bad files, no `npx`, atomic write |
| `test_migration.py` | `container/scripts/swarmbox-migrate.sh` (the layout migration, serve step 4) on a fixture workspace built from the v0.1.0 code in mktemp, and `serve` running it |
| `test_parity.py` | The parity suite (design 8.4, 12.2, 12.3, 13.2): one or more tests per row of the feature catalog against the function, the real helper, `serve`, `swarmbox-attach` (private tmux socket), `swarmbox-web`, the tool manifests and the Cloudflare wrapper; the removed items; the old flags compared with the recorded v0.1.0 run flags (`tests/fixtures/v0.1.0-run-flags.json`, made by `tests/record_v010_flags.py`). Rows that could only be checked reduced are tagged `[reduced]` and listed at the end of the run |
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
| `test_run_all.py` | `tests/run_all.sh`, the full-regression runner (`--werror`, `--repeat N`, `--only`, `--list`), on small files only |
| `test_tool_claude_real.py` | the first call of Claude Code through the shim: fake-curl argument tests always; the real download in throwaway containers only with `SWARMBOX_TEST_NETWORK=1` and `SWARMBOX_IMAGE_BUILD=1` (slow, about 330 MB) |
| `test_tool_gemini_clasp_poetry.py` | the `gemini`, `clasp` and `poetry` tools: installers with a fake npm and a fake curl serving a fake Poetry installer (stay in the prefix, versions from the manifest, no cache outside it), validate on the real tools folder (agents latest, others pinned, unique PROVIDES), `tool-ports` listing 43323 and the host helper publishing it, the `clasp login` function in bash and zsh, the gemini alias and `yolo` |
| `test_tool_go_gcloud.py` | the `go` and `gcloud` tools: installers with a fake curl and tiny tarballs (checksum verified before extracting, wrong checksum leaves the prefix empty, arch names, nothing outside the prefix), the manifest checksum reaching the installer for the host arch, `go/shell.sh` in bash and zsh, validate's checksum rules |
| `test_tool_real.py` | the real-installer tests per tool (6.9): the scan harness against misbehaving fake installers always; real installs in throwaway containers (no side effects, npm cache rule, survives a reset) only with `SWARMBOX_TEST_NETWORK=1`, `SWARMBOX_IMAGE_BUILD=1` and Podman (`SWARMBOX_REAL_TOOLS=go,poetry` limits the table) |
| `test_tool_use_remove.py` | `swarmbox-tool use` and `remove`: version switch, clean failures, `--purge`, locks, the guard that keeps SwarmBox's own folders |
| `test_tool_new.py` | `swarmbox-tool new`: the skeleton passes `validate`, name rules, `--repo` and `--dir` |
| `test_tool_doctor.py` | the environment fingerprint (6.11): `doctor`, `doctor --fix`, `link --user` and the shim (ARCH refuses, NODE_MAJOR and LIBC warn once per entry) |
| `test_tool_image_level.py` | image-level installs (6.8): `install --image`, the run-time lookup (workspace first, a broken one never shadows a good image install), fingerprint at build |
| `test_record_checksums.py` | `dev/record-checksums.sh` (the maintainer script of D29) with a fake curl and a fake go.dev listing: both checksums written, idempotent, a mismatching listing refused, no other line touched |
| `test_tool_opencode.py` | the `opencode` tool: the installer with a fake npm and a fake package tree (stays in the prefix, prunes other platform builds and keeps the current one, amd64 and arm64), the rendering by the tool's prepare script (`LOCAL_LLM_*`, mode 600, idempotence, the MCP mirror compared with the v0.1.0 function), the manifest, `MCP_FORMAT`, the shim and no alias |
| `test_tool_prepare.py` | `swarmbox-tool prepare` and the prepare after an install: fake tools whose prepare script succeeds, fails, hangs or is absent, WITH-declared and user-level tools, order, one failure line per tool |
| `test_tool_shim.py` | `swarmbox-shim`: symlink and PATH calls under the shebang shell, dash, bash and busybox sh; first-use install then no installer; failure and retry; unknown command 127; user index wins; no manifest read on the hot path; loop guards; shellcheck |
| `test_tool_install.py` | `swarmbox-tool install`, `run`, `list`, `update`: fake installers, the lock (two processes at once), the managed and `UPDATE=self` layouts, failure leaves nothing, checksum mismatch, exit codes, stdout purity |
| `test_tool_link.py` | `swarmbox-tool link --system` and `--user`: shims, the `command tool` index, `tool-ports`, idempotence, stale shims, same-level conflicts, no project level |
| `test_tool_manifest.py` | `swarmbox-tool` manifest loading and `validate` (every rule of design 6.9, the install.sh lint, no project level) and the `claude` manifest and installer (fake `curl`) |
| `test_tool_stub.py` | the parts of `container/scripts/swarmbox-tool.sh` that are still stubs (the later-phase exit 70 of `use`, `remove`, `doctor`, `new`), `link` with no manifests, and the empty `tool-ports` file |
| `test_tmux_browser_keys.py` | the browser key bindings of tmux (real tmux on a private socket; about 60 s) |
| `test_web_build.py` | `container/scripts/swarmbox-web.sh` against a fake ttyd, with `serve`, and the browser tests rerun on the page it renders (needs a browser for those) |
| `test_smoke_skeleton.py` | the structure of `tests/smoke_image.py` (steps, tags, names, forbidden verbs); starts no container |
| `test_web_container.py` | the web terminal, `pubkey`, `tool validate` and `host-helper` in a throwaway container (skipped unless `SWARMBOX_IMAGE_BUILD=1`; reduced: no nested Podman) |
| `test_web_style.py` | the web terminal style (needs a browser) |
| `test_web_terminal.py` | the web terminal wrapper |

Run them all with `sh tests/run_all.sh` (one line per file with its test count; `--werror` runs each with `python3 -W error`, `--repeat 3` runs each file three times, `--only a.py,b.py` picks files). Shared helpers (the repository root, the fake `podman`, and later the
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
