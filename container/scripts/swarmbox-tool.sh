#!/bin/bash
# swarmbox-tool: the STUB of Phase 2 (design 6, 10.2; installed as /usr/local/bin/swarmbox-tool). The real program (manifests,
# link, install, run, validate) is Phase 4a. Until then:
#
#   validate        a placeholder: says so and passes (the smoke test calls it, 13.3)
#   link --system   writes an EMPTY box:/usr/local/share/swarmbox/host/tool-ports (the image build always writes the file, 3.7.1)
#   link --user     nothing to do, succeeds, so that `serve` and the host function do not warn at every start
#   prepare         nothing to do, succeeds
#   anything else   exit 70 (EX_SOFTWARE) with a message that names Phase 4a
#
# Test-only variable (decision log [2.5]): SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host.

HOST_DIR=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}

usage() {
    echo "usage: swarmbox-tool validate | link --system|--user | prepare   (stub: the real swarmbox-tool arrives in Phase 4a)" >&2
    exit 64
}

[ $# -ge 1 ] || usage
cmd=$1
shift
case "$cmd" in
    validate)
        echo "swarmbox-tool validate: placeholder. No tool manifests exist yet (they arrive in Phase 4a), so there is nothing to validate."
        ;;
    link)
        [ $# -eq 1 ] || usage
        case "$1" in
            --system)
                if ! mkdir -p "$HOST_DIR" || ! : > "$HOST_DIR/tool-ports"; then
                    echo "swarmbox-tool: cannot write $HOST_DIR/tool-ports" >&2
                    exit 1
                fi
                echo "swarmbox-tool link --system: stub, wrote an empty $HOST_DIR/tool-ports"
                ;;
            --user)
                echo "swarmbox-tool link --user: stub, no tools to link yet (Phase 4a)"
                ;;
            *) usage ;;
        esac
        ;;
    prepare)
        echo "swarmbox-tool prepare: stub, no tools to prepare yet (Phase 4a)"
        ;;
    *)
        echo "swarmbox-tool: '$cmd' is not available yet: this is a placeholder, tools arrive in Phase 4a of the SwarmBox 2.0 build" >&2
        exit 70
        ;;
esac
