# OpenCode. Sourced by every interactive shell. It renders nothing: prepare.sh writes the file at every start.
# OpenCode merges this file with, and never instead of, the user's own opencode.json.
export OPENCODE_CONFIG=/tmp/swarmbox/opencode.json

# Auto-approve: --auto is accepted by `opencode` and `opencode run` and refused before any other subcommand, so the function adds it
# only for those two (and for the options and the project folder of the plain form), never for `opencode mcp ...`, `opencode auth ...`
# and the like. SWARMBOX_YOLO=0 (set by the host, `swarmbox config set YOLO 0`) turns it off. `command opencode` reaches the program
# (or its shim) on PATH, not this function.
# Repository context (the sysop's autocontext, _sb_context of swarmbox-agents sh): a session of the plain form started on a commit with
# a digest gets it as an instruction file (OPENCODE_CONFIG_CONTENT {"instructions":[FILE]}, merged with the other configs; OpenCode
# puts it in the system prompt), run with --standalone: the shared background service reads its config once, from the environment of
# the session that started it, so another session would get that session's context (measured with 2.4.2). A user's own
# OPENCODE_CONFIG_CONTENT wins: no context then. `opencode run` is a one-shot call: no context.
_sb_opencode_session() {
    local _oc_f
    _sb_context_file=
    if [ -z "${OPENCODE_CONFIG_CONTENT:-}" ] && type _sb_context >/dev/null 2>&1; then
        _sb_context opencode
    fi
    if [ -n "$_sb_context_file" ]; then
        _oc_f=${_sb_context_file//\\/\\\\}
        _oc_f=${_oc_f//\"/\\\"}
        OPENCODE_CONFIG_CONTENT="{\"instructions\":[\"$_oc_f\"]}" command opencode --standalone "$@"
    else
        command opencode "$@"
    fi
}
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
        case "${1:-}" in
            -h | --help | -v | --version) command opencode "$@" ;;
            "" | -*) _sb_opencode_session "$@" ;;
            *) if [ -d "$1" ]; then _sb_opencode_session "$@"; else command opencode "$@"; fi ;;
        esac
        return
    fi
    case "${1:-}" in
        -h | --help | -v | --version) command opencode "$@" ;;
        run)
            shift
            command opencode run --auto "$@"
            ;;
        "" | -*) _sb_opencode_session --auto "$@" ;;
        # a subcommand wins over a project folder of the same name in the current folder
        completion | acp | mcp | attach | debug | auth | agent | upgrade | uninstall | serve | web | models | stats | export | import | github | pr | session | db | generate)
            command opencode "$@"
            ;;
        *)
            if [ -d "$1" ]; then
                _sb_opencode_session --auto "$@"
            else
                command opencode "$@"
            fi
            ;;
    esac
}
