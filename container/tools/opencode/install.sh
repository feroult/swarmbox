#!/bin/bash
# OpenCode installer (design 6.4, 6.12; B10): npm under --prefix, then the unused platform builds are removed.
# Called by `swarmbox-tool install opencode` with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH. Writes only below $TOOL_PREFIX (and npm's cache,
# cleaned at the end). Progress goes to stderr only: stdout belongs to the tool being run.
#
# THE PACKAGE CHOICE IS THIS ONE VARIABLE. "@opencode/cli" is the 2.x line that v0.1.0 installs; "opencode-ai" is a 1.x line. They are
# different release lines: a home written by one fails under the other ("Database is not empty and has no session table", B10), so do not
# swap them silently. See decision log [0.3] and [4b.2]. 2.x starts a shared background server per user account (`--standalone`
# avoids it) [unverified here: not exercised under the box's supervisor, see [4b.2]].
set -euo pipefail

PACKAGE="@opencode/cli"

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:=latest}"
: "${TOOL_ARCH:=}"

# The install runs in a scratch environment, removed on exit, so nothing is written outside the prefix: node-gyp (a native dependency)
# unpacks Node headers into ~/.cache/node-gyp (measured in 4b.7: 2811 files, gemini) and a package's postinstall may run the program
# (measured in 4b.7: opencode wrote ~/.local/share/opencode/log). The npm cache is not touched (NPM_CONFIG_CACHE names it explicitly).
scratch=$(mktemp -d "${TMPDIR:-/tmp}/opencode-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
export npm_config_devdir=$scratch/gyp XDG_DATA_HOME=$scratch/data XDG_STATE_HOME=$scratch/state XDG_CONFIG_HOME=$scratch/config XDG_CACHE_HOME=$scratch/cache

echo "opencode: installing $PACKAGE@$TOOL_VERSION" >&2
npm install -g --prefix "$TOOL_PREFIX" "$PACKAGE@$TOOL_VERSION" >&2
npm cache clean --force >&2 || echo "opencode: warning: npm cache clean failed (the cache is safe to lose)" >&2

# The package ships one build per platform and hard-links the right one to bin/opencode.exe. Keep the build(s) that file is linked to and
# remove the others. Never a fixed list of names: the count and the names move with the version and the architecture (B10).
# If no build can be identified as the linked one, NOTHING is removed (safe: the cost is disk, not a broken tool).
pkgdir="$TOOL_PREFIX/lib/node_modules/$PACKAGE"
exe="$pkgdir/bin/opencode.exe"
builds="$pkgdir/node_modules/@opencode"
[ -d "$builds" ] || builds="$pkgdir/node_modules"   # opencode-ai keeps its builds directly under node_modules

archtoken=x64
[ "$TOOL_ARCH" != arm64 ] || archtoken=arm64

if [ -f "$exe" ] && [ -d "$builds" ]; then
    keep=()
    others=()
    for d in "$builds"/*/; do
        [ -d "$d" ] || continue
        d=${d%/}
        if [ -n "$(find "$d" -type f -samefile "$exe" -print -quit 2>/dev/null)" ]; then
            keep+=("$d")
        else
            others+=("$d")
        fi
    done
    if [ "${#keep[@]}" -eq 0 ]; then
        echo "opencode: no platform build is hard-linked to bin/opencode.exe: nothing removed" >&2
    else
        for d in "${others[@]+"${others[@]}"}"; do
            # the current architecture's build is never removed, whatever the link says
            case "${d##*/}" in
                *-linux-"$archtoken") echo "opencode: keeping ${d##*/} (current architecture)" >&2; continue ;;
            esac
            rm -rf "$d"
        done
        echo "opencode: removed the unused platform builds, kept: ${keep[*]##*/}" >&2
    fi
else
    echo "opencode: the package layout is not the expected one (no bin/opencode.exe or no builds folder): nothing removed" >&2
fi

if ! "$TOOL_PREFIX/bin/opencode" --version >/dev/null 2>&1; then
    echo "opencode: the installed program does not run (opencode --version failed)" >&2
    exit 1
fi
echo "opencode: installed $("$TOOL_PREFIX/bin/opencode" --version 2>/dev/null | head -n 1)" >&2
