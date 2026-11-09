# Release checklist

What the maintainer must check by hand before the first public release (`v2.0.0`). Nothing here has been done: no push, tag, visibility change, published image or history rewrite.
`sh dev/release-check.sh` is read-only and prints one line per open condition (it also reports the `[OWNER-TODO: ...]` placeholders in `SECURITY.md`, `CODE_OF_CONDUCT.md` and
`THIRD_PARTY_NOTICES.md`). Run it last, on the commit you tag.

## 1. Run it on real machines

Use a second box (`SWARMBOX_NAME=dev`, its own workspace and web port) so a real box is never touched. Record every failure with its exact message.

| Check | What to do | Expected |
|---|---|---|
| A real Linux host | `dev/host-smoke.sh` first (builds the image, makes a throw-away box with its own names, prints OK/FAIL lines; paste them), then `swarmbox`, a second tab, `swarmbox claude`, `swarmbox url`, `reset`, `stop`; `podman run alpine echo ok` inside the box; `podman -c dev ps` on the host | all work; the nested run needs a normal 65536 subuid range |
| macOS (Podman machine) | `brew install podman; podman machine init; podman machine start`, then the same commands with the workspace under your home | each exits 0; a file written in the box shows on the Mac; the web terminal opens. An unshared folder is exit 4. `podman -c` may fail across the VM: write down what you see |
| Host UID other than 1000 | as another user (a Mac user is 501), start a box and write a file | `ls -ln` shows that UID as the owner |
| Lowest Podman | Podman 4.0, 4.3, 4.9 and the latest: `swarmbox` and `SWARMBOX_SMOKE_FULL=1 python3 tests/smoke_image.py` | 4.3 and newer work; older ones are refused with exit 3. If 4.0 to 4.2 pass, lowering the limit in `check_podman_version` is your choice |
| macOS shell details | `printf '2.0.10\n2.0.9\n' \| sort -V` (2.0.9 first); `/bin/bash --version`; `stat -f %Lp` on a file with an xattr; `podman run --rm -e SHELL <image> init` in zsh; `swarmbox remote status` without Command Line Tools | the function and helper work under bash 3.2 and macOS `/bin/sh`; `init` prints zsh syntax; a missing `python3` exits 3 with a message |
| WSL2 | a workspace under `/mnt/c/...`, then one on the Linux filesystem; `swarmbox remote token` with the home on a Windows drive | the first is refused with exit 4; the second works; mode 600 accepted, 644 ignored with a warning |
| Cloudflare end to end | the check list at the end of [cloudflare.md](cloudflare.md), with a real account | the URL asks for an e-mail code, a different e-mail is refused, `remote off` removes everything |
| Clean machine, README only | on a fresh user with only Podman: build and install by the README Quick start; `swarmbox`; a second tab joins; `claude --version` installs it; `swarmbox url`; `swarmbox stop`; the [uninstall](uninstall.md) steps | every place you had to leave the README is a README defect |

## 2. Repository and CI

1. **CI first run.** Push the branch and read the first runs: `gh run list --branch opensource`, `gh run view <id> --log-failed`. Confirm that `ci.yml` parses and runs, that the macOS bash 3.2
   job passes, that the `ubuntu-24.04-arm` runner label is available to the account and the arm64 job passes, and that the image smoke test runs.
2. **Repository visibility.** `gh repo view feroult/swarmbox --json visibility,pushedAt`. It reported `public` on 2026-11-08; whatever was pushed is public, and a rewrite does not un-publish it.
3. **History and identities.** `git log --format='%an <%ae>' | sort | uniq -c` lists `Fernando Ultremare <feroult@gmail.com>`, `Fernando Ultremare <ferout@gmail.com>`, `User Name <user@example.com>` (a placeholder)
   and `fer <fer@ciandt.com>` (an employer address). Decide which may be public. Scan the exact commit with `gitleaks git --no-banner --redact --log-opts=--all .` first. A rewrite (`git filter-repo --mailmap`,
   on a fresh clone) changes every hash and breaks the tag `v0.1.0`. Push only `main`, `opensource` and the tag you intend; never `--all`, `--mirror` or `--tags`.
