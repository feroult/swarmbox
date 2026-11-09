#!/bin/bash
# gcloud installer: Google's version-pinned tarball for the architecture, verified against the manifest's
# checksum BEFORE it is extracted, then extracted into $TOOL_PREFIX with its top directory "google-cloud-sdk" stripped (so
# $TOOL_PREFIX/bin/gcloud, gsutil and bq). The SDK's own install script is NOT run: it only edits shell startup files and asks about
# usage reporting, and the bin/ programs work in place with the bundled Python.
# Called by `swarmbox-tool install gcloud` with TOOL_PREFIX, TOOL_VERSION, TOOL_ARCH (amd64|arm64) and TOOL_SHA256. Progress goes to stderr only.
set -euo pipefail

: "${TOOL_PREFIX:?TOOL_PREFIX is not set}"
: "${TOOL_VERSION:?TOOL_VERSION is not set (gcloud is pinned)}"
: "${TOOL_ARCH:?TOOL_ARCH is not set}"
case "$TOOL_VERSION" in latest | "" | *[!0-9A-Za-z._-]*) echo "gcloud: refusing the version '$TOOL_VERSION'" >&2; exit 1 ;; esac
case "$TOOL_ARCH" in
    amd64) vendor_arch=x86_64 ;;
    arm64) vendor_arch=arm ;; # Google's name for 64-bit Arm
    *) echo "gcloud: unsupported architecture '$TOOL_ARCH'" >&2; exit 1 ;;
esac
if [[ ! "${TOOL_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "gcloud: TOOL_SHA256 is missing or not a 64-digit hexadecimal checksum: refusing to install an unverified download" >&2
    exit 1
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/gcloud-install.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
file="google-cloud-cli-$TOOL_VERSION-linux-$vendor_arch.tar.gz"
echo "gcloud: downloading $file (about 90 MB)" >&2
curl -fsSL --retry 3 -o "$scratch/$file" "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/$file" >&2

got=$(sha256sum "$scratch/$file" | cut -d' ' -f1)
want=$(printf '%s' "$TOOL_SHA256" | tr 'A-F' 'a-f')
if [ "$got" != "$want" ]; then
    echo "gcloud: checksum mismatch for $file: expected $want, computed $got. Nothing was installed." >&2
    exit 1
fi

tar -xzf "$scratch/$file" -C "$TOOL_PREFIX" --strip-components=1
for p in gcloud gsutil bq; do
    if [ ! -x "$TOOL_PREFIX/bin/$p" ]; then
        echo "gcloud: the install finished but $TOOL_PREFIX/bin/$p is missing" >&2
        exit 1
    fi
done
echo "gcloud: installed Google Cloud CLI $TOOL_VERSION ($TOOL_ARCH)" >&2
