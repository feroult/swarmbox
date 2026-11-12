"""The product Dockerfile, checked statically (no build).

The v0.1.0 Dockerfile is retired; nothing here reads it.
Run: python3 tests/test_dockerfile.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def instructions(text):
    """Dockerfile instructions with continuation lines joined; comments dropped."""
    out, cur = [], ""
    for line in text.splitlines():
        if not cur and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if cur and line.lstrip().startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            cur += line.rstrip()[:-1] + " "
        else:
            out.append((cur + line).strip())
            cur = ""
    if cur:
        out.append(cur.strip())
    return out


D = read("Dockerfile")
INS = instructions(D)
CODE = "\n".join(INS)


class BaseAndUser(unittest.TestCase):
    def test_base_image(self):
        froms = [i for i in INS if i.startswith("FROM ")]
        self.assertEqual(len(froms), 1)
        self.assertRegex(froms[0], r"^FROM node:24-trixie-slim$|^FROM node:\$\{NODE_VERSION\}-trixie-slim$")
        if "NODE_VERSION" in froms[0]:
            self.assertIn("ARG NODE_VERSION=24", D)

    def test_fixed_user_is_agent_1000_by_renaming_node(self):
        self.assertIn("usermod -l agent node", CODE)
        self.assertIn("groupmod -n agent node", CODE)
        self.assertIn("usermod -d /home/agent -m agent", CODE)
        self.assertIn("agent ALL=(ALL) NOPASSWD: ALL", CODE)
        self.assertNotRegex(CODE, r"useradd|groupadd")
        users = [i for i in INS if i.startswith("USER ")]
        self.assertEqual(users[-1], "USER agent")
        self.assertIn("WORKDIR /home/agent", INS)

class Pinned(unittest.TestCase):
    def test_downloads_are_checksummed(self):
        for tool in ("ttyd", "starship"):
            self.assertRegex(D, r"ARG %s_VERSION=\d" % tool.upper())
        self.assertGreaterEqual(CODE.count("sha256sum -c"), 2)


class TmuxPinned(unittest.TestCase):
    """tmux is a pinned Debian backport (3.5a of Debian 13 has no pane scrollbar), fetched by checksum with a copy that never goes away."""

    def arg(self, name):
        m = re.search(r"^ARG %s=(\S+)" % name, D, re.M)
        self.assertTrue(m, "no ARG %s" % name)
        return m.group(1)

    def test_it_is_no_longer_in_the_package_list_of_the_base_layer(self):
        first = next(i for i in INS if i.startswith("RUN apt-get update") and re.search(r"\sgit\s", i) and re.search(r"\scurl\s", i))
        self.assertNotRegex(first, r"(^|\s)tmux(\s|$)", "the Debian 13 tmux (3.5a) must not be the one in the image")

    def test_the_version_and_the_hashes_are_pinned_for_both_architectures(self):
        self.assertRegex(self.arg("TMUX_VERSION"), r"^\d+\.\d+[a-z]?-\d+~bpo13\+\d+$")
        for a in ("AMD64", "ARM64"):
            self.assertRegex(self.arg("TMUX_SHA256_" + a), r"^[0-9a-f]{64}$")
            self.assertRegex(self.arg("TMUX_SHA1_" + a), r"^[0-9a-f]{40}$")
        self.assertNotEqual(self.arg("TMUX_SHA256_AMD64"), self.arg("TMUX_SHA256_ARM64"))

    def test_the_install_checks_every_source_and_falls_back_to_the_snapshot(self):
        run = next(i for i in INS if i.startswith("RUN") and "TMUX_VERSION" in i)
        self.assertIn("https://deb.debian.org/debian/pool/main/t/tmux/", run)
        self.assertIn("https://snapshot.debian.org/file/$SHA1", run, "the archive drops the file when backports moves on; the snapshot keeps it")
        self.assertIn("sha256sum -c", run)
        self.assertIn('apt-get install -y --no-install-recommends "/tmp/$F"', run, "dependencies come from Debian 13")
        self.assertRegex(run, r"unsupported architecture")
        self.assertTrue(run.rstrip().endswith("tmux -V"), "the build prints the version it installed")
        # the checksum is checked in the loop, for each source, before the file is kept: a wrong file is never installed
        self.assertLess(run.index("sha256sum -c"), run.index("apt-get install"))

    def test_the_version_in_the_third_party_lists_is_the_one_pinned(self):
        pinned = self.arg("TMUX_VERSION")
        rows = [l.split("\t") for l in read("docs/debian-packages.tsv").splitlines() if l.startswith("tmux\t")]
        self.assertEqual([r[1] for r in rows], [pinned], "docs/debian-packages.tsv")
        notice = [l for l in read("THIRD_PARTY_NOTICES.md").splitlines() if l.startswith("| `tmux` |")]
        self.assertEqual(len(notice), 1)
        self.assertIn("| %s |" % pinned, notice[0], "THIRD_PARTY_NOTICES.md")


class StartupAndLayout(unittest.TestCase):
    def test_entrypoint_and_cmd(self):
        self.assertIn('ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]', INS)
        self.assertIn('CMD ["serve"]', INS)
        self.assertIn("COPY container/entrypoint.sh /usr/local/bin/swarmbox-entrypoint", CODE)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "container", "entrypoint.sh")))

    def test_every_copy_source_exists(self):
        for i in INS:
            if i.startswith("COPY "):
                parts = i.split()[1:]
                parts = [p for p in parts if not p.startswith("--")]
                for src in parts[:-1]:
                    self.assertTrue(os.path.exists(os.path.join(ROOT, src)), "COPY source missing: %s" % src)

class HostHelperArchive(unittest.TestCase):
    """Container/host/ is the helper archive's folder, and swarmbox-install is the entrypoint's `install`."""

    def test_the_host_folder_is_copied_into_the_archive_folder(self):
        self.assertIn("COPY container/host/ /usr/local/share/swarmbox/host/", INS)
        self.assertIn("COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py", INS)

    def test_swarmbox_host_is_executable_and_the_folder_readable(self):
        chmod = [i for i in INS if i.startswith("RUN chmod") and "swarmbox-entrypoint" in i]
        self.assertEqual(len(chmod), 1)
        self.assertRegex(chmod[0], r"chmod 755 /usr/local/share/swarmbox/host/swarmbox-host")
        self.assertRegex(chmod[0], r"chmod -R a\+rX /usr/local/share/swarmbox/host")

class NestedPodman(unittest.TestCase):
    """Every row of the nested Podman settings table is still in the Dockerfile."""

    def test_file_capabilities_instead_of_setuid(self):
        self.assertIn("chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap", CODE)
        self.assertIn("setcap cap_setuid+ep /usr/bin/newuidmap", CODE)
        self.assertIn("setcap cap_setgid+ep /usr/bin/newgidmap", CODE)

class ToolMachinery(unittest.TestCase):
    """The image ships the real tool program, the manifests and the generated shims."""

    def test_link_system_runs_after_every_copy_and_chmod_it_needs(self):
        idx = [n for n, i in enumerate(INS) if "swarmbox-tool link --system" in i]
        self.assertEqual(len(idx), 1)
        for needle in ("COPY container/tools/", "COPY container/scripts/swarmbox-tool.sh", "COPY container/scripts/swarmbox-shim.sh",
                       "COPY container/scripts/dirs.sh"):
            first = [n for n, i in enumerate(INS) if i.startswith(needle)]
            self.assertEqual(len(first), 1, needle)
            self.assertLess(first[0], idx[0], needle)
        self.assertIn("chmod 755", INS[idx[0]])  # same RUN as the chmod, so the link sees executable scripts
        self.assertTrue(INS[idx[0]].startswith("RUN "))

    def test_no_agent_is_installed_and_no_tool_state_is_baked(self):
        # the only install is the WITH_TOOLS loop (class WithTools); nothing named, nothing by default
        installs = [i for i in INS if "swarmbox-tool install" in i]
        self.assertEqual(len(installs), 1)
        self.assertIn('"$t"', installs[0])
        self.assertNotIn("swarmbox-tool run", CODE)
        self.assertNotIn(".local/share/swarmbox", CODE)
        self.assertNotRegex(CODE, r"tools/claude")


def tool_names():
    return sorted(os.listdir(os.path.join(ROOT, "container", "tools")))


class WithTools(unittest.TestCase):
    """The WITH_TOOLS build argument."""

    def run_idx(self):
        idx = [n for n, i in enumerate(INS) if "swarmbox-tool install" in i]
        self.assertEqual(len(idx), 1)
        return idx[0]

    def test_the_run_loops_over_the_comma_list_and_installs_into_the_image_state(self):
        i = INS[self.run_idx()]
        self.assertTrue(i.startswith("RUN "))
        self.assertIn("$WITH_TOOLS", i)
        self.assertIn("tr ',' ' '", i)
        self.assertIn('swarmbox-tool install "$t" --image', i)
        self.assertIn("set -eu", i)  # an unknown name or a failed installer fails the build
        self.assertIn("set -f", i)   # no globbing of a name

    def test_the_core_never_names_a_tool(self):
        names = tool_names()
        self.assertGreaterEqual(len(names), 7)
        for name in names:
            self.assertNotRegex(CODE, r"(?<![\w./-])%s(?![\w-])" % re.escape(name), "the Dockerfile names the tool " + name)
        # and the argument carries no default list
        self.assertNotRegex(D, r"WITH_TOOLS=\"?[a-z]")

if __name__ == "__main__":
    unittest.main(verbosity=2)
