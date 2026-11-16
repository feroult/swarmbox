# Gemini CLI. Sourced by every interactive shell (bash and zsh). It starts Gemini in auto-approve mode (--yolo).
# SWARMBOX_YOLO=0 (set by the host, `swarmbox config set YOLO 0`) turns it off. `command gemini` reaches the program (or its shim) on PATH.
gemini() {
    if [ "${SWARMBOX_YOLO:-1}" = 0 ]; then
        command gemini "$@"
    else
        command gemini --yolo "$@"
    fi
}
