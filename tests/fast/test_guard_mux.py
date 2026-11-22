"""Architectural guard: tmux usage inside container/ must stay isolated inside the explicit tmux adapter files.

Core scripts (entrypoint.sh, swarmbox-attach.sh, swarmbox-web.sh, swarmbox-bus.py, swarmbox-addon.sh) and
mux-agnostic sysop modules (service.py, state.py, actions.py, policy.py, audit.py, history.py, ipc.py, paths.py,
config.py, watch.py, mcpserver.py, tabsclient.py) must never acquire direct tmux invocations or dock imports.

Run with: python3 -W error tests/fast/test_guard_mux.py
"""
import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import repo_scan  # noqa: E402

# Files under container/ that are explicitly allowed to execute tmux commands or import the tmux dock adapter.
TMUX_ADAPTER_FILES = {
    "container/scripts/mux/tmux.sh": "concrete tmux shell backend (serve init, attach, command runner, web fallback)",
    "container/scripts/swarmbox-tabs.py": "TmuxBackend class implementing the TabsBackend contract",
    "container/config/tmux.conf": "tmux server configuration and keybindings",
    "container/config/tmux-browser-keys.conf": "browser keybinding table for tmux",
    "container/web/ttyd-clipboard.js": "browser bridge for ttyd/tmux copy mode and strip controls",
    "container/web/ttyd-style.css": "browser stylesheet for ttyd/tmux strip controls",
    "container/addons/sysop/lib/swarmbox_sysop/dock.py": "tmux pane docking and Follower adapter",
    "container/addons/sysop/lib/swarmbox_sysop/panel.py": "tmux-hosted ANSI panel and client probe",
    "container/addons/sysop/lib/swarmbox_sysop/line.py": "tmux @sysop_line status-line sink",
    "container/addons/sysop/lib/swarmbox_sysop/keys.py": "tmux prefix-key wrapper over actions.py",
    "container/addons/sysop/lib/swarmbox_sysop/ui_host.py": "mux UI dispatcher that lazily loads tmux Follower/Toaster",
    "container/addons/sysop/lib/swarmbox_sysop/__main__.py": "fast-path lazy dispatch for `dock redock` resize bursts",
    "container/addons/sysop/lib/swarmbox_sysop/risk.py": "security guardrail regex flagging commands that touch tmux",
}

# Patterns that indicate direct runtime coupling to tmux (code lines only, comments stripped).
TMUX_PATTERNS = [
    ("direct tmux command invocation", re.compile(r"""(?:^|[\s;|&`("'\[\{])tmux(?:\s+-[A-Za-z]|\s+(?:new-session|has-session|attach|attach-session|kill-session|kill-window|new-window|list-windows|list-panes|list-clients|display-message|capture-pane|send-keys|set-option|show-options|link-window|wait-for|split-window|select-window)\b)""")),
    ("subprocess tmux call", re.compile(r"""["']tmux["']\s*[,\]\)]""")),
    ("sysop dock import", re.compile(r"""\b(?:from\s+\.\s+import\s+[^#\n]*\bdock\b|from\s+\.dock\s+import|import\s+[^#\n]*\bdock\b)""")),
]


def _code_lines(rel, text):
    """Yield (lineno, code) with full-line comments and Python docstrings excluded."""
    if rel.endswith(".py"):
        # Strip triple-quoted strings (docstrings) line-preserving so line numbers stay accurate
        cleaned = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', lambda m: "\n" * m.group(0).count("\n"), text)
        for n, ln in enumerate(cleaned.splitlines(), 1):
            code = ln.split("#", 1)[0]
            if code.strip():
                yield n, code
        return
    for n, ln in enumerate(text.splitlines(), 1):
        stripped = ln.lstrip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        yield n, ln


