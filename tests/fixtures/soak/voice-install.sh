#!/bin/bash
# The voice installer of the soak test: what container/tools/voice/install.sh does, minus the download and the build (no network, no compiler):
# the library, the web parts and the launcher are the real ones; whisper-cli is the fake of tests/fixtures/voice/whisper-fake and the model a
# placeholder file. The soak copies the tool to a scratch folder and puts this file in place of install.sh there.
set -euo pipefail
: "${TOOL_PREFIX:?}"
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$TOOL_PREFIX/bin" "$TOOL_PREFIX/libexec" "$TOOL_PREFIX/models"
cp "$SOAK_WHISPER" "$TOOL_PREFIX/libexec/whisper-cli"
chmod 755 "$TOOL_PREFIX/libexec/whisper-cli"
echo placeholder > "$TOOL_PREFIX/models/ggml-small.bin"
cp -R "$here/lib" "$TOOL_PREFIX/lib"
cp -R "$here/web" "$TOOL_PREFIX/web"
find "$TOOL_PREFIX/lib" -name __pycache__ -prune -exec rm -rf {} +
cat > "$TOOL_PREFIX/bin/swarmbox-voice" << 'LAUNCHER'
#!/bin/sh
prefix=$(cd "$(dirname "$0")/.." && pwd -P)
py=/usr/bin/python3
[ -x "$py" ] || py=python3
PYTHONPATH="$prefix/lib" exec "$py" -B -m swarmbox_voice "$@"
LAUNCHER
chmod 755 "$TOOL_PREFIX/bin/swarmbox-voice"
echo "voice: installed (soak stand-in)" >&2
