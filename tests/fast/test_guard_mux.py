"""Architectural guard: herdr (herdr-core, `hc`) is the only multiplexer of the box. Nothing under container/ may run tmux or ttyd again, or
ship a file for them (a tmux.conf, a ttyd page).

The host helper (container/host/) is not scanned: it only prints a warning for the removed MUX key.

Run with: python3 -W error tests/fast/test_guard_mux.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import repo_scan  # noqa: E402

# Patterns that indicate a runtime use of tmux or ttyd (code lines only, comments stripped).
PATTERNS = [
    ("direct tmux command invocation", re.compile(r"""(?:^|[\s;|&`("'\[\{])tmux(?:\s+-[A-Za-z]|\s+(?:new-session|has-session|attach|attach-session|kill-session|kill-window|new-window|list-windows|list-panes|list-clients|display-message|capture-pane|send-keys|set-option|show-options|link-window|wait-for|split-window|select-window)\b)""")),
    ("subprocess tmux call", re.compile(r"""["']tmux["']\s*[,\]\)]""")),
    ("ttyd invocation", re.compile(r"""(?:^|[\s;|&`("'\[\{])ttyd(?:\s+-|\s*["']?\s*[,\]\)])|["']ttyd["']""")),
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
    """Return [(path, lineno, line, reason)] for every use of tmux or ttyd under container/."""
    findings = []
    for rel, text in sorted(files.items()):
        if text is None or not rel.startswith("container/"):
            continue
        if rel.endswith(".md") or rel.startswith("container/host/"):
            continue
        for n, code in _code_lines(rel, text):
            for why, rx in PATTERNS:
                if rx.search(code):
                    findings.append((rel, n, code.strip()[:140], why))
    return findings


class OnlyHerdr(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {rel: repo_scan.read(rel) for rel in repo_scan.repo_files()}

    def test_nothing_under_container_runs_tmux_or_ttyd(self):
        found = scan_container(self.files)
        msg = "\n".join("%s:%d: %s  [%s]" % f for f in found)
        self.assertEqual(found, [], "tmux or ttyd came back (herdr is the only multiplexer):\n" + msg)

    def test_no_file_for_tmux_or_ttyd_is_shipped(self):
        left = sorted(rel for rel in self.files if rel.startswith(("container/", "Dockerfile"))
                      and re.search(r"(?i)(^|/)[^/]*(tmux|ttyd)[^/]*$", rel))
        self.assertEqual(left, [], "a tmux or ttyd file is still in the image sources")

    def test_the_image_installs_neither(self):
        df = self.files["Dockerfile"]
        self.assertNotRegex(df, r"(?i)\btmux\b")
        self.assertNotRegex(df, r"(?i)\bttyd\b")
        self.assertIn("herdr-core", df)

    def test_the_mux_loader_defaults_to_herdr_and_there_is_no_other_backend(self):
        mux = sorted(rel for rel in self.files if rel.startswith("container/scripts/mux/"))
        self.assertEqual(mux, ["container/scripts/mux/herdr.sh", "container/scripts/mux/mux.sh"])
        self.assertIn("SB_MUX_NAME=${SWARMBOX_MUX:-herdr}", self.files["container/scripts/mux/mux.sh"])


class ScannerSelfTest(unittest.TestCase):
    def test_scanner_catches_leaks_and_ignores_comments(self):
        tree = {
            "container/scripts/core.sh": "# tmux new-session -d\ntmux new-session -d -s main\nexec ttyd -p 7681 bash\n",
            "container/addons/sysop/lib/swarmbox_sysop/core.py": '"""tmux attach"""\nsubprocess.run(["tmux", "ls"])\nsubprocess.run(["ttyd", "-p", "1"])\n',
            "container/scripts/clean.sh": "# mentions tmux and ttyd in a comment only\necho ok\n",
        }
        found = scan_container(tree)
        paths = [f[0] for f in found]
        self.assertEqual(paths.count("container/scripts/core.sh"), 2)
        self.assertEqual(paths.count("container/addons/sysop/lib/swarmbox_sysop/core.py"), 2)
        self.assertNotIn("container/scripts/clean.sh", paths)


if __name__ == "__main__":
    unittest.main()
