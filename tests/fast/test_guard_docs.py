"""Guards on the documents of the repository: the README shows commands that exist, links resolve, no placeholder is left, the policy files exist,
and the third-party notices list everything the image installs. Cheap text checks: no process but `swarmbox help`.
Run: python3 tests/fast/test_guard_docs.py
"""
import glob
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, DEFAULT_IMAGE_REPO  # noqa: E402

DEFAULT_REPO_PATH = DEFAULT_IMAGE_REPO.split("/", 1)[1]   # ghcr.io/<owner>/<name> without the registry

HOST = os.path.join(ROOT, "container", "host", "swarmbox-host")
HOST_WORDS_ROUTED = ["stop", "reset", "up", "url", "update", "config", "env", "remote", "fingerprint", "version", "help"]   # the words the script handles itself
FORWARDED_WORDS = ["attach", "pubkey", "addon", "--plain", "claude", "gemini", "yolo", "bash"]
POLICY_FILES = ("SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md")


def read(*p):
    path = os.path.join(ROOT, *p)
    if not os.path.isfile(path):
        raise AssertionError("%s does not exist" % "/".join(p))
    with open(path, encoding="utf-8") as f:
        return f.read()


README = read("README.md")


def section(text, heading):
    """The part of the README from the "## <heading>" line to the next "## " line."""
    m = re.search(r"^## %s[^\n]*$" % re.escape(heading), text, re.M)
    assert m, "no section '## %s'" % heading
    n = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end():m.end() + n.start()] if n else text[m.end():]


def notice_section(text, program):
    """The part of the notices from the heading that names `program` (level 2 or 3) to the next heading of level 1 to 3."""
    m = re.search(r"^#{2,3} .*\b%s\b.*$" % re.escape(program), text, re.M | re.I)
    assert m, "no heading for %s in the notices" % program
    n = re.search(r"^#{1,3} ", text[m.end():], re.M)
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
    def test_sections_topics_no_placeholder_and_no_old_script(self):
        for h in ("Quick start", "Everyday commands", "Security"):
            section(README, h)
        self.assertEqual(README.count("```") % 2, 0)
        self.assertNotIn("<org>", README)
        # the image is published: the README may name it, but only the one default image repository
        for ref in set(re.findall(r"ghcr\.io/[\w./-]+", README)):
            self.assertEqual(ref, "ghcr.io/" + DEFAULT_REPO_PATH, ref)
        for needle in ("swarmbox config", "swarmbox env add", "swarmbox url", "swarmbox update", "swarmbox addon list",
                       "docs/cloudflare.md", "docs/web-terminal.md", "docs/nested-podman.md", "docs/uninstall.md",
                       "swarmbox remote setup", "swarmbox reset"):
            self.assertIn(needle, README, needle)
        self.assertNotRegex(README, r"(?<![\w/-])(start|build)\.sh|Migrating from")

    def test_quick_start_installs_the_published_release_with_claude(self):
        qs = section(README, "Quick start")
        self.assertIn("releases/latest/download/install.sh | sh -s -- --with claude", qs)
        self.assertIn("swarmbox env add ANTHROPIC_API_KEY", qs)
        self.assertNotIn("init", qs)
        self.assertNotIn(">> ~/", qs)   # no line appended to a startup file

    def test_remote_access_points_to_its_page_which_has_the_details(self):
        page = read("docs", "cloudflare.md")
        for needle in ("swarmbox remote setup --domain", "CLOUDFLARE_API_TOKEN", "swarmbox remote off", "swarmbox remote token"):
            self.assertIn(needle, page, needle)

    def test_security_section_states_the_kernel_limit_and_no_safe_claim(self):
        sec = section(README, "Security")
        self.assertIn("shares the kernel", sec)
        self.assertNotRegex(sec.lower(), r"\b(is|are|completely|totally) (secure|safe)\b")

    def test_every_swarmbox_command_in_code_blocks_is_a_real_word(self):
        usage = subprocess.run(["sh", HOST, "help"], capture_output=True, text=True).stdout
        addon_words = set(re.findall(r"^    ([a-z]+)\) cmd_", read("container", "scripts", "swarmbox-addon.sh"), re.M))
        addon_words |= {"validate", "link"}
        subs = {"config": ["get", "set", "list", "seed"], "env": ["add", "rm", "list"], "remote": ["setup", "status", "off", "token"]}
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
                if w == "addon" and len(words) > 2:
                    self.assertIn(words[2], addon_words, ln)
                if w in HOST_WORDS_ROUTED:
                    self.assertIn(w, usage, ln)
        self.assertGreater(seen, 5)


class Links(unittest.TestCase):
    def test_every_relative_link_of_the_documents_resolves_and_the_fences_are_balanced(self):
        files = [os.path.join(ROOT, n) for n in ("README.md", "CONTRIBUTING.md") + POLICY_FILES]
        files += sorted(glob.glob(os.path.join(ROOT, "docs", "*.md")))
        bad = []
        for f in files:
            rel = os.path.relpath(f, ROOT)
            raw = read(rel)
            if sum(1 for l in raw.splitlines() if l.lstrip().startswith("```")) % 2:
                bad.append("%s: an unbalanced code fence" % rel)
            text = re.sub(r"`[^`\n]*`", "", outside_fences(raw))
            for m in re.finditer(r"\]\(([^)\s]+)\)", text):
                target = m.group(1)
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, frag = target.partition("#")
                dest = os.path.normpath(os.path.join(os.path.dirname(f), path)) if path else f
                if not os.path.exists(dest):
                    bad.append("%s -> %s" % (rel, target))
                elif frag and dest.endswith(".md") and frag not in anchors(read(os.path.relpath(dest, ROOT))):
                    bad.append("%s -> %s (no such heading)" % (rel, target))
        self.assertEqual(bad, [])


