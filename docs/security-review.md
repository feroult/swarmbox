# Security review of the host helper

Reviewed 2026-11-08 by the AI agent that wrote the code, reading it line by line. **No human reviewed it and no third party audited it.**
Treat it as a first written review, not an audit. A human review is on the [release checklist](release-checklist.md).

## Scope

Read in full: the host helper `container/host/swarmbox-host` (POSIX sh: configuration, `create-flags`, `fingerprint`, `up`, `reset`, `stop`, `url`,
`update`, `remote`, the connector step, the lock, temporary files, every `eval`, the extraction of the helper from the image), the function
templates `container/host/templates/{bash,zsh,fish}`, `container/scripts/swarmbox-init.sh`, and `cloudflare-setup.py` as the back end of `remote`.

Not reviewed: the container side (`serve`, tools, shims), the web terminal, Cloudflare's services, Podman itself, the signing of the image,
and the flags the helper builds as Podman handles them. No real macOS, no real WSL and no Podman older than 4.3 were available, so behaviour
that differs there (BSD `stat` and `find` for the mode check, `mktemp -d` templates, `chmod` on `/mnt`) is unverified.

## Threat model

The helper runs as the host user. Inputs come from the user (command line, environment, config file), from other accounts on the machine (only
through folders they can write, so the question is whether the helper puts anything in such a folder), and from the image the user chose (it supplies the
helper archive that is then run). A hostile image is not defended against beyond refusing a malformed archive: it already supplies code the host runs
next (D26). A hostile process of the same user is out of scope.

## Findings

Severity: high (host compromise from unprivileged input), medium (a guard can be bypassed by crafted input), low (hardening, a local-account concern),
info (reviewed, no defect). Status: `fixed` (code changed, a regression test fails without it) or `documented` (no change, reason given). No finding is open.
Tests are in `tests/test_security_review.py`, by class.

