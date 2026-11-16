"""The `voice` addon: its manifest and install.sh, with fake curl, fake python3/pip/cmake and a fake whisper source tarball.

No network, no compiler, no model: the fake curl serves a tiny tarball and a tiny "model" whose checksums are patched into a COPY of
install.sh (the real checksums pin the real downloads). The install must write only under $ADDON_PREFIX (and its own scratch folder,
which is removed), leave bin/swarmbox-voice working, refuse `.en` models, unknown models, wrong checksums and other versions, and
download only the pinned URLs. A real install (network, several minutes) is opt-in: SWARMBOX_REAL_VOICE_INSTALL=1.
Run with: python3 -W error tests/test_addon_voice.py
"""
import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_voice import models  # noqa: E402

ADDON = os.path.join(ROOT, "container", "addons", "voice")
ADDON_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")

FAKE_CURL = r"""#!/bin/sh
out= url=
while [ $# -gt 0 ]; do
    case $1 in
        -o) out=$2; shift ;;
        http*) url=$1 ;;
    esac
    shift
done
echo "$url" >> "$FAKE_LOG"
case $url in
    https://github.com/ggml-org/whisper.cpp/archive/refs/tags/*) cp "$FAKE_TARBALL" "$out" ;;
    https://huggingface.co/ggerganov/whisper.cpp/resolve/*) cp "$FAKE_MODEL" "$out" ;;
    *) echo "fake curl: unexpected URL $url" >&2; exit 22 ;;
esac
if [ -n "${FAKE_BAD:-}" ]; then echo tampered >> "$out"; fi
"""
FAKE_PYTHON = r"""#!/bin/sh
# only `python3 -m venv DIR` is faked: a venv whose pip does nothing and whose cmake makes a fake whisper-cli
if [ "$1" = -m ] && [ "$2" = venv ]; then
    mkdir -p "$3/bin"
    printf '#!/bin/sh\necho "pip $*" >> "$FAKE_LOG"\n' > "$3/bin/pip"
    cat > "$3/bin/cmake" <<'EOS'
#!/bin/sh
echo "cmake $*" >> "$FAKE_LOG"
if [ "$1" = -S ]; then
    build=$4
    mkdir -p "$build/bin"
    printf '#!/bin/sh\necho fake whisper\n' > "$build/bin/whisper-cli"
    chmod 755 "$build/bin/whisper-cli"
fi
EOS
    chmod 755 "$3/bin/pip" "$3/bin/cmake"
    exit 0
fi
echo "fake python3: unexpected call $*" >&2
exit 1
"""


def rd(path):
    with open(path) as f:
        return f.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, text, mode=0o755):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


