# Cleanup log

Decisions of the unattended test-suite cleanup (one entry each: what, why, how to undo).
Undo any entry with `git revert` of the commit named in it, or `git show <commit>` to see the deleted files.

## Baseline measurement (before cleanup)

tests/ had 28254 lines in 85 files. Seconds per file, one run in the foreground:

| file | tests | seconds |
|---|---|---|
| test_attach_command.py | 49 | 24.9 |
| test_attach_container.py | 5 | 0.0 |
| test_bashrc_container.py | 6 | 0.0 |
| test_bashrc_fragment.py | 43 | 0.3 |
| test_build_index.py | 5 | 0.0 |
| test_ci_workflow.py | 29 | 1.9 |
| test_cloudflare_setup.py | 62 | 5.3 |
| test_default_names_lint.py | 5 | 0.0 |
| test_design_partb.py | 5 | 0.0 |
| test_dev_build.py | 13 | 0.1 |
| test_dirs.py | 13 | 0.1 |
| test_dockerfile.py | 42 | 0.0 |
| test_docs_consistency.py | 101 | 0.1 |
| test_entrypoint.py | 19 | 0.3 |
| test_final_audit.py | 11 | 0.2 |
| test_function_bash.py | 134 | 11.2 |
| test_function_fish.py | 65 | 0.0 |
| test_function_zsh.py | 66 | 0.0 |
| test_helpers.py | 30 | 0.7 |
| test_history_audit.py | 16 | 0.1 |
| test_host_config.py | 69 | 4.7 |
| test_host_connector.py | 19 | 3.0 |
| test_host_create_flags.py | 101 | 4.0 |
| test_host_remote.py | 37 | 2.7 |
| test_host_remote_e2e_fake.py | 4 | 61.1 |
| test_host_shells.py | 7 | 0.7 |
| test_host_socket.py | 27 | 2.6 |
| test_host_up.py | 120 | 19.4 |
| test_host_update.py | 34 | 2.2 |
| test_image_build.py | 10 | 0.0 |
| test_image_with_tools.py | 6 | 0.0 |
| test_init_output.py | 28 | 0.3 |
| test_mcp_registry.py | 17 | 1.2 |
| test_migration.py | 27 | 1.1 |
| test_migration_e2e.py | 12 | 0.5 |
| test_name_check.py | 7 | 0.0 |
| test_owner_check.py | 32 | 2.4 |
| test_parity.py | 44.8 |  |
| test_pubkey_ensure.py | 9 | 0.1 |
| test_record_checksums.py | 18 | 0.6 |
| test_registry_e2e.py | 1 | 0.0 |
| test_release_check.py | 19 | 1.2 |
| test_release_checklist.py | 11 | 0.0 |
| test_release_docs.py | 10 | 0.1 |
| test_release_version.py | 7 | 0.0 |
| test_release_workflow.py | 29 | 0.0 |
| test_repo_files.py | 9 | 0.0 |
| test_retired.py | 8 | 0.1 |
| test_retired_coverage.py | 8 | 0.0 |
| test_run_all.py | 6 | 0.4 |
| test_security_review.py | 54 | 4.4 |
| test_serve_container.py | 4 | 0.0 |
| test_serve_steps.py | 42 | 10.5 |
| test_smoke_skeleton.py | 14 | 0.0 |
| test_spikes_common.py | 7 | 0.0 |
| test_ssh_key.py | 5 | 0.0 |
| test_starship.py | 20 | 0.4 |
| test_third_party_notices.py | 22 | 0.1 |
| test_tool_claude_real.py | 14 | 0.0 |
| test_tool_doctor.py | 19 | 3.1 |
| test_tool_gemini_clasp_poetry.py | 33 | 0.5 |
| test_tool_go_gcloud.py | 24 | 0.4 |
| test_tool_image_level.py | 16 | 0.7 |
| test_tool_install.py | 50 | 11.0 |
| test_tool_link.py | 31 | 0.6 |
| test_tool_manifest.py | 44 | 0.7 |
| test_tool_new.py | 5 | 0.1 |
| test_tool_opencode.py | 42 | 1.4 |
| test_tool_prepare.py | 19 | 1.4 |
| test_tool_real.py | 59 | 0.1 |
| test_tool_shim.py | 23 | 0.7 |
| test_tool_stub.py | 12 | 0.1 |
| test_tool_use_remove.py | 17 | 2.8 |
| test_update_bot_config.py | 18 | 0.0 |
| test_web_build.py | 42 | 1.6 |
| test_web_container.py | 5 | 0.0 |

