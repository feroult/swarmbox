#!/bin/bash
# Go installer (design 6.4, 6.12; B25): the official tarball from go.dev, verified against the manifest's checksum BEFORE it is extracted,
# then extracted into $TOOL_PREFIX with its top directory "go" stripped (so $TOOL_PREFIX/bin/go and gofmt, and GOROOT is $TOOL_PREFIX).
# Called by `swarmbox-tool install go` with TOOL_PREFIX, TOOL_VERSION, TOOL_ARCH (amd64|arm64) and TOOL_SHA256. Progress goes to stderr only.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (go is pinned, D21)}"
: "${TOOL_ARCH:?TOOL_ARCH is not set}"
case "$TOOL_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "go: refusing the version '$TOOL_VERSION'" >&2; exit 1 ;; esac
case "$TOOL_ARCH" in amd64 | arm64) ;; *) echo "go: unsupported architecture '$TOOL_ARCH'" >&2; exit 1 ;; esac
if [[ ! "${TOOL_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "go: TOOL_SHA256 is missing or not a 64-digit hexadecimal checksum: refusing to install an unverified download" >&2
    exit 1
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/go-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
file="go$TOOL_VERSION.linux-$TOOL_ARCH.tar.gz"
echo "go: downloading $file" >&2
curl -fsSL --retry 3 -o "$scratch/$file" "https://go.dev/dl/$file" >&2

got=$(sha256sum "$scratch/$file" | cut -d' ' -f1)
want=$(printf '%s' "$TOOL_SHA256" | tr 'A-F' 'a-f')
if [ "$got" != "$want" ]; then
    echo "go: checksum mismatch for $file: expected $want, computed $got. Nothing was installed." >&2
    exit 1
fi

tar -xzf "$scratch/$file" -C "$TOOL_PREFIX" --strip-components=1
for p in go gofmt; do
    if [ ! -x "$TOOL_PREFIX/bin/$p" ]; then
        echo "go: the install finished but $TOOL_PREFIX/bin/$p is missing" >&2
        exit 1
    fi
done
echo "go: installed go$TOOL_VERSION ($TOOL_ARCH)" >&2
