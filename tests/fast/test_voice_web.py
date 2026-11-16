"""How the web terminal decides on the voice front, and how the addon follows `swarmbox update`.

Real programs: container/scripts/swarmbox-web.sh (with a fake ttyd and a fake `swarmbox-voice` that record their arguments), the real
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
import test_web_build as wb  # noqa: E402  (only its helpers: its test class is not imported by name)

ADDON_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
ADDONS = os.path.join(ROOT, "container", "addons")
VOICE = voice_support.VOICE
FAKE_VOICE = '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_DIR/voice.argv"\n'


def read(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="voice-web-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        j = lambda *p: os.path.join(self.tmp, *p)  # noqa: E731
        self.home, self.fake, self.lib, self.run_dir = j("home"), j("fake"), j("lib"), j("run")
        for d in (self.home, self.fake, self.lib, self.run_dir):
            os.makedirs(d)
        os.symlink(wb.DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        wb.write_exec(os.path.join(self.fake, "ttyd"), wb.FAKE_TTYD)
        wb.write_exec(os.path.join(self.fake, "swarmbox-addon"), '#!/bin/sh\nexec bash "%s" "$@"\n' % ADDON_SH)
        self.page = wb.build_page(self.tmp)
        self.addons = os.path.join(self.home, ".local", "share", "swarmbox", "addons")
        self.prefix = os.path.join(self.addons, "voice", "1.9.5")

    def env(self, **extra):
        e = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.home, "FAKE_DIR": self.tmp, "SWARMBOX_TEST_LIB": self.lib,
             "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_WEB_PAGE": self.page, "SWARMBOX_TEST_WEB_PORT": "29541",
             "SWARMBOX_TEST_WEB_IFACE": "lo", "LANG": "C.UTF-8", "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS,
             "SWARMBOX_TEST_IMAGE_STATE": os.path.join(self.tmp, "image-state"), "SWARMBOX_TEST_HOST_DIR": os.path.join(self.tmp, "host"),
             "SWARMBOX_TEST_USER_ADDONS": os.path.join(self.tmp, "user-addons"), "SWARMBOX_TEST_LOCK": os.path.join(self.tmp, "addons.lock"),
             "SWARMBOX_TEST_ARCH": "amd64", "TMPDIR": self.tmp}
        e.update(extra)
        return e

    def web(self, mode, **extra):
        return subprocess.run(["bash", wb.WEB, mode], env=self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.tmp)

    def addon(self, *args, **extra):
        return subprocess.run(["bash", ADDON_SH, *args], env=self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.tmp)

    def install_fake(self, root=None, with_front=True, old=False):
        """A complete install of voice (.swarmbox-env, current link, launcher) with the page parts and, unless old, the front."""
        prefix = self.prefix if root is None else os.path.join(root, "voice", "1.9.5")
        shutil.copytree(VOICE, prefix, ignore=shutil.ignore_patterns("__pycache__", "install.sh", "prepare.sh", "addon.conf"))
        os.makedirs(os.path.join(prefix, "bin"))
        wb.write_exec(os.path.join(prefix, "bin", "swarmbox-voice"), FAKE_VOICE)
        with open(os.path.join(prefix, ".swarmbox-env"), "w") as f:
            f.write("ARCH=amd64\nVERSION=1.9.5\n")
        if not with_front:
            os.remove(os.path.join(prefix, "lib", "swarmbox_voice", "front.py"))
        os.symlink("1.9.5", os.path.join(os.path.dirname(prefix), "current"))
        return prefix

    def index(self):
        return read(os.path.join(self.run_dir, "index.html"))

    def ttyd_argv(self):
        with open(os.path.join(self.tmp, "ttyd.json")) as f:
            return json.load(f)["argv"]


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
    """swarmbox-web behaves exactly as before: tags absent, ttyd on the web port."""

    def check_plain(self, **extra):
        r = self.web("run", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("/voice/", self.index())
        argv = self.ttyd_argv()
        self.assertEqual(argv[:4], ["-p", "29541", "-i", "lo"])
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

    def test_render_alone_is_the_same(self):
        self.install_fake()
        self.assertEqual(self.web("render", SWARMBOX_VOICE_WEB="0").returncode, 0)
        self.assertNotIn("/voice/", self.index())
        self.assertEqual(self.web("render", SWARMBOX_VOICE_WEB="1").returncode, 0)
        self.assertIn("/voice/page.js", self.index())

    def test_the_page_without_the_tags_is_byte_identical_to_the_one_before_this_feature(self):
        r = self.web("render")
        self.assertEqual(r.returncode, 0, r.stderr)
        plain = self.index()
        self.install_fake()
        self.assertEqual(self.web("render", SWARMBOX_VOICE_WEB="0").returncode, 0)
        self.assertEqual(self.index(), plain)


class Enabled(Base):
    def setUp(self):
        super().setUp()
        self.install_fake()

    def test_render_adds_the_two_tags_in_the_right_places(self):
        self.assertEqual(self.web("render").returncode, 0)
        page = self.index()
        css, js = '<link rel="stylesheet" href="/voice/page.css">', '<script src="/voice/page.js" defer></script>'
        self.assertEqual(page.count(css), 1)
        self.assertEqual(page.count(js), 1)
        self.assertTrue(page.index(css) < page.index("</head>") < page.index("<body") < page.index(js) < page.index("</body>"))
        self.assertTrue(page.rstrip().endswith("</body></html>") or page.index(js) + len(js) == page.index("</body>"))
        self.assertEqual(page.count("</head>"), 1)
        self.assertEqual(page.count("</body>"), 1)
        self.assertNotIn("__SWARMBOX_", page)

    def test_run_execs_the_front_with_the_ttyd_command_after_the_dashes(self):
        r = self.web("run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ttyd.json")), "ttyd is started by the front, not exec'd")
        argv = read(os.path.join(self.tmp, "voice.argv")).splitlines()
        self.assertEqual(argv[:6], ["front", "--listen", "lo:29541", "--ttyd-port", "7680", "--"])
        self.assertEqual(argv[6:9], ["ttyd", "-p", "29541"])
        self.assertIn("-W", argv)
        self.assertIn("-O", argv)
        self.assertEqual(argv[argv.index("--index") + 1], os.path.join(self.run_dir, "index.html"))
        self.assertNotIn("--service-listen", argv)

    def test_the_default_front_address_is_every_interface_on_7681(self):
        r = subprocess.run(["bash", wb.WEB, "run"], env={k: v for k, v in self.env().items() if k not in ("SWARMBOX_TEST_WEB_PORT", "SWARMBOX_TEST_WEB_IFACE")},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = read(os.path.join(self.tmp, "voice.argv")).splitlines()
        self.assertEqual(argv[:3], ["front", "--listen", "0.0.0.0:7681"])

    def test_test_ports_are_passed(self):
        self.web("run", SWARMBOX_TEST_WEB_TTYD_PORT="29542", SWARMBOX_TEST_VOICE_PORT="29543")
        argv = read(os.path.join(self.tmp, "voice.argv")).splitlines()
        self.assertEqual(argv[argv.index("--ttyd-port") + 1], "29542")
        self.assertEqual(argv[argv.index("--service-listen") + 1], "127.0.0.1:29543")

    def test_explicit_on_is_enabled_too(self):
        self.assertEqual(self.web("render", SWARMBOX_VOICE_WEB="1").returncode, 0)
        self.assertIn("/voice/page.js", self.index())

    def test_the_other_settings_still_apply(self):
        conf = os.path.join(self.home, ".config", "swarmbox")
        os.makedirs(conf)
        with open(os.path.join(conf, "web-terminal.conf"), "w") as f:
            f.write("padding=12\nfontSize=18\n")
        self.web("run")
        argv = read(os.path.join(self.tmp, "voice.argv")).splitlines()
        self.assertIn("fontSize=18", argv)
        self.assertIn("--swarmbox-padding:12px", self.index())


class PrepareTests(Base):
    """`swarmbox update` brings a new image with the same whisper.cpp version: the install keeps its files, prepare refreshes them."""

    def setUp(self):
        super().setUp()
        self.install_fake()
        self.old_lib = os.path.join(self.prefix, "lib", "swarmbox_voice")

    def staleness(self):
        # an old service: no front, an old server, an old page, the planners folder of an install from before voice became an input
        os.remove(os.path.join(self.old_lib, "front.py"))
        with open(os.path.join(self.old_lib, "server.py"), "a") as f:
            f.write("# old\n")
        with open(os.path.join(self.prefix, "web", "page.js"), "w") as f:
            f.write("old page")
        os.makedirs(os.path.join(self.prefix, "planners"))
        with open(os.path.join(self.prefix, "planners", "planner-gone"), "w") as f:
            f.write("x")

    def test_prepare_refreshes_lib_and_web_from_the_image_copy_and_drops_the_old_planners(self):
        self.staleness()
        r = self.addon("prepare")
        self.assertEqual(r.returncode, 0, r.stderr)
        for d in ("lib", "web"):
            same = subprocess.run(["diff", "-rq", "-x", "__pycache__", os.path.join(VOICE, d), os.path.join(self.prefix, d)], capture_output=True, text=True)
            self.assertEqual(same.stdout, "", d)
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

    def web_restart_world(self, ttyd=True, front=False):
        """Fake pgrep (which processes 'run') and a fake swarmbox-web that records its arguments."""
        wb.write_exec(os.path.join(self.fake, "pgrep"), '#!/bin/sh\nfor a in "$@"; do case "$a" in ttyd) [ "$FAKE_TTYD" = 1 ] && exit 0 ;; '
                      '"swarmbox_voice front") [ "$FAKE_FRONT" = 1 ] && exit 0 ;; esac; done\nexit 1\n')
        wb.write_exec(os.path.join(self.fake, "swarmbox-web"), '#!/bin/sh\nprintf "%s\\n" "$@" >> "$FAKE_DIR/web.calls"\n')
        return dict(FAKE_TTYD="1" if ttyd else "0", FAKE_FRONT="1" if front else "0")

    def web_calls(self):
        p = os.path.join(self.tmp, "web.calls")
        return read(p).split() if os.path.exists(p) else []

    def test_installed_while_the_web_terminal_runs_without_the_front_it_asks_for_a_restart_once(self):
        extra = self.web_restart_world(ttyd=True, front=False)
        r = self.addon("prepare", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.web_calls(), ["restart"])
        self.assertIn("microphone", r.stderr)

    def test_no_restart_when_the_front_runs_when_there_is_no_web_terminal_or_voice_web_is_off(self):
        for what, extra in (("the front runs", dict(ttyd=True, front=True)), ("no web terminal", dict(ttyd=False, front=False))):
            with self.subTest(what):
                env = self.web_restart_world(**extra)
                self.assertEqual(self.addon("prepare", **env).returncode, 0)
                self.assertEqual(self.web_calls(), [], what)
        env = self.web_restart_world(ttyd=True, front=False)
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
        self.assertIn("old page", read(os.path.join(self.prefix, "web", "page.js")))

    def test_after_the_refresh_the_web_terminal_takes_the_front(self):
        self.staleness()
        self.assertEqual(self.web("render").returncode, 0)
        self.assertNotIn("/voice/", self.index(), "an install from before the front is not used")
        self.assertEqual(self.addon("prepare").returncode, 0)
        self.assertEqual(self.web("render").returncode, 0)
        self.assertIn("/voice/page.js", self.index())

    def test_the_prepare_script_is_where_swarmbox_addon_looks_for_it(self):
        self.assertTrue(os.path.isfile(os.path.join(VOICE, "prepare.sh")))
        entry = read(os.path.join(ROOT, "container", "entrypoint.sh"))
        self.assertIn("swarmbox-addon prepare", entry)
        self.assertLess(entry.index("step 7"), entry.index("step 10"), "prepare runs before the web terminal starts")


if __name__ == "__main__":
    unittest.main()