def scan_container(files):
    """Return [(path, lineno, line, reason)] for tmux leaks outside TMUX_ADAPTER_FILES."""
    findings = []
    for rel, text in sorted(files.items()):
        if text is None or not rel.startswith("container/"):
            continue
        if rel in TMUX_ADAPTER_FILES or rel.endswith(".md") or rel.endswith(".conf"):
            continue
        if rel.startswith("container/host/"):
            continue
        for n, code in _code_lines(rel, text):
            for why, rx in TMUX_PATTERNS:
                if rx.search(code):
                    findings.append((rel, n, code.strip()[:140], why))
    return findings


class MuxBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {rel: repo_scan.read(rel) for rel in repo_scan.repo_files()}

    def test_no_direct_tmux_coupling_outside_adapter_files(self):
        found = scan_container(self.files)
        msg = "\n".join("%s:%d: %s  [%s]" % f for f in found)
        self.assertEqual(found, [], "tmux leaked into a core file (route through mux/ or TabsBackend/ui_host instead):\n" + msg)

    def test_allowlist_has_no_dead_entries_and_every_entry_has_a_reason(self):
        for rel, reason in TMUX_ADAPTER_FILES.items():
            self.assertIn(rel, self.files, "dead TMUX_ADAPTER_FILES entry: %s" % rel)
            self.assertTrue(reason.strip(), rel)

    def test_core_files_are_not_in_the_tmux_adapter_allowlist(self):
        must_be_clean = (
            "container/entrypoint.sh",
            "container/scripts/swarmbox-attach.sh",
            "container/scripts/swarmbox-web.sh",
            "container/scripts/swarmbox-bus.py",
            "container/addons/sysop/lib/swarmbox_sysop/service.py",
            "container/addons/sysop/lib/swarmbox_sysop/cli.py",
            "container/addons/sysop/lib/swarmbox_sysop/state.py",
            "container/addons/sysop/lib/swarmbox_sysop/actions.py",
            "container/addons/sysop/lib/swarmbox_sysop/policy.py",
            "container/addons/sysop/lib/swarmbox_sysop/mcpserver.py",
            "container/addons/sysop/lib/swarmbox_sysop/tabsclient.py",
        )
        for rel in must_be_clean:
            self.assertIn(rel, self.files, rel)
            self.assertNotIn(rel, TMUX_ADAPTER_FILES, rel)

    def test_swarmbox_tabs_only_invokes_tmux_inside_tmux_backend(self):
        src = self.files["container/scripts/swarmbox-tabs.py"]
        tree = ast.parse(src, filename="swarmbox-tabs.py")
        leaks = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "TmuxBackend":
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "tmux":
                    # Only the backwards-compat Tabs.tmux() pass-through may forward to self.backend.tmux()
                    if isinstance(node, ast.ClassDef) and node.name == "Tabs":
                        parent_fn = next(
                            (m.name for m in node.body if isinstance(m, ast.FunctionDef)
                             and m.lineno <= sub.lineno <= (m.end_lineno or m.lineno)),
                            None,
                        )
                        if parent_fn == "tmux":
                            continue
                    leaks.append((sub.lineno, getattr(node, "name", type(node).__name__)))
        self.assertEqual(leaks, [], "tmux call leaked outside TmuxBackend in swarmbox-tabs.py: %r" % (leaks,))


class ScannerSelfTest(unittest.TestCase):
    def test_scanner_catches_leaks_and_ignores_comments(self):
        tree = {
            "container/scripts/core.sh": "# tmux new-session -d\ntmux new-session -d -s main\n",
            "container/addons/sysop/lib/swarmbox_sysop/core.py": '"""tmux attach"""\nfrom . import dock\nsubprocess.run(["tmux", "ls"])\n',
            "container/scripts/clean.sh": "# mentions tmux in comment only\necho ok\n",
        }
        found = scan_container(tree)
        paths = [f[0] for f in found]
        self.assertEqual(paths.count("container/scripts/core.sh"), 1)
        self.assertEqual(paths.count("container/addons/sysop/lib/swarmbox_sysop/core.py"), 2)
        self.assertNotIn("container/scripts/clean.sh", paths)


if __name__ == "__main__":
    unittest.main()
