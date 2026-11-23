#!/bin/bash
# Voice prepare.sh: run by `swarmbox-addon prepare` at every box start (serve step 7, before the web terminal) and after an install.
#
# install.sh copies lib/ into the install, and swarmbox-addon skips the installer when that version folder
# exists, so after `swarmbox update` (a new image, the same whisper.cpp version) the install would keep the OLD service.
# This script makes the files of the image, which sit next to it, the ones in use: when the folder differs it
# replaces the installed copy by a fresh one (copy beside it, then two renames). Whisper, the models and the launcher are not touched.
# Idempotent; nothing is written when the folders are equal. Exit 0, or 1 with a line on stderr when the install could not be updated.
set -u
here=${SWARMBOX_ADDON_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
real=$(swarmbox-addon where voice swarmbox-voice 2>/dev/null) || exit 0   # not installed: nothing to refresh
prefix=${real%/bin/swarmbox-voice}
[ "$prefix" != "$real" ] && [ -d "$prefix" ] || { echo "voice prepare: cannot place the install of $real" >&2; exit 1; }
rc=0
for d in lib; do
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
[ -d "$prefix/web" ] && rm -rf "$prefix/web"             # the page parts of the old ttyd web terminal (the Web Studio has its own microphone)
# Installed while the box runs: the web server started without the front, so /voice/ is not served and the page has no microphone. Ask the
# supervisor to start it again, once, so a reload of the page shows the microphone. At box start this script runs before the web server
# exists: nothing to do. When the front already runs, or the web terminal is off, or voice.web is 0: nothing to do either.
if [ "${SWARMBOX_VOICE_WEB:-1}" != 0 ] && pgrep -f -- "herdr-web/server.mjs" > /dev/null 2>&1 && ! pgrep -f -- "swarmbox_voice front" > /dev/null 2>&1; then
    swarmbox-web restart > /dev/null 2>&1 && echo "voice prepare: the web terminal restarts to show the microphone (reload the page)" >&2
fi
exit "$rc"