class ManifestTests(unittest.TestCase):
    def test_manifest_passes_the_real_validator(self):
        p = subprocess.run(["bash", ADDON_SH, "validate", os.path.join(ROOT, "container", "addons")], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"], "HOME": tempfile.gettempdir()}, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("image/voice  (VERSION=", p.stdout)

    def test_manifest_fields(self):
        text = rd(os.path.join(ADDON, "addon.conf"))
        for line in ("SCHEMA=1", "NAME=voice", 'DESCRIPTION="Speak goals: microphone, Whisper"', 'COMMANDS="swarmbox-voice"'):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("PORTS=", text, "no published port: the service is loopback only")
        self.assertNotRegex(re.sub(r"(?m)^#.*$", "", text), "SHA256_")
        version = re.search(r"^VERSION=(\S+)$", text, re.M).group(1)
        self.assertNotEqual(version, "latest")
        self.assertIn("WHISPER_VERSION_PINNED=%s\n" % version, rd(os.path.join(ADDON, "install.sh")))

    def test_installer_is_executable_and_nothing_runs_at_image_build(self):
        self.assertTrue(os.stat(os.path.join(ADDON, "install.sh")).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(os.path.join(ADDON, "planners")), "voice only hears: it ships no planner")
        for name in ("install.sh", "prepare.sh", "addon.conf"):
            # the one allowed word: prepare.sh removes the planners folder of an old install
            text = "\n".join(l for l in rd(os.path.join(ADDON, name)).splitlines() if "an install from before voice became an input" not in l)
            for gone in ("planner", "claude", "login", "CLAUDE_CODE"):
                self.assertNotIn(gone, text.replace("voice only hears", ""), "%s still mentions %s" % (name, gone))
        dockerfile = rd(os.path.join(ROOT, "Dockerfile"))
        self.assertNotRegex(dockerfile, r"(?m)^[^#\n]*\bvoice\b")

    def test_model_table_of_the_installer_equals_the_python_one(self):
        text = rd(os.path.join(ADDON, "install.sh"))
        table = dict(re.findall(r"^\s+\[([a-z0-9-]+)\]=([0-9a-f]{64})$", text, re.M))
        self.assertEqual(table, {k: v[1] for k, v in models.MODELS.items()})
        self.assertIn("MODEL_REVISION=%s\n" % models.REVISION, text)
        self.assertFalse([k for k in table if k.endswith(".en")])


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-voiceinst."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "fakebin")
        self.home = os.path.join(self.tmp, "home")
        self.scratchroot = os.path.join(self.tmp, "tmpdir")
        self.prefix = os.path.join(self.tmp, "prefix")
        for d in (self.bin, self.home, self.scratchroot, self.prefix):
            os.mkdir(d)
        write(os.path.join(self.bin, "curl"), FAKE_CURL)
        write(os.path.join(self.bin, "python3"), FAKE_PYTHON)
        self.log = os.path.join(self.tmp, "fake.log")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            body = b"int main(){}\n"
            info = tarfile.TarInfo("whisper.cpp-fake/main.cpp")
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
        self.tarball = os.path.join(self.tmp, "src.tar.gz")
        with open(self.tarball, "wb") as f:
            f.write(buf.getvalue())
        self.model = os.path.join(self.tmp, "model.bin")
        with open(self.model, "wb") as f:
            f.write(b"fake ggml model")
        # a COPY of the addon folder whose installer pins the fake downloads
        self.addon = os.path.join(self.tmp, "voice")
        shutil.copytree(ADDON, self.addon, ignore=shutil.ignore_patterns("__pycache__"))
        text = rd(os.path.join(self.addon, "install.sh"))
        text = re.sub(r"WHISPER_SRC_SHA256=[0-9a-f]{64}", "WHISPER_SRC_SHA256=" + sha(Path(self.tarball).read_bytes()), text)
        for name in models.MODELS:
            text = re.sub(r"(\[%s\]=)[0-9a-f]{64}" % re.escape(name), r"\g<1>" + sha(b"fake ggml model"), text)
        write(os.path.join(self.addon, "install.sh"), text)

    def install(self, model=None, version="1.9.5", arch="amd64", bad=False, script=None):
        env = {"PATH": self.bin + ":" + os.environ["PATH"], "HOME": self.home, "TMPDIR": self.scratchroot, "ADDON_PREFIX": self.prefix,
               "ADDON_VERSION": version, "ADDON_ARCH": arch, "FAKE_LOG": self.log, "FAKE_TARBALL": self.tarball,
               "FAKE_MODEL": self.model}
        if model:
            env["SWARMBOX_VOICE_STT_MODEL"] = model
        if bad:
            env["FAKE_BAD"] = "1"
        return subprocess.run(["bash", script or os.path.join(self.addon, "install.sh")], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)

    def logged(self):
        return rd(self.log).splitlines() if os.path.exists(self.log) else []

    def test_install_writes_only_under_the_prefix_and_leaves_a_working_command(self):
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, "", "progress goes to stderr")
        for rel in ("bin/swarmbox-voice", "libexec/whisper-cli", "models/ggml-small.bin", "lib/swarmbox_voice/__init__.py",
                    "web/page.js", "web/page.css"):
            self.assertTrue(os.path.exists(os.path.join(self.prefix, rel)), rel)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "planners")))
        for rel in ("bin/swarmbox-voice", "libexec/whisper-cli"):
            self.assertTrue(os.access(os.path.join(self.prefix, rel), os.X_OK), rel)
        self.assertEqual(os.listdir(self.home), [], "nothing in the home")
        self.assertEqual(os.listdir(self.scratchroot), [], "the scratch folder is removed")
        self.assertFalse(list(self._pycache()), "no bytecode copied or written into the prefix")
        # the installed command runs from its own prefix, with no model setting in the environment of the box
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home}
        r = subprocess.run([os.path.join(self.prefix, "bin", "swarmbox-voice"), "--self-test"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([os.path.join(self.prefix, "bin", "swarmbox-voice"), "say", "--help"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("goal", r.stdout)

    def _pycache(self):
        for d, dirs, _ in os.walk(self.prefix):
            for n in dirs:
                if n == "__pycache__":
                    yield os.path.join(d, n)

    def test_only_the_pinned_urls_are_fetched_and_cmake_is_pinned(self):
        self.assertEqual(self.install(model="medium").returncode, 0)
        urls = [x for x in self.logged() if x.startswith("http")]
        self.assertEqual(urls, ["https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v1.9.5.tar.gz",
                                "https://huggingface.co/ggerganov/whisper.cpp/resolve/%s/ggml-medium.bin" % models.REVISION])
        self.assertTrue(os.path.exists(os.path.join(self.prefix, "models", "ggml-medium.bin")))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "models", "ggml-small.bin")), "only the chosen model")
        pip = [x for x in self.logged() if x.startswith("pip ")]
        self.assertEqual(len(pip), 1)
        self.assertRegex(pip[0], r"cmake==\d+\.\d+\.\d+$")
        cm = [x for x in self.logged() if x.startswith("cmake ")]
        self.assertTrue(any("-DBUILD_SHARED_LIBS=OFF" in x and "-DCMAKE_BUILD_TYPE=Release" in x for x in cm), cm)
        self.assertTrue(any("--target whisper-cli" in x for x in cm), cm)

    def test_en_and_unknown_models_are_refused_before_any_download(self):
        for model in ("small.en", "tiny.en", "nosuch", "../small", "Small"):
            shutil.rmtree(self.prefix)
            os.mkdir(self.prefix)
            p = self.install(model=model)
            self.assertNotEqual(p.returncode, 0, model)
            self.assertEqual(self.logged(), [], model)
            self.assertEqual(os.listdir(self.prefix), [], model)

    def test_a_wrong_checksum_installs_nothing(self):
        p = self.install(bad=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("checksum mismatch", p.stderr)
        self.assertEqual(os.listdir(self.prefix), [])
        self.assertEqual(os.listdir(self.scratchroot), [])
        self.assertEqual([x for x in self.logged() if x.startswith("pip ")], [], "stopped before getting cmake")

    def test_a_wrong_model_checksum_leaves_no_model_and_fails(self):
        text = rd(os.path.join(self.addon, "install.sh"))
        text = re.sub(r"(\[small\]=)[0-9a-f]{64}", r"\g<1>" + "0" * 64, text)
        script = os.path.join(self.addon, "install-badmodel.sh")
        write(script, text)
        p = self.install(script=script)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("checksum mismatch for model small", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "models", "ggml-small.bin")))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "bin", "swarmbox-voice")))

    def test_other_versions_and_architectures_are_refused(self):
        for kw in ({"version": "1.8.0"}, {"version": "latest"}, {"version": "1.9.5;rm"}, {"arch": "riscv"}):
            self.assertNotEqual(self.install(**kw).returncode, 0, kw)
        self.assertEqual(self.logged(), [])

    def test_the_real_installer_passes_the_lint_and_has_no_apt_or_sudo(self):
        text = rd(os.path.join(ADDON, "install.sh"))
        self.assertNotRegex(re.sub(r"(?m)^\s*#.*$", "", text), r"\b(apt|apt-get|sudo)\b")
        self.assertNotIn("ADDON_SHA256", text)
        self.assertNotRegex(text, r"ggml-[a-z0-9-]*\.en")


@unittest.skipUnless(os.environ.get("SWARMBOX_REAL_VOICE_INSTALL") == "1", "set SWARMBOX_REAL_VOICE_INSTALL=1 (network, a compiler, minutes)")
class RealInstall(unittest.TestCase):
    def test_real_install_with_the_tiny_model(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-voicereal.")
        self.addCleanup(shutil.rmtree, tmp, True)
        prefix = os.path.join(tmp, "prefix")
        os.mkdir(prefix)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "TMPDIR": tmp, "ADDON_PREFIX": prefix, "ADDON_VERSION": "1.9.5",
               "ADDON_ARCH": "arm64" if os.uname().machine in ("aarch64", "arm64") else "amd64", "SWARMBOX_VOICE_STT_MODEL": "tiny"}
        p = subprocess.run(["bash", os.path.join(ADDON, "install.sh")], env=env, capture_output=True, text=True, timeout=3600)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        self.assertTrue(os.access(os.path.join(prefix, "libexec", "whisper-cli"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
