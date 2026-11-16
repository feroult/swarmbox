# Regression ledger: every real bug of version 1 and the test that guards it

A regression is a bug that the old suite would have caught. This table is the audit of the Integrate step: for each fix of version 1
(`git log --grep fix`, `CHANGELOG.md`, `docs/spikes/`, the findings of the e2e and soak runs, the security review and the notes of the
three areas of this review) the test that fails when the bug comes back, and its layer. An id is `layer/test_file.py::Class` (every test
of the class) or `layer/test_file.py::Class::test_name`. `tests/fast/test_layout.py` resolves every id of this file, so a rename or a
deletion of a guard has to be a decision made here too. Layer `fast` runs in `sh tests/run.sh`; `slow` runs in Podman (`sh dev/test-slow.sh`)
because it needs a real tmux, a pty, ttyd or Chromium.

The three area ledgers in this folder say where each old test went; this file says what each bug is guarded by now.

## Named in the brief of the review

| Bug | Test | Layer |
|---|---|---|
| redact: quadratic time (100000 dashes took 110 s) | `fast/test_tabs_redact_dos.py::RedactTimeTest::test_adversarial_inputs_are_fast` | fast |
| redact: the JWT lookbehind (`\beyJ` let a hyphen in front hide it; the speed fix kept that) | `fast/test_tabs_redact_dos.py::RedactBehaviourTest::test_a_jwt_after_a_dash_is_redacted_as_it_was_before_the_speed_fix` | fast |
| redact: a secret split by the colour markers, by hard line breaks, by the cut of a long line | `fast/test_tabs.py::TestScreenSecretsAndMarkers` | fast |
| status.json written by two threads (reader and main) lost the newest state | `fast/test_sysop_service.py::StatusFile::test_two_threads_writing_status_json_leave_the_newest_state` | fast |
| the tab renamed `python3`: tmux names a window after the active pane and the panel had the focus | `fast/test_sysop_dock_logic.py::TabName` (the freeze and thaw state machine), `slow/test_sysop_dock.py::TabName` (real tmux) | fast + slow |
| the busy footer of an agent cut off in a narrow pane | `fast/test_tabs.py::TestAgentState::test_busy_in_a_narrow_pane_where_the_footer_is_cut` | fast |
| Esc (any key) on an open dialog of an agent is the user's decision: high risk, an approval at every autonomy level | `fast/test_sysop_policy.py::AgentTabs::test_a_dialog_on_the_screen_makes_every_key_high_esc_included`, `fast/test_sysop_policy.py::HooksReadlineAndDialogs::test_a_dialog_on_the_screen_of_a_tab_that_does_not_say_claude_is_an_agents_dialog` | fast |
| a dialog that opens while an action waits stops it | `fast/test_sysop_mcp.py::ServerWait::test_a_dialog_that_opens_while_an_action_waits_stops_it` | fast |
| the Whisper silence goal: a recording with no sound reached the recognizer and became a goal | `fast/test_voice_service.py::GoalOnTheBus::test_silence_is_nothing_heard_and_nothing_is_published`, `fast/test_voice_service.py::GoalOnTheBus::test_a_recording_with_no_sound_never_reaches_whisper_and_nothing_is_published` | fast |
| the stale fuse marker: one failed probe of native overlay left `.has-mount-program` = true, then every run died with "fuse: device not found" | `fast/test_serve_steps.py::NestedPodmanState::test_without_a_usable_fuse_the_stale_marker_is_removed_before_the_service_starts`, `fast/test_serve_steps.py::NestedPodmanState::test_a_usable_fuse_device_or_a_marker_that_says_false_leaves_the_marker_alone`, `slow/test_nested_fuse_real.py::NestedWithoutFuse` (needs a nested Podman: CI) | fast + slow |
| the serve test wiped the nested Podman state (runtime folder) of the box that ran it | `fast/test_serve_steps.py::NestedPodmanState::test_a_serve_test_never_points_step_8_at_the_real_runtime_folder_of_podman` | fast |
| audit rotation: the log grew for ever, two writers threw a generation away | `fast/test_sysop_soak.py::AuditLimit`, `fast/test_sysop_service.py::Flood::test_the_audit_file_rotates_instead_of_growing_without_bound` | fast |
| the disk full: the service, its log, the end of a goal and the watcher no longer die | `fast/test_sysop_soak.py::ServiceOnAFullDisk`, `fast/test_sysop_soak.py::LogOnAFullDisk`, `fast/test_sysop_soak.py::FullDiskEnds`, `fast/test_sysop_soak.py::FailedGoalOnAFullDisk`, `fast/test_sysop_soak.py::McpWithoutAudit` | fast |
| the hooks flood: one redock process per resize event | `fast/test_sysop_soak.py::RedockCoalescing`, `fast/test_sysop_soak.py::RedockFastPath` | fast |
| the burst Enter: a burst of sends failed; the Enter is its own step after a pause, a swallowed Enter is pressed once more | `fast/test_tabs.py::TestSend::test_run_is_text_then_a_separate_enter_after_the_pause`, `fast/test_tabs.py::TestSend::test_a_swallowed_enter_is_pressed_once_more_and_the_text_is_not_typed_again`, `slow/test_tabs_real.py::TestAgent::test_a_burst_would_have_failed_and_the_driver_does_not_burst` | fast + slow |
| the window-resized hook passes the window that changed and fits only that window | `fast/test_sysop_soak.py::RedockFastPath`, `slow/test_sysop_dock.py::HookRedock`, `slow/test_sysop_always.py::Resizing` | fast + slow |

