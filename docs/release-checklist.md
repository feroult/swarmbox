# Release checklist (owner actions before and after the tag v2.0.0)

The build prepared everything below and did none of it: no push, no tag, no visibility change, no image published, no history rewrite. Each item says what to decide and
where to look or which command to run. Run `sh dev/release-check.sh` at the end: it is read-only and fails with a line per open condition (it reports the `[OWNER-TODO: ...]`
placeholders of SECURITY.md, CODE_OF_CONDUCT.md and THIRD_PARTY_NOTICES.md until you fill them in).

## Name check (D25), recorded 2026-11-08

`sh dev/name-check.sh` asks public, unauthenticated indexes (it needs the network; the tests use a fake curl). Result on 2026-11-08, from the development box:

| Source | Result |
|---|---|
| GitHub repository search for `swarmbox` in the name | 21 public repositories (one search answered, a second one was refused with HTTP 403, the unauthenticated rate limit) |
| npm package `swarmbox` | **taken**: version 0.17.0, a different project (a sandbox for AI agents testing a product in browsers), modified 2026-11-07 |
| PyPI package `swarmbox` | **taken**: version 0.3.0, "Python orchestration for coding agents in local, container, and cloud sandboxes", by another author |
| `feroult/swarmbox` on GitHub | exists and the API reports it as **public** (visibility `public`, default branch `main`, last push 2026-11-08) |
| Trademark databases (USPTO, EUIPO, WIPO Global Brand Database) | **not searched** (they need a browser and a judgment about classes; [unverified]) |

This is a name lookup, not a trademark search, and not legal advice. What it shows: the bare name is already used by projects in the same field (agent sandboxes) on npm and PyPI,
so a user who types `npm i swarmbox` or `pip install swarmbox` gets someone else's tool. SwarmBox itself ships no npm or PyPI package, and its image path
`ghcr.io/feroult/swarmbox-dev` is under your account, so nothing collides technically. The risk is confusion and a possible trademark claim, not a build break.
Default taken by the build (decision log `[7.6]`): the name check does **not** pass cleanly, so the `<org>` placeholders in README.md and the design stay (D38 says to keep them until it passes). 

### Name decision

Decide one of: keep `SwarmBox` and accept the overlap (then replace `<org>` with `feroult`); rename (then the image path, the helper names, the function markers and the docs change; a large edit,
not prepared). Where to look: `sh dev/name-check.sh swarmbox feroult`, then the three trademark databases for your country (search "swarmbox" in software classes 9 and 42), and the
two projects above. If you keep the name, replace the placeholder everywhere with one command, check the tree, and run the tests:

```sh
git grep -l '<org>' -- README.md docs CONTRIBUTING.md SECURITY.md CHANGELOG.md container tests dev .github   # the files that name it
git grep -l '<org>' | xargs sed -i 's#<org>#feroult#g'                                                      # owner-run, not run by the build
python3 tests/test_docs_consistency.py && python3 tests/test_release_docs.py                                  # some tests expect <org>; update them with the change
```

[unverified: the replacement was not run; tests/test_docs_consistency.py asserts `<org>` in the README install line and will need the matching edit.]

## The owner actions, in order

### 1. Repository visibility

The repository `feroult/swarmbox` already reports `public` to the unauthenticated GitHub API (2026-11-08). The design and the history audit assumed private until M4. Where to look:
the repository Settings, section Danger Zone, "Change visibility"; or `gh repo view feroult/swarmbox --json visibility,pushedAt`. If it is public already, the history that was pushed
is public (see History below); a rewrite does not un-publish it.

### 2. Copyright holder

Decide the name that holds the copyright (a person or an organization). LICENSE is the unmodified Apache-2.0 text with no copyright line (decision log `[1.1]`), which Apache recommends; the holder
goes in a `Copyright <year> <holder>` line you add to README.md or a NOTICE file if you want one. Where to look: `grep -n -i copyright LICENSE | head -3`, and decision log `[1.1]`.

### 3. Contacts

Three placeholders need a real address or a private advisory link: the security contact in SECURITY.md, the conduct contact in CODE_OF_CONDUCT.md and the source-request contact
in THIRD_PARTY_NOTICES.md. Command: `grep -n 'OWNER-TODO' SECURITY.md CODE_OF_CONDUCT.md THIRD_PARTY_NOTICES.md`. A private vulnerability report link (Settings, Security, "Private vulnerability reporting") avoids publishing a mailbox.

### 4. Author identities

`git log --format='%an <%ae>' | sort | uniq -c` lists four: `Fernando Ultremare <feroult@gmail.com>` (270 commits, the tag tagger), `Fernando Ultremare <ferout@gmail.com>` (6),
`User Name <user@example.com>` (43, a placeholder) and `fer <fer@ciandt.com>` (1, an employer address). Decide whether each may be public. The employer address is the one to think about.
Where to look: docs/history-audit.md, section Identities.

