# Ledger: the tests of the shell side and the host (area "shell-and-host")

Files: the host script (`swarmbox-host`: settings, create flags, up/reset/stop/url, update, remote, connector, socket, installers, local-up, pull
line), the entrypoint and its supervisors, `swarmbox-attach`, the addon manager and the shim (manifest, link, install, run, use/remove, prepare,
doctor, new, image level, the per-addon installers), the shell fragment and the agent functions, starship, banner, statusline, the MCP
registry, the XDG folders, the SSH key, `cloudflare-setup.py`.
Not in this area (other agents): the web files (`test_web_build`, `test_web_strip*`, `test_web_style`, `test_clipboard_bridge`,
`test_tmux_browser_keys`), the notices, the guards, `test_addon_voice`, `test_sysop_addon`, the image tests (`test_image_build`,
`test_image_with_addons`, `test_nested_fuse_real`, `smoke_image.py` besides one import).

## Numbers (host, `env -i`, tmux, ttyd, chromium, podman hidden; the same files run one at a time)

| | Files | Tests | Seconds |
|---|---|---|---|
| before | 41 | 540 | 105.9 |
| after, fast | 38 | 490 | 63.3 (wall 10 s at `-j 8`) |
| after, slow (new files, they skip without the gate) | 3 | 13 + 3 + 1 | `test_attach_real` 4.4 s and `test_banner_glint` 14 s in Podman with the gate |

`dev/test-slow.sh fast -- --werror --repeat 2 -j 8` on these files plus `test_bus_serve`, `test_web_build`, `test_voice_config` (which import
what moved): 84 runs, 0 failures, 0 reaped, in the offline read-only container.

The count of tests goes down by 9 % only: these files were already one behaviour per test, with tables. What changed is the duplication across
files (one home per rule), the processes started per case (the pull line 26 s to 3 s, the create-flags loop, the supervisors) and the layer (the
real-tmux half of attach and the real `podman` test are slow now, the fake-tmux half is fast).

## Shared code that moved to `tests/support` (no test file imports another test file in this area any more)

| Module | What | Used by |
|---|---|---|
| `serve_support.py` | the fake tmux, ttyd, bus, podman and `swarmbox-*` programs of `serve`, `ServeCase` | `test_serve_steps`, `test_serve_logs`, `test_web_build`, `test_bus_serve` (still imports the names through `test_serve_steps`) |
| `host_support.py` | `CreateFlagsBase`, `UpBase` (the host script against FakePodman), `line`, `pairs_of`, `fingerprint` | `test_host_*`, `test_swarmbox_command`, `test_security_review`, `test_addon_gemini_clasp_poetry`; `test_voice_config` (another area) still uses `cf.Base`, `cf.fingerprint` through `test_host_create_flags` |
| `addon_support.py` | `make_addon`, `Base` (recording fake installers), `ShimBase`, `tree_hash` | `test_addon_*` |
| `attach_support.py` | the fake tmux, `IsoTmux` (the isolated real one), `PtyProc`, the gate | `test_attach_command`, `test_attach_real`, `smoke_image.py` |
| `cloudflare_support.py` | the fake Cloudflare API on 127.0.0.1 | `test_cloudflare_setup`, `test_host_remote_e2e_fake` |

## Per file

