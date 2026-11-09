# Owner checks: what needs real hardware

The development box is a Linux container with host UID 1000 and Podman 4.3.1. It cannot run macOS, a user with another UID, an older Podman, a
clean macOS `python3`, or a real Windows drive under WSL. This file is the closing checklist for those facts of design Part B (B6, B7, B8, B15
and the macOS or WSL parts of B19, B21, B22, B23, B32, B34). Nothing here was run on that hardware. Every check below is **open with the owner**
until you paste the result back; the decision log entry `[6.6]` says what was reduced here and why.

## How to run the script

`dev/owner-check.sh` is POSIX `sh`. It is read-only apart from one `mktemp` folder, which it removes on exit, and containers named
`swarmbox-test-*` (started with `--rm`, removed again by their exact name). It never touches your real SwarmBox configuration, workspace or a box named
`swarmbox`; it refuses to start when `SWARMBOX_NAME` is set to anything that does not start with `swarmbox-test-`.

```sh
git clone <the repository> swarmbox-src && cd swarmbox-src       # or use your existing checkout
sh dev/owner-check.sh --list                                      # the check ids
env -u SWARMBOX_NAME sh dev/owner-check.sh 2>&1 | tee owner-check.out
```

Paste `owner-check.out` back. Lines are `PASS <id> ...`, `FAIL <id> ...`, `SKIP <id> <reason>`, `INFO <topic> ...` and a last
`SUMMARY pass=N fail=N skip=N`. The exit status is 1 when any line is `FAIL`. A `SKIP` is not a pass: it says why the check did not run.

Options you will need below: `--image REF` (the plain image of the container checks, default `docker.io/library/debian:bookworm-slim`, pulled by
Podman on first use), `--box-image REF` (the SwarmBox image, for B21; nothing is pulled for it), `--workdir-parent DIR` (where the temporary folder is created),
`--helper PATH` (default: the installed helper under `${XDG_DATA_HOME:-~/.local/share}/swarmbox/host`, else the one in the checkout; it is copied first),
`--no-container`, `--only B22,B34`.

## State of each fact

| Fact | State | What closes it | Script id | Section |
|---|---|---|---|---|
| B6 the whole design on macOS | open with the owner | a Mac with a Podman machine | `B6.machine`, `box.workspace-write`, `box.tun` and the manual steps | B6 |
| B7 host UID other than 1000 | open with the owner (helper side closed-reduced) | a user with another UID (a Mac user is 501) | `B7.host-uid` | B7 |
| B8 lowest Podman version | open with the owner | Podman 4.0, 4.3, 4.9 and the latest | `B8.podman-version` and the manual steps | B8 |
| B15 `python3` on a clean macOS | open with the owner | a Mac that never had the Command Line Tools | `B15.python3` | B15 |
| B19 macOS `sort -V`, bash 3.2 | open with the owner (Linux closed) | a Mac | `B19.sort-v` | Rechecks |
| B21 `-e SHELL` through the Podman machine | open with the owner (Linux closed) | a Mac (zsh) and the SwarmBox image | `B21.shell-env` | Rechecks |
| B22 token file mode, macOS and a WSL home | open with the owner (Linux closed) | a Mac; WSL with a folder on `/mnt/c` | `B22.token-mode` | Rechecks |
| B23 helper under macOS `/bin/sh` | open with the owner (Linux closed) | a Mac | `B23.helper-sh` | Rechecks |
| B32 real WSL and Windows drives | open with the owner (refusal logic closed-reduced) | a WSL2 distribution | `B32.wsl-refusal` | Rechecks |
| B34 macOS `stat` with extended attributes | open with the owner (Linux closed) | a Mac | `B34.mode-forms` | Rechecks |
| Migration of the real box | open with the owner | your real workspace | none | Dogfooding |

What was done here instead, all `[reduced]`: the script runs against a fake `uname` (Darwin and Linux), a fake `/proc/version` (WSL), a fake
`xcode-select` and a fake Podman (`tests/test_owner_check.py`, 32 tests under dash, bash and sh); the script ran against the real Podman 4.3.1 of the development box
with `swarmbox-test-` names; and the script ran as another user (`nobody`, UID 65534, through `sudo -n -u`) in a `mktemp` home. A real Podman with a host UID other than 1000
was tried (`unshare --map-user=2000`) and refused to run keep-id because no subuid range exists for that user; so the Podman side of B7 is not proven.

