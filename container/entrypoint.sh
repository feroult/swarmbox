#!/bin/sh
# swarmbox-entrypoint (design 10.2): placeholder from slice 2.1.
# The image needs an ENTRYPOINT to build and to run any command; the subcommands serve, attach, init, pubkey, tool and
# host-helper are written by the next slices of Phase 2. Until then they fail loudly instead of pretending to work
# (exit 70, EX_SOFTWARE); any other command is run as given, which is already the final behavior (design 10.2).
case "${1:-}" in
    serve|attach|init|pubkey|tool|host-helper)
        echo "swarmbox-entrypoint: '$1' is not implemented in this build yet (Phase 2, slice 2.1 placeholder)" >&2
        exit 70
        ;;
    "")
        echo "swarmbox-entrypoint: no command given" >&2
        exit 64
        ;;
    *)
        exec "$@"
        ;;
esac
