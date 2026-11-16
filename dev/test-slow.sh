#!/bin/sh
# test-slow.sh: run the integration tests (tests/slow) in Podman, in the test image, with real tmux, ttyd, Chromium and a pty.
#
# Usage: sh dev/test-slow.sh [slow|fast|all] [--tmux 35|37] [--image IMAGE] [--build] [--online] [--shell] [-- RUNNER OPTIONS]
#   slow (default)   tests/slow, with SWARMBOX_TEST_REAL_TMUX=1: the gate that lets the real-tmux and browser tests run, which only a
#                    container may set (never on a machine whose tmux you use)
#   fast | all       the same container for tests/fast (or both): the offline, read-only-root world of a CI runner
#   --tmux 35|37     tmux 3.5a (Debian 13, the default) or 3.7c (the version of the product image); selects the image tag
#   --image IMAGE    use this image as it is (it must be built from dev/test-image/Containerfile or have the same programs)
#   --build          build the image again even when it exists
#   --online         give the container a network (the tests that need one say so; the default is none)
#   --shell          open a shell in the container instead of running tests (the repository is copied to /work/repo)
#   after --         options for tests/run.sh (-j N, --only a.py, --list, --repeat N, --werror, ...)
# The image is swarmbox-test-slow:tmux35 or :tmux37, built from dev/test-image/Containerfile when it is missing (needs a network once).
# The container is named swarmbox-test-slow-<pid>, runs with --read-only, a tmpfs /work and /tmp, the checkout mounted read-only (it is
# copied to /work/repo) and is removed when it ends. Nothing is written to the checkout and no port is published.
# Exit status: the runner's (0 passed, 1 a file failed, 2 usage); 3 when podman or the image is not there.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 3
SEL=slow
TMUXV=35
IMAGE=
BUILD=0
ONLINE=0
SHELL_ONLY=0
while [ $# -gt 0 ]; do
    case $1 in
        slow|fast|all) SEL=$1; shift ;;
        --tmux) [ $# -ge 2 ] || { echo "test-slow: --tmux needs 35 or 37" >&2; exit 2; }; TMUXV=$2; shift 2 ;;
        --image) [ $# -ge 2 ] || { echo "test-slow: --image needs a name" >&2; exit 2; }; IMAGE=$2; shift 2 ;;
        --build) BUILD=1; shift ;;
        --online) ONLINE=1; shift ;;
        --shell) SHELL_ONLY=1; shift ;;
        --) shift; break ;;
        *) echo "test-slow: unknown option $1" >&2; exit 2 ;;
    esac
done
case $TMUXV in
    35) VARIANT=stock ;;
    37) VARIANT=backport ;;
    *) echo "test-slow: --tmux is 35 or 37" >&2; exit 2 ;;
esac
command -v podman > /dev/null 2>&1 || { echo "test-slow: podman is not installed" >&2; exit 3; }
[ -n "$IMAGE" ] || IMAGE=swarmbox-test-slow:tmux$TMUXV

if [ "$BUILD" = 1 ] || ! podman image exists "$IMAGE" > /dev/null 2>&1; then
    case $IMAGE in swarmbox-test-slow:*) ;; *) echo "test-slow: image $IMAGE does not exist" >&2; exit 3 ;; esac
    echo "test-slow: building $IMAGE from dev/test-image/Containerfile (tmux variant $VARIANT) ..." >&2
    podman build -f "$ROOT/dev/test-image/Containerfile" --build-arg "TMUX_VARIANT=$VARIANT" -t "$IMAGE" "$ROOT/dev/test-image" || exit 3
fi

NAME=swarmbox-test-slow-$$
cleanup() { podman rm -f "$NAME" > /dev/null 2>&1; }
trap 'cleanup; exit 130' INT TERM HUP
NET=none
[ "$ONLINE" = 0 ] || NET=slirp4netns
TTY=
[ "$SHELL_ONLY" = 0 ] || TTY=-it
if [ "$SHELL_ONLY" = 1 ]; then
    CMD='cp -r /src /work/repo 2>/dev/null; cd /work/repo && exec bash'
else
    CMD='cp -r /src /work/repo 2>/dev/null; cd /work/repo && HOME=/work/home TMPDIR=/tmp exec sh tests/run.sh "$@"'
fi
# shellcheck disable=SC2086  # TTY is empty or one option
podman run --rm $TTY --name "$NAME" --network "$NET" --read-only --userns=keep-id:uid=1000,gid=1000 \
    -e SWARMBOX_TEST_REAL_TMUX=1 -e PYTHONDONTWRITEBYTECODE=1 -e LANG=C.UTF-8 \
    -v "$ROOT":/src:ro --tmpfs /work:rw,exec,mode=1777,size=4g --tmpfs /tmp:rw,exec,mode=1777,size=2g \
    "$IMAGE" sh -c "$CMD" test-slow "$SEL" "$@"
rc=$?
cleanup
exit $rc
