"""Guard: no coding agent is named in the generic code of SwarmBox (docs/agents-design.md, step 9).

An agent is declared once, in its addon (container/addons/<addon>/, with agent/agent.conf), and every other part of the box reads that
declaration through the registry (swarmbox_agents.py, agents.mjs). So the id, the command and every alias of every agent of the registry
(claude, claude-code, agy, antigravity, opencode today: the list is read from the registry, not written here) must not appear in a product
file outside the folder of its addon: the Dockerfile, install.sh, cloudflare-setup.py and everything under container/. Documentation, tests
and dev/ may name agents. A name counts as a word in lower case, not inside a path or a longer name: `claude-code` counts, `~/.claude/`,
`my-claude`, `claudette` and the prose name "Claude Code" do not.

A legitimate use is listed in ALLOW (a file glob, a regular expression the line must match, and the reason). An entry that no longer matches
anything is an error (remove it). The scanner is also checked against small trees of its own, so a guard that stopped finding would fail.
Both read the repository once, through tests/support/repo_scan.py.

Run: python3 tests/fast/test_guard_agents.py
"""
import fnmatch
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import repo_scan  # noqa: E402
from helpers import ROOT  # noqa: E402

ADDONS = os.path.join(ROOT, "container", "addons")
SCOPE = ("Dockerfile", "install.sh", "cloudflare-setup.py", "container/")

_spec = importlib.util.spec_from_file_location("swarmbox_agents", os.path.join(ROOT, "container", "scripts", "swarmbox_agents.py"))
REG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(REG)

# (file glob, regular expression the line must match, reason)
ALLOW = [
    ("container/config/bashrc.sh", r"swarmbox config set AGENT claude|--with claude",
     "an example in the messages of `yolo` (the setting the user types on the host)"),
    ("container/host/swarmbox-host", r"for example: swarmbox claude|the name of an agent \(claude\)",
     "an example in the usage and in a message of the host, which cannot read the box's registry"),
    ("container/scripts/swarmbox-addon.sh", r"\(for example claude\)", "an example in the usage of swarmbox-addon"),
    ("container/scripts/swarmbox-install.sh", r"for example claude,gcloud", "an example in the usage of the installer"),
    ("container/addons/clasp/install.sh", r"measured in 4b\.7: opencode wrote", "a measurement of what an npm postinstall writes, not agent logic"),
]


def agent_names(env):
    """{name: addon} for every id, command and alias of the agents of the registry"""
    out = {}
    for a in REG.agents(env):
        for n in [a["id"], a["cmd"]] + a["aliases"]:
            out.setdefault(n, a["addon"])
    return out


def name_re(names):
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<![\w./-])(%s)(?![\w-])" % alts)


def scan(texts, names, agent_addons, allow=ALLOW):
    """[(file, line number, line, name)] of every agent name in a product file outside the folder of an agent addon"""
    rx = name_re(names)
    skip = tuple("container/addons/%s/" % a for a in agent_addons)
    found = []
    for rel in sorted(texts):
        if not rel.startswith(SCOPE) or rel.startswith(skip):
            continue
        for n, line in enumerate(texts[rel].splitlines(), 1):
            for m in rx.finditer(line):
                if any(fnmatch.fnmatch(rel, g) and re.search(r, line) for g, r, _ in allow):
                    continue
                found.append((rel, n, line.strip()[:160], m.group(1)))
    return found