Sum: about 194 s (test_parity was stopped by me after 45 s because it is deleted anyway, so the real before-total is a little higher).
Skipped: test_clipboard_bridge, test_web_style, test_tmux_browser_keys (browser tests). No other file needed the network; the real-image tests skip themselves when no image exists.
Note: the run left 36 orphan `sleep infinity` processes (serve tests); killed only those with PPID 1.

## Decisions

All entries: undo with `git revert` of the commit that holds the change (see `git log -- <path>`).

- Step 2, migration removed: `swarmbox-migrate.sh`, its call (serve step 4, the number stays unused so health messages and tests keep their numbers), its Dockerfile lines, `docs/migration.md`, the README and CHANGELOG sections, the migration tests. Why: owner said no v0.1.0 compatibility. The README keeps no v0.1.0 section.
- Step 2, deleted v1/process tests: test_parity, record_v010_flags and the v1 flag fixture, test_retired, test_retired_coverage, audit_history, test_history_audit, test_final_audit, dev/final-audit.sh, docs/history-audit.md, tests/spikes and test_spikes_common, test_design_partb, test_release_docs, test_smoke_skeleton (tests/smoke_image.py stays, CI runs it), test_registry_e2e + e2e_registry + docs/local-registry.md (needs a registry), test_update_bot_config. Why: they only guard the overnight process or v1.
- Step 2, kept `dev/record-checksums.sh`: CONTRIBUTING, the PR template, dependabot.yml and the go/gcloud tool.conf files tell maintainers to run it. Its test stays (test_record_checksums).
- Step 2, kept test_build_index: 5 fast tests of a real build script (`container/web/build-index.sh`), not a process artifact.
- Step 2, `dev/owner-check.sh` and test_owner_check deleted; `docs/owner-checks.md` rewritten as a plain checklist table (the B6..B34 facts, B20 and the clean-machine walk-through kept, the script ids dropped). Undo: revert the commit and restore the old doc.
- Step 2, test_docs_consistency (1100 lines of phase-close and wording audits) replaced by 6 guards: README commands exist, relative links of the user docs resolve, no `<org>`, topics, quick start, security wording.
- Step 2, test_ci_workflow rewritten as 10 text checks without PyYAML (it used to pip-install PyYAML into a venv). ci.yml now runs `sh tests/run_all.sh` in the linux job instead of listing 80 files by hand.
- The historical docs (design.md, decision-log.md, implementation-plan.md, implementation-status.md, overnight-report.md) still mention deleted files and the migration. I left them as history; no test reads them any more. A later step may prune or delete them.

- Step 3, shrinking: tests were removed by name, keeping one test per behaviour or branch and dropping copies, table-driven repeats, wording-of-docs tests and implementation-detail tests. Biggest cuts: test_host_up 1257 to 620 lines, test_host_create_flags 1090 to 548, test_host_config 917 to 412, test_cloudflare_setup 844 to 438, test_attach_command 818 to 501, test_security_review 818 to 378 (the security-review doc table of docs/security-review.md still names some removed tests; its own checking test is gone). Undo: `git revert` the commits titled "test: trim ..." / "test: further trim ...".
- Step 3, deleted whole files beyond step 2: test_release_checklist (doc wording), test_tool_claude_real (its real run is the claude row of test_tool_real, its fake-curl cases are in test_tool_manifest), test_serve_container, test_attach_container, test_web_container (smoke_image.py covers the same steps in the real image; CI still runs smoke_image, test_bashrc_container, test_image_build and test_image_with_tools). The shared image set-up moved to tests/image_support.py. I could not run the image tests here (no SWARMBOX_IMAGE_BUILD), so that move is checked only by import and skip.
- Step 3, test_ci_workflow and test_release_workflow were rewritten as plain text checks; PyYAML (which the old test pip-installed into a venv under /tmp) is not needed any more.
- Step 3, `BashPosixFunction` (the same function cases run a second time under `bash --posix`) was removed; test_host_shells still covers the helper under POSIX shells.
- Step 3 fix: test_host_remote_e2e_fake waited 60 s on a real network check of `talkr.run` in `remote status`; it now passes `--verify-timeout 1` (61 s to 3.5 s). Undo: remove that argument.
- Step 3, v0.1.0-flavoured tests that are left: one test that a v0.1.0 container is refused by `up` (product behaviour that still exists). Remove it together with the product code in the later simplification step.
- Step 4: `tests/run_all.sh` prints seconds per file and the total, and runs every file under `tests/reap_run.py`, a wrapper that becomes a child subreaper (Linux prctl) and, when the file ends, kills by PID the processes it adopted ("reaped N" in the line). No kill by name. test_run_all has a test for it. Undo: revert the commit "run_all.sh prints seconds".
- Step 5: leaks fixed at the source. test_serve_steps kills the whole process group of each `serve` it starts (its `sleep infinity`), and the `cf-slow` and `slow-flags` helper scripts of test_host_up and test_security_review stop when their test folder is gone. A full run now reaps nothing.
- Step 6: CONTRIBUTING.md describes the layout by groups of files instead of one row per file; `swarmbox:dev` is now `swarmbox-dev:local`; test_repo_files no longer requires every test file to be named there.
- ci.yml: the linux job runs `sh tests/run_all.sh`; the macos list lost the deleted files; the three deleted container tests were removed from the smoke job.

