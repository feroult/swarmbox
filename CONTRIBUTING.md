# Contributing to SwarmBox

SwarmBox is a Podman-based sandbox for running AI coding agents in auto-approve mode. The architecture is in `docs/design.md`;
`docs/history/` holds records of how it was built (not current documentation). Contributions are accepted under the Apache License 2.0 (`LICENSE`). Please follow `CODE_OF_CONDUCT.md`; report security problems as `SECURITY.md` says, not in a public issue; user-visible changes go in `CHANGELOG.md`.

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

Tests are Python `unittest` scripts that need only Python 3 and the standard library. The suite is small on purpose: one test per
behaviour or branch, no copies of the same case, no tests of wording in docs. Run one file, or all of them:

```
python3 tests/test_host_up.py        # one file
sh tests/run_all.sh                  # all files, one line each with the count and the seconds (about 1 minute)
```

`tests/run_all.sh` options: `--werror` (each file under `python3 -W error`), `--repeat N`, `--only a.py,b.py`, `--browser` (adds the
three browser tests, which need chromium and ttyd and run in the scheduled CI job), `--list`. It runs every file under
`tests/reap_run.py`, which kills by PID whatever a file left behind and shows it as `reaped N`; a test that leaks a process is a bug
to fix in that test (end children in `addCleanup`). Run files in the foreground.

What each group covers (a file name tells the rest):

| Files | What they cover |
|---|---|
| `test_host_*.py`, `test_security_review.py`, `test_cloudflare_setup.py` | the script `container/host/swarmbox-host` (installed as `swarmbox`) against a fake `podman` (`tests/helpers.py`): `up`, `reset`, `stop`, `url`, `update`, `config`, `env`, `remote`, create flags with golden files in `tests/fixtures/`, the host connection, the connector, hostile input; `cloudflare-setup.py` against a fake Cloudflare API on loopback |
| `test_swarmbox_command.py`, `test_install.py`, `test_host_shells.py` | the `swarmbox` script as a program: which words it handles and which go to the box, `podman exec` forwarding and the `-t` rule; the two installers (`container/scripts/swarmbox-install.sh`, `install.sh`): idempotence, atomic write, PATH advice, old-function warning, the Podman version check; the script under dash, bash and busybox |
| `test_serve_steps.py`, `test_entrypoint.py`, `test_attach_command.py`, `test_web_build.py`, `test_bashrc_fragment.py`, `test_starship.py`, `test_pubkey_ensure.py`, `test_ssh_key.py`, `test_mcp_registry.py`, `test_dirs.py`, `test_build_index.py` | what runs inside the box: `serve` steps and signals with fakes on `PATH`, `swarmbox-attach` (fake tmux, then real tmux on a private `-L swarmbox-test-<random>` socket), `swarmbox-web`, the shell fragment, the key, the MCP registry, the XDG paths, the web page build |
| `test_tool_*.py` | the tool machinery `swarmbox-tool` and `swarmbox-shim` (manifests, link, install, run, prepare, use, remove, doctor, image level, the per-tool installers); `test_tool_real.py` also installs for real in throwaway containers, only with `SWARMBOX_TEST_NETWORK=1` and `SWARMBOX_IMAGE_BUILD=1` |
| `test_dockerfile.py`, `test_dev_build.py`, `test_image_build.py`, `test_image_with_tools.py`, `test_bashrc_container.py` | the `Dockerfile` (static) and the built image (skipped unless `SWARMBOX_IMAGE_BUILD=1`; the image comes from `dev/dev-build.sh` or `SWARMBOX_IMAGE_TAG`, shared by `tests/image_support.py`). `tests/smoke_image.py` is the image smoke test (not a `test_*.py`): `SWARMBOX_IMAGE_BUILD=1 python3 tests/smoke_image.py` is the reduced run for a development box, `SWARMBOX_SMOKE_FULL=1` the full run for CI |
| `test_ci_workflow.py`, `test_release_workflow.py`, `test_release_check.py`, `test_release_version.py`, `test_third_party_notices.py`, `test_record_checksums.py`, `test_name_check.py` | the repository machinery: text checks of the two workflows, the release scripts under `dev/` on fixture repositories, the notices generator, the checksum recorder |
| `test_default_names_lint.py`, `test_repo_files.py`, `test_docs_consistency.py`, `test_run_all.py`, `test_helpers.py` | guards: no default name or image repository written as a literal (read `container/host/DEFAULTS`), the policy files exist and link, the README commands exist and its links resolve, the runner itself, the fake `podman` |
| `test_clipboard_bridge.py`, `test_web_style.py`, `test_tmux_browser_keys.py` | the web terminal in a real browser and tmux keys; they need chromium and ttyd and run in the scheduled CI job only |

