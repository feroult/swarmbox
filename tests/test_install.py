"""The two installers: `podman run --rm IMAGE install | sh` (container/scripts/swarmbox-install.sh) and install.sh at the repository root.

Both end in `swarmbox setup`, which the real script runs against the shared FakePodman: Podman's version answers, and
`run --rm IMAGE host-helper` writes a tar archive built in Python. HOME, XDG_*, SWARMBOX_BIN_DIR and every folder are mktemp folders
(the real home is never touched), and downloads are file:// URLs, never the network.
Run: python3 tests/test_install.py
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_IMAGE_REPO, FakePodman, make_archive, read_defaults  # noqa: E402

INSTALLER = os.path.join(ROOT, "container", "scripts", "swarmbox-install.sh")
HOST_DIR = os.path.join(ROOT, "container", "host")
INSTALL_SH = os.path.join(ROOT, "install.sh")
SCRIPT = os.path.join(HOST_DIR, "swarmbox-host")
with open(os.path.join(HOST_DIR, "VERSION")) as _f:
    VERSION = _f.read().strip()
IMG = "localhost/swarmbox-test-image:local"
TOOLS = ["sh", "dash", "bash", "cat", "rm", "mkdir", "rmdir", "mv", "chmod", "mktemp", "sed", "tr", "head", "tail", "grep", "cut",
         "uname", "dirname", "basename", "wc", "tar", "cp", "sort", "id", "true", "false", "sleep", "touch", "date", "stat", "find",
         "sha256sum", "printf", "env", "ls", "readlink", "kill"]
OLD_BLOCK = "alias x=y\n# >>> swarmbox 2.0.0 >>>\nswarmbox() { :; }\n# <<< swarmbox 2.0.0 <<<\n"


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-install."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.home)
        os.makedirs(self.tmp + "/tools")
        for t in TOOLS:
            p = shutil.which(t)
            if p:
                os.symlink(p, os.path.join(self.tmp, "tools", t))
        archive = os.path.join(self.tmp, "image.tar")
        make_archive(archive, version=VERSION)
        self.fp = FakePodman({"version": {"stdout": "4.3.1\n"}, "run": {"stdout_file": archive}}).__enter__()
        self.addCleanup(self.fp.__exit__)

    def env(self, path=None, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_"))}
        e.update({"HOME": self.home, "SWARMBOX_BIN_DIR": self.bin, "LC_ALL": "C", "PATH": path or self.fp.env()["PATH"]})
        e.pop("SHELL", None)
        e.update(extra)
        return e

    def installer_text(self, *args, containerenv=None, **kw):
        env = {"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": HOST_DIR,
               "SWARMBOX_TEST_CONTAINERENV": containerenv or os.path.join(self.tmp, "no-containerenv")}
        r = subprocess.run(["sh", INSTALLER, *args], env=env, capture_output=True, text=True, **kw)
        return r

    def containerenv(self, image):
        p = os.path.join(self.tmp, "containerenv")
        with open(p, "w") as f:
            f.write('engine="podman-4.9"\nname="x"\nid="abc"\nimage="%s"\nimageid="def"\nrootless=1\n' % image)
        return p

    def pipe_to_sh(self, text, **env):
        """The installer the way users run it: its text on the standard input of sh."""
        return subprocess.run(["sh"], input=text, env=self.env(**env), capture_output=True, text=True, cwd=self.tmp)

    def config(self):
        p = os.path.join(self.home, ".config", "swarmbox", "config")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return f.read()

    def installed(self):
        return os.path.join(self.bin, "swarmbox")


class InstallerTextTest(Base):
    def test_it_prints_a_sh_script_that_carries_the_script_exactly(self):
        r = self.installer_text("--image", IMG, "--with", "claude")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(r.stdout.startswith("#!/bin/sh\n"))
        with open(os.path.join(self.tmp, "inst.sh"), "w") as f:
            f.write(r.stdout)
        self.assertEqual(subprocess.run(["sh", "-n", os.path.join(self.tmp, "inst.sh")]).returncode, 0)
        head, rest = r.stdout.split("<<'SWARMBOX_SCRIPT_END'\n", 1)
        body = rest.split("\nSWARMBOX_SCRIPT_END\n", 1)[0] + "\n"
        self.assertEqual(body.encode(), read_bytes(SCRIPT))
        self.assertIn("IMAGE='%s'" % IMG, head)
        self.assertIn("WITH='claude'", head)

    def test_the_same_arguments_print_the_same_text_and_nothing_is_written(self):
        a = self.installer_text("--with", "claude", "--image", IMG)
        b = self.installer_text("--with", "claude", "--image", IMG)
        self.assertEqual(a.stdout, b.stdout)
        self.assertFalse(os.path.exists(self.bin))
        self.assertEqual(os.listdir(self.home), [])

    def test_the_image_is_the_one_podman_recorded_for_the_container(self):
        r = self.installer_text("--with", "claude", containerenv=self.containerenv("localhost/swarmbox-test-local:local"))
        self.assertIn("IMAGE='localhost/swarmbox-test-local:local'", r.stdout)

    def test_image_flag_wins_over_the_container_name(self):
        r = self.installer_text("--image", "x/y:1", containerenv=self.containerenv("localhost/other:2"))
        self.assertIn("IMAGE='x/y:1'", r.stdout)

    def test_without_either_it_is_the_default_repository_at_the_image_version(self):
        r = self.installer_text()
        self.assertIn("did not tell this container the image", r.stderr)
        if "<" in DEFAULT_IMAGE_REPO:
            # the repository is still a placeholder: no installer is printed, the message asks for --image
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(r.stdout, "")
            self.assertIn("--image", r.stderr)
            return
        self.assertIn("IMAGE='%s:%s'" % (DEFAULT_IMAGE_REPO, VERSION), r.stdout)
        self.assertIn("WITH=''", r.stdout)

    def test_values_are_quoted_for_sh(self):
        r = self.installer_text("--with", "a'b $(id) `x`", "--image", "r/i:1")
        self.assertIn("WITH='a'\\''b $(id) `x`'", r.stdout)

    def test_bad_arguments_are_exit_2_and_print_no_installer(self):
        for args in (["--image", "-x"], ["--with"], ["--nope"], ["extra"], ["--with", "a\nb"]):
            with self.subTest(args=args):
                r = self.installer_text(*args)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertTrue(r.stderr.startswith("swarmbox install: "))

    def test_a_script_that_holds_the_end_marker_is_refused(self):
        d = os.path.join(self.tmp, "host")
        shutil.copytree(HOST_DIR, d)
        with open(os.path.join(d, "swarmbox-host"), "a") as f:
            f.write("SWARMBOX_SCRIPT_END\n")
        r = subprocess.run(["sh", INSTALLER, "--image", IMG], env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": d},
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (3, ""))

    def test_help(self):
        r = self.installer_text("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("podman run --rm IMAGE install", r.stdout)


class InstallRunTest(Base):
    def run_installer(self, *args, **env):
        return self.pipe_to_sh(self.installer_text("--image", IMG, *args).stdout, **env)

    def test_it_writes_the_script_mode_755_the_support_files_and_the_config(self):
        r = self.run_installer("--with", "claude,go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_bytes(self.installed()), read_bytes(SCRIPT))
        self.assertEqual(stat.S_IMODE(os.stat(self.installed()).st_mode), 0o755)
        self.assertEqual(sorted(os.listdir(self.bin)), ["swarmbox"], "no temporary file is left")
        support = os.path.join(self.home, ".local", "share", "swarmbox", "host")
        self.assertEqual(sorted(set(os.listdir(support)) - {"calls"}), ["DEFAULTS", "VERSION", "cloudflare-setup.py", "tool-ports"])
        cfg = self.config()
        self.assertIn("IMAGE=%s\n" % IMG, cfg)
        self.assertIn("WITH=claude,go\n", cfg)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.home, ".config", "swarmbox", "config")).st_mode), 0o600)
        self.assertEqual([c for c in self.fp.calls() if c[0] == "run"], [["run", "--rm", IMG, "host-helper"]])
        self.assertIn("Next: open a new terminal and run `swarmbox`", r.stdout)

    def test_without_tools_no_with_line_is_written(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertNotIn("WITH", self.config())

    def test_the_installed_script_works(self):
        self.run_installer("--with", "claude")
        for args, want in ((["version"], VERSION + "\n"), (["config", "get", "IMAGE"], IMG + "\n"), (["config", "get", "WITH"], "claude\n")):
            r = subprocess.run([self.installed(), *args], env=self.env(), capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, want, ""), args)

    def test_running_it_again_changes_nothing_that_was_right(self):
        self.assertEqual(self.run_installer("--with", "claude").returncode, 0)
        before = (read_bytes(self.installed()), self.config(), os.stat(self.installed()).st_mode)
        r = self.run_installer("--with", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((read_bytes(self.installed()), self.config(), os.stat(self.installed()).st_mode), before)
        self.assertNotIn("installer asked", r.stderr)
        self.assertEqual(sorted(os.listdir(self.bin)), ["swarmbox"])

    def test_a_different_value_on_a_rerun_is_reported_once_and_never_overwrites(self):
        self.run_installer("--with", "claude")
        r = self.run_installer("--with", "gemini")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the installer asked for WITH=gemini, the config says WITH=claude; run `swarmbox config set WITH gemini`", r.stderr)
        self.assertIn("WITH=claude\n", self.config())
        self.assertNotIn("installer asked", self.run_installer("--with", "gemini").stderr)

    def test_it_replaces_an_older_script_by_a_rename(self):
        os.makedirs(self.bin)
        with open(self.installed(), "w") as f:
            f.write("#!/bin/sh\necho old\n")
        ino = os.stat(self.installed()).st_ino
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertNotEqual(os.stat(self.installed()).st_ino, ino)
        self.assertEqual(read_bytes(self.installed()), read_bytes(SCRIPT))

    def test_a_failure_before_the_rename_leaves_the_old_script_and_no_temporary_file(self):
        os.makedirs(self.bin)
        with open(self.installed(), "w") as f:
            f.write("#!/bin/sh\necho old\n")
        shim = os.path.join(self.tmp, "shim")
        os.mkdir(shim)
        with open(os.path.join(shim, "chmod"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(shim, "chmod"), 0o755)
        r = self.run_installer(PATH=shim + os.pathsep + self.fp.env()["PATH"])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read_bytes(self.installed()), b"#!/bin/sh\necho old\n")
        self.assertEqual(os.listdir(self.bin), ["swarmbox"])

    def test_path_advice_only_when_the_folder_is_not_in_path(self):
        r = self.run_installer()
        self.assertIn("%s is not in your PATH" % self.bin, r.stdout)
        self.assertIn("export PATH=", r.stdout)
        self.assertIn("fish_add_path %s" % self.bin, r.stdout)
        r = self.run_installer(PATH=self.bin + os.pathsep + self.fp.env()["PATH"])
        self.assertNotIn("not in your PATH", r.stdout)

    def test_an_old_function_block_is_found_and_reported_but_never_edited(self):
        rcs = {".bashrc": OLD_BLOCK, ".zshrc": "# nothing here\n", ".config/fish/config.fish": "function swarmbox\nend\n# >>> swarmbox 2.0.0 >>>\n"}
        for rel, text in rcs.items():
            p = os.path.join(self.home, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        before = {rel: (read_bytes(os.path.join(self.home, rel)), os.stat(os.path.join(self.home, rel)).st_mtime_ns) for rel in rcs}
        r = self.run_installer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("an old swarmbox shell function is still in:"), 1)
        line = [ln for ln in r.stderr.splitlines() if "still in:" in ln][0]
        self.assertIn(os.path.join(self.home, ".bashrc"), line)
        self.assertIn("config.fish", line)
        self.assertNotIn(".zshrc", line)
        self.assertIn("delete that block", r.stderr)
        after = {rel: (read_bytes(os.path.join(self.home, rel)), os.stat(os.path.join(self.home, rel)).st_mtime_ns) for rel in rcs}
        self.assertEqual(after, before)

    def test_no_rc_file_is_created_or_touched_and_no_warning_without_the_block(self):
        r = self.run_installer()
        self.assertNotIn("old swarmbox shell function", r.stderr)
        for rel in (".bashrc", ".zshrc", ".profile", ".bash_profile", ".config/fish"):
            self.assertFalse(os.path.exists(os.path.join(self.home, rel)), rel)

    def test_podman_older_than_4_3_is_exit_3_and_nothing_else_is_written(self):
        archive = os.path.join(self.tmp, "image.tar")
        self.fp.configure({"version": {"stdout": "4.2.1\n"}, "run": {"stdout_file": archive}})
        r = self.run_installer()
        self.assertEqual(r.returncode, 3)
        self.assertIn("Podman 4.2 found, 4.3 or newer is required", r.stderr)
        self.assertIsNone(self.config())
        self.assertEqual([c for c in self.fp.calls() if c[0] == "run"], [])

    def test_podman_4_10_is_newer_than_4_3(self):
        archive = os.path.join(self.tmp, "image.tar")
        self.fp.configure({"version": {"stdout": "4.10.0\n"}, "run": {"stdout_file": archive}})
        self.assertEqual(self.run_installer().returncode, 0)

    def test_podman_missing_is_exit_3_with_the_advice(self):
        r = self.run_installer(PATH=os.path.join(self.tmp, "tools"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("Podman is not installed", r.stderr)
        self.assertIn("brew install podman", r.stderr)
        self.assertIsNone(self.config())

    def test_a_failing_image_leaves_no_support_folder_and_no_config(self):
        self.fp.configure({"version": {"stdout": "4.3.1\n"}, "run": {"exit": 125, "stderr": "Error: no route to host\n"}})
        r = self.run_installer()
        self.assertEqual(r.returncode, 3)
        self.assertIn("no route to host", r.stderr)
        self.assertIsNone(self.config())
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "share", "swarmbox", "host")))
        self.assertEqual(os.listdir(os.path.join(self.home, ".local", "share", "swarmbox")), [])

    def test_the_bin_folder_is_made_when_missing(self):
        self.assertFalse(os.path.exists(self.bin))
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertTrue(os.path.isdir(self.bin))

    def test_the_default_bin_folder_is_home_local_bin(self):
        env = self.env()
        env.pop("SWARMBOX_BIN_DIR")
        r = subprocess.run(["sh"], input=self.installer_text("--image", IMG).stdout, env=env, capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".local", "bin", "swarmbox")))


class InstallShTest(Base):
    def release(self, version=VERSION, script=None, sha=None):
        d = os.path.join(self.tmp, "release")
        os.makedirs(d, exist_ok=True)
        data = script if script is not None else read_bytes(SCRIPT)
        with open(os.path.join(d, "swarmbox"), "wb") as f:
            f.write(data)
        with open(os.path.join(d, "swarmbox.sha256"), "w") as f:
            f.write("%s  swarmbox\n" % (sha or hashlib.sha256(data).hexdigest()))
        return "file://" + d

    def run_sh(self, *args, url=None, **env):
        return subprocess.run(["sh", INSTALL_SH, *args], env=self.env(SWARMBOX_RELEASE_URL=url or self.release(), **env),
                              capture_output=True, text=True, cwd=self.tmp, input="")

    def test_it_installs_the_verified_script_and_does_the_setup(self):
        r = self.run_sh("--version", VERSION, "--image", IMG, "--with", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_bytes(self.installed()), read_bytes(SCRIPT))
        self.assertEqual(stat.S_IMODE(os.stat(self.installed()).st_mode), 0o755)
        self.assertEqual(sorted(os.listdir(self.bin)), ["swarmbox"])
        self.assertIn("IMAGE=%s\n" % IMG, self.config())
        self.assertIn("WITH=claude\n", self.config())

    def test_without_version_it_asks_the_script_and_the_image_is_repo_colon_version(self):
        r = self.run_sh()
        # the default repository holds the <org> placeholder, which is not an image reference: setup says so, the script is in place
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("is not an image reference", r.stderr)
        self.assertIn("%s:%s" % (DEFAULT_IMAGE_REPO, VERSION), r.stderr)
        self.assertEqual(read_bytes(self.installed()), read_bytes(SCRIPT))

    def test_a_checksum_that_does_not_match_installs_nothing(self):
        r = self.run_sh("--image", IMG, url=self.release(sha="0" * 64))
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum", r.stderr)
        self.assertEqual(os.listdir(self.bin), [])
        self.assertIsNone(self.config())

    def test_a_tampered_script_installs_nothing_and_leaves_the_old_one(self):
        os.makedirs(self.bin)
        with open(self.installed(), "w") as f:
            f.write("old\n")
        url = self.release(sha=hashlib.sha256(read_bytes(SCRIPT)).hexdigest(), script=b"#!/bin/sh\necho evil\n")
        r = self.run_sh("--image", IMG, url=url)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(read_bytes(self.installed()), b"old\n")
        self.assertEqual(os.listdir(self.bin), ["swarmbox"])

    def test_a_missing_download_or_checksum_installs_nothing(self):
        r = self.run_sh("--image", IMG, url="file://" + os.path.join(self.tmp, "nowhere"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot download", r.stderr)
        self.assertEqual(os.listdir(self.bin), [])
        url = self.release()
        os.unlink(url[len("file://"):] + "/swarmbox.sha256")
        r = self.run_sh("--image", IMG, url=url)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(os.listdir(self.bin), [])

    def test_the_download_address_comes_from_the_repository_and_the_version(self):
        shim = os.path.join(self.tmp, "shim")
        os.mkdir(shim)
        log = os.path.join(self.tmp, "curl.log")
        with open(os.path.join(shim, "curl"), "w") as f:
            f.write('#!/bin/sh\nfor a; do last=$a; done\necho "$last" >> "%s"\nexit 22\n' % log)
        os.chmod(os.path.join(shim, "curl"), 0o755)
        env = self.env(PATH=shim + os.pathsep + self.fp.env()["PATH"])
        for args, base in ((["--version", "2.1.3"], "download/v2.1.3"), ([], "latest/download")):
            subprocess.run(["sh", INSTALL_SH, *args], env=env, capture_output=True, text=True, cwd=self.tmp, input="")
            with open(log) as f:
                want = "https://github.com/%s/releases/%s/swarmbox" % (DEFAULT_IMAGE_REPO.split("/", 1)[1], base)
                self.assertEqual(f.read().splitlines()[-1], want)

    def test_bad_arguments_are_refused_before_any_download(self):
        for args in (["--version", "x"], ["--version", "2.0.0;id"], ["--image", "a b"], ["--nope", "1"], ["--with"]):
            with self.subTest(args=args):
                r = self.run_sh(*args)
                self.assertEqual(r.returncode, 1)
                self.assertFalse(os.path.exists(self.bin))

    def test_podman_missing_is_refused_before_any_download(self):
        r = subprocess.run(["sh", INSTALL_SH, "--image", IMG], env=self.env(PATH=os.path.join(self.tmp, "tools"), SWARMBOX_RELEASE_URL=self.release()),
                           capture_output=True, text=True, cwd=self.tmp, input="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Podman is not installed", r.stderr)
        self.assertFalse(os.path.exists(self.bin))

    def test_it_is_short_and_edits_no_startup_file(self):
        with open(INSTALL_SH) as f:
            text = f.read()
        self.assertLessEqual(len(text.splitlines()), 60)
        for rc in (".bashrc", ".zshrc", "config.fish", ".profile"):
            self.assertNotIn(rc, text)

    def test_its_repository_is_the_one_of_the_defaults_file(self):
        with open(INSTALL_SH) as f:
            self.assertIn("REPO='%s'\n" % read_defaults()["SWARMBOX_DEFAULT_IMAGE_REPO"], f.read())

    def test_it_runs_twice_with_the_same_result(self):
        self.assertEqual(self.run_sh("--image", IMG, "--with", "claude").returncode, 0)
        before = (read_bytes(self.installed()), self.config())
        r = self.run_sh("--image", IMG, "--with", "claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((read_bytes(self.installed()), self.config()), before)


if __name__ == "__main__":
    unittest.main()
