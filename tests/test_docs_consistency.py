"""A few cheap guards on README and docs: the commands they show exist, links resolve, no placeholder is left.
Run: python3 tests/test_docs_consistency.py
"""
import glob
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_NAME, DEFAULT_IMAGE_REPO  # noqa: E402

DEFAULT_REPO_PATH = DEFAULT_IMAGE_REPO.split("/", 1)[1]   # ghcr.io/<owner>/<name> without the registry

HOST = os.path.join(ROOT, "container", "host", "swarmbox-host")
HOST_WORDS_ROUTED = ["stop", "reset", "up", "url", "update", "config", "env", "remote", "fingerprint", "version", "help"]   # the words the script handles itself
FORWARDED_WORDS = ["attach", "pubkey", "tool", "--plain", "claude", "gemini", "yolo", "bash"]


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


README = read("README.md")


def section(text, heading):
    m = re.search(r"^## %s[^\n]*$" % re.escape(heading), text, re.M)
    assert m, "no section '## %s'" % heading
    n = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end():m.end() + n.start()] if n else text[m.end():]


def outside_fences(text):
    return re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)


def slug(h):
    h = re.sub(r"`", "", h.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(text):
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} +(.+?)\s*$", outside_fences(text), re.M)}


class Readme(unittest.TestCase):
    def test_sections_topics_and_no_placeholder(self):
        for h in ("Quick start", "Everyday commands", "Security", "Privacy"):
            section(README, h)
        self.assertEqual(README.count("```") % 2, 0)
        self.assertNotIn("<org>", README)
        # the image is published: the README may name it, but only the one default image repository
        for ref in set(re.findall(r"ghcr\.io/[\w./-]+", README)):
            self.assertEqual(ref, "ghcr.io/" + DEFAULT_REPO_PATH, ref)
        for needle in ("swarmbox config", "swarmbox env add", "swarmbox url", "swarmbox update", "swarmbox tool list",
                       "docs/cloudflare.md", "docs/web-terminal.md", "docs/nested-podman.md", "docs/uninstall.md",
                       "swarmbox remote setup", "swarmbox reset"):
            self.assertIn(needle, README, needle)

    def test_quick_start_installs_the_published_release_with_claude(self):
        qs = section(README, "Quick start")
        self.assertIn("releases/latest/download/install.sh | sh -s -- --with claude", qs)
        self.assertIn("podman run --rm ghcr.io/" + DEFAULT_REPO_PATH + ":", qs)
        self.assertIn("claude", qs)
        self.assertIn("swarmbox env add ANTHROPIC_API_KEY", qs)
        self.assertNotIn("init", qs)
        self.assertNotIn(">> ~/", qs)   # no line appended to a startup file

    def test_remote_access_section_is_in_the_readme(self):
        rem = section(README, "Remote access")
        for needle in ("swarmbox remote setup --domain", "CLOUDFLARE_API_TOKEN", "swarmbox remote off",
                       "swarmbox remote token", "swarmbox url", "ssh ", "docs/cloudflare.md"):
            self.assertIn(needle, rem, needle)

    def test_security_section_states_the_kernel_limit_and_no_safe_claim(self):
        sec = section(README, "Security")
        self.assertIn("shares the kernel", sec)
        self.assertNotRegex(sec.lower(), r"\b(is|are|completely|totally) (secure|safe)\b")

    def test_no_migration_or_v1_scripts_are_mentioned(self):
        self.assertNotRegex(README, r"(?<![\w/-])(start|build)\.sh|Migrating from")

    def test_every_swarmbox_command_in_code_blocks_is_a_real_word(self):
        usage = subprocess.run(["sh", HOST, "help"], capture_output=True, text=True).stdout
        tool_words = set(re.findall(r"^    ([a-z]+)\) cmd_", read("container", "scripts", "swarmbox-tool.sh"), re.M))
        tool_words |= {"validate", "link"}
        subs = {"config": ["get", "set", "list", "seed"], "env": ["add", "rm", "list"],
                "remote": ["setup", "status", "off", "token"]}
        seen = 0
        for block in re.findall(r"^```[a-z]*\n(.*?)^```", README, re.M | re.S):
            for ln in block.splitlines():
                words = ln.split("  #")[0].strip().split()
                while words and re.match(r"^[A-Z_]+=", words[0]):
                    words = words[1:]
                if not words or words[0] != "swarmbox":
                    continue
                seen += 1
                w = words[1] if len(words) > 1 else "attach"
                self.assertIn(w, HOST_WORDS_ROUTED + FORWARDED_WORDS, ln)
                if w in subs and len(words) > 2:
                    self.assertIn(words[2], subs[w], ln)
                if w == "tool" and len(words) > 2:
                    self.assertIn(words[2], tool_words, ln)
                if w in HOST_WORDS_ROUTED:
                    self.assertIn(w, usage, ln)
        self.assertGreater(seen, 8)


class Links(unittest.TestCase):
    def test_every_relative_link_of_the_user_docs_resolves(self):
        files = [os.path.join(ROOT, n) for n in ("README.md", "SECURITY.md", "CONTRIBUTING.md")]
        files += sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))
        bad = []
        for f in files:
            text = re.sub(r"`[^`\n]*`", "", outside_fences(read(os.path.relpath(f, ROOT))))
            for m in re.finditer(r"\]\(([^)\s]+)\)", text):
                target = m.group(1)
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(f), path)) if path else f
                if not os.path.exists(dest):
                    bad.append("%s -> %s" % (os.path.relpath(f, ROOT), target))
                elif frag and dest.endswith(".md") and frag not in anchors(read(os.path.relpath(dest, ROOT))):
                    bad.append("%s -> %s (no such heading)" % (os.path.relpath(f, ROOT), target))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
