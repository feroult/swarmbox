#!/usr/bin/env python3
"""Slice 6.6: dev/owner-check.sh, the hardware checks the owner runs on a Mac, on WSL2, as another UID, with an older Podman.

The script runs here against a fake uname (Darwin, Linux), a fake /proc/version (WSL), a fake xcode-select and a fake podman that
records its calls and runs the container command on the host (so the file the "container" writes is a real file). What is proven:
the output is well formed under dash and bash, a FAIL gives a non-zero exit, nothing is written outside the mktemp folder, only
swarmbox-test- names reach Podman, and a box named swarmbox is refused. The reduced host-UID run (the script as another user) is
the last class; it skips by name when sudo -n -u is not possible. Not proven here: the real macOS, a real Windows drive, a real
Podman older than 4.3, a clean macOS python3 (they are in docs/owner-checks.md and stay open, B6 B7 B8 B15).
Run: python3 tests/test_owner_check.py
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "owner-check.sh")
HELPER_DIR = os.path.join(ROOT, "container", "host")
LINE = re.compile(r"^(PASS|FAIL|SKIP) [A-Za-z0-9_.-]+ \S.*$|^INFO [A-Za-z0-9_.-]+ .*$|^SUMMARY pass=\d+ fail=\d+ skip=\d+$")

FAKE_PODMAN = r'''#!/bin/sh
# a fake podman: records every call; "run" executes the container command on the host with /work mapped to the -v folder
echo "$*" >> "$FAKE_LOG"
case $1 in
    version) echo "${FAKE_PODMAN_VERSION:-4.3.1}"; exit 0 ;;
    --version) echo "podman version ${FAKE_PODMAN_VERSION:-4.3.1}"; exit 0 ;;
    machine) echo "podman-machine-default running=${FAKE_MACHINE_RUNNING:-true}"; exit 0 ;;
    image) exit "${FAKE_IMAGE_EXISTS_RC:-0}" ;;
    rm) exit 0 ;;
    run) ;;
    *) echo "unexpected podman verb $1" >&2; exit 99 ;;
esac
shift
vol=
dev=
last=
prev=
for a in "$@"; do
    [ "$prev" = -v ] && vol=$a
    [ "$prev" = --device ] && dev=$a
    prev=$a
    last=$a
done
[ "${FAKE_RUN_RC:-0}" = 0 ] || { echo "Error: fake run failure" >&2; exit "$FAKE_RUN_RC"; }
if [ "$last" = init ]; then
    case ${SHELL:-} in
        */zsh) printf 'swarmbox() {\n  emulate -L zsh\n  local -a sa pe\n}\n' ;;
        */fish) printf 'function swarmbox\nend\n' ;;
        *) printf 'swarmbox() {\n  local -a sa pe\n}\n' ;;
    esac
    exit 0
fi
if [ -n "$dev" ]; then exit "${FAKE_TUN_RC:-0}"; fi
if [ -n "$vol" ]; then
    host=${vol%%:*}
    script=$(printf '%s' "$last" | sed -e "s#/work#$host#g" -e 's#\$(id -u)#1000#g' -e 's#\$(id -g)#1000#g')
    [ "${FAKE_NO_WRITE:-0}" = 1 ] && exit 0
    sh -c "$script"
fi
exit 0
'''


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


class Env:
    """A scratch folder with fake commands first on PATH, a clean HOME and an empty TMPDIR to look at afterwards."""

    def __init__(self, uname="Linux", wsl=False, xcode_ok=None, python=True):
        self.root = tempfile.mkdtemp(prefix="owner-check-test-")
        self.bin = os.path.join(self.root, "bin")
        self.home = os.path.join(self.root, "home")
        self.tmp = os.path.join(self.root, "tmp")
        self.cwd = os.path.join(self.root, "cwd")
        self.log = os.path.join(self.root, "podman.log")
        for d in (self.bin, self.home, self.tmp, self.cwd, os.path.join(self.home, ".config"), os.path.join(self.home, ".local")):
            os.makedirs(d, exist_ok=True)
        open(self.log, "w").close()
        write_exec(os.path.join(self.bin, "podman"), FAKE_PODMAN)
        real_id = shutil.which("id")
        write_exec(os.path.join(self.bin, "id"), '#!/bin/sh\nif [ "$1" = -u ] && [ -n "${FAKE_UID:-}" ]; then echo "$FAKE_UID"; else exec %s "$@"; fi\n' % real_id)
        real_uname = shutil.which("uname")
        write_exec(os.path.join(self.bin, "uname"), '#!/bin/sh\ncase "$1" in -s) echo %s ;; -m) echo x86_64 ;; *) exec %s "$@" ;; esac\n' % (uname, real_uname))
        if xcode_ok is not None:
            write_exec(os.path.join(self.bin, "xcode-select"), "#!/bin/sh\nexit %d\n" % (0 if xcode_ok else 2))
        if uname == "Darwin":
            write_exec(os.path.join(self.bin, "xattr"), "#!/bin/sh\nexit 0\n")
            write_exec(os.path.join(self.bin, "sw_vers"), "#!/bin/sh\necho 14.5\n")
        self.python_marker = os.path.join(self.root, "python3-ran")
        if python:
            write_exec(os.path.join(self.bin, "python3"), '#!/bin/sh\n: > "%s"\necho 3.9.6\n' % self.python_marker)
        self.pv = os.path.join(self.root, "proc-version")
        with open(self.pv, "w") as f:
            f.write("Linux version 5.15.153.1-microsoft-standard-WSL2\n" if wsl else "Linux version 6.1.0-18-amd64 (debian)\n")
        # the helper of the repository has no tool-ports and no cloudflare-setup.py: the script must cope
        self.base_env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.home, "TMPDIR": self.tmp,
                         "SWARMBOX_CHECK_PROC_VERSION": self.pv, "FAKE_LOG": self.log, "SHELL": "/bin/zsh", "LANG": "C"}

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run(self, *args, interpreter="sh", env=None, uid_prefix=None):
        e = dict(self.base_env)
        e.update(env or {})
        cmd = [interpreter, SCRIPT] + list(args)
        if uid_prefix:
            cmd = uid_prefix + cmd
        return subprocess.run(cmd, capture_output=True, text=True, cwd=self.cwd, env=e, timeout=120)

    def podman_calls(self):
        with open(self.log) as f:
            return [l.rstrip("\n") for l in f if l.strip()]

    def tree(self, path):
        out = []
        for dp, dn, fn in os.walk(path):
            for n in dn + fn:
                out.append(os.path.relpath(os.path.join(dp, n), path))
        return sorted(out)


def parse(out):
    res = {}
    for l in out.splitlines():
        m = re.match(r"^(PASS|FAIL|SKIP) (\S+) ", l)
        if m:
            res.setdefault(m.group(2), []).append(m.group(1))
    return res


INTERPRETERS = [i for i in ("dash", "bash", "sh") if shutil.which(i)]


class Basics(unittest.TestCase):
    def test_file_is_posix_sh_and_executable(self):
        self.assertTrue(os.path.isfile(SCRIPT))
        with open(SCRIPT) as f:
            text = f.read()
        self.assertEqual(text.splitlines()[0], "#!/bin/sh")
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)
        for bad in ("[[", "echo -e", "<<<"):
            self.assertTrue(bad not in text, "bashism %r" % bad)
        self.assertIsNone(re.search(r"\$'[^']*\\[nt]", text), "ANSI-C quoting")
        self.assertIsNone(re.search(r"(?m)^\s*local\s", text))
        for forbidden in ("pkill", "killall", "kill-server", "system prune", "volume prune", "rm -a", "stop -a", "7681", "tmux"):
            self.assertTrue(forbidden not in text, "forbidden text %r" % forbidden)

    def test_parses_under_dash(self):
        if not shutil.which("dash"):
            self.skipTest("dash missing")
        self.assertEqual(subprocess.run(["dash", "-n", SCRIPT]).returncode, 0)

    def test_shellcheck_when_available(self):
        if not shutil.which("shellcheck"):
            self.skipTest("shellcheck not installed (CI installs it)")
        p = subprocess.run(["shellcheck", "-s", "sh", SCRIPT], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_list_names_the_checks(self):
        p = subprocess.run(["sh", SCRIPT, "--list"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        ids = p.stdout.split()
        for need in ("B6.machine", "B7.host-uid", "B8.podman-version", "B15.python3", "B19.sort-v", "B21.shell-env",
                     "B22.token-mode", "B23.helper-sh", "B32.wsl-refusal", "B34.mode-forms"):
            self.assertIn(need, ids)


class Output(unittest.TestCase):
    def test_well_formed_lines_and_exit_zero_in_each_shell(self):
        for interp in INTERPRETERS:
            with self.subTest(interp=interp):
                env = Env()
                try:
                    p = env.run(interpreter=interp)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    lines = p.stdout.splitlines()
                    for l in lines:
                        self.assertRegex(l, LINE)
                    self.assertTrue(lines[-1].startswith("SUMMARY "))
                    r = parse(p.stdout)
                    self.assertEqual(r["B8.podman-version"], ["PASS"])
                    self.assertEqual(r["box.workspace-write"], ["PASS"])
                    self.assertEqual(r["box.tun"], ["PASS"])
                    self.assertEqual(r["B22.token-mode"], ["PASS"])
                    self.assertEqual(r["B23.helper-sh"], ["PASS"])
                    self.assertEqual(r["B34.mode-forms"], ["PASS"])
                    self.assertEqual(r["B19.sort-v"], ["PASS"])
                    self.assertEqual(r["B15.python3"], ["PASS"])
                    self.assertEqual(r["B6.machine"], ["SKIP"])      # not macOS
                    self.assertEqual(r["B32.wsl-refusal"], ["SKIP"])  # not WSL
                    self.assertEqual(r["B21.shell-env"], ["SKIP"])    # no --box-image
                    m = re.search(r"SUMMARY pass=(\d+) fail=(\d+) skip=(\d+)", p.stdout)
                    self.assertEqual(int(m.group(2)), 0)
                    self.assertEqual(sum(len(v) for v in r.values()), int(m.group(1)) + int(m.group(2)) + int(m.group(3)))
                finally:
                    env.close()

    def test_one_line_per_check_even_when_b7_needs_the_container_run(self):
        env = Env()
        try:
            p = env.run("--only", "B7", env={"FAKE_UID": "501"})   # a macOS-like user; the files are really owned by the test user
            r = parse(p.stdout)
            self.assertEqual(len(r["box.workspace-write"]), 1)
            self.assertEqual(r["B7.host-uid"], ["FAIL"], "the fake id says 501 but the file owner is the real user: must be caught")
            self.assertEqual(len([c for c in env.podman_calls() if c.startswith("run")]), 1)
        finally:
            env.close()

    def test_only_selects_by_prefix_and_unknown_is_a_usage_error(self):
        env = Env()
        try:
            p = env.run("--only", "B22,B34")
            self.assertEqual(sorted(parse(p.stdout)), ["B22.token-mode", "B34.mode-forms"])
            p = env.run("--only", "B99")
            self.assertEqual(p.returncode, 2)
            p = env.run("--bogus")
            self.assertEqual(p.returncode, 2)
        finally:
            env.close()

    def test_no_container_skips_every_container_check_and_calls_no_run(self):
        env = Env()
        try:
            p = env.run("--no-container", "--box-image", "swarmbox-test-img-x")
            r = parse(p.stdout)
            for k in ("box.workspace-write", "box.tun", "B21.shell-env"):
                self.assertEqual(r[k], ["SKIP"], k)
            self.assertFalse([c for c in env.podman_calls() if c.startswith("run")])
        finally:
            env.close()


class FailureExit(unittest.TestCase):
    def test_a_fail_gives_exit_one(self):
        env = Env()
        try:
            p = env.run(env={"FAKE_TUN_RC": "1"})
            self.assertEqual(p.returncode, 1)
            self.assertEqual(parse(p.stdout)["box.tun"], ["FAIL"])
            self.assertRegex(p.stdout, r"SUMMARY pass=\d+ fail=1 ")
        finally:
            env.close()

    def test_podman_older_than_4_3_fails_b8_and_4_10_passes(self):
        env = Env()
        try:
            for v, want in (("4.2.1", "FAIL"), ("3.4.4", "FAIL"), ("4.3.0", "PASS"), ("4.10.0", "PASS"), ("5.1.2", "PASS")):
                p = env.run("--only", "B8", env={"FAKE_PODMAN_VERSION": v})
                self.assertEqual(parse(p.stdout)["B8.podman-version"], [want], v)
                self.assertEqual(p.returncode, 0 if want == "PASS" else 1, v)
            p = env.run("--only", "B8", env={"FAKE_PODMAN_VERSION": "garbage"})
            self.assertEqual(parse(p.stdout)["B8.podman-version"], ["FAIL"])
        finally:
            env.close()

    def test_a_failed_container_run_is_a_fail_with_the_podman_message(self):
        env = Env()
        try:
            p = env.run("--only", "box.workspace-write", env={"FAKE_RUN_RC": "125"})
            self.assertEqual(p.returncode, 1)
            self.assertIn("fake run failure", p.stdout)
        finally:
            env.close()

    def test_a_folder_the_machine_does_not_share_is_a_fail(self):
        env = Env()
        try:
            p = env.run("--only", "box.workspace-write", env={"FAKE_NO_WRITE": "1"})
            self.assertEqual(parse(p.stdout)["box.workspace-write"], ["FAIL"])
            self.assertIn("not shared", p.stdout)
        finally:
            env.close()

    def test_no_helper_is_a_fail_not_a_crash(self):
        env = Env()
        try:
            p = env.run("--only", "B22", "--helper", os.path.join(env.root, "nothing-here"))
            self.assertEqual(parse(p.stdout)["B22.token-mode"], ["FAIL"])
            self.assertEqual(p.returncode, 1)
        finally:
            env.close()

    def test_helper_that_breaks_the_token_rule_fails_b22(self):
        env = Env()
        try:
            h = os.path.join(env.root, "h")
            shutil.copytree(HELPER_DIR, h)
            path = os.path.join(h, "swarmbox-host")
            with open(path) as f:
                text = f.read()
            self.assertIn("TOKEN_IGNORED", text)
            # a helper that never ignores the token
            with open(path, "w") as f:
                f.write(text.replace("TOKEN_IGNORED=1", "TOKEN_IGNORED=0"))
            p = env.run("--only", "B22", "--helper", path)
            self.assertEqual(parse(p.stdout)["B22.token-mode"], ["FAIL"], p.stdout)
        finally:
            env.close()


class Platforms(unittest.TestCase):
    def test_macos_checks_the_machine_and_the_xattr_case(self):
        env = Env(uname="Darwin", xcode_ok=True)
        try:
            p = env.run()
            r = parse(p.stdout)
            self.assertEqual(r["B6.machine"], ["PASS"])
            self.assertEqual(r["B34.mode-forms"], ["PASS"])
            self.assertIn("xattr-600=ok", p.stdout)
            self.assertIn("macos=14.5", p.stdout)
            self.assertIn("machine list", " ".join(env.podman_calls()))
            p = env.run("--only", "B6", env={"FAKE_MACHINE_RUNNING": "false"})
            self.assertEqual(parse(p.stdout)["B6.machine"], ["FAIL"])
            self.assertIn("podman machine start", p.stdout)
        finally:
            env.close()

    def test_macos_python_stub_is_reported_and_never_run(self):
        env = Env(uname="Darwin", xcode_ok=False)
        try:
            p = env.run("--only", "B15")
            self.assertEqual(parse(p.stdout)["B15.python3"], ["FAIL"])
            self.assertIn("Command Line Tools", p.stdout)
            self.assertFalse(os.path.exists(env.python_marker), "the stub python3 must not run")
        finally:
            env.close()

    def test_python_missing_is_a_fail_naming_remote(self):
        env = Env(python=False)
        try:
            p = env.run("--only", "B15", env={"SWARMBOX_CHECK_PYTHON": "swarmbox-no-such-python"})
            self.assertEqual(parse(p.stdout)["B15.python3"], ["FAIL"])
            self.assertIn("swarmbox remote", p.stdout)
        finally:
            env.close()

    def test_python_present_on_macos_with_tools_runs(self):
        env = Env(uname="Darwin", xcode_ok=True)
        try:
            p = env.run("--only", "B15")
            self.assertEqual(parse(p.stdout)["B15.python3"], ["PASS"])
            self.assertTrue(os.path.exists(env.python_marker))
        finally:
            env.close()

    def test_wsl_refusal_runs_with_the_fake_proc_version(self):
        env = Env(wsl=True)
        try:
            p = env.run("--only", "B32")
            self.assertEqual(parse(p.stdout)["B32.wsl-refusal"], ["PASS"], p.stdout)
            self.assertIn("wsl=yes", env.run("--only", "env").stdout)
        finally:
            env.close()

    def test_wsl_refusal_fails_with_a_helper_that_does_not_refuse(self):
        env = Env(wsl=True)
        try:
            h = os.path.join(env.root, "h")
            shutil.copytree(HELPER_DIR, h)
            path = os.path.join(h, "swarmbox-host")
            with open(path) as f:
                text = f.read()
            with open(path, "w") as f:
                f.write(text.replace("    is_wsl || return 0\n", "    return 0\n", 1))
            p = env.run("--only", "B32", "--helper", path)
            self.assertEqual(parse(p.stdout)["B32.wsl-refusal"], ["FAIL"], p.stdout)
        finally:
            env.close()

    def test_non_wsl_skips_b32(self):
        env = Env(wsl=False)
        try:
            self.assertEqual(parse(env.run("--only", "B32").stdout)["B32.wsl-refusal"], ["SKIP"])
        finally:
            env.close()

    def test_b21_with_the_box_image_checks_each_shell(self):
        env = Env()
        try:
            p = env.run("--only", "B21", "--box-image", "swarmbox-test-img-fake")
            self.assertEqual(parse(p.stdout)["B21.shell-env"], ["PASS"], p.stdout)
            runs = [c for c in env.podman_calls() if c.startswith("run")]
            self.assertEqual(len(runs), 5)
            for c in runs:
                self.assertIn("-e SHELL", c)
                self.assertTrue(c.rstrip().endswith("init"))
        finally:
            env.close()

    def test_b21_skips_when_the_image_is_not_local_and_never_pulls(self):
        env = Env()
        try:
            p = env.run("--only", "B21", "--box-image", "swarmbox-test-img-fake", env={"FAKE_IMAGE_EXISTS_RC": "1"})
            self.assertEqual(parse(p.stdout)["B21.shell-env"], ["SKIP"])
            self.assertFalse([c for c in env.podman_calls() if c.startswith("run")])
            self.assertFalse([c for c in env.podman_calls() if c.startswith("pull")])
        finally:
            env.close()

    def test_workdir_parent_is_where_the_folder_goes(self):
        env = Env()
        try:
            parent = os.path.join(env.root, "elsewhere")
            os.makedirs(parent)
            p = env.run("--only", "env", "--workdir-parent", parent)
            self.assertIn("workdir=" + os.path.realpath(parent), p.stdout)
            self.assertEqual(os.listdir(parent), [])
            self.assertEqual(os.listdir(env.tmp), [])
            p = env.run("--only", "env", "--workdir-parent", os.path.join(env.root, "missing"))
            self.assertEqual(p.returncode, 2)
        finally:
            env.close()


class Safety(unittest.TestCase):
    def test_writes_nothing_outside_its_mktemp_folder_and_removes_it(self):
        env = Env(uname="Darwin", wsl=True, xcode_ok=True)
        try:
            home_before = env.tree(env.home)
            cwd_before = env.tree(env.cwd)
            p = env.run("--box-image", "swarmbox-test-img-fake")
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertEqual(env.tree(env.home), home_before)
            self.assertEqual(env.tree(env.cwd), cwd_before)
            self.assertEqual(env.tree(env.tmp), [], "the mktemp folder must be removed")
        finally:
            env.close()

    def test_the_mktemp_folder_is_removed_after_a_fail_too(self):
        env = Env()
        try:
            p = env.run(env={"FAKE_RUN_RC": "1"})
            self.assertEqual(p.returncode, 1)
            self.assertEqual(env.tree(env.tmp), [])
        finally:
            env.close()

    def test_the_repository_is_not_written(self):
        before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        env = Env(wsl=True)
        try:
            env.run()
        finally:
            env.close()
        after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_only_swarmbox_test_names_and_harmless_verbs_reach_podman(self):
        env = Env(uname="Darwin", wsl=True, xcode_ok=True)
        try:
            env.run("--box-image", "swarmbox-test-img-fake")
            calls = env.podman_calls()
            self.assertTrue(calls)
            for c in calls:
                verb = c.split()[0]
                self.assertIn(verb, ("--version", "version", "machine", "image", "run", "rm"), c)
                if verb == "machine":
                    self.assertEqual(c.split()[1], "list")
                if verb == "image":
                    self.assertEqual(c.split()[1], "exists")
                if verb == "run":
                    m = re.search(r"--name (\S+)", c)
                    self.assertTrue(m, c)
                    self.assertTrue(m.group(1).startswith("swarmbox-test-"), c)
                    self.assertIn("--rm", c.split())
                    for bad in ("--privileged", "-p ", "--publish", "--network=host", "--pid=host"):
                        self.assertNotIn(bad, c)
                if verb == "rm":
                    parts = c.split()
                    self.assertEqual(parts[1], "-f")
                    self.assertTrue(parts[2].startswith("swarmbox-test-"))
                    self.assertEqual(len(parts), 3)
        finally:
            env.close()

    def test_refuses_a_box_named_swarmbox(self):
        env = Env()
        try:
            for args, extra in ((["--name", "swarmbox"], {}), (["--name", "dev"], {}), (["--name", "swarmbox-test-"], {}),
                                ([], {"SWARMBOX_NAME": "swarmbox"}), ([], {"SWARMBOX_NAME": "dev"})):
                p = env.run(*args, env=extra)
                self.assertEqual(p.returncode, 2, (args, extra, p.stdout, p.stderr))
                self.assertEqual(p.stdout, "")
                self.assertIn("refusing", p.stderr)
            self.assertEqual(env.podman_calls(), [], "no Podman call may happen when the run is refused")
            ok = env.run("--only", "env", env={"SWARMBOX_NAME": "swarmbox-test-mine"})
            self.assertEqual(ok.returncode, 0)
        finally:
            env.close()

    def test_the_owner_swarmbox_variables_do_not_reach_the_helper(self):
        env = Env()
        try:
            p = env.run("--only", "B22,B32", env={"SWARMBOX_WORKSPACE": "/mnt/c/x", "SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": "leak",
                                                  "SWARMBOX_NAME": "swarmbox-test-mine"})
            self.assertEqual(parse(p.stdout)["B22.token-mode"], ["PASS"])
            self.assertNotIn("leak", p.stdout + p.stderr)
        finally:
            env.close()

    def test_the_real_owner_data_folder_is_only_read(self):
        env = Env()
        try:
            data = os.path.join(env.home, ".local", "share", "swarmbox", "host")
            os.makedirs(data)
            shutil.copytree(HELPER_DIR, data, dirs_exist_ok=True)
            with open(os.path.join(data, "tool-ports"), "w"):
                pass
            before = env.tree(env.home)
            p = env.run("--only", "env,B22,B23")
            self.assertEqual(parse(p.stdout)["B22.token-mode"], ["PASS"])
            m = re.search(r"helper=(\S+)", p.stdout)
            self.assertIn("swarmbox-owner-check.", m.group(1))   # the helper in use is the copy, never the installed original
            self.assertEqual(env.tree(env.home), before)
        finally:
            env.close()


@unittest.skipUnless(shutil.which("sudo"), "sudo missing")
class ReducedHostUid(unittest.TestCase):
    """[reduced] B7: the script as another UID (nobody, 65534) through sudo -n, with the fake podman. This proves the helper-side
    and script-side behavior for a host UID other than 1000 (create-flags, config, the mode rule, ownership of the file the
    fake container writes). It does NOT prove Podman's keep-id with a host UID other than 1000: that needs subuid ranges for the
    user (rootless Podman under `unshare --map-user=2000` answered 'keep-id requires additional UIDs or GIDs defined in
    /etc/subuid', recorded in the decision log), so B7 stays open with the owner."""

    def setUp(self):
        p = subprocess.run(["sudo", "-n", "-u", "nobody", "id", "-u"], capture_output=True, text=True)
        if p.returncode != 0 or p.stdout.strip() in ("", str(os.getuid())):
            self.skipTest("sudo -n -u nobody not possible here (reduced B7 not run)")
        self.nobody_uid = p.stdout.strip()

    def test_script_as_another_uid_in_a_mktemp_home(self):
        env = Env()
        try:
            # everything nobody touches lives in a world-accessible copy inside the scratch folder
            for d in (env.root, env.bin, env.home, env.tmp, env.cwd):
                os.chmod(d, 0o777)
            script_dir = os.path.join(env.root, "repo")
            shutil.copytree(os.path.join(ROOT, "dev"), os.path.join(script_dir, "dev"))
            shutil.copytree(HELPER_DIR, os.path.join(script_dir, "container", "host"))
            for dp, dn, fn in os.walk(script_dir):
                os.chmod(dp, 0o755)
                for n in fn:
                    os.chmod(os.path.join(dp, n), 0o755)
            os.chmod(env.log, 0o666)
            e = ["env", "PATH=" + env.base_env["PATH"], "HOME=" + env.home, "TMPDIR=" + env.tmp, "FAKE_LOG=" + env.log,
                 "SWARMBOX_CHECK_PROC_VERSION=" + env.pv, "SHELL=/bin/sh", "LC_ALL=C"]
            p = subprocess.run(["sudo", "-n", "-u", "nobody"] + e + ["sh", os.path.join(script_dir, "dev", "owner-check.sh")],
                               capture_output=True, text=True, cwd=env.cwd, timeout=120)
            self.assertIn("uid=" + self.nobody_uid, p.stdout, p.stdout + p.stderr)
            r = parse(p.stdout)
            self.assertEqual(r["B7.host-uid"], ["PASS"], p.stdout + p.stderr)
            self.assertEqual(r["B22.token-mode"], ["PASS"], p.stdout)
            self.assertEqual(r["B23.helper-sh"], ["PASS"], p.stdout)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(env.tree(env.tmp), [])
        finally:
            subprocess.run(["sudo", "-n", "-u", "nobody", "true"])
            env.close()


if __name__ == "__main__":
    unittest.main()
