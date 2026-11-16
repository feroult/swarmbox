# Baseline of the test suite before the reorganisation

Measured on commit `ff7ddf6` (branch `sysop-v1`), one test file at a time (as the old `tests/run_all.sh` did), with per-test timings. Raw data: `baseline.json` in this folder (per file: layer, tests, skips and seconds in each environment, what it needs, and its tests that took 0.5 s or more).

Three environments:

| Environment | What it is | Files | Tests | Skipped | Sum of file times |
|---|---|---|---|---|---|
| host | this machine (32 cores), `env -i`, tmux, ttyd, chromium and podman hidden from `PATH` so that no real tmux runs outside a container | 102 | 1849 | 308 | 351 s |
| Podman, offline | image with tmux 3.5a, ttyd, chromium; `--network none --read-only`, tmpfs `/tmp` and `/work`; no gate variable | 102 | 1849 | 237 | 550 s |
| Podman, gates on | the same with `SWARMBOX_TEST_REAL_TMUX=1`, for the 13 files that have a gated part (browser and real-tmux files) | 13 | 332 | 0 | 487 s |

Everything passed in every environment (0 failures). One exception that is not a defect: `test_dev_check.py` failed in the first Podman run because the copy of the tree had no `.git` (its hook test needs a repository); it passes in the gated run, which had one. The remaining skips need something that no environment here has: the image build, the network, nested Podman, the real voice installer, actionlint, starship.

The old runner reported "about 7 minutes": 351 s of file time on the host plus start-up, one file after the other.
The same files take 550 s inside the offline container (+200 s) because the image has tmux, chromium and ttyd, so the files that the host skips run: `test_attach_command` (real tmux, 12 tests), `test_banner_glint` (3), the five browser files (`test_clipboard_bridge`, `test_web_style`, `test_tmux_browser_keys`, `test_voice_page_browser`), and nothing else.

## Where the seconds go (host)

The 25 slowest files (311 s of 351 s = 89 % in 25 of 102 files):

