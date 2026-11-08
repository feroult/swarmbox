#!/bin/bash
# clasp installer (design 6.4, 6.12): npm under --prefix, then the npm cache is cleaned.
# Called by `swarmbox-tool install clasp` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. Writes only below $TOOL_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

PACKAGE="@google/clasp"

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (clasp is pinned, D21)}"

# The install runs in a scratch environment, removed on exit, so nothing is written outside the prefix: node-gyp (a native dependency)
# unpacks Node headers into ~/.cache/node-gyp (measured in 4b.7: 2811 files, gemini) and a package's postinstall may run the program
# (measured in 4b.7: opencode wrote ~/.local/share/opencode/log). The npm cache is not touched (NPM_CONFIG_CACHE names it explicitly).
scratch=$(mktemp -d "${TMPDIR:-/tmp}/clasp-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export npm_config_devdir=$scratch/gyp XDG_DATA_HOME=$scratch/data XDG_STATE_HOME=$scratch/state XDG_CONFIG_HOME=$scratch/config XDG_CACHE_HOME=$scratch/cache

echo "clasp: installing $PACKAGE@$TOOL_VERSION" >&2
npm install -g --prefix "$TOOL_PREFIX" "$PACKAGE@$TOOL_VERSION" >&2
npm cache clean --force >&2 || echo "clasp: warning: npm cache clean failed (the cache is safe to lose)" >&2

if [ ! -x "$TOOL_PREFIX/bin/clasp" ]; then
    echo "clasp: the install finished but $TOOL_PREFIX/bin/clasp is missing" >&2
    exit 1
fi
echo "clasp: installed $PACKAGE@$TOOL_VERSION" >&2