| File | Tests before | s before | Tests after | s after | What was deleted or merged, and where it lives now |
|---|---|---|---|---|---|
| `test_addon_agent_shell.py` | 18 | 0.2 | 13 | 0.1 | the "flags exactly once" and "gemini has no mcp flag" tests repeated the exact-equality asserts of their neighbours; a grep that the flags are not in addon.conf; two copies of the fragment checks (they are `test_bashrc_fragment`'s) |
| `test_addon_stub.py` | 4 | 0.1 | - | - | merged into `test_addon_manifest` (class `Cli`): usage 64 for no argument and for an unknown command (one table), validate with no manifest, bash -n and shellcheck |
| `test_addon_image_level.py` | 5 | 0.3 | - | - | merged into `test_addon_install` (class `ImageLevel`), unchanged |
| `test_addon_install.py` | 12 | 2.2 | 19 | 2.6 | +2: a self-updating installer that fails (exit 69, nothing recorded, the next call retries) and one whose program is the shim (refused); the 5 image-level tests moved in |
| `test_addon_manifest.py` | 23 | 0.6 | 26 | 0.6 | +3 (`Cli`); the "real addons folder validates, with every shipped addon" check lives here once (three copies in the per-addon files deleted) |
| `test_addon_link.py` | 12 | 0.4 | 12 | 0.4 | the real-tree row also checks the shims of claude, gemini, clasp and poetry |
| `test_addon_gemini_clasp_poetry.py` | 13 | 0.5 | 11 | 0.4 | deleted "all five validate" and the second addon-ports check (manifest and link own them) |
| `test_addon_go_gcloud.py` | 10 | 0.3 | 8 | 0.3 | deleted "real folder validates" and a grep of install.sh for ADDON_SHA256 (the wrong-checksum tests run the real installer) |
| `test_addon_opencode.py` | 9 | 0.3 | 8 | 0.2 | deleted "real folder validates" |
| `test_attach_command.py` | 24 | 4.0 | 9 | 3.3 | split: `tests/fast/test_attach_command.py` (fake tmux: 9 tests, the not-ready wait is 0 s, a new test that the wait ends when the marker appears) and `tests/slow/test_attach_real.py` (real isolated tmux, gated, 13 tests, no fixed sleep: a wait for the prompt). Deleted: the entrypoint forwarding (test_entrypoint does it with awkward arguments), a grep for `IDLE_NAME`, a grep for the Dockerfile COPY |
| `test_bashrc_fragment.py` | 26 | 0.2 | 22 | 0.1 | deleted the class `RealAddons` (4): the real agent addons through the fragment are `test_addon_agent_shell.ThroughTheFragment`, the path order is `PathAndEnvironment` |
| `test_host_config.py` | 22 | 3.1 | 22 | 3.4 | +4 KEYS rows: voice.language, voice.stt.model (the `.en` refusal), voice.stt.vocabulary (500 characters), voice.web (they were surviving mutants) |
| `test_host_connector.py` | 10 | 3.4 | 9 | 3.2 | "the token never reaches the box container" deleted: one home, `test_security_review` |
| `test_host_create_flags.py` | 33 | 14.7 | 33 | 7.5 | the 120-combination loop is a seeded sample of 24 that asserts it met every value of every axis |
| `test_host_remote.py` | 8 | 0.6 | 10 | 0.6 | +2: no epilogue question after a dry run or a failed setup; `status` says "podman was not found" |
| `test_host_shells.py` | 4 | 0.9 | 3 | 0.9 | deleted a test that asserted that busybox is in a list of interpreters |
| `test_host_socket.py` | 8 | 0.8 | 9 | 0.8 | the real `podman system connection` test moved to `tests/slow/test_host_socket_real.py` (needs podman; keeps the guard on the real folders); the fast-path call count is `test_host_up`; +2: a link to another place is relinked, a non-link in its place is refused (exit 4) |
| `test_host_up.py` | 37 | 8.2 | 36 | 7.4 | fast-path tests merged (one inspect, the call budget, the connection list first); the three warning cases in one test; the version table gains the refusals below 4.3 (it only had accepted versions); +2 stop tests (podman refuses; no box) |
| `test_host_update.py` | 22 | 2.6 | 23 | 2.9 | one table of hostile tags by class (security_review had a second one); the archive test is here, a table by member class with symlink and hard-link rows (a surviving mutant); a ResourceWarning fixed |
| `test_install.py` | 43 | 2.1 | 42 | 2.1 | deleted "podman 4.10 is newer than 4.3" (a row of `test_host_up`) |
| `test_pubkey_ensure.py` | 5 | 0.1 | - | - | merged into `test_ssh_key`: the same script was tested in two files; the grep of the serve step is `test_serve_steps` |
| `test_ssh_key.py` | 4 | 0.1 | 6 | 0.1 | absorbs `test_pubkey_ensure` |
| `test_pull_ui.py` | 12 | 26.1 | 9 | 3.3 | 5 tests run a whole pull (4 steps of 0.2 s); colors, ASCII, widths and the bar call the drawing functions directly |
| `test_security_review.py` | 14 | 3.3 | 11 | 2.6 | tables by class (13 workspace names to 8, 23 config values to 10), the tag table and the exact-tag test moved to `test_host_update`, dead document helpers removed, no import of another test file |
| `test_serve_logs.py` | 3 | 2.9 | 2 | 1.6 | the `serve.log` trim shares the run of the first test |
| `test_serve_steps.py` | 30 | 11.3 | 21 | 7.0 | one ordinary start (`DefaultRun`) serves the step order, the log, the marker, the health file, "no sudo", "nothing stale to say" and the SIGTERM check; each supervisor has one crash-loop test; the fuse cases are a table; the fake world is `tests/support/serve_support.py` |
| `test_swarmbox_command.py` | 14 | 8.4 | 11 | 4.6 | routing table 17 to 10 rows (one per class), exit-code propagation 18 runs to 3, a regex over the source of the host-word case deleted, a "no -t" test that the routing asserts repeat |
| `test_addon_doctor.py` | 8 | 2.5 | 8 | 2.4 | unchanged |
| `test_addon_new.py` | 5 | 0.2 | 5 | 0.2 | unchanged |
| `test_addon_prepare.py` | 7 | 1.3 | 7 | 1.3 | unchanged |
| `test_addon_shim.py` | 9 | 0.6 | 9 | 0.5 | unchanged |
| `test_addon_use_remove.py` | 12 | 0.6 | 12 | 0.6 | unchanged |
| `test_banner.py` | 4 | 0.1 | 4 | 0.1 | unchanged |
| `test_cloudflare_setup.py` | 12 | 0.8 | 12 | 0.7 | unchanged the fake API moved to `tests/support/cloudflare_support.py`|
| `test_dirs.py` | 4 | 0.1 | 4 | 0.1 | unchanged |
| `test_entrypoint.py` | 11 | 0.5 | 11 | 0.4 | unchanged + the shebang assertion (from serve_steps)|
| `test_host_remote_e2e_fake.py` | 4 | 0.6 | 4 | 0.5 | unchanged |
| `test_local_up.py` | 10 | 0.2 | 10 | 0.2 | unchanged |
| `test_mcp_registry.py` | 9 | 0.2 | 9 | 0.2 | unchanged |
| `test_starship.py` | 10 | 0.2 | 10 | 0.1 | unchanged |
| `test_statusline.py` | 10 | 0.4 | 10 | 0.4 | unchanged |

Slow files of the area: `test_banner_glint` (gated by `SWARMBOX_TEST_REAL_TMUX=1` now, a private `TMUX_TMPDIR`, no scan of `/tmp`, no sleep loop),
`test_bashrc_container` and `smoke_image.py` (imports now from `support`), `test_addon_real` (unchanged: it needs the image, the network and
Podman).

## Real bugs and where their regression test is

| Bug (CHANGELOG, git log, security review) | Test |
|---|---|
| stale `.has-mount-program` after a probe on another graph root: "fuse: device not found" | `test_serve_steps.NestedPodmanState` (no fuse: removed before the service; fuse or marker false: left alone) |
| stale runtime folder of nested Podman after a host reboot | `test_serve_steps.NestedPodmanState.test_a_stale_runtime_folder...` |
| the serve test wiped the nested Podman state of the box that ran it | `serve_support.ServeCase.env` gives every test its own `SWARMBOX_TEST_PODMAN_RUNROOT` |
| run folder not writable after a reboot: no marker, `up` timed out | `test_serve_steps.RunFolderNotWritable` |
| logs grew for ever | `test_serve_logs` |
| a bus supervisor that ended by itself left a pid file whose USR1 kills | `test_serve_steps.BusStep.test_exit_8...` |
| crash loops of ttyd and the bus: five exits, give up, restart by hand | `test_serve_steps.Supervisor`, `BusStep` |
| exit in a host tab jumped to the window of another tab; the grouped session of a finished call stayed; a returning tab lost its place | `tests/slow/test_attach_real.py` (exit, place, exit codes and "no session left") |
| the glint left letters behind and rewrote whole rows | `tests/slow/test_banner_glint.py` |
| SR-01 image reference starting with `-`; SR-02/03 private folders and no write through a planted symlink (temp name, lock); SR-04 `cloudflare.json` mode 600; SR-05 archive with `..`, absolute, link members; signals leave no lock | `test_security_review`, `test_host_update.FailureTest` (archive table), `test_cloudflare_setup` |
| the update tests broke at the version they used | `test_host_update.NewerVersionLiteralsTest` |
| the installer accepted a placeholder image | `test_install` (`without either it is the default repository`) |
| the pull line: percent never goes back, 99 until the end, no glyph of a Nerd Font, `unpack` label, error shown | `test_pull_ui`, `test_host_update.PullProgressTest` |
| two `up` at once made two boxes; a killed `up` left a lock | `test_host_up.LockTest` |
| the connector was not brought up for a running box | `test_host_connector` |
| `yolo` with an agent that is no command / is `yolo` | `test_bashrc_fragment.Yolo` |
| macOS: BSD `stat`, extended attributes, a long temporary folder | `test_host_config.ModeCheckTest`, `test_host_socket` (skip when the folder is too long) |
| the 100-character socket path | `test_host_socket.BoundaryTest` |

## The mutation check

Mutants: the 72 of the original plan (`mutants-plan.json`) in this area's product files, and 267 new ones (seed 7, a sample of
`swarmbox-host`, `swarmbox-addon.sh`, `entrypoint.sh`, `swarmbox-attach.sh`, `swarmbox-shim.sh`, `swarmbox-install.sh`, `swarmbox-mcp.sh`,
`banner.sh`, `swarmbox-statusline.sh`, `install.sh`, `cloudflare-setup.py`); the new ones were run against the OLD suite (a `git archive` of
`HEAD`) to know what it killed, then every mutant against the new one, in the test image with the gate on.

