#!/bin/bash
# Gemini CLI installer: npm under --prefix, then the npm cache is cleaned.
# Called by `swarmbox-tool install gemini` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. Writes only below $TOOL_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

PACKAGE="@google/gemini-cli"

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:=latest}"

# The install runs in a scratch environment, removed on exit, so nothing is written outside the prefix: node-gyp (a native dependency)
# unpacks Node headers into ~/.cache/node-gyp (measured in 4b.7: 2811 files, gemini) and a package's postinstall may run the program
# (measured in 4b.7: opencode wrote ~/.local/share/opencode/log). The npm cache is not touched (NPM_CONFIG_CACHE names it explicitly).
scratch=$(mktemp -d "${TMPDIR:-/tmp}/gemini-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export npm_config_devdir=$scratch/gyp XDG_DATA_HOME=$scratch/data XDG_STATE_HOME=$scratch/state XDG_CONFIG_HOME=$scratch/config XDG_CACHE_HOME=$scratch/cache

echo "gemini: installing $PACKAGE@$TOOL_VERSION" >&2
npm install -g --prefix "$TOOL_PREFIX" "$PACKAGE@$TOOL_VERSION" >&2
npm cache clean --force >&2 || echo "gemini: warning: npm cache clean failed (the cache is safe to lose)" >&2

if [ ! -x "$TOOL_PREFIX/bin/gemini" ]; then
    echo "gemini: the install finished but $TOOL_PREFIX/bin/gemini is missing" >&2
    exit 1
fi
echo "gemini: installed $PACKAGE@$TOOL_VERSION" >&2