## Result

| | before | after |
|---|---|---|
| lines in tests/ (py, sh, fixtures) | 28254 | 13654 |
| test files test_*.py | 83 | 60 |
| tests (all files run here) | about 2100 | 662 |
| whole suite, seconds (browser tests excluded) | about 194 s, test_parity not finished (stopped at 45 s); the old run_all had no timing | 44 s |

Not reached: the target of about 12000 lines. What is left is mostly set-up code of fakes (host_up, create_flags, host_config, security_review, function_cases, helpers) plus tests/smoke_image.py (569 lines, run by CI) and the three browser tests (636 lines, scheduled CI, not run here). I kept those because each remaining test guards a real behaviour.

Kept on purpose: tests/test_default_names_lint.py, tests/test_repo_files.py, test_build_index.py (real build script), test_record_checksums.py (the script is referenced by CONTRIBUTING, the PR template, dependabot.yml and tool.conf), test_name_check.py, test_release_check.py and test_release_version.py (release.yml uses the version script), test_dev_build.py, the three browser tests (not run here: need chromium).

Skipped in the final run (by design): the real-image tests (no SWARMBOX_IMAGE_BUILD), the real installers (no network), zsh and fish function tests (those shells are not installed in this box), and the three browser tests. Everything else passes.

Files deleted in total (git diff --diff-filter=D 3eaa045..HEAD): 47 files, listed by `git diff --diff-filter=D --name-only 3eaa045 HEAD`.

Owner review: (1) the old design/plan/status/decision-log/overnight-report docs still name deleted files and the migration; (2) docs/security-review.md maps findings to test names, some now removed; (3) the image tests were not run here.

## Step 7: first end-to-end run in nested containers

Image built with `dev/dev-build.sh` (72 s with a warm base cache, 1.75 GB). Walked the journey with the generated bash function and a temp workspace (box `swarmbox-test-box`, random high web port). Everything below is undone with `git revert` of the commits titled "ux: ...".

Worked on the first try: init output for bash, zsh and fish (zsh and fish only read), first `swarmbox up` (1.7 s with the image present), attach into tmux `main` (shared, idle window closed), `config`, `env`, `pubkey`, ssh key kept across `reset`, `url`, `stop` twice, `up` twice and in parallel, a busy port, a taken workspace, a missing /dev/net/tun (exit 3, clear), `tool list/install/use/remove` with the real go tool from go.dev, shims, `claude --version` after the background install, git, the web terminal (page, clipboard script, a foreign Origin refused), nested Podman (`podman run alpine` pulled and ran in the box).

Rough edges found and fixed:
- `swarmbox --help` (and `help`, `-h`) created the box and ran `bash --help`. Now the host prints the command list and exits 0; the three function templates route the words to the host. Regenerate the function with `init` to get it. The helper's own usage no longer says `swarmbox-host` and lists the user commands only.
- `swarmbox <command>` (for example `swarmbox ls`) showed nothing: the tmux window closes and takes the output. The last screen of the window is now printed after it closes. Side effect: after `swarmbox claude` the last screen of Claude Code is printed too.
- `up` and `reset` said "the banner shows them" about warnings but print no banner. They now print the warnings.
- A busy web port: the message now names the command (`swarmbox config set WEB_PORT <port+1>`), once.
- A container with the box name that SwarmBox did not make was reported as "made by SwarmBox v0.1.0" and told the user to set WORKSPACE to "unknown". Now one plain message (exit 5 as before).
- `swarmbox pubkey` printed colour codes when piped and the path `.work/.ssh/...` (v0.1 leftover). Fixed both; same `.work` comment in tmux.conf.
- `swarmbox tool`: usage said "phase", `--help` was an error (exit 70), `tool update <managed tool>` said "later phase". Now a real usage (exit 64), and `update` explains how to update a managed tool. `install go --version 1.2.3` failed with a checksum mismatch; it now says the tool is pinned.
- "another creation setting changed (the fingerprint differs)" now reads "a setting changed since the box was created".
- Removed the unused `swarmbox-podman-service` script (v0.1 leftover, nothing called it).