## Sysop, bus, tabs and voice (the other findings of the soak and e2e runs)

| Bug | Test | Layer |
|---|---|---|
| a goal with a byte that is not UTF-8 killed the service | `fast/test_sysop_service.py::Surrogates` | fast |
| a flood of rejected goals filled the folders | `fast/test_sysop_service.py::Flood::test_rejected_goals_keep_little_and_the_folders_are_pruned_while_it_runs` | fast |
| the log of a daemon grew; output must follow the rotated file | `fast/test_sysop_soak.py::LogRotation` | fast |
| two SIGTERMs in a row left a traceback (voice) | `fast/test_voice_soak.py::TwoSigterms` | fast |
| a burst of recordings: at most N recognizers, a fixed busy answer, the places come back | `fast/test_voice_soak.py::Burst` | fast |
| the body that trickles in held a slot of the voice front for ever | `fast/test_voice_front.py::VoicePath::test_a_body_that_trickles_in_has_a_total_deadline` | fast |
| a framed page must not get the voice or strip controls (frame-ancestors, X-Frame-Options) | `fast/test_voice_front.py::VoicePath`, `fast/test_web_strip_script.py::FakeDom` | fast |
| a brain left running after an error of the supervisor | `fast/test_sysop_brain.py::BrainSupervision` | fast |
| keys typed in the tab while a goal arrives answered an action that had just appeared (the keys guard; the panel never takes the focus) | `fast/test_sysop_panel.py::Keys::test_keys_are_ignored_for_half_a_second_after_a_new_action`, `slow/test_sysop_dock.py::NoFocus`, `slow/test_sysop_always.py::NoFocusSteal`, `slow/test_sysop_web.py` | fast + slow |
| the text that does not fit cannot be allowed with `run`; a long command is shown whole | `fast/test_sysop_panel.py::ApprovalRequest` | fast |
| the result of the last goal in a short pane; a paragraph whole or gone | `fast/test_sysop_panel.py::IdleScreen` | fast |
| the panel in a portrait, landscape, narrow or short window; a resize flips the layout | `fast/test_sysop_dock_logic.py::LayoutRule`, `slow/test_sysop_always.py::Resizing` | fast + slow |
| the real stop ends the goal and nothing more is typed (pid of its own brain, never a `pgrep` of the machine) | `slow/test_sysop_real.py` | slow |
| a bus supervisor kill or restart in a burst; the stale socket | `fast/test_bus_serve.py`, `fast/test_bus_cli.py::NotRunning` | fast |
| the bus: a group whose members are all stuck is busy, a busy group does not stop the others, `--allow-none` does not hide it | `fast/test_bus.py::Groups`, `fast/test_bus.py::Receivers::test_allow_none_does_not_hide_a_busy_group` | fast |
| `pub` with invalid UTF-8 or NaN/Infinity reached a subscriber as bare JSON | `fast/test_bus_cli.py::Pub::test_invalid_utf8_on_stdin_is_6`, `fast/test_bus_cli.py::Pub::test_nan_and_infinity_are_text_and_never_reach_a_subscriber_as_bare_json` | fast |
| tabs: a busy agent is refused unless `--queue`; Esc interrupts a busy agent | `fast/test_tabs.py::TestSend::test_a_busy_agent_is_refused_unless_queue`, `slow/test_tabs_real.py::TestAgent::test_esc_interrupts_a_busy_agent` | fast + slow |
| tabs: locks per tab survive a killed holder | `fast/test_tabs_locks.py` | fast |
| the risk of a text typed into a shell or an agent (slash and bang, hooks, readline, history expansion, state builtins, reads of the login) | `fast/test_sysop_policy.py::RiskTable`, `fast/test_sysop_policy.py::HooksReadlineAndDialogs`, `fast/test_sysop_policy.py::ShellInput`, `fast/test_sysop_policy.py::LineEnds` | fast |