Shared helpers (the fake `podman`, the helper archive of an image, a pseudo terminal) are in `tests/helpers.py`. Write a test first, with fakes; use a real
container only for a smoke test, with a `swarmbox-test-` name.

## Before you push: the local gate

CI rejects a push for things that pass on a developer machine: shellcheck findings, and tests that need the variables of your terminal
(`TERM`, `COLORTERM`, `STARSHIP_SHELL`; a CI runner has none of them). `dev/check.sh` runs those checks here:

```bash
sh dev/check.sh                # shellcheck 0.9 on the files ci.yml lists, then the unit tests in a clean environment (about a minute and a half)
sh dev/check.sh --release      # and dev/release-check.sh, before a release tag
git config core.hooksPath dev/hooks    # once per clone: run it before every push of main or of a v* tag
```

The shellcheck file lists are read from `.github/workflows/ci.yml`, so they cannot drift; a new shell file goes into that list and is checked from then on.
The version is pinned to 0.9, the one of the CI runner: when none is installed, `dev/check.sh` fetches it with pip into `~/.cache/swarmbox-dev`.
The tests run under `env -i` with `PATH`, `HOME` and a UTF-8 `LANG`: a test that reads `TERM` or another variable must set it itself.
A push of another branch is not checked. Skip it once with `git push --no-verify` (or `SWARMBOX_SKIP_CHECK=1 git push`).
It cannot cover what only CI has: the macOS job (bash 3.2), the arm64 job and the image smoke test. It also prints how many tests were skipped
here (no tmux, dash or busybox): CI runs them.

## Releasing

A release is one command, and the part that needs a writer is the CHANGELOG, which is written **before** it runs, by whoever made the changes (a person or
an agent), under `## [Unreleased]` in `CHANGELOG.md`: one `- ` item per change that matters to a user of SwarmBox, in the same commit as the change when
you can (that is when the reason is fresh). Changes only to `dev/`, tests or CI go in one short line, or are left out.

```bash
sh dev/release.sh               # the next patch version; or: minor, major, 2.1.0
sh dev/release.sh --dry-run     # checks and says what it would do, changes nothing
```

It checks that you are on `main`, in step with `origin`, and that only `CHANGELOG.md` has changes; it **refuses to go on when `[Unreleased]` is empty, a placeholder
or too thin**, and its error says what to do, with the commits since the last release and the last entry as a model, so the author can write it and run the
command again. Then it moves the items under the new dated heading, sets the version (`container/host/VERSION` and `SCRIPT_VERSION`), runs `sh dev/check.sh`, makes
the commit `release: X.Y.Z`, runs `dev/release-check.sh`, pushes `main`, **waits for the CI of that commit** and only then creates and pushes the tag `vX.Y.Z`, which starts
the release workflow. It then waits for the release and verifies it: the checksum of `swarmbox`, the version it reports and, with Podman, that the image tags agree and have two
architectures. A failure after the bump puts the files back (your CHANGELOG text included); a CI that fails leaves no tag. `GH_TOKEN` (optional) avoids the anonymous rate limit of the API.

## Smoke test on a host

`dev/host-smoke.sh` builds the image and checks the product end to end on a real host (not inside a box): it installs the `swarmbox` script of its own image into a temporary folder (twice) and puts it on `PATH` for the run, then checks `up`, labels, `config`,
`env`, `pubkey`, the user and workspace, tmux, the web terminal, nested Podman, `stop`, `reset`, `url` and `help`. It prints one
`OK`, `FAIL` or `SKIP` line per step and `RESULT: N ok, M fail, K skip`; paste that when you report a failure. It uses only
`swarmbox-test-*` names, a temporary workspace, a private config folder, a private install folder and a random port on `127.0.0.1`, and removes them on exit
(`--keep` leaves them, `--with-tools` also installs Go, `--no-cache` builds from scratch, `--dry-run` prints the commands only).

## Building the image locally

The 2.0 image is the root `Dockerfile`. In a development box (nested Podman) build it with

```
sh dev/dev-build.sh            # tag swarmbox-test-img-<random>; then: podman rmi <that exact tag>
```

