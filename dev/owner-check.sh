#!/bin/sh
# owner-check.sh: the checks of design Part B that need hardware the development box does not have (slice 6.6).
#
# The owner runs this on a Mac, on WSL2, on a Linux host with a UID other than 1000 and on a host with an older Podman, and pastes
# the output back. docs/owner-checks.md says what each line means and what to do about a FAIL. Read-only apart from one mktemp
# folder (removed on exit) and containers whose names start with swarmbox-test- (removed by their exact name, --rm). It never
# touches the real configuration, the real workspace or a box named swarmbox: it refuses to start when SWARMBOX_NAME or --name is
# not swarmbox-test-*.
#
# Usage: sh dev/owner-check.sh [options]
#   --helper PATH        the swarmbox-host to check (default: the installed one under XDG_DATA_HOME, else the one in this repository);
#                        its folder is copied into the mktemp folder, nothing is written to the original
#   --image REF          a plain image for the workspace, uid and tun checks (default docker.io/library/debian:bookworm-slim)
#   --box-image REF      the SwarmBox image, for the SHELL check of B21 (skipped without it; nothing is pulled for it)
#   --workdir-parent DIR where to create the mktemp folder (default $TMPDIR or /tmp); point it at a folder on a Windows drive to
#                        recheck B22 and B34 in a WSL home on /mnt/c, or at a folder under your home when the default is not
#                        shared with the Podman machine
#   --name NAME          prefix of the container names (must start with swarmbox-test-; default swarmbox-test-owner-<pid>-<time>)
#   --no-container       skip every check that starts a container
#   --only IDS           comma-separated check ids or id prefixes (B22 runs B22.token-mode)
#   --list               print the check ids and stop
# Output: one line per check, "PASS <id> <detail>", "FAIL <id> <detail>", "SKIP <id> <reason>", "INFO <topic> <text>", and a last
# line "SUMMARY pass=N fail=N skip=N". Exit status: 0 no FAIL, 1 at least one FAIL, 2 usage error or refusal.
# Environment for tests: SWARMBOX_CHECK_PROC_VERSION (stands for /proc/version), SWARMBOX_CHECK_PYTHON (the program looked up
# instead of python3), SWARMBOX_CHECK_HELPER, SWARMBOX_CHECK_IMAGE, SWARMBOX_CHECK_BOX_IMAGE.
set -u
LC_ALL=C
export LC_ALL

CHECK_IDS='env.info B8.podman-version B6.machine box.workspace-write B7.host-uid box.tun B15.python3 B19.sort-v B21.shell-env B22.token-mode B23.helper-sh B32.wsl-refusal B34.mode-forms'

PASS_N=0
FAIL_N=0
SKIP_N=0

oneline() { printf '%s' "$*" | tr '\n\t' '  ' | cut -c1-300; }
pass() { PASS_N=$((PASS_N + 1)); printf 'PASS %s %s\n' "$1" "$(oneline "$2")"; }
fail() { FAIL_N=$((FAIL_N + 1)); printf 'FAIL %s %s\n' "$1" "$(oneline "$2")"; }
skip() { SKIP_N=$((SKIP_N + 1)); printf 'SKIP %s %s\n' "$1" "$(oneline "$2")"; }
info() { printf 'INFO %s %s\n' "$1" "$(oneline "$2")"; }
usage_error() { printf 'owner-check: %s\n' "$*" >&2; exit 2; }

# ---------------------------------------------------------------- arguments and refusals