## Host, installer, box start and the shell of the box

| Bug (CHANGELOG, git log, security review) | Test | Layer |
|---|---|---|
| a host reboot left the runtime folder of the nested Podman with the old boot ID | `fast/test_serve_steps.py::NestedPodmanState::test_a_stale_runtime_folder_of_nested_podman_is_removed_before_the_service_starts` | fast |
| after a reboot the run folder was not writable, no ready marker, `up` timed out | `fast/test_serve_steps.py::RunFolderNotWritable` | fast |
| the logs of the box grew for ever (cut to the last megabyte past 4 MiB) | `fast/test_serve_logs.py::Trimmer` | fast |
| a bus supervisor that ended by itself left a pid file whose USR1 kills; crash loops of ttyd and the bus give up after five exits | `fast/test_serve_steps.py::BusStep`, `fast/test_serve_steps.py::Supervisor` | fast |
| exit in a host terminal tab jumped to the window of another tab; the grouped session of a finished call stayed; a returning tab lost its place | `slow/test_attach_real.py::RealTmuxCase` | slow |
| the web terminal attaches to the session itself so the status bar (the tabs) stays | `fast/test_attach_command.py::InteractiveAttachFakeTests::test_web_attaches_to_the_session_itself_so_the_status_bar_stays`, `fast/test_web_build.py::Run::test_the_session_is_swarmbox_attach_when_it_exists_else_tmux_attach` | fast |
| the glint of the banner left letters behind and rewrote whole rows | `slow/test_banner_glint.py::Glint` | slow |
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
| the npm installers of the addons wrote into the home (node-gyp headers, logs) | `fast/test_addon_gemini_clasp_poetry.py::NpmAddonInstallTest::test_writes_nothing_outside_the_prefix` | fast |
| an addon whose program is the shim looped, a manifest with a path or a glob as VERSION or COMMANDS, a self-updating addon pinned | `fast/test_addon_shim.py::LoopGuard`, `fast/test_addon_use_remove.py::HostileManifests`, `fast/test_addon_use_remove.py::Use::test_self_updating_addon_is_refused`, `fast/test_addon_install.py::InstallSelf` | fast |
| the wizard for the voice installer: unknown models and versions are refused before any download, a checksum is checked before the download | `fast/test_addon_voice.py::InstallTests`, `fast/test_addon_go_gcloud.py::InstallTest` | fast |
| the nested Podman run without `/dev/fuse` | `fast/test_serve_steps.py::NestedPodmanState`, `slow/test_nested_fuse_real.py::NestedWithoutFuse` | fast + slow |

## Web terminal, page and strip

