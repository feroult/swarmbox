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

    def test_no_image_manifests_at_all_still_writes_an_empty_tool_ports_and_index(self):
        shutil.rmtree(self.image)
        self.assertEqual(self.link("--system").returncode, 0)
        self.assertEqual(os.path.getsize(os.path.join(self.host, "tool-ports")), 0)
        self.assertEqual(self.read(self.base, "lib", "index"), "")
        self.assertEqual(os.listdir(self.ishims), [])

    def test_invalid_port_entry_is_skipped_with_a_warning(self):
        make_tool(self.image, "odd", PROVIDES='"odd"', PORTS='"abc 9000"')
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertIn("abc", r.stderr)
        self.assertEqual(self.read(self.host, "tool-ports"), "clasp\t43323\nodd\t9000\n")

    def test_idempotent_by_tree_hash_and_no_temp_leftovers(self):
        self.link("--system")
        h1 = (tree_hash(self.base), os.stat(os.path.join(self.ishims, "gcloud"), follow_symlinks=False).st_ino)
        r = self.link("--system")
        self.assertEqual(r.returncode, 0, r.stderr)
        h2 = (tree_hash(self.base), os.stat(os.path.join(self.ishims, "gcloud"), follow_symlinks=False).st_ino)
        self.assertEqual(h1, h2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, "lib"))), ["index", "shims"])
        self.assertEqual(sorted(os.listdir(self.host)), ["tool-ports"])

    def test_removing_a_manifest_removes_its_shims_on_relink(self):
        self.link("--system")
        shutil.rmtree(os.path.join(self.image, "gcloud"))
        self.link("--system")
        self.assertEqual(os.listdir(self.ishims), ["clasp"])
        self.assertEqual(self.read(self.base, "lib", "index"), "clasp clasp\n")

    def test_files_not_generated_by_link_are_left_alone(self):
        os.makedirs(self.ishims)
        with open(os.path.join(self.ishims, "keep.txt"), "w") as f:
            f.write("k")
        os.symlink("/bin/true", os.path.join(self.ishims, "foreign"))
        self.link("--system")
        self.assertEqual(self.read(self.ishims, "keep.txt"), "k")
        self.assertEqual(os.readlink(os.path.join(self.ishims, "foreign")), "/bin/true")

    def test_a_real_file_with_a_command_name_is_not_overwritten(self):
        os.makedirs(self.ishims)
        with open(os.path.join(self.ishims, "bq"), "w") as f:
            f.write("mine")
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertIn("bq", r.stderr)
        self.assertEqual(self.read(self.ishims, "bq"), "mine")
        self.assertNotIn("bq gcloud", self.read(self.base, "lib", "index"))

    def test_a_dangling_stale_shim_that_points_to_the_dispatcher_is_removed(self):
        os.makedirs(self.ishims)
        os.symlink(SHIM, os.path.join(self.ishims, "gone"))
        self.link("--system")
        self.assertFalse(os.path.lexists(os.path.join(self.ishims, "gone")))

    def test_same_level_duplicate_is_reported_exit_1_and_nothing_is_written(self):
        make_tool(self.image, "gcloud2", PROVIDES='"bq"')
        r = self.link("--system")
        self.assertEqual(r.returncode, 1)
        self.assertIn("'bq'", r.stderr)
        self.assertIn("gcloud", r.stderr)
        self.assertFalse(os.path.exists(self.ishims))
        self.assertFalse(os.path.exists(os.path.join(self.base, "lib", "index")))
        self.assertFalse(os.path.exists(os.path.join(self.host, "tool-ports")))

    def test_duplicate_does_not_destroy_an_earlier_good_state(self):
        self.link("--system")
        make_tool(self.image, "gcloud2", PROVIDES='"bq"')
        before = tree_hash(self.base)
        self.assertEqual(self.link("--system").returncode, 1)
        self.assertEqual(tree_hash(self.base), before)
        self.assertTrue(os.path.islink(os.path.join(self.ishims, "bq")))
        self.assertEqual(self.read(self.base, "lib", "index"), "bq gcloud\nclasp clasp\ngcloud gcloud\ngsutil gcloud\n")

    def test_a_manifest_that_does_not_source_is_skipped_and_the_rest_is_linked(self):
        d = os.path.join(self.image, "broken")
        os.makedirs(d)
        with open(os.path.join(d, "tool.conf"), "w") as f:
            f.write("exit 3\n")
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertIn("broken", r.stderr)
        self.assertIn("clasp", os.listdir(self.ishims))

    def test_a_newer_schema_or_a_command_with_a_slash_is_skipped(self):
        make_tool(self.image, "future", PROVIDES='"future"', SCHEMA="2")
        make_tool(self.image, "evil", PROVIDES='"../evil ok"')
        r = self.link("--system")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("future", os.listdir(self.ishims))
        self.assertIn("ok", os.listdir(self.ishims))
        self.assertFalse(os.path.exists(os.path.join(self.base, "lib", "evil")))
        self.assertIn("future", r.stderr)

    def test_link_system_does_not_touch_the_user_level(self):
        make_tool(self.user, "mine", PROVIDES='"mine"')
        self.link("--system")
        self.assertFalse(os.path.exists(self.ushims))

    def test_a_tool_ports_file_with_old_content_is_replaced(self):
        os.makedirs(self.host)
        with open(os.path.join(self.host, "tool-ports"), "w") as f:
            f.write("old\t1\n")
        self.link("--system")
        self.assertEqual(self.read(self.host, "tool-ports"), "clasp\t43323\n")


