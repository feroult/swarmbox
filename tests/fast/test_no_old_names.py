"""Guard: the repository carries no old name of the addon concept.

The things SwarmBox installs on demand are addons: `swarmbox addon ...`, `swarmbox-addon`, `addon.conf`, container/addons, the
ADDON_* variables of an installer, SB_ADDONS_DIR. The names this replaced must not come back, in any file or file name: not as a
compatibility reading, not as a hint, not in a comment. This test scans every file of the repository, except
  - .git and the __pycache__ folders,
  - docs/history and docs/spikes (records of what was done and measured),
  - the released part of CHANGELOG.md (everything from the first released version down: history; the [Unreleased] entry is scanned),
  - this file (it names the patterns).

Two kinds of finding, both failures:
  1. an old name (the OLD_NAMES list): a command, a file, a variable, a manifest key that no longer exists. Allowed only through
     OLD_NAME_ALLOW, which names the file and the reason.
  2. the word "tool" or "tools" (any case, any compound such as WITH_TOOLS, tool-ports, mytool, NoSysopTool). It is kept only where it
     means something else, listed in LEGIT_PHRASES (a phrase that is removed from the line before the check) and in LEGIT_FILES (a whole
     file where the word only ever means the tools an LLM calls), each with its reason. A new use that is not listed fails the
     test: say `addon`, or add the phrase here with a reason.

Run: python3 tests/fast/test_no_old_names.py
"""
import fnmatch
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SELF = "tests/fast/test_no_old_names.py"
SKIP_DIRS = ("docs/history", "docs/spikes")   # and every .git and __pycache__ folder
CHANGELOG = "CHANGELOG.md"
CHANGELOG_RELEASED = re.compile(r"(?m)^## \[(?!Unreleased\])")  # the first released heading starts the history

# ---- 1. the old names (regular expressions, searched in every line and in every path) ------------------------------------------------

OLD_NAMES = [
    ("swarmbox-tool", r"swarmbox-tool"),
    ("tool.conf", r"tool\.conf"),
    ("container/tools", r"container/tools"),
    ("swarmbox tool", r"swarmbox tool"),
    ("TOOL_PREFIX and its siblings", r"TOOL_(PREFIX|VERSION|ARCH|SHA256)"),
    ("SB_TOOLS_DIR", r"SB_TOOLS_DIR"),
    ("SWARMBOX_TEST_*TOOL*", r"SWARMBOX_TEST_\w*TOOL"),
    ("SWARMBOX_TOOL*", r"SWARMBOX_\w*TOOL"),
    ("KIND=", r"KIND="),
    ("PROVIDES", r"PROVIDES"),
    ("YOLO_FLAGS", r"YOLO_FLAGS"),
    ("YOLO_ALIAS", r"YOLO_ALIAS"),
    ("MCP_FLAGS", r"MCP_FLAGS"),
    ("MCP_FORMAT", r"MCP_FORMAT"),
    ("the files and tests that carried the word", r"test_tool_|test_sysop_tool|test_image_with_tools|swarmbox-tool\.sh|tool-ports"),
    ("the intermediate name of the design", r"(?i)plugins?"),
    ("an addon named as a tool (a program or a mod of SwarmBox)", r"\b(sysop|voice|claude|gemini|opencode|clasp|poetry|gcloud) tool\b(?! calls?)"),
]

# (path glob, regex, reason): the old names that a file may carry. The regex is removed from the line before the check.
OLD_NAME_ALLOW = [
    ("container/addons/claude/shell.sh", r"\| plugin \| plugins \|",
     "the subcommands of the Claude Code program (`claude plugin`, `claude plugins`), which the claude function never gives the flags"),
    ("container/addons/opencode/shell.sh", r"\| plugin \|",
     "a subcommand of the OpenCode program"),
]

# ---- 2. the word "tool" / "tools" ------------------------------------------------------------------------------------------------------

WORD_PATTERNS = [
    re.compile(r"(?<![A-Za-z])(?:tools?|Tools?|TOOLS?)"),   # tool, Tools, TOOLS, WITH_TOOLS, tool-ports, ToolPorts, tooldir, toolset, tooling
    re.compile(r"(?<=[a-z])Tools?(?![a-z])"),            # NoSysopTool, NpmToolInstall
    re.compile(r"(?<=[a-z])tools?\b"),                   # mytool, imgtools
]

