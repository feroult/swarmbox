# SwarmBox shell fragment. Installed as /etc/swarmbox/bashrc.sh and sourced from the
# image's /etc/bash.bashrc; `swarmbox-attach` also sources it directly for a command run without a terminal.
#
# It gives every shell: the Python venv, the PATH additions of the addons, the colored ls and grep aliases, the
# `shell.sh` of every addon (the auto-approve function of an agent is there) and the `yolo` function, and, in an
# interactive shell only, the banner with the startup-health lines and the Starship prompt. Nothing here
# regenerates a file: that is `serve`'s job.
#
# bash only (arrays and here-strings; bash 3.2 semantics are kept). Sourcing twice is harmless.
# Test-only variables (the paths the design fixes): SWARMBOX_DIRS_SH, SWARMBOX_IMAGE_ADDONS_DIR, SWARMBOX_IMAGE_SHIMS_DIR,
# SWARMBOX_BANNER_SCRIPT, SWARMBOX_STARSHIP_INIT, SWARMBOX_VENV.

# An interactive shell is unchanged; a command run without a terminal (SWARMBOX_CMD=1) gets the aliases, the functions of the addons and the PATH
# and nothing else; any other shell (scripts, `bash -c`) is left alone.
case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return 0 ;; esac

# shellcheck source=/dev/null
. "${SWARMBOX_DIRS_SH:-/usr/local/lib/swarmbox/dirs.sh}" 2>/dev/null || {
    SB_CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/swarmbox
    SB_DATA_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox
    SB_STATE_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/swarmbox
    SB_ADDONS_DIR=$SB_DATA_DIR/addons
    SB_SHIMS_DIR=$SB_DATA_DIR/shims
    SB_HEALTH_FILE=$SB_STATE_DIR/health
}
_sb_image_addons=${SWARMBOX_IMAGE_ADDONS_DIR:-/usr/local/lib/swarmbox/addons}
_sb_image_shims=${SWARMBOX_IMAGE_SHIMS_DIR:-/usr/local/lib/swarmbox/shims}

# --- Python virtual environment (before the PATH additions, so the shims still come first) ---
_sb_venv=${SWARMBOX_VENV:-/opt/flow}
if [ -z "${VIRTUAL_ENV:-}" ] && [ -r "$_sb_venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    . "$_sb_venv/bin/activate"
fi
unset _sb_venv

# --- PATH: user shims, image shims, the addons' current/bin, ~/.local/bin, then what was there ---
_sb_path_add() {
    case ":$PATH:" in *":$1:"*) ;; *) PATH="$1:$PATH" ;; esac
}
_sb_path_add "$HOME/.local/bin"
for _sb_d in "$SB_ADDONS_DIR"/*/current/bin; do
    [ -d "$_sb_d" ] && _sb_path_add "$_sb_d"
done
_sb_path_add "$_sb_image_shims"
_sb_path_add "$SB_SHIMS_DIR"
export PATH
unset _sb_d
unset -f _sb_path_add

# --- colors and small helpers (moved from the image's bashrc echo lines) ---
# The purple glow of the box, in 256-colour numbers (not the 16 colours of the terminal, which every scheme paints its own way): folders
# bold violet, links lavender, programs green, the special files amber and fuchsia, the dangerous ones on a dark red or amber background.
export LS_COLORS='rs=0:di=1;38;5;141:ln=38;5;183:mh=00:pi=38;5;179:so=1;38;5;176:do=1;38;5;176:bd=38;5;179;48;5;236:cd=38;5;179;48;5;236:or=1;38;5;203;48;5;236:mi=00:su=1;38;5;255;48;5;88:sg=1;38;5;16;48;5;179:ca=1;38;5;16;48;5;203:tw=1;38;5;141;48;5;236:ow=38;5;141;48;5;236:st=1;38;5;255;48;5;54:ex=1;38;5;78:'
# grep: the match in bold lavender, the file names violet, the line numbers and the separators gray
export GREP_COLORS='mt=1;38;5;183:fn=38;5;141:ln=38;5;243:bn=38;5;243:se=38;5;240'
alias ls='ls --color=auto'
alias ll='ls -alF --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'

# --- The addons ---
# The shell.sh of every addon is sourced: what an addon wants in the shell (the auto-approve function of an agent, a port for
# `clasp login`, the path of Go) is in its own file; this fragment reads no manifest. The user level (<config>/addons) wins over the
# image level for the same name. A failing file does not stop the shell.
_sb_seen=" "
for _sb_base in "$SB_CONFIG_DIR/addons" "$_sb_image_addons"; do
    for _sb_d in "$_sb_base"/*/; do
        [ -d "$_sb_d" ] || continue
        _sb_d=${_sb_d%/}
        _sb_name=${_sb_d##*/}
        case "$_sb_seen" in *" $_sb_name "*) continue ;; esac
        _sb_seen="$_sb_seen$_sb_name "
        [ -r "$_sb_d/shell.sh" ] || continue
        # shellcheck source=/dev/null
        . "$_sb_d/shell.sh" </dev/null 2>/dev/null || true
    done
