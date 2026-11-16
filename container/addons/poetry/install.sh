#!/bin/bash
# Poetry installer: the official installer (https://install.python-poetry.org) with POETRY_HOME set to $ADDON_PREFIX.
# Called by `swarmbox-addon install poetry` with ADDON_PREFIX, ADDON_VERSION and ADDON_ARCH. The pip cache and Poetry's own config and cache
# go to a private temporary folder that is removed at the end, so nothing lands in ~/.cache or ~/.config.
# Progress goes to stderr only: stdout belongs to the addon being run.
set -euo pipefail

: "${ADDON_PREFIX:?ADDON_PREFIX is not set}"
: "${ADDON_VERSION:?ADDON_VERSION is not set (poetry is pinned)}"

scratch=$(mktemp -d "${TMPDIR:-/tmp}/poetry-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export XDG_CACHE_HOME="$scratch/cache" XDG_CONFIG_HOME="$scratch/config" XDG_DATA_HOME="$scratch/data"
export PIP_NO_CACHE_DIR=1 POETRY_HOME="$ADDON_PREFIX" POETRY_CONFIG_DIR="$scratch/config/pypoetry" POETRY_CACHE_DIR="$scratch/cache/pypoetry"

echo "poetry: installing Poetry $ADDON_VERSION with the official installer into $ADDON_PREFIX" >&2
# The script is read in full before it runs, so a failed download stops here and nothing half-runs.
script=$(curl -fsSL https://install.python-poetry.org)
printf '%s\n' "$script" | python3 - --version "$ADDON_VERSION" >&2

if [ ! -x "$ADDON_PREFIX/bin/poetry" ]; then
    echo "poetry: the installer finished but $ADDON_PREFIX/bin/poetry is missing" >&2
    exit 1
fi
if ! "$ADDON_PREFIX/bin/poetry" --version >/dev/null 2>&1; then
    echo "poetry: the installed program does not run (poetry --version failed)" >&2
    exit 1
fi
echo "poetry: installed $("$ADDON_PREFIX/bin/poetry" --version 2>/dev/null | head -n 1)" >&2
