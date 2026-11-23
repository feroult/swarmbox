# tests/e2e

The manual harnesses with the real `claude` and the long soak (`sh tests/run.sh e2e` runs every `*.sh` here). The first ones (`e2e_sysop`,
`e2e_voice`, `soak_v1`) drove a real tmux and ttyd and went away with tmux: herdr is the only multiplexer of the box. New harnesses for herdr-core
and the Herdr Web Studio go here.
