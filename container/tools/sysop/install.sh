#!/bin/bash
# Sysop installer. The sysop is stdlib Python and ships with the image: this copies the library into $TOOL_PREFIX, writes the launcher
# bin/swarmbox-sysop and runs the self-test. No network, no compiler. Called by `swarmbox-tool install sysop` with TOOL_PREFIX,
# TOOL_VERSION and TOOL_ARCH. Progress goes to stderr only.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (sysop is pinned)}"
case "$TOOL_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "sysop: refusing the version '$TOOL_VERSION'" >&2; exit 1 ;; esac

here=$(cd "$(dirname "$0")" && pwd)
[ -d "$here/lib/swarmbox_sysop" ] || { echo "sysop: $here/lib/swarmbox_sysop is missing" >&2; exit 1; }

mkdir -p "$TOOL_PREFIX/bin"
cp -R "$here/lib" "$TOOL_PREFIX/lib"
find "$TOOL_PREFIX/lib" -name __pycache__ -prune -exec rm -rf {} +

cat > "$TOOL_PREFIX/bin/swarmbox-sysop" << 'LAUNCHER'
#!/bin/sh
# swarmbox-sysop: the sysop tool (installed by `swarmbox tool install sysop`). The system python3, the library of this prefix.
prefix=$(cd "$(dirname "$0")/.." && pwd -P)
py=/usr/bin/python3
[ -x "$py" ] || py=python3
PYTHONPATH="$prefix/lib" exec "$py" -B -m swarmbox_sysop "$@"
LAUNCHER
chmod 755 "$TOOL_PREFIX/bin/swarmbox-sysop"

"$TOOL_PREFIX/bin/swarmbox-sysop" --self-test >&2 || {
    echo "sysop: the install finished but swarmbox-sysop --self-test failed" >&2
    exit 1
}
echo "sysop: installed $TOOL_VERSION" >&2
