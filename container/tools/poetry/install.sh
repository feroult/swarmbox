#!/bin/bash
# Poetry installer: the official installer (https://install.python-poetry.org) with POETRY_HOME set to $TOOL_PREFIX.
# Called by `swarmbox-tool install poetry` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. The pip cache and Poetry's own config and cache
# go to a private temporary folder that is removed at the end, so nothing lands in ~/.cache or ~/.config.
# Progress goes to stderr only: stdout belongs to the tool being run.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (poetry is pinned)}"

scratch=$(mktemp -d "${TMPDIR:-/tmp}/poetry-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export XDG_CACHE_HOME="$scratch/cache" XDG_CONFIG_HOME="$scratch/config" XDG_DATA_HOME="$scratch/data"
export PIP_NO_CACHE_DIR=1 POETRY_HOME="$TOOL_PREFIX" POETRY_CONFIG_DIR="$scratch/config/pypoetry" POETRY_CACHE_DIR="$scratch/cache/pypoetry"

echo "poetry: installing Poetry $TOOL_VERSION with the official installer into $TOOL_PREFIX" >&2
# The script is read in full before it runs, so a failed download stops here and nothing half-runs.
script=$(curl -fsSL https://install.python-poetry.org)
printf '%s\n' "$script" | python3 - --version "$TOOL_VERSION" >&2

if [ ! -x "$TOOL_PREFIX/bin/poetry" ]; then
    echo "poetry: the installer finished but $TOOL_PREFIX/bin/poetry is missing" >&2
    exit 1
fi
if ! "$TOOL_PREFIX/bin/poetry" --version >/dev/null 2>&1; then
    echo "poetry: the installed program does not run (poetry --version failed)" >&2
    exit 1
fi
echo "poetry: installed $("$TOOL_PREFIX/bin/poetry" --version 2>/dev/null | head -n 1)" >&2
