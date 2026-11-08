#!/bin/bash
# Maintainer script (design 6.4, 6.12; D29): records SHA256_amd64 and SHA256_arm64 of a tool's pinned download into its tool.conf.
# Run it by hand when the pinned VERSION of go or gcloud is bumped, then commit the changed tool.conf. It is NOT run by any test against
# the network (the tests use a fake curl) and it is not part of the image.
#
#   dev/record-checksums.sh go|gcloud [TOOL_CONF]     (default: container/tools/<tool>/tool.conf of this repository)
#
#   go      copies the checksums of go.dev's JSON listing (https://go.dev/dl/?mode=json, then &include=all for an older release), after
#           downloading both tarballs and checking that the computed checksum equals the listing's (B25). A mismatch refuses.
#   gcloud  downloads the version-pinned tarball for x86_64 and arm and records the checksum it computes (trust on first use, B11:
#           Google publishes a checksum only for the unversioned name, so there is nothing to compare with).
#
# Both checksums are written together, only after both downloads succeeded; the file is replaced atomically. Only the two SHA256_ lines
# change (an existing line is replaced in place, a missing one is appended). Exit: 0 done, 1 failed (conf untouched), 64 usage.
set -euo pipefail

die() { echo "record-checksums: $*" >&2; exit 1; }
usage() { echo "usage: dev/record-checksums.sh go|gcloud [TOOL_CONF]" >&2; exit 64; }

if [ $# -lt 1 ] || [ $# -gt 2 ]; then usage; fi
tool=$1
case "$tool" in go | gcloud) ;; *) usage ;; esac
root=$(cd "$(dirname "$0")/.." && pwd)
conf=${2:-$root/container/tools/$tool/tool.conf}
[ -f "$conf" ] || { echo "record-checksums: no such file: $conf" >&2; exit 64; }

version=$(sed -n 's/^VERSION=//p' "$conf" | head -n 1 | tr -d "\"'")
[ -n "$version" ] || die "$conf has no VERSION"
[ "$version" != latest ] || die "VERSION must be pinned (D21), found latest"
case "$version" in *[!0-9A-Za-z._-]*) die "VERSION '$version' has unexpected characters" ;; esac

work=$(mktemp -d "${TMPDIR:-/tmp}/record-checksums.XXXXXX")
trap 'rm -rf "$work"' EXIT

download() { # URL FILE
    curl -fsSL --retry 3 -o "$2" "$1" || die "download failed: $1"
    [ -s "$2" ] || die "download is empty: $1"
}
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

declare -A sums
case "$tool" in
    go)
        listing_sha() { # JSON ARCH -> checksum of the linux tarball of $version
            jq -r --arg v "go$version" --arg a "$2" \
                '[.[] | select(.version == $v) | .files[] | select(.os == "linux" and .arch == $a and .kind == "archive"
                  and (.filename | endswith(".tar.gz")))] | first | .sha256 // empty' "$1"
        }
        json="$work/listing.json"
        curl -fsSL --retry 3 -o "$json" "https://go.dev/dl/?mode=json" || die "cannot read go.dev's listing"
        if [ -z "$(listing_sha "$json" amd64 2>/dev/null)" ]; then
            curl -fsSL --retry 3 -o "$json" "https://go.dev/dl/?mode=json&include=all" || die "cannot read go.dev's full listing"
        fi
        for arch in amd64 arm64; do
            want=$(listing_sha "$json" "$arch" 2>/dev/null || true)
            [ -n "$want" ] || die "go$version linux-$arch is not in go.dev's listing"
            [[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "go.dev's checksum for linux-$arch is not 64 lowercase hex digits: $want"
            file="go$version.linux-$arch.tar.gz"
            download "https://go.dev/dl/$file" "$work/$file"
            got=$(sha_of "$work/$file")
            [ "$got" = "$want" ] || die "the computed checksum of $file ($got) does not match go.dev's listing ($want) for $arch"
            sums[$arch]=$got
        done
        ;;
    gcloud)
        for pair in amd64:x86_64 arm64:arm; do
            arch=${pair%%:*}
            file="google-cloud-cli-$version-linux-${pair##*:}.tar.gz"
            download "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/$file" "$work/$file"
            sums[$arch]=$(sha_of "$work/$file")
            rm -f "$work/$file"
        done
        ;;
esac

# One awk pass: replace the two lines in place, append what was missing, change nothing else.
awk -v amd="${sums[amd64]}" -v arm="${sums[arm64]}" '
    /^SHA256_amd64=/ { print "SHA256_amd64=" amd; da = 1; next }
    /^SHA256_arm64=/ { print "SHA256_arm64=" arm; dr = 1; next }
    { print }
    END { if (!da) print "SHA256_amd64=" amd; if (!dr) print "SHA256_arm64=" arm }
' "$conf" >"$work/new.conf"
# A conf that did not end with a newline gets one from awk's print; the mode of the file is kept.
cat "$work/new.conf" >"$work/final" && chmod --reference="$conf" "$work/final" && mv "$work/final" "$conf"
echo "record-checksums: $tool $version: SHA256_amd64=${sums[amd64]} SHA256_arm64=${sums[arm64]}" >&2
