#!/bin/bash
# Soak and fault test of version 1 with the whole stack in Podman (see the docstring of tests/soak_v1.py). NOT part of the fast gate.
#
#   tests/soak_v1.sh [-i IMAGE] [-r RESULTS_DIR] [-- soak_v1.py arguments, e.g. --minutes 40 --faults bus-kill,disk-full --real 3]
#
# IMAGE defaults to localhost/swarmbox-sysop-test (tmux 3.5a, claude CLI, ttyd, python3); localhost/tmuxfacts-test37 has tmux 3.7c, the version of the box
# image. The container is the box in miniature: a tmpfs /work for everything, a small tmpfs /state for the state folder (so that a full disk can be
# made), and a bash as PID 1 (like the entrypoint of the box, it reaps orphans). Run at most two of these at a time.
#
# The login: only the real goals (--real N, default 3) use it. CLAUDE_CODE_OAUTH_TOKEN from the environment, else taken from the environment of PID 1 of this
# machine WITHOUT printing it; it goes to the container as `-e NAME` (never on a command line) and everything the container prints passes a filter that
# replaces it by <token>. Without a login the real goals are skipped.
set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(dirname "$here")
image=localhost/swarmbox-sysop-test
results=${SOAK_RESULTS_HOST:-}
state_mb=${SOAK_STATE_MB:-160}
while [ $# -gt 0 ]; do
    case $1 in
        -i) image=$2; shift 2 ;;
        -r) results=$2; shift 2 ;;
        --) shift; break ;;
        *) break ;;
    esac
done
[ -n "$results" ] || results=$(mktemp -d /tmp/soak-v1-results.XXXXXX)
mkdir -p "$results"
chmod 777 "$results"

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -r /proc/1/environ ]; then
    CLAUDE_CODE_OAUTH_TOKEN=$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^CLAUDE_CODE_OAUTH_TOKEN=//p')
fi
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-}"

mask() {
    python3 -I -u -c '
import os, sys
t = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
for line in sys.stdin:
    sys.stdout.write(line.replace(t, "<token>") if t else line)
    sys.stdout.flush()
'
}

echo "soak_v1: image $image, results in $results" >&2
podman run --rm --userns=keep-id:uid=1000,gid=1000 -e CLAUDE_CODE_OAUTH_TOKEN -e SOAK_RESULTS=/results \
    -v "$repo":/src:ro -v "$results":/results --tmpfs /work:rw,exec,mode=1777,size=3g --tmpfs "/state:rw,mode=1777,size=${state_mb}m" "$image" \
    bash -c 'cp -r /src /work/repo 2>/dev/null; export HOME=/work/home; cd /work/repo && python3 -B tests/soak_v1.py "$@" & wait $!' soak "$@" 2>&1 | mask
exit "${PIPESTATUS[0]}"
