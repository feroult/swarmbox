# SwarmBox shell fragment (design 6.6, 3.3, 4.2, 10.3, D9). Installed as /etc/swarmbox/bashrc.sh and sourced from the
# image's /etc/bash.bashrc; `swarmbox-attach` also sources it directly for a command run without a terminal.
#
# It gives every shell: the Python venv, the PATH additions of the tools (6.2), the colored ls and grep aliases, the
# auto-approve alias of every agent manifest and the `yolo` function (6.6), the `shell.sh` of every tool, and, in an
# interactive shell only, the banner with the startup-health lines (4.2) and the Starship prompt. Nothing here
# regenerates a file: that is `serve`'s job (10.3).
#
# bash only (arrays and here-strings; bash 3.2 semantics are kept). Sourcing twice is harmless.
# Test-only variables (the paths the design fixes): SWARMBOX_DIRS_SH, SWARMBOX_IMAGE_TOOLS_DIR, SWARMBOX_IMAGE_SHIMS_DIR,
# SWARMBOX_BANNER_SCRIPT, SWARMBOX_STARSHIP_INIT, SWARMBOX_VENV.

# An interactive shell is unchanged; a command run without a terminal (SWARMBOX_CMD=1) gets the aliases and the PATH
# and nothing else; any other shell (scripts, `bash -c`) is left alone.
case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return 0 ;; esac

# shellcheck source=/dev/null
. "${SWARMBOX_DIRS_SH:-/usr/local/lib/swarmbox/dirs.sh}" 2>/dev/null || {
    SB_CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/swarmbox
    SB_DATA_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox
    SB_STATE_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/swarmbox
    SB_TOOLS_DIR=$SB_DATA_DIR/tools
    SB_SHIMS_DIR=$SB_DATA_DIR/shims
    SB_HEALTH_FILE=$SB_STATE_DIR/health
}
_sb_image_tools=${SWARMBOX_IMAGE_TOOLS_DIR:-/usr/local/lib/swarmbox/tools}
_sb_image_shims=${SWARMBOX_IMAGE_SHIMS_DIR:-/usr/local/lib/swarmbox/shims}

# --- Python virtual environment (before the PATH additions, so the shims still come first) ---
_sb_venv=${SWARMBOX_VENV:-/opt/flow}
if [ -z "${VIRTUAL_ENV:-}" ] && [ -r "$_sb_venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    . "$_sb_venv/bin/activate"
fi
unset _sb_venv

# --- PATH: user shims, image shims, the tools' current/bin, ~/.local/bin, then what was there (6.2) ---
_sb_path_add() {
    case ":$PATH:" in *":$1:"*) ;; *) PATH="$1:$PATH" ;; esac
}
_sb_path_add "$HOME/.local/bin"
for _sb_d in "$SB_TOOLS_DIR"/*/current/bin; do
    [ -d "$_sb_d" ] && _sb_path_add "$_sb_d"
done
_sb_path_add "$_sb_image_shims"
_sb_path_add "$SB_SHIMS_DIR"
export PATH
unset _sb_d
unset -f _sb_path_add

# --- colors and small helpers (moved from the image's bashrc echo lines) ---
export LS_COLORS='rs=0:di=1;34:ln=1;36:mh=00:pi=40;33:so=1;35:do=1;35:bd=40;33;1:cd=40;33;1:or=40;31;1:mi=00:su=37;41:sg=30;43:ca=30;41:tw=30;42:ow=34;42:st=37;44:ex=1;32:'
alias ls='ls --color=auto'
alias ll='ls -alF --color=auto'
alias la='ls -A --color=auto'
alias l='ls -CF --color=auto'
alias grep='grep --color=auto'
alias fgrep='fgrep --color=auto'
alias egrep='egrep --color=auto'

# --- Agents from the manifests (6.3, 6.6) ---
# _sb_scan prints one record per tool, fields separated by the character 0x1f:
#   name, KIND, PROVIDES, YOLO_FLAGS, YOLO_ALIAS, MCP_FLAGS, directory
# The user level (<config>/tools) wins over the image level for the same name. Each manifest is read in a subshell,
# so its variables never reach the shell; a manifest that fails to load gives no record. Assumption: tool.conf is a sourceable KEY=VALUE file, the tool name is its directory name.
_sb_scan() {
    local base d name seen=" " us=$'\037'
    for base in "$SB_CONFIG_DIR/tools" "$_sb_image_tools"; do
        for d in "$base"/*/; do
            [ -r "${d}tool.conf" ] || continue
            d=${d%/}
            name=${d##*/}
            case "$seen" in *" $name "*) continue ;; esac
            seen="$seen$name "
            (
                unset KIND PROVIDES YOLO_FLAGS YOLO_ALIAS MCP_FLAGS
                # shellcheck source=/dev/null
                . "$d/tool.conf" >/dev/null 2>&1 </dev/null || exit 0
                printf '%s%s%s%s%s%s%s%s%s%s%s%s%s\n' "$name" "$us" "${KIND:-tool}" "$us" "${PROVIDES:-$name}" "$us" \
                    "${YOLO_FLAGS:-}" "$us" "${YOLO_ALIAS:-1}" "$us" "${MCP_FLAGS:-}" "$us" "$d"
            ) 2>/dev/null
        done
    done
}

