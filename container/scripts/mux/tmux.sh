#!/bin/bash
# tmux.sh: the tmux multiplexer backend for SwarmBox (loaded by mux.sh when SWARMBOX_MUX=tmux).
#
# All tmux-specific lifecycle, session, window-slot and command-wrapper logic lives here so the
# core scripts (entrypoint.sh, swarmbox-attach.sh, swarmbox-web.sh) never invoke tmux directly.

_SB_TMUX_SESSION=main
_SB_TMUX_IDLE_NAME=idle

mux_available() {
    command -v tmux > /dev/null 2>&1
}

mux_serve_init() {
    local rc
    log "step 9: starting tmux, session $_SB_TMUX_SESSION"
    if have tmux; then
        run_logged env -u TMUX tmux new-session -d -s "$_SB_TMUX_SESSION" -n "$_SB_TMUX_IDLE_NAME"
        rc=$?
        [ "$rc" = 0 ] || warn "tmux did not start the session $_SB_TMUX_SESSION (exit $rc); see serve.log"
    else
        warn "tmux not found; the session $_SB_TMUX_SESSION was not created"
    fi
}

mux_serve_shutdown_note() {
    log "leaving the tmux server to end with the container"
}

mux_web_fallback() {
    # shellcheck disable=SC2034  # consumed by swarmbox-web.sh
    MUX_WEB_FALLBACK_CMD=(tmux attach -t "$_SB_TMUX_SESSION")
}

_tmux_ensure_session() {
    tmux has-session -t "=$_SB_TMUX_SESSION" 2>/dev/null && return 0
    tmux new-session -d -s "$_SB_TMUX_SESSION" -n "$_SB_TMUX_IDLE_NAME" 2>/dev/null || tmux has-session -t "=$_SB_TMUX_SESSION" 2>/dev/null
}

# _tmux_idle_window: print the id of the idle window when it is the ONLY window of the session, still named by `serve`, with
# one pane running just a shell (nothing typed into it that is still running). Anything else is a window of the user.
_tmux_idle_window() {
    local rows id name cmd panes
    rows=$(tmux list-windows -t "=$_SB_TMUX_SESSION" -F '#{window_id}|#{window_name}|#{pane_current_command}|#{window_panes}' 2>/dev/null) || return 1
    [ "$(printf '%s\n' "$rows" | wc -l)" = 1 ] || return 1
    IFS='|' read -r id name cmd panes <<< "$rows"
    [ "$name" = "$_SB_TMUX_IDLE_NAME" ] && [ "$panes" = 1 ] || return 1
    case "$cmd" in bash|zsh|sh|dash|fish) ;; *) return 1 ;; esac
    printf '%s\n' "$id"
}

# _tmux_new_window: a detached window in the session, in the caller's directory; prints its id. The rest are the shell command.
_tmux_new_window() {
    tmux new-window -d -P -F '#{window_id}' -t "=$_SB_TMUX_SESSION:" -c "$PWD" "$@"
}

_tmux_window_listed() {
    tmux list-windows -t "=$_SB_TMUX_SESSION" -F '#{window_id}' 2>/dev/null | grep -qxF "$1"
}

# _tmux_slot_target KEY: where the window of the host tab KEY goes in main, so that a tab that leaves and comes back (exit, then `swarmbox` again in the
# same host tab) is back in the same place in the browser. KEY is SWARMBOX_TAB, the pty of the host tab, which the host script passes: it names the tab
# in any terminal or over ssh. The server keeps the keys in the order they first appeared (the global option @sb_order, at most 64) and each window
# the key of its tab (the window option @sb_tab). Prints the id of the first window of main whose tab comes AFTER this one in that order, to go before
# it; nothing when there is none (a new tab, or the last one): the end. Windows with no key (opened from the browser) keep their places.
_tmux_slot_target() {
    local key=$1 k l id found=0
    local -a keys later=()
    read -ra keys <<< "$(tmux show-options -gqv @sb_order 2>/dev/null)"
    for k in "${keys[@]}"; do
        if [ "$found" = 1 ]; then later+=("$k"); elif [ "$k" = "$key" ]; then found=1; fi
    done
    if [ "$found" = 0 ]; then
        keys+=("$key")
        if [ "${#keys[@]}" -gt 64 ]; then keys=("${keys[@]: -64}"); fi
        tmux set-option -g @sb_order "${keys[*]}" 2>/dev/null
        return 0
    fi
    while IFS='|' read -r id k; do
        [ -n "$k" ] || continue
        for l in "${later[@]}"; do
            if [ "$l" = "$k" ]; then printf '%s\n' "$id"; return 0; fi
        done
    done < <(tmux list-windows -t "=$_SB_TMUX_SESSION" -F '#{window_id}|#{@sb_tab}' 2>/dev/null)
    return 0
}

