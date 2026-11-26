"""Guards that look at every file of the repository: no old name of the addon concept, and no default name written as a literal.

Both read the repository once, through tests/support/repo_scan.py (the files of `git ls-files`, each read once), and both are checked against a
small tree of their own (a dict of path to text), so a lint that stopped finding anything would fail too.

1. No old name of the addon concept. The things SwarmBox installs on demand are addons: `swarmbox addon ...`, `swarmbox-addon`, `addon.conf`,
   container/addons, the ADDON_* variables of an installer, SB_ADDONS_DIR. The names this replaced must not come back, in any file or file
   name: not as a compatibility reading, not as a hint, not in a comment. Everything is scanned except .git and the __pycache__ folders,
   docs/history and docs/spikes (records of what was done and measured), the released part of CHANGELOG.md (everything from the first
   released version down; the [Unreleased] entry is scanned) and this file (it names the patterns). Two kinds of finding, both failures:
     - an old name (OLD_NAMES): a command, a file, a variable, a manifest key that no longer exists. Allowed only through OLD_NAME_ALLOW,
       which names the file and the reason.
     - the word "tool" or "tools" (any case, any compound such as WITH_TOOLS, tool-ports, mytool, NoSysopTool). Kept only where it means
       something else, listed in LEGIT_PHRASES (a phrase removed from the line before the check) and in LEGIT_FILES (a whole file where
       the word only ever means the tools an LLM calls), each with its reason. A new use fails the test: say `addon`, or add it here.
2. The default names live in container/host/DEFAULTS and nowhere else. A product file (the Dockerfile, cloudflare-setup.py, container/, dev/,
   .github/) or a test must not hold the default box name or the default image repository as a literal, or one of the retired spellings.
   Documentation (README.md, docs/, CONTRIBUTING.md, THIRD_PARTY_NOTICES.md, CHANGELOG.md) describes the defaults in prose and is checked by
   tests/fast/test_guard_docs.py. (The flip test, "change the two lines of DEFAULTS and the products follow", is in test_host_config.py.)

Run: python3 tests/fast/test_guard_names.py
"""
import fnmatch
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import repo_scan  # noqa: E402
from helpers import DEFAULT_NAME, DEFAULT_IMAGE_REPO, read_defaults  # noqa: E402

SELF = "tests/fast/test_guard_names.py"
SKIP_DIRS = ("docs/history", "docs/spikes")   # and every .git and __pycache__ folder
CHANGELOG = "CHANGELOG.md"
CHANGELOG_RELEASED = re.compile(r"(?m)^## \[(?!Unreleased\])")  # the first released heading starts the history
NOT_TEXT = (".pyc", ".png", ".gif", ".jpg", ".ico", ".woff", ".woff2")

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
    ("container/addons/antigravity/shell.sh", r"\| plugin \| plugins \|",
     "the subcommands of the Antigravity CLI program (`agy plugin`, `agy plugins`), which the agy function never gives the flag"),
    ("container/addons/opencode/shell.sh", r"\| plugin \|",
     "a subcommand of the OpenCode program"),
    ("container/addons/claude/agent/agent.conf", r"^PASSTHROUGH=.* plugin plugins ",
     "the subcommands of the Claude Code program (`claude plugin`, `claude plugins`), passed through without the flags"),
    ("container/addons/antigravity/agent/agent.conf", r"^PASSTHROUGH=.* plugin plugins ",
     "the subcommands of the Antigravity CLI program (`agy plugin`, `agy plugins`), passed through without the flag"),
    ("container/addons/antigravity/prepare.sh", r"(?i)plugins?",
     "the plugins of the Antigravity CLI: the addon gives agy the MCP servers of the box as a plugin of SwarmBox's own"),
    ("tests/fast/test_addon_antigravity.py", r"(?i)plugins?",
     "the test of that Antigravity plugin (its files plugin.json and mcp_config.json)"),
    ("docs/design.md", r"Antigravity plugin|config/plugins/|agy plugin disable",
     "the Antigravity plugin that carries the MCP servers of the box to agy"),
    ("CHANGELOG.md", r"Antigravity plugin|config/plugins/|agy plugin (list|disable)",
     "the Antigravity plugin that carries the MCP servers of the box to agy"),
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
    (r"\btools?\b(?=[^`.]{0,6}`(list_tabs|read_tab|look_tab|box_info|focus_tab|open_tab|close_tab|run|input|wait|say|done)`)", "the tools of the sysop's brain, named right after (`list_tabs`, `look_tab`...)"),
    (r"\*\*Its tools\*\*", "the tools of the sysop's brain (heading of a list in the design page of the addons)"),
    (r"dev-?tools", "Chrome DevTools (the protocol, the MCP server chrome-devtools-mcp): a third-party name"),
    (r"Command Line Tools", "the Xcode Command Line Tools of macOS: a third-party name"),
    (r"net-tools", "the Debian package net-tools"),
    (r"\b(build|test|browser test|host-side) tools\b", "ordinary English: programs a job needs"),
]