HELPER_ARG=${SWARMBOX_CHECK_HELPER:-}
IMAGE=${SWARMBOX_CHECK_IMAGE:-docker.io/library/debian:bookworm-slim}
BOX_IMAGE=${SWARMBOX_CHECK_BOX_IMAGE:-}
PARENT=
NAME=
NO_CONTAINER=0
ONLY=
LIST=0
while [ $# -gt 0 ]; do
    case $1 in
        --helper) [ $# -ge 2 ] || usage_error "--helper needs a path"; HELPER_ARG=$2; shift 2 ;;
        --image) [ $# -ge 2 ] || usage_error "--image needs a reference"; IMAGE=$2; shift 2 ;;
        --box-image) [ $# -ge 2 ] || usage_error "--box-image needs a reference"; BOX_IMAGE=$2; shift 2 ;;
        --workdir-parent) [ $# -ge 2 ] || usage_error "--workdir-parent needs a folder"; PARENT=$2; shift 2 ;;
        --name) [ $# -ge 2 ] || usage_error "--name needs a name"; NAME=$2; shift 2 ;;
        --no-container) NO_CONTAINER=1; shift ;;
        --only) [ $# -ge 2 ] || usage_error "--only needs a list"; ONLY=$2; shift 2 ;;
        --list) LIST=1; shift ;;
        -h|--help) sed -n '/^# owner-check/,/^set -u/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) usage_error "unknown option $1" ;;
    esac
done

if [ "$LIST" = 1 ]; then
    for _id in $CHECK_IDS; do printf '%s\n' "$_id"; done
    exit 0
fi

ONLY_LIST=$(printf '%s' "$ONLY" | tr ',' ' ')
for _w in $ONLY_LIST; do
    _known=0
    for _id in $CHECK_IDS; do
        case $_id in "$_w"|"$_w".*) _known=1 ;; esac
    done
    [ "$_known" = 1 ] || usage_error "unknown check '$_w' (see --list)"
done

# A box named swarmbox (or any real box name) must never be addressed: this script only ever uses swarmbox-test-* names.
if [ -n "${SWARMBOX_NAME:-}" ]; then
    case $SWARMBOX_NAME in
        swarmbox-test-*) ;;
        *) usage_error "SWARMBOX_NAME is '$SWARMBOX_NAME'; refusing to run next to a real box. Run: env -u SWARMBOX_NAME sh $0" ;;
    esac
fi
[ -n "$NAME" ] || NAME="swarmbox-test-owner-$$-$(date +%s)"
case $NAME in
    swarmbox-test-?*) ;;
    *) usage_error "--name '$NAME' must start with swarmbox-test-; refusing to run against a real box" ;;
esac
case $NAME in
    *[!A-Za-z0-9_.-]*) usage_error "--name '$NAME' has characters outside A-Za-z0-9_.-" ;;
esac

wanted() {
    [ -n "$ONLY" ] || return 0
    for _w in $ONLY_LIST; do
        case $1 in "$_w"|"$_w".*) return 0 ;; esac
    done
    return 1
}

# ---------------------------------------------------------------- the one working folder, and cleanup

REAL_HOME=${HOME:-}
REAL_DATA=${XDG_DATA_HOME:-$REAL_HOME/.local/share}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SHELL_REAL=${SHELL:-}
CREATED=
WORK=

# shellcheck disable=SC2317  # called through the EXIT trap
cleanup() {
    for _c in $CREATED; do
        podman rm -f "$_c" > /dev/null 2>&1 || :
    done
    case $WORK in
        */swarmbox-owner-check.*) [ -d "$WORK" ] && rm -rf "$WORK" ;;
    esac
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

[ -z "$PARENT" ] || [ -d "$PARENT" ] || usage_error "--workdir-parent $PARENT is not a folder"
WORK=$(mktemp -d "${PARENT:-${TMPDIR:-/tmp}}/swarmbox-owner-check.XXXXXX") || usage_error "could not create a folder in ${PARENT:-${TMPDIR:-/tmp}}"
WORK=$(cd "$WORK" && pwd -P)
mkdir "$WORK/home" "$WORK/cfg" "$WORK/state" "$WORK/data" "$WORK/ws"

# Nothing of the owner's SwarmBox configuration reaches the helper: the SWARMBOX_* variables are dropped.
for _v in $(env | sed -n 's/^\(SWARMBOX_[A-Za-z0-9_]*\)=.*/\1/p'); do
    case $_v in SWARMBOX_CHECK_*) ;; *) unset "$_v" ;; esac