done
unset _sb_seen _sb_base _sb_d _sb_name

# yolo: run the default agent, $SWARMBOX_AGENT (the host records it when the box is created: the AGENT setting, else the first addon
# of WITH). The agent's own function (its shell.sh) starts it in auto-approve mode; yolo asks for that mode even when SWARMBOX_YOLO=0.
yolo() {
    if [ -z "${SWARMBOX_AGENT:-}" ]; then
        echo "yolo: this box has no default agent. Set one on the host (swarmbox config set AGENT claude, then swarmbox reset) or create the box with --with claude." >&2
        return 1
    fi
    # yolo is not an agent: it would call itself until the shell dies.
    if [ "$SWARMBOX_AGENT" = yolo ]; then
        echo "yolo: the default agent cannot be 'yolo'. Set an agent on the host (swarmbox config set AGENT claude, then swarmbox reset)." >&2
        return 1
    fi
    # The addon antigravity provides the command agy: the default agent may be named by either.
    local _sb_agent=$SWARMBOX_AGENT
    [ "$_sb_agent" != antigravity ] || _sb_agent=agy
    # The first item of WITH is the default when AGENT is not set, and it may be an addon that is not an agent (sysop, voice): say so.
    if ! command -v "$_sb_agent" > /dev/null 2>&1; then
        echo "yolo: the default agent '$SWARMBOX_AGENT' is not a command in this box. Set the agent on the host (swarmbox config set AGENT claude, then swarmbox reset)." >&2
        return 127
    fi
    SWARMBOX_YOLO=1 "$_sb_agent" "$@"
}

# --- Interactive only: startup-health warnings, then the Starship prompt ---
# Not for a shell started with -c (the command window of `swarmbox <command>` runs `bash -ic`).
# Once per shell: a second sourcing prints nothing.
if [ -z "${SWARMBOX_CMD:-}" ] && [ -z "${BASH_EXECUTION_STRING:-}" ] && [ -z "${_sb_fragment_done:-}" ]; then
    _sb_fragment_done=1
    # Lines of <state>/health (written by `serve` and by the host helper, including the stale-image line), one per
    # failed step or warning. Control characters are dropped so a line cannot repaint the terminal.
    if [ -s "$SB_HEALTH_FILE" ]; then
        while IFS= read -r _sb_line || [ -n "$_sb_line" ]; do
            _sb_line=${_sb_line//[[:cntrl:]]/}
            [ -n "$_sb_line" ] && printf '  \033[0;33m!\033[0m %s\n' "$_sb_line"
        done < "$SB_HEALTH_FILE"
    fi
    unset _sb_line
    # Starship redefines PS1, so it comes last.
    _sb_starship=${SWARMBOX_STARSHIP_INIT:-/etc/swarmbox/scripts/starship-init.sh}
    # shellcheck source=/dev/null
    [ -r "$_sb_starship" ] && . "$_sb_starship"
    unset _sb_starship
fi
unset _sb_image_addons _sb_image_shims
