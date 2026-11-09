#!/bin/sh
# host-smoke.sh: exercise the real product end to end on the HOST and print one OK/FAIL/SKIP line per step.
#
# Run it on your machine (WSL2, Linux; rootless Podman 4.3 or newer), not inside a box. It never touches your own SwarmBox:
# every container, volume and image it makes is named swarmbox-test-*, the config and state folders are private temp folders
# (XDG_CONFIG_HOME, XDG_STATE_HOME, SWARMBOX_NAME point there), the workspace is a mktemp folder and the web terminal is on a
# random high port of 127.0.0.1. It installs the `swarmbox` script of its own image into a temp folder (SWARMBOX_BIN_DIR) that it puts
# on PATH for this run only, the way a user does, and uses that script for everything. On exit it removes what it created, by exact
# name, and prints the list.
#
#   dev/host-smoke.sh                 build the image, create a throw-away box, check it, remove everything
#   dev/host-smoke.sh --no-cache      build without the layer cache (slow)
#   dev/host-smoke.sh --with-tools    also run `tool install go` (needs the network, slow)
#   dev/host-smoke.sh --keep          do not clean up; print the names so you can look and remove them
#   dev/host-smoke.sh --force         run even when /run/.containerenv or /.dockerenv says this is a container
#   dev/host-smoke.sh --dry-run       print the commands without running Podman
#
# Output: "OK <step> (<n>s)", "FAIL <step>: <reason>", "SKIP <step>: <reason>", then "RESULT: N ok, M fail, K skip".
# Exit status 1 when any step failed. Paste the output back.

set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
say() { printf '%s\n' "$*"; }

NOCACHE= TOOLS=0 KEEP=0 FORCE=0 DRY=0
for a in "$@"; do
  case $a in
    --no-cache) NOCACHE=--no-cache ;;
    --with-tools) TOOLS=1 ;;
    --keep) KEEP=1 ;;
    --force) FORCE=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) say "unknown option: $a (try --help)"; exit 2 ;;
  esac
done

if [ "$FORCE" = 0 ] && { [ -e /run/.containerenv ] || [ -e /.dockerenv ]; }; then
  say "This looks like a container (/run/.containerenv or /.dockerenv exists). Run this on the host, or pass --force."
  exit 2
fi

PREFIX=swarmbox-test-
RND=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
BOX=${PREFIX}box-$RND
VOL=$BOX-containers
IMG=localhost/${PREFIX}img:$RND
PORT=$((20000 + $(od -An -N2 -tu2 /dev/urandom | tr -d ' ') % 30000))
WORK=$(mktemp -d "${TMPDIR:-/tmp}/${PREFIX}host.XXXXXX") || exit 1
WS=$WORK/workspace BINDIR=$WORK/bin
mkdir -p "$WS" "$BINDIR" "$WORK/config" "$WORK/state" || exit 1