class LinkUser(Base):
    def test_user_level_shims_and_index_and_no_tool_ports(self):
        make_tool(self.user, "mine", PROVIDES='"mine mine2"', PORTS='"9999"')
        r = self.link("--user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(self.ushims)), ["mine", "mine2"])
        self.assertEqual(os.readlink(os.path.join(self.ushims, "mine")), SHIM)
        self.assertEqual(self.read(self.base, "share", "index"), "mine mine\nmine2 mine\n")
        self.assertFalse(os.path.exists(self.host))  # user-level PORTS never reach tool-ports (6.3)

    def test_link_user_does_not_touch_the_image_level(self):
        make_tool(self.image, "img", PROVIDES='"img"')
        make_tool(self.user, "mine", PROVIDES='"mine"')
        self.link("--user")
        self.assertFalse(os.path.exists(self.ishims))

    def test_link_user_uses_the_workspace_dirs_from_dirs_sh_and_honors_xdg(self):
        ws = os.path.join(self.base, "ws")
        os.makedirs(os.path.join(ws, "xdgdata"))
        cfg = os.path.join(ws, ".config", "swarmbox", "tools")
        make_tool(cfg, "mine", PROVIDES='"mine"')
        env = dict(HOME=ws, SWARMBOX_TEST_USER_TOOLS="", SWARMBOX_TEST_USER_SHIMS="")
        r = self.link("--user", **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(os.path.join(ws, ".local", "share", "swarmbox", "shims", "mine")))
        self.assertEqual(self.read(ws, ".local", "share", "swarmbox", "index"), "mine mine\n")
        # XDG_DATA_HOME moves the shims and the index; the manifests stay under the config home
        r = self.link("--user", XDG_DATA_HOME=os.path.join(ws, "xdgdata"), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(os.path.join(ws, "xdgdata", "swarmbox", "shims", "mine")))

    def test_with_no_manifests_it_succeeds_and_leaves_an_empty_level(self):
        shutil.rmtree(self.user)
        r = self.link("--user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(self.ushims), [])
        self.assertEqual(self.read(self.base, "share", "index"), "")

    def test_relink_removes_the_shim_of_a_removed_user_tool(self):
        make_tool(self.user, "mine", PROVIDES='"mine"')
        self.link("--user")
        shutil.rmtree(os.path.join(self.user, "mine"))
        self.link("--user")
        self.assertEqual(os.listdir(self.ushims), [])

    def test_same_level_duplicate_exits_1_without_half_writing(self):
        make_tool(self.user, "a", PROVIDES='"x y"')
        make_tool(self.user, "b", PROVIDES='"y z"')
        r = self.link("--user")
        self.assertEqual(r.returncode, 1)
        self.assertIn("'y'", r.stderr)
        self.assertFalse(os.path.exists(self.ushims))
        self.assertFalse(os.path.exists(os.path.join(self.base, "share", "index")))

    def test_idempotent_by_tree_hash(self):
        make_tool(self.user, "mine", PROVIDES='"mine"')
        self.link("--user")
        h = tree_hash(self.base)
        self.assertEqual(self.link("--user").returncode, 0)
        self.assertEqual(tree_hash(self.base), h)

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

    def test_user_shim_folder_is_created_without_touching_other_files_in_the_data_dir(self):
        os.makedirs(os.path.join(self.base, "share"))
        with open(os.path.join(self.base, "share", "other"), "w") as f:
            f.write("o")
        self.link("--user")
        self.assertEqual(self.read(self.base, "share", "other"), "o")


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
    def test_real_tools_tree_links_claude_and_tool_ports_is_empty(self):
        shutil.rmtree(self.image)
        shutil.copytree(REAL_TOOLS, self.image)
        r = self.link("--system")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("claude", os.listdir(self.ishims))
        self.assertIn("claude claude\n", self.read(self.base, "lib", "index"))
        p = os.path.join(self.host, "tool-ports")
        self.assertTrue(os.path.isfile(p))
        self.assertNotIn("claude", self.read(p))
        self.assertEqual(os.path.getsize(p), 0)


class Stubs(Base):
    def test_prepare_still_succeeds_and_unknown_subcommand_exits_70(self):
        r = subprocess.run(["bash", TOOL, "prepare"], env=self.env(), capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["bash", TOOL, "bogus"], env=self.env(), capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 70)

    def test_link_needs_exactly_one_known_flag(self):
        for args in (["link"], ["link", "--bogus"], ["link", "--system", "--user"]):
            r = subprocess.run(["bash", TOOL, *args], env=self.env(), capture_output=True, text=True, timeout=20)
            self.assertEqual(r.returncode, 64, args)

    def test_unwritable_host_dir_exits_1(self):
        open(self.host, "w").close()  # a file where the folder should be
        r = self.link("--system")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tool-ports", r.stderr)


if __name__ == "__main__":
    unittest.main()
