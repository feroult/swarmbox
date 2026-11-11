"""The progress line of a pull (ui_pull in container/host/swarmbox-host): drawn only for a person at a terminal, from the bytes Podman
has downloaded and the total the registry reports, with fallbacks that never leave a pull without feedback.

The functions are cut out of the real script and run by `sh` under a pseudo-terminal, with a fake `podman` (a pull that grows a file in a
fake temporary folder over a second) and a fake `curl` (a token, an index and an image manifest). Nothing touches the network or a real
Podman. Run with: python3 tests/test_pull_ui.py
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
from helpers import ROOT, DEFAULT_IMAGE_REPO  # noqa: E402

REF = DEFAULT_IMAGE_REPO + ":2.0"

HOST = os.path.join(ROOT, "container", "host", "swarmbox-host")

FAKE_PODMAN = """#!/bin/sh
case $1 in
    info) echo "$FAKE_TMP" ;;
    pull)
        [ -z "${FAKE_PULL_FAIL:-}" ] || { echo "Trying to pull $2..." >&2; echo "Error: initializing source: connection refused" >&2; exit 125; }
        mkdir -p "$FAKE_TMP/container_images_storage1"
        i=0
        while [ "$i" -lt "${FAKE_STEPS:-6}" ]; do
            dd if=/dev/zero bs=1024 count=128 >> "$FAKE_TMP/container_images_storage1/blob" 2> /dev/null
            sleep 0.2
            i=$((i + 1))
        done
        sleep "${FAKE_TAIL:-0}"
        rm -rf "$FAKE_TMP/container_images_storage1"
        ;;
esac
"""

# The layers add up to 768 KiB, and the fake pull grows exactly that much (6 steps of 128 KiB): the line caps at 99% until the pull ends.
FAKE_CURL = """#!/bin/sh
case "$*" in
    *ghcr.io/token*) echo '{"token":"abc"}' ;;
    *manifests/sha256:*) echo '{"schemaVersion":2,"config":{"size":1500},"layers":[{"size":393216},{"size":393216}]}' ;;
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


class PullUiTest(unittest.TestCase):
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

    def run_pull(self, tty=True, **env):
        """pull_image under a pseudo-terminal (or with a pipe): returns (exit status, output bytes)."""
        base = {"PATH": self.bin + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "FAKE_TMP": self.faketmp, "TERM": "xterm-256color",
                "LANG": "C.UTF-8", "TMPDIR": self.tmp, "HOME": self.tmp}
        base.update(env)
        script = '. "%s"; UP_BG=; UP_ERRF=; pull_image %s; rc=$?; echo "[rc=$rc msg=$PULL_MSG]"; exit $rc' % (self.funcs, REF)
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

    @staticmethod
    def plain(out):
        """The text of the line without escape sequences."""
        return re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", out).decode("utf-8", "replace")

    def test_a_terminal_gets_the_line_with_a_percent_and_ends_on_a_done_line(self):
        rc, out = self.run_pull()
        text = self.plain(out)
        self.assertEqual(rc, 0, text)
        self.assertIn("pull", text)
        self.assertRegex(text, r"\d+%")
        self.assertRegex(text, r"MB")
        self.assertIn("pulled %s (" % REF, text)
        self.assertIn("✔", text)
        self.assertIn("▰", text)
        self.assertNotIn("Trying to pull", text, "Podman's own output stays out of the line")

    def test_the_percent_only_grows_and_never_passes_99_before_the_end(self):
        rc, out = self.run_pull()
        pcts = [int(x) for x in re.findall(r"(\d+)%", self.plain(out).replace("\r", "\n"))]
        self.assertTrue(pcts, "no percent was drawn")
        self.assertEqual(pcts, sorted(pcts))
        self.assertLessEqual(max(pcts), 99)

    def test_without_a_total_the_bar_sweeps_and_shows_no_percent(self):
        with open(os.path.join(self.bin, "curl"), "w") as f:   # a registry that cannot be reached
            f.write("#!/bin/sh\nexit 22\n")
        os.chmod(os.path.join(self.bin, "curl"), 0o755)
        rc, out = self.run_pull()
        text = self.plain(out)
        self.assertEqual(rc, 0, text)
        self.assertNotRegex(text.split("pulled")[0], r"\d+%")
        self.assertIn("pull", text)

    def test_starship_in_the_shell_turns_the_powerline_glyphs_on_and_icons_zero_turns_them_off(self):
        sep = "".encode()
        _, out = self.run_pull(STARSHIP_SHELL="bash")
        self.assertIn(sep, out)
        self.assertIn("".encode(), out)
        _, out = self.run_pull(STARSHIP_SHELL="bash", SWARMBOX_ICONS="0")
        self.assertNotIn(sep, out)
        _, out = self.run_pull()
        self.assertNotIn(sep, out, "no Starship, no glyphs that need a Nerd Font")
        _, out = self.run_pull(SWARMBOX_ICONS="1")
        self.assertIn(sep, out)

    def test_no_color_has_no_color_escapes_and_no_utf8_locale_gives_ascii(self):
        _, out = self.run_pull(NO_COLOR="1")
        self.assertNotRegex(out, rb"\x1b\[[0-9;]*m")
        _, out = self.run_pull(LANG="C", LC_ALL="C")
        text = self.plain(out)
        self.assertIn("#", text)
        self.assertNotIn("▰", text)
        self.assertIn("ok pulled", text)

    def test_truecolor_and_256_color_terminals_get_their_own_sequences(self):
        _, out = self.run_pull(COLORTERM="truecolor")
        self.assertIn(b"\x1b[48;2;109;40;217m", out)
        _, out = self.run_pull()
        self.assertIn(b"\x1b[48;5;56m", out)
        self.assertNotIn(b";2;109;40;217", out)

    def test_swarmbox_progress_plain_and_a_dumb_terminal_leave_podmans_own_output(self):
        for env in ({"SWARMBOX_PROGRESS": "plain"}, {"TERM": "dumb"}):
            rc, out = self.run_pull(**env)
            text = self.plain(out)
            self.assertEqual(rc, 0, text)
            self.assertNotIn("pulled ghcr.io", text, env)

    def test_without_a_terminal_it_is_quiet_and_draws_nothing(self):
        rc, out = self.run_pull(tty=False)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.decode().strip(), "[rc=0 msg=]")

    def test_a_failed_pull_shows_the_last_lines_of_podmans_error_and_returns_them(self):
        rc, out = self.run_pull(FAKE_PULL_FAIL="1")
        text = self.plain(out)
        self.assertNotEqual(rc, 0)
        self.assertIn("Error: initializing source: connection refused", text)
        self.assertIn("msg=Error: initializing source: connection refused", text)
        self.assertNotIn("pulled ghcr.io", text)

    def test_a_narrow_terminal_drops_the_right_hand_blocks(self):
        _, out = self.run_pull(COLUMNS="50")   # tput honours COLUMNS
        before = self.plain(out).split("pulled")[0]
        self.assertNotIn("MB/s", before)
        self.assertNotRegex(before, r"\d+/\d+ MB")
        _, out = self.run_pull(COLUMNS="60")
        before = self.plain(out).split("pulled")[0]
        self.assertRegex(before, r"\d+/\d+ MB")
        self.assertNotIn("MB/s", before)

    def test_when_the_download_is_over_and_the_pull_is_still_writing_the_label_says_unpack(self):
        _, out = self.run_pull(FAKE_TAIL="3")
        text = self.plain(out)
        self.assertIn("unpack", text)
        self.assertLess(text.index("pull "), text.index("unpack"), "the line starts as pull")


if __name__ == "__main__":
    unittest.main()
