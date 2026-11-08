# Running SwarmBox against a local registry

This is how the install line, `swarmbox update` and `swarmbox update --to` are tried without the real registry (`ghcr.io/<org>/swarmbox`, which does not exist yet; `<org>` is a placeholder, decision D32). The automated version is `tests/e2e_registry.py`; this page is the same thing by hand.

Everything below is for a throwaway test: the registry listens on `127.0.0.1` only, with plain HTTP, and holds throwaway images.

## 1. Start a registry

```bash
PORT=$((20000 + RANDOM % 20000))                      # never 7681, 8889 or 43323
podman volume create swarmbox-test-registry-data
podman run -d --name swarmbox-test-registry \
  -v swarmbox-test-registry-data:/var/lib/registry \
  -p 127.0.0.1:$PORT:5000 docker.io/library/registry:2
curl -s http://127.0.0.1:$PORT/v2/                    # prints {}
```

Publish on `127.0.0.1`, never on `0.0.0.0`: the registry has no login.

## 2. Tell Podman the registry speaks plain HTTP

Podman insists on HTTPS unless the registry is marked insecure. Use a file and an environment variable, so nothing global changes:

```bash
cat > /tmp/sb-registries.conf <<EOF
[[registry]]
location = "localhost:$PORT"
insecure = true
EOF
export CONTAINERS_REGISTRIES_CONF=/tmp/sb-registries.conf
```

A `registries.conf` in `$XDG_CONFIG_HOME/containers/` is **not** read for this by Podman 4.3.1 (it looks under `$HOME/.config/containers/`); the environment variable is the reliable way (found by the e2e run).

## 3. Publish two versions

The image is built once (`dev/dev-build.sh --tag swarmbox-test-img`, which holds the APT override for a nested build in a scratch copy of the Dockerfile). The versions differ only in `/usr/local/share/swarmbox/host/VERSION`, so a one-line Containerfile makes the second:

```bash
printf 'FROM swarmbox-test-img\nUSER root\nRUN echo 2.0.1 > /usr/local/share/swarmbox/host/VERSION\nUSER agent\n' > /tmp/Containerfile.201
podman build -t swarmbox-test-img-201 -f /tmp/Containerfile.201 /tmp
R=localhost:$PORT/placeholder-org/swarmbox
podman tag swarmbox-test-img $R:2.0.0 && podman tag swarmbox-test-img $R:2.0 && podman push $R:2.0.0 && podman push $R:2.0
podman tag swarmbox-test-img-201 $R:2.0.1 && podman tag swarmbox-test-img-201 $R:2.0 && podman push $R:2.0.1 && podman push $R:2.0   # the moving tag moves
podman rmi $R:2.0 $R:2.0.0 $R:2.0.1                    # forget the local tags, so the next steps really pull
```

## 4. The install line

The line of design 3.1 with the registry replaced. A registry other than `ghcr.io/<org>` needs `--image`, because `init` cannot know where it was pulled from (the function's default image is the real registry's):

```bash
podman run --rm -e SHELL $R:2.0.0 init --with claude --image $R:2.0.0 >> /tmp/sb-rc
. /tmp/sb-rc                       # a throwaway rc file, not ~/.bashrc
```

Use a scratch `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, a scratch workspace (`SWARMBOX_WORKSPACE`) and a box name that starts with `swarmbox-test-` (`SWARMBOX_NAME`), so the owner's real box and files are never touched. Inside another container (the development box) add `SWARMBOX_TEST_NO_NESTED=1`; then the box has no nested Podman and the result is **reduced**. The scratch `XDG_CONFIG_HOME` hides Podman's own configuration: put a `containers/storage.conf` in it that points at the real image store (`graphroot` and `runroot` from `podman info`), and copy `containers.conf`; `tests/e2e_registry.py` does this.

Then `swarmbox`, `swarmbox update`, `swarmbox reset`, `swarmbox update --to 2.0.0` as in design 3.8.

## 5. Take it down

```bash
podman rm -f -t 0 swarmbox-test-registry && podman volume rm swarmbox-test-registry-data
podman rmi $R:2.0.0 $R:2.0.1 $R:2.0 swarmbox-test-img-201     # whatever of these exists
```

Remove the boxes and volumes by their exact names. Never use `prune`, `rm -a` or `rmi -a`.

## What this does not prove

The real registry (`ghcr.io`, TLS, authentication, multi-arch manifests), macOS and arm64, and a nested Podman inside the box (the development box is a container, so the third level is faked with `SWARMBOX_TEST_NO_NESTED=1`). Those are Phase 6 and 7 checks.

Run it: `SWARMBOX_E2E=1 python3 tests/e2e_registry.py` (10 to 20 minutes; set `SWARMBOX_E2E_IMAGE=<tag>` to reuse a built image).

[← Back to the README](../README.md)
