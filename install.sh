#!/bin/sh
# install.sh: install the `swarmbox` command from a GitHub release (the other way is `podman run --rm IMAGE install | sh`).
#
#   sh install.sh [--version X.Y.Z] [--image REF] [--with TOOLS]
#
# Downloads the `swarmbox` script of the release, checks it against the published `swarmbox.sha256`, writes it to
# ${SWARMBOX_BIN_DIR:-$HOME/.local/bin}/swarmbox (mode 755, through a temporary file and a rename), then runs `swarmbox setup`: it checks
# Podman (4.3 or newer), fetches the support files from the image, records the image and the tools in the SwarmBox config file, and
# says what to run next. It edits no shell startup file, and running it again changes nothing that is already right.
# Without --version the latest release is installed; without --image the image is REPO:VERSION.
# SWARMBOX_RELEASE_URL replaces the download folder (tests use file://).
set -eu

# The image repository: the same value as SWARMBOX_DEFAULT_IMAGE_REPO in container/host/DEFAULTS (a test compares them).
REPO='ghcr.io/<org>/swarmbox'
VERSION=
IMAGE=
WITH=

fail() { echo "install.sh: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
    [ $# -ge 2 ] || fail "usage: sh install.sh [--version X.Y.Z] [--image REF] [--with TOOLS]"
    case $1 in
        --version) VERSION=$2 ;;
        --image) IMAGE=$2 ;;
        --with) WITH=$2 ;;
        *) fail "usage: sh install.sh [--version X.Y.Z] [--image REF] [--with TOOLS]" ;;
    esac
    shift 2
done
case $VERSION in ''|[0-9]*.[0-9]*.[0-9]*) ;; *) fail "--version must look like 2.0.0" ;; esac
case $VERSION$IMAGE in *[!A-Za-z0-9._/:@-]*) fail "--version or --image has a character that is not allowed" ;; esac
command -v podman > /dev/null 2>&1 || fail "Podman is not installed (https://podman.io/docs/installation)."
command -v curl > /dev/null 2>&1 || fail "curl is not installed."

if [ -n "$VERSION" ]; then URL=https://github.com/${REPO#*/}/releases/download/v$VERSION; else URL=https://github.com/${REPO#*/}/releases/latest/download; fi
URL=${SWARMBOX_RELEASE_URL:-$URL}
BIN=${SWARMBOX_BIN_DIR:-${HOME:?HOME is not set}/.local/bin}
mkdir -p "$BIN"
tmp=$(mktemp "$BIN/.swarmbox.XXXXXX")
trap 'rm -f "$tmp" "$tmp.sha256"' EXIT
curl -fsSL -o "$tmp" "$URL/swarmbox" || fail "cannot download $URL/swarmbox"
curl -fsSL -o "$tmp.sha256" "$URL/swarmbox.sha256" || fail "cannot download $URL/swarmbox.sha256"
want=$(cut -d ' ' -f 1 < "$tmp.sha256")
if command -v sha256sum > /dev/null 2>&1; then got=$(sha256sum < "$tmp" | cut -d ' ' -f 1); else got=$(shasum -a 256 < "$tmp" | cut -d ' ' -f 1); fi
[ -n "$want" ] && [ "$want" = "$got" ] || fail "the checksum of swarmbox does not match $URL/swarmbox.sha256; nothing was installed."
chmod 755 "$tmp"
[ -n "$VERSION" ] || VERSION=$("$tmp" version)
mv -f "$tmp" "$BIN/swarmbox"
rm -f "$tmp.sha256"
trap - EXIT
exec "$BIN/swarmbox" setup --image "${IMAGE:-${REPO}:$VERSION}" ${WITH:+--with "$WITH"}
