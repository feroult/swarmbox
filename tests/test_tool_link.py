"""Slice 4a.2: `swarmbox-tool link --system` and `link --user` (design 6.2, 6.3, 3.7.1; decisions D2, D18).

Fixture manifests in mktemp directories, passed through the test-only variables of decision log [4a.1] and [4a.2]:
SWARMBOX_TEST_IMAGE_TOOLS, SWARMBOX_TEST_IMAGE_SHIMS (image shim folder; the index is its sibling `index`),
SWARMBOX_TEST_HOST_DIR, SWARMBOX_TEST_USER_TOOLS (manifests) and SWARMBOX_TEST_USER_SHIMS (user shim folder; index sibling).
Without the user overrides, link --user uses dirs.sh with HOME and the XDG variables (tested too).
Run with: python3 tests/test_tool_link.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_tool_manifest import make_tool  # noqa: E402

TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")
REAL_TOOLS = os.path.join(ROOT, "container", "tools")
SHIM = "/usr/local/bin/swarmbox-shim"


def tree_hash(root):
    h = hashlib.sha256()
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for n in sorted(fn + dn):
            p = os.path.join(dp, n)
            h.update(os.path.relpath(p, root).encode())
            if os.path.islink(p):
                h.update(b"L" + os.readlink(p).encode())
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    h.update(b"F" + f.read())
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="tool-link-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.image, self.user = j("image"), j("user")
        self.ishims, self.ushims = j("lib", "shims"), j("share", "shims")
        self.host = j("host")
        os.makedirs(self.image)
        os.makedirs(self.user)

    def env(self, **extra):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.base, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_TOOLS": self.image, "SWARMBOX_TEST_IMAGE_SHIMS": self.ishims,
             "SWARMBOX_TEST_USER_TOOLS": self.user, "SWARMBOX_TEST_USER_SHIMS": self.ushims,
             "SWARMBOX_TEST_HOST_DIR": self.host}
        e.update(extra)
        return e

    def link(self, flag, cwd=None, **extra):
        return subprocess.run(["bash", TOOL, "link", flag], env=self.env(**extra), capture_output=True, text=True,
                              timeout=30, cwd=cwd or self.base)

    def read(self, *p):
        with open(os.path.join(*p)) as f:
            return f.read()



class LinkSystem(Base):
    def setUp(self):
        super().setUp()
        make_tool(self.image, "gcloud", PROVIDES='"gcloud gsutil bq"')
        make_tool(self.image, "clasp", PROVIDES='"clasp"', PORTS='"43323"')

    def test_shims_are_symlinks_to_the_dispatcher_one_per_command(self):
        r = self.link("--system")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(self.ishims)), ["bq", "clasp", "gcloud", "gsutil"])
        for c in os.listdir(self.ishims):
            p = os.path.join(self.ishims, c)
            self.assertTrue(os.path.islink(p))
            self.assertEqual(os.readlink(p), SHIM)

    def test_index_has_one_sorted_command_tool_line_per_command(self):
        self.link("--system")
        self.assertEqual(self.read(self.base, "lib", "index"), "bq gcloud\nclasp clasp\ngcloud gcloud\ngsutil gcloud\n")

    def test_tool_ports_has_a_line_per_ports_entry(self):
        make_tool(self.image, "multi", PROVIDES='"multi"', PORTS='"8001 8002"')
        self.link("--system")
        self.assertEqual(self.read(self.host, "tool-ports"), "clasp\t43323\nmulti\t8001\nmulti\t8002\n")

    def test_no_ports_gives_an_empty_file_that_exists(self):
        shutil.rmtree(os.path.join(self.image, "clasp"))
        self.assertEqual(self.link("--system").returncode, 0)
        p = os.path.join(self.host, "tool-ports")
        self.assertTrue(os.path.isfile(p))
        self.assertEqual(os.path.getsize(p), 0)

    def test_idempotent_by_tree_hash_and_no_temp_leftovers(self):
        self.link("--system")
        h1 = (tree_hash(self.base), os.stat(os.path.join(self.ishims, "gcloud"), follow_symlinks=False).st_ino)
        r = self.link("--system")
        self.assertEqual(r.returncode, 0, r.stderr)
        h2 = (tree_hash(self.base), os.stat(os.path.join(self.ishims, "gcloud"), follow_symlinks=False).st_ino)
        self.assertEqual(h1, h2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, "lib"))), ["index", "shims"])
        self.assertEqual(sorted(os.listdir(self.host)), ["tool-ports"])

    def test_a_real_file_with_a_command_name_is_not_overwritten(self):
        os.makedirs(self.ishims)
        with open(os.path.join(self.ishims, "bq"), "w") as f:
            f.write("mine")
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertIn("bq", r.stderr)
        self.assertEqual(self.read(self.ishims, "bq"), "mine")
        self.assertNotIn("bq gcloud", self.read(self.base, "lib", "index"))

    def test_same_level_duplicate_is_reported_exit_1_and_nothing_is_written(self):
        make_tool(self.image, "gcloud2", PROVIDES='"bq"')
        r = self.link("--system")
        self.assertEqual(r.returncode, 1)
        self.assertIn("'bq'", r.stderr)
        self.assertIn("gcloud", r.stderr)
        self.assertFalse(os.path.exists(self.ishims))
        self.assertFalse(os.path.exists(os.path.join(self.base, "lib", "index")))
        self.assertFalse(os.path.exists(os.path.join(self.host, "tool-ports")))

    def test_a_manifest_that_does_not_source_is_skipped_and_the_rest_is_linked(self):
        d = os.path.join(self.image, "broken")
        os.makedirs(d)
        with open(os.path.join(d, "tool.conf"), "w") as f:
            f.write("exit 3\n")
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertIn("broken", r.stderr)
        self.assertIn("clasp", os.listdir(self.ishims))

class LinkUser(Base):
    def test_user_level_shims_and_index_and_no_tool_ports(self):
        make_tool(self.user, "mine", PROVIDES='"mine mine2"', PORTS='"9999"')
        r = self.link("--user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(self.ushims)), ["mine", "mine2"])
        self.assertEqual(os.readlink(os.path.join(self.ushims, "mine")), SHIM)
        self.assertEqual(self.read(self.base, "share", "index"), "mine mine\nmine2 mine\n")
        self.assertFalse(os.path.exists(self.host))  # user-level PORTS never reach tool-ports (6.3)

    def test_the_same_command_in_both_levels_is_allowed_and_user_wins_on_path(self):
        make_tool(self.image, "img", PROVIDES='"both"')
        make_tool(self.user, "mine", PROVIDES='"both"')
        self.assertEqual(self.link("--system").returncode, 0)
        self.assertEqual(self.link("--user").returncode, 0)
        self.assertEqual(self.read(self.base, "lib", "index"), "both img\n")
        self.assertEqual(self.read(self.base, "share", "index"), "both mine\n")
        # the PATH order of 6.2: the user shim folder comes first, so `both` resolves to the user-level link
        # (the links are dangling here, the dispatcher is not installed on the test machine, so look them up by hand)
        path = [self.ushims, self.ishims]
        first = next(os.path.join(d, "both") for d in path if os.path.lexists(os.path.join(d, "both")))
        self.assertEqual(first, os.path.join(self.ushims, "both"))

class Absence(Base):
    def test_a_project_level_tools_folder_produces_no_shim_index_line_or_port(self):
        proj = os.path.join(self.base, "project")
        os.makedirs(os.path.join(proj, ".swarmbox", "tools"))
        os.makedirs(os.path.join(proj, "tools"))
        for d in (os.path.join(proj, ".swarmbox", "tools"), os.path.join(proj, "tools"), proj):
            make_tool(d, "projtool", PROVIDES='"projcmd"', PORTS='"5555"')
        make_tool(self.image, "img", PROVIDES='"imgcmd"')
        for flag in ("--system", "--user"):
            self.assertEqual(self.link(flag, cwd=proj).returncode, 0)
        self.assertNotIn("projcmd", os.listdir(self.ishims) + os.listdir(self.ushims))
        self.assertNotIn("projcmd", self.read(self.base, "lib", "index") + self.read(self.base, "share", "index"))
        self.assertNotIn("5555", self.read(self.host, "tool-ports"))
        self.assertEqual(self.read(self.host, "tool-ports"), "")


class RealImageTree(Base):
    def test_real_tools_tree_links_claude_and_tool_ports_lists_only_clasp(self):
        shutil.rmtree(self.image)
        shutil.copytree(REAL_TOOLS, self.image)
        r = self.link("--system")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("claude", os.listdir(self.ishims))
        self.assertIn("claude claude\n", self.read(self.base, "lib", "index"))
        p = os.path.join(self.host, "tool-ports")
        self.assertTrue(os.path.isfile(p))
        # 4b.3: clasp is the one shipped tool with a port (design 6.12); no other real tool declares PORTS
        self.assertEqual(self.read(p), "clasp\t43323\n")


if __name__ == "__main__":
    unittest.main()