## B6: macOS through a Podman machine

Prepare: `brew install podman`, `podman machine init`, `podman machine start`. Then the script, with the temporary folder under your home when your temporary folder is not shared with the machine:

```sh
env -u SWARMBOX_NAME sh dev/owner-check.sh --only B6,box,B7,B15,B19,B22,B23,B34 --workdir-parent "$HOME"
```

Expected on a working Mac: `PASS B6.machine` (a machine with `running=true`), `PASS box.workspace-write` (the container saw uid/gid `1000 1000` and the file on the host is
owned by your user), `PASS box.tun`. `B7.host-uid` is `PASS` too, because your macOS user is not 1000. A `FAIL box.workspace-write` with "not shared" means the folder is
outside the folders the machine shares: record the folder and the `podman machine inspect` output.

Then the manual run of the real product, with the image of your choice (a local registry, [local-registry.md](local-registry.md)). Use a second box so that nothing real is touched:

```sh
export SWARMBOX_NAME=dev
swarmbox config set WORKSPACE "$HOME/swarmbox-dev"       # a folder under your home (the machine shares /Users)
swarmbox                  # first call: pull, create, enter; leave with exit
swarmbox reset            # recreate; the workspace is kept
swarmbox url              # then open the address in a browser: the web terminal
swarmbox stop
podman -c dev ps          # the host connection of the box (it may fail on macOS: the socket does not cross the VM; record it)
```

Expected: each command exits 0, a file written in the box shows in the folder on the Mac, the web terminal opens. Record every failure with the exact message as a documented limit in design Part B (B6):
the design already says what each failure should look like (for an unshared folder, exit 4 with the "not shared with the Podman machine" text of 3.5).
`podman -c` across the VM is the part B6 lists as possibly failing (the socket does not cross the VM); write down what you see.

## B7: a host UID other than 1000

On Linux, create a user and run the same script as that user (rootless Podman needs `/etc/subuid` and `/etc/subgid` lines for it, which `useradd` adds on most distributions):

```sh
sudo useradd -m swarmtest && id -u swarmtest        # expect a number other than 1000
sudo -iu swarmtest sh -c 'cd /path/to/swarmbox-src && sh dev/owner-check.sh --only B7,box'
```

Expected: `PASS B7.host-uid host uid N: keep-id:uid=1000,gid=1000 gave 1000/1000 inside and ownership N on the host`. On a Mac the same line comes from the run in B6.
Then, for a real box as that user, write a file in the workspace from inside and look at it with `ls -ln` on the host: the owner must be that UID.

Remove the test user afterwards: `sudo userdel -r swarmtest`.

## B8: the lowest Podman version

```sh
podman --version
sh dev/owner-check.sh --only B8,box
```

Expected: `PASS B8.podman-version` for 4.3 and newer. Below 4.3 it prints `FAIL` on purpose: the helper refuses those versions with exit 3
(`swarmbox: Podman X.Y found, 4.3 or newer is required.`). To learn whether an older version would really work, run the container checks on it and record the result:

```sh
sh dev/owner-check.sh --only box --image docker.io/library/debian:bookworm-slim     # keep-id and the tun device
```

Record the Podman version and which of `box.workspace-write` and `box.tun` passed, for 4.0, 4.3, 4.9 and the latest. If 4.0 to 4.2 pass everything, the helper's gate in
`check_podman_version` may be lowered; that is a decision for you, not made here. The full smoke test (`SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py`) is the stronger check and needs a built image.

## B15: `python3` on a clean macOS

Use a Mac that has never installed the Command Line Tools (or check `xcode-select -p`; "no developer tools were found" means clean).

```sh
sh dev/owner-check.sh --only B15
swarmbox remote status    # with the function installed
```

