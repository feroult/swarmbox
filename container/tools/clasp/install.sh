#!/bin/bash
# clasp installer (design 6.4, 6.12): npm under --prefix, then the npm cache is cleaned.
# Called by `swarmbox-tool install clasp` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. Writes only below $TOOL_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

PACKAGE="@google/clasp"

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (clasp is pinned, D21)}"

echo "clasp: installing $PACKAGE@$TOOL_VERSION" >&2
npm install -g --prefix "$TOOL_PREFIX" "$PACKAGE@$TOOL_VERSION" >&2
npm cache clean --force >&2 || echo "clasp: warning: npm cache clean failed (the cache is safe to lose)" >&2

if [ ! -x "$TOOL_PREFIX/bin/clasp" ]; then
    echo "clasp: the install finished but $TOOL_PREFIX/bin/clasp is missing" >&2
    exit 1
fi
echo "clasp: installed $PACKAGE@$TOOL_VERSION" >&2
