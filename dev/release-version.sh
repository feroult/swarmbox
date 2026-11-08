#!/bin/sh
# release-version.sh TAG: maps a release tag to the image tags (design 10.4, D32; used by .github/workflows/release.yml).
#
#   dev/release-version.sh v2.0.0
#   version=2.0.0
#   minor=2.0
#   tags=2.0.0 2.0 latest
#
# Only vX.Y.Z is accepted: numbers without leading zeros, a lowercase v, nothing after the patch number. A prerelease
# (v2.0.0-rc.1) or build suffix is refused, because the design defines no tag scheme for one (decision log [7.5]).
# Output is key=value lines on stdout (safe to append to $GITHUB_OUTPUT); errors go to stderr. Exit: 0 ok, 1 refused,
# 64 usage. It reads no file, runs no other program and uses no network.
set -eu

fail() { echo "release-version: $*" >&2; exit 1; }

[ $# -eq 1 ] || { echo "usage: dev/release-version.sh vX.Y.Z" >&2; exit 64; }
tag=$1

case $tag in
    *-* | *+*) fail "'$tag' looks like a prerelease or build tag; only vX.Y.Z releases are published (no prerelease scheme in the design)." ;;
esac
# A newline would defeat the pattern match below (case matches the whole string, but be explicit).
case $tag in
    *'
'*) fail "the tag holds a newline." ;;
esac
# v, then three numbers with no leading zero: a single 0 or a digit 1-9 followed by digits.
case $tag in
    v*.*.*) ;;
    *) fail "'$tag' is not of the form vX.Y.Z." ;;
esac
rest=${tag#v}
major=${rest%%.*}
rest=${rest#*.}
minor=${rest%%.*}
patch=${rest#*.}
for part in "$major" "$minor" "$patch"; do
    case $part in
        *[!0-9]* | '') fail "'$tag' is not of the form vX.Y.Z (number '$part')." ;;
        0) ;;
        0*) fail "'$tag' has a number with a leading zero ('$part')." ;;
    esac
done

echo "version=$major.$minor.$patch"
echo "minor=$major.$minor"
echo "tags=$major.$minor.$patch $major.$minor latest"