class RepoFiles(unittest.TestCase):
    def test_the_license_is_apache_2_with_its_appendix(self):
        t = read("LICENSE")
        self.assertTrue(t.lstrip().startswith("Apache License"))
        self.assertIn("Version 2.0, January 2004", t[:300])
        for needle in ("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION", "END OF TERMS AND CONDITIONS",
                       "APPENDIX: How to apply the Apache License to your work.", 'Licensed under the Apache License, Version 2.0 (the "License");'):
            self.assertIn(needle, t)

    def test_contributing_has_the_rules_and_every_path_it_names_exists(self):
        t = read("CONTRIBUTING.md")
        for needle in ("python3 tests/fast/test_", "sh tests/run.sh", "podman build", "dev/dev-build.sh", "swarmbox-test-",
                       "git config core.hooksPath dev/hooks", "dev/check.sh", "dev/release.sh", "[Unreleased]", "feat:", "fix:", "test:", "docs:"):
            self.assertIn(needle, t, needle)
        self.assertRegex(t, r"(?i)never .*(live|running) (box|swarmbox)|(live|running) (box|swarmbox).* never|never touch")
        paths = set(re.findall(r"`((?:tests|docs|container|lib|\.github)/[\w./-]+|[\w-]+\.(?:sh|md|py|yml))`", t))
        self.assertTrue(paths)
        for p in sorted(paths):
            if "*" in p or "<" in p or p.startswith("test_"):
                continue
            self.assertTrue(os.path.exists(os.path.join(ROOT, p)), "CONTRIBUTING.md mentions %s, which does not exist" % p)

    def test_the_policy_files_exist_and_the_readme_and_contributing_point_at_them(self):
        contributing = read("CONTRIBUTING.md")
        for name in POLICY_FILES:
            self.assertTrue(read(name).strip(), name)
            self.assertIn(name, contributing, name)
            self.assertIn("(%s)" % name, README, name)


# ---- THIRD_PARTY_NOTICES.md -------------------------------------------------------------------------------------------------------------

def dockerfile_apt_packages(dockerfile):
    """Every package named in an `apt-get install` of the Dockerfile."""
    pkgs = []
    for block in re.findall(r"apt-get install -y ((?:[^\n]*\\\n)*[^\n]*)", dockerfile):
        for w in block.split("&&")[0].replace("\\", " ").split():
            if re.match(r"^[a-z0-9][a-z0-9.+-]*$", w):
                pkgs.append(w)
    return sorted(set(pkgs))


class Notices(unittest.TestCase):
    """The image's contents are in THIRD_PARTY_NOTICES.md with a license and a source: the apt packages (a table row each), the downloaded programs
    and npm packages of the Dockerfile, and every addon (a section each); and in docs/debian-packages.tsv (one line per package)."""

    @classmethod
    def setUpClass(cls):
        cls.text = read("THIRD_PARTY_NOTICES.md")
        cls.dockerfile = read("Dockerfile")

    def test_every_apt_package_has_a_row_with_a_license_and_a_source_and_a_line_in_the_full_list(self):
        pkgs = dockerfile_apt_packages(self.dockerfile)
        self.assertIn("podman", pkgs)
        self.assertIn("libcap2-bin", pkgs)
        listed = {l.split("\t")[0] for l in read("docs", "debian-packages.tsv").split("\n") if l and not l.startswith("#")}
        for p in pkgs:
            with self.subTest(package=p):
                m = re.search(r"^\|\s*`%s`\s*\|(.*)$" % re.escape(p), self.text, re.M)
                self.assertIsNotNone(m, "%s is in the Dockerfile apt list but has no table row in the notices" % p)
                cells = [c.strip() for c in m.group(1).split("|")]
                self.assertGreaterEqual(len(cells), 3)
                self.assertTrue(cells[1], "an empty license cell")
                self.assertRegex(m.group(0), r"https://\S+", "no source URL")
                self.assertIn(p, listed, "not in docs/debian-packages.tsv")

    def test_every_downloaded_program_and_addon_has_a_section_with_a_license_and_a_source(self):
        d, low = self.dockerfile, self.text.lower()
        programs = {"ttyd", "starship", "tmux"}
        for arg in re.findall(r"^ARG (\w+)_VERSION=", d, re.M):
            if arg not in ("CLAUDE_CODE", "OPENCODE", "NODE"):   # the agents are addons; node is the base image tag, not a download
                programs.add(arg.lower().replace("_", "-"))
        programs.update(re.findall(r"npm install -g (@[\w-]+/[\w-]+)(?:@\$\{\w+\})?", d))
        addons = sorted(os.listdir(os.path.join(ROOT, "container", "addons")))
        self.assertTrue({"gcloud", "poetry", "go", "clasp", "gemini"} <= set(addons), addons)
        self.assertIn("chrome-devtools-mcp", programs)
        for name in sorted(programs | {"google-cloud-cli" if a == "gcloud" else a for a in addons}):
            self.assertIn(name.lower(), low, "%s is installed by the image but is not in the notices" % name)
        for name in ("ttyd", "starship", "tmux") + tuple("google cloud cli" if a == "gcloud" else a for a in addons):
            with self.subTest(section=name):
                s = notice_section(self.text, name)
                self.assertRegex(s, r"(?i)license:")
                self.assertRegex(s, r"https://\S+")

    def test_what_could_not_be_checked_is_tagged_not_guessed(self):
        self.assertNotIn("[unverified", self.text)
        self.assertIn("[owner-check:", self.text)
        self.assertIn("[verified:", self.text)


if __name__ == "__main__":
    unittest.main()
