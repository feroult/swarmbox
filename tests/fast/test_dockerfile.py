"""The product Dockerfile checked statically (no build), and the data of the image smoke test that follows the addons of the repository.

The Dockerfile is only built by CI and by dev/dev-build.sh, so each invariant a build would break late is checked here: the pins and checksums, the
user, the order of the addon wiring, the files that COPY needs. The smoke test (tests/slow/smoke_image.py, CI only) lists each addon's commands: an
addon added without its line there would fail only on the first image build.
Run: python3 tests/fast/test_dockerfile.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
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


class Image(unittest.TestCase):
    def test_one_pinned_base_and_the_fixed_user_agent_1000_made_by_renaming_node(self):
        froms = [i for i in INS if i.startswith("FROM ")]
        self.assertEqual(len(froms), 1)
        self.assertRegex(froms[0], r"^FROM node:24-trixie-slim$|^FROM node:\$\{NODE_VERSION\}-trixie-slim$")
        if "NODE_VERSION" in froms[0]:
            self.assertIn("ARG NODE_VERSION=24", D)
        for needle in ("usermod -l agent node", "groupmod -n agent node", "usermod -d /home/agent -m agent", "agent ALL=(ALL) NOPASSWD: ALL"):
            self.assertIn(needle, CODE)
        self.assertNotRegex(CODE, r"useradd|groupadd")
        self.assertEqual([i for i in INS if i.startswith("USER ")][-1], "USER agent")
        self.assertIn("WORKDIR /home/agent", INS)

    def test_every_module_the_web_studio_imports_is_copied_into_the_image(self):
        # file-preview.mjs was imported by server.mjs but missing from the COPY: the image built, and the web studio crashed on start (ERR_MODULE_NOT_FOUND)
        web = os.path.join(ROOT, "container", "web", "herdr")
        copied = " ".join(i for i in instructions(read("Dockerfile")) if i.startswith("COPY"))
        for name in ("server.mjs", "cockpit.mjs", "hc-client.mjs", "file-preview.mjs"):
            with open(os.path.join(web, name), encoding="utf-8") as f:
                for dep in re.findall(r"from\s+['\"]\./([\w.-]+\.mjs)['\"]", f.read()):
                    self.assertIn("container/web/herdr/" + dep, copied, name + " imports " + dep + ", which the Dockerfile does not COPY")

    def test_entrypoint_cmd_and_every_copy_source(self):
        self.assertIn('ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]', INS)
        self.assertIn('CMD ["serve"]', INS)
        self.assertIn("COPY container/entrypoint.sh /usr/local/bin/swarmbox-entrypoint", CODE)
        for i in INS:
            if i.startswith("COPY "):
                for src in [p for p in i.split()[1:] if not p.startswith("--")][:-1]:
                    self.assertTrue(os.path.exists(os.path.join(ROOT, src)), "COPY source missing: %s" % src)

    def test_every_script_copied_to_usr_local_bin_is_made_executable_and_attach_is_one(self):
        copied = [i.split()[-1] for i in INS if i.startswith("COPY ") and i.split()[-1].startswith("/usr/local/bin/")]
        self.assertIn("/usr/local/bin/swarmbox-attach", copied)
        run = [i for i in INS if i.startswith("RUN chmod 644") and "swarmbox-entrypoint" in i]
        self.assertEqual(len(run), 1)
        m = re.search(r"chmod 755 ((?:/\S+\s+)+)", run[0] + " ")
        self.assertTrue(m)
        for dst in copied:
            self.assertIn(dst, m.group(1).split(), "not made executable: %s" % dst)

    def test_the_host_helper_archive_folder_is_copied_readable_with_the_host_script_executable(self):
        self.assertIn("COPY container/host/ /usr/local/share/swarmbox/host/", INS)
        self.assertIn("COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py", INS)
        chmod = [i for i in INS if i.startswith("RUN chmod") and "swarmbox-entrypoint" in i]
        self.assertEqual(len(chmod), 1)
        self.assertRegex(chmod[0], r"chmod 755 /usr/local/share/swarmbox/host/swarmbox-host")
        self.assertRegex(chmod[0], r"chmod -R a\+rX /usr/local/share/swarmbox/host")

    def test_nested_podman_uses_file_capabilities_instead_of_setuid(self):
        self.assertIn("chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap", CODE)
        self.assertIn("setcap cap_setuid+ep /usr/bin/newuidmap", CODE)
        self.assertIn("setcap cap_setgid+ep /usr/bin/newgidmap", CODE)


class Pins(unittest.TestCase):
    """starship and herdr are fetched by checksum; herdr (herdr-core) is the only multiplexer, so neither tmux nor ttyd is in the image."""

    def arg(self, name):
        m = re.search(r"^ARG %s=(\S+)" % name, D, re.M)
        self.assertTrue(m, "no ARG %s" % name)
        return m.group(1)

    def test_downloads_are_pinned_and_checksummed(self):
        for prog in ("STARSHIP", "HERDR_CORE", "HERDR"):
            self.assertRegex(self.arg(prog + "_VERSION"), r"^\d")
        for a in ("AMD64", "ARM64"):
            self.assertRegex(self.arg("HERDR_CORE_SHA256_" + a), r"^[0-9a-f]{64}$")
            self.assertRegex(self.arg("HERDR_SHA256_" + a), r"^[0-9a-f]{64}$")
        self.assertGreaterEqual(CODE.count("sha256sum -c"), 3)

    def test_neither_tmux_nor_ttyd_is_installed(self):
        self.assertNotRegex(D, r"(?i)\btmux\b")
        self.assertNotRegex(D, r"(?i)\bttyd\b")
        self.assertIn("ln -sf /usr/local/bin/herdr-core /usr/local/bin/hc", CODE)


class Addons(unittest.TestCase):
    def addon_run(self):
        idx = [n for n, i in enumerate(INS) if "swarmbox-addon install" in i]
        self.assertEqual(len(idx), 1, "the only install is the WITH_ADDONS loop")
        return idx[0]

    def test_link_system_runs_after_every_copy_and_chmod_it_needs(self):
        idx = [n for n, i in enumerate(INS) if "swarmbox-addon link --system" in i]
        self.assertEqual(len(idx), 1)
        for needle in ("COPY container/addons/", "COPY container/scripts/swarmbox-addon.sh", "COPY container/scripts/swarmbox-shim.sh",
                       "COPY container/scripts/dirs.sh"):
            first = [n for n, i in enumerate(INS) if i.startswith(needle)]
            self.assertEqual(len(first), 1, needle)
            self.assertLess(first[0], idx[0], needle)
        self.assertIn("chmod 755", INS[idx[0]])  # same RUN as the chmod, so the link sees executable scripts
        self.assertTrue(INS[idx[0]].startswith("RUN "))

    def test_with_addons_loops_over_the_comma_list_and_nothing_is_baked_by_default(self):
        run = INS[self.addon_run()]
        self.assertTrue(run.startswith("RUN "))
        for needle in ("$WITH_ADDONS", "tr ',' ' '", 'swarmbox-addon install "$t" --image',
                       "set -eu",   # an unknown name or a failed installer fails the build
                       "set -f"):   # no globbing of a name
            self.assertIn(needle, run)
        self.assertNotIn("swarmbox-addon run", CODE)
        self.assertNotIn(".local/share/swarmbox", CODE)
        self.assertNotRegex(CODE, r"addons/claude")
        self.assertNotRegex(D, r"WITH_ADDONS=\"?[a-z]", "the argument carries no default list")

    def test_the_core_never_names_an_addon(self):
        names = addon_names()
        self.assertGreaterEqual(len(names), 7)
        for name in names:
            self.assertNotRegex(CODE, r"(?<![\w./-])%s(?![\w-])" % re.escape(name), "the Dockerfile names the addon " + name)


def addon_names():
    return sorted(os.listdir(os.path.join(ROOT, "container", "addons")))


class SmokeData(unittest.TestCase):
    def test_every_addon_has_its_commands_in_the_smoke_test_and_the_bus_and_tabs_are_checked(self):
        src = read("tests/slow/smoke_image.py")
        ns = {}
        exec(re.search(r"ADDON_COMMANDS = \{.*?\}\n", src, re.S).group(0), ns)
        commands = ns["ADDON_COMMANDS"]
        found = {}
        for name in addon_names():
            text = read("container/addons/%s/addon.conf" % name)
            m = re.search(r'^COMMANDS="([^"]*)"', text, re.M)
            self.assertIsNotNone(m, "%s has no COMMANDS" % name)
            found[re.search(r"^NAME=(\S+)", text, re.M).group(1)] = m.group(1).split()
        self.assertEqual(commands, found)
        box_step = src.split("def step_box_commands")[1].split("def step_addon_shim")[0]
        self.assertIn("swarmbox-bus", box_step)
        self.assertIn("swarmbox-tabs", box_step)
        self.assertIn("step_box_commands", src.split("STEPS = [")[1])


if __name__ == "__main__":
    unittest.main()