### 5. History: publish whole (the default) or clean

Re-run on 2026-11-08 at HEAD 50debd8: `python3 -I tests/audit_history.py . --json` finds no credential. Its five "secret" hits are the documented test canaries
(`CANARY-...`, `eyJhbGciOiJIUzI1NiJ9.canarytoken-...`) and the README placeholder `your-claude-oauth-token`; the rest are emails, home paths, hosts and IPs of the classes already triaged in
docs/history-audit.md. **Default: publish the history whole** (nothing to rotate; a rewrite changes 320 hashes and breaks the tag `v0.1.0` and every clone), pushing only `main`, `opensource` and the tag `v0.1.0`.
Never `git push --all`, `--mirror` or `--tags`: the local branches `backup/before-author-rewrite`, `origin/memory` and the `refs/original/...` refs must stay local.

Owner-run commands, none of them run by the build; all are [unverified] because no rewrite was ever tried here and `git filter-repo` is not installed on the development box.

Publish whole (no rewrite):

```sh
gitleaks git --no-banner --redact --log-opts=--all . ; python3 -I tests/audit_history.py . --json | head -20   # re-scan the exact commit
git push origin opensource                                    # the branch; add the tag only when you decide: git push origin v0.1.0
git ls-remote --heads --tags origin                           # check that only the intended refs exist
```

Clean the identities first (only if you decided in item 4 that an address must not be public), on a fresh clone, never in this checkout:

```sh
git clone --no-local . ../swarmbox-clean && cd ../swarmbox-clean
printf '%s\n' 'Fernando Ultremare <feroult@gmail.com> <fer@ciandt.com>' 'Fernando Ultremare <feroult@gmail.com> <ferout@gmail.com>' 'Fernando Ultremare <feroult@gmail.com> <user@example.com>' > ../mailmap
git filter-repo --mailmap ../mailmap --refs refs/heads/opensource refs/heads/main      # needs: pip install git-filter-repo
git log --format='%an <%ae>' | sort | uniq -c            # only the intended identity is left
# every hash changed: recreate v0.1.0 on the rewritten commit that has the same tree, and tell anyone who cloned
```

Where the remote already holds the old history (item 1), a rewrite needs a force-push of every ref; GitHub keeps old commits reachable by hash and cached views, so treat any address that was pushed as published.

### 6. Push and the first CI run (closes B30, B31, B28)

Nothing was ever run on GitHub Actions. Push the branch (item 5), then read the first runs of `ci.yml`: `gh run list --branch opensource`, `gh run view <id> --log-failed`. Close, with the evidence tag
`[verified: how; date; Podman and OS; image]` in design Part B: B30 (the macOS bash 3.2 and the whole `ci.yml` parse and run), B31 (the `ubuntu-24.04-arm` label is available to the account; the arm64 job passes),
B28 (the image smoke test runs in CI). Where to look: the Actions tab, and docs/implementation-status.md for the gate rows that say partial.

### 7. Registry visibility

The first publish creates the package `ghcr.io/feroult/swarmbox-dev` as private. After the first run of `release.yml` set it public once: the repository page, Packages, the package, Package settings,
"Change visibility". Check from a machine that is not logged in: `podman logout ghcr.io; podman pull ghcr.io/feroult/swarmbox-dev:2.0.0`.

### 8. Dry run of release.yml, then the tag v2.0.0

The workflow was validated by parsing only (docs/design.md 10.4 lists what stays [unverified]: cosign identity, grype on the real image, the arm64 label). Run it by hand once from a branch (`gh workflow run release.yml --ref opensource`;
nothing is published without a tag), read the log, then create the tag yourself (nothing in this repository ever creates it):

```sh
sh dev/release-check.sh                  # must print RELEASE CHECK OK (the <org> warning is allowed only if you decided to keep it)
git tag -a v2.0.0 -m 'SwarmBox 2.0.0'    # owner-run
git push origin v2.0.0                   # starts release.yml; watch it: gh run watch
```

Replace the `Unreleased` in the CHANGELOG entry with the date in a commit before the tag.

### 9. B20 recheck and the clean machine walkthrough

After the first publish: the commands of docs/owner-checks.md, section "B20: `swarmbox update` against the real registry", then the section "Clean machine: README only". Record the results in design Part B
(B20) and in docs/implementation-status.md.

### 10. Before you announce

Re-run `sh dev/release-check.sh` on the pushed commit, read decision log entries `[7.1]` to `[7.6]`, and look at the open items in docs/implementation-status.md (every row that says partial or blocked).
