#!/bin/bash
# Sysop prepare.sh: run by `swarmbox-addon prepare` at every box start (serve step 7) and after an install, under `timeout -k 2`.
#
# 1. install.sh copies lib/ into the install, and swarmbox-addon skips the installer when that version folder exists, so after `swarmbox update`
#    (a new image, the same VERSION) the install would keep the OLD library. Like the voice addon's, this makes the files of the image (next to
#    this script) the ones in use: when lib differs it is replaced by a fresh copy (copy beside it, then two renames). Idempotent.
# 2. It starts the resident subscriber, detached: `setsid nohup ... serve --log --dock --watch &` (--dock: the service keeps the panel in tmux; --watch: a watcher (watch.py) starts the service again when it
#    dies, so a kill or a crash is not the end of the sysop until the next box start; when the watcher is already there, this start only tells it to start the service now), with its three standard streams and every other descriptor
#    away from this script (the caller captures our output and kills our children when the timeout ends, so the service must not be one of
#    them). Starting is idempotent: when a service already runs (`status -q`), nothing starts; and two starts at once end with one service
#    (the service takes a flock; the loser exits 0). The service keeps a pid file and a log in its run and state folders (see paths.py), and
#    reconnects to the bus by itself, so it does not matter that the bus starts before or after this.
# Exit 0, or 1 with a line on stderr when the install could not be updated or the service did not come up within 5 s (a refused setting is in serve.log).
set -u
here=${SWARMBOX_ADDON_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
real=$(swarmbox-addon where sysop swarmbox-sysop 2>/dev/null) || exit 0   # not installed: nothing to refresh or start
prefix=${real%/bin/swarmbox-sysop}
if [ "$prefix" = "$real" ] || [ ! -d "$prefix" ]; then
    echo "sysop prepare: cannot place the install of $real" >&2
    exit 1
fi
rc=0
d=lib
if [ -d "$here/$d" ]; then
    if ! { [ -d "$prefix/$d" ] && diff -rq -x __pycache__ "$here/$d" "$prefix/$d" > /dev/null 2>&1; }; then
        new=$prefix/.$d.new.$$
        old=$prefix/.$d.old.$$
        rm -rf "$new"
        if cp -R "$here/$d" "$new" && find "$new" -name __pycache__ -prune -exec rm -rf {} + \
            && { [ ! -d "$prefix/$d" ] || mv "$prefix/$d" "$old"; } && mv "$new" "$prefix/$d"; then
            rm -rf "$old"
            echo "sysop prepare: refreshed $d from the image" >&2
        else
            rm -rf "$new"
            [ -d "$prefix/$d" ] || { [ ! -d "$old" ] || mv "$old" "$prefix/$d"; }
            echo "sysop prepare: could not refresh $d in $prefix" >&2
            rc=1
        fi
    fi
fi
bin=$prefix/bin/swarmbox-sysop
if [ ! -x "$bin" ]; then
    echo "sysop prepare: $bin is not executable" >&2
    exit 1
fi
if "$bin" status -q > /dev/null 2>&1; then
    exit "$rc"                          # a service runs already
fi
setsid nohup "$bin" serve --log --dock --watch < /dev/null > /dev/null 2>&1 &
# The service reads its settings first: a refused one (a bad SWARMBOX_SYSOP_BRAIN) ends it in a moment. Say so, instead of "started".
n=0
until "$bin" status -q > /dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -gt 50 ]; then
        echo "sysop prepare: the goal subscriber did not come up (see serve.log in the state folder of the sysop, or run: swarmbox-sysop --self-test)" >&2
        exit 1
    fi
    sleep 0.1
done
echo "sysop prepare: started the goal subscriber" >&2
exit "$rc"
