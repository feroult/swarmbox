#!/bin/bash
# The voice installer of the soak test: what container/addons/voice/install.sh does, minus the download and the build (no network, no compiler):
# the library, the web parts and the launcher are the real ones; whisper-cli is the fake of tests/fixtures/voice/whisper-fake and the model a
# placeholder file. The soak copies the addon to a scratch folder and puts this file in place of install.sh there.
set -euo pipefail
: "${ADDON_PREFIX:?}"
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$ADDON_PREFIX/bin" "$ADDON_PREFIX/libexec" "$ADDON_PREFIX/models"
cp "$SOAK_WHISPER" "$ADDON_PREFIX/libexec/whisper-cli"
chmod 755 "$ADDON_PREFIX/libexec/whisper-cli"
echo placeholder > "$ADDON_PREFIX/models/ggml-small.bin"
cp -R "$here/lib" "$ADDON_PREFIX/lib"
cp -R "$here/web" "$ADDON_PREFIX/web"
find "$ADDON_PREFIX/lib" -name __pycache__ -prune -exec rm -rf {} +
cat > "$ADDON_PREFIX/bin/swarmbox-voice" << 'LAUNCHER'
#!/bin/sh
prefix=$(cd "$(dirname "$0")/.." && pwd -P)
py=/usr/bin/python3
[ -x "$py" ] || py=python3
PYTHONPATH="$prefix/lib" exec "$py" -B -m swarmbox_voice "$@"
LAUNCHER
chmod 755 "$ADDON_PREFIX/bin/swarmbox-voice"
echo "voice: installed (soak stand-in)" >&2