# Phrases (searched with re.I unless stated) that are removed from a line before the check, anywhere in the repository. Each is a
# legitimate use of the word: the tools an LLM calls, a third party's own text, or ordinary English for programs.
LEGIT_PHRASES = [
    (r"--tools\b|allowedTools", "the options of the `claude` program that choose the tools of an LLM (`--tools \"\"`, `--allowedTools`)"),
    (r"\btool calls?\b", "a call of an LLM to one of its tools (the budget of the sysop is counted in them)"),
    (r"\b(Bash|Write|Read|Edit) tool\b", "the built-in tools of Claude Code, named as its own screen names them (third-party text)"),
    (r"\bbuilt-in tools?\b", "the built-in tools of Claude Code, which the sysop's brain runs without"),
    (r"gives it a few tools that read\b", "the sysop's brain (a program that speaks MCP) is given a few tools: its own words in addon.conf"),
    (r"tells the brain where the tools are\b", "the MCP file that tells the sysop's brain where its tools are (error text of the host)"),
    (r"a few tools served by `swarmbox-sysop mcp`", "the tools the sysop serves to its brain over MCP (design.md)"),
    (r"The tools call `swarmbox-tabs`", "the sysop tools call swarmbox-tabs as a child process (design.md)"),
    (r"tool(chain|bar|tip)s?|ToolError", "ordinary English and words of the web page: the toolchain (a language's compiler), the strip's toolbar and tooltip, the error of a sysop tool call"),
    (r"itertools|imagetools|setuptools|libtool|autotools|mailtools",
     "names of third-party software: Python itertools and setuptools, docker buildx imagetools, GNU libtool, Debian libmailtools-perl"),
    (r"\btools?\b(?=[^`.]{0,6}`(list_tabs|read_tab|look_tab|run|input|wait|say|done)`)", "the tools of the sysop's brain, named right after (`list_tabs`, `look_tab`...)"),
    (r"\*\*Its tools\*\*", "the tools of the sysop's brain (heading of a list in the design page of the addons)"),
    (r"dev-?tools", "Chrome DevTools (the protocol, the MCP server chrome-devtools-mcp): a third-party name"),
    (r"Command Line Tools", "the Xcode Command Line Tools of macOS: a third-party name"),
    (r"net-tools", "the Debian package net-tools"),
    (r"\b(build|test|browser test|host-side) tools\b", "ordinary English: programs a job needs"),
]

# Files where the word only ever means the tools an LLM calls (or a test that exercises them). The old names above still apply there.
LEGIT_FILES = [
    ("container/addons/sysop/lib/**", "the sysop serves tools to an LLM over MCP: mcpserver.py, brain.py, policy.py, audit.py, service.py, ipc.py, panel.py"),
    ("container/addons/sysop/README.md", "the tools of the sysop's brain"),
    ("docs/sysop.md", "the tools of the sysop's brain, their table, budget and errors"),
    ("tests/support/sysop_support.py", "support of the sysop tests"),
    ("tests/*/test_sysop_*.py", "tests of the sysop: the tools of its brain, the records of their calls ({\"tool\": ...})"),
    ("tests/support/fixtures/sysop/**", "the fake `claude` that calls the sysop's MCP tools from a script"),
    ("tests/support/fixtures/soak/brain.py", "the scripted brain of the soak test: steps that call the sysop's tools"),
    ("tests/e2e/e2e_sysop.py", "the real-model test of the sysop: goals that tell the brain which tool to call, and the records of the calls"),
    ("tests/e2e/e2e_voice.py", "the real-model test of voice and sysop: the records of the tools the brain called"),
    ("tests/e2e/soak_v1.py", "the soak test: the records of the tools the brain called"),
    ("dev/spikes/**", "records of experiments with the MCP tools of an LLM and with the Claude Code screens"),
]


PHRASES = [(re.compile(p, re.I), why) for p, why in LEGIT_PHRASES]


def _skipped(rel):
    if rel == SELF or any(rel == d or rel.startswith(d + "/") for d in SKIP_DIRS):
        return True
    return any(part in (".git", "__pycache__") for part in rel.split("/"))


