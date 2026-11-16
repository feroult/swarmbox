#!/bin/bash
# Go installer: the official tarball from go.dev, verified against the manifest's checksum BEFORE it is extracted,
# then extracted into $ADDON_PREFIX with its top directory "go" stripped (so $ADDON_PREFIX/bin/go and gofmt, and GOROOT is $ADDON_PREFIX).
# Called by `swarmbox-addon install go` with ADDON_PREFIX, ADDON_VERSION, ADDON_ARCH (amd64|arm64) and ADDON_SHA256. Progress goes to stderr only.
set -euo pipefail

: "${ADDON_PREFIX:?ADDON_PREFIX is not set}"
: "${ADDON_VERSION:?ADDON_VERSION is not set (go is pinned)}"
: "${ADDON_ARCH:?ADDON_ARCH is not set}"
case "$ADDON_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "go: refusing the version '$ADDON_VERSION'" >&2; exit 1 ;; esac
case "$ADDON_ARCH" in amd64 | arm64) ;; *) echo "go: unsupported architecture '$ADDON_ARCH'" >&2; exit 1 ;; esac
if [[ ! "${ADDON_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "go: ADDON_SHA256 is missing or not a 64-digit hexadecimal checksum: refusing to install an unverified download" >&2
    exit 1
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/go-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
file="go$ADDON_VERSION.linux-$ADDON_ARCH.tar.gz"
echo "go: downloading $file" >&2
curl -fsSL --retry 3 -o "$scratch/$file" "https://go.dev/dl/$file" >&2

got=$(sha256sum "$scratch/$file" | cut -d' ' -f1)
want=$(printf '%s' "$ADDON_SHA256" | tr 'A-F' 'a-f')
if [ "$got" != "$want" ]; then
    echo "go: checksum mismatch for $file: expected $want, computed $got. Nothing was installed." >&2
    exit 1
fi

tar -xzf "$scratch/$file" -C "$ADDON_PREFIX" --strip-components=1
for p in go gofmt; do
    if [ ! -x "$ADDON_PREFIX/bin/$p" ]; then
        echo "go: the install finished but $ADDON_PREFIX/bin/$p is missing" >&2
        exit 1
    fi
done
echo "go: installed go$ADDON_VERSION ($ADDON_ARCH)" >&2