| # | File | Tests | Host s | Podman s | Cumulative % | Layer (new) | Slowest tests (s) |
|---|---|---|---|---|---|---|---|
| 1 | `test_sysop_panel.py` | 77 | 46.9 | 47.0 | 13 | fast | 15 test(s) over 1 s; `test_the_idle_panel_costs_almost_no_cpu_and_follows_a_new_goal` 11.2, `test_the_countdown_runs_out_and_the_action_is_sent` 3.2 |
| 2 | `test_sysop_service.py` | 56 | 29.8 | 29.7 | 22 | fast | 8 test(s) over 1 s; `test_the_queue_limit` 4.9, `test_the_deadline_ends_a_goal` 4.0 |
| 3 | `test_tabs.py` | 88 | 27.6 | 27.6 | 30 | fast | 4 test(s) over 1 s; `test_no_tmux_and_no_session_are_4_and_a_timeout_is_5` 5.1, `test_a_long_text_goes_in_small_words_and_is_typed_whole` 3.8 |
| 4 | `test_pull_ui.py` | 12 | 26.1 | 26.3 | 37 | fast | 11 test(s) over 1 s; `test_no_nerd_font_glyph_is_ever_drawn_whatever_the_shell_or_the_environment` 5.2, `test_when_the_download_is_over_and_the_pull_is_still_writing_the_label_says_unpack` 4.4 |
| 5 | `test_voice_front.py` | 46 | 24.9 | 24.9 | 44 | fast | 7 test(s) over 1 s; `test_ttyd_exiting_stops_the_service_and_gives_its_status` 1.8, `test_a_dead_service_is_restarted_and_the_terminal_never_noticed` 1.5 |
| 6 | `test_sysop_mcp.py` | 84 | 22.9 | 22.9 | 51 | fast | 3 test(s) over 1 s; `test_a_send_that_was_refused_typed_nothing_and_a_timeout_may_have` 2.2, `test_every_call_decision_and_result_is_in_the_audit_file_with_the_source` 2.1 |
| 7 | `test_sysop_soak.py` | 39 | 15.2 | 15.1 | 55 | fast | 5 test(s) over 1 s; `test_a_log_that_cannot_be_written_does_not_end_the_service` 4.8, `test_an_error_in_one_turn_of_the_main_loop_is_logged_and_the_loop_goes_on` 2.2 |
| 8 | `test_host_create_flags.py` | 33 | 14.7 | 14.6 | 59 | fast | 1 test(s) over 1 s; `test_loop_over_key_combinations` 8.7, `test_unchanged_by_runtime_only_keys_and_secrets` 0.6 |
| 9 | `test_serve_steps.py` | 30 | 11.3 | 11.3 | 63 | fast | 2 test(s) over 1 s; `test_a_killed_broker_is_started_again_with_the_backoff` 1.3, `test_a_broker_that_does_not_answer_is_one_warning_and_serve_goes_on` 1.3 |
| 10 | `test_bus_cli.py` | 33 | 8.6 | 8.7 | 65 | fast | 1 test(s) over 1 s; `test_100_messages_per_second_for_3_seconds_one_process_each` 3.1, `test_many_clients_in_parallel_all_delivered_once` 1.0 |
| 11 | `test_swarmbox_command.py` | 14 | 8.4 | 8.3 | 67 | fast | 2 test(s) over 1 s; `test_exit_codes_of_forwarded_commands_propagate` 2.9, `test_every_other_word_goes_to_the_box_after_up` 2.3 |
| 12 | `test_sysop_addon.py` | 15 | 8.2 | 7.9 | 70 | fast | 4 test(s) over 1 s; `test_prepare_and_goals_work_together_with_the_real_command` 1.7, `test_two_prepares_at_once_end_with_one_service` 1.3 |
| 13 | `test_sysop_brain.py` | 33 | 8.2 | 8.2 | 72 | fast | 4 test(s) over 1 s; `test_stop_while_the_brain_ignores_term_still_kills_it` 2.7, `test_the_brain_runs_in_its_own_process_group_and_none_is_left` 2.1 |
| 14 | `test_host_up.py` | 37 | 8.2 | 8.1 | 74 | fast | 1 test(s) over 1 s; `test_versions_are_compared_as_numbers` 1.1, `test_two_up_calls_started_together_make_exactly_one_box` 0.8 |
| 15 | `test_voice_service.py` | 36 | 7.5 | 7.4 | 77 | fast | 1 test(s) over 1 s; `test_loudest_gives_the_same_answer_as_the_prefix_sum_and_keeps_no_list_of_samples` 1.1, `test_no_listener_over_http_is_a_503_with_a_state` 0.7 |
| 16 | `test_tabs_redact_dos.py` | 8 | 6.7 | 6.6 | 78 | fast | 1 test(s) over 1 s; `test_adversarial_inputs_are_fast` 5.9, `test_cost_does_not_grow_faster_than_the_size` 0.6 |
| 17 | `test_sysop_review.py` | 31 | 5.6 | 5.6 | 80 | fast | 2 test(s) over 1 s; `test_the_forger_of_decisions_needs_an_approval_itself` 2.0, `test_run_on_a_prompt_with_text_left_on_it` 2.0 |
| 18 | `test_bus_serve.py` | 4 | 5.3 | 5.3 | 82 | fast | 1 test(s) over 1 s; `test_a_killed_broker_is_restarted_after_the_backoff_and_takes_over_the_stale_socket` 3.6, `test_the_step_starts_the_broker_and_the_bus_works_end_to_end` 0.5 |
| 19 | `test_sysop_watch.py` | 6 | 4.3 | 4.3 | 83 | fast | 3 test(s) over 1 s; `test_a_second_watch_start_changes_nothing_when_the_service_runs` 1.7, `test_kill_9_of_the_service_brings_it_back_and_a_term_does_not` 1.2 |
| 20 | `test_voice_soak.py` | 5 | 4.0 | 4.0 | 84 | fast | 1 test(s) over 1 s; `test_two_sigterms_in_a_row_leave_no_traceback` 2.6, `test_at_most_max_parallel_recognizers_run_at_once_and_every_recording_is_served` 0.8 |
| 21 | `test_attach_command.py` | 24 | 4.0 | 20.4 | 85 | slow | 2 test(s) over 1 s; `test_window_arguments_and_the_quoted_command_string` 2.2, `test_not_ready_exits_6_after_the_timeout_and_never_calls_tmux` 1.0 |
| 22 | `test_host_connector.py` | 10 | 3.4 | 3.5 | 86 | fast | 0 test(s) over 1 s; `test_connector_failure_warns_and_the_up_exit_code_is_unchanged` 1.0, `test_different_token_recreates` 0.5 |
| 23 | `test_security_review.py` | 14 | 3.3 | 3.2 | 87 | fast | 0 test(s) over 1 s; `test_workspace_names_with_hostile_characters_stay_one_literal_argument` 1.0, `test_the_token_from_the_file_or_the_environment_is_never_in_argv_output_or_the_box_flags` 0.5 |
| 24 | `test_host_config.py` | 22 | 3.1 | 3.1 | 88 | fast | 0 test(s) over 1 s; `test_set_every_key_roundtrip_and_file_mode` 0.5, `test_panel_mode_reaches_the_box_as_panel_mode_never_as_the_marker` 0.4 |
| 25 | `test_serve_logs.py` | 3 | 2.9 | 2.9 | 89 | fast | 2 test(s) over 1 s; `test_a_log_past_the_limit_is_cut_to_its_last_quarter_and_a_small_one_is_left_alone` 1.3, `test_the_serve_log_itself_is_trimmed_too` 1.3 |

