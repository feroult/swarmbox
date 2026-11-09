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
