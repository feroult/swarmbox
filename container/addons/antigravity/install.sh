#!/bin/bash
# Antigravity CLI installer: the vendor's own release manifest and download, verified with the SHA-512 of that manifest. It does NOT run the
# vendor's install.sh, because that script ends with `agy install`, which edits the shell's startup files (SwarmBox owns those).
# Called by `swarmbox-addon install antigravity` with ADDON_PREFIX, ADDON_VERSION and ADDON_ARCH; runs as the agent user with HOME the workspace.
#
# Like claude, this is an UPDATE=self installer: the program lives in ~/.local/bin/agy (the place the vendor installer uses too) and updates itself.
# $ADDON_PREFIX only holds SwarmBox's record of the install. The binary inside the tarball is named `antigravity`; it is installed as `agy`.
# The program keeps its login and data in ~/.gemini/antigravity-cli and ~/.gemini/config (measured with 1.5.13): the folder Gemini CLI uses too.
# Progress goes to stderr only: stdout belongs to the addon being run.
set -euo pipefail

: "${ADDON_PREFIX:?ADDON_PREFIX is not set}"
: "${ADDON_VERSION:=latest}"
: "${ADDON_ARCH:=}"

BASE="https://antigravity-cli-auto-updater-974169037036.us-central1.run.app"

arch=$ADDON_ARCH
if [ -z "$arch" ]; then
    case "$(uname -m)" in
        x86_64 | amd64) arch=amd64 ;;
        arm64 | aarch64) arch=arm64 ;;
        *) echo "antigravity: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
    esac
fi
case "$arch" in amd64 | arm64) ;; *) echo "antigravity: unsupported architecture: $arch" >&2; exit 1 ;; esac

# a pinned version is not offered by the vendor (the manifest is always the newest); say so instead of installing another one
if [ "$ADDON_VERSION" != "latest" ]; then
    echo "antigravity: the vendor publishes only the newest release; version $ADDON_VERSION cannot be installed" >&2
    exit 1
fi

platform="linux_$arch"
if [ -f /lib/libc.musl-x86_64.so.1 ] || [ -f /lib/libc.musl-aarch64.so.1 ] || ldd /bin/ls 2>&1 | grep -q musl; then
    platform="${platform}_musl"
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/antigravity-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

echo "antigravity: reading the release manifest ($platform)" >&2
manifest=$(curl -fsSL "$BASE/manifests/$platform.json")
field() { printf '%s\n' "$manifest" | sed -n 's/.*"'"$1"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1; }
version=$(field version)
url=$(field url)
sha512=$(field sha512)
if [ -z "$url" ] || [ -z "$sha512" ]; then
    echo "antigravity: the release manifest has no url or sha512" >&2
    exit 1
fi
case "$url" in https://*) ;; *) echo "antigravity: the release url is not https: $url" >&2; exit 1 ;; esac

echo "antigravity: downloading ${version:-the newest release}" >&2
curl -fsSL -o "$scratch/payload" "$url"
actual=$(sha512sum "$scratch/payload" | cut -d' ' -f1)
if [ "$actual" != "$sha512" ]; then
    echo "antigravity: the download does not match the SHA-512 of the manifest: nothing installed" >&2
    exit 1
fi

case "$url" in
    *.tar.gz*) tar -xzf "$scratch/payload" -C "$scratch" antigravity; bin=$scratch/antigravity ;;
    *) bin=$scratch/payload ;;
esac

mkdir -p "$HOME/.local/bin"
chmod 755 "$bin"
# a copy next to the target, then a rename: a running agy is never overwritten in place
cp "$bin" "$HOME/.local/bin/.agy.$$"
mv -f "$HOME/.local/bin/.agy.$$" "$HOME/.local/bin/agy"

launcher="$HOME/.local/bin/agy"
if [ ! -x "$launcher" ]; then
    echo "antigravity: the install finished but $launcher is missing" >&2
    exit 1
fi

mkdir -p "$ADDON_PREFIX"
# the check runs with a scratch HOME: the program creates its folders in HOME the first time it runs
reported=$(HOME="$scratch/home" "$launcher" --version 2>/dev/null | head -n 1 || true)
printf 'requested=%s\nreported=%s\narch=%s\n' "$ADDON_VERSION" "$reported" "$arch" > "$ADDON_PREFIX/installed"
echo "antigravity: installed agy ${reported:-$version}" >&2