done

PV=${SWARMBOX_CHECK_PROC_VERSION:-/proc/version}
is_wsl() { [ -r "$PV" ] && grep -qi microsoft "$PV" 2> /dev/null; }
OS=$(uname -s 2> /dev/null || echo unknown)
ARCH=$(uname -m 2> /dev/null || echo unknown)
UID_N=$(id -u)
case $WORK in /mnt/[A-Za-z]/*) ON_WIN=1 ;; *) ON_WIN=0 ;; esac

# The helper under test: copied, so that it writes nothing next to the original; tool-ports may be absent from a repository copy.
if [ -n "$HELPER_ARG" ]; then
    HELPER_SRC=$HELPER_ARG
elif [ -x "$REAL_DATA/swarmbox/host/swarmbox-host" ]; then
    HELPER_SRC=$REAL_DATA/swarmbox/host/swarmbox-host
else
    HELPER_SRC=$SCRIPT_DIR/../container/host/swarmbox-host
fi
HELPER=
if [ -f "$HELPER_SRC" ]; then
    mkdir "$WORK/helper"
    cp -R "$(dirname "$HELPER_SRC")/." "$WORK/helper/" 2> /dev/null
    if [ -f "$WORK/helper/$(basename "$HELPER_SRC")" ]; then
        chmod 755 "$WORK/helper/$(basename "$HELPER_SRC")"
        [ -f "$WORK/helper/tool-ports" ] || : > "$WORK/helper/tool-ports"
        HELPER=$WORK/helper/$(basename "$HELPER_SRC")
    fi
fi

# Runs the helper with every path and name inside the working folder.
helper_env() {
    env HOME="$WORK/home" XDG_CONFIG_HOME="$WORK/cfg" XDG_STATE_HOME="$WORK/state" XDG_DATA_HOME="$WORK/data" \
        SWARMBOX_NAME="$NAME" SWARMBOX_INIT=1 SWARMBOX_TEST_PROC_VERSION="$PV" "$@"
}

mode_ok() { case $1 in [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7]) return 0 ;; esac; return 1; }

# ---------------------------------------------------------------- the checks

check_env() {
    info env "os=$OS arch=$ARCH uid=$UID_N shell=${SHELL_REAL:-unset} wsl=$(is_wsl && echo yes || echo no) workdir=$WORK on-windows-drive=$([ "$ON_WIN" = 1 ] && echo yes || echo no)"
    if command -v podman > /dev/null 2>&1; then
        info env "podman=$(podman --version 2> /dev/null | head -n 1)"
    else
        info env "podman=not found"
    fi
    info env "helper=${HELPER:-none} image=$IMAGE box-image=${BOX_IMAGE:-none}"
    if [ "$OS" = Darwin ] && command -v sw_vers > /dev/null 2>&1; then info env "macos=$(sw_vers -productVersion 2> /dev/null)"; fi
    _sh=$(/bin/sh -c 'echo "${BASH_VERSION:-}"' 2> /dev/null)
    info env "bin-sh=$([ -n "$_sh" ] && echo "bash $_sh" || echo "not bash")"
    return 0
}

check_b6_machine() {
    if [ "$OS" != Darwin ]; then skip B6.machine "not macOS (the Podman machine exists only there)"; return; fi
    command -v podman > /dev/null 2>&1 || { fail B6.machine "podman not found"; return; }
    _l=$(podman machine list --format '{{.Name}} running={{.Running}}' 2> "$WORK/machine.err") || { fail B6.machine "podman machine list failed: $(head -n 1 "$WORK/machine.err")"; return; }
    case $_l in
        *running=true*) pass B6.machine "a Podman machine is running: $_l" ;;
        *) fail B6.machine "no running Podman machine (run: podman machine start): $_l" ;;
    esac
}

# One throwaway container with the creation flags of the box that matter here: keep-id and a bind mount of a folder of the
# working folder. It writes the ids it sees and a file; the host then reads the file and its owner.
WS_DONE=0
WS_RAN=0
WS_IDS_OK=0
WS_OWNER_OK=0
check_workspace_write() {
    [ "$WS_DONE" = 0 ] || return 0
    WS_DONE=1
    if [ "$NO_CONTAINER" = 1 ]; then skip box.workspace-write "--no-container"; return; fi
    command -v podman > /dev/null 2>&1 || { fail box.workspace-write "podman not found"; return; }
    _c="$NAME-ws"
    CREATED="$CREATED $_c"
    if ! podman run --rm --name "$_c" --userns=keep-id:uid=1000,gid=1000 -v "$WORK/ws:/work" "$IMAGE" \
        sh -c 'echo "$(id -u) $(id -g)" > /work/ids && echo ok > /work/probe' > "$WORK/ws.out" 2> "$WORK/ws.err"; then
        fail box.workspace-write "podman run failed: $(grep -v '^$' "$WORK/ws.err" | head -n 2) (on macOS the folder must be under a path the Podman machine shares; see --workdir-parent)"
        return
    fi
    WS_RAN=1
    if [ "$(cat "$WORK/ws/probe" 2> /dev/null)" != ok ]; then
        fail box.workspace-write "the container ran but the file it wrote is not in the host folder (the folder is not shared with the Podman machine?)"
        return
    fi
    [ "$(cat "$WORK/ws/ids" 2> /dev/null)" = "1000 1000" ] && WS_IDS_OK=1
    [ -n "$(find "$WORK/ws/probe" -user "$UID_N" 2> /dev/null)" ] && WS_OWNER_OK=1
    if [ "$WS_IDS_OK" = 1 ] && [ "$WS_OWNER_OK" = 1 ]; then
        pass box.workspace-write "container saw uid/gid $(cat "$WORK/ws/ids"), the file on the host is owned by host uid $UID_N"
    elif [ "$WS_IDS_OK" != 1 ]; then
        fail box.workspace-write "the container saw ids '$(cat "$WORK/ws/ids" 2> /dev/null)', expected '1000 1000'"
    else
        fail box.workspace-write "the file on the host is not owned by host uid $UID_N"
    fi
}

check_b7() {
    if [ "$UID_N" = 1000 ]; then skip B7.host-uid "the host UID is 1000; run this as a user with another UID (docs/owner-checks.md, B7)"; return; fi
    if [ "$NO_CONTAINER" = 1 ]; then skip B7.host-uid "--no-container"; return; fi
    check_workspace_write   # prints its own line once, even when only B7 was asked for
    if [ "$WS_RAN" != 1 ]; then fail B7.host-uid "the container check did not complete (see box.workspace-write)"; return; fi
    if [ "$WS_IDS_OK" = 1 ] && [ "$WS_OWNER_OK" = 1 ]; then
        pass B7.host-uid "host uid $UID_N: keep-id:uid=1000,gid=1000 gave 1000/1000 inside and ownership $UID_N on the host"
    else
        fail B7.host-uid "host uid $UID_N: keep-id mapping or ownership is wrong (see box.workspace-write)"
    fi
}

check_tun() {
    if [ "$NO_CONTAINER" = 1 ]; then skip box.tun "--no-container"; return; fi
    command -v podman > /dev/null 2>&1 || { fail box.tun "podman not found"; return; }
    _c="$NAME-tun"
    CREATED="$CREATED $_c"
    if podman run --rm --name "$_c" --device /dev/net/tun "$IMAGE" sh -c 'test -c /dev/net/tun' > /dev/null 2> "$WORK/tun.err"; then
        pass box.tun "a container with --device /dev/net/tun sees the character device"
    else
        fail box.tun "no /dev/net/tun in a container: $(grep -v '^$' "$WORK/tun.err" | head -n 1) (the nested Podman of the box needs it; on macOS it is the VM's)"
    fi
}

check_b8() {
    command -v podman > /dev/null 2>&1 || { fail B8.podman-version "podman not found"; return; }
    _v=$(podman version --format '{{.Client.Version}}' 2> /dev/null) || _v=
    case $_v in
        [0-9]*.[0-9]*) ;;
        *) fail B8.podman-version "could not read the version ('$_v')"; return ;;
    esac
    _maj=${_v%%.*}
    _min=${_v#*.}
    _min=${_min%%[!0-9]*}
    case $_maj$_min in *[!0-9]*|'') fail B8.podman-version "could not parse the version '$_v'"; return ;; esac
    if [ "$_maj" -lt 4 ] || { [ "$_maj" -eq 4 ] && [ "$_min" -lt 3 ]; }; then
        fail B8.podman-version "Podman $_v is older than 4.3: the helper refuses it (exit 3). To learn whether it would work, follow docs/owner-checks.md B8 and record the result"
    else
        pass B8.podman-version "Podman $_v is at least 4.3, the version the helper's gate accepts; this is one data point for the lowest working version (B8)"
    fi
}

check_b15() {
    _py=${SWARMBOX_CHECK_PYTHON:-python3}
    if ! command -v "$_py" > /dev/null 2>&1; then
        fail B15.python3 "$_py not found: 'swarmbox remote' would exit 3 (every other command is POSIX sh and does not need it)"
        return
    fi
    # On a Mac without the Command Line Tools /usr/bin/python3 is a stub that opens an install dialog when it runs.
    if [ "$OS" = Darwin ] && command -v xcode-select > /dev/null 2>&1 && ! xcode-select -p > /dev/null 2>&1; then
        fail B15.python3 "$_py is only the Command Line Tools stub (xcode-select -p fails); not run, because it would open an install dialog"
        return
    fi
    _pv=$("$_py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2> /dev/null) || _pv=
    if [ -n "$_pv" ]; then
        pass B15.python3 "$_py runs: $_pv at $(command -v "$_py")"
    else
        fail B15.python3 "$_py is on the PATH but did not run"
        return
    fi
    if [ -n "$HELPER" ] && [ -f "$(dirname "$HELPER")/cloudflare-setup.py" ]; then
        _rc=0
        helper_env sh "$HELPER" remote status > /dev/null 2> "$WORK/remote.err" || _rc=$?
        info B15 "swarmbox remote status exit=$_rc (3 would mean python3 or the script is missing): $(head -n 1 "$WORK/remote.err")"
    else
        info B15 "cloudflare-setup.py is not next to the helper copy; swarmbox remote status not run"
    fi
}

check_b19() {
    _want='2.0.0 2.0.9 2.0.10 '
    _bad=
    _detail=
    for _sh in sh /bin/bash zsh; do
        command -v "$_sh" > /dev/null 2>&1 || continue
        _got=$("$_sh" -c "printf '2.0.10\n2.0.9\n2.0.0\n' | sort -V" 2> /dev/null | tr '\n' ' ')
        if [ "$_got" = "$_want" ]; then _detail="$_detail $_sh=ok"; else _detail="$_detail $_sh=WRONG($_got)"; _bad=1; fi
    done
    _b=$(/bin/bash -c 'echo $BASH_VERSION' 2> /dev/null)
    [ -z "$_b" ] || info B19 "/bin/bash is $_b"
    if [ -z "$_bad" ]; then pass B19.sort-v "sort -V orders 2.0.0 2.0.9 2.0.10 in:$_detail"
    else fail B19.sort-v "sort -V gives the wrong order in:$_detail (the function then keeps the helper and prints no update notice)"; fi
}

# Whether the text of `init` in file $2 is the syntax of shell $1.
init_marker() {
    case $1 in
        zsh) grep -q 'emulate -L zsh' "$2" ;;
        fish) grep -q '^function swarmbox' "$2" ;;
        *) grep -q 'local -a sa pe' "$2" && ! grep -q 'emulate -L zsh' "$2" && ! grep -q '^function swarmbox' "$2" ;;
    esac
}

check_b21() {
    if [ "$NO_CONTAINER" = 1 ]; then skip B21.shell-env "--no-container"; return; fi
    if [ -z "$BOX_IMAGE" ]; then skip B21.shell-env "needs the SwarmBox image: pass --box-image REF (nothing is pulled for it)"; return; fi
    command -v podman > /dev/null 2>&1 || { fail B21.shell-env "podman not found"; return; }
    if ! podman image exists "$BOX_IMAGE" > /dev/null 2>&1; then skip B21.shell-env "image $BOX_IMAGE is not in local storage"; return; fi
    _bad=
    _detail=
    _n=0
    for _case in "real:$SHELL_REAL" "dash:/bin/dash" "zsh:/bin/zsh" "fish:/usr/bin/fish" "unset:"; do
        _n=$((_n + 1))
        _label=${_case%%:*}
        _val=${_case#*:}
        _c="$NAME-init-$_n"
        CREATED="$CREATED $_c"
        _rc=0
        if [ "$_label" = unset ]; then
            env -u SHELL podman run --rm --name "$_c" -e SHELL "$BOX_IMAGE" init > "$WORK/init.$_n" 2> "$WORK/init.$_n.err" || _rc=$?
        else
            env SHELL="$_val" podman run --rm --name "$_c" -e SHELL "$BOX_IMAGE" init > "$WORK/init.$_n" 2> "$WORK/init.$_n.err" || _rc=$?
        fi
        if [ "$_rc" != 0 ]; then _detail="$_detail $_label=run-failed"; _bad=1; continue; fi
        case $_label in
            real) _exp=$(basename "${_val:-bash}") ;;
            zsh) _exp=zsh ;;
            fish) _exp=fish ;;
            *) _exp=bash ;;
        esac
        case $_exp in zsh|fish) ;; *) _exp=bash ;; esac
        if init_marker "$_exp" "$WORK/init.$_n"; then _detail="$_detail $_label->$_exp"; else _detail="$_detail $_label=WRONG(expected $_exp)"; _bad=1; fi
    done
    if [ -z "$_bad" ]; then pass B21.shell-env "init printed the syntax of the SHELL it was given:$_detail"
    else fail B21.shell-env "init printed the wrong syntax or failed:$_detail"; fi
}

# The mode as the helper reads it: stat -c %a, then stat -f %Lp, then find -perm (the first form that gives an octal number).
read_mode() {
    _m=$(stat -c %a "$1" 2> /dev/null) || _m=
    mode_ok "$_m" || { _m=$(stat -f %Lp "$1" 2> /dev/null) || _m=; }
    if ! mode_ok "$_m"; then
        _m=
        for _t in 600 640 644 660 664 666 400 440 444 700 750 755 777; do
            if [ -n "$(find "$1" -perm "$_t" -print 2> /dev/null)" ]; then _m=$_t; break; fi
        done
    fi
    mode_ok "$_m" || return 1
    case $_m in 0[0-7][0-7][0-7]) _m=${_m#0} ;; esac
    printf '%s' "$_m"
}

check_b22() {
    [ -n "$HELPER" ] || { fail B22.token-mode "no helper found (pass --helper)"; return; }
    # The helper decides where the file of this box name lives; let it create the file, then add a fake token line to it.
    helper_env sh "$HELPER" config set TZ UTC > /dev/null 2>&1
    _cf=$(find "$WORK/cfg" -type f -name config 2> /dev/null | head -n 1)
    [ -n "$_cf" ] || { fail B22.token-mode "the helper did not create a config file under the working folder"; return; }
    printf 'CLOUDFLARE_TUNNEL_TOKEN=owner-check-not-a-real-token\n' >> "$_cf"
    chmod 600 "$_cf"
    _where=
    [ "$ON_WIN" != 1 ] || _where=" (workdir on a Windows drive)"
    _got=$(read_mode "$_cf") || _got=
    if [ "$_got" != 600 ]; then fail B22.token-mode "after chmod 600 the mode reads '$_got'$_where: this filesystem does not keep modes"; return; fi
    _rc=0
    _val=$(helper_env sh "$HELPER" config get CLOUDFLARE_TUNNEL_TOKEN 2> "$WORK/b22.err") || _rc=$?
    if [ "$_rc" != 0 ] || [ "$_val" != owner-check-not-a-real-token ]; then
        fail B22.token-mode "mode 600: config get exit $_rc '$(head -n 1 "$WORK/b22.err")'$_where; the helper should accept the token"
        return
    fi
    chmod 644 "$_cf"
    _got=$(read_mode "$_cf") || _got=
    if [ "$_got" != 644 ]; then fail B22.token-mode "after chmod 644 the mode reads '$_got'$_where: this filesystem does not keep modes, so the rule cannot be shown"; return; fi
    _rc=0
    _val=$(helper_env sh "$HELPER" config get CLOUDFLARE_TUNNEL_TOKEN 2> "$WORK/b22.err") || _rc=$?
    if [ "$_val" = owner-check-not-a-real-token ] || ! grep -q 'mode is 644' "$WORK/b22.err"; then
        fail B22.token-mode "mode 644: the helper did not ignore the token and name the mode (exit $_rc, stderr '$(head -n 1 "$WORK/b22.err")')$_where"
        return
    fi
    chmod 600 "$_cf"
    pass B22.token-mode "mode 600 accepted; mode 644 ignored with a warning naming 644 and chmod 600$_where"
}

b23_run() {   # b23_run DIR INTERPRETER... -- helper args
    _dir=$1
    shift
    env HOME="$WORK/home" XDG_CONFIG_HOME="$_dir" XDG_STATE_HOME="$WORK/state" SWARMBOX_NAME="$NAME" "$@"
}

check_b23() {
    [ -n "$HELPER" ] || { fail B23.helper-sh "no helper found (pass --helper)"; return; }
    _detail=
    _bad=
    _n=0
    for _i in "/bin/sh" "dash" "bash --posix" "busybox sh"; do
        _prog=${_i%% *}
        case $_prog in /*) [ -x "$_prog" ] || continue ;; *) command -v "$_prog" > /dev/null 2>&1 || continue ;; esac
        _n=$((_n + 1))
        _d="$WORK/b23-$_n"
        mkdir -p "$_d"
        _ok=1
        # shellcheck disable=SC2086
        _r=$(b23_run "$_d" $_i "$HELPER" version 2> /dev/null) || _r=
        case $_r in [0-9]*.[0-9]*.[0-9]*) ;; *) _ok=0 ;; esac
        # shellcheck disable=SC2086
        b23_run "$_d" $_i "$HELPER" config set TZ UTC > /dev/null 2>&1 || _ok=0
        # shellcheck disable=SC2086
        _g=$(b23_run "$_d" $_i "$HELPER" config get TZ 2> /dev/null) || _g=
        [ "$_g" = UTC ] || _ok=0
        # shellcheck disable=SC2086
        b23_run "$_d" $_i "$HELPER" config list 2> /dev/null | grep -q '^TZ=UTC' || _ok=0
        if [ "$_ok" = 1 ]; then _detail="$_detail [$_i]=ok"; else _detail="$_detail [$_i]=FAILED"; _bad=1; fi
    done
    if [ "$_n" = 0 ]; then skip B23.helper-sh "no shell found"; return; fi
    if [ -z "$_bad" ]; then pass B23.helper-sh "version, config set/get/list work under:$_detail"
    else fail B23.helper-sh "the helper failed under:$_detail"; fi
}

check_b32() {
    if ! is_wsl; then skip B32.wsl-refusal "not WSL (/proc/version does not say microsoft)"; return; fi
    [ -n "$HELPER" ] || { fail B32.wsl-refusal "no helper found (pass --helper)"; return; }
    if command -v findmnt > /dev/null 2>&1; then
        info B32 "findmnt -t 9p,drvfs: $(findmnt -n -t 9p,drvfs -o TARGET,FSTYPE 2> /dev/null | head -n 4 | tr '\n' ';')"
    fi
    _rc=0
    helper_env SWARMBOX_WORKSPACE=/mnt/c/swarmbox-owner-check sh "$HELPER" create-flags > /dev/null 2> "$WORK/b32a.err" || _rc=$?
    if [ "$_rc" != 4 ] || ! grep -q 'Windows drive' "$WORK/b32a.err"; then
        fail B32.wsl-refusal "a workspace under /mnt/c was not refused with exit 4 (exit $_rc: $(head -n 1 "$WORK/b32a.err"))"
        return
    fi
    _rc=0
    helper_env SWARMBOX_WORKSPACE="$WORK/ws2" sh "$HELPER" create-flags > /dev/null 2> "$WORK/b32b.err" || _rc=$?
    if [ "$ON_WIN" = 1 ]; then _exp=4; else _exp=0; fi
    if [ "$_rc" != "$_exp" ]; then
        fail B32.wsl-refusal "a workspace in the working folder (on a Windows drive: $([ "$ON_WIN" = 1 ] && echo yes || echo no)) gave exit $_rc, expected $_exp: $(head -n 1 "$WORK/b32b.err")"
        return
    fi
    pass B32.wsl-refusal "/mnt/c/... refused with exit 4; a workspace in the working folder gave exit $_exp"
}

check_b34() {
    _f="$WORK/mode-file"
    _detail=
    _bad=
    : > "$_f"
    for _e in 600 644; do
        chmod "$_e" "$_f"
        _c=$(stat -c %a "$_f" 2> /dev/null) || _c=n/a
        _b=$(stat -f %Lp "$_f" 2> /dev/null) || _b=n/a
        mode_ok "$_c" || _c="n/a"
        mode_ok "$_b" || _b="n/a"
        _fd=n/a
        [ -z "$(find "$_f" -perm "$_e" -print 2> /dev/null)" ] || _fd=$_e
        _r=$(read_mode "$_f") || _r=
        info B34 "file mode $_e: stat -c %a=$_c stat -f %Lp=$_b find -perm=$_fd helper-order=$_r"
        if [ "$_r" = "$_e" ]; then _detail="$_detail $_e=ok"; else _detail="$_detail $_e=WRONG($_r)"; _bad=1; fi
    done
    if [ "$OS" = Darwin ] && command -v xattr > /dev/null 2>&1; then
        chmod 600 "$_f"
        if xattr -w com.swarmbox.owner-check 1 "$_f" 2> /dev/null; then
            _r=$(read_mode "$_f") || _r=
            if [ "$_r" = 600 ]; then _detail="$_detail xattr-600=ok"; else _detail="$_detail xattr-600=WRONG($_r)"; _bad=1; fi
        else
            info B34 "xattr -w failed; the extended attribute case was not run"
        fi
    fi
    if [ -z "$_bad" ]; then pass B34.mode-forms "the helper's order of forms reads the octal mode:$_detail"
    else fail B34.mode-forms "the helper's order of forms reads a wrong mode:$_detail"; fi
}

# ---------------------------------------------------------------- run

wanted env.info && check_env
wanted B8.podman-version && check_b8
wanted B6.machine && check_b6_machine
wanted box.workspace-write && check_workspace_write
wanted B7.host-uid && check_b7
wanted box.tun && check_tun
wanted B15.python3 && check_b15
wanted B19.sort-v && check_b19
wanted B21.shell-env && check_b21
wanted B22.token-mode && check_b22
wanted B23.helper-sh && check_b23
wanted B32.wsl-refusal && check_b32
wanted B34.mode-forms && check_b34

printf 'SUMMARY pass=%s fail=%s skip=%s\n' "$PASS_N" "$FAIL_N" "$SKIP_N"
[ "$FAIL_N" = 0 ] || exit 1
exit 0
