# Git history audit (D37)

Audit of the git history of this repository for secrets and personal data, done in Phase 1 (slice 1.5) as decision D37 asks.
The GitHub repository stays private until milestone M4. Phase 7 acts on this report. Nothing was rewritten and nothing was
pushed. Making the repository public is a manual action of the owner; this audit does not do it.

Secret values are never printed here: a credential-shaped value would be shown as its first 4 characters and its length.

## Method

Two independent scans, both read-only, both run on 2026-11-08 on a Debian 12 box:

1. gitleaks, the primary tool, with its default rules: `gitleaks git --no-banner --redact --log-opts=--all -f json .`
   It reads the commit diffs of every commit reachable from any ref.
2. `tests/audit_history.py`, a Python script of this repository (tested by `tests/test_history_audit.py`). It scans every
   added line of `git log --all -p`, every commit message, every annotated tag message, every blob of
   `git rev-list --all --objects` (this covers content that only merge commits bring in) and every file name that ever
   existed. Classes: private keys, AWS, GCP, GitHub, Anthropic, OpenAI and Slack token shapes, JSON web tokens, Cloudflare
   tunnel tokens, high-entropy values next to key, token, secret or password words, sensitive file names (`.env`, key and
   certificate files, credential files), e-mail addresses, home paths, IP addresses and URL host names. It also lists the
   identities (author, committer, tagger).

Each result was then read by a person (the implementer) and triaged below.

## Tool and version

- gitleaks 8.30.1 (linux x64 release binary). It was downloaded from the project's GitHub release into a temporary
  directory, checked against the `checksums.txt` of the same release (sha256 OK) and deleted after the run. It was not
  installed into the repository or the system.
- Fallback script: `tests/audit_history.py`. It was used in addition to gitleaks, not instead: gitleaks does not list
  identities, hosts, home paths or file names, and it skips merge commits.

## Scope

- Repository state scanned: HEAD `8a169403ae8ff8f07c103c884da4add9e777d81e`, branch `opensource`.
- Commits: 227 commits reachable from all refs (`git rev-list --all --count`), 935 objects, 92 distinct paths ever present,
  history from 2025-07-12 to 2026-11-08. gitleaks reported 222 commits scanned: it skips the 5 merge commits (their content
  comes from the parents, and the blob pass of the script covers it).
- Refs (11): `refs/heads/main`, `refs/heads/opensource`, `refs/heads/backup/before-author-rewrite`,
  `refs/remotes/origin/main`, `origin/opensource`, `origin/memory`, `origin/HEAD`, the tag `v0.1.0` (annotated, so the v0.1.0
  tree is covered) and three `refs/original/...` refs left by an earlier history rewrite (filter-branch backup).
- Deleted files are covered: diffs and blobs of every commit are scanned, not only the current tree.
- Not covered: files that were never committed; the GitHub side (pull requests, issues, releases, forks, cached views);
  the commit messages of refs that exist only on the remote and were never fetched.

## Findings

### Credentials

No credential was found. Every automatic hit was a false positive.

| Commit | Path | Class | Tool | Triage | Action |
|--------|------|-------|------|--------|--------|
| 656d95f4 (and 7ed665b2) | tests/test_cloudflare_setup.py:416 | generic-api-key | gitleaks | false positive: the 37-character test fixture `0123...` (a counting sequence, first 4 characters `0123`) feeds a Cloudflare "Global API Key" shape check | none |
| c249978b | README.md | high-entropy near a key word | script | false positive: the documentation placeholder for an OAuth token (starts `your`), a sentence, not a value | none |

Checked and clear: no private key, no AWS, GCP, GitHub, Anthropic, OpenAI or Slack token shape, no Cloudflare tunnel token,
no JSON web token, and no file ever committed with a sensitive name (`.env`, `id_*`, `*.pem`, `*.key`, credentials). File
names that contain "key" or "token" (`ssh-key.sh`, `tmux-browser-keys.conf`, and their tests) are code, not key files.
Because no credential was found, no credential needs to be rotated.

### Personal data and environment details