The host column of the slow files is small because the real tests skip there; their cost is in the Podman column and in the gated runs:

| File | Tests | Skipped on host | Podman offline s | Podman gates on s | Gated run: tests run |
|---|---|---|---|---|---|
| `test_sysop_always.py` | 60 | 43 | 2.3 | 106.5 | 60 |
| `test_tmux_browser_keys.py` | 22 | 22 | 72.1 | 72.1 | 22 |
| `test_sysop_dock.py` | 81 | 66 | 0.4 | 71.0 | 81 |
| `test_web_strip.py` | 35 | 18 | 0.5 | 62.1 | 35 |
| `test_clipboard_bridge.py` | 11 | 11 | 39.8 | 39.5 | 11 |
| `test_voice_page_browser.py` | 14 | 14 | 31.7 | 31.7 | 14 |
| `test_tabs_real.py` | 28 | 28 | 0.1 | 25.2 | 28 |
| `test_sysop_real.py` | 15 | 15 | 0.1 | 24.1 | 15 |
| `test_web_style.py` | 7 | 7 | 20.1 | 19.9 | 7 |
| `test_sysop_web.py` | 4 | 4 | 0.1 | 15.3 | 4 |
| `test_sysop_soak.py` | 39 | 0 | 15.1 | 15.0 | 39 |
| `test_voice_soak.py` | 5 | 0 | 4.0 | 4.0 | 5 |
| `test_dev_check.py` | 11 | 0 | 0.1 | 0.1 | 11 |

Shape of the distribution (host seconds per file):

| Bucket | Files | Tests | Seconds | Share |
|---|---|---|---|---|
| under 1 s | 65 | 785 | 17 | 5 % |
| 1 to 5 s | 19 | 388 | 48 | 14 % |
| 5 to 15 s | 11 | 274 | 93 | 26 % |
| 15 s or more | 7 | 402 | 193 | 55 % |

By area (the prefix of the file name):

