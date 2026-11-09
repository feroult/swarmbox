## What and why

<!-- One logical change. Say what was not checked. -->

## Checklist

- [ ] Tests added or updated and run (`sh tests/run_all.sh`).
- [ ] `docs/design.md` is consistent with the change.
- [ ] A bump of `VERSION` in `container/tools/go/tool.conf` or `container/tools/gcloud/tool.conf` ran
      `sh dev/record-checksums.sh go` (or `gcloud`) so `SHA256_amd64` and `SHA256_arm64` match the new version.
- [ ] Any other pinned version that moved is listed in CONTRIBUTING.md "Bumping pinned versions".
