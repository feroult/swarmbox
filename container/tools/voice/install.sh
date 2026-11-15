#!/bin/bash
# Voice installer. Builds whisper.cpp (CPU only, static) from the pinned release tarball, fetches ONE multilingual Whisper model,
# and copies the tool's own files (the Python library and the web page parts) into $TOOL_PREFIX.
#
# Called by `swarmbox-tool install voice` with TOOL_PREFIX, TOOL_VERSION (the whisper.cpp release) and TOOL_ARCH. Progress goes to
# stderr only. Needs network, a C++ compiler (the image has build-essential) and python3 with venv; cmake comes from a pinned
# PyPI wheel in a scratch venv, because the installer may not use apt. Both downloads are verified with SHA-256 BEFORE use.
#
# The model is $SWARMBOX_VOICE_STT_MODEL (default small; never an `.en` model: those only know English). Another model later:
# `swarmbox-voice model fetch NAME`. Result: bin/swarmbox-voice, libexec/whisper-cli, models/ggml-<model>.bin, lib/, web/.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (voice is pinned)}"
: "${TOOL_ARCH:?TOOL_ARCH is not set}"
case "$TOOL_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "voice: refusing the version '$TOOL_VERSION'" >&2; exit 1 ;; esac
case "$TOOL_ARCH" in amd64 | arm64) ;; *) echo "voice: unsupported architecture '$TOOL_ARCH'" >&2; exit 1 ;; esac

# The checksums pinned for the version in tool.conf. A new VERSION needs a new checksum (dev/record-checksums.sh does not cover it).
WHISPER_VERSION_PINNED=1.9.5
WHISPER_SRC_SHA256=ff1a9053feb509ff9d7729703355541ae9690073a6b1c40eb692c962e0dc1720
CMAKE_WHEEL=3.31.10
MODEL_REVISION=5359861c739e955e79d9a303bcbc70fb988958b1
# model name -> SHA-256 of ggml-<name>.bin at MODEL_REVISION (the same table as lib/swarmbox_voice/models.py; a test compares them)
declare -A MODEL_SHA256=(
    [tiny]=be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21
    [base]=60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
    [small]=1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b
    [medium]=6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208
    [large-v3]=64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2
    [large-v3-turbo]=1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69
)

if [ "$TOOL_VERSION" != "$WHISPER_VERSION_PINNED" ]; then
    echo "voice: this installer is pinned to whisper.cpp $WHISPER_VERSION_PINNED, not $TOOL_VERSION: update its checksum with the version" >&2
    exit 1
fi
model=${SWARMBOX_VOICE_STT_MODEL:-small}
case "$model" in
    *.en) echo "voice: '$model' is an English-only model; use a multilingual one (small, medium, ...)" >&2; exit 1 ;;
esac
if [ -z "${MODEL_SHA256[$model]:-}" ]; then
    echo "voice: unknown model '$model'; known: ${!MODEL_SHA256[*]}" >&2
    exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
[ -d "$here/lib" ] || { echo "voice: $here/lib is missing" >&2; exit 1; }

scratch=$(mktemp -d "${TMPDIR:-/tmp}/voice-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

verify() { # verify FILE SHA256 LABEL
    local got
    got=$(sha256sum "$1" | cut -d' ' -f1)
    if [ "$got" != "$2" ]; then
        echo "voice: checksum mismatch for $3: expected $2, computed $got. Nothing was installed." >&2
        exit 1
    fi
}

echo "voice: downloading whisper.cpp $TOOL_VERSION" >&2
curl -fsSL --retry 3 -o "$scratch/whisper.tar.gz" "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v$TOOL_VERSION.tar.gz" >&2
verify "$scratch/whisper.tar.gz" "$WHISPER_SRC_SHA256" "whisper.cpp $TOOL_VERSION"
mkdir "$scratch/src"
tar -xzf "$scratch/whisper.tar.gz" -C "$scratch/src" --strip-components=1

echo "voice: getting cmake $CMAKE_WHEEL" >&2
python3 -m venv "$scratch/venv" >&2
"$scratch/venv/bin/pip" install --quiet --disable-pip-version-check "cmake==$CMAKE_WHEEL" >&2
cmake="$scratch/venv/bin/cmake"

echo "voice: building whisper-cli (CPU only, this takes a few minutes)" >&2
flags=(-DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DGGML_NATIVE=OFF)
if [ "$TOOL_ARCH" = amd64 ]; then
    flags+=(-DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON)   # any x86-64 CPU since about 2013, so the build survives a move of the workspace
fi
"$cmake" -S "$scratch/src" -B "$scratch/build" "${flags[@]}" >&2
"$cmake" --build "$scratch/build" --target whisper-cli -j "$(nproc)" >&2

mkdir -p "$TOOL_PREFIX/bin" "$TOOL_PREFIX/libexec" "$TOOL_PREFIX/models"
cp "$scratch/build/bin/whisper-cli" "$TOOL_PREFIX/libexec/whisper-cli"
chmod 755 "$TOOL_PREFIX/libexec/whisper-cli"

echo "voice: downloading the model $model" >&2
curl -fsSL --retry 3 -o "$scratch/model.bin" "https://huggingface.co/ggerganov/whisper.cpp/resolve/$MODEL_REVISION/ggml-$model.bin" >&2
verify "$scratch/model.bin" "${MODEL_SHA256[$model]}" "model $model"
mv "$scratch/model.bin" "$TOOL_PREFIX/models/ggml-$model.bin"

cp -R "$here/lib" "$TOOL_PREFIX/lib"
if [ -d "$here/web" ]; then cp -R "$here/web" "$TOOL_PREFIX/web"; fi
find "$TOOL_PREFIX/lib" -name __pycache__ -prune -exec rm -rf {} +

cat > "$TOOL_PREFIX/bin/swarmbox-voice" << 'LAUNCHER'
#!/bin/sh
# swarmbox-voice: the voice tool (installed by `swarmbox tool install voice`). The system python3, the library of this prefix.
prefix=$(cd "$(dirname "$0")/.." && pwd -P)
py=/usr/bin/python3
[ -x "$py" ] || py=python3
PYTHONPATH="$prefix/lib" exec "$py" -B -m swarmbox_voice "$@"
LAUNCHER
chmod 755 "$TOOL_PREFIX/bin/swarmbox-voice"

SWARMBOX_VOICE_STT_MODEL=$model "$TOOL_PREFIX/bin/swarmbox-voice" --self-test >&2 || {
    echo "voice: the install finished but swarmbox-voice --self-test failed" >&2
    exit 1
}
echo "voice: installed whisper.cpp $TOOL_VERSION ($TOOL_ARCH) with the $model model" >&2
