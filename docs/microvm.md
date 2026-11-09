# Stronger isolation: what is known about microVMs

SwarmBox is a container. It shares the kernel with your machine (see [the README](../README.md) and the security model in [design.md](design.md)). This page records what the maintainer and
the AI assistant learned about getting a hypervisor boundary instead. Each statement is tagged: **measured** (run on a real machine), **cited** (from a page, not re-checked when this page was
written) or **assumed** (not verified). Nothing here is a supported feature.

## What works today: a virtual machine around the box

**Supported advice (cited, and the reason for the README text).** For untrusted work, run SwarmBox inside a dedicated virtual machine (Multipass, Lima, Hyper-V, or any Linux VM) or on a dedicated machine.
A kernel escape then reaches the VM, not your files.

- On **WSL2**, all distros share one VM kernel (cited, Microsoft's WSL documentation). A second distro does not isolate anything from the first; the boundary is the WSL2 VM versus Windows. Keep the workspace
  on the Linux filesystem, as SwarmBox requires anyway.

## Kata Containers

- **Podman is not a supported engine for Kata 3.2 (cited).** The Kata 3.2 `Limitations` document says Podman is unsupported.
- **No OCI runtime binary (found by the owner and the assistant, with Podman 4.3.1; not re-run for this page).** The Kata release shipped a containerd shim only: there was no `kata-runtime` that Podman
  can call as an OCI runtime (`--runtime`). `dev/kata-probe.sh --install-kata` fetches the static release into a user folder and reports what it finds.
- Conclusion (assumed from the two points above): Kata is not a practical way to harden a Podman-based box today. A newer Kata release may differ; `dev/kata-probe.sh` will say.

## krun (crun with libkrun)

- `krun` is a build of `crun` that starts each container in a microVM through libkrun. It is an OCI runtime that Podman can use (`podman --runtime krun`), which makes it the Podman-compatible microVM option
  (cited, the crun and libkrun projects).
- **Untested for SwarmBox (assumed).** Nobody has run a SwarmBox box, or nested Podman inside it, under `krun`. SwarmBox needs `/dev/net/tun`, an unmasked `/proc`, and a user namespace with `keep-id`;
  whether a microVM runtime accepts them is unknown.
- **To verify:** libkrun's default network model is TSI (transparent socket impersonation), not a virtual NIC, so `/dev/net/tun`, netavark and port publishing may not behave as in a container (assumed);
  and its limit of 16 virtual CPUs (cited, to be re-checked against the installed version).
- Needs `/dev/kvm` for your user.

## Measuring on a host

`dev/kata-probe.sh` runs on the **host** (not in the box). It checks `/dev/kvm`, pulls a small throw-away image, and times each runtime it finds (`crun` as the baseline, `krun`, and Kata if present or installed
with `--install-kata`), `RUNS` times. It never touches a SwarmBox container or image.

Baseline measured by the owner on WSL2 with `crun` (one run, not repeated; a number to compare a microVM runtime against, not a benchmark):

| What | crun on WSL2 |
|---|---|
| container start | 0.38 s |
| a CPU loop | 2.3 s |
| 2000 small files on a mount | 0.4 s |
| 256 MB write with fsync | 0.55 s |

## What would have to be true

A microVM runtime would be worth adopting only if nested Podman works inside it, the web terminal port and the host connection still work, and start-up and file costs stay acceptable on the mounted workspace.
None of this is known. Until it is, the VM-around-the-box advice stands.
