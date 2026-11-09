# Removing SwarmBox

## Uninstall

There is no `swarmbox uninstall` command, and the installer never edited a startup file, so there is no rc edit. Do these by hand, in this order:

1. If you set up remote access, run `swarmbox remote off` first (it needs the script): it removes the DNS record, the route and the Access application. Then remove the connector: `podman rm -f swarmbox-cloudflared`.
2. Stop and remove the box: `podman rm -f swarmbox`, and the host connection `podman system connection rm swarmbox` (an error that none exists can be ignored). For a second box give its `SWARMBOX_NAME` instead of `swarmbox`, one box at a time.
3. Delete the script: `rm ~/.local/bin/swarmbox` (or `$SWARMBOX_BIN_DIR/swarmbox` if you set it). If you installed an earlier version that added a `swarmbox` function to
   `~/.bashrc`, `~/.zshrc` or `~/.config/fish/config.fish`, delete that block too: the lines from `# >>> swarmbox X.Y.Z >>>` to `# <<< swarmbox X.Y.Z <<<` and the
   comment line above them. The installer finds such a block when you install again and warns.
4. Remove the support files the installer fetched from the image, and the state: `rm -rf ~/.local/share/swarmbox`, and `rm -rf ~/.local/state/swarmbox` (locks and notices).
5. Remove the host configuration: `rm -rf ~/.config/swarmbox` (the config, `cloudflare.json`, the folders of second boxes; it may hold the tunnel token).
6. Optional: the workspace folder `~/swarmbox` (your projects, logins and tools; back up what you need) and the nested Podman volume, `podman volume rm swarmbox-containers` (`<name>-containers` for a second box).
7. Optional: the image, `podman rmi ghcr.io/<org>/swarmbox:<tag>` (for a local build, `podman rmi localhost/swarmbox:local`).
