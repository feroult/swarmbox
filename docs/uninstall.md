# Removing SwarmBox

## Uninstall

There is no `swarmbox uninstall` command. Do these by hand, in this order (`sed -i.bak` keeps a copy of the file it edits):

1. Remove the function block from your startup file: the one-line comment above it and every line from `# >>> swarmbox 2.0.0 >>>` to `# <<< swarmbox 2.0.0 <<<`. The version in the markers is the one you installed, and a second `init` run leaves a second block. For bash: `sed -i.bak -e '/^# swarmbox [0-9.]*: the shell function printed/d' -e '/^# >>> swarmbox /,/^# <<< swarmbox /d' ~/.bashrc` (use `~/.zshrc` for zsh, `~/.config/fish/config.fish` for fish).
2. Stop and remove the box: `podman rm -f swarmbox-dev`, and the host connection `podman system connection rm swarmbox-dev` (an error that none exists can be ignored). For a second box give its `SWARMBOX_NAME` instead of `swarmbox-dev`, one box at a time.
3. Remove the host helper and its state: `rm -rf ~/.local/share/swarmbox/host`, and `rm -rf ~/.local/state/swarmbox` (locks and notices).
4. Remove the host configuration: `rm -rf ~/.config/swarmbox` (the config, `cloudflare.json`, the folders of second boxes; it may hold the tunnel token).
5. If you set up remote access, run `swarmbox remote off` **before step 1**: it removes the DNS record, the route and the Access application. Then remove the connector: `podman rm -f swarmbox-dev-cloudflared`.
6. Optional: the workspace folder `~/swarmbox` (your projects, logins and tools; back up what you need) and the nested Podman volume, `podman volume rm swarmbox-dev-containers` (`<name>-containers` for a second box).
7. Optional: the image, `podman rmi ghcr.io/<org>/swarmbox-dev:<tag>` (for a local build, `podman rmi localhost/swarmbox-dev:local`).