_sb_records=$(_sb_scan)
if [ "${SWARMBOX_YOLO:-1}" != "0" ] && [ -n "$_sb_records" ]; then
    while IFS=$'\037' read -r _sb_name _sb_kind _sb_provides _sb_flags _sb_alias _sb_mcp _sb_dir; do
        [ "$_sb_kind" = "agent" ] || continue
        [ -n "$_sb_flags" ] || continue
        [ "$_sb_alias" != "0" ] || continue
        _sb_cmd=${_sb_provides%% *}
        # shellcheck disable=SC2139  # the alias is built now, from the manifest, on purpose
        alias "$_sb_cmd=$_sb_cmd $_sb_flags${_sb_mcp:+ $_sb_mcp}" 2>/dev/null
    done <<< "$_sb_records"
fi

# yolo: the default agent in auto-approve mode. The default is SWARMBOX_AGENT, else the first agent of SWARMBOX_WITH,
# else (not in the design, decision [2.4]) the first agent manifest by name. It calls the program, not the alias, so the
# flags are never given twice, and it works with SWARMBOX_YOLO=0 and for agents without an alias (YOLO_ALIAS=0).
yolo() {
    local records agent=${SWARMBOX_AGENT:-} name kind provides flags mcp found="" first="" w
    records=$(_sb_scan | LC_ALL=C sort)
    while IFS=$'\037' read -r name kind provides flags _ mcp _; do
        [ "$kind" = "agent" ] || continue
        [ -n "$first" ] || first=$name
    done <<< "$records"
    if [ -z "$first" ]; then
        echo "yolo: no agent installed (no agent manifest found; add one with SWARMBOX_WITH or swarmbox-tool)" >&2
        return 1
    fi
    if [ -z "$agent" ]; then
        for w in ${SWARMBOX_WITH//,/ }; do
            while IFS=$'\037' read -r name kind provides flags _ mcp _; do
                [ "$name" = "$w" ] && [ "$kind" = "agent" ] && { agent=$w; break; }
            done <<< "$records"
            [ -n "$agent" ] && break
        done
        [ -n "$agent" ] || agent=$first
    fi
    while IFS=$'\037' read -r name kind provides flags _ mcp _; do
        [ "$name" = "$agent" ] && [ "$kind" = "agent" ] && { found=1; break; }
    done <<< "$records"
    if [ -z "$found" ]; then
        echo "yolo: the agent '$agent' is not installed (no agent manifest of that name)" >&2
        return 1
    fi
    local -a argv
    read -r -a argv <<< "$flags $mcp"
    command "${provides%% *}" "${argv[@]}" "$@"
}

# shell.sh of every tool (6.3, 6.6), after the generated aliases so it can extend or override them. A failing file
# does not stop the shell.
while IFS=$'\037' read -r _sb_name _sb_kind _sb_provides _sb_flags _sb_alias _sb_mcp _sb_dir; do
    [ -r "$_sb_dir/shell.sh" ] || continue
    # shellcheck source=/dev/null
    . "$_sb_dir/shell.sh" </dev/null 2>/dev/null || true
done <<< "$_sb_records"
unset _sb_name _sb_kind _sb_provides _sb_flags _sb_alias _sb_mcp _sb_dir _sb_cmd _sb_records

# --- Interactive only: the banner with the startup-health lines (4.2), then the prompt ---
# Not for a shell started with -c (the command window of `swarmbox <command>` runs `bash -ic`, 3.3): the banner would
# precede the command's own output. Once per shell: a second sourcing prints nothing.
if [ -z "${SWARMBOX_CMD:-}" ] && [ -z "${BASH_EXECUTION_STRING:-}" ] && [ -z "${_sb_fragment_done:-}" ]; then
    _sb_fragment_done=1
    _sb_banner=${SWARMBOX_BANNER_SCRIPT:-/usr/local/bin/banner.sh}
    [ -x "$_sb_banner" ] && "$_sb_banner"
    # Lines of <state>/health (written by `serve` and by the host helper, including the stale-image line), one per
    # failed step or warning. Control characters are dropped so a line cannot repaint the terminal.
    if [ -s "$SB_HEALTH_FILE" ]; then
        while IFS= read -r _sb_line || [ -n "$_sb_line" ]; do
            _sb_line=${_sb_line//[[:cntrl:]]/}
            [ -n "$_sb_line" ] && printf '  \033[0;33m!\033[0m %s\n' "$_sb_line"
        done < "$SB_HEALTH_FILE"
    fi
    unset _sb_banner _sb_line
    # Starship redefines PS1, so it comes last.
    _sb_starship=${SWARMBOX_STARSHIP_INIT:-/etc/swarmbox/scripts/starship-init.sh}
    # shellcheck source=/dev/null
    [ -r "$_sb_starship" ] && . "$_sb_starship"
    unset _sb_starship
fi
# _sb_scan and _sb_image_tools stay defined: `yolo` uses them when it runs.
unset _sb_image_shims