def scan_text(rel, text):
    """[(line number, line, why)] of the findings of one file."""
    if rel == CHANGELOG:
        m = CHANGELOG_RELEASED.search(text)
        if m:
            text = text[:m.start()]
    old_allow = [re.compile(rx) for g, rx, _ in OLD_NAME_ALLOW if fnmatch.fnmatch(rel, g)]
    word_ok = any(fnmatch.fnmatch(rel, g) for g, _ in LEGIT_FILES)
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        probe = line
        for rx in old_allow:
            probe = rx.sub("", probe)
        for name, rx in OLD_NAMES:
            if re.search(rx, probe):
                out.append((n, line.strip(), "old name: " + name))
        if word_ok:
            continue
        rest = probe
        for rx, _ in PHRASES:
            rest = rx.sub(" ", rest)
        if any(w.search(rest) for w in WORD_PATTERNS):
            out.append((n, line.strip(), 'the word "tool"'))
    return out


def scan_path(rel):
    """The findings in the last component of a path: the name of a file or of a folder."""
    out = []
    part = rel.split("/")[-1]
    for name, rx in OLD_NAMES:
        if re.search(rx, part):
            out.append("old name: " + name)
    rest = part
    for rx, _ in PHRASES:
        rest = rx.sub(" ", rest)
    if any(w.search(rest) for w in WORD_PATTERNS):
        out.append('the word "tool" in a name')
    return out


def repo_files(root):
    """The relative paths of the files that belong to the repository: tracked or new and not ignored (git), else every file of the
    folder except the ones in a folder that starts with a dot (and .github)."""
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            return sorted(set(p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p))
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if not d.startswith(".") or d == ".github"]
        out.extend((rel_dir + "/" + f).lstrip("/") for f in filenames)
    return sorted(out)


def scan_tree(root, files=None):
    """[(relative path, line number or 0, text, why)] of every finding among the files of the repository under root."""
    found = []
    seen_dirs = set()
    for rel in (repo_files(root) if files is None else files):
        if _skipped(rel) or rel.endswith((".pyc", ".png", ".gif", ".jpg", ".ico", ".woff", ".woff2")):
            continue
        full = os.path.join(root, rel)
        if os.path.islink(full) or not os.path.isfile(full):
            continue
        parts = rel.split("/")
        for i in range(1, len(parts)):          # the folders of the path, each once
            d = "/".join(parts[:i])
            if d not in seen_dirs:
                seen_dirs.add(d)
                for why in scan_path(d):
                    found.append((d, 0, "(folder name)", why))
        for why in scan_path(rel):
            found.append((rel, 0, "(file name)", why))
        try:
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line, why in scan_text(rel, text):
            found.append((rel, n, line[:160], why))
    return found


def report(found, limit=60):
    lines = ["%s:%s: %s  [%s]" % (p, n or "-", t, why) for p, n, t, why in found[:limit]]
    if len(found) > limit:
        lines.append("... and %d more" % (len(found) - limit))
    return "\n" + "\n".join(lines)


class TheRepository(unittest.TestCase):
    def test_no_old_name_and_no_stray_tool_word_is_left(self):
        found = scan_tree(ROOT)
        self.assertEqual(found, [], "an old name is back (say addon, or add a legitimate use to the lists of this file):" + report(found))

    def test_every_file_level_entry_of_the_lists_matches_a_file(self):
        files = repo_files(ROOT)
        for glob, _ in LEGIT_FILES + [(g, r) for g, r, _ in OLD_NAME_ALLOW]:
            self.assertTrue(any(fnmatch.fnmatch(f, glob) for f in files), "no file matches the allowlist entry %s: remove it" % glob)

    def test_every_entry_has_a_reason(self):
        for entry in LEGIT_PHRASES + LEGIT_FILES:
            self.assertTrue(entry[1].strip(), entry)
        for entry in OLD_NAME_ALLOW:
            self.assertTrue(entry[2].strip(), entry)


