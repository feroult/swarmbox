# Containers inside SwarmBox (nested Podman)

Agents have `sudo` and a full rootless Podman **inside** the container, so they can
provision databases, APIs, etc. without any path to the host's Podman. There is no flag
for it: it is always on.

```bash
podman run -d --name mongo --network dev -p 27017:27017 mongo:7   # inside SwarmBox
```

- **Reach them from the host**: `start.sh` registers a Podman connection named after the
  container (default `swarmbox`) and starts the API service inside. From your host shell:
  ```bash
  podman -c swarmbox ps
  podman -c swarmbox logs mongo
  ```
  (Linux/WSL2 only; unix sockets do not cross the macOS VM.)
- **Publish ports to the host in two hops**: declare the port when starting
  (`./start.sh --ports 27017`) and publish it inside (`-p 27017:27017`; do not bind it to
  `127.0.0.1` inside, or the outer forwarder cannot reach it). `--ports` publishes on the
  host's `127.0.0.1` only; to expose a port on the network, give the full form
  (`--ports 0.0.0.0:27017:27017`).
- **Container-to-container**: create a network (`podman network create dev`) and use the
  container name as hostname.
- **Storage** lives in a named volume (`<container-name>-containers`), not in `.work/`
  (its files are owned by sub-UIDs your user cannot delete). To wipe it:
  `podman volume rm swarmbox-containers`.
- **User IDs**: SwarmBox has ~64k user IDs, so an image whose default user has a higher ID
  (distroless `nonroot` 65532, some `nobody` 65534 images) can be pulled but not run as that
  user: run it with `--user root` (inside SwarmBox that is your own user, not host root).
- **Limits**: nested containers share SwarmBox's hostname (`utsns=host`), and `start.sh`
  needs `/dev/net/tun` and an unmasked `/proc` to create the container. Flags such as
  `--ports` only apply when the container is created, so use `--reset` to change them.

[← Back to the README](../README.md)
