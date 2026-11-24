# OpenCode. Sourced by every interactive shell. It renders nothing: prepare.sh writes the file at every start.
# OpenCode merges this file with, and never instead of, the user's own opencode.json.
export OPENCODE_CONFIG=/tmp/swarmbox/opencode.json

# Auto-approve: --auto is accepted by `opencode` and `opencode run` and refused before any other subcommand, so the function adds it
# only for those two (and for the options and the project folder of the plain form), never for `opencode mcp ...`, `opencode auth ...`
# and the like. SWARMBOX_YOLO=0 (set by the host, `swarmbox config set YOLO 0`) turns it off. `command opencode` reaches the program
# (or its shim) on PATH, not this function.
opencode() {
    case "${1:-}" in
        -h | --help | -v | --version | run | completion | acp | mcp | attach | debug | auth | agent | upgrade | uninstall | serve | web | models | stats | export | import | github | pr | session | db | generate) ;;
        *)
            if [ -z "${1:-}" ] || [ "${1#-}" != "$1" ] || [ -d "$1" ]; then
                type _sb_worktree_guard >/dev/null 2>&1 && { _sb_worktree_guard opencode "$@" || return $?; }
            fi
            ;;
    esac
    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then
        command opencode "$@"
        return
    fi
    case "${1:-}" in
        -h | --help | -v | --version) command opencode "$@" ;;
        run)
            shift
            command opencode run --auto "$@"
            ;;
        "" | -*) command opencode --auto "$@" ;;
        # a subcommand wins over a project folder of the same name in the current folder
        completion | acp | mcp | attach | debug | auth | agent | upgrade | uninstall | serve | web | models | stats | export | import | github | pr | session | db | generate)
            command opencode "$@"
            ;;
        *)
            if [ -d "$1" ]; then
                command opencode --auto "$@"
            else
                command opencode "$@"
            fi
            ;;
    esac
}
