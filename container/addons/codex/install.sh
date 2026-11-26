#!/bin/bash
# OpenAI Codex CLI installer: npm under --prefix. The package `@openai/codex` is a small Node launcher with the native program of the platform
# as an optional dependency (npm installs only the one of this machine: measured with 0.172.0, @openai/codex-linux-x64).
# Called by `swarmbox-addon install codex` with ADDON_PREFIX, ADDON_VERSION and ADDON_ARCH. Writes only below $ADDON_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the addon being run.
set -euo pipefail

PACKAGE="@openai/codex"

: "${ADDON_PREFIX:?ADDON_PREFIX is not set}"
: "${ADDON_VERSION:=latest}"

# The install runs in a scratch environment, removed on exit, so nothing is written outside the prefix (a postinstall may run the program).
scratch=$(mktemp -d "${TMPDIR:-/tmp}/codex-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export npm_config_devdir=$scratch/gyp XDG_DATA_HOME=$scratch/data XDG_STATE_HOME=$scratch/state XDG_CONFIG_HOME=$scratch/config XDG_CACHE_HOME=$scratch/cache
export CODEX_HOME=$scratch/codex-home

echo "codex: installing $PACKAGE@$ADDON_VERSION" >&2
npm install -g --prefix "$ADDON_PREFIX" "$PACKAGE@$ADDON_VERSION" >&2
npm cache clean --force >&2 || echo "codex: warning: npm cache clean failed (the cache is safe to lose)" >&2

if ! "$ADDON_PREFIX/bin/codex" --version >/dev/null 2>&1; then
    echo "codex: the installed program does not run (codex --version failed)" >&2
    exit 1
fi
echo "codex: installed $("$ADDON_PREFIX/bin/codex" --version 2>/dev/null | head -n 1)" >&2
