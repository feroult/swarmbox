#!/usr/bin/env python3
"""Slice 6.2: the inventory of the v0.1.0-only tests (design 13.1, 12.2) and the guard that keeps them from coming back.

Six test files of v0.1.0 exercised start.sh, lib/ or container/web/web-terminal.sh. Slice 6.2 deleted them (test_start_attach,
test_start_fake_podman, test_start_init, test_start_timezone, test_start_web_connector, test_web_terminal) and ported what they
pinned. This file holds, for every deleted test, the 2.0 test that now pins the same behavior, or the reason it was dropped on
purpose (decision log [6.2]). It fails when:
  - a named 2.0 test does not exist (a rename or a deletion would silently lose coverage);
  - a deleted file comes back;
  - a tests/ file other than the allow-list mentions start.sh, build.sh, lib/{attach-session,podman-connection,ui,web}.sh,
    container/scripts/init.sh, container/web/web-terminal.sh or container/opencode (slice 6.3 deleted the
    scripts; tests/test_retired.py asserts they are gone).
Run: python3 tests/test_retired_coverage.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TESTS = os.path.join(ROOT, "tests")
SELF = os.path.basename(__file__)

DELETED = ("test_start_attach.py", "test_start_fake_podman.py", "test_start_init.py", "test_start_timezone.py",
           "test_start_web_connector.py", "test_web_terminal.py")

A = "test_attach_command.py"
U = "test_host_up.py"
C = "test_host_connector.py"
F = "test_host_create_flags.py"
W = "test_web_build.py"
P = "test_parity.py"
H = "test_host_config.py"

# old file -> old test -> (new file, new test) or "dropped: <why>" (every dropped one is in the decision log [6.2])
MAP = {
    "test_start_attach.py": {
        "test_by_default_it_attaches_to_the_main_tmux_session": (A, "test_attach_creates_main_when_the_server_has_no_session"),
        "test_attach_shell_keeps_the_plain_bash": (A, "test_plain_with_a_terminal_runs_through_bash_ic_without_tmux"),
        "test_with_the_web_session_running_it_adds_a_window_in_a_grouped_session": (A, "test_two_attach_calls_share_one_session_as_two_windows_and_the_idle_one_is_gone"),
        "test_the_grouped_session_goes_away_when_the_host_tab_closes_but_the_window_stays": (A, "test_hup_to_the_caller_ends_the_client_and_leaves_the_window"),
        "test_without_a_session_it_creates_main_with_a_single_window": (A, "test_a_missing_session_is_created_with_the_idle_window_first"),
        "test_the_host_tab_has_no_status_bar_but_the_web_session_keeps_it": (A, "test_the_grouped_session_without_status_bar_and_a_new_window"),
    },
    "test_start_fake_podman.py": {
        "test_creates_a_container_when_none_exists": (U, "test_a_missing_box_is_created_with_the_captured_flags"),
        "test_builds_the_image_when_it_is_missing": (U, "test_a_missing_image_is_pulled_then_used"),   # 2.0 pulls, it never builds on the host (D2)
        "test_an_existing_container_is_started_not_recreated": (U, "test_a_stopped_box_is_started_and_waited_for"),
    },
    "test_start_init.py": {
        "test_by_default_init_is_used_when_podman_can_run_it": (U, "test_init_auto_is_resolved_by_a_throwaway_probe_that_supports_it"),
        "test_when_podman_cannot_run_init_the_container_is_still_created_without_it": (U, "test_init_auto_without_init_support_runs_without_it_and_says_so"),
        "test_init_can_be_forced_without_probing": (U, "test_init_0_and_1_need_no_probe"),
        "test_init_can_be_turned_off_without_probing": (F, "test_init_1_emits_init_0_does_not"),
        "test_reset_also_creates_the_container_with_init": (U, "test_reset_also_creates_the_box_with_init_and_the_time_zone"),
        "test_reattaching_to_an_existing_container_does_not_probe_or_create": (U, "test_a_running_box_takes_one_inspect_and_no_run"),
    },
    "test_start_timezone.py": {
        "test_by_default_the_container_follows_the_machines_time_zone": (F, "test_tz_local_zone_and_off"),
        "test_without_a_localtime_file_no_flag_is_passed": (F, "test_tz_local_without_a_local_time_file_gives_no_flag_and_a_warning"),
        "test_a_zone_can_be_chosen": (F, "test_tz_local_zone_and_off"),
        "test_it_can_be_turned_off": (F, "test_tz_old_off_spellings_of_v0_1_0_still_mean_off"),
        "test_an_invalid_zone_is_ignored_and_cannot_inject_arguments": (F, "test_tz_invalid_is_exit_2"),   # 2.0 refuses (exit 2, nothing printed) instead of ignoring:
        "test_reset_also_passes_the_time_zone": (U, "test_reset_also_creates_the_box_with_init_and_the_time_zone"),
        "test_reattaching_creates_nothing": (U, "test_a_running_box_takes_one_inspect_and_no_run"),
    },
    "test_start_web_connector.py": {
        "test_missing_connector_is_created_from_the_token": (C, "test_token_and_web_on_creates_the_connector_with_expected_flags_and_the_token_only_in_env"),
        "test_the_token_never_appears_on_a_command_line_or_in_the_output": (C, "test_token_and_web_on_creates_the_connector_with_expected_flags_and_the_token_only_in_env"),
        "test_a_stopped_connector_with_the_same_token_is_started_not_recreated": (C, "test_stopped_with_same_token_is_started_not_recreated"),
        "test_a_running_connector_with_the_same_token_is_left_alone": (C, "test_running_with_same_token_is_a_noop_beyond_inspect"),
        "test_a_connector_holding_another_token_is_recreated_even_if_running": (C, "test_different_token_recreates"),
        "test_a_failed_create_is_reported_briefly": (C, "test_connector_failure_warns_and_the_up_exit_code_is_unchanged"),
        "test_the_connector_image_can_be_chosen": (C, "test_image_override_by_env_and_not_by_config"),
        "test_without_a_token_a_stopped_connector_is_started": "dropped: 2.0 makes no Podman call at all without a tunnel token (design 5.2 '5.4 state', 3.7.2 step 7); test_no_token_means_no_connector_calls pins the new rule",
        "test_without_a_token_a_running_connector_is_left_alone": (C, "test_no_token_means_no_connector_calls"),
        "test_a_connector_that_will_not_start_is_reported": (C, "test_connector_failure_warns_and_the_up_exit_code_is_unchanged"),
        "test_without_token_or_connector_nothing_is_created_and_it_stays_quiet": (C, "test_no_token_means_no_connector_calls"),
        "test_people_using_remote_access_are_told_how_to_get_a_connector": "dropped: the hint pointed at cloudflare-setup.py; `swarmbox remote setup` now creates the token flow itself and the script prints the token advice (test_cloudflare_setup)",
        "test_existing_web_container_accepts_web_and_brings_up_the_tunnel": (C, "test_a_running_box_still_brings_the_connector_up_on_every_entry"),
        "test_existing_web_container_brings_up_the_tunnel_even_without_the_flag": (C, "test_a_running_box_still_brings_the_connector_up_on_every_entry"),
        "test_existing_web_container_starts_a_stopped_connector_without_a_token": "dropped: same rule as the first dropped case (no token, no connector call)",
        "test_the_port_the_container_really_publishes_wins_over_the_flag": "dropped: 2.0 has no --web PORT flag; the port is the WEB_PORT key and a change shows as the ports-changed warning (test_ports_changed_line in test_host_up.py)",
        "test_an_existing_container_without_the_web_terminal_still_refuses_web": "dropped: 2.0 never blocks on a changed setting, it warns (design 3.7.2; test_warnings_never_change_the_exit_code in test_host_up.py)",
        "test_an_existing_container_without_the_web_terminal_never_touches_the_connector": (C, "test_web_off_skips_the_connector"),
        "test_without_web_the_connector_is_not_even_looked_at": (C, "test_web_off_skips_the_connector"),
        "test_the_token_is_not_passed_to_the_swarmbox_container": (C, "test_the_tunnel_token_never_reaches_the_box_container"),
        "test_listing_the_token_in_env_keys_is_refused": (H, "test_cloudflare_prefix_is_refused_with_exit_2"),
        "test_no_api_token_is_needed_or_used": (C, "test_no_cloudflare_api_token_is_needed_or_used"),
    },
    "test_web_terminal.py": {
        "test_not_started_without_the_web_flag": (P, "test_row09_serve_starts_ttyd_by_default_and_not_with_web_off"),
        "test_defaults": (W, "test_defaults_of_the_ttyd_command_line"),
        "test_config_file_overrides_and_adds": (W, "test_the_config_file_overrides_and_adds_options"),
        "test_values_are_handed_over_as_valid_json": (W, "test_values_are_handed_over_as_valid_json"),
        "test_a_utf8_locale_is_provided_when_there_is_none": (W, "test_a_missing_locale_is_provided"),
        "test_an_existing_utf8_locale_is_kept": (W, "test_an_existing_utf8_locale_is_kept"),
        "test_a_non_utf8_locale_is_replaced": (W, "test_a_non_utf8_locale_is_replaced"),
        "test_lc_all_decides_over_lang": (W, "test_lc_all_decides_over_lang"),
        "test_ttyd_serves_its_page_with_the_bridge_injected_before_the_body_ends": ("test_build_index.py", "test_page_has_the_three_placeholders_and_both_assets"),
        "test_without_the_page_or_the_bridge_ttyd_serves_its_own_page": (W, "test_a_failed_render_does_not_start_ttyd"),   # 2.0 refuses to start without the built page instead of serving ttyd's own
        "test_an_unexpected_page_falls_back_to_the_original": ("test_build_index.py", "test_a_stock_page_without_a_body_fails_and_leaves_no_output"),   # the image build fails instead of falling back
        "test_clipboard_options_are_consumed_not_passed_to_ttyd": (W, "test_the_clipboard_switches_reach_the_page_and_not_ttyd"),
        "test_the_page_is_rebuilt_only_when_something_changed": (W, "test_a_changed_conf_changes_the_page_at_the_next_render"),   # 2.0 renders at every start, no cache (D13)
        "test_a_script_tag_inside_the_bridge_cannot_end_the_injected_script": ("test_build_index.py", "test_closing_tags_inside_assets_are_escaped"),
        "test_value_may_contain_equals_signs": (W, "test_a_value_may_contain_equals_signs"),
    },
}

# files that may still mention the retired scripts, and why
ALLOW = {
    "test_parity.py": "compares 2.0 with fixtures recorded from `git archive v0.1.0` (names the old files as history)",
    "record_v010_flags.py": "the recorder of those fixtures: runs the OLD start.sh out of `git archive v0.1.0`, never the files on disk",
    "test_migration.py": "fixtures built from v0.1.0 content (`git show v0.1.0:...`) for the layout migration",
    "test_tool_opencode.py": "compares the 2.0 mirror and template with `git show v0.1.0:container/scripts/init.sh` and `...container/opencode/local-llm.json`",
    "test_dockerfile.py": "asserts the 2.0 Dockerfile does NOT use init.sh (an absence check)",
    "test_docs_consistency.py": "the docs rule that start.sh may be named only in a historic or migration context",
    "test_retired.py": "the absence test of slice 6.3 (names the deleted files to assert they are gone)",
    SELF: "this file (names the retired files to guard against them)",
}
FORBIDDEN = re.compile(
    r"(?<![\w./-])start\.sh|(?<![\w./-])build\.sh|lib/(?:attach-session|podman-connection|ui|web)\.sh|"
    r"(?<![\w-])init\.sh|web-terminal\.sh|container/opencode")


def defines(path, name):
    with open(os.path.join(TESTS, path), encoding="utf-8") as f:
        return re.search(r"^\s*def %s\(" % re.escape(name), f.read(), re.M) is not None


class RetiredCoverage(unittest.TestCase):
    def test_the_deleted_files_are_gone(self):
        for f in DELETED:
            self.assertFalse(os.path.exists(os.path.join(TESTS, f)), f)

    def test_every_deleted_file_has_a_map_and_nothing_else_does(self):
        self.assertEqual(sorted(MAP), sorted(DELETED))

    def test_every_replacement_test_exists(self):
        missing = []
        for old, tests in MAP.items():
            for name, target in tests.items():
                if isinstance(target, tuple):
                    if not defines(*target):
                        missing.append("%s::%s -> %s::%s" % (old, name, *target))
                else:
                    self.assertTrue(target.startswith("dropped: ") and len(target) > 40, "%s::%s needs a reason" % (old, name))
        self.assertEqual(missing, [])

    def test_the_old_test_counts_are_all_accounted_for(self):
        # the number of tests each deleted file had at HEAD of slice 6.1 (git show ec75a1d:tests/<file> | grep -c 'def test_')
        counts = {"test_start_attach.py": 6, "test_start_fake_podman.py": 3, "test_start_init.py": 6, "test_start_timezone.py": 7,
                  "test_start_web_connector.py": 22, "test_web_terminal.py": 15}
        for f, n in counts.items():
            self.assertEqual(len(MAP[f]), n, f)

    def test_dropped_ones_are_few_and_listed(self):
        dropped = sorted("%s::%s" % (o, n) for o, t in MAP.items() for n, v in t.items() if isinstance(v, str))
        self.assertEqual(len(dropped), 5, dropped)


class NoOldScriptsInTests(unittest.TestCase):
    def test_only_the_allow_list_names_the_retired_scripts(self):
        bad = []
        for name in sorted(os.listdir(TESTS)):
            path = os.path.join(TESTS, name)
            if not os.path.isfile(path) or not name.endswith((".py", ".sh", ".md")) or name in ALLOW:
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if FORBIDDEN.search(line):
                        bad.append("%s:%d: %s" % (name, n, line.strip()[:100]))
        self.assertEqual(bad, [])

    def test_the_allow_list_entries_exist_and_have_a_reason(self):
        for name, why in ALLOW.items():
            self.assertTrue(os.path.isfile(os.path.join(TESTS, name)), name)
            self.assertGreater(len(why), 10)

    def test_the_allowed_files_name_the_old_code_only_as_history(self):
        # test_parity and the recorder reach the old code through the tag, never through the working tree
        for name in ("test_parity.py", "record_v010_flags.py"):
            with open(os.path.join(TESTS, name), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("v0.1.0", text, name)
            self.assertNotRegex(text, r'os\.path\.join\(ROOT, "start\.sh"\)', name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