| ID | Severity | Location | Finding | Status | Test |
|---|---|---|---|---|---|
| SR-01 | medium | `validate_value` (IMAGE), `connector_ensure`, `cloudflare-setup.py`, `swarmbox-init.sh` | An image reference starting with `-` was read by `podman pull` or `run` as an option (`IMAGE=--privileged`, the connector image override, `init --image`). One `valid_image_ref` now refuses a leading `-` and characters outside the reference set everywhere. | fixed | ImageReferenceTest |
| SR-02 | low | `cfg_write_keys`, `notice_clear`, `ensure_state_dir`, `capture_flags` | Temporary files had predictable names (the pid) and were opened with `>`, which writes through a planted symlink. The name is now removed first and the config and notices files are created with noclobber. | fixed | TempFileTest |
| SR-03 | low | `private_dir` (config, state, data folders) | A folder that already existed with mode 755 or 777 stayed open to other accounts. The helper now removes group and other permissions from the three folders it writes in (never adds, never recursive). | fixed | TempFileTest |
| SR-04 | low | `cloudflare-setup.py` `save_config` | `cloudflare.json` was written with the umask mode, through a symlink at the final name. It is now written with `mkstemp` (mode 600), `chmod 600` and `os.replace`, in a mode 700 folder. | fixed | TempFileTest |
| SR-05 | low | `cmd_update`, `archive_safe` | The archive from `podman run <image> host-helper` was unpacked and only the result tested. Member names must now not be absolute or contain `..`, and every member must be a plain file or folder (no links or devices) before extraction; otherwise exit 3 and nothing changes. | fixed | UpdateInputTest |
| SR-06 | low | `templates/bash`, `zsh`, `fish` (the bootstrap) | The function extracts the helper with `tar -x` into a fresh `mktemp -d` folder without a member check. Not changed: the archive comes from the image the function names, whose helper is executed straight after, so a check adds no boundary. The folder is swapped in only when the archive unpacked and the helper is executable; a failure keeps the old copy. `update` does check the archive (SR-05). | documented | UpdateInputTest |
| SR-07 | info | `acquire_lock`, `reap_stale`, `sweep_state` | The lock is an atomic `mkdir` with the holder's pid. A symlink planted at the lock name is never followed. A recycled pid can make a dead holder look alive until the wait ends (exit 6, the message names the folder to remove). Accepted: the failure is a refusal to start, never a second box. | documented | TempFileTest |
| SR-08 | info | `up_cleanup`, `up_traps` | The EXIT trap removes this call's temporary files and its own lock on every exit path; HUP, INT and TERM exit with 129, 130 and 143. SIGKILL cannot be trapped; leftovers are swept by the next `up` once their pid is gone. | documented | CleanupTest |
| SR-09 | info | `validate_value`, `check_workspace`, `create_box`, `cmd_create_flags` | Quoting. A workspace path with spaces, quotes, `$(...)`, backticks, `;`, `*`, a leading `-`, a tab or non-ASCII reaches Podman as one argument; a newline, carriage return or `:` is refused (exit 2). Flags travel one per line. Every `eval` (13, counted with grep) takes a validated variable name or a key from a fixed list. Values of `ENV_KEYS` go by name only (`-e NAME`), so never in argv. No defect found. | documented | QuotingTest |
| SR-10 | info | `resolve_tunnel_token`, `connector_ensure`, `read_secret`, `cmd_remote`, `cfg_write_keys` | Tunnel token. Never accepted as an argument or read from a pipe (typed on a terminal, echo off, `stty` restored); stored only at mode 600 (the write is refused if `chmod` fails); a file holding it with another mode is ignored with a warning naming `chmod 600`. It reaches Podman only through the environment of `podman run`, never argv, and is removed from the environment of `cloudflare-setup.py`. Not in the box's create arguments, labels, environment, `create-flags`, `fingerprint`, `config list`, `url` or any message. Names starting `SWARMBOX_CLOUDFLARE_` cannot go in `ENV_KEYS`. | documented | TokenTest |
| SR-11 | low | `cmd_config_get`, the connector container | Two places show the token by design: `config get CLOUDFLARE_TUNNEL_TOKEN` and `remote token` print it because the user asked; and the connector container holds it in its environment, so `podman inspect` and `/proc/<pid>/environ` show it to the same user and root. The token can only connect a connector to its own tunnel and is rotated by deleting the tunnel. Accepted. | documented | TokenTest |
| SR-12 | info | `valid_tag`, `cmd_update`, `split_image` | `update --to` input and rollback. A tag must start with a letter, digit or `_`, use only letters, digits, `_`, `.`, `-`, and be at most 128 bytes, else exit 2 before any Podman call. The version the archive reports must be a plain `X.Y.Z` and, for an exact tag, equal the tag; any failure leaves the helper, config and local tags as they were. This is a consistency check, not an integrity check: integrity is the job of signing and of pulling from the owner's registry (D26). | documented | UpdateInputTest |
| SR-13 | info | `parse_line`, `cfg_raw`, `cfg_prepare`, `is_file_key` | Config parsing. The file is read line by line with `read -r`, never sourced or evaluated; only keys of a fixed list are used, so `PATH=`, `LD_PRELOAD=`, `IFS=` and `SWARMBOX_*` lines are inert. `$(...)` and backticks in a value are literal text. | documented | ConfigParsingTest |
| SR-14 | info | `umask 077`, `cfg_write_keys`, `cmd_update`, `save_config` | File modes. With umask 000 everything the helper creates under the config, state and data folders has no group or other permission. The mode is read as an octal number (`stat -c %a`, `stat -f %Lp`, `find -perm`), never from `ls`. The BSD forms were not run on a real macOS (unverified). | documented | ModeTest |
| SR-15 | low | `notice_mark` | The notices file (names of keys already announced, not secret) is appended with `>>`, which follows a symlink at that name. The folder is private (SR-03), so only the user can plant it. Accepted: same-user input is out of scope. | documented | TempFileTest |

## Tools and limits

- `shellcheck -s sh container/host/swarmbox-host container/scripts/swarmbox-init.sh` found nothing (shellcheck 0.9.0, 2026-11-08). The bash template reports two intended notes
  (SC2015, SC2088); the zsh and fish templates cannot be checked.
- `tests/test_security_review.py` runs the real helper and script against a fake Podman, on `mktemp` folders only.
- The real registry, image signing and a real Cloudflare account were not used. The review is of the code at this commit; a change to the helper needs these tests run again (`sh tests/run_all.sh` does).
