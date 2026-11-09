# Containers inside SwarmBox (nested Podman)

Agents have `sudo` and a full rootless Podman **inside** the box, so they can provision databases, APIs, etc. without any path to
the host's Podman. There is no flag for it: it is always on, and the box is created with what it needs (`/dev/net/tun`, an unmasked `/proc`,
a volume for the storage). `swarmbox up` checks that the host has `/dev/net/tun` and stops with a message when it does not.

```bash
podman run -d --name mongo --network dev -p 27017:27017 mongo:7   # inside SwarmBox
```

- **Reach them from the host**: `swarmbox up` registers a Podman connection named after the box (default `swarmbox-dev`; the
  name is `SWARMBOX_NAME`) and the box starts the Podman API service inside it. From your host shell:
  ```bash
  podman -c swarmbox-dev ps
  podman -c swarmbox-dev logs mongo
  ```
  Linux and WSL2 only: unix sockets do not cross the macOS VM, so no connection is registered on a Mac [unverified: not run on macOS].
  The socket is `<workspace>/.local/state/swarmbox/podman.sock`. A unix socket path holds at most 107 characters; when the workspace
  path makes it longer than 100, the helper connects through a short symlink in `~/.local/state/swarmbox/` instead, and a path that is
  still too long makes `swarmbox up` stop with exit 4.
- **Publish ports to the host in two hops**: declare the port on the host and publish it inside. On the host,
  `swarmbox config set PORTS 27017` and then `swarmbox reset` (a published port is a creation setting, so it needs a new box;
  `swarmbox reset` keeps your workspace and the nested Podman volume). Inside, publish it with `-p 27017:27017`; do not bind it to
  `127.0.0.1` inside, or the outer forwarder cannot reach it. `PORTS` publishes on the host's `127.0.0.1` only; to expose a port on the
  network give the full form (`swarmbox config set PORTS 0.0.0.0:27017:27017`), which prints a warning. `PORTS` takes a comma list.
- **Container-to-container**: create a network (`podman network create dev`) and use the container name as hostname.
- **Storage** lives in a named volume (`<box-name>-containers`, `swarmbox-dev-containers` for the default box), not in the workspace
  (its files are owned by sub-UIDs your user cannot delete). `swarmbox reset` keeps it. To wipe it, remove the box first:
  `podman rm -f swarmbox-dev`, then `podman volume rm swarmbox-dev-containers`.
- **User IDs**: SwarmBox has ~64k user IDs, so an image whose default user has a higher ID (distroless `nonroot` 65532, some `nobody` 65534
  images) can be pulled but not run as that user: run it with `--user root` (inside SwarmBox that is your own user, not host root).
- **Limits**: nested containers share the box's hostname (`utsns=host`). Settings such as `PORTS` only apply when the box is created,
  so use `swarmbox reset` to change them. Running Podman inside a box that is itself inside another container (a third level) needs the
  same `/dev/net/tun` and unmasked `/proc`, which a plain test container does not have; the image's smoke test for the nested container runs
  only in CI [unverified: that job has never run].

[← Back to the README](../README.md)
