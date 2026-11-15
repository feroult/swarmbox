#!/bin/bash
# Runs the tests of the spike in a Podman container (never against the tmux of this box). Needs the image with tmux, python3, less, vim, fzf.
# usage: dev/spikes/tmux-facts/run-in-container.sh [image] [unittest args...]
IMG=${1:-localhost/tmuxfacts-test}; shift
HERE=$(cd "$(dirname "$0")/../../.." && pwd)
exec podman run --rm --userns=keep-id:uid=1000,gid=1000 -v "$HERE":/src:ro --tmpfs /work:rw,exec,mode=1777,size=1g -e HOME=/work \
    "$IMG" bash -c 'cp -r /src/dev/spikes/tmux-facts /work/tf && cd /work/tf && python3 -m unittest -v test_tmuxfacts "$@"' _ "$@" 2>&1