class TheScanner(unittest.TestCase):
    """The scanner on a small tree of its own: what it flags and what it lets through."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="old-names-")
        self.addCleanup(__import__("shutil").rmtree, self.root, ignore_errors=True)

    def put(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def hits(self):
        return scan_tree(self.root)

    def test_every_old_name_is_found(self):
        samples = ["run swarmbox-tool list", "tool.conf", "container/tools/go", "swarmbox tool install go", "export TOOL_PREFIX=x",
                   "TOOL_VERSION", "TOOL_ARCH", "TOOL_SHA256", "SB_TOOLS_DIR", "SWARMBOX_TEST_IMAGE_TOOLS", "SWARMBOX_TOOLS_DIR",
                   "KIND=agent", "PROVIDES=x", "YOLO_FLAGS=x", "YOLO_ALIAS=0", "MCP_FLAGS=x", "MCP_FORMAT=claude", "tests/test_tool_x.py",
                   "see plugin.conf", "swarmbox-plugin list", "the plugin system", "plugins", "an addon named as a tool: the sysop tool"]
        for s in samples:
            with self.subTest(sample=s):
                self.put("a.txt", s + "\n")
                self.assertTrue(self.hits(), s)

    def test_the_word_is_found_in_every_form(self):
        for s in ("a tool", "the tools", "the tools are installed on first use", "the tool answers addon list", "the toolset", "tooling for addons",
                  "# tooldir=/x", "Tool", "TOOLS", "WITH_TOOLS", "tool_ports", "ToolPorts", "NoSysopTool", "mytool",
                  "imgtools", "x.tools.y", "(tool)", "ThroughSwarmboxToolTest"):
            with self.subTest(sample=s):
                self.put("a.txt", s + "\n")
                self.assertEqual([h[3] for h in self.hits()], ['the word "tool"'], s)

    def test_legitimate_uses_pass(self):
        for s in ("the toolchain", "a tooltip", "Chrome DevTools", "chrome-devtools-mcp", "DEVTOOLS", "net-tools",
                  "at most 20 tool calls", "claude --tools '' --allowedTools x", "the Bash tool", "the toolbar", "build tools, jq", "Install test tools",
                  "Command Line Tools", "the built-in tools", "docker buildx imagetools", "the tools `list_tabs` and `run`"):
            with self.subTest(sample=s):
                self.put("a.txt", s + "\n")
                self.assertEqual(self.hits(), [], s)

    def test_a_legitimate_phrase_does_not_hide_a_stray_word_on_the_same_line(self):
        self.put("a.txt", "20 tool calls, and install the tool with swarmbox\n")
        self.assertEqual([h[3] for h in self.hits()], ['the word "tool"'])
        self.put("a.txt", "the Bash tool; swarmbox-tool list\n")
        self.assertEqual([h[3] for h in self.hits()], ["old name: swarmbox-tool", 'the word "tool"'])

    def test_a_legit_file_keeps_the_word_but_not_the_old_names(self):
        self.put("docs/sysop.md", "the tools of the brain\n")
        self.assertEqual(self.hits(), [])
        self.put("docs/sysop.md", "the tools of the brain, and swarmbox-tool\n")
        self.assertEqual([h[3] for h in self.hits()], ["old name: swarmbox-tool"])

    def test_the_allowed_old_names_are_allowed_in_their_file_only(self):
        line = "        agents | mcp | plugin | plugins | purge)\n"
        self.put("container/addons/claude/shell.sh", line)
        self.assertEqual(self.hits(), [])
        self.put("tests/test_other.py", line)
        self.assertEqual([h[3] for h in self.hits()], ["old name: the intermediate name of the design"])

    def test_the_names_of_files_and_folders_are_scanned(self):
        self.put("container/tools/x/install.sh", "echo hi\n")
        self.put("tests/test_tool_new.py", "pass\n")
        paths = {h[0] for h in self.hits() if h[1] == 0}
        self.assertEqual(paths, {"container/tools", "tests/test_tool_new.py"})

    def test_the_skipped_places_are_skipped(self):
        for rel in ("docs/history/a.md", "docs/spikes/b.md", ".git/config", "x/__pycache__/c.py", SELF):
            self.put(rel, "swarmbox-tool and tools\n")
        self.assertEqual(self.hits(), [])

    def test_only_the_released_part_of_the_changelog_is_history(self):
        self.put("CHANGELOG.md", "# Changelog\n\n## [Unreleased]\n\n- swarmbox-tool is gone\n\n## [2.0.13] - 2026-11-13\n\n- the tool command\n- swarmbox-tool list\n")
        found = self.hits()
        self.assertEqual({(h[0], h[1]) for h in found}, {("CHANGELOG.md", 5)})

    def test_binary_files_and_unreadable_files_do_not_stop_the_scan(self):
        with open(os.path.join(self.root, "x.bin"), "wb") as f:
            f.write(b"\xff\xfe tool \x00")
        self.put("a.txt", "fine\n")
        self.assertEqual(self.hits(), [])


if __name__ == "__main__":
    unittest.main()