| Area | Files | Tests | Host s | Share |
|---|---|---|---|---|
| sysop | 15 | 569 | 146 | 42 % |
| voice | 7 | 155 | 39 | 11 % |
| tabs | 4 | 128 | 35 | 10 % |
| host | 9 | 148 | 35 | 10 % |
| other | 27 | 242 | 34 | 10 % |
| bus | 3 | 93 | 16 | 5 % |
| serve | 2 | 33 | 14 | 4 % |
| addon | 16 | 209 | 11 | 3 % |
| swarmbox | 1 | 14 | 8 | 2 % |
| attach | 1 | 24 | 4 | 1 % |
| release | 4 | 54 | 3 | 1 % |
| web | 3 | 60 | 2 | 1 % |
| install | 1 | 43 | 2 | 1 % |
| dev | 2 | 24 | 0 | 0 % |
| bashrc | 2 | 32 | 0 | 0 % |
| banner | 2 | 7 | 0 | 0 % |
| image | 2 | 7 | 0 | 0 % |
| docs | 1 | 7 | 0 | 0 % |

The 25 slowest tests (Podman, gates on where the file has them):

| s | File | Test |
|---|---|---|
| 12.2 | `test_sysop_always.py` | `test_idle_panels_use_almost_no_cpu` |
| 11.7 | `test_sysop_always.py` | `test_the_follower_in_always_mode_brings_the_panels_by_itself_and_costs_no_cpu` |
| 11.2 | `test_sysop_panel.py` | `test_the_idle_panel_costs_almost_no_cpu_and_follows_a_new_goal` |
| 9.7 | `test_banner_glint.py` | `test_a_pass_writes_only_the_cells_that_change_and_leaves_the_letters_as_they_were` |
| 8.6 | `test_host_create_flags.py` | `test_loop_over_key_combinations` |
| 6.7 | `test_tabs_real.py` | `test_active_is_the_window_of_the_last_active_client_two_pty_clients` |
| 5.8 | `test_tabs_redact_dos.py` | `test_adversarial_inputs_are_fast` |
| 5.7 | `test_sysop_always.py` | `test_a_panel_that_crashes_at_its_start_is_not_made_in_a_loop` |
| 5.3 | `test_tmux_browser_keys.py` | `test_the_plus_button_creates_a_window_only_in_the_first_three_columns` |
| 5.2 | `test_tmux_browser_keys.py` | `test_splits_focus_resize_zoom_and_close` |
| 5.2 | `test_tmux_browser_keys.py` | `test_the_plus_button_creates_a_window_only_in_the_first_three_columns` |
| 5.2 | `test_tmux_browser_keys.py` | `test_splits_focus_resize_zoom_and_close` |
| 5.2 | `test_clipboard_bridge.py` | `test_a_mouse_selection_in_tmux_reaches_the_browser_clipboard` |
| 5.2 | `test_pull_ui.py` | `test_no_nerd_font_glyph_is_ever_drawn_whatever_the_shell_or_the_environment` |
| 5.1 | `test_banner_glint.py` | `test_with_the_switch_off_nothing_is_ever_drawn` |
| 5.1 | `test_tabs.py` | `test_no_tmux_and_no_session_are_4_and_a_timeout_is_5` |
| 4.9 | `test_attach_command.py` | `test_a_tab_that_leaves_and_comes_back_returns_to_its_place_in_the_browser` |
| 4.8 | `test_sysop_service.py` | `test_the_queue_limit` |
| 4.8 | `test_sysop_soak.py` | `test_a_log_that_cannot_be_written_does_not_end_the_service` |
| 4.8 | `test_web_strip.py` | `test_holding_an_arrow_repeats_and_a_tap_types_once` |
| 4.7 | `test_sysop_always.py` | `test_keys_typed_in_the_tab_while_a_goal_arrives_never_reach_a_countdown_panel` |
| 4.7 | `test_sysop_always.py` | `test_keys_typed_in_the_tab_while_a_goal_arrives_never_reach_an_approval_panel` |
| 4.7 | `test_web_strip.py` | `test_the_keyboard_of_a_phone_moves_the_strip_above_it` |
| 4.7 | `test_sysop_web.py` | `test_keys_typed_in_the_browser_while_a_goal_arrives_never_reach_the_panel` |
| 4.6 | `test_sysop_dock.py` | `test_every_sysop_key_without_the_addon_leaves_the_pane_typing` |

