"""The progress line of a pull (ui_pull in container/host/swarmbox-host): drawn only for a person at a terminal, from the bytes Podman
has downloaded and the total the registry reports, with fallbacks that never leave a pull without feedback.

The functions are cut out of the real script and run by `sh` under a pseudo-terminal, with a fake `podman` (a pull that grows a file in a
fake temporary folder over a second) and a fake `curl` (a token, an index and an image manifest). Nothing touches the network or a real
Podman. A pull is a second of real time (the line is redrawn every quarter of a second), so the tests that are about how the line
looks call the drawing functions directly and only five of them run a whole pull. Run with: python3 tests/fast/test_pull_ui.py
"""
import os
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, DEFAULT_IMAGE_REPO  # noqa: E402

REF = DEFAULT_IMAGE_REPO + ":2.0"

HOST = os.path.join(ROOT, "container", "host", "swarmbox-host")

FAKE_PODMAN = """#!/bin/sh
case $1 in
    info) echo "$FAKE_TMP" ;;
    pull)
        [ -z "${FAKE_PULL_FAIL:-}" ] || { echo "Trying to pull $2..." >&2; echo "Error: initializing source: connection refused" >&2; exit 125; }
        [ -z "${FAKE_SKIP_BLOB:-}" ] || echo "Copying blob sha256:$FAKE_SKIP_BLOB skipped: already exists" >&2
        mkdir -p "$FAKE_TMP/container_images_storage1"
        i=0
        while [ "$i" -lt "${FAKE_STEPS:-4}" ]; do
            dd if=/dev/zero bs=1024 count="${FAKE_KIB:-192}" >> "$FAKE_TMP/container_images_storage1/blob" 2> /dev/null
            sleep "${FAKE_STEP_SLEEP:-0.05}"
            i=$((i + 1))
        done
        [ -z "${FAKE_WRITE_MANIFEST:-}" ] || echo "Writing manifest to image destination" >&2
        sleep "${FAKE_TAIL:-0}"
        rm -rf "$FAKE_TMP/container_images_storage1"
        ;;
esac
"""

# The layers add up to 768 KiB, and the fake pull grows exactly that much (4 steps of 192 KiB): the line caps at 99% until the pull ends.
FAKE_CURL = """#!/bin/sh
case "$*" in
    *ghcr.io/token*) echo '{"token":"abc"}' ;;
    *manifests/sha256:*) echo '{"schemaVersion":2,"config":{"size":1500},"layers":[{"digest":"sha256:1111222233334444","size":196608},{"digest":"sha256:5555666677778888","size":589824}]}' ;;
    *manifests/*) echo '{"manifests":[{"mediaType":"x","digest":"sha256:aaa111","size":1,"platform":{"architecture":"amd64","os":"linux"}},{"mediaType":"x","digest":"sha256:bbb222","size":1,"platform":{"architecture":"arm64","os":"linux"}}]}' ;;
esac
"""


def functions():
    """The part of the script from ui_setup to the end of pull_image, plus show_err."""
    with open(HOST) as f:
        text = f.read()
    a = text.index("# ---------------------------------------------------------------- the pull, for a person at a terminal")
    b = text.index("# A missing image is pulled, never built.")
    m = re.search(r"^show_err\(\) .*$", text, re.M)
    return m.group(0) + "\n" + text[a:b]