# Files where the word only ever means the tools an LLM calls (or a test that exercises them). The old names above still apply there.
LEGIT_FILES = [
    ("container/addons/sysop/lib/**", "the sysop serves tools to an LLM over MCP: mcpserver.py, brain.py, policy.py, audit.py, service.py, ipc.py"),
    ("container/addons/sysop/README.md", "the tools of the sysop's brain"),
    ("docs/sysop.md", "the tools of the sysop's brain, their table, budget and errors"),
    ("tests/support/sysop_support.py", "support of the sysop tests"),
    ("tests/*/test_sysop_*.py", "tests of the sysop: the tools of its brain, the records of their calls ({\"tool\": ...})"),
    ("tests/support/fixtures/sysop/**", "the fake `claude` that calls the sysop's MCP tools from a script"),
    ("dev/spikes/**", "records of experiments with the MCP tools of an LLM and with the Claude Code screens"),
]



PHRASES = [(re.compile(p, re.I), why) for p, why in LEGIT_PHRASES]


def skipped(rel):
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


def scan_path(part):
    """The findings in one component of a path: the name of a file or of a folder."""
    out = ["old name: " + name for name, rx in OLD_NAMES if re.search(rx, part)]
    rest = part
    for rx, _ in PHRASES:
        rest = rx.sub(" ", rest)
    if any(w.search(rest) for w in WORD_PATTERNS):
        out.append('the word "tool" in a name')
    return out


def scan_old_names(files):
    """[(path, line number or 0, text, why)] for {relative path: text or None}: the names of the files and of their folders, and every line."""
    found, seen_dirs = [], set()
    for rel in sorted(files):
        if skipped(rel) or rel.endswith(NOT_TEXT):
            continue
        parts = rel.split("/")
        for i in range(1, len(parts)):          # the folders of the path, each once
            d = "/".join(parts[:i])
            if d not in seen_dirs:
                seen_dirs.add(d)
                found += [(d, 0, "(folder name)", why) for why in scan_path(parts[i - 1])]
        found += [(rel, 0, "(file name)", why) for why in scan_path(parts[-1])]
        if files[rel] is not None:
            found += [(rel, n, line[:160], why) for n, line, why in scan_text(rel, files[rel])]
    return found


# ---- 2. the default names ------------------------------------------------------------------------------------------------------------

PRODUCT_ROOTS = ("Dockerfile", "cloudflare-setup.py", "container/", "dev/", ".github/", "tests/")
DEFAULTS = "container/host/DEFAULTS"
FIXTURES = "tests/support/fixtures/"

# Retired spellings: the names v0.1.0 used as defaults, which must not come back as defaults of 2.0.
RETIRED = [r"ghcr\.io/<org>/swarmbox(?![\w-])", r"ghcr\.io/feroult/swarmbox-dev", r"swarmbox-cloudflared", r"swarmbox-containers", r":-swarmbox\}",
           r"--name swarmbox(?![\w-])", r"default: swarmbox\)"]


def default_patterns(name, repo):
    """The patterns that count as a default written down again. The bare name is the product's own name (written everywhere), so it only counts
    where a default lives: a shell default (`:-NAME}`) and a `--name NAME` argument. The derived names and the image path count anywhere."""
    return [re.compile(p) for p in [r":-%s\}" % re.escape(name), r"--name %s(?![\w-])" % re.escape(name), re.escape(repo) + r"(?![\w-])",
                                    r"(?<![\w.])%s-(?:containers|cloudflared)\b" % re.escape(name)] + RETIRED]


