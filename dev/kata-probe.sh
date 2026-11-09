#!/bin/sh
# kata-probe.sh: does a microVM runtime work with rootless Podman on this host,
# and what does it cost compared with the default crun?
#
# Run it on the HOST (not inside the box). It never touches your SwarmBox
# container or image. It uses a throw-away image (alpine) and --rm containers.
#
#   dev/kata-probe.sh                  check KVM, then benchmark every runtime found
#   dev/kata-probe.sh --install-kata   also download Kata into ~/.local/share/kata-probe
#                                      (a user-level folder, nothing under /usr or /opt)
#   RUNS=3 dev/kata-probe.sh           number of repetitions (default 5)
#
# Runtimes tried: crun (baseline), krun (if installed), kata (if found or installed).

set -u

RUNS=${RUNS:-5}
IMAGE=${IMAGE:-docker.io/library/alpine:3.20}
KATA_HOME=${KATA_HOME:-$HOME/.local/share/kata-probe}
WORK=$(mktemp -d "${TMPDIR:-/tmp}/kata-probe.XXXXXX") || exit 1
trap 'rm -rf "$WORK"' EXIT INT TERM

say() { printf '%s\n' "$*"; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.2f", b - a }'; }

install_kata=0
for a in "$@"; do
  case $a in
    --install-kata) install_kata=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) say "unknown option: $a"; exit 2 ;;
  esac
done

say "== 1. Host"
say "kernel : $(uname -r)"
say "podman : $(podman --version 2>&1)"
say "rootless/runtime : $(podman info --format '{{.Host.Security.Rootless}} {{.Host.OCIRuntime.Name}}' 2>&1)"
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
  say "kvm    : access ok"
else
  say "kvm    : NO ACCESS (/dev/kvm missing or your user is not in group kvm). Stopping."
  exit 1
fi

say
say "== 2. Pulling the test image (one time)"
podman pull -q "$IMAGE" >/dev/null 2>&1 || { say "cannot pull $IMAGE"; exit 1; }

# Kata install into a user folder. It only unpacks files; it does not register anything.
kata_runtime=""
if [ "$install_kata" = 1 ]; then
  say
  say "== 3. Installing Kata into $KATA_HOME"
  mkdir -p "$KATA_HOME" || exit 1
  url=$(curl -fsSL https://api.github.com/repos/kata-containers/kata-containers/releases/latest \
    | grep -o 'https://[^"]*kata-static-[^"]*-amd64\.tar\.[a-z]*' | head -n 1)
  if [ -z "$url" ]; then
    say "could not find the Kata static release URL (network or API limit)."
  elif case $url in *.zst) ! command -v zstd >/dev/null 2>&1 ;; *) false ;; esac; then
    say "the Kata archive is .zst and 'zstd' is not installed. Run: sudo apt install zstd"
    say "then run this script again (nothing was downloaded)."
  else
    # The archive is kept in $KATA_HOME so a second run does not download it again.
    pkg="$KATA_HOME/$(basename "$url")"
    if [ ! -s "$pkg" ]; then
      say "downloading: $url"
      curl -fSL "$url" -o "$pkg.part" && mv "$pkg.part" "$pkg"
    fi
    [ -s "$pkg" ] && tar -xf "$pkg" -C "$KATA_HOME" && say "unpacked under $KATA_HOME/opt/kata"
  fi
fi
if [ -x "$KATA_HOME/opt/kata/bin/kata-runtime" ]; then
  kata_runtime="$KATA_HOME/opt/kata/bin/kata-runtime"
elif command -v kata-runtime >/dev/null 2>&1; then
  kata_runtime=$(command -v kata-runtime)
fi

runtimes="crun"
command -v krun >/dev/null 2>&1 && runtimes="$runtimes krun"
[ -n "$kata_runtime" ] && runtimes="$runtimes $kata_runtime"
say
say "runtimes to test: $runtimes"

# One timed run of a command in the container. Prints seconds, or FAIL.
# $1 runtime, rest: extra podman args then image command.
run_timed() {
  rt=$1; shift
  s=$(now)
  if podman run --rm --runtime "$rt" "$@" >"$WORK/out" 2>"$WORK/err"; then
    e=$(now); elapsed "$s" "$e"
  else
    echo FAIL
  fi
}

avg_of() {
  # reads numbers on stdin, prints the mean (or FAIL if any line was FAIL)
  awk '/FAIL/ { f = 1 } !/FAIL/ { s += $1; n++ } END { if (f || n == 0) print "FAIL"; else printf "%.2f", s / n }'
}

bench() {
  rt=$1
  name=$(basename "$rt")
  say
  say "== Runtime: $name"

  t=$(run_timed "$rt" "$IMAGE" true)
  if [ "$t" = FAIL ]; then
    say "does not start with rootless podman. Error:"
    sed 's/^/   /' "$WORK/err" | head -n 8
    return
  fi

  startup=$(i=0; while [ $i -lt "$RUNS" ]; do run_timed "$rt" "$IMAGE" true; i=$((i+1)); done | avg_of)

  cpu=$(i=0; while [ $i -lt 3 ]; do
    run_timed "$rt" "$IMAGE" sh -c 'i=0; while [ $i -lt 2000000 ]; do i=$((i+1)); done'
    i=$((i+1)); done | avg_of)

  mkdir -p "$WORK/mnt-$name"
  small=$(i=0; while [ $i -lt 3 ]; do
    run_timed "$rt" -v "$WORK/mnt-$name:/w:Z" "$IMAGE" sh -c 'i=0; while [ $i -lt 2000 ]; do echo x > /w/f$i; i=$((i+1)); done'
    i=$((i+1)); done | avg_of)

  big=$(i=0; while [ $i -lt 3 ]; do
    run_timed "$rt" -v "$WORK/mnt-$name:/w:Z" "$IMAGE" sh -c 'dd if=/dev/zero of=/w/big bs=1M count=256 conv=fsync 2>/dev/null'
    i=$((i+1)); done | avg_of)

  nested=$(run_timed "$rt" "$IMAGE" sh -c 'test -e /dev/net/tun && echo tun || echo no-tun')

  say "startup (true)               : ${startup}s  (mean of $RUNS)"
  say "cpu loop (2M iterations)     : ${cpu}s"
  say "2000 small files on a mount  : ${small}s"
  say "256 MB write + fsync (mount) : ${big}s"
  say "kernel seen in the box       : $(podman run --rm --runtime "$rt" "$IMAGE" uname -r 2>/dev/null)"
}

for rt in $runtimes; do
  bench "$rt"
done

say
say "== Done. Paste everything above back to Claude."
say "Memory per idle box is not measured here (it needs host-side tools per runtime)."