Not fixed, for the owner:
- Nested Podman did not start in the box here: `newuidmap` fails because the development box's own user namespace is 1000 ids narrower than the box's `/etc/subuid` range (agent:1001:64535). With `/etc/subuid` set to 63535 inside the box, `podman run` worked. A real host with a normal 65536 subuid range should be fine; I did not shrink the range in the Dockerfile because images that run as nobody (65534) would stop working. Verify on a real host.
- The development box has utsns=host, so `--hostname` is refused; I ran with a `podman` wrapper that drops it (outside the repository).
- `swarmbox url` prints the public address built from a saved Cloudflare domain even when this box was never exposed (by design of `public_host`); it can look wrong for a second box.
- `remote ...` stops at the missing API token with a long permission list; nothing else was tried (no Cloudflare account).
- `swarmbox update` could not be run (no registry); `tool update` for managed tools does not exist.
- tmux prints `[exited]` before the output of a `swarmbox <command>`.

## Step 8: product code simplification

Undo any item with `git revert` of the commit titled "simplify: ..." / "test: ..." that holds it (`git log --oneline`).

- Removed v0.1.0 and "phase"/"slice" wording from the code, comments, Dockerfile, CI header and docs (README, CONTRIBUTING, cloudflare.md, web-terminal.md). The doc claim that the box moves `.swarmbox/web-terminal.conf` was false (no code does it) and is gone.
- `swarmbox-host`: the TZ spellings `OFF`, `none`, `NONE` (v0.1.0 only) are no longer accepted; use `off`. The foreign-container refusal (no `swarmbox.managed` label, exit 5) stays as a generic safety guard, with a plain message ("SwarmBox did not make"); the label value 2 is unchanged.
- `swarmbox-host`: one `opt_arg` helper replaces four copies of the `--x V` / `--x=V` parser (seed, create-flags, fingerprint, update); one `resolve_valid` replaces four copies of resolve-then-validate; the two env loops of create-flags are one. Header comment rewritten.
- `swarmbox url` (and `remote status`) print the public address only when `cloudflare.json` was saved for this box (its `name` equals the box name) or `SWARMBOX_WEB_HOSTNAME`/`SWARMBOX_WEB_DOMAIN` is set. Side effect: `cloudflare.json` keeps one name, so after `remote setup` for a second box the first box prints no public address until its `remote setup` is run again. Test added; the existing url test now saves the name.
- `[exited]` before the output of `swarmbox <command>`: accepted, not changed. It is tmux's own message when the grouped client ends; hiding it means moving the cursor up and erasing a line, which erases a real line (the prompt) whenever tmux printed something else (`[detached]`, nothing). Not safe for a small change.
- `swarmbox-tool`: `need_tdir` and `need_manifest` replace ten copies of the same two lines. All subcommands stay (validate, link, install, run, list, update, use, remove, new, doctor, prepare): each is in the usage text and has tests; `prepare` is called by `serve`. `new --repo/--dir` and `doctor --fix` are the least used; I left them.
- `cloudflare-setup.py`: `--print-token` removed (the `token` command does the same; the option had no test; its row in docs/cloudflare.md is gone); one `resolve_domain` instead of two copies; an unused return value of `step_tunnel` dropped.
- `entrypoint.sh`: removed the "not found" branches for scripts the image always installs (swarmbox-pubkey, -tool, -mcp, -web) and the direct-`ttyd` fallback. test_serve_steps and test_web_build now install their fake ttyd as `swarmbox-web` (the fallback they exercised is gone).
- Checked and left alone: no unused function in swarmbox-host, the scripts or cloudflare-setup.py (grep by name); every file under dev/ is referenced by CONTRIBUTING, a workflow or a test (kata-probe.sh is kept for the owner); no `__pycache__` is tracked and .gitignore covers it. The Dockerfile packages were kept (users may rely on pip, build-essential, wget); only comments changed.
- Image check: `SWARMBOX_IMAGE_BUILD=1 python3 tests/smoke_image.py` (reduced mode): 11 passed, 0 failed, 2 skipped (nested-podman, nested-cgroup need the third nesting level). The image was built by dev-build.sh inside the run and removed by it; no swarmbox-test- container, image or volume is left. The pids count stayed near 170 (limit 16384).
- Lines before to after: swarmbox-host 2301 to 2244, swarmbox-tool.sh 1475 to 1477 (header and two helpers; a net saving was not found without removing subcommands), cloudflare-setup.py 796 to 790, entrypoint.sh 434 to 402, Dockerfile 208 to 207. Tests: 665 in 57 files, all green.
- Owner review: (1) `url` after a second box's `remote setup`; (2) keep or drop `tool new --repo/--dir` and `doctor --fix`; (3) the TZ spelling change.