| Class | What | Where (first commit) | Triage | Action |
|-------|------|----------------------|--------|--------|
| email | `noreply@anthropic.com` (141 commit messages, 1 tag message) | commit trailers, 2659d8ed | public co-author trailer, not personal | none |
| email | `feroult@gmail.com` | tag v0.1.0 tagger line, 9107d8fc | the owner's identity, also the author of most commits | owner decision (see Identities) |
| email | `you@example.com`, `me@example.com`, `two@example.com`, `a@b.co`, `git@github.com` | docs, tests, ssh config | examples and the standard GitHub SSH user | none |
| home-path | `/home/agent`, `/root`, `/home/node`, `/home/claude-user` | Dockerfile, start.sh, docs, spikes | container user names, not a person's home | none |
| home-path | `/home/alice`, `/Users/me`, `/Users/maximilian` | design.md, spike_b5_socket_len.py | illustrative long paths made up for the socket-length spike (`/Users/maximilian.longname/...`), not an owner path | none |
| ip-address | `192.168.1.100`, `1.2.3.4`, `131.0.0.0` | start.sh help text, a test, a browser version string in a Dockerfile path | documentation example, test value, version number | none |
| host | 28 distinct host names (github.com, api.cloudflare.com, claude.ai, ... plus `127.0.0.1`, `host.containers.internal`, `example.com`, `swarmbox.example.com`) | docs, scripts | public documentation and installer URLs; no private or company host name | none |
| name | `Fernando` (README memory example), `feroult` (GitHub account in `ghcr.io/feroult/swarmbox`, the memory service fork URL, D38) | README, docs, Dockerfile | the owner's public GitHub account; D38 already chose to publish under it | none |

## Identities

Authors and committers in the history (counts are author plus committer roles over 227 commits):

| Identity | Count | Notes |
|----------|-------|-------|
| `Fernando Ultremare <feroult@gmail.com>` | 355 | the owner; also the v0.1.0 tagger |
| `User Name <user@example.com>` | 86 | 43 commits made with a placeholder git identity (the cause is not recorded), dated 2025-12-31 to 2026-11-05 |
| `Fernando Ultremare <ferout@gmail.com>` | 12 | 6 commits with a second personal address |
| `fer <fer@ciandt.com>` | 2 | 1 commit, `a73e44a` ("memory"), made with a work (employer) address; it is on main, opensource and origin/memory |

The `refs/original/...` refs and `backup/before-author-rewrite` are leftovers of an earlier author rewrite. They hold the same
identities as main (no extra ones), but they would carry old hashes into a public mirror.

## Recommendation

Verdict for secrets: the history can be published whole. There is nothing to rotate and no reason to rewrite for credentials.

For personal data the call belongs to the owner, because every item below is an identity, not a credential:

1. Recommended default for Phase 7: publish the history whole, but push only the refs that should be public
   (`main` or `opensource` and the tag `v0.1.0`). Never `git push --all`, `--mirror` or `--tags` blindly: the branches
   `backup/before-author-rewrite` and `origin/memory` and the `refs/original/...` refs must stay local (delete them or leave
   them out of the push).
2. Before that, the owner decides whether the employer address `fer@ciandt.com` (1 commit), the second address
   `ferout@gmail.com` (6 commits) and the placeholder identity `User Name <user@example.com>` (43 commits) may be public. If
   not, Phase 7 rewrites authors with `git filter-repo --mailmap` on a fresh clone (all hashes change, the tag `v0.1.0` must
   be recreated, and the owner is told). If yes, no rewrite is needed.
3. Re-run both scans on the exact commit that will be published, because the history keeps growing until M4:
   `gitleaks git --no-banner --redact --log-opts=--all .` and `python3 -I tests/audit_history.py . --json`.
4. Making the repository public stays a manual action of the owner after steps 1 to 3. This audit changed no visibility
   setting.

## Limitations

- Pattern and entropy scanners miss secrets in unknown shapes, split strings and encoded data. The read of the identity and
  host lists is manual and covers only what the script listed.
- The checksum of the gitleaks binary comes from the same release page as the binary, so it detects a corrupt download but not
  a compromised release. [unverified: no signature check was done]
- gitleaks skips merge commits; the script's blob pass covers their content but cannot name the merge commit.
- Binary files are skipped by the script; the path list holds no image, archive, PDF or font file.
- The scan is a snapshot of HEAD `8a169403`; this report is committed after it, so the published HEAD will differ.
- Only the local clone was scanned; the remote may hold refs that were never fetched.
- A later scan will flag two test fixtures as false positives: `tests/test_cloudflare_setup.py` (the counting-sequence key above)
  and `tests/test_history_audit.py` (an `api_key = "%s"` format string whose value is assembled at run time). Both were
  checked after this audit. Phase 7 should allowlist them or expect them.
