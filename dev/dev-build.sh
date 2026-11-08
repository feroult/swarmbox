#!/bin/sh
# dev-build.sh: build the 2.0 image in the development box (a container with nested rootless Podman).
#
# There, apt inside a build fails with a setgroups error unless APT::Sandbox::User "root"; is set. That line is a
# property of this development box, not of the product, so it goes into a SCRATCH copy of the Dockerfile (a mktemp
# directory outside the repository) and never into ./Dockerfile. The build context stays the repository.
#
# Usage: dev/dev-build.sh [--tag swarmbox-test-<name>] [--keep-scratch] [--dry-run] [--no-cache]
#                         [--build-arg K=V]... [--dockerfile FILE]
# The tag must start with swarmbox-test- (the rule for everything a test creates); the default is
# swarmbox-test-img-<random>. Prints the tag on stdout. Remove the image by its exact name: podman rmi <tag>.
# --dry-run writes the scratch copy, prints "scratch: <dir>" on stderr and does not call podman.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=""
KEEP=0
DRY=0
DOCKERFILE=Dockerfile
EXTRA=""
while [ $# -gt 0 ]; do
    case $1 in
        --tag) [ $# -ge 2 ] || { echo "dev-build: --tag needs a value" >&2; exit 64; }; TAG=$2; shift 2 ;;
        --keep-scratch) KEEP=1; shift ;;
        --dry-run) DRY=1; KEEP=0; shift ;;
        --no-cache) EXTRA="$EXTRA --no-cache"; shift ;;
        --dockerfile) [ $# -ge 2 ] || { echo "dev-build: --dockerfile needs a value" >&2; exit 64; }; DOCKERFILE=$2; shift 2 ;;
        --build-arg) [ $# -ge 2 ] || { echo "dev-build: --build-arg needs a value" >&2; exit 64; }; EXTRA="$EXTRA --build-arg $2"; shift 2 ;;
        *) echo "dev-build: unknown option $1" >&2; exit 64 ;;
    esac
done
if [ -z "$TAG" ]; then
    TAG="swarmbox-test-img-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
fi
case $TAG in
    swarmbox-test-?*) ;;
    *) echo "dev-build: the image tag must start with swarmbox-test- (got '$TAG')" >&2; exit 64 ;;
esac
case $TAG in
    */*|*:*|*[!a-z0-9._-]*) echo "dev-build: the image tag must be a plain name: lowercase letters, digits, . _ - (got '$TAG')" >&2; exit 64 ;;
esac
SRC=$ROOT/$DOCKERFILE
[ -f "$SRC" ] || { echo "dev-build: $SRC not found" >&2; exit 66; }
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-dev-build.XXXXXX")
cleanup() { [ "$KEEP" = 1 ] || rm -rf "$SCRATCH"; }
trap cleanup EXIT HUP INT TERM
# the override goes right after the first FROM line (a global ARG before FROM stays valid)
awk -v done=0 '
    { print }
    !done && /^FROM / {
        print "RUN mkdir -p /etc/apt/apt.conf.d && echo '\''APT::Sandbox::User \"root\";'\'' > /etc/apt/apt.conf.d/99swarmbox-dev-sandbox"
        done = 1
    }' "$SRC" > "$SCRATCH/Dockerfile"
echo "scratch: $SCRATCH" >&2
if [ "$DRY" = 1 ]; then
    echo "$TAG"
    exit 0
fi
# shellcheck disable=SC2086  # EXTRA is a list of options built above
podman build $EXTRA -f "$SCRATCH/Dockerfile" -t "$TAG" "$ROOT"
echo "$TAG"
