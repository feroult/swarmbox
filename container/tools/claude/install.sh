#!/bin/bash
# Claude Code installer (the vendor's native installer, not npm, so that `claude update` works).
# Called by `swarmbox-tool install claude` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH; runs as the agent user with HOME the workspace.
#
# This is the one installer that writes outside $TOOL_PREFIX: an UPDATE=self tool may write the paths of its own installer inside the
# workspace home (~/.local/bin/claude, ~/.local/share/claude, ~/.local/state/claude, ~/.cache/claude). This script itself never writes
# ~/.claude or ~/.claude.json (the user's login and settings), but the vendor installer creates both (measured).
# $TOOL_PREFIX only holds SwarmBox's record of the install.
# The vendor installer verifies its own download; SwarmBox records no checksum for it (design section 11).
# Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:=latest}"

# Version "latest" is passed as NO argument; any other value is passed as the one argument.
args=()
if [ "$TOOL_VERSION" != "latest" ]; then
    args=("$TOOL_VERSION")
fi

echo "claude: installing Claude Code (${TOOL_VERSION}) with the vendor's native installer" >&2
# The script is read in full before it runs, so a failed download stops here and nothing half-runs.
script=$(curl -fsSL https://claude.ai/install.sh)
printf '%s\n' "$script" | bash -s ${args[@]+"${args[@]}"} >&2

launcher="$HOME/.local/bin/claude"
if [ ! -x "$launcher" ]; then
    echo "claude: the vendor installer finished but $launcher is missing" >&2
    exit 1
fi

mkdir -p "$TOOL_PREFIX"
version=$("$launcher" --version 2>/dev/null | head -n 1 || true)
printf 'requested=%s\nreported=%s\narch=%s\n' "$TOOL_VERSION" "$version" "${TOOL_ARCH:-unknown}" > "$TOOL_PREFIX/installed"
echo "claude: installed ${version:-Claude Code}" >&2