- 339 compared: 278 with the same result, 5 killed only by the new suite, 56 reported "survived" by the harness. All 56 are killed when the
  harness is given the test files (`--tests`): the harness picks the test files that name the product file in their text, and the shared fakes
  moved to `tests/support`, so `test_serve_steps` (and others) no longer name `entrypoint.sh`. **For the Integrate step: `dev/mutate.py` has to
  follow `tests/support` modules (the test files that import a support module that names the product file), or its replay of the plan
  reports false survivors for entrypoint, attach and shim.**
- Old survivors now killed: `voice.stt.model` refusal and `voice.stt.vocabulary` (host_config), the link refresh (host_socket), the archive
  hard-link refusal, `stop` that podman refuses, the remote epilogue (dry run) and the status line without podman (host_remote),
  cloudflare 424 and 638. Still surviving, as before: `swarmbox-addon.sh` 566, 695, 697, 709, 1248, 1366, 1424, 1433 (image-mode cleanup and
  doctor details), `entrypoint.sh` 117, `swarmbox-attach.sh` 49, `swarmbox-statusline.sh` 23. Four mutants of the old plan are stale (the file
  changed by one line since); the three of them that were survivors were rebuilt by hand and are killed.

## For the Integrate step

- `tests/slow/test_host_socket_real.py` needs a real `podman`, which the test image does not have (CI does).
- The image has no `zsh`: the zsh branches of `test_host_shells`, `test_host_create_flags` and `test_addon_agent_shell` skip silently there.
- `test_bus_serve` and `test_voice_config` import names from `test_serve_steps` and `test_host_create_flags`; they work, and should import from
  `tests/support` (`serve_support`, `host_support`) when their owners touch them.
- `CONTRIBUTING.md` rows of this area were adjusted (three lines); the other agents' rewrite of that file should keep them.
