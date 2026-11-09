# Owner checks: what needs real hardware

The development box is a Linux container with host UID 1000 and Podman 4.3.1. It cannot show macOS, a host user with another UID, an older Podman,
a clean macOS `python3` or a Windows drive under WSL. This is the plain checklist for those facts of design Part B. Every item is **open with the
owner** until you have run it and recorded the result in design Part B (with an evidence tag `[verified: how; date; Podman and OS; image]`).
Use a second box (`SWARMBOX_NAME=dev`, its own workspace and web port) so the real one is never touched.

## Checklist

| Fact | What to do | Expected |
|---|---|---|
| B6 the whole design on macOS | `brew install podman; podman machine init; podman machine start`, then `swarmbox`, `swarmbox reset`, `swarmbox url`, `swarmbox stop` with the workspace under your home | every command exits 0; a file written in the box shows on the Mac; the web terminal opens. Record each failure with its exact message (an unshared folder is exit 4, "not shared with the Podman machine"). `podman -c dev ps` may fail across the VM: write down what you see |
| B7 host UID other than 1000 | `sudo useradd -m swarmtest`, then as that user start a box and write a file in the workspace | `ls -ln` on the host shows that UID as the owner (a Mac user is 501). Remove the user: `sudo userdel -r swarmtest` |
| B8 lowest Podman | on Podman 4.0, 4.3, 4.9 and the latest: `swarmbox` and `SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py` | 4.3 and newer work; older ones are refused with exit 3 ("4.3 or newer is required"). If 4.0 to 4.2 pass everything, lowering `check_podman_version` is your decision |
| B15 `python3` on a clean macOS | on a Mac without the Command Line Tools (`xcode-select -p` fails) run `swarmbox remote status` | prints that `python3` is missing and exits 3; every other command works |
| B19 macOS `sort -V`, bash 3.2 | `printf '2.0.10\n2.0.9\n' \| sort -V`; `/bin/bash --version` | `2.0.9` comes first; the function and the helper work under bash 3.2 |
| B21 `-e SHELL` through the Podman machine | in zsh: `podman run --rm -e SHELL <image> init` | the printed function has zsh syntax; with `SHELL` unset it prints bash |
| B22 token file mode (macOS, WSL) | `swarmbox remote token` on a Mac and on WSL with the home on a Windows drive | mode 600 accepted; 644 ignored with a warning naming `chmod 600`. On a drive without `metadata` the mode is not kept: the token must not live in a config file there (record it) |
| B23 helper under macOS `/bin/sh` | `/bin/sh $(command -v swarmbox-host) version` style call, then any `swarmbox` command | works (macOS `/bin/sh` is bash 3.2 in POSIX mode) |
| B32 real WSL and Windows drives | on WSL2 with a workspace under `/mnt/c/...` | refused with exit 4; a workspace on the Linux filesystem works |
| B34 macOS `stat` with extended attributes | `stat -f %Lp file` on a file with an xattr | prints the mode (`600`, `644`); the helper reads it correctly |

## Dogfooding your real box

Nothing here was done by the build. v0.1.0 compatibility is not provided (branch `main` keeps v1).

1. **Back up** the workspace while the old container is stopped.
2. Run a second box first, from the 2.0 image, and use it for a few days:

   ```sh
   SWARMBOX_NAME=dev swarmbox config set WORKSPACE ~/code/dev
   SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682
   SWARMBOX_NAME=dev swarmbox
   ```

3. Run `swarmbox remote status` if you use remote access, and the end-to-end Cloudflare checklist of [cloudflare.md](cloudflare.md).

## B20: `swarmbox update` against the real registry (after the first publish)

After the tag `v2.0.0` has produced the package `ghcr.io/feroult/swarmbox-dev` and you have set it public (docs/release-checklist.md). Use a throwaway home:

```sh
export H=$(mktemp -d) && export XDG_CONFIG_HOME=$H/c XDG_DATA_HOME=$H/d XDG_STATE_HOME=$H/s
podman manifest inspect ghcr.io/feroult/swarmbox-dev:2.0.0 | grep -c '"architecture"'     # 2 or more: amd64 and arm64
cosign verify --certificate-identity-regexp '^https://github.com/feroult/swarmbox/.github/workflows/release.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/feroult/swarmbox-dev:2.0.0 >/dev/null && echo SIGNED
podman run --rm -e SHELL ghcr.io/feroult/swarmbox-dev:2.0.0 init --with claude --workspace $H/ws > $H/function.sh
export SWARMBOX_NAME=swarmbox-b20 && . $H/function.sh
swarmbox update            # pulls the 2.0 series, records the exact tag in IMAGE
swarmbox config get IMAGE  # ghcr.io/feroult/swarmbox-dev:2.0.Z
swarmbox update --to 2.0.0
swarmbox reset && swarmbox version
```

Then go offline and run `swarmbox reset` again: it must start from the local tag without a pull. Clean up with the exact names
(`podman rm -f swarmbox-b20; podman volume rm swarmbox-b20-containers; rm -rf "$H"; unset SWARMBOX_NAME XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME`).
The rollback half needs a second published version (`2.0.1`).

## Clean machine: README only

A stranger must be able to install from the README alone. On a machine or fresh user with Podman and nothing else of this project:

1. Copy the install line, read the function it prints, run it with the append (under 2 minutes without the image pull).
2. In a new terminal run `swarmbox` (first call pulls and opens a shell); a second terminal joins the same tmux session.
3. In the box run `claude --version` (first call installs it).
4. `swarmbox url` opens the web terminal in a browser.
5. `swarmbox stop`, then follow the Uninstall section and check `ls ~/.config/swarmbox ~/.local/share/swarmbox` finds nothing.

Every place where you had to leave the README is a README defect.
