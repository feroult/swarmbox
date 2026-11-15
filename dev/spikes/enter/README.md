# Spike "enter"

Types a prompt into the real Claude Code TUI in tmux and makes it submit. Report: [docs/spikes/enter.md](../../../docs/spikes/enter.md).

- `enter.sh`: the PoC driver (recommended method, state checks, exit codes).
- `lib.sh`: helpers (isolated tmux socket, `boot`, `state`, `seed_home`) sourced by the test scripts.
- `trials.sh`, `special.sh`, `special2.sh`, `busy-keys.sh`, `keys.sh`, `screens.sh`, `poc-test.sh`: the experiments.
- `screens/`: real captures of each state.

Run inside the test image, never on the master box:

    podman run --rm --userns=keep-id:uid=1000,gid=1000 -e CLAUDE_CODE_OAUTH_TOKEN -v $PWD:/spike:ro \
      --tmpfs /work:rw,exec,mode=1777,size=3g localhost/swarmbox-sysop-test bash /spike/poc-test.sh