1786 tests ran in the best environment; 237 took more than 1 s (638 s together), 16 took more than 5 s (113 s), the other 1549 took 204 s together.

## Classification of every file

`fast`: needs no real tmux, browser, Podman or network. `slow`: at least half of its tests need one of them (they skip, with the gate `SWARMBOX_TEST_REAL_TMUX=1` for the real tmux, when it is missing). `e2e`: a harness, not a test file. A fast file marked *mixed* has a small gated tail (it stays fast; the tail still skips, and the slow runs of CI or `dev/test-slow.sh` do not reach it: the area agents split it or move the tail). *pty/processes* means the file starts our own long-lived processes or a pty: cheap in principle, expensive in seconds.

| File | Layer | Tests | Host s | Needs | Note |
|---|---|---|---|---|---|
| `test_addon_agent_shell.py` | fast | 18 | 0.2 | - |  |
| `test_addon_doctor.py` | fast | 8 | 2.5 | - |  |
| `test_addon_gemini_clasp_poetry.py` | fast | 13 | 0.5 | - |  |
| `test_addon_go_gcloud.py` | fast | 10 | 0.3 | - |  |
| `test_addon_image_level.py` | fast | 5 | 0.3 | - |  |
| `test_addon_install.py` | fast | 12 | 2.2 | - |  |
| `test_addon_link.py` | fast | 12 | 0.4 | - |  |
| `test_addon_manifest.py` | fast | 23 | 0.6 | shellcheck | mixed: 1 tests skip without the extra program |
| `test_addon_new.py` | fast | 5 | 0.2 | - |  |
| `test_addon_opencode.py` | fast | 9 | 0.3 | chromium |  |
| `test_addon_prepare.py` | fast | 7 | 1.3 | - |  |
| `test_addon_real.py` | slow | 50 | 0.1 | IMAGE_BUILD, REAL_ADDONS, TEST_NETWORK, podman |  |
| `test_addon_shim.py` | fast | 9 | 0.6 | shellcheck | mixed: 1 tests skip without the extra program |
| `test_addon_stub.py` | fast | 4 | 0.1 | shellcheck |  |
| `test_addon_use_remove.py` | fast | 12 | 0.6 | - |  |
| `test_addon_voice.py` | fast | 12 | 0.4 | REAL_VOICE_INSTALL | mixed: 1 tests skip without the extra program |
| `test_attach_command.py` | slow | 24 | 4.0 | pty, tmux |  |
| `test_banner.py` | fast | 4 | 0.1 | - |  |
| `test_banner_glint.py` | slow | 3 | 0.0 | tmux |  |
| `test_bashrc_container.py` | slow | 6 | 0.1 | IMAGE_BUILD |  |
| `test_bashrc_fragment.py` | fast | 26 | 0.2 | shellcheck | mixed: 1 tests skip without the extra program |
| `test_build_index.py` | fast | 6 | 0.1 | - |  |
| `test_bus.py` | fast | 56 | 2.4 | - |  |
| `test_bus_cli.py` | fast | 33 | 8.6 | - |  |
| `test_bus_serve.py` | fast | 4 | 5.3 | - |  |
| `test_ci_workflow.py` | fast | 14 | 0.1 | actionlint, REAL_VOICE_INSTALL, SMOKE_FULL, TEST_REAL_TMUX, shellcheck | mixed: 1 tests skip without the extra program |
| `test_clipboard_bridge.py` | slow | 11 | 0.1 | chromium, ttyd |  |
| `test_cloudflare_setup.py` | fast | 12 | 0.8 | - |  |
| `test_default_names_lint.py` | fast | 5 | 0.1 | - |  |
| `test_dev_build.py` | fast | 13 | 0.2 | - |  |
| `test_dev_check.py` | fast | 11 | 0.1 | - |  |
| `test_dirs.py` | fast | 4 | 0.1 | shellcheck |  |
| `test_dockerfile.py` | fast | 16 | 0.1 | - |  |
| `test_docs_consistency.py` | fast | 7 | 0.1 | - |  |
| `test_entrypoint.py` | fast | 11 | 0.5 | shellcheck |  |
| `test_helpers.py` | fast | 3 | 0.0 | podman |  |
| `test_host_config.py` | fast | 22 | 3.1 | find, pty, stat | pty/processes |
| `test_host_connector.py` | fast | 10 | 3.4 | - |  |
| `test_host_create_flags.py` | fast | 33 | 14.7 | bash, busybox, dash, zsh | heavy (15 s) |
| `test_host_remote.py` | fast | 8 | 0.6 | pty, stat | pty/processes |
| `test_host_remote_e2e_fake.py` | fast | 4 | 0.6 | - |  |
| `test_host_shells.py` | fast | 4 | 0.9 | bash, busybox, dash, shellcheck, zsh | mixed: 2 tests skip without the extra program |
| `test_host_socket.py` | fast | 8 | 0.8 | podman | mixed: 1 tests skip without the extra program |
| `test_host_up.py` | fast | 37 | 8.2 | podman |  |
| `test_host_update.py` | fast | 22 | 2.6 | pty | pty/processes |
| `test_image_build.py` | slow | 4 | 0.0 | chromium, IMAGE_BUILD, podman |  |
| `test_image_with_addons.py` | slow | 3 | 0.0 | IMAGE_BUILD, TEST_NETWORK, podman |  |
| `test_install.py` | fast | 43 | 2.1 | - |  |
| `test_local_up.py` | fast | 10 | 0.2 | - |  |
| `test_mcp_registry.py` | fast | 9 | 0.2 | chromium |  |
| `test_name_check.py` | fast | 7 | 0.1 | - |  |
| `test_nested_fuse_real.py` | slow | 1 | 0.0 | IMAGE_BUILD, TEST_NESTED, TEST_NETWORK, podman |  |
| `test_no_old_names.py` | fast | 13 | 0.7 | - |  |
| `test_pubkey_ensure.py` | fast | 5 | 0.1 | ssh-keygen |  |
| `test_pull_ui.py` | fast | 12 | 26.1 | pty | pty/processes; heavy (26 s) |
| `test_record_checksums.py` | fast | 6 | 0.1 | - |  |
| `test_release_check.py` | fast | 11 | 0.9 | - |  |
| `test_release_script.py` | fast | 23 | 1.6 | - |  |
| `test_release_version.py` | fast | 11 | 0.1 | - |  |
| `test_release_workflow.py` | fast | 9 | 0.0 | actionlint, shellcheck | mixed: 1 tests skip without the extra program |
| `test_repo_files.py` | fast | 8 | 0.1 | chromium |  |
| `test_run_all.py` | fast | 7 | 0.6 | - |  |
| `test_security_review.py` | fast | 14 | 3.3 | - |  |
| `test_serve_logs.py` | fast | 3 | 2.9 | - |  |
| `test_serve_steps.py` | fast | 30 | 11.3 | - | heavy (11 s) |
| `test_smoke_image_data.py` | fast | 3 | 0.0 | - |  |
| `test_ssh_key.py` | fast | 4 | 0.1 | - |  |
| `test_starship.py` | fast | 10 | 0.2 | git, starship | mixed: 2 tests skip without the extra program |
| `test_statusline.py` | fast | 10 | 0.4 | git, jq |  |
| `test_swarmbox_command.py` | fast | 14 | 8.4 | bash, dash |  |
| `test_sysop_addon.py` | fast | 15 | 8.2 | shellcheck |  |
| `test_sysop_always.py` | slow | 60 | 2.3 | TEST_REAL_TMUX |  |
| `test_sysop_brain.py` | fast | 33 | 8.2 | - |  |
| `test_sysop_bus.py` | fast | 12 | 1.2 | - |  |
| `test_sysop_dock.py` | slow | 81 | 0.4 | TEST_REAL_TMUX, pty, swarmbox-sysop, tmux |  |
| `test_sysop_keys.py` | fast | 13 | 0.5 | - |  |
| `test_sysop_mcp.py` | fast | 84 | 22.9 | - | heavy (23 s) |
| `test_sysop_panel.py` | fast | 77 | 46.9 | pty | pty/processes; heavy (47 s) |
| `test_sysop_policy.py` | fast | 43 | 0.4 | - |  |
| `test_sysop_real.py` | slow | 15 | 0.1 | TEST_REAL_TMUX, tmux |  |
| `test_sysop_review.py` | fast | 31 | 5.6 | - |  |
| `test_sysop_service.py` | fast | 56 | 29.8 | - | heavy (30 s) |
| `test_sysop_soak.py` | fast | 39 | 15.2 | - | heavy (15 s) |
| `test_sysop_watch.py` | fast | 6 | 4.3 | - |  |
| `test_sysop_web.py` | slow | 4 | 0.1 | chromium, TEST_REAL_TMUX, ttyd |  |
| `test_tabs.py` | fast | 88 | 27.6 | - | heavy (28 s) |
| `test_tabs_locks.py` | fast | 4 | 0.8 | - |  |
| `test_tabs_real.py` | slow | 28 | 0.1 | TEST_REAL_TMUX, fzf, less, pty, tmux |  |
| `test_tabs_redact_dos.py` | fast | 8 | 6.7 | - |  |
| `test_theme.py` | fast | 13 | 0.1 | - |  |
| `test_third_party_notices.py` | fast | 6 | 0.1 | - |  |
| `test_tmux_browser_keys.py` | slow | 22 | 0.1 | pty, tmux |  |
| `test_voice_config.py` | fast | 18 | 1.4 | - |  |
| `test_voice_front.py` | fast | 46 | 24.9 | - | heavy (25 s) |
| `test_voice_page.py` | fast | 11 | 0.1 | node |  |
| `test_voice_page_browser.py` | slow | 14 | 0.1 | chromium |  |
| `test_voice_service.py` | fast | 36 | 7.5 | - |  |
| `test_voice_soak.py` | fast | 5 | 4.0 | - |  |
| `test_voice_web.py` | fast | 25 | 1.5 | - |  |
| `test_web_build.py` | fast | 18 | 1.6 | chromium, shellcheck, ttyd |  |
| `test_web_strip.py` | slow | 35 | 0.5 | chromium, TEST_REAL_TMUX, node, ttyd |  |
| `test_web_style.py` | slow | 7 | 0.1 | chromium, ttyd |  |
| `smoke_image.py` | slow | script | - | podman, the image (`SWARMBOX_IMAGE_BUILD=1`, full: nested Podman) | not collected by the runner; CI runs it by path |
| `e2e_sysop.py` (+ `.sh`) | e2e | script | - | podman, the real `claude` login, minutes | never in a default run |
| `e2e_voice.py` (+ `.sh`) | e2e | script | - | podman, the real `claude` login, minutes | never in a default run |
| `soak_v1.py` (+ `.sh`) | e2e | script | - | podman, the real `claude` login, minutes | never in a default run |

Totals: 85 fast files (1481 tests, 343 s on the host), 17 slow files (368 tests, 503 s in Podman with the gates on where they have them), 3 e2e harnesses, 1 smoke script.

## Notes for the people who trim the files

- Many test files import each other (`test_serve_steps` is used by `test_bus_serve`, `test_serve_logs`, `test_web_build`; `test_host_up` by four files; `test_addon_install`, `test_addon_manifest` by seven; `test_sysop_mcp`/`test_sysop_service`/`test_sysop_panel` by the review and soak files). Deleting or splitting a file can break its importers: move the shared part to `tests/support` first.
- A fast file may not import a slow one (`tests/fast/test_layout.py`); `test_web_build` used to import `test_clipboard_bridge` (a slow file) only for two path constants.
- The 17 slow files have fast parts that were not split off (`test_sysop_dock` 15 of 81, `test_web_strip` 17 of 35, `test_sysop_always` 17 of 60, `test_attach_command` 12 of 24 run without real tmux). They are in `slow/` for now; moving their fake-tmux halves into `fast/` is a split of the file.