# mux_attach_interactive: a terminal tab of the host. It gets a session of its OWN with just its window, and that window is also linked into the
# session "main", so the browser still shows it as a tab. When the shell of the tab ends (`exit`) its window goes, its session has
# no window left and ends, and so does this client: you are back at the host shell, as with any program. (A grouped session would not
# do: it shares the window list of all the tabs, so when its window went the client was moved to the window of ANOTHER tab.)
# Closing the host tab only detaches: the session of the tab ends (destroy-unattached) but the window keeps running in main.
mux_attach_interactive() {
    unset TMUX
    local idle w term key anchor linked _rows _cols
    local -a size=()
    _tmux_ensure_session || die "tmux could not start the session $_SB_TMUX_SESSION"
    idle=$(_tmux_idle_window)
    term="swarmbox-tab-$$-$(date +%s%N)"
    # the size of this terminal, so that the window does not start at 80x24 and is resized when the client attaches
    if read -r _rows _cols < <(stty size 2>/dev/null) && [ "${_rows:-0}" -gt 0 ] && [ "${_cols:-0}" -gt 0 ]; then size=(-x "$_cols" -y "$_rows"); fi
    tmux new-session -d -s "$term" -c "$PWD" "${size[@]}" || die "tmux could not open a window"
    w=$(tmux display-message -p -t "=$term:" '#{window_id}' 2>/dev/null)
    # the place in main: back where this host tab was (see _tmux_slot_target), else the end. The target names the session: a bare window id would
    # be looked up in the first session that has the window, which is the session of the tab that owns it, not main.
    key=${SWARMBOX_TAB:-}
    key=${key//[^A-Za-z0-9._\/-]/_}
    key=${key:0:80}
    anchor=
    if [ -n "$key" ] && [ -n "$w" ]; then
        tmux set-option -w -t "$w" @sb_tab "$key" 2>/dev/null
        anchor=$(_tmux_slot_target "$key")
    fi
    linked=0
    if [ -n "$w" ] && [ -n "$anchor" ] && tmux link-window -d -b -s "$w" -t "=$_SB_TMUX_SESSION:$anchor" 2>/dev/null; then linked=1; fi   # else the end, below
    if [ "$linked" = 0 ] && [ -n "$w" ] && tmux link-window -d -a -s "$w" -t "=$_SB_TMUX_SESSION:{end}" 2>/dev/null; then linked=1; fi
    if [ "$linked" = 0 ]; then
        tmux kill-session -t "=$term" 2>/dev/null
        die "tmux could not open a window"
    fi
    [ -z "$idle" ] || tmux kill-window -t "$idle" 2>/dev/null
    exec tmux attach-session -t "=$term" \; set-option destroy-unattached on \; set-option status off
}

# mux_attach_web: the browser attaches to the session main itself, so it keeps the status bar with the tabs (the windows of the host tabs are
# linked into it); the host terminals each have a session of their own without a bar (mux_attach_interactive, above).
mux_attach_web() {
    unset TMUX
    _tmux_ensure_session || die "tmux could not start the session $_SB_TMUX_SESSION"
    export SWARMBOX_WEB_CLIENT=1      # the tmux client of the browser says so in its environment: the sysop panel looks for it (a terminal gets no bar of buttons, the page draws it).
    # Not SWARMBOX_WEB: that one is the setting of the box (the web terminal on or off) and every process of the box has it
    exec tmux attach-session -t "=$_SB_TMUX_SESSION"
}

# The wrapper runs as the window's command. $1 the quoted command, $2 the status file, $3 the channel.
# bash -ic runs in the background and the wrapper waits, so that the trap can run when tmux hangs the window up
# (kill-window); stdin is passed on explicitly because a background job of a non-interactive shell would get /dev/null.
read -r -d '' _SB_TMUX_WRAPPER <<'EOF'
sb_status=$2
sb_chan=$3
sb_fin() { echo "$1" > "$sb_status.tmp" && mv "$sb_status.tmp" "$sb_status"; tmux wait-for -S "$sb_chan"; }
trap 'kill "$sb_pid" 2>/dev/null; sb_fin 129; exit 129' HUP TERM
exec 3<&0
bash -ic "$1" <&3 3<&- &
sb_pid=$!
wait "$sb_pid"
sb_rc=$?
trap - HUP TERM
tmux capture-pane -p -J -t "$TMUX_PANE" > "$sb_status.out" 2>/dev/null
sb_fin "$sb_rc"
EOF

mux_attach_command() {
    unset TMUX
    local cmd_q=$1
    local poll=${POLL:-1}
    local run_dir=${SB_RUN_DIR:-/tmp/swarmbox}
    local id status chan grp w client waiter ticks n rc detached=0
    id="$(date +%s%N)p$$"
    status="$run_dir/exit.$id"
    chan="swarmbox-$id"
    grp="swarmbox-cmd-$id"
    _tmux_ensure_session || die "tmux could not start the session $_SB_TMUX_SESSION"
    rm -f "$status" "$status.tmp"
    w=$(_tmux_new_window bash -c "$_SB_TMUX_WRAPPER" wrapper "$cmd_q" "$status" "$chan") || die "tmux could not open a window"
    [ -n "$w" ] || die "tmux could not open a window"

    # the grouped client, as a child (not exec), selected on the command's window; stdin is passed on explicitly
    exec 3<&0
    tmux new-session -t "=$_SB_TMUX_SESSION" -s "$grp" \; set-option destroy-unattached on \; set-option status off \; select-window -t "$w" <&3 3<&- &
    client=$!
    exec 3<&-
    tmux wait-for "$chan" < /dev/null &
    waiter=$!

    # shellcheck disable=SC2317,SC2329  # called from the trap
    _tmux_abort() {
        kill "$waiter" 2>/dev/null
        tmux kill-session -t "=$grp" 2>/dev/null
        kill "$client" 2>/dev/null
        exit "$1"
    }
    trap '_tmux_abort 129' HUP
    trap '_tmux_abort 143' TERM

    ticks=$(awk -v p="$poll" 'BEGIN { t = int(p * 10 + 0.5); if (t < 1) t = 1; print t }')
    n=0
    while kill -0 "$waiter" 2>/dev/null; do
        sleep 0.1
        n=$((n + 1))
        [ "$n" -ge "$ticks" ] || continue
        n=0
        [ -s "$status" ] && break
        if ! _tmux_window_listed "$w" || ! kill -0 "$client" 2>/dev/null; then
            # the window is gone or the client ended: give a status that is on its way a moment to arrive
            for _ in 1 2 3 4 5; do
                kill -0 "$waiter" 2>/dev/null || break
                [ -s "$status" ] && break
                sleep 0.2
            done
            if ! kill -0 "$waiter" 2>/dev/null || [ -s "$status" ]; then break; fi
            _tmux_window_listed "$w" && detached=1
            break
        fi
    done
    kill "$waiter" 2>/dev/null
    wait "$waiter" 2>/dev/null

    # end the grouped client so that this call returns although other windows exist; restore the terminal before exiting
    tmux kill-session -t "=$grp" 2>/dev/null
    for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        kill -0 "$client" 2>/dev/null || break
        sleep 0.2
    done
    kill "$client" 2>/dev/null
    wait "$client" 2>/dev/null
    # the grouped session can still be there: a client that started late creates it after the kill above, and the server
    # notices a client's end after a moment. Remove it for sure, so that no session of a finished call outlives the call.
    for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        tmux has-session -t "=$grp" 2>/dev/null || break
        tmux kill-session -t "=$grp" 2>/dev/null
        sleep 0.1
    done
    trap - HUP TERM

    if [ "$detached" = 1 ]; then
        rm -f "$status" "$status.tmp" "$status.out"
        echo "swarmbox: detached; the command keeps running in window $w of the session $_SB_TMUX_SESSION" >&2
        exit 0
    fi
    rc=$(cat "$status" 2>/dev/null)
    # the window is gone and with it the output: show the last screen of it, without the empty lines at the end
    awk '{ l[NR] = $0 } END { n = NR; while (n > 0 && l[n] ~ /^[ \t]*$/) n--; for (i = 1; i <= n; i++) print l[i] }' "$status.out" 2>/dev/null
    rm -f "$status" "$status.tmp" "$status.out"
    case "$rc" in
        ''|*[!0-9]*) die "the command's status is lost (its window was closed hard or tmux ended); exit status unknown" 1 ;;
    esac
    exit "$rc"
}
