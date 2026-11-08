#!/bin/bash
# swarmbox-migrate: the one-way layout migration of design 12.4, run by `serve` as step 4 (W) at every start.
#
# It acts only on files that exist under <workspace>/.swarmbox/ (the v0.1.0 layout; the workspace is $HOME in the box), never
# overwrites an existing destination, never removes a folder recursively and removes .swarmbox/ itself only when it is empty
# afterwards. Safe to run again: a second run finds nothing to do. A step that fails (a read-only folder, a full disk) is
# reported on stderr, the other rows still run, and the exit status is 1 (`serve` turns that into one health line).
#
#   settings.json       copied over the link <workspace>/.claude/settings.json (the link is replaced by a real file), then deleted
#   web-terminal.conf   moved to $SB_CONFIG_DIR/web-terminal.conf
#   ttyd-index.html, opencode-local.json, podman.sock, *.log, *.lock   deleted (regenerated elsewhere)
#   memory/             left alone and mentioned
#   anything else       left alone and listed, so .swarmbox/ stays
#
# Test-only variable (decision log [2.3]; not in the configuration table of design 8): SWARMBOX_TEST_LIB (folder with dirs.sh).
SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "swarmbox-migrate: cannot read $SB_LIB/dirs.sh" >&2; exit 1; }

OLD="$HOME/.swarmbox"
# Not there (or a link we must not follow): nothing to do, nothing to say.
[ -d "$OLD" ] && [ ! -L "$OLD" ] || exit 0

FAILED=0
note() { echo "swarmbox-migrate: $*"; }
fail() { echo "swarmbox-migrate: $*" >&2; FAILED=1; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }

# delete_old <path>: remove one file (or link, or socket) of the old folder without following it.
delete_old() {
    exists "$1" || return 0
    rm -f -- "$1" 2>/dev/null
    if exists "$1"; then fail "could not delete $1"; return 1; fi
    return 0
}

# ours <link target>: true when the target is the old settings file (absolute, as init.sh of v0.1.0 wrote it).
ours() { case "$1" in "$OLD/settings.json" | */.swarmbox/settings.json) return 0 ;; esac; return 1; }

# --- settings.json ----------------------------------------------------------------------------------------------------
SET_OLD="$OLD/settings.json"
SET_NEW="$HOME/.claude/settings.json"
if [ -f "$SET_OLD" ] && [ ! -L "$SET_OLD" ]; then
    if [ -L "$SET_NEW" ]; then
        if ours "$(readlink "$SET_NEW")"; then
            tmp="$SET_NEW.tmp.$$"
            if cp -p -- "$SET_OLD" "$tmp" 2>/dev/null && mv -f -- "$tmp" "$SET_NEW" 2>/dev/null; then
                delete_old "$SET_OLD"
            else
                rm -f -- "$tmp" 2>/dev/null
                fail "could not replace the link $SET_NEW by a copy of $SET_OLD"
            fi
        else
            note "$SET_NEW is a link to somewhere else: left as it is, $SET_OLD kept"
        fi
    elif [ -e "$SET_NEW" ]; then
        if cmp -s -- "$SET_OLD" "$SET_NEW"; then
            delete_old "$SET_OLD"
        else
            note "$SET_NEW already exists and differs: not overwritten, $SET_OLD kept (merge by hand)"
        fi
    else
        tmp="$SET_NEW.tmp.$$"
        if mkdir -p -- "$HOME/.claude" 2>/dev/null && cp -p -- "$SET_OLD" "$tmp" 2>/dev/null && mv -f -- "$tmp" "$SET_NEW" 2>/dev/null; then
            delete_old "$SET_OLD"
        else
            rm -f -- "$tmp" 2>/dev/null
            fail "could not copy $SET_OLD to $SET_NEW"
        fi
    fi
elif [ -L "$SET_NEW" ] && [ ! -e "$SET_NEW" ] && ours "$(readlink "$SET_NEW")"; then
    # the old file is gone and the link v0.1.0's init.sh made dangles: Claude Code would write through it into .swarmbox/
    if rm -f -- "$SET_NEW" 2>/dev/null; then
        note "removed the dangling link $SET_NEW"
    else
        fail "could not remove the dangling link $SET_NEW"
    fi
fi

# --- web-terminal.conf ------------------------------------------------------------------------------------------------
CONF_OLD="$OLD/web-terminal.conf"
CONF_NEW="$SB_CONFIG_DIR/web-terminal.conf"
if [ -f "$CONF_OLD" ] && [ ! -L "$CONF_OLD" ]; then
    if exists "$CONF_NEW"; then
        note "$CONF_NEW already exists: not overwritten, $CONF_OLD kept"
    elif mkdir -p -- "$SB_CONFIG_DIR" 2>/dev/null && mv -- "$CONF_OLD" "$CONF_NEW" 2>/dev/null; then
        :
    else
        fail "could not move $CONF_OLD to $CONF_NEW"
    fi
fi

# --- deleted (regenerated elsewhere) ----------------------------------------------------------------------------------
for f in "$OLD/ttyd-index.html" "$OLD/opencode-local.json" "$OLD/podman.sock" "$OLD"/*.log "$OLD"/*.lock; do
    delete_old "$f"
done

# --- memory/ and what is left -----------------------------------------------------------------------------------------
[ -d "$OLD/memory" ] && note "$OLD/memory is left by the removed memory service and is not used; delete it when you no longer need it"
left=""
while IFS= read -r name; do
    [ "$name" = memory ] && continue
    left="$left${left:+, }$name"
done < <(find "$OLD" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null)
[ -z "$left" ] || note "left in $OLD (not part of the migration table): $left"

# .swarmbox/ goes only when empty (rmdir refuses otherwise)
rmdir -- "$OLD" 2>/dev/null && note "migration finished, $OLD removed"

exit "$FAILED"
