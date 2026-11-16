#!/bin/bash
# End to end test of version 1 from the microphone in a browser to the answer in a real Claude Code tab, with the real pieces, in Podman (see the docstring
# of tests/e2e/e2e_voice.py). NOT part of the fast gate.
#
#   tests/e2e/e2e_voice.sh [-i IMAGE] [-r RESULTS_DIR] [-c CACHE_DIR] [-- e2e_voice.py arguments, e.g. --only 1,3 --runs 5]
#
# IMAGE defaults to localhost/swarmbox-sysop-test (tmux 3.5a); localhost/tmuxfacts-test37 has tmux 3.7c, the version of the box image. Both have the claude CLI,
# chromium, ttyd, espeak-ng and python3. CACHE_DIR (default: a folder next to the results) keeps the install of the voice addon (whisper.cpp built from
# source and the model small, about 500 MB) between runs: the first run builds it (about a minute), the next ones copy it. The tmux server and everything
# else runs inside the container; the host's tmux is never touched.
#
# The login: CLAUDE_CODE_OAUTH_TOKEN from the environment. When it is not set the script takes it from the environment of PID 1 of this machine (where
# the master box keeps it) WITHOUT printing it. It goes to the container as `-e NAME` (the value is never on a command line), and everything the
# container prints passes a filter that replaces it by <token> (the filter reads it from the environment, not from its arguments).
set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(dirname "$(dirname "$here")")
image=localhost/swarmbox-sysop-test
results=${E2E_RESULTS_HOST:-}
cache=${E2E_WS_CACHE_HOST:-}
while [ $# -gt 0 ]; do
    case $1 in
        -i) image=$2; shift 2 ;;
        -r) results=$2; shift 2 ;;
        -c) cache=$2; shift 2 ;;
        --) shift; break ;;
        *) break ;;
    esac
done
[ -n "$results" ] || results=$(mktemp -d /tmp/e2e-voice-results.XXXXXX)
[ -n "$cache" ] || cache=$results/../e2e-voice-ws-cache
mkdir -p "$results" "$cache"
chmod 777 "$results" "$cache"

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -r /proc/1/environ ]; then
    CLAUDE_CODE_OAUTH_TOKEN=$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^CLAUDE_CODE_OAUTH_TOKEN=//p')
fi
export CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-}"
[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || echo "e2e_voice: no CLAUDE_CODE_OAUTH_TOKEN: the scenarios that need the brain will fail" >&2

mask() {
    python3 -I -u -c '
import os, sys
t = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
for line in sys.stdin:
    sys.stdout.write(line.replace(t, "<token>") if t else line)
    sys.stdout.flush()
'
}

echo "e2e_voice: image $image, results in $results, voice cache in $cache" >&2
podman run --rm --userns=keep-id:uid=1000,gid=1000 -e CLAUDE_CODE_OAUTH_TOKEN -e E2E_RESULTS=/results -e E2E_WS_CACHE=/ws-cache -e E2E_TRACE \
    -v "$repo":/src:ro -v "$results":/results -v "$cache":/ws-cache --tmpfs /work:rw,exec,mode=1777,size=4g "$image" \
    bash -c 'cp -r /src /work/repo 2>/dev/null; export HOME=/work/home; cd /work/repo && exec python3 -B tests/e2e/e2e_voice.py "$@"' e2e "$@" 2>&1 | mask
exit "${PIPESTATUS[0]}"