# Private paths: the script reads its config under XDG_CONFIG_HOME and keeps locks and the connection under XDG_STATE_HOME; its
# own file and its support files go to SWARMBOX_BIN_DIR and SWARMBOX_TEST_SUPPORT_DIR. HOME and XDG_DATA_HOME stay, because Podman
# keeps its images there. Settings of yours in the environment are dropped.
for v in $(env | sed -n 's/^\(SWARMBOX_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
unset CONTAINER_HOST CONTAINER_CONNECTION
REAL_CONF=${XDG_CONFIG_HOME:-$HOME/.config}/containers
XDG_CONFIG_HOME=$WORK/config XDG_STATE_HOME=$WORK/state SWARMBOX_NAME=$BOX
SWARMBOX_BIN_DIR=$BINDIR SWARMBOX_TEST_SUPPORT_DIR=$WORK/support
export XDG_CONFIG_HOME XDG_STATE_HOME SWARMBOX_NAME SWARMBOX_BIN_DIR SWARMBOX_TEST_SUPPORT_DIR
PATH=$BINDIR:$PATH; export PATH
for f in storage.conf containers.conf registries.conf; do   # Podman settings, read only, so images are still found
  if [ -f "$REAL_CONF/$f" ]; then mkdir -p "$XDG_CONFIG_HOME/containers"; ln -s "$REAL_CONF/$f" "$XDG_CONFIG_HOME/containers/$f"; fi
done

P() { if [ "$DRY" = 1 ]; then say "+ podman $*" >&2; else command podman "$@"; fi; }
SB() { if [ "$DRY" = 1 ]; then say "+ swarmbox $*" >&2; else "$BINDIR/swarmbox" "$@"; fi; }
IN() { P exec "$BOX" "$@"; }                      # a command in the box
fail() { [ "$DRY" = 1 ] || say "$*" >&2; return 1; }
inspect() { P inspect -f "$1" "$BOX"; }

OK=0 BAD=0 SKIP=0 HAVE_IMG=0 HAVE_BOX=0 CLEANED=0 OWN=
ERR=$WORK/err.txt OUTF=$WORK/out.txt

# step NAME COMMAND...: runs the command with its output captured; rc 0 is OK, 77 is SKIP, anything else FAIL (the run goes on).
step() {
  s_name=$1; shift
  if [ "$DRY" = 1 ]; then say "DRY $s_name"; "$@" >/dev/null; return 0; fi
  rm -f "$WORK/info"; s_t0=$(date +%s)
  "$@" >"$OUTF" 2>"$ERR"; s_rc=$?
  s_sec=$(( $(date +%s) - s_t0 ))
  [ -s "$ERR" ] || cp "$OUTF" "$ERR"
  s_why=$(grep -v '^[[:space:]]*$' "$ERR" | tail -n 3 | tr '\n' ' ' | cut -c1-300)
  case $s_rc in
    0) say "OK $s_name (${s_sec}s)$(cat "$WORK/info" 2>/dev/null)"; OK=$((OK + 1)) ;;
    77) say "SKIP $s_name: $s_why"; SKIP=$((SKIP + 1)) ;;
    *) say "FAIL $s_name: ${s_why:-exit $s_rc, no message}"; BAD=$((BAD + 1)) ;;
  esac
}
need_img() { [ "$HAVE_IMG" = 1 ] || { say "no image (the build step failed)" >&2; return 77; }; }
need_box() { [ "$HAVE_BOX" = 1 ] || { say "no box (the up step failed)" >&2; return 77; }; }

