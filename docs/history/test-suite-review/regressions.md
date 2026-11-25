# Regression ledger: every real bug of version 1 and the test that guards it

A regression is a bug that the old suite would have caught. This table is the audit of the Integrate step: for each fix of version 1
(`git log --grep fix`, `CHANGELOG.md`, `docs/spikes/`, the findings of the e2e and soak runs, the security review and the notes of the
three areas of this review) the test that fails when the bug comes back, and its layer. An id is `layer/test_file.py::Class` (every test
of the class) or `layer/test_file.py::Class::test_name`. `tests/fast/test_layout.py` resolves every id of this file, so a rename or a
deletion of a guard has to be a decision made here too. Layer `fast` runs in `sh tests/run.sh`; `slow` runs in Podman (`sh dev/test-slow.sh`)
because it needs a real tmux, a pty, ttyd or Chromium.

Since the tmux removal (herdr is the only multiplexer) the rows whose bug lived only in tmux, ttyd, the tmux panel of the sysop or
the ttyd page are gone, and so are the guards of those rows that tested only that code. The real-stop row of the sysop has no guard now: its only test drove a real tmux.

The three area ledgers in this folder say where each old test went; this file says what each bug is guarded by now.

## Named in the brief of the review

| Bug | Test | Layer |
|---|---|---|
| redact: quadratic time (100000 dashes took 110 s) | `fast/test_tabs_redact_dos.py::RedactTimeTest::test_adversarial_inputs_are_fast` | fast |
| redact: the JWT lookbehind (`\beyJ` let a hyphen in front hide it; the speed fix kept that) | `fast/test_tabs_redact_dos.py::RedactBehaviourTest::test_a_jwt_after_a_dash_is_redacted_as_it_was_before_the_speed_fix` | fast |
| redact: a secret split by the colour markers, by hard line breaks, by the cut of a long line | `fast/test_tabs.py::TestScreenSecretsAndMarkers` | fast |
| status.json written by two threads (reader and main) lost the newest state | `fast/test_sysop_service.py::StatusFile::test_two_threads_writing_status_json_leave_the_newest_state` | fast |
| the busy footer of an agent cut off in a narrow pane | `fast/test_tabs.py::TestAgentState::test_busy_in_a_narrow_pane_where_the_footer_is_cut` | fast |
| Esc (any key) on an open dialog of an agent is the user's decision: high risk, an approval at every autonomy level | `fast/test_sysop_policy.py::AgentTabs::test_a_dialog_on_the_screen_makes_every_key_high_esc_included`, `fast/test_sysop_policy.py::HooksReadlineAndDialogs::test_a_dialog_on_the_screen_of_a_tab_that_does_not_say_claude_is_an_agents_dialog` | fast |
| a dialog that opens while an action waits stops it | `fast/test_sysop_mcp.py::ServerWait::test_a_dialog_that_opens_while_an_action_waits_stops_it` | fast |
| the Whisper silence goal: a recording with no sound reached the recognizer and became a goal | `fast/test_voice_service.py::GoalOnTheBus::test_silence_is_nothing_heard_and_nothing_is_published`, `fast/test_voice_service.py::GoalOnTheBus::test_a_recording_with_no_sound_never_reaches_whisper_and_nothing_is_published` | fast |
| the stale fuse marker: one failed probe of native overlay left `.has-mount-program` = true, then every run died with "fuse: device not found" | `fast/test_serve_steps.py::NestedPodmanState::test_without_a_usable_fuse_the_stale_marker_is_removed_before_the_service_starts`, `fast/test_serve_steps.py::NestedPodmanState::test_a_usable_fuse_device_or_a_marker_that_says_false_leaves_the_marker_alone`, `slow/test_nested_fuse_real.py::NestedWithoutFuse` (needs a nested Podman: CI) | fast + slow |
| the serve test wiped the nested Podman state (runtime folder) of the box that ran it | `fast/test_serve_steps.py::NestedPodmanState::test_a_serve_test_never_points_step_8_at_the_real_runtime_folder_of_podman` | fast |
| audit rotation: the log grew for ever, two writers threw a generation away | `fast/test_sysop_soak.py::AuditLimit`, `fast/test_sysop_service.py::Flood::test_the_audit_file_rotates_instead_of_growing_without_bound` | fast |
| the disk full: the service, its log, the end of a goal and the watcher no longer die | `fast/test_sysop_soak.py::ServiceOnAFullDisk`, `fast/test_sysop_soak.py::LogOnAFullDisk`, `fast/test_sysop_soak.py::FullDiskEnds`, `fast/test_sysop_soak.py::FailedGoalOnAFullDisk`, `fast/test_sysop_soak.py::McpWithoutAudit` | fast |
| the burst Enter: a burst of sends failed; the Enter is its own step after a pause, a swallowed Enter is pressed once more | `fast/test_tabs.py::TestSend::test_run_is_text_then_a_separate_enter_after_the_pause`, `fast/test_tabs.py::TestSend::test_a_swallowed_enter_is_pressed_once_more_and_the_text_is_not_typed_again` | fast |