4. **Contacts and copyright.** Fill the three `[OWNER-TODO: ...]` placeholders (security contact, conduct contact, source-request contact; `grep -n OWNER-TODO SECURITY.md CODE_OF_CONDUCT.md THIRD_PARTY_NOTICES.md`).
   A private vulnerability report link avoids publishing a mailbox. `LICENSE` is the unmodified Apache-2.0 text; add a `Copyright <year> <holder>` line where you want one.

## 3. Name and registries

`sh dev/name-check.sh swarmbox feroult` asks public, unauthenticated indexes. Recorded on 2026-11-08 from the development box (rerun it, results change):

- npm package `swarmbox`: taken (0.17.0, another project, a sandbox for AI agents testing a product in browsers).
- PyPI package `swarmbox`: taken (0.3.0, "Python orchestration for coding agents in local, container, and cloud sandboxes", another author).
- GitHub: 21 public repositories with `swarmbox` in the name.
- Trademark databases (USPTO, EUIPO, WIPO Global Brand Database): **not searched**. Search "swarmbox" in software classes 9 and 42 for your country. This is a name lookup, not legal advice.

Decide: keep the name and accept the overlap (then replace `<org>` with `feroult` everywhere and update the tests that expect it, for example `git grep -l '<org>'`), or rename (a large edit: image path, markers, docs; not prepared).
The default names of the box and the image repository are in `container/host/DEFAULTS`; the development tree ships `swarmbox-dev`, which becomes `swarmbox` for the release. Check the container registries too.

## 4. Security review by a human

[security-review.md](security-review.md) was written by the same AI agent that wrote the host helper. Have a person read `container/host/swarmbox-host`, `container/scripts/swarmbox-init.sh`, `cloudflare-setup.py`
and the update path, and revise the review. Check `THIRD_PARTY_NOTICES.md` and its redistribution questions.

## 5. OpenCode package line

The tool installs one npm package, named in the single variable `PACKAGE` at the top of `container/tools/opencode/install.sh`: `@opencode/cli` 2.x or `opencode-ai` 1.x (both showed as MIT by `npm view`). Pick one and
make `THIRD_PARTY_NOTICES.md` say which.

## 6. Publish

1. Dry run the release workflow by hand from a branch (`gh workflow run release.yml --ref opensource`; nothing is published without a tag) and read the log: the cosign identity, grype on the real image, the arm64 build.
2. Replace `Unreleased` in the `CHANGELOG.md` entry with the date in a commit. `sh dev/release-check.sh` must print `RELEASE CHECK OK` (the `<org>` warning is allowed only if you decided to keep it).
3. Create the tag yourself: `git tag -a v2.0.0 -m 'SwarmBox 2.0.0'`, then `git push origin v2.0.0`, and watch `gh run watch`.
4. The first publish creates the package as private. Set it public once (the repository's Packages, the package, Package settings, Change visibility) and check from a logged-out machine:
   `podman logout ghcr.io; podman pull ghcr.io/feroult/swarmbox-dev:2.0.0`.
5. Check the published image with a throwaway home:

```sh
export H=$(mktemp -d) && export XDG_CONFIG_HOME=$H/c XDG_DATA_HOME=$H/d XDG_STATE_HOME=$H/s
podman manifest inspect ghcr.io/feroult/swarmbox-dev:2.0.0 | grep -c '"architecture"'     # 2 or more
cosign verify --certificate-identity-regexp '^https://github.com/feroult/swarmbox/.github/workflows/release.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/feroult/swarmbox-dev:2.0.0 >/dev/null && echo SIGNED
podman run --rm -e SHELL ghcr.io/feroult/swarmbox-dev:2.0.0 init --with claude --workspace $H/ws > $H/function.sh
export SWARMBOX_NAME=swarmbox-b20 && . $H/function.sh
swarmbox update; swarmbox config get IMAGE        # pulls the 2.0 series, records the exact tag
swarmbox update --to 2.0.0; swarmbox reset && swarmbox version
```

Then go offline and run `swarmbox reset` again: it must start from the local tag without a pull. Clean up by exact names
(`podman rm -f swarmbox-b20; podman volume rm swarmbox-b20-containers; rm -rf "$H"; unset SWARMBOX_NAME XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME`).
The rollback half needs a second published version.
