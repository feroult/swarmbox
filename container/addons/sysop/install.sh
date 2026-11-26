#!/bin/bash
# Sysop installer. The sysop is stdlib Python and ships with the image: this copies the library into $ADDON_PREFIX, writes the launcher
# bin/swarmbox-sysop and runs the self-test. No network, no compiler. Called by `swarmbox-addon install sysop` with ADDON_PREFIX,
# ADDON_VERSION and ADDON_ARCH. Progress goes to stderr only.
set -euo pipefail

: "${ADDON_PREFIX:?ADDON_PREFIX is not set}"
: "${ADDON_VERSION:?ADDON_VERSION is not set (sysop is pinned)}"
case "$ADDON_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "sysop: refusing the version '$ADDON_VERSION'" >&2; exit 1 ;; esac

here=$(cd "$(dirname "$0")" && pwd)
[ -d "$here/lib/swarmbox_sysop" ] || { echo "sysop: $here/lib/swarmbox_sysop is missing" >&2; exit 1; }

# The agent registry library of the box (swarmbox_agents.py, stdlib): /usr/local/lib/swarmbox in the image, container/scripts in a checkout
# (SWARMBOX_TEST_LIB, the folder of dirs.sh, in the tests).
# The launcher puts its folder on PYTHONPATH; it is the box's, not a copy, so it follows the image.
agents_lib=
for d in "${SWARMBOX_TEST_LIB:-/nonexistent}" "$here/../../scripts" "$here/../.." /usr/local/lib/swarmbox; do
    if [ -f "$d/swarmbox_agents.py" ]; then agents_lib=$(cd "$d" && pwd -P); break; fi
done
[ -n "$agents_lib" ] || { echo "sysop: the agent registry library swarmbox_agents.py is missing" >&2; exit 1; }
case "$agents_lib" in *[!A-Za-z0-9/._-]*) echo "sysop: unusual path of the agent registry: $agents_lib" >&2; exit 1 ;; esac

mkdir -p "$ADDON_PREFIX/bin"
cp -R "$here/lib" "$ADDON_PREFIX/lib"
find "$ADDON_PREFIX/lib" -name __pycache__ -prune -exec rm -rf {} +

cat > "$ADDON_PREFIX/bin/swarmbox-sysop" << 'LAUNCHER'
#!/bin/sh
# swarmbox-sysop: the sysop addon (installed by `swarmbox addon install sysop`). The system python3, the library of this prefix.
prefix=$(cd "$(dirname "$0")/.." && pwd -P)
py=/usr/bin/python3
[ -x "$py" ] || py=python3
PYTHONPATH="$prefix/lib:@AGENTS_LIB@" exec "$py" -B -m swarmbox_sysop "$@"
LAUNCHER
sed -i "s#@AGENTS_LIB@#$agents_lib#" "$ADDON_PREFIX/bin/swarmbox-sysop"
chmod 755 "$ADDON_PREFIX/bin/swarmbox-sysop"

"$ADDON_PREFIX/bin/swarmbox-sysop" --self-test >&2 || {
    echo "sysop: the install finished but swarmbox-sysop --self-test failed" >&2
    exit 1
}
echo "sysop: installed $ADDON_VERSION" >&2
