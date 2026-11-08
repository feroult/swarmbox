"""Slice 2.1: the product Dockerfile (design 10.1, 10.2, 10.5, D9, D23), checked statically (no build).

The v0.1.0 Dockerfile is retired (decisions [2.1] and [6.2]); nothing here reads it.
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


class HostHelperArchive(unittest.TestCase):
    """Slice 3.5: container/host/ is the helper archive's folder, and swarmbox-init is the entrypoint's `init`."""

    def test_the_host_folder_is_copied_into_the_archive_folder(self):
        self.assertIn("COPY container/host/ /usr/local/share/swarmbox/host/", INS)
        self.assertIn("COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py", INS)

    def test_the_host_copy_comes_before_the_tool_link_that_writes_tool_ports(self):
        self.assertLess(CODE.index("COPY container/host/"), CODE.index("swarmbox-tool link --system"))

    def test_swarmbox_host_is_executable_and_the_folder_readable(self):
        chmod = [i for i in INS if i.startswith("RUN chmod") and "swarmbox-entrypoint" in i]
        self.assertEqual(len(chmod), 1)
        self.assertRegex(chmod[0], r"chmod 755 /usr/local/share/swarmbox/host/swarmbox-host")
        self.assertRegex(chmod[0], r"chmod -R a\+rX /usr/local/share/swarmbox/host")

    def test_swarmbox_init_is_installed_and_executable(self):
        self.assertIn("COPY container/scripts/swarmbox-init.sh /usr/local/bin/swarmbox-init", INS)
        chmod = [i for i in INS if i.startswith("RUN chmod") and "swarmbox-entrypoint" in i][0]
        self.assertIn("/usr/local/bin/swarmbox-init", chmod.split("chmod 755")[1].split("&&")[0])

    def test_the_sources_exist_and_the_templates_are_the_three_shells(self):
        for f in ("container/host/swarmbox-host", "container/host/VERSION", "container/scripts/swarmbox-init.sh"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, f)), f)
        self.assertEqual(sorted(os.listdir(os.path.join(ROOT, "container", "host", "templates"))), ["bash", "fish", "zsh"])

    def test_the_dev_build_copies_the_same_dockerfile(self):
        # dev/dev-build.sh builds a scratch copy of ./Dockerfile with the repository as the context, so the COPY lines above apply
        self.assertIn("$ROOT/$DOCKERFILE", read("dev/dev-build.sh"))
        self.assertIn('podman build $EXTRA -f "$SCRATCH/Dockerfile" -t "$TAG" "$ROOT"', read("dev/dev-build.sh"))


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
        # slice 4b.6: the only install is the WITH_TOOLS loop (class WithTools); nothing named, nothing by default
        installs = [i for i in INS if "swarmbox-tool install" in i]
        self.assertEqual(len(installs), 1)
        self.assertIn('"$t"', installs[0])
        self.assertNotIn("swarmbox-tool run", CODE)
        self.assertNotIn(".local/share/swarmbox", CODE)
        self.assertNotRegex(CODE, r"tools/claude")


def tool_names():
    return sorted(os.listdir(os.path.join(ROOT, "container", "tools")))


class WithTools(unittest.TestCase):
    """Slice 4b.6 (design 6.8, 10.2, D2, D23): the WITH_TOOLS build argument."""

    def run_idx(self):
        idx = [n for n, i in enumerate(INS) if "swarmbox-tool install" in i]
        self.assertEqual(len(idx), 1)
        return idx[0]

    def test_arg_exists_and_defaults_to_empty(self):
        args = [i for i in INS if i.startswith("ARG WITH_TOOLS")]
        self.assertEqual(len(args), 1)
        self.assertIn(args[0], ("ARG WITH_TOOLS=", 'ARG WITH_TOOLS=""', "ARG WITH_TOOLS=''"))

    def test_the_arg_is_declared_after_the_stable_layers(self):
        arg = [n for n, i in enumerate(INS) if i.startswith("ARG WITH_TOOLS")][0]
        for needle in ("RUN apt-get update", "RUN npm install -g",
                       "ARG TTYD_VERSION", "ARG STARSHIP_VERSION"):
            first = [n for n, i in enumerate(INS) if i.startswith(needle)]
            self.assertTrue(first, needle)
            self.assertLess(first[0], arg, needle)

    def test_the_run_loops_over_the_comma_list_and_installs_into_the_image_state(self):
        i = INS[self.run_idx()]
        self.assertTrue(i.startswith("RUN "))
        self.assertIn("$WITH_TOOLS", i)
        self.assertIn("tr ',' ' '", i)
        self.assertIn('swarmbox-tool install "$t" --image', i)
        self.assertIn("set -eu", i)  # an unknown name or a failed installer fails the build
        self.assertIn("set -f", i)   # no globbing of a name

    def test_the_run_is_a_noop_when_the_list_is_empty(self):
        i = INS[self.run_idx()]
        self.assertRegex(i, r"for t in \$\(printf '%s' \"\$WITH_TOOLS\" \| tr ',' ' '\); do")
        self.assertNotRegex(i, r"swarmbox-tool install [^\"]")  # never an install outside the loop
        import subprocess
        r = subprocess.run(["sh", "-c", "WITH_TOOLS=''; " + i[len("RUN "):].replace("swarmbox-tool", "echo CALLED")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        r = subprocess.run(["sh", "-c", "WITH_TOOLS='a, b,c'; " + i[len("RUN "):].replace("swarmbox-tool", "echo CALLED")], capture_output=True, text=True)
        self.assertEqual(r.stdout.split("\n")[:3], ["CALLED install a --image", "CALLED install b --image", "CALLED install c --image"])

    def test_the_install_runs_as_agent_and_the_state_folder_is_created_with_that_owner(self):
        n = self.run_idx()
        # the folder is created owned by agent (no chown -R) before the install, which runs as agent: no root-owned entries
        mk = [k for k, i in enumerate(INS) if "install -d -o agent -g agent" in i and "/opt/swarmbox/tools" in i]
        self.assertEqual(len(mk), 1)
        self.assertLess(mk[0], n)
        self.assertNotIn("chown -R", CODE)
        between = INS[mk[0]:n]
        self.assertIn("USER agent", between)
        self.assertEqual(INS[n + 1], "USER root", "the next instruction restores root for the layers that follow")

    def test_the_npm_cache_rule_is_respected(self):
        n = self.run_idx()
        env = [k for k, i in enumerate(INS) if i == "ENV NPM_CONFIG_CACHE=/opt/npm-cache"]
        self.assertEqual(len(env), 1)
        self.assertLess(env[0], n)
        self.assertNotIn("/opt/npm-cache", INS[n])
        self.assertNotIn("npm", INS[n])

    def test_it_comes_after_the_tool_machinery_it_needs(self):
        n = self.run_idx()
        link = [k for k, i in enumerate(INS) if "swarmbox-tool link --system" in i][0]
        self.assertLess(link, n)

    def test_the_core_never_names_a_tool(self):
        names = tool_names()
        self.assertGreaterEqual(len(names), 7)
        for name in names:
            self.assertNotRegex(CODE, r"(?<![\w./-])%s(?![\w-])" % re.escape(name), "the Dockerfile names the tool " + name)
        # and the argument carries no default list
        self.assertNotRegex(D, r"WITH_TOOLS=\"?[a-z]")

    def test_the_built_image_ships_no_tool_install_by_default(self):
        # the loop is the only writer of /opt/swarmbox/tools, and its default input is empty
        self.assertEqual(len([i for i in INS if "/opt/swarmbox/tools" in i and "install -d" not in i]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
