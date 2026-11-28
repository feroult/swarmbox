"""How the web server decides on the voice front, and how the addon follows `swarmbox update`.

Real programs: container/scripts/swarmbox-web.sh with the real herdr backend (container/scripts/mux/herdr.sh) over a fake hc, a fake web
server and a fake `swarmbox-voice` that record their arguments, the real
swarmbox-addon.sh (its `where` command and `prepare`) over the real manifests of container/addons, and the real voice prepare.sh. Everything
lives in a mktemp tree; nothing is served. Run with: python3 -W error tests/fast/test_voice_web.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import voice_support  # noqa: E402
from helpers import ROOT  # noqa: E402

ADDON_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
WEB = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
MUX_DIR = os.path.join(ROOT, "container", "scripts", "mux")
ADDONS = os.path.join(ROOT, "container", "addons")
VOICE = voice_support.VOICE
FAKE_VOICE = '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_DIR/voice.argv"\n'


def read(path):
    with open(path) as f:
        return f.read()


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


# a herdr-core that is up with one live terminal, and a web server that records its arguments
FAKE_HC = '#!/bin/sh\ncase "$1" in server) exit 0 ;; ls) echo \'[{"address":"t1","state":"live"}]\' ;; *) echo \'{"address":"t1"}\' ;; esac\n'
FAKE_SERVER = '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_DIR/server.argv"\n'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="voice-web-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        j = lambda *p: os.path.join(self.tmp, *p)  # noqa: E731
        self.home, self.fake, self.lib, self.run_dir = j("home"), j("fake"), j("lib"), j("run")
        for d in (self.home, self.fake, self.lib, self.run_dir):
            os.makedirs(d)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        os.symlink(MUX_DIR, os.path.join(self.lib, "mux"))
        write_exec(os.path.join(self.fake, "hc"), FAKE_HC)
        self.server = os.path.join(self.fake, "server.mjs")
        write_exec(self.server, FAKE_SERVER)
        write_exec(os.path.join(self.fake, "swarmbox-addon"), '#!/bin/sh\nexec bash "%s" "$@"\n' % ADDON_SH)
        self.addons = os.path.join(self.home, ".local", "share", "swarmbox", "addons")
        self.prefix = os.path.join(self.addons, "voice", "1.9.5")

    def env(self, **extra):
        e = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.home, "FAKE_DIR": self.tmp, "SWARMBOX_TEST_LIB": self.lib,
             "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_WEB_PORT": "29541",
             "SWARMBOX_TEST_WEB_IFACE": "lo", "LANG": "C.UTF-8", "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS,
             "SWARMBOX_TEST_HC_BIN": os.path.join(self.fake, "hc"), "SWARMBOX_TEST_HERDR_WEB": self.server,
             "SWARMBOX_TEST_IMAGE_STATE": os.path.join(self.tmp, "image-state"), "SWARMBOX_TEST_HOST_DIR": os.path.join(self.tmp, "host"),
             "SWARMBOX_TEST_USER_ADDONS": os.path.join(self.tmp, "user-addons"), "SWARMBOX_TEST_LOCK": os.path.join(self.tmp, "addons.lock"),
             "SWARMBOX_TEST_ARCH": "amd64", "TMPDIR": self.tmp}
        e.update(extra)
        return e

    def web(self, mode, **extra):
        return subprocess.run(["bash", WEB, mode], env=self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.tmp)

    def addon(self, *args, **extra):
        return subprocess.run(["bash", ADDON_SH, *args], env=self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.tmp)

    def install_fake(self, root=None, with_front=True):
        """A complete install of voice (.swarmbox-env, current link, launcher) with, unless with_front is False, the front."""
        prefix = self.prefix if root is None else os.path.join(root, "voice", "1.9.5")
        shutil.copytree(VOICE, prefix, ignore=shutil.ignore_patterns("__pycache__", "install.sh", "prepare.sh", "addon.conf"))
        os.makedirs(os.path.join(prefix, "bin"))
        write_exec(os.path.join(prefix, "bin", "swarmbox-voice"), FAKE_VOICE)
        with open(os.path.join(prefix, ".swarmbox-env"), "w") as f:
            f.write("ARCH=amd64\nVERSION=1.9.5\n")
        if not with_front:
            os.remove(os.path.join(prefix, "lib", "swarmbox_voice", "front.py"))
        os.symlink("1.9.5", os.path.join(os.path.dirname(prefix), "current"))
        return prefix

    def server_argv(self):
        return read(os.path.join(self.tmp, "server.argv")).splitlines()

    def voice_argv(self):
        return read(os.path.join(self.tmp, "voice.argv")).splitlines()


class WhereTests(Base):
    def test_not_installed_is_exit_1_and_prints_nothing(self):
        r = self.addon("where", "voice", "swarmbox-voice")
        self.assertEqual((r.returncode, r.stdout), (1, ""))

    def test_installed_prints_the_real_program(self):
        self.install_fake()
        r = self.addon("where", "voice", "swarmbox-voice")
        self.assertEqual((r.returncode, r.stdout), (0, os.path.join(self.addons, "voice", "current", "bin", "swarmbox-voice") + "\n"), r.stderr)

    def test_the_image_level_install_counts_too(self):
        self.install_fake(root=os.path.join(self.tmp, "image-state"))
        self.assertEqual(self.addon("where", "voice", "swarmbox-voice").returncode, 0)

    def test_an_incomplete_install_and_bad_arguments_are_exit_1_or_64(self):
        os.makedirs(os.path.join(self.prefix, "bin"))
        os.symlink("1.9.5", os.path.join(self.addons, "voice", "current"))   # no .swarmbox-env: not complete
        self.assertEqual(self.addon("where", "voice", "swarmbox-voice").returncode, 1)
        self.assertEqual(self.addon("where", "voice", "other").returncode, 1)
        self.assertEqual(self.addon("where", "nosuch", "x").returncode, 1)
        self.assertEqual(self.addon("where", "voice").returncode, 64)
        self.assertEqual(self.addon("where", "../x", "y").returncode, 64)

    def test_where_never_installs_anything(self):
        self.addon("where", "voice", "swarmbox-voice")
        self.assertFalse(os.path.exists(self.addons))


class Disabled(Base):
    """No front: the web server itself is on the web port."""

    def check_plain(self, **extra):
        r = self.web("run", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.server_argv(), ["-p", "29541", "-i", "lo"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "voice.argv")))

    def test_not_installed(self):
        self.check_plain()

    def test_installed_but_the_setting_is_off(self):
        self.install_fake()
        self.check_plain(SWARMBOX_VOICE_WEB="0")

    def test_installed_without_the_front_in_it_yet(self):
        self.install_fake(with_front=False)
        self.check_plain()

    def test_no_swarmbox_addon_at_all(self):
        self.install_fake()
        os.remove(os.path.join(self.fake, "swarmbox-addon"))
        self.check_plain()

    def test_render_is_gone(self):
        self.assertEqual(self.web("render").returncode, 64)


class Enabled(Base):
    def setUp(self):
        super().setUp()
        self.install_fake()

    def test_run_execs_the_front_with_the_web_server_command_after_the_dashes(self):
        r = self.web("run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "server.argv")), "the server is started by the front, not exec'd")
        argv = self.voice_argv()
        self.assertEqual(argv, ["front", "--listen", "lo:29541", "--server-port", "7680", "--", self.server, "-p", "29541", "-i", "lo"])

    def test_the_default_front_address_is_every_interface_on_7681(self):
        r = subprocess.run(["bash", WEB, "run"], env={k: v for k, v in self.env().items() if k not in ("SWARMBOX_TEST_WEB_PORT", "SWARMBOX_TEST_WEB_IFACE")},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.voice_argv()[:3], ["front", "--listen", "0.0.0.0:7681"])

    def test_test_ports_are_passed(self):
        self.web("run", SWARMBOX_TEST_WEB_SERVER_PORT="29542", SWARMBOX_TEST_VOICE_PORT="29543")
        argv = self.voice_argv()
        self.assertEqual(argv[argv.index("--server-port") + 1], "29542")
        self.assertEqual(argv[argv.index("--service-listen") + 1], "127.0.0.1:29543")

    def test_explicit_on_is_enabled_too(self):
        self.assertEqual(self.web("run", SWARMBOX_VOICE_WEB="1").returncode, 0)
        self.assertEqual(self.voice_argv()[0], "front")


class PrepareCase(Base):
    """`swarmbox update` brings a new image with the same whisper.cpp version: the install keeps its files, prepare refreshes them."""

    def setUp(self):
        super().setUp()
        self.install_fake()
        self.old_lib = os.path.join(self.prefix, "lib", "swarmbox_voice")

    def staleness(self):
        # an old service: no front, an old server, the page parts of the old ttyd web terminal, the planners folder of an install from
        # before voice became an input
        os.remove(os.path.join(self.old_lib, "front.py"))
        with open(os.path.join(self.old_lib, "server.py"), "a") as f:
            f.write("# old\n")
        os.makedirs(os.path.join(self.prefix, "web"))
        with open(os.path.join(self.prefix, "web", "page.js"), "w") as f:
            f.write("old page")
        os.makedirs(os.path.join(self.prefix, "planners"))
        with open(os.path.join(self.prefix, "planners", "planner-gone"), "w") as f:
            f.write("x")


class PrepareTests(PrepareCase):
    """The refresh of the files of the install."""

    def test_prepare_refreshes_lib_from_the_image_copy_and_drops_the_old_planners_and_page(self):
        self.staleness()
        r = self.addon("prepare")
        self.assertEqual(r.returncode, 0, r.stderr)
        same = subprocess.run(["diff", "-rq", "-x", "__pycache__", os.path.join(VOICE, "lib"), os.path.join(self.prefix, "lib")], capture_output=True, text=True)
        self.assertEqual(same.stdout, "")
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "web")), "the page parts of an old install are removed")
        self.assertFalse(os.path.exists(os.path.join(VOICE, "web")), "and the image has none")
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "planners")), "the planners of an old install are removed")
        self.assertFalse(os.path.exists(os.path.join(VOICE, "planners")), "and the image has none")
        self.assertEqual(sorted(f for f in os.listdir(self.prefix) if f.startswith(".")), [".swarmbox-env"], "no scratch folder is left")

    def test_it_leaves_whisper_the_models_and_the_launcher_alone(self):
        for rel in ("libexec/whisper-cli", "models/ggml-tiny.bin"):
            os.makedirs(os.path.dirname(os.path.join(self.prefix, rel)), exist_ok=True)
            with open(os.path.join(self.prefix, rel), "w") as f:
                f.write("keep " + rel)
        launcher = read(os.path.join(self.prefix, "bin", "swarmbox-voice"))
        self.staleness()
        self.assertEqual(self.addon("prepare").returncode, 0)
        self.assertEqual(read(os.path.join(self.prefix, "libexec/whisper-cli")), "keep libexec/whisper-cli")
        self.assertEqual(read(os.path.join(self.prefix, "models/ggml-tiny.bin")), "keep models/ggml-tiny.bin")
        self.assertEqual(read(os.path.join(self.prefix, "bin", "swarmbox-voice")), launcher)

    def test_it_is_idempotent_and_writes_nothing_when_the_install_is_current(self):
        self.staleness()
        self.assertEqual(self.addon("prepare").returncode, 0)
        marker = os.path.join(self.old_lib, "front.py")
        before = os.stat(marker).st_ino
        r = self.addon("prepare")
        self.assertEqual((r.returncode, "refreshed" in r.stderr), (0, False), r.stderr)
        self.assertEqual(os.stat(marker).st_ino, before)

    def test_a_pycache_in_the_image_copy_or_the_install_is_no_difference(self):
        os.makedirs(os.path.join(self.old_lib, "__pycache__"))
        with open(os.path.join(self.old_lib, "__pycache__", "x.pyc"), "w") as f:
            f.write("x")
        r = self.addon("prepare")
        self.assertEqual((r.returncode, "refreshed" in r.stderr), (0, False), r.stderr)

    def test_not_installed_means_nothing_happens(self):
        os.remove(os.path.join(self.addons, "voice", "current"))
        r = self.addon("prepare")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "lib", "swarmbox_voice", "front.py.new")))


class PrepareAndTheWebServer(PrepareCase):
    """The restart of the web server that prepare asks for, a refresh that fails, and the front after the refresh."""

    def web_restart_world(self, server=True, front=False):
        """Fake pgrep (which processes 'run') and a fake swarmbox-web that records its arguments."""
        write_exec(os.path.join(self.fake, "pgrep"), '#!/bin/sh\nfor a in "$@"; do case "$a" in herdr-web/server.mjs) [ "$FAKE_SERVER" = 1 ] && exit 0 ;; '
                   '"swarmbox_voice front") [ "$FAKE_FRONT" = 1 ] && exit 0 ;; esac; done\nexit 1\n')
        write_exec(os.path.join(self.fake, "swarmbox-web"), '#!/bin/sh\nprintf "%s\\n" "$@" >> "$FAKE_DIR/web.calls"\n')
        return dict(FAKE_SERVER="1" if server else "0", FAKE_FRONT="1" if front else "0")

    def web_calls(self):
        p = os.path.join(self.tmp, "web.calls")
        return read(p).split() if os.path.exists(p) else []

    def test_installed_while_the_web_server_runs_without_the_front_it_asks_for_a_restart_once(self):
        extra = self.web_restart_world(server=True, front=False)
        r = self.addon("prepare", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.web_calls(), ["restart"])
        self.assertIn("microphone", r.stderr)

    def test_no_restart_when_the_front_runs_when_there_is_no_web_terminal_or_voice_web_is_off(self):
        for what, extra in (("the front runs", dict(server=True, front=True)), ("no web server", dict(server=False, front=False))):
            with self.subTest(what):
                env = self.web_restart_world(**extra)
                self.assertEqual(self.addon("prepare", **env).returncode, 0)
                self.assertEqual(self.web_calls(), [], what)
        env = self.web_restart_world(server=True, front=False)
        self.assertEqual(self.addon("prepare", SWARMBOX_VOICE_WEB="0", **env).returncode, 0)
        self.assertEqual(self.web_calls(), [], "voice.web is 0")

    def test_an_unwritable_install_is_one_prepare_failed_line_and_the_old_files_stay(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores permissions")
        self.staleness()
        os.chmod(self.prefix, 0o555)
        self.addCleanup(os.chmod, self.prefix, 0o755)
        r = self.addon("prepare")
        self.assertEqual(r.returncode, 1)
        self.assertEqual([l for l in r.stderr.splitlines() if l.startswith("prepare-failed: ")], ["prepare-failed: voice: prepare.sh failed (exit 1)"])
        self.assertIn("# old", read(os.path.join(self.old_lib, "server.py")))

    def test_after_the_refresh_the_web_server_takes_the_front(self):
        self.staleness()
        self.assertEqual(self.web("run").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "voice.argv")), "an install from before the front is not used")
        self.assertEqual(self.addon("prepare").returncode, 0)
        self.assertEqual(self.web("run").returncode, 0)
        self.assertEqual(self.voice_argv()[0], "front")

    def test_the_prepare_script_is_where_swarmbox_addon_looks_for_it(self):
        self.assertTrue(os.path.isfile(os.path.join(VOICE, "prepare.sh")))
        entry = read(os.path.join(ROOT, "container", "entrypoint.sh"))
        self.assertIn("swarmbox-addon prepare", entry)
        self.assertLess(entry.index("step 7"), entry.index("step 10"), "prepare runs before the web server starts")


if __name__ == "__main__":
    unittest.main()