Expected on a clean Mac: `FAIL B15.python3 ... only the Command Line Tools stub`. The script does not run that stub, because running it opens an install dialog. Then
`swarmbox remote status` prints that `python3` is missing and exits 3; every other command works. After the Command Line Tools (or Homebrew's Python) are installed the line is `PASS`.
If your Mac passes, the fact is "python3 is present" for that macOS version: record the version of macOS (`sw_vers -productVersion`).

## Rechecks: the macOS and WSL parts of B19, B21, B22, B23, B32, B34

One run on the Mac covers B19, B22, B23 and B34 (the ids are in the script list):

```sh
env -u SWARMBOX_NAME sh dev/owner-check.sh --only B19,B22,B23,B34
/bin/bash --version | head -n 1       # macOS ships bash 3.2: the function and the helper must work with it
```

- **B19** expects `PASS B19.sort-v` with `sh=ok /bin/bash=ok` (and `zsh=ok`): `sort -V` puts `2.0.9` before `2.0.10`. A `FAIL` means macOS `sort` lacks `-V`; the function then keeps the helper and prints no update notice (design 3.6).
- **B22** expects `PASS B22.token-mode`: mode 600 accepted, mode 644 ignored with a warning that names `644` and `chmod 600`.
- **B23** expects `PASS B23.helper-sh` listing `[/bin/sh]=ok` (macOS `/bin/sh` is bash 3.2 in POSIX mode).
- **B34** expects `PASS B34.mode-forms` with `600=ok 644=ok xattr-600=ok`. The `INFO B34` lines show what each form (`stat -c %a`, `stat -f %Lp`, `find -perm`) printed: on a Mac `stat -f %Lp` is the one that answers.
- **B21** needs the image, in a shell where `SHELL` is zsh: `sh dev/owner-check.sh --only B21 --box-image ghcr.io/<org>/swarmbox-dev:2.0.0` (use your local registry reference). Expected: `PASS B21.shell-env init printed the syntax of the SHELL it was given: real->zsh dash->bash zsh->zsh fish->fish unset->bash`.

On WSL2, with a Linux-filesystem home:

```sh
env -u SWARMBOX_NAME sh dev/owner-check.sh --only B32,B22,B34
```

- **B32** expects `PASS B32.wsl-refusal` (a workspace under `/mnt/c/...` refused with exit 4; one in the temporary folder accepted), and `INFO B32 findmnt` lists the `drvfs` or `9p` mounts of your drives. B22 and B34 run the same way as on the Mac.

Then the WSL **home on a Windows drive** (B22, B34), with a folder that you create yourself on the drive; the script makes its own folder inside it and removes it:

```sh
mkdir -p /mnt/c/Users/<you>/swarmbox-check-parent
env -u SWARMBOX_NAME sh dev/owner-check.sh --only B22,B34,B32 --workdir-parent /mnt/c/Users/<you>/swarmbox-check-parent
rmdir /mnt/c/Users/<you>/swarmbox-check-parent
```

Expected on a drive mounted without metadata: `FAIL B22.token-mode ... this filesystem does not keep modes` (`chmod 600` has no effect there). That is the answer to the question
and it means the token must not be kept in a config file on such a drive: record it. On a drive with `metadata` in its mount options the line is `PASS`.
The same run reports `B32.wsl-refusal` with the temporary folder on a Windows drive: it then expects exit 4 for that folder too, which is the D34 rule.
The development box's kernel string says WSL2 (it is a container on a WSL2 machine), so `B32.wsl-refusal` passes here, but it has no `/mnt/c` and no 9p mount: it proves the refusal text, not a Windows drive. It stays open.

## Dogfooding and migrating your real box

Order matters, and nothing here was done by the build. Details and the file table are in [migration.md](migration.md).

1. **Back up** while the old container is stopped: `podman stop swarmbox && cp -a /path/to/.work /path/to/.work.backup`.
2. **Run a second box first** (`SWARMBOX_NAME=dev`, another workspace and another web port) from the 2.0 image, and use it for a few days:

   ```sh
   SWARMBOX_NAME=dev swarmbox config set WORKSPACE ~/code/dev
   SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682
   SWARMBOX_NAME=dev swarmbox
   ```

3. **Try the migration on a copy** of the real workspace (the section "Try it on a copy first" of migration.md), then compare the hashes of the original.
4. **Migrate the real workspace** with the numbered steps of migration.md. The v0.1.0 tag stays; `git checkout v0.1.0` runs the old version again if you must go back.
5. Run `swarmbox remote status` if you used remote access, and the end-to-end Cloudflare checklist of [cloudflare.md](cloudflare.md).

## What to send back

The whole `owner-check.out` of each machine, `uname -a`, `podman --version` and (macOS) `sw_vers`, plus the notes of the manual steps. With those the facts can be closed in design Part B with an evidence
tag of the form `[verified: dev/owner-check.sh; <date>; Podman <version>, <OS>; <image>]`. Until then they stay `[unverified]`.

## B20: `swarmbox update` against the real registry (after the first publish)

B20 is closed only against a local registry (`tests/e2e_registry.py`). The real registry stays `[unverified]` until you run this once, after the tag `v2.0.0`
has produced the package `ghcr.io/feroult/swarmbox-dev` and you have set the package public (docs/release-checklist.md). Use a second box so the real one is not touched,
and a throwaway home so nothing of your own configuration is read or written:

```sh
export H=$(mktemp -d) && export XDG_CONFIG_HOME=$H/c XDG_DATA_HOME=$H/d XDG_STATE_HOME=$H/s     # throwaway state
podman manifest inspect ghcr.io/feroult/swarmbox-dev:2.0.0 | grep -c '"architecture"'               # 2 or more: amd64 and arm64
podman manifest inspect ghcr.io/feroult/swarmbox-dev:2.0 | grep -c '"architecture"'                 # the moving tag exists too
cosign verify --certificate-identity-regexp '^https://github.com/feroult/swarmbox/.github/workflows/release.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/feroult/swarmbox-dev:2.0.0 >/dev/null && echo SIGNED
podman run --rm -e SHELL ghcr.io/feroult/swarmbox-dev:2.0.0 init --with claude --workspace $H/ws > $H/function.sh   # prints only
export SWARMBOX_NAME=swarmbox-b20 && . $H/function.sh        # bash or zsh; for fish use `source` on a file printed with --shell fish
swarmbox update                  # expect: pulls ghcr.io/feroult/swarmbox-dev:2.0, reads the exact version, records IMAGE, says to run swarmbox reset
swarmbox config get IMAGE        # expect: ghcr.io/feroult/swarmbox-dev:2.0.Z, the exact tag
swarmbox update --to 2.0.0       # expect: pulls that tag; IMAGE is ghcr.io/feroult/swarmbox-dev:2.0.0
swarmbox reset                   # creates the box from the recorded tag (a throwaway workspace under $H/ws)
swarmbox version                 # the helper version equals the image tag
```

Then the offline half: disconnect the network (airplane mode or `sudo ip link set <iface> down`) and run `swarmbox reset` again. It must start the same box from the local tag
with no pull. Clean up: `podman rm -f swarmbox-b20; podman volume rm swarmbox-b20-containers` (the exact names; a `podman volume ls` shows them), `rm -rf "$H"`, and
`unset SWARMBOX_NAME XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME`. With only `2.0.0` published, the `swarmbox update` line moves the series to `2.0.0` itself; the rollback
half (`update --to` an older tag) needs a second published version, so it stays `[unverified]` until `2.0.1` exists. Record the evidence as
`[verified: the commands above on the real registry; <date>; Podman <version>, <OS>; ghcr.io/feroult/swarmbox-dev:<tag>]` in design Part B, row B20.

## Clean machine: README only

The exit criterion of the release is that a stranger can install from the README alone. Use a machine or a fresh user that has Podman and nothing else of this project
(no checkout, no `~/.local/share/swarmbox`, no `~/.config/swarmbox`). Open only README.md (on the web page of the repository) and follow it with the clock running:

1. Read the top block. Copy the install line without the `>> ~/.bashrc` part, read the function it prints, then run it with the append. Time: under 2 minutes without the image pull.
2. Open a new terminal. Run `swarmbox`. The first call pulls the image and opens a shell in the box. A second terminal running `swarmbox` joins the same tmux session.
3. In the box run `claude --version` (first call installs it), then `yolo` only if you have a login you accept to use.
4. `swarmbox url`: the address opens the web terminal in a browser on the same machine.
5. `swarmbox stop`, then follow the Uninstall section of the README step by step and check that `ls ~/.config/swarmbox ~/.local/share/swarmbox` finds nothing.

Write down every place where you had to leave the README (to search, to ask, to read the design): each is a README defect. The step count and the wall time are the result.
This check was not run by the build (no published image and no second clean machine); it is open with the owner.
