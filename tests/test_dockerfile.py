"""Slice 2.1: the product Dockerfile (design 10.1, 10.2, 10.5, D9, D23), checked statically (no build).

The old image is Dockerfile.v0.1.0 (decision [2.1]); build.sh builds that one until Phase 6.
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
        self.assertRegex(froms[0], r"^FROM node:24-slim$|^FROM node:\$\{NODE_VERSION\}-slim$")
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

    def test_no_host_build_arguments(self):
        for word in ("USER_UID", "USER_GID", "HOST_OS"):
            self.assertNotIn(word, D)


class WhatIsNotThere(unittest.TestCase):
    def test_no_agents_or_heavy_tools(self):
        low = CODE.lower()  # instructions only: a comment may say what is absent
        for word in ("claude", "opencode", "gemini", "gcloud", "google-cloud", "clasp", "golang", "go.dev",
                     "poetry", "cloudflared", "anthropic"):
            self.assertNotIn(word, low, word)

    def test_no_init_sh(self):
        self.assertNotRegex(CODE, r"(?<![\w-])init\.sh")  # starship-init.sh is a different file
        self.assertNotIn("init-swarmbox", CODE)

    def test_no_apt_sandbox_override(self):
        self.assertNotIn("APT::Sandbox", D)
        self.assertNotIn("Sandbox::User", D)


class Pinned(unittest.TestCase):
    def test_chrome_devtools_mcp_is_pinned_to_an_exact_version(self):
        m = re.search(r"^ARG CHROME_DEVTOOLS_MCP_VERSION=(\d+\.\d+\.\d+)$", D, re.M)
        self.assertIsNotNone(m, "ARG CHROME_DEVTOOLS_MCP_VERSION=<x.y.z> missing")
        self.assertRegex(CODE, r"npm install -g [^\n]*chrome-devtools-mcp@\$\{CHROME_DEVTOOLS_MCP_VERSION\}")
        self.assertNotRegex(CODE, r"chrome-devtools-mcp@latest")
        self.assertNotRegex(CODE, r"\bnpx\b")

    def test_every_version_arg_has_a_default(self):
        for line in re.findall(r"^ARG (\w*VERSION\w*)(=.*)?$", D, re.M):
            self.assertTrue(line[1], "%s has no default" % line[0])

    def test_downloads_are_checksummed(self):
        for tool in ("ttyd", "starship"):
            self.assertRegex(D, r"ARG %s_VERSION=\d" % tool.upper())
        self.assertGreaterEqual(CODE.count("sha256sum -c"), 2)


class StartupAndLayout(unittest.TestCase):
    def test_entrypoint_and_cmd(self):
        self.assertIn('ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]', INS)
        self.assertIn('CMD ["serve"]', INS)
        self.assertIn("COPY container/entrypoint.sh /usr/local/bin/swarmbox-entrypoint", CODE)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "container", "entrypoint.sh")))

    def test_npm_cache_is_owned_by_agent_without_chown_r(self):
        self.assertIn("ENV NPM_CONFIG_CACHE=/opt/npm-cache", INS)
        self.assertRegex(CODE, r"install -d -o agent -g agent[^&]*/opt/npm-cache")
        self.assertNotRegex(CODE, r"chown -R")
        # the root-run npm install must not write into /opt/npm-cache: it gets its own cache and removes it in the same RUN
        self.assertRegex(CODE, r"npm install -g --cache /tmp/\S+ chrome-devtools-mcp@\$\{CHROME_DEVTOOLS_MCP_VERSION\}[^\n]*rm -rf /tmp/\S+")

    def test_environment(self):
        for env in ("ENV LANG=C.UTF-8", "ENV BROWSER=none", "ENV CHROME_BIN=/usr/bin/chromium",
                    "ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true", "ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium"):
            self.assertIn(env, INS)
        self.assertNotIn("ANTHROPIC_MODEL", D)

    def test_build_index_runs_at_build(self):
        self.assertIn("container/web/build-index.sh", CODE)
        self.assertRegex(CODE, r"RUN [^\n]*build-index\.sh")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "container", "web", "build-index.sh")))

    def test_every_copy_source_exists(self):
        for i in INS:
            if i.startswith("COPY "):
                parts = i.split()[1:]
                parts = [p for p in parts if not p.startswith("--")]
                for src in parts[:-1]:
                    self.assertTrue(os.path.exists(os.path.join(ROOT, src)), "COPY source missing: %s" % src)

    def test_no_file_outside_container_is_copied_except_cloudflare_setup(self):
        for i in INS:
            if i.startswith("COPY "):
                for src in [p for p in i.split()[1:-1] if not p.startswith("--")]:
                    self.assertTrue(src.startswith("container/") or src == "cloudflare-setup.py", src)

    def test_stable_layers_come_before_volatile_ones(self):
        self.assertLess(CODE.index("apt-get install"), CODE.index("COPY container/"))
        self.assertLess(CODE.index("chrome-devtools-mcp@${CHROME_DEVTOOLS_MCP_VERSION}"), CODE.index("COPY container/entrypoint.sh"))


class NestedPodman(unittest.TestCase):
    """Design 10.5: every row of the table is still in the Dockerfile."""

    def test_packages(self):
        for pkg in ("podman", "netavark", "aardvark-dns", "iptables", "uidmap", "libcap2-bin"):
            self.assertRegex(CODE, r"apt-get install[^\n]*\b%s\b" % pkg)

    def test_file_capabilities_instead_of_setuid(self):
        self.assertIn("chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap", CODE)
        self.assertIn("setcap cap_setuid+ep /usr/bin/newuidmap", CODE)
        self.assertIn("setcap cap_setgid+ep /usr/bin/newgidmap", CODE)

    def test_subuid_subgid(self):
        self.assertIn("agent:1001:64535", CODE)
        self.assertIn("> /etc/subuid", CODE)
        self.assertIn("> /etc/subgid", CODE)

    def test_storage_and_containers_conf(self):
        self.assertIn("/etc/containers/storage.conf", CODE)
        self.assertIn('driver = "overlay"', CODE)
        self.assertIn('ignore_chown_errors = "true"', CODE)
        self.assertIn("/etc/containers/containers.conf", CODE)
        for line in ('utsns = "host"', 'cgroup_manager = "cgroupfs"', 'events_logger = "file"',
                     'network_backend = "netavark"'):
            self.assertIn(line, CODE)


class Contents(unittest.TestCase):
    def test_tools_the_image_needs(self):
        for pkg in ("tmux", "chromium", "git", "openssh-client", "jq", "python3", "build-essential", "curl"):
            self.assertRegex(CODE, r"apt-get install[^\n]*\b%s\b" % pkg)
        self.assertIn("/opt/flow", CODE)
        self.assertIn("astral.sh/uv", CODE)
        self.assertIn("/usr/local/bin/ttyd", CODE)
        self.assertIn("/usr/local/bin/starship", CODE)

    def test_layer_hygiene(self):
        for i in INS:
            if i.startswith("RUN ") and "apt-get update" in i:
                self.assertIn("rm -rf /var/lib/apt/lists/*", i)


class ToolMachinery(unittest.TestCase):
    """Slice 4a.5 (design 6.2, 10.2, D2): the image ships the real tool program, the manifests and the generated shims."""

    def test_manifests_and_scripts_are_copied_to_their_places(self):
        self.assertIn("COPY container/tools/ /usr/local/lib/swarmbox/tools/", INS)
        self.assertIn("COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool", INS)
        self.assertIn("COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim", INS)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "container", "tools", "claude", "tool.conf")))

    def test_both_scripts_and_the_installers_are_executable(self):
        chmod = [i for i in INS if i.startswith("RUN ") and "chmod 755" in i and "swarmbox-tool" in i]
        self.assertEqual(len(chmod), 1)
        self.assertIn("/usr/local/bin/swarmbox-tool", chmod[0])
        self.assertIn("/usr/local/bin/swarmbox-shim", chmod[0])
        # the installers and prepare scripts are run by the program: they must be executable and the tree readable
        self.assertRegex(chmod[0], r"/usr/local/lib/swarmbox/tools")

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

    def test_image_shims_are_on_the_path_of_every_process(self):
        self.assertIn("ENV PATH=/usr/local/lib/swarmbox/shims:$PATH", INS)

    def test_no_agent_is_installed_and_no_tool_state_is_baked(self):
        self.assertNotIn("swarmbox-tool install", CODE)
        self.assertNotIn("swarmbox-tool run", CODE)
        self.assertNotIn(".local/share/swarmbox", CODE)
        self.assertNotRegex(CODE, r"tools/claude")


class OldDockerfile(unittest.TestCase):
    def test_v010_dockerfile_is_kept_for_build_sh(self):
        old = read("Dockerfile.v0.1.0")
        self.assertIn("USER_UID", old)
        self.assertIn("@anthropic-ai/claude-code", old)
        self.assertIn("-f Dockerfile.v0.1.0", read("build.sh"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
