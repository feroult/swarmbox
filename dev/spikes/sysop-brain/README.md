# Spike: sysop-brain (isolation and streaming of the brain)

Harness of section 8 of [docs/sysop-brain-design.md](../../../docs/sysop-brain-design.md). Run in a scratch folder, never against the live sysop.

- `fake_mcp.py`: a stdio MCP server with `say`, `run` (sleeps `RUN_SLEEP` s), `done`, `envnames`; logs every request raw, with a timestamp.
- `drive.py OUT GOAL [--cfg DIR] [--home DIR] [--cwd DIR] [--resume SID] [--model M] [--run-sleep S] [--sigint-after-say] [--wrap DIRS] [--extra ARG]...`:
  the brain invocation of the design with standard output on a pipe, every line timestamped (`OUT/stream.tsv`), an allowlisted environment
  (`PATH`, `HOME`, `LANG`, `CLAUDE_CODE_OAUTH_TOKEN`, optional `TMPDIR` from `SPIKE_TMPDIR`), peak RSS/VSZ/threads of the process group.
- `init.py OUT`: what the `init` and `result` events say.
- `landlock_exec.py DIR[:DIR...] -- CMD...`: denies every filesystem write outside the folders (reads stay open), then runs CMD.

Needs `CLAUDE_CODE_OAUTH_TOKEN` in the environment.