which builds from a scratch copy of the `Dockerfile` that carries the apt override (see below); the product file is never changed.
`SWARMBOX_IMAGE_BUILD=1 python3 tests/test_image_build.py` builds and inspects it. To build by hand: `podman build -t localhost/swarmbox:local .`
(then install it as the README Quick start shows: `podman run --rm localhost/swarmbox:local install --with claude --image localhost/swarmbox:local | sh`; `SWARMBOX_BIN_DIR=DIR` installs somewhere else). Tests-only variables: `SWARMBOX_TEST_SUPPORT_DIR` (where the script keeps its support files), `SWARMBOX_TEST_HOST_DIR` and `SWARMBOX_TEST_CONTAINERENV` (what `install` reads).

Caveats when building inside a SwarmBox (nested rootless Podman 4.3.1):

- Only about 64,000 user IDs are available, so a base image with very high UIDs can fail to unpack.
- `apt` inside a nested build fails with a `setgroups` error unless `APT::Sandbox::User "root";` is set. Put that line in a
  configuration file of a scratch copy of the `Dockerfile`, never in the product `Dockerfile`.
- A container cannot start another Podman that needs `/dev/net/tun` or an unmasked `/proc` (a third nesting level): test that
  part with a fake or a test-only switch and say so in the test.
- Builds take minutes and the image is several GB; run them in the background and give them a long timeout.

See `docs/nested-podman.md` for the nested engine in detail.

## Bumping pinned versions

Every version the repository pins, who bumps it, and how. `.github/dependabot.yml` (Dependabot, weekly) bumps what its
managers can read: the `uses:` lines of the workflows and a literal `FROM` line. It cannot read the shell-style
`tool.conf` files or the `ARG` pins of the Dockerfile, so those are bumped by hand. Keep this table in step with the pins.

| Pin | Bumped by | How |
|---|---|---|
| `NODE_VERSION` | by hand | the base image is `FROM node:${NODE_VERSION}-slim`, which Dependabot does not read; change the `ARG` (and `ARG NODE_VERSION` in the test) and rebuild |
| `node:${NODE_VERSION}-slim` | by hand | the same line as `NODE_VERSION` (a FROM built from an ARG is not read by Dependabot) |
| `TTYD_VERSION` | by hand | change the `ARG`; the build checks the release's `SHA256SUMS` |
| `STARSHIP_VERSION` | by hand | change the `ARG`; the build checks the release's `.sha256` file |
| `UV_VERSION` | by hand | change the `ARG` |
| `CHROME_DEVTOOLS_MCP_VERSION` | by hand | change the `ARG` and check its Node range against the base image |
| `cloudflared image` | by hand | change the default in `container/host/swarmbox-host` AND `cloudflare-setup.py` together (the tests compare them) |
| `container/tools/go/tool.conf` | by hand, then the checksum script | change `VERSION`, then run `sh dev/record-checksums.sh go` (it writes `SHA256_amd64` and `SHA256_arm64` from go.dev's listing and refuses a mismatch), commit both |
| `container/tools/gcloud/tool.conf` | by hand, then the checksum script | change `VERSION`, then run `sh dev/record-checksums.sh gcloud` (it downloads the pinned archive for each architecture and records the computed `SHA256_amd64` and `SHA256_arm64`), commit both |
| `container/tools/clasp/tool.conf` | by hand | change `VERSION` |
| `container/tools/poetry/tool.conf` | by hand | change `VERSION` |
| `container/tools/claude/tool.conf` | floating (nothing to bump) | `VERSION=latest`; the tool updates itself |
| `container/tools/gemini/tool.conf` | floating (nothing to bump) | `VERSION=latest` |
| `container/tools/opencode/tool.conf` | floating (nothing to bump) | `VERSION=latest` |

A go or gcloud bump without the checksum step leaves the old checksums in the file and the installer refuses the new
archive; the pull request template reminds you.

GitHub Actions are pinned by version tag (`actions/checkout@v4`), not by commit SHA. A SHA is stronger against a moved tag; Dependabot bumps
tags and can also update SHA-pinned actions, so the choice can be reversed. Whether the Dependabot entries open pull requests as described is
unverified until the repository is on GitHub.

## Branches and commits

- Work on a branch, not on `main`. Do not rewrite history or move tags.
- One logical change per commit. Start the message with a type: `feat:`, `fix:`, `test:`, `docs:`, `refactor:` or `build:`.
- Add only the files you changed (no `git add -A`).
- Keep `docs/design.md` consistent in the same commit as the change; say in the docs what you could not check.
- Code, comments and docs are in English.
