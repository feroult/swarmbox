#!/bin/sh
# release-version.sh TAG: maps a release tag to the image tags (used by .github/workflows/release.yml).
#
#   dev/release-version.sh v2.0.0
#   version=2.0.0
#   minor=2.0
#   tags=2.0.0 2.0 latest
#
# Accepted: vX.Y.Z (a release) and vX.Y.Z-beta.N or vX.Y.Z-rc.N (a prerelease): numbers without leading zeros, a lowercase v,
# nothing else. A prerelease gets exactly one image tag (its own version): never `X.Y` and never `latest`, which belong to
# the final releases. Build suffixes (+) and any other prerelease name are refused.
# Output is key=value lines on stdout (safe to append to $GITHUB_OUTPUT); errors go to stderr. Exit: 0 ok, 1 refused,
# 64 usage. It reads no file, runs no other program and uses no network.
set -eu

fail() { echo "release-version: $*" >&2; exit 1; }

[ $# -eq 1 ] || { echo "usage: dev/release-version.sh vX.Y.Z" >&2; exit 64; }
tag=$1

pre=""
case $tag in
    *+*) fail "'$tag' has a build suffix; not supported." ;;
    *-*)
        pre=${tag#*-}
        tag=${tag%%-*}
        # beta.N or rc.N, N a number without a leading zero (1 or more digits, first not 0)
        case $pre in
            beta.[1-9] | beta.[1-9][0-9]* | rc.[1-9] | rc.[1-9][0-9]*) ;;
            *) fail "'$tag-$pre': the only prerelease forms are -beta.N and -rc.N (N from 1, no leading zero)." ;;
        esac
        case ${pre#*.} in *[!0-9]*) fail "'$tag-$pre': the prerelease number is not a number." ;; esac
        ;;
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

if [ -n "$pre" ]; then
    echo "version=$major.$minor.$patch-$pre"
    echo "minor="
    echo "tags=$major.$minor.$patch-$pre"
    echo "prerelease=true"
else
    echo "version=$major.$minor.$patch"
    echo "minor=$major.$minor"
    echo "tags=$major.$minor.$patch $major.$minor latest"
    echo "prerelease=false"
fi
