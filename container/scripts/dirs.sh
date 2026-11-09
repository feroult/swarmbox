#!/bin/sh
# shellcheck disable=SC2034  # the variables are used by the scripts that source this file
# dirs.sh: the one file that defines every SwarmBox path.
# Source it; do not run it:  . /usr/local/lib/swarmbox/dirs.sh
#
# POSIX sh (sh, dash, bash 3.2 and later). Sourcing has no side effects: it sets variables and creates nothing on disk
# (the folders are made by `serve`). Sourcing twice gives the same values; every source recomputes from
# the environment. Safe under `set -eu`.
#
# XDG rule: XDG_CONFIG_HOME, XDG_DATA_HOME and XDG_STATE_HOME are honored, each for its own paths only. Per the XDG Base
# Directory specification, an empty value counts as unset and a relative value is invalid and ignored; the default under
# $HOME applies in both cases. One trailing slash is removed. Paths may contain spaces: always quote the variables.
#
# Variable                 Value (defaults shown)
# SB_CONFIG_DIR            ${XDG_CONFIG_HOME:-$HOME/.config}/swarmbox            you edit (web-terminal.conf, manifests)
# SB_DATA_DIR              ${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox         installed things
# SB_TOOLS_DIR             $SB_DATA_DIR/tools
# SB_SHIMS_DIR             $SB_DATA_DIR/shims
# SB_STATE_DIR             ${XDG_STATE_HOME:-$HOME/.local/state}/swarmbox        logs, health, socket
# SB_LOG_DIR               $SB_STATE_DIR/logs
# SB_HEALTH_FILE           $SB_STATE_DIR/health
# SB_PODMAN_SOCK           $SB_STATE_DIR/podman.sock
# SB_RUN_DIR               /tmp/swarmbox                                          tmpfs, regenerated at every start
#
# Inside the box HOME is the workspace, so these are <workspace>/.config/swarmbox and so on.

_sb_xdg_root() {
    # $1 = value of the XDG variable, $2 = default. Prints the base folder.
    case "$1" in
        /*) _sb_v=$1 ;;
        *) _sb_v=$2 ;;
    esac
    case "$_sb_v" in
        /) ;;
        */) _sb_v=${_sb_v%/} ;;
    esac
    printf '%s' "$_sb_v"
}

_sb_home=${HOME:-}
SB_CONFIG_DIR=$(_sb_xdg_root "${XDG_CONFIG_HOME:-}" "$_sb_home/.config")/swarmbox
SB_DATA_DIR=$(_sb_xdg_root "${XDG_DATA_HOME:-}" "$_sb_home/.local/share")/swarmbox
SB_STATE_DIR=$(_sb_xdg_root "${XDG_STATE_HOME:-}" "$_sb_home/.local/state")/swarmbox
SB_TOOLS_DIR=$SB_DATA_DIR/tools
SB_SHIMS_DIR=$SB_DATA_DIR/shims
SB_LOG_DIR=$SB_STATE_DIR/logs
SB_HEALTH_FILE=$SB_STATE_DIR/health
SB_PODMAN_SOCK=$SB_STATE_DIR/podman.sock
SB_RUN_DIR=/tmp/swarmbox

unset _sb_home _sb_v
unset -f _sb_xdg_root 2>/dev/null || true
