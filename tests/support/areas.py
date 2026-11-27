"""Declarative mapping from repository paths to fast test areas for tests/run.sh.

Used by `sh tests/run.sh loop` and `sh tests/run.sh --area <name>`. Standard library only (Python 3.6+).
"""
import os
import re
import subprocess

GUARDS = (
    "test_layout.py",
    "test_dockerfile.py",
    "test_guard_agents.py",
    "test_guard_mux.py",
)

AREAS = {
    "guards": GUARDS,
    "herdr": (
        "test_herdr_backend.py",
        "test_herdr_file_preview.py",
        "test_web_server.py",
        "test_web_bundle.py",
        "test_addons_web.py",
        "test_context_web.py",
        "test_pins.py",
        "test_pins_web.py",
        "test_cockpit_tabs.py",
        "test_cockpit_wheel.py",
        "test_attach_command.py",
        "test_mux_isolation.py",
        "test_open_url.py",
        "test_theme.py",
        "test_tui_signals.py",
    ),
    "sysop": (
        "test_sysop_addon.py",
        "test_sysop_automations.py",
        "test_sysop_autoname_worktree.py",
        "test_sysop_brain.py",
        "test_sysop_bus.py",
        "test_sysop_digest.py",
        "test_sysop_events.py",
        "test_sysop_hermetic.py",
        "test_sysop_history.py",
        "test_sysop_live_web.py",
        "test_sysop_mcp.py",
        "test_sysop_policy.py",
        "test_sysop_service.py",
        "test_sysop_soak.py",
        "test_sysop_usermsgs.py",
        "test_sysop_watch.py",
    ),
    "voice": (
        "test_addon_voice.py",
        "test_voice_config.py",
        "test_voice_front.py",
        "test_voice_service.py",
        "test_voice_soak.py",
        "test_voice_web.py",
    ),
    "host": (
        "test_host_config.py",
        "test_host_connector.py",
        "test_host_create_flags.py",
        "test_host_remote.py",
        "test_host_remote_e2e_fake.py",
        "test_host_shells.py",
        "test_host_socket.py",
        "test_host_up.py",
        "test_host_update.py",
        "test_install.py",
        "test_cloudflare_setup.py",
        "test_pull_ui.py",
        "test_swarmbox_command.py",
    ),
    "tabs": (
        "test_tabs.py",
        "test_tabs_locks.py",
        "test_tabs_redact_dos.py",
        "test_cockpit_tabs.py",
        "test_state.py",
    ),
    "bus": (
        "test_bus.py",
        "test_bus_cli.py",
        "test_bus_serve.py",
        "test_serve_logs.py",
        "test_serve_steps.py",
        "test_sysop_bus.py",
    ),
    "worktree": (
        "test_worktree.py",
        "test_sysop_autoname_worktree.py",
    ),
    "addons": (
        "test_addon_agent_shell.py",
        "test_addon_antigravity.py",
        "test_addon_clasp_poetry.py",
        "test_addon_claude.py",
        "test_addon_doctor.py",
        "test_addon_go_gcloud.py",
        "test_addon_install.py",
        "test_addon_link.py",
        "test_addon_manifest.py",
        "test_addon_new.py",
        "test_addon_opencode.py",
        "test_addon_prepare.py",
        "test_addon_shim.py",
        "test_addon_use_remove.py",
        "test_addon_voice.py",
        "test_addons_web.py",
        "test_mcp_registry.py",
        "test_agents_registry.py",
    ),
    "release": (
        "test_dev_build.py",
        "test_dev_check.py",
        "test_gen_notices.py",
        "test_local_up.py",
        "test_local_watch.py",
        "test_mutate.py",
        "test_name_check.py",
        "test_record_checksums.py",
        "test_release_check.py",
        "test_release_script.py",
        "test_release_version.py",
        "test_workflows.py",
    ),
    "runner": (
        "test_runner.py",
        "test_layout.py",
    ),
}

# Changes to these paths trigger a safe fallback to the full fast suite in `loop`.
SHARED_INFRA_EXACT = (
    "Dockerfile",
    "container/scripts/swarmbox-agents.py",
    "container/scripts/swarmbox_agents.py",
    "container/entrypoint.sh",
)

SHARED_INFRA_PREFIXES = (
    "tests/support/",
    "container/config/",
)

