# Antigravity CLI (agy). Sourced by every interactive shell (bash and zsh). It starts agy in auto-approve mode (--dangerously-skip-permissions).
# The flag goes only to the prompt form (`agy`, `agy -p ...`, `agy "a prompt"`): a subcommand such as `agy update` or `agy mcp list` is
# passed through untouched, because it may refuse the flag. SWARMBOX_YOLO=0 (set by the host, `swarmbox config set YOLO 0`) turns it off.
# `command agy` reaches the program (or its shim) on PATH, not this function.
agy() {
    case "${1:-}" in
        acp | agent | agents | changelog | help | install | mcp | mic-serve | models | plugin | plugins | remote-control | update)
            command agy "$@"
            return
            ;;
    esac
    type _sb_worktree_guard >/dev/null 2>&1 && { _sb_worktree_guard agy "$@" || return $?; }
    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then
        command agy "$@"
    else
        command agy --dangerously-skip-permissions "$@"
    fi
}
