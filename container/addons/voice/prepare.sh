#!/bin/bash
# Voice prepare.sh: run by `swarmbox-addon prepare` at every box start (serve step 7, before the web terminal) and after an install.
#
# install.sh copies lib/ and web/ into the install, and swarmbox-addon skips the installer when that version folder
# exists, so after `swarmbox update` (a new image, the same whisper.cpp version) the install would keep the OLD service and
# page. This script makes the files of the image, which sit next to it, the ones in use: for each of the two folders that differs it
# replaces the installed copy by a fresh one (copy beside it, then two renames). Whisper, the models and the launcher are not touched.
# Idempotent; nothing is written when the folders are equal. Exit 0, or 1 with a line on stderr when the install could not be updated.
set -u
here=${SWARMBOX_ADDON_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
real=$(swarmbox-addon where voice swarmbox-voice 2>/dev/null) || exit 0   # not installed: nothing to refresh
prefix=${real%/bin/swarmbox-voice}
[ "$prefix" != "$real" ] && [ -d "$prefix" ] || { echo "voice prepare: cannot place the install of $real" >&2; exit 1; }
rc=0
for d in lib web; do
    [ -d "$here/$d" ] || continue
    if [ -d "$prefix/$d" ] && diff -rq -x __pycache__ "$here/$d" "$prefix/$d" > /dev/null 2>&1; then continue; fi
    new=$prefix/.$d.new.$$
    old=$prefix/.$d.old.$$
    rm -rf "$new"
    if cp -R "$here/$d" "$new" && find "$new" -name __pycache__ -prune -exec rm -rf {} + \
        && { [ ! -d "$prefix/$d" ] || mv "$prefix/$d" "$old"; } && mv "$new" "$prefix/$d"; then
        rm -rf "$old"
        echo "voice prepare: refreshed $d from the image" >&2
    else
        rm -rf "$new"
        [ -d "$prefix/$d" ] || { [ ! -d "$old" ] || mv "$old" "$prefix/$d"; }
        echo "voice prepare: could not refresh $d in $prefix" >&2
        rc=1
    fi
done
[ -d "$prefix/planners" ] && rm -rf "$prefix/planners"   # an install from before voice became an input only
exit "$rc"
