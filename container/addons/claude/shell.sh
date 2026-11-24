# Claude Code. Sourced by every interactive shell (bash and zsh). It starts Claude Code in auto-approve mode with the MCP servers of the box:
# --dangerously-skip-permissions and --mcp-config $HOME/.claude/mcp-servers.json. The flags go only to the prompt form (`claude`,
# `claude -p ...`, `claude "a prompt"`): a subcommand such as `claude update` or `claude mcp list` is passed through untouched, because
# it may refuse them. SWARMBOX_YOLO=0 (set by the host, `swarmbox config set YOLO 0`) turns the function off: plain `claude`.
# `command claude` reaches the program (or its shim) on PATH, not this function.
claude() {
    case "${1:-}" in
        agents | attach | auth | auto-mode | doctor | gateway | import | install | logs | mcp | plugin | plugins | purge | respawn | rm | setup-token | stop | kill | ultrareview | update | upgrade)
            command claude "$@"
            return
            ;;
    esac
    type _sb_worktree_guard >/dev/null 2>&1 && { _sb_worktree_guard claude "$@" || return $?; }
    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then
        command claude "$@"
    else
        command claude --dangerously-skip-permissions --mcp-config "$HOME/.claude/mcp-servers.json" "$@"
    fi
}