# Ordered path rules: more specific prefixes and exact files come before broader prefixes.
# Each entry is (pattern, kind, targets) where pattern ending with "/" matches by prefix,
# otherwise by exact match. kind is "areas" or "tests".
PATH_RULES = (
    ("container/addons/sysop/", "areas", ("sysop",)),
    ("container/addons/voice/", "areas", ("voice",)),
    ("container/addons/", "areas", ("addons",)),
    ("container/web/herdr/worktree-ops.mjs", "areas", ("herdr", "worktree")),
    ("container/web/herdr/routes-worktrees.mjs", "areas", ("herdr", "worktree")),
    ("container/web/herdr/sysop-store.mjs", "areas", ("herdr", "sysop")),
    ("container/web/herdr/public/sysoplive.js", "areas", ("herdr", "sysop")),
    ("container/web/herdr/", "areas", ("herdr",)),
    ("container/host/", "areas", ("host",)),
    ("install.sh", "areas", ("host",)),
    ("cloudflare-setup.py", "areas", ("host",)),
    ("container/scripts/swarmbox-tabs.py", "areas", ("tabs",)),
    ("container/scripts/swarmbox-state.py", "areas", ("tabs",)),
    ("container/scripts/swarmbox-bus.py", "areas", ("bus",)),
    ("container/scripts/swarmbox-worktree.py", "areas", ("worktree",)),
    ("container/scripts/swarmbox-addon.sh", "areas", ("addons",)),
    ("container/scripts/swarmbox-shim.sh", "areas", ("addons",)),
    ("container/scripts/swarmbox-install.sh", "areas", ("addons",)),
    ("container/scripts/swarmbox-mcp.sh", "areas", ("addons",)),
    ("container/mcp/", "areas", ("addons",)),
    ("container/scripts/swarmbox-web.sh", "areas", ("herdr",)),
    ("container/scripts/swarmbox-attach.sh", "areas", ("herdr",)),
    ("container/scripts/swarmbox-pins.py", "areas", ("herdr",)),
    ("container/scripts/swarmbox-open.py", "areas", ("herdr",)),
    ("container/scripts/mux/", "areas", ("herdr",)),
    ("container/scripts/dirs.sh", "tests", ("test_dirs.py",)),
    ("container/scripts/ssh-key.sh", "tests", ("test_ssh_key.py",)),
    ("container/scripts/starship-init.sh", "tests", ("test_starship.py",)),
    ("container/scripts/swarmbox-statusline.sh", "tests", ("test_statusline.py",)),
    ("dev/spikes/", "areas", ("guards",)),
    ("dev/test-image/", "areas", ("guards",)),
    ("dev/", "areas", ("release",)),
    (".github/workflows/", "areas", ("release",)),
    ("tests/run.sh", "areas", ("runner",)),
    ("tests/slow/", "areas", ("guards",)),
    ("tests/e2e/", "areas", ("guards",)),
    ("docs/security-review.md", "tests", ("test_security_review.py", "test_guard_docs.py", "test_guard_names.py")),
    ("docs/", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("changelog.d/", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("README.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("CONTRIBUTING.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("CHANGELOG.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("SECURITY.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("CODE_OF_CONDUCT.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("LICENSE", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("THIRD_PARTY_NOTICES.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("AGENTS.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    ("tests/README.md", "tests", ("test_guard_docs.py", "test_guard_names.py")),
    (".github/pull_request_template.md", "areas", ("guards",)),
    (".github/dependabot.yml", "areas", ("guards",)),
    (".gitignore", "areas", ("guards",)),
    (".grype.yaml", "areas", ("guards",)),
)

_FAST_TEST_RE = re.compile(r"^tests/fast/(test_[^/]+\.py)$")


def normalize_path(path):
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def is_shared_infra(path):
    p = normalize_path(path)
    if p in SHARED_INFRA_EXACT:
        return True
    return any(p.startswith(prefix) for prefix in SHARED_INFRA_PREFIXES)


def _select_present(names, available_fast):
    by_base = dict((os.path.basename(f), f) for f in available_fast)
    return sorted(by_base[n] for n in set(names) if n in by_base)


def tests_for_areas(area_names, available_fast):
    """Return (selected_rel_paths, unknown_areas). Always includes GUARDS."""
    unknown = [a for a in area_names if a not in AREAS]
    if unknown:
        return [], unknown
    chosen = set(GUARDS)
    for a in area_names:
        chosen.update(AREAS[a])
    return _select_present(chosen, available_fast), []


def resolve_changed(changed_paths, available_fast):
    """Map changed repo-relative paths to fast test files.

    Returns (selected_rel_paths, note, is_fallback).
    """
    paths = [normalize_path(p) for p in changed_paths if p and normalize_path(p)]
    if not paths:
        return _select_present(GUARDS, available_fast), "loop: clean tree, running guards", False

    chosen = set(GUARDS)
    for p in paths:
        if is_shared_infra(p):
            return list(available_fast), "loop: shared infra changed (%s), running full fast suite" % p, True
        m = _FAST_TEST_RE.match(p)
        if m:
            chosen.add(m.group(1))
            continue
        matched = False
        for pattern, kind, targets in PATH_RULES:
            if (pattern.endswith("/") and p.startswith(pattern)) or p == pattern:
                matched = True
                if kind == "areas":
                    for area in targets:
                        chosen.update(AREAS[area])
                else:
                    chosen.update(targets)
                break
        if not matched:
            return list(available_fast), "loop: unmapped file changed (%s), running full fast suite" % p, True

    selected = _select_present(chosen, available_fast)
    note = "loop: %d changed file(s) -> %d test files" % (len(paths), len(selected))
    return selected, note, False


def git_changed_files(repo_root, since=None):
    """Return (paths, error_message). On success error_message is None."""
    try:
        if since is not None:
            r = subprocess.run(
                ["git", "diff", "--name-only", "-z", since, "--"],
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if r.returncode != 0:
                err = r.stderr.decode("utf-8", "replace").strip() or ("exit %d" % r.returncode)
                return None, err
            paths = [x for x in r.stdout.decode("utf-8", "replace").split("\0") if x]
            u = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if u.returncode == 0:
                paths.extend(x for x in u.stdout.decode("utf-8", "replace").split("\0") if x)
            seen = set()
            out = []
            for p in paths:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
            return out, None

        r = subprocess.run(
            ["git", "status", "--porcelain", "-uall", "-z"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip() or ("exit %d" % r.returncode)
            return None, err
        tokens = r.stdout.decode("utf-8", "replace").split("\0")
        paths = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not tok:
                i += 1
                continue
            status = tok[:2]
            path = tok[3:]
            if path:
                paths.append(path)
            if "R" in status or "C" in status:
                i += 1
                if i < len(tokens) and tokens[i]:
                    paths.append(tokens[i])
            i += 1
        seen = set()
        out = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out, None
    except OSError as e:
        return None, str(e)