# Removal by exact name, and only for what this run created (OWN is set after the "does not exist yet" check).
safe() { case $1 in "$PREFIX"*|localhost/"$PREFIX"*) return 0 ;; esac; say "refusing to remove '$1'" >&2; return 1; }
cleanup() {
  [ "$CLEANED" = 0 ] || return 0
  CLEANED=1
  [ -n "$OWN" ] || { rm -rf "$WORK"; return 0; }
  if [ "$KEEP" = 1 ]; then
    say; say "KEPT (remove them yourself):"
    say "  container $BOX   volume $VOL   image $IMG   web http://127.0.0.1:$PORT/"
    say "  files $WORK (config and state of the throw-away box; use XDG_CONFIG_HOME=$WORK/config XDG_STATE_HOME=$WORK/state SWARMBOX_NAME=$BOX SWARMBOX_TEST_SUPPORT_DIR=$WORK/support $BINDIR/swarmbox ...)"
    say "  remove: podman rm -f -t 0 $BOX; podman volume rm $VOL; podman rmi $IMG; podman system connection rm $BOX"
    return 0
  fi
  [ "$DRY" = 0 ] || { rm -rf "$WORK"; return 0; }
  say; say "CLEANUP (everything this run created):"
  safe "$BOX" && P rm -f -t 0 "$BOX" >/dev/null 2>&1; safe "$BOX" && P system connection rm "$BOX" >/dev/null 2>&1
  safe "$VOL" && P volume rm -f "$VOL" >/dev/null 2>&1
  safe "$IMG" && P rmi "$IMG" >/dev/null 2>&1
  for k in "container $BOX" "volume $VOL" "image $IMG"; do
    if P "${k%% *}" exists "${k#* }" 2>/dev/null; then say "  NOT removed: $k"; else say "  removed: $k"; fi
  done
  P unshare rm -rf "$WORK" >/dev/null 2>&1; rm -rf "$WORK"
  [ ! -e "$WORK" ] && say "  removed: $WORK" || say "  NOT removed: $WORK"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

say "SwarmBox host smoke test. Prefix of everything it creates: $PREFIX"
say "  will create: container $BOX, volume $VOL, image $IMG,"
say "  a Podman connection named $BOX (in a private config), folder $WORK, web port 127.0.0.1:$PORT"
say "  never touched: your own box, its volume, its config in ~/.config/swarmbox, its workspace"
say

if [ "$DRY" = 0 ]; then
  command -v podman >/dev/null 2>&1 || { say "podman not found"; exit 2; }
  for k in "container $BOX" "image $IMG" "volume $VOL"; do
    ! podman "${k%% *}" exists "${k#* }" 2>/dev/null || { say "'${k#* }' already exists; run again"; exit 2; }
  done
fi
OWN=1

s_podman() {
  v=$(P version --format '{{.Client.Version}}') || return 1
  say "podman $v" >&2
  case $v in [0-3].*|4.[0-2].*) fail "Podman $v is older than 4.3" ;; esac || return 1
  [ "$(P info --format '{{.Host.Security.Rootless}}')" = true ] || fail "Podman is not rootless"
}
s_build() {
  t0=$(date +%s)
  # shellcheck disable=SC2086
  P build $NOCACHE -t "$IMG" "$ROOT" >"$WORK/build.log" 2>&1 || { tail -n 8 "$WORK/build.log" >&2; return 1; }
  HAVE_IMG=1
  printf ' [image %s]' "$(P image inspect -f '{{.Size}}' "$IMG" | awk '{ printf "%.0f MB", $1 / 1048576 }')" >"$WORK/info"
}
s_install() {   # the README: the image prints an installer, sh runs it; the script it writes is the one this run uses
  P run --rm "$IMG" install --image "$IMG" >"$WORK/installer.sh" || return 1
  [ "$DRY" = 1 ] && return 0
  head -n 1 "$WORK/installer.sh" | grep -qx '#!/bin/sh' && grep -q "IMAGE='$IMG'" "$WORK/installer.sh" || fail "the printed installer lacks #!/bin/sh or the image"
  sh "$WORK/installer.sh" >"$WORK/install1.out" 2>&1 || { tail -n 5 "$WORK/install1.out" >&2; return 1; }
  [ -x "$BINDIR/swarmbox" ] && [ "$(command -v swarmbox)" = "$BINDIR/swarmbox" ] || fail "swarmbox is not on PATH after the install"
  cp "$BINDIR/swarmbox" "$WORK/swarmbox.first"
  sh "$WORK/installer.sh" >"$WORK/install2.out" 2>&1 || fail "the second install failed"
  cmp -s "$BINDIR/swarmbox" "$WORK/swarmbox.first" || fail "the second install changed the script"
  [ "$(ls -A "$BINDIR")" = swarmbox ] || fail "the install left other files in the bin folder: $(ls -A "$BINDIR")"
  SB config set WORKSPACE "$WS"
}
s_up() {
  SB config set WEB_PORT "$PORT" && SB config set HOSTNAME "$BOX" || return 1
  SB up || return 1
  HAVE_BOX=1
}
s_labels() {
  [ "$(inspect '{{.State.Running}}')" = true ] || fail "not running"
  [ "$(inspect '{{.Name}}')" = "$BOX" ] || fail "name is $(inspect '{{.Name}}')"
  [ "$(inspect '{{index .Config.Labels "swarmbox.managed"}}')" = 2 ] || fail "swarmbox.managed label is not 2"
  [ "$(inspect '{{index .Config.Labels "swarmbox.image"}}')" = "$IMG" ] || fail "swarmbox.image label wrong"
  [ "$(inspect '{{index .Config.Labels "swarmbox.workspace"}}')" = "$WS" ] || fail "swarmbox.workspace label wrong"
}
s_config() {
  SB config set TZ UTC && [ "$(SB config get TZ)" = UTC ] || fail "config get TZ is not UTC"
  SB config get WEB_PORT | grep -qx "$PORT" || fail "config get WEB_PORT is not $PORT"
}
s_env() {
  SB env add SMOKE_TEST_VAR || return 1
  SB env list | grep -qx SMOKE_TEST_VAR || fail "env list lacks SMOKE_TEST_VAR"
  SB env rm SMOKE_TEST_VAR && ! SB env list | grep -qx SMOKE_TEST_VAR || fail "env rm left SMOKE_TEST_VAR"
}
s_pubkey() {
  KEY=$(SB pubkey | grep -o 'ssh-[a-z0-9]* [A-Za-z0-9+/=]*' | head -n 1)
  [ -n "$KEY" ] || fail "no ssh public key in the output of pubkey"
}
s_user() { [ "$(IN id -un):$(IN id -u)" = agent:1000 ] || fail "user is $(IN id -un):$(IN id -u), expected agent:1000"; }
s_home() {
  : >"$WS/host-marker" && [ "$(IN sh -c 'echo $HOME')" = /home/agent ] && IN test -e /home/agent/host-marker || fail "the workspace is not /home/agent"
  IN sh -c 'touch /home/agent/box-marker' && [ -e "$WS/box-marker" ] || fail "a file made in the box is not in the workspace"
}
s_tmux() { IN tmux has-session -t =main || fail "no tmux session main"; }
s_web() {
  n=0
  while [ $n -lt 20 ]; do
    c=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null)
    [ "$c" = 200 ] && return 0
    n=$((n + 1)); sleep 1
  done
  fail "http://127.0.0.1:$PORT/ answered '$c', expected 200"
}
s_git() { IN git --version; }
s_nested() {
  IN podman pull -q docker.io/library/alpine:3.20 >/dev/null 2>"$WORK/pull.err" || { { say "cannot pull alpine:"; tail -n 1 "$WORK/pull.err"; } >&2; return 77; }
  [ "$(IN podman run --rm docker.io/library/alpine:3.20 echo nested-ok)" = nested-ok ] || fail "nested podman run did not print nested-ok"
}
s_tun() { IN test -c /dev/net/tun || fail "/dev/net/tun is missing in the box"; }
s_toollist() { SB tool list; }
s_toolgo() {
  [ "$TOOLS" = 1 ] || { say "needs the network and is slow; use --with-tools" >&2; return 77; }
  SB tool install go && IN sh -lc 'go version' || fail "go is not usable after tool install"
}
s_up2() {
  id1=$(inspect '{{.Id}}'); SB up || return 1
  [ "$(inspect '{{.Id}}')" = "$id1" ] && [ "$(inspect '{{.State.Running}}')" = true ] || fail "a second up changed or stopped the box"
}
s_stop() { SB stop && [ "$(inspect '{{.State.Running}}')" = false ] || fail "the box is still running after stop"; }
s_restart() { SB up && [ "$(inspect '{{.State.Running}}')" = true ] && s_web; }
s_reset() {
  id1=$(inspect '{{.Id}}'); SB reset || return 1
  [ "$(inspect '{{.Id}}')" != "$id1" ] || fail "reset did not make a new container"
  [ -e "$WS/host-marker" ] && [ -e "$WS/box-marker" ] || fail "reset lost workspace files"
  [ "$(SB pubkey | grep -o 'ssh-[a-z0-9]* [A-Za-z0-9+/=]*' | head -n 1)" = "$KEY" ] || fail "the SSH key changed across reset"
}
s_url() {
  u=$(SB url) || return 1
  say "$u" | grep -qx "http://127.0.0.1:$PORT" || fail "no local address in: $u"
  ! say "$u" | grep -q 'https://' || fail "a public address was printed: $u"
}
s_help() {
  h=$(SB help 2>&1)
  for w in up stop reset url config env pubkey tool remote; do say "$h" | grep -q "$w" || fail "help does not list $w"; done
  [ "$(SB --help 2>&1)" = "$h" ] && [ "$(SB -h 2>&1)" = "$h" ] || fail "--help and -h differ from help"
  [ -n "$(SB version)" ] || fail "version printed nothing"
}
s_run() {   # any other word runs in the box: up, then podman exec ... swarmbox-entrypoint attach <command>
  SB echo host-smoke-ok >"$WORK/run.out" 2>&1; rc=$?
  [ $rc = 0 ] && grep -q host-smoke-ok "$WORK/run.out" || fail "swarmbox echo exited $rc: $(tail -n 2 "$WORK/run.out" | tr '\n' ' ')"
  SB sh -c 'exit 7' >/dev/null 2>&1; [ $? = 7 ] || fail "the exit status of the command was not passed on"
}

onimg() { need_img || return 77; "$@"; }
onbox() { need_box || return 77; "$@"; }
step "podman version, rootless" s_podman
step "build image" s_build
step "install script from the image, twice" onimg s_install
step "up creates the box" onimg s_up
for t in "box running, name, labels:s_labels" "config get/set:s_config" "env add/list/rm:s_env" "pubkey prints a key:s_pubkey" \
  "user is agent uid 1000:s_user" "workspace is home:s_home" "tmux session main:s_tmux" "ttyd answers 200:s_web" "git installed:s_git" "swarmbox <command> runs in the box:s_run" \
  "nested podman run:s_nested" "/dev/net/tun:s_tun" "tool list:s_toollist" "tool install go:s_toolgo" "second up is harmless:s_up2" \
  "stop:s_stop" "up again, web answers:s_restart" "reset keeps workspace and key:s_reset" "url local only:s_url" "help lists commands:s_help"; do
  step "${t%:*}" onbox "${t##*:}"
done

say
say "RESULT: $OK ok, $BAD fail, $SKIP skip"
cleanup
[ "$BAD" = 0 ]