def scan_defaults(files, name, repo):
    """["path:line: text"] for every use of a default name or image repository, outside the DEFAULTS file, the fixtures and this file."""
    pats = default_patterns(name, repo)
    return ["%s:%d: %s" % (rel, n, line.strip()[:120]) for rel, text in sorted(files.items())
            if text is not None and rel.startswith(PRODUCT_ROOTS) and rel not in (DEFAULTS, SELF) and not rel.startswith(FIXTURES)
            and "__pycache__" not in rel
            for n, line in enumerate(text.split("\n"), 1) if any(p.search(line) for p in pats)]


def report(found, limit=60):
    lines = [x if isinstance(x, str) else "%s:%s: %s  [%s]" % (x[0], x[1] or "-", x[2], x[3]) for x in found[:limit]]
    if len(found) > limit:
        lines.append("... and %d more" % (len(found) - limit))
    return "\n" + "\n".join(lines)


class TheRepository(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {rel: repo_scan.read(rel) for rel in repo_scan.repo_files()}

    def test_no_old_name_and_no_stray_tool_word_is_left(self):
        found = scan_old_names(self.files)
        self.assertEqual(found, [], "an old name is back (say addon, or add a legitimate use to the lists of this file):" + report(found))

    def test_no_default_name_or_image_repository_is_written_as_a_literal(self):
        found = scan_defaults(self.files, DEFAULT_NAME, DEFAULT_IMAGE_REPO)
        self.assertEqual(found, [], "read container/host/DEFAULTS (a test: helpers.DEFAULT_NAME) instead:" + report(found))

    def test_the_allowlists_have_no_dead_entry_and_every_entry_has_a_reason(self):
        for glob, _ in LEGIT_FILES + [(g, r) for g, r, _ in OLD_NAME_ALLOW]:
            self.assertTrue(any(fnmatch.fnmatch(f, glob) for f in self.files), "no file matches the allowlist entry %s: remove it" % glob)
        for entry in LEGIT_PHRASES + LEGIT_FILES + [e[::2] for e in OLD_NAME_ALLOW]:
            self.assertTrue(entry[1].strip(), entry)

    def test_the_defaults_file_has_exactly_the_two_keys_and_a_real_owner(self):
        d = read_defaults()
        self.assertEqual(sorted(d), ["SWARMBOX_DEFAULT_IMAGE_REPO", "SWARMBOX_DEFAULT_NAME"])
        self.assertTrue(d["SWARMBOX_DEFAULT_IMAGE_REPO"].endswith("/" + d["SWARMBOX_DEFAULT_NAME"]), d)
        self.assertNotIn("<org>", d["SWARMBOX_DEFAULT_IMAGE_REPO"])   # a real owner, not the placeholder


class TheOldNamesScanner(unittest.TestCase):
    """The scanner on small trees of its own: what it flags and what it lets through."""

    def one(self, text, rel="a.txt"):
        return [h[3] for h in scan_old_names({rel: text + "\n"})]

    def test_every_old_name_is_found(self):
        for s in ("run swarmbox-tool list", "tool.conf", "container/tools/go", "swarmbox tool install go", "export TOOL_PREFIX=x", "TOOL_VERSION", "TOOL_ARCH",
                  "TOOL_SHA256", "SB_TOOLS_DIR", "SWARMBOX_TEST_IMAGE_TOOLS", "SWARMBOX_TOOLS_DIR", "KIND=agent", "PROVIDES=x", "YOLO_FLAGS=x",
                  "YOLO_ALIAS=0", "MCP_FLAGS=x", "MCP_FORMAT=claude", "tests/test_tool_x.py", "see plugin.conf", "swarmbox-plugin list", "the plugin system",
                  "plugins", "an addon named as a tool: the sysop tool"):
            with self.subTest(sample=s):
                self.assertTrue(self.one(s), s)

    def test_the_word_is_found_in_every_form_and_legitimate_uses_pass(self):
        for s in ("a tool", "the tools", "the tool answers addon list", "the toolset", "tooling for addons", "# tooldir=/x", "Tool", "TOOLS", "WITH_TOOLS",
                  "tool_ports", "ToolPorts", "NoSysopTool", "mytool", "imgtools", "x.tools.y", "(tool)", "ThroughSwarmboxToolTest"):
            with self.subTest(found=s):
                self.assertEqual(self.one(s), ['the word "tool"'], s)
        for s in ("the toolchain", "a tooltip", "Chrome DevTools", "chrome-devtools-mcp", "DEVTOOLS", "net-tools", "at most 20 tool calls",
                  "claude --tools '' --allowedTools x", "the Bash tool", "the toolbar", "build tools, jq", "Install test tools", "Command Line Tools",
                  "the built-in tools", "docker buildx imagetools", "the tools `list_tabs` and `run`"):
            with self.subTest(legitimate=s):
                self.assertEqual(self.one(s), [], s)

    def test_a_legitimate_phrase_does_not_hide_a_stray_word_on_the_same_line(self):
        self.assertEqual(self.one("20 tool calls, and install the tool with swarmbox"), ['the word "tool"'])
        self.assertEqual(self.one("the Bash tool; swarmbox-tool list"), ["old name: swarmbox-tool", 'the word "tool"'])

    def test_a_legit_file_keeps_the_word_but_not_the_old_names_and_an_allowed_old_name_is_allowed_in_its_file_only(self):
        self.assertEqual(self.one("the tools of the brain", "docs/sysop.md"), [])
        self.assertEqual(self.one("the tools of the brain, and swarmbox-tool", "docs/sysop.md"), ["old name: swarmbox-tool"])
        line = "        agents | mcp | plugin | plugins | purge)"
        self.assertEqual(self.one(line, "container/addons/claude/shell.sh"), [])
        self.assertEqual(self.one(line, "tests/test_other.py"), ["old name: the intermediate name of the design"])

    def test_file_and_folder_names_are_scanned_and_the_skipped_places_are_skipped(self):
        found = scan_old_names({"container/tools/x/install.sh": "echo hi\n", "tests/test_tool_new.py": "pass\n"})
        self.assertEqual({h[0] for h in found if h[1] == 0}, {"container/tools", "tests/test_tool_new.py"})
        skipped_places = {rel: "swarmbox-tool and tools\n" for rel in ("docs/history/a.md", "docs/spikes/b.md", ".git/config", "x/__pycache__/c.py", SELF)}
        self.assertEqual(scan_old_names(skipped_places), [])

    def test_only_the_released_part_of_the_changelog_is_history_and_an_unreadable_file_does_not_stop_the_scan(self):
        log = "# Changelog\n\n## [Unreleased]\n\n- swarmbox-tool is gone\n\n## [2.0.13] - 2026-11-13\n\n- the tool command\n- swarmbox-tool list\n"
        found = scan_old_names({"CHANGELOG.md": log, "x.bin": None, "a.txt": "fine\n"})
        self.assertEqual({(h[0], h[1]) for h in found}, {("CHANGELOG.md", 5)})


class TheDefaultNamesScanner(unittest.TestCase):
    def test_what_it_finds_and_what_it_lets_through(self):
        n, r = DEFAULT_NAME, DEFAULT_IMAGE_REPO
        bad = ["BOX=${SWARMBOX_NAME:-%s}" % n, 'REPO="%s"' % r, "podman rm -f swarmbox-cloudflared", "podman volume rm swarmbox-containers",
               "NAME=${SWARMBOX_NAME:-swarmbox}", "ghcr.io/<org>/swarmbox:1", "podman rm -f %s-cloudflared" % n]
        fine = ["# swarmbox-test-ok and %s-extra and x%s are not the default" % (n, n), "tmux -L swarmbox; ghcr.io/<org>/swarmbox-other"]
        files = {"dev/a.sh": "\n".join(bad) + "\n", "dev/b.sh": "\n".join(fine) + "\n", DEFAULTS: "SWARMBOX_DEFAULT_NAME=%s\n" % n,
                 FIXTURES + "x.json": r, "docs/a.md": r, SELF: r}
        got = scan_defaults(files, n, r)
        self.assertEqual(sorted({":".join(g.split(":")[:2]) for g in got}), ["dev/a.sh:%d" % i for i in range(1, 8)])


if __name__ == "__main__":
    unittest.main()