def repo_env():
    return {"HOME": tempfile.gettempdir(), "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS, "SWARMBOX_TEST_USER_ADDONS": "/nonexistent"}


class TheRepository(unittest.TestCase):
    def setUp(self):
        self.names = agent_names(repo_env())
        self.agent_addons = sorted(set(self.names.values()))
        self.texts = repo_scan.texts()

    def test_the_registry_has_the_agents_this_guard_protects(self):
        for n in ("claude", "claude-code", "agy", "antigravity", "opencode"):
            self.assertIn(n, self.names)

    def test_no_agent_is_named_in_generic_code(self):
        found = scan(self.texts, self.names, self.agent_addons)
        self.assertEqual(found, [], "an agent is named outside its addon: read it from the registry, or add a legitimate use to ALLOW:\n"
                         + "\n".join("%s:%d: %s  [%s]" % f for f in found))

    def test_the_allowlist_has_no_dead_entry_and_every_entry_has_a_reason(self):
        rx = name_re(self.names)
        for g, r, why in ALLOW:
            with self.subTest(glob=g):
                self.assertTrue(why.strip(), "every entry has a reason")
                files = [f for f in self.texts if fnmatch.fnmatch(f, g)]
                self.assertTrue(files, "no file matches the allowlist entry %s: remove it" % g)
                lines = [ln for f in files for ln in self.texts[f].splitlines() if re.search(r, ln) and rx.search(ln)]
                self.assertTrue(lines, "the allowlist entry %s %r matches no line that names an agent: remove it" % (g, r))


class TheScanner(unittest.TestCase):
    NAMES = {"claude": "claude", "claude-code": "claude", "agy": "antigravity", "antigravity": "antigravity"}

    def one(self, line, rel="container/scripts/x.py", allow=()):
        return [f[3] for f in scan({rel: line + "\n"}, self.NAMES, ["claude", "antigravity"], allow)]

    def test_what_it_finds(self):
        self.assertEqual(self.one('AGENTS = ("claude", "agy")'), ["claude", "agy"])
        self.assertEqual(self.one("if app == 'claude-code':"), ["claude-code"])
        self.assertEqual(self.one("# TUIs like agy redraw late"), ["agy"], "a comment counts too")
        self.assertEqual(self.one("const m = { antigravity: 'agy' };", "container/web/herdr/x.mjs"), ["antigravity", "agy"])

    def test_what_it_lets_through(self):
        for line in ("the prose name Claude Code", "~/.claude/settings.json", "my-claude-thing", "claudette", "agyx", "x.agy",
                     "the Antigravity CLI", "/home/agent/.claude.json"):
            with self.subTest(line=line):
                self.assertEqual(self.one(line), [])

    def test_the_folder_of_an_agent_addon_documentation_tests_and_dev_are_not_scanned(self):
        for rel in ("container/addons/claude/agent/agent.conf", "container/addons/antigravity/install.sh", "docs/design.md", "tests/fast/t.py",
                    "dev/x.sh", "README.md"):
            with self.subTest(rel=rel):
                self.assertEqual(self.one("claude agy", rel), [])
        self.assertEqual(self.one("claude", "container/addons/sysop/x.py"), ["claude"], "an addon that is no agent is generic code")
        self.assertEqual(self.one("claude", "Dockerfile"), ["claude"])

    def test_an_allowed_use_is_allowed_in_its_file_and_on_its_line_only(self):
        allow = [("container/x.sh", r"for example claude", "an example")]
        self.assertEqual(self.one("for example claude", "container/x.sh", allow), [])
        self.assertEqual(self.one("for example claude", "container/y.sh", allow), ["claude"])
        self.assertEqual(self.one("AGENT=claude", "container/x.sh", allow), ["claude"])

    def test_the_names_come_from_the_registry(self):
        tmp = tempfile.mkdtemp(prefix="sbguard-")
        self.addCleanup(shutil.rmtree, tmp, True)
        d = os.path.join(tmp, "robo")
        os.makedirs(os.path.join(d, "agent"))
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=robo\nCOMMANDS="robo"\n')
        with open(os.path.join(d, "agent", "agent.conf"), "w") as f:
            f.write('ID=robo\nALIASES="robo-cli"\n')
        names = agent_names({"HOME": tmp, "SWARMBOX_TEST_IMAGE_ADDONS": tmp, "SWARMBOX_TEST_USER_ADDONS": "/nonexistent"})
        self.assertEqual(names, {"robo": "robo", "robo-cli": "robo"})
        self.assertEqual([f[3] for f in scan({"container/scripts/x.py": "run('robo-cli')\n"}, names, ["robo"])], ["robo-cli"])


if __name__ == "__main__":
    unittest.main()