| Bug | Test | Layer |
|---|---|---|
| accents typed alone were dropped: ttyd now always runs with a UTF-8 locale | `fast/test_web_build.py::Run::test_ttyd_always_gets_a_utf8_locale_so_an_accent_typed_alone_is_not_dropped` | fast |
| ttyd stops reading a value at the first thing that parses: a font list lost its fallbacks (values are handed over as JSON) | `fast/test_web_build.py::Run::test_a_value_is_handed_to_ttyd_as_json_so_a_font_list_keeps_its_fallbacks` | fast |
| the Mac Option key must be Meta so Option+1..9 change the tmux window | `fast/test_web_build.py::Run::test_mac_option_is_meta_by_default_and_the_user_can_turn_it_off` | fast |
| tmux 3.5a has no pane scrollbar: the backport is pinned and checked; the scrollbar line loads quietly on an older tmux; the scroll is not modal | `fast/test_dockerfile.py::Pins`, `slow/test_tmux_browser_keys.py::BoxConfig::test_the_scrollbar_is_off_and_set_quietly_so_an_older_tmux_still_loads_the_file` | fast + slow |
| xterm.js reserves 15 px for a scrollbar it measures as zero when it keeps a history | `fast/test_web_build.py::Render::test_the_browser_keeps_no_scrollback_unless_the_bar_is_on_or_the_conf_sets_one`, `slow/test_web_style.py::WebStyle` | fast + slow |
| the browser must never answer an OSC 52 read request; Ctrl+V pastes, Ctrl+C copies only with a selection; the right click menu only when tmux has no mouse | `slow/test_clipboard_bridge.py::Defaults`, `slow/test_clipboard_bridge.py::OptOuts`, `slow/test_clipboard_bridge.py::RightClickWhileTmuxHasTheMouse`, `slow/test_clipboard_bridge.py::RightClickWhenNothingHasTheMouse` | slow |
| the strip never covers the last row; tmux has exactly the rows xterm shows; 44 px targets; phone, landscape, keyboard | `slow/test_web_strip.py::Desktop`, `slow/test_web_strip.py::Phone`, `slow/test_web_strip.py::Settings` | slow |
| a framed page gets no strip and no key button; a note ends by itself and a new one restarts the clock | `fast/test_web_strip_script.py::FakeDom` | fast |
| a hostile `stripKeys`, `padding` or `ctrlVPaste` value stays inside the page; a closing tag in an asset is escaped | `fast/test_web_strip_script.py::Render`, `fast/test_web_build.py::Render::test_a_value_cannot_inject_into_the_page`, `fast/test_web_build.py::BuildIndex::test_closing_tags_inside_assets_are_escaped` | fast |
| `swarmbox-web restart` signalled a stale, garbage or unsafe pid (0, 1, -1) | `fast/test_web_build.py::Restart::test_a_stale_garbage_or_unsafe_pid_is_refused_and_nothing_is_signalled` | fast |
| the mouse wheel scrolls five lines; a program that asks for the mouse gets the wheel; the keys file alone | `slow/test_tmux_browser_keys.py::BoxConfig`, `slow/test_tmux_browser_keys.py::KeysFileAlone` | slow |
| the voice page: light, answers, denied microphone, blur ends the recording, a mic and a light only | `slow/test_voice_page_browser.py`, `fast/test_voice_page.py`, `fast/test_voice_web.py` | fast + slow |

## Repository machinery, CI and release

| Bug | Test | Layer |
|---|---|---|
| a step with `: ` in its name makes GitHub show no job; a step with neither `run` nor `uses` | `fast/test_workflows.py::BothWorkflows` | fast |
| the macOS job named a test file by hand (a copy of a list): its list is in one place | `fast/test_workflows.py::Ci::test_linux_runs_fast_and_slow_and_macos_runs_the_list_in_one_place`, `fast/test_layout.py::Layout::test_the_macos_list_names_existing_fast_files` | fast |
| the real-installer step in CI did not fail when the tests failed (no pipefail) | `fast/test_workflows.py::Ci` | fast |
| a release: placeholders, a gate or a release check that fails puts the files back, a CI failure leaves no tag, a wrong checksum or version is a failure, the image tags agree | `fast/test_release_script.py::FullRelease`, `fast/test_release_script.py::ImageVerification` | fast |
| the release check modifies nothing; a tag on another commit than HEAD fails | `fast/test_release_check.py::ReleaseCheckTest` | fast |
| the gate passed only with the variables of the developer's terminal | `fast/test_dev_check.py::CheckScriptTest` | fast |
| the test image drifts from the product image (tmux, ttyd pins) | `fast/test_layout.py::Layout::test_the_test_image_pins_what_the_product_image_pins`, `fast/test_dockerfile.py::Pins` | fast |
| old names of the addon concept; default names written as literals | `fast/test_guard_names.py::TheRepository`, `fast/test_guard_names.py::TheOldNamesScanner` | fast |
| a test that leaks a process, or starts a real tmux on a machine that is not a container | `fast/test_runner.py`, `fast/test_layout.py` | fast |
| the mutation harness: a plan replays the same mutants, the helper modules of the tests are followed | `fast/test_mutate.py` | fast |
