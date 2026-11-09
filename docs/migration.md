# Migrating a v0.1.0 workspace to SwarmBox 2.0

This is the checklist for moving an existing v0.1.0 workspace (the `.work/` folder next to the old `start.sh`) to 2.0. The design is in
[design.md](design.md) section 12.4; what each v0.1.0 file becomes is the table there.

**1. Back up first.** The layout migration is one way: an older image looks for `<workspace>/.swarmbox/` and will not find it. The backup is a
copy of the whole workspace, made while the old container is stopped:

```sh
podman stop swarmbox          # the old container; the workspace is not touched
cp -a /path/to/.work /path/to/.work.backup
```

## Try it on a copy first (recommended)

The automated test (`python3 tests/test_migration_e2e.py`) runs this whole sequence on a generated fixture only, so it cannot know what is in
your real workspace. Run the migration once on a copy before you trust it. You need a second box name so the real one is not touched:

```sh
cp -a /path/to/.work /tmp/work-copy
( cd /path/to/.work && find . \( -type f -o -type l \) | sort | xargs -d '\n' sha256sum > /tmp/work.sha256 )   # fingerprint of the original
podman run --rm -e SHELL <image> init --workspace /tmp/work-copy > /tmp/trial-function.sh
SWARMBOX_NAME=trial bash -c '. /tmp/trial-function.sh; swarmbox'      # a throwaway shell; it does not touch your startup file
( cd /path/to/.work && sha256sum -c /tmp/work.sha256 --quiet )        # the original is unchanged
```

The box named `trial` publishes the same ports as your real one: stop the real box first, or give the trial its own with
`SWARMBOX_NAME=trial swarmbox config set PORTS ...` and `WEB_PORT`.

Compare with `.swarmbox/`: `settings.json` is replaced by a real file at `.claude/settings.json`, `web-terminal.conf` moved to
`.config/swarmbox/`, the logs, locks, `ttyd-index.html`, `opencode-local.json` and `podman.sock` are gone, `memory/` stays and keeps `.swarmbox/`.
Anything else in `.swarmbox/` is listed by the box and left alone. Remove the trial box with `podman rm -f trial` and the copy when done.

## The real migration

Keep this order. Make **no `swarmbox` call** between step 2 and step 3: a call before `init` has recorded the workspace creates the config
with the default workspace `~/swarmbox`.

1. Stop and remove the v0.1.0 container. Your files stay, and so does the nested Podman volume `swarmbox-containers` (do not remove it):

   ```sh
   podman rm -f swarmbox
   ```

2. Install 2.0 and record the workspace (an existing `.work/` is used as it is). The output is the shell function; appending it to the startup file installs it. Open a new shell afterwards:

   ```sh
   podman run --rm -e SHELL <image> init --workspace /path/to/.work >> ~/.bashrc    # or ~/.zshrc, or fish
   ```

3. Give the box the settings the old flags carried (the names that were in `--env-keys`, the ports, the browser):

   ```sh
   swarmbox env add GITHUB_TOKEN          # once for every former --env-keys name; also LOCAL_LLM_* if you used it
   swarmbox config set PORTS 3000,8080
   swarmbox config set BROWSER_URL 9222
   ```

4. If remote access was set up, check it with `swarmbox remote status` (the Cloudflare files are read as before).
5. Run `swarmbox`. The first call creates the box, registers the host connection `podman -c swarmbox-dev` at the new socket address (replacing the
   old `<workspace>/.swarmbox/podman.sock` one), and `serve` runs the layout migration. It prints one line about `memory/` (left by the removed
   memory service; delete it when you no longer need it) and nothing else when all goes well. A second start changes nothing.

If something is wrong, restore the backup (`rm -rf` the workspace only after you have checked that the copy is whole) and use the v0.1.0 tag of
the repository (`git checkout v0.1.0`) to run the old version again.

## What was and was not tested

`tests/test_migration.py` (the script on a fixture) and `tests/test_migration_e2e.py` (the whole sequence with the function, the real helper and
a fake Podman) are tagged `[reduced: fixture]`: the fixture is built from what the v0.1.0 scripts write, not from a real workspace, and no real
Podman or box was involved. The run on your real workspace copy is yours (B29 in design Part B stays open for it).
