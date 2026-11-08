#!/bin/bash
# Gemini CLI installer (design 6.4, 6.12): npm under --prefix, then the npm cache is cleaned.
# Called by `swarmbox-tool install gemini` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. Writes only below $TOOL_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

PACKAGE="@google/gemini-cli"

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:=latest}"

echo "gemini: installing $PACKAGE@$TOOL_VERSION" >&2
npm install -g --prefix "$TOOL_PREFIX" "$PACKAGE@$TOOL_VERSION" >&2
npm cache clean --force >&2 || echo "gemini: warning: npm cache clean failed (the cache is safe to lose)" >&2

if [ ! -x "$TOOL_PREFIX/bin/gemini" ]; then
    echo "gemini: the install finished but $TOOL_PREFIX/bin/gemini is missing" >&2
    exit 1
fi
echo "gemini: installed $PACKAGE@$TOOL_VERSION" >&2
