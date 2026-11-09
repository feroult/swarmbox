# clasp. Sourced by every interactive shell (bash and zsh). `clasp login` starts a local OAuth listener; the box publishes
# one fixed port for it (PORTS in tool.conf), so login must use that port. Every other subcommand, and a login that already names
# a port, is passed through untouched. `command clasp` reaches the shim on PATH, not this function.
clasp() {
    if [ "${1:-}" = login ]; then
        local _sb_a
        for _sb_a in "$@"; do
            case "$_sb_a" in
                --redirect-port | --redirect-port=*)
                    command clasp "$@"
                    return
                    ;;
            esac
        done
        shift
        command clasp login --redirect-port 43323 "$@"
        return
    fi
    command clasp "$@"
}