## Sysop, bus, tabs and voice (the other findings of the soak and e2e runs)

| Bug | Test | Layer |
|---|---|---|
| a goal with a byte that is not UTF-8 killed the service | `fast/test_sysop_service.py::Surrogates` | fast |
| a flood of rejected goals filled the folders | `fast/test_sysop_service.py::Flood::test_rejected_goals_keep_little_and_the_folders_are_pruned_while_it_runs` | fast |
| the service died and nothing started it again: the watcher restarts it after 1, 2, 4 ... 30 s, gives up on a status 2, and the goals in flight are marked `failed` | `fast/test_sysop_watch.py::Scripted`, `fast/test_sysop_watch.py::RealService`, `fast/test_sysop_service.py::OwnProcess::test_kill_and_restart_loses_the_goal_in_flight_and_says_so` | fast |
| the locks of `swarmbox-tabs` (one per tab) and the bus survive a killed holder | `fast/test_tabs_locks.py::Locks`, `fast/test_bus.py::SingleInstance` | fast |
| the log of a daemon grew; output must follow the rotated file | `fast/test_sysop_soak.py::LogRotation` | fast |
| two SIGTERMs in a row left a traceback (voice) | `fast/test_voice_soak.py::TwoSigterms` | fast |
| a burst of recordings: at most N recognizers, a fixed busy answer, the places come back | `fast/test_voice_soak.py::Burst` | fast |
| the body that trickles in held a slot of the voice front for ever | `fast/test_voice_front.py::VoicePath::test_a_body_that_trickles_in_has_a_total_deadline` | fast |
| a framed page must not get the voice controls (frame-ancestors, X-Frame-Options) | `fast/test_voice_front.py::VoicePath` | fast |
| a brain left running after an error of the supervisor | `fast/test_sysop_brain.py::BrainSupervision` | fast |
| a bus supervisor kill or restart in a burst; the stale socket | `fast/test_bus_serve.py`, `fast/test_bus_cli.py::NotRunning` | fast |
| the bus: a group whose members are all stuck is busy, a busy group does not stop the others, `--allow-none` does not hide it | `fast/test_bus.py::Groups`, `fast/test_bus.py::Receivers::test_allow_none_does_not_hide_a_busy_group` | fast |
| `pub` with invalid UTF-8 or NaN/Infinity reached a subscriber as bare JSON | `fast/test_bus_cli.py::Pub::test_invalid_utf8_on_stdin_is_6`, `fast/test_bus_cli.py::Pub::test_nan_and_infinity_are_text_and_never_reach_a_subscriber_as_bare_json` | fast |
| tabs: a busy agent is refused unless `--queue`; Esc interrupts a busy agent | `fast/test_tabs.py::TestSend::test_a_busy_agent_is_refused_unless_queue` | fast |
| tabs: locks per tab survive a killed holder | `fast/test_tabs_locks.py` | fast |
| the risk of a text typed into a shell or an agent (slash and bang, hooks, readline, history expansion, state builtins, reads of the login) | `fast/test_sysop_policy.py::RiskTable`, `fast/test_sysop_policy.py::HooksReadlineAndDialogs`, `fast/test_sysop_policy.py::ShellInput`, `fast/test_sysop_policy.py::LineEnds` | fast |

## Host, installer, box start and the shell of the box

