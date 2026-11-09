#!/bin/sh
# swarmbox-shim (installed as /usr/local/bin/swarmbox-shim). The one dispatcher every shim links to.
#
# A shim is a symlink named after a command a tool provides. This script learns the command from the name it was called with
# (basename "$0", dash, bash, zsh and busybox sh all give $0 as invoked), finds the tool in the index (the user
# index first, then the image index: the user wins), and replaces itself with `swarmbox-tool run <tool> <command> -- "$@"`,
# which installs on first use and execs the real program.
#
# Hot path rule: one pass over at most two small index files. It never sources a manifest and never starts anything but
# `swarmbox-tool` (the manifests are read by `run`, not here). POSIX sh on purpose: dash starts
# faster than bash and the same text runs under bash and busybox sh.
#
# Exit codes: 127 unknown command (the shell's own "command not found"), 64 called as swarmbox-shim itself, 70 the manager is
# missing or the call chain loops, otherwise whatever `swarmbox-tool run` gives (69 failed install, the program's own status).
#
# Test-only variables: SWARMBOX_TEST_USER_SHIMS and SWARMBOX_TEST_IMAGE_SHIMS (as in swarmbox-tool; the
# index is the sibling file `index` of the shim folder), SWARMBOX_TEST_TOOL replaces /usr/local/bin/swarmbox-tool,
# SWARMBOX_TEST_LIB is the folder with dirs.sh.

cmd=${0##*/}
case $cmd in
    swarmbox-shim | swarmbox-shim.sh)
        echo "swarmbox-shim: this is the dispatcher that the command links point to; call a command by its own name (see: swarmbox-tool list)" >&2
        exit 64
        ;;
esac

# Loop guard: a real program that turns out to be this shim again would call itself forever. The depth travels in the
# environment; a program that starts other SwarmBox commands legitimately stays far below the limit.
depth=${SWARMBOX_SHIM_DEPTH:-0}
case $depth in
    '' | *[!0-9]*) depth=0 ;;
esac
if [ "$depth" -ge 16 ]; then
    echo "swarmbox-shim: '$cmd' called itself $depth times (the real program resolves back to the shim); stopping" >&2
    exit 70
fi

# user_index: <workspace>/.local/share/swarmbox/index (dirs.sh), or the sibling of the test override.
if [ -n "${SWARMBOX_TEST_USER_SHIMS:-}" ]; then
    user_index=${SWARMBOX_TEST_USER_SHIMS%/}/../index
else
    user_index=
    for lib in "${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}/dirs.sh" "${0%/*}/dirs.sh"; do
        if [ -r "$lib" ]; then
            # shellcheck disable=SC1090  # chosen at run time
            . "$lib"
            user_index=$SB_DATA_DIR/index
            break
        fi
    done
fi
image_index=${SWARMBOX_TEST_IMAGE_SHIMS:-/usr/local/lib/swarmbox/shims}
image_index=${image_index%/}/../index

tool=
for idx in "$user_index" "$image_index"; do
    [ -n "$idx" ] || continue
    [ -r "$idx" ] || continue
    while IFS=' ' read -r c t _rest || [ -n "$c" ]; do
        if [ "$c" = "$cmd" ] && [ -n "$t" ]; then
            tool=$t
            break
        fi
        c=
    done <"$idx"
    [ -z "$tool" ] || break
done

if [ -z "$tool" ]; then
    echo "$cmd: command not found (no installed SwarmBox tool provides it; see: swarmbox-tool list)" >&2
    exit 127
fi

mgr=${SWARMBOX_TEST_TOOL:-/usr/local/bin/swarmbox-tool}
if [ ! -x "$mgr" ]; then
    echo "swarmbox-shim: cannot run '$cmd': $mgr is missing or not executable" >&2
    exit 70
fi

SWARMBOX_SHIM_DEPTH=$((depth + 1))
export SWARMBOX_SHIM_DEPTH
exec "$mgr" run "$tool" "$cmd" -- "$@"