class PullUiCase(unittest.TestCase):
    """The fakes and the runners; the tests are in three classes that the runner runs side by side."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-pullui.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        for name, body in (("podman", FAKE_PODMAN), ("curl", FAKE_CURL)):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        self.funcs = os.path.join(self.tmp, "funcs.sh")
        with open(self.funcs, "w") as f:
            f.write(functions())
        self.faketmp = os.path.join(self.tmp, "vartmp")
        os.mkdir(self.faketmp)

    def sh(self, script, tty=True, **env):
        """Run a script of sh that has the functions of the host script loaded, under a pseudo-terminal (or with a pipe):
        returns (exit status, output bytes)."""
        base = {"PATH": self.bin + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "FAKE_TMP": self.faketmp, "TERM": "xterm-256color",
                "LANG": "C.UTF-8", "TMPDIR": self.tmp, "HOME": self.tmp}
        base.update(env)
        script = '. "%s"; UP_BG=; UP_ERRF=; %s' % (self.funcs, script)
        if not tty:
            r = subprocess.run(["sh", "-c", script], env=base, capture_output=True)
            return r.returncode, r.stdout + r.stderr
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe("sh", ["sh", "-c", script], base)
        out = b""
        while True:
            r, _, _ = select.select([fd], [], [], 30)
            if not r:
                break
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), out

    def run_pull(self, tty=True, **env):
        """pull_image of the whole flow, then the status and the message it set."""
        env.setdefault("SWARMBOX_TEST_PULL_TICK", "0.03")
        return self.sh('pull_image %s; rc=$?; echo "[rc=$rc msg=$PULL_MSG]"; exit $rc' % REF, tty=tty, **env)

    def draw(self, script, **env):
        """Output of the drawing functions with the setup of a UTF-8 terminal, colors on and 80 columns, `script` run after it."""
        setup = 'UI_ESC=$(printf "\\033"); UI_COLOR=1; UI_COLS=${UI_COLS:-80}; UI_ON=#; UI_OFF=-; UI_OK=ok; UI_DOT=.; ui_tick=3; '
        return self.sh(setup + script, tty=False, **env)[1].decode()

    @staticmethod
    def plain(out):
        """The text of the line without escape sequences."""
        return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", out).decode("utf-8", "replace")


class WholePull(PullUiCase):
    """The whole flow on a terminal: a real pull of a fraction of a second."""

    def test_a_terminal_gets_the_line_with_a_percent_that_only_grows_and_ends_on_a_done_line(self):
        # the environment is the hostile one: a Starship shell and the icons switch must not bring a Nerd Font glyph in
        rc, out = self.run_pull(STARSHIP_SHELL="bash", SWARMBOX_ICONS="1")
        text = self.plain(out)
        self.assertEqual(rc, 0, text)
        self.assertRegex(text, r"\d+/\d+ MB")
        self.assertIn("pulled %s \u00b7 " % REF, text)
        self.assertIn("\u2713", text)
        self.assertIn("\u25b0", text)
        self.assertNotIn("Trying to pull", text, "Podman's own output stays out of the line")
        pcts = [int(x) for x in re.findall(r"(\d+)%", text.replace("\r", "\n"))]
        self.assertTrue(pcts, "no percent was drawn")
        self.assertEqual(pcts, sorted(pcts))
        self.assertLessEqual(max(pcts), 99, "the line caps at 99% until the pull ends")
        # private-use characters are where the powerline arrows and the icons live
        icons = sorted({hex(ord(c)) for c in out.decode("utf-8", "replace") if 0xE000 <= ord(c) <= 0xF8FF or ord(c) >= 0xF0000})
        self.assertEqual(icons, [])
        self.assertIn(b"\x1b[38;5;141m", out, "a 256-color terminal gets the 256-color violet")
        self.assertNotIn(b";2;167;139;250", out)

    def test_without_a_total_the_bar_sweeps_and_shows_no_percent(self):
        with open(os.path.join(self.bin, "curl"), "w") as f:   # a registry that cannot be reached
            f.write("#!/bin/sh\nexit 22\n")
        os.chmod(os.path.join(self.bin, "curl"), 0o755)
        rc, out = self.run_pull(FAKE_STEPS="2")
        text = self.plain(out)
        self.assertEqual(rc, 0, text)
        self.assertNotRegex(text.split("pulled")[0], r"\d+%")
        self.assertIn("pull", text)


class WholePullUnpack(PullUiCase):
    """The whole flow on a terminal: the unpack after the download."""

    def test_when_the_download_is_over_and_the_pull_is_still_writing_the_label_says_unpack(self):
        _, out = self.run_pull(FAKE_STEPS="1", FAKE_KIB="768", FAKE_TAIL="0.15")
        text = self.plain(out)
        self.assertIn("unpack", text)
        self.assertLess(text.index("pull "), text.index("unpack"), "the line starts as pull")

    def test_skipped_cached_layers_still_reach_99_percent_and_unpack(self):
        # 196608 B (192 KiB, 25%) is already cached and skipped; Podman only downloads the remaining 576 KiB (75%).
        rc, out = self.run_pull(FAKE_SKIP_BLOB="1111222233334444", FAKE_STEPS="3", FAKE_KIB="192", FAKE_TAIL="0.15")
        text = self.plain(out)
        self.assertEqual(rc, 0, text)
        pcts = [int(x) for x in re.findall(r"(\d+)%", text.replace("\r", "\n"))]
        self.assertTrue(pcts, "no percent was drawn")
        self.assertEqual(pcts, sorted(pcts))
        self.assertEqual(max(pcts), 99, "skipped layers must count toward the total so the pull reaches 99%%: %r" % pcts)
        self.assertIn("unpack", text)


class PullFallbacks(PullUiCase):
    """The whole flow: a failed pull, and the cases that leave Podman's own output or draw nothing."""

    def test_a_failed_pull_shows_the_last_lines_of_podmans_error_and_returns_them(self):
        rc, out = self.run_pull(FAKE_PULL_FAIL="1")
        text = self.plain(out)
        self.assertNotEqual(rc, 0)
        self.assertIn("Error: initializing source: connection refused", text)
        self.assertIn("msg=Error: initializing source: connection refused", text)
        self.assertNotIn("pulled ghcr.io", text)

    def test_swarmbox_progress_plain_and_a_dumb_terminal_leave_podmans_own_output(self):
        for env in ({"SWARMBOX_PROGRESS": "plain"}, {"TERM": "dumb"}):
            rc, out = self.run_pull(FAKE_STEPS="1", **env)
            text = self.plain(out)
            self.assertEqual(rc, 0, text)
            self.assertNotIn("pulled ghcr.io", text, env)

    def test_without_a_terminal_it_is_quiet_and_draws_nothing(self):
        rc, out = self.run_pull(tty=False, FAKE_STEPS="1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.decode().strip(), "[rc=0 msg=]")



class LineLooks(PullUiCase):
    """How the line looks: the functions called directly."""

    def test_no_color_has_no_color_escapes_and_no_utf8_locale_gives_ascii(self):
        show = 'ui_setup; echo "UI=$UI COLOR=$UI_COLOR ON=$UI_ON OK=$UI_OK"; ui_bar 50; echo; ui_done_line %s 5 ""' % REF
        _, out = self.sh(show, NO_COLOR="1")
        self.assertIn(b"UI=1 COLOR=0", out)
        self.assertNotRegex(out, rb"\x1b\[[0-9;]*m")
        _, out = self.sh(show, LANG="C", LC_ALL="C")
        text = self.plain(out)
        self.assertIn("ON=# OK=ok", text)
        self.assertIn("ok pulled", text)
        self.assertNotIn("\u25b0", text)

    def test_truecolor_gets_its_sequences_the_filled_part_is_violet_and_the_rest_dark_gray(self):
        out = self.draw("ui_bar 50", COLORTERM="truecolor")
        self.assertIn("\x1b[38;2;167;139;250m", out, "the violet of the filled bar")
        self.assertIn("\x1b[38;2;63;63;70m", out, "the part of the bar still to come")
        self.assertNotRegex(out, r"\x1b\[48;", "no background anywhere: the line is words and a bar")

    def test_a_narrow_terminal_drops_the_right_hand_blocks(self):
        for cols, mb, speed in (("50", False, False), ("60", True, False), ("80", True, True)):
            line = self.plain(self.draw("ui_draw_pull 40 3 10000000 2 7 pull", UI_COLS=cols).encode())
            self.assertEqual(bool(re.search(r"3/10 MB", line)), mb, cols)
            self.assertEqual("MB/s" in line, speed, cols)

    def test_indeterminate_bar_is_always_four_cells_and_label_keeps_bar_aligned(self):
        for tick in range(1, 26):
            bar = self.plain(self.draw("ui_tick=%d; ui_bar -1" % tick).encode())
            self.assertEqual(len(bar), 16, tick)
            self.assertEqual(bar.count("#"), 4, "tick %d: %r" % (tick, bar))
        pull_line = self.plain(self.draw("ui_draw_pull 40 3 10000000 2 7 pull").encode())
        unpack_line = self.plain(self.draw("ui_draw_pull 99 10 10000000 0 9 unpack").encode())
        self.assertEqual(pull_line.index("#"), unpack_line.index("#"), "bar column must not jump between pull and unpack")
        indet_line = self.plain(self.draw("ui_draw_pull -1 0 '' 0 0 pull").encode())
        self.assertNotIn("   0 MB", indet_line, "indeterminate line should not have a 3-space gap before MB")


if __name__ == "__main__":
    unittest.main()