| Bug (CHANGELOG, git log, security review) | Test | Layer |
|---|---|---|
| a host reboot left the runtime folder of the nested Podman with the old boot ID | `fast/test_serve_steps.py::NestedPodmanState::test_a_stale_runtime_folder_of_nested_podman_is_removed_before_the_service_starts` | fast |
| after a reboot the run folder was not writable, no ready marker, `up` timed out | `fast/test_serve_steps.py::RunFolderNotWritable` | fast |
| the logs of the box grew for ever (cut to the last megabyte past 4 MiB) | `fast/test_serve_logs.py::Trimmer` | fast |
| a bus supervisor that ended by itself left a pid file whose USR1 kills; crash loops of ttyd and the bus give up after five exits | `fast/test_serve_steps.py::BusStep`, `fast/test_serve_steps.py::Supervisor` | fast |
| the glint of the banner left letters behind and rewrote whole rows | *(retired — `banner.sh` was removed)* | — |
| security review SR-01: an image reference that starts with `-` | `fast/test_security_review.py::ImageReferenceTest` | fast |
| SR-02, SR-03: private folders, no write through a planted symlink at a predictable temporary name, a lock released by a signal | `fast/test_security_review.py::TempFileTest`, `fast/test_security_review.py::ModeTest`, `fast/test_security_review.py::CleanupTest` | fast |
| SR-04: `cloudflare.json` with mode 600, written to a new file renamed over the old one | `fast/test_cloudflare_setup.py::TestSafetyAndErrors`, `fast/test_security_review.py::TokenTest` | fast |
| SR-05: a helper archive with absolute, `..`, link or device members | `fast/test_host_update.py::FailureTest` | fast |
| `config set` refused shell metacharacters; the config file is parsed, never sourced | `fast/test_security_review.py::QuotingTest`, `fast/test_security_review.py::ConfigParsingTest` | fast |
| the update tests broke at the version they used | `fast/test_host_update.py::NewerVersionLiteralsTest` | fast |
| the installer accepted a placeholder image name | `fast/test_install.py::InstallRunTest` | fast |
| no progress shown while the image was pulled; the percent went back, a Nerd Font glyph, `unpack` | `fast/test_pull_ui.py::PullUiTest`, `fast/test_host_update.py::PullProgressTest` | fast |
| two `up` at once made two boxes; a killed `up` left a lock | `fast/test_host_up.py::LockTest` | fast |
| `--web` on an existing box: the connector was not brought up | `fast/test_host_connector.py::ConnectorTest` | fast |
| ports are published on 127.0.0.1 by default; a new container gets an init and the time zone of the host | `fast/test_host_create_flags.py::KeyTest::test_ports_default_is_loopback_only`, `fast/test_host_create_flags.py::KeyTest::test_init_1_emits_init_0_does_not`, `fast/test_host_create_flags.py::KeyTest::test_tz_local_zone_and_off` | fast |
| `yolo` with an agent that is no command, or is `yolo`, called itself | `fast/test_bashrc_fragment.py::Yolo` | fast |
| the auto-approve flags go only to the interactive prompt of an agent, never to `claude update` or `claude mcp ...`; agents are functions, not aliases | `fast/test_addon_agent_shell.py::ClaudeShell`, `fast/test_addon_agent_shell.py::ThroughTheFragment` | fast |
| macOS: BSD `stat`, extended attributes, a long temporary folder; the 100-character socket path | `fast/test_host_config.py::ModeCheckTest`, `fast/test_host_socket.py::BoundaryTest` | fast |
| with `BROWSER_URL` set the Chrome DevTools MCP attaches to that browser (the unprefixed variable is not read) | `fast/test_mcp_registry.py::McpCase` | fast |
| the colours of the Claude Code theme in tmux: `CLAUDE_CODE_TMUX_TRUECOLOR` is set in the shell of the box | `fast/test_theme.py` | fast |
| the npm installers of the addons wrote into the home (node-gyp headers, logs) | `fast/test_addon_clasp_poetry.py::NpmAddonInstallTest::test_writes_nothing_outside_the_prefix` | fast |
| an addon whose program is the shim looped, a manifest with a path or a glob as VERSION or COMMANDS, a self-updating addon pinned | `fast/test_addon_shim.py::LoopGuard`, `fast/test_addon_use_remove.py::HostileManifests`, `fast/test_addon_use_remove.py::Use::test_self_updating_addon_is_refused`, `fast/test_addon_install.py::InstallSelf` | fast |
| the wizard for the voice installer: unknown models and versions are refused before any download, a checksum is checked before the download | `fast/test_addon_voice.py::InstallTests`, `fast/test_addon_go_gcloud.py::InstallTest` | fast |
| the nested Podman run without `/dev/fuse` | `fast/test_serve_steps.py::NestedPodmanState`, `slow/test_nested_fuse_real.py::NestedWithoutFuse` | fast + slow |

## Web terminal, page and strip

| Bug | Test | Layer |
|---|---|---|
| accents typed alone were dropped: the web server always runs with a UTF-8 locale | `fast/test_web_server.py::Run::test_the_server_always_gets_a_utf8_locale_so_an_accent_typed_alone_is_not_dropped` | fast |
| `swarmbox-web restart` signalled a stale, garbage or unsafe pid (0, 1, -1) | `fast/test_web_server.py::Restart::test_a_stale_garbage_or_unsafe_pid_is_refused_and_nothing_is_signalled` | fast |
| the voice page: light, answers, denied microphone, blur ends the recording, a mic and a light only | `fast/test_voice_web.py` | fast |

## Repository machinery, CI and release

| Bug | Test | Layer |
|---|---|---|
| a step with `: ` in its name makes GitHub show no job; a step with neither `run` nor `uses` | `fast/test_workflows.py::BothWorkflows` | fast |
| the macOS job named a test file by hand (a copy of a list): its list is in one place | `fast/test_workflows.py::Ci::test_linux_runs_fast_and_slow_and_macos_runs_the_list_in_one_place`, `fast/test_layout.py::Layout::test_the_macos_list_names_existing_fast_files` | fast |
| the real-installer step in CI did not fail when the tests failed (no pipefail) | `fast/test_workflows.py::Ci` | fast |
| a release: placeholders, a gate or a release check that fails puts the files back, a CI failure leaves no tag, a wrong checksum or version is a failure, the image tags agree | `fast/test_release_script.py::FullRelease`, `fast/test_release_script.py::ImageVerification` | fast |
| the release check modifies nothing; a tag on another commit than HEAD fails | `fast/test_release_check.py::ReleaseCheckTest` | fast |
| the gate passed only with the variables of the developer's terminal | `fast/test_dev_check.py::CheckScriptTest` | fast |
| the test image drifts from the product image (and must not bring tmux or ttyd back) | `fast/test_layout.py::Layout::test_the_test_image_has_no_tmux_or_ttyd_either`, `fast/test_dockerfile.py::Pins` | fast |
| old names of the addon concept; default names written as literals | `fast/test_guard_names.py::TheRepository`, `fast/test_guard_names.py::TheOldNamesScanner` | fast |
| a test that leaks a process, or starts a real tmux on a machine that is not a container | `fast/test_runner.py`, `fast/test_layout.py` | fast |
| the mutation harness: a plan replays the same mutants, the helper modules of the tests are followed | `fast/test_mutate.py` | fast |
| the Dockerfile stops installing `swarmbox-attach`, or stops making a script copied to `/usr/local/bin` executable | `fast/test_dockerfile.py::Image::test_every_script_copied_to_usr_local_bin_is_made_executable_and_attach_is_one` | fast |
| a test of the sysop addon split its panel into the tmux server of the machine that ran the suite | `fast/test_sysop_addon.py::Tree` and `tests/support/sysop_support.py::Env` give a private socket, `TMUX_TMPDIR` and `TMPDIR` | fast |
| `dev/release.sh --bump-only` left its backup of the changelog in `/tmp` | `fast/test_release_script.py::Bump::test_bump_only_rewrites_the_three_files_and_commits_nothing` | fast |

## Fixes of code that no longer exists

The fixes of the first commits (the memory MCP server and its WAL and busy timeout, the hooks of the memory agent, `start.sh` messages, the Playwright and Vite
installs, the port 8338 -> 8889 of the memory dashboard, `CLAUDE.md` deployment) are of files that were deleted before version 1 (`git log --diff-filter=D`):
nothing is left to regress. The `swarmbox-migrate` of the 2.0 layout was dropped with them. The fixes of the shell fragment, the installer, `swarmbox update`,
the web terminal and the image that are still in the tree are the rows above.
