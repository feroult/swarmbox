#!/bin/bash
# swarmbox-tool (design 6; installed as /usr/local/bin/swarmbox-tool). Phase 4a grows it in slices. State of this file:
#
#   validate [DIR]  REAL (slice 4a.1): reads the manifests of both levels (or only the folder DIR) and checks the rules of 6.9.
#                   Exit 0 all good, 1 a manifest failed, 64 usage.
#   link --system  REAL (slice 4a.2): shims, index and tool-ports of the image level (see link_level below)
#   link --user     REAL (slice 4a.2): shims and index of the user level, in the workspace dirs of dirs.sh; no tool-ports
#   install NAME [--version X] [--force]  REAL (slice 4a.3): first-use install under the lock (see "install" below)
#   run NAME COMMAND [-- ARGS...]          REAL (slice 4a.3): install when needed, then exec the real program
#   list                                   REAL (slice 4a.3): every tool of both levels and its state
#   update NAME                            REAL for UPDATE=self (runs UPDATE_CMD); a managed tool answers with how to update it, exit 1
#   use NAME VERSION                       REAL (slice 4b.5): switches the active version of a managed tool (see "use, remove, new, doctor")
#   remove NAME [--purge]                  REAL (4b.5): deletes the install of NAME in the workspace (--purge also its user-level manifest)
#   new NAME [--repo | --dir DIR]          REAL (4b.5): writes a skeleton that passes validate (user level by default)
#   doctor [--fix]                         REAL (4b.5): ok / needs reinstall / missing for every tool; --fix reinstalls the ones that need it
#   prepare         REAL (slice 4b.2): runs the prepare.sh of every installed or WITH-declared tool (see "prepare" below)
#   anything else   usage, exit 64
#
# Manifests (6.3) are shell-sourceable KEY=VALUE files. Loading one SOURCES it in a subshell, so it executes arbitrary shell:
# that is why only two levels are ever read, the image (read-only, built from the repository) and the user level (the user's own
# workspace), never a project folder (D18, 6.10). The `install.sh` lint of validate is a lint (design 6.4): it catches mistakes,
# it does not make an installer safe to run.
#
# Test-only variables (decision log [2.5] and [4a.1]; not in the configuration table of design 8): SWARMBOX_TEST_HOST_DIR replaces
# /usr/local/share/swarmbox/host, SWARMBOX_TEST_IMAGE_TOOLS replaces /usr/local/lib/swarmbox/tools, SWARMBOX_TEST_USER_TOOLS
# replaces the user level ($SB_CONFIG_DIR/tools), SWARMBOX_TEST_LIB is the folder with dirs.sh; decision log [4a.2]:
# SWARMBOX_TEST_IMAGE_SHIMS replaces /usr/local/lib/swarmbox/shims (its index is the sibling `index`) and
# SWARMBOX_TEST_USER_SHIMS replaces $SB_SHIMS_DIR (index: sibling `index`); decision log [4a.3]: SWARMBOX_TEST_LOCK replaces the lock
# file /tmp/swarmbox/tools.lock and SWARMBOX_TEST_ARCH forces TOOL_ARCH (amd64 or arm64) instead of reading `uname -m`; decision log
# [4b.5]: SWARMBOX_TEST_NODE_MAJOR (may be empty) and SWARMBOX_TEST_LIBC (glibc or musl) replace the Node major and the libc that
# the fingerprint (6.11) reads from the running image; decision log [4b.6]: SWARMBOX_TEST_IMAGE_STATE replaces /opt/swarmbox/tools. The tools
# folder itself follows dirs.sh (HOME and the XDG variables), so tests move it by moving HOME.

HOST_DIR=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}
IMAGE_TOOLS=${SWARMBOX_TEST_IMAGE_TOOLS:-/usr/local/lib/swarmbox/tools}
IMAGE_SHIMS=${SWARMBOX_TEST_IMAGE_SHIMS:-/usr/local/lib/swarmbox/shims}
# The image-level INSTALLS (design 6.8, 10.2): what `install NAME --image` writes at build (WITH_TOOLS). Not the manifests (IMAGE_TOOLS).
IMAGE_STATE=${SWARMBOX_TEST_IMAGE_STATE:-/opt/swarmbox/tools}
IMAGE_MODE=0
SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
SCHEMA_KNOWN=1
KNOWN_KEYS=(SCHEMA NAME KIND PROVIDES VERSION UPDATE UPDATE_CMD YOLO_FLAGS YOLO_ALIAS MCP_FORMAT MCP_FLAGS PORTS SHA256_amd64 SHA256_arm64)

# user_tools_dir: the user level, <workspace>/.config/swarmbox/tools (from dirs.sh), or the test override.
user_tools_dir() {
    if [ -n "${SWARMBOX_TEST_USER_TOOLS:-}" ]; then
        printf '%s' "$SWARMBOX_TEST_USER_TOOLS"
        return 0
    fi
    local lib
    for lib in "$SB_LIB/dirs.sh" "$(dirname "$0")/dirs.sh"; do
        if [ -r "$lib" ]; then
            # shellcheck disable=SC1090  # chosen at run time
            . "$lib"
            printf '%s' "$SB_CONFIG_DIR/tools"
            return 0
        fi
    done
    return 1
}

WORK=
cleanup() { [ -z "$WORK" ] || rm -rf "$WORK"; }
trap cleanup EXIT

# load_manifest DIR: sources DIR/tool.conf in a subshell (cwd = DIR, the known keys unset first so that the environment cannot
# leak in) and fills the associative array M with the known keys. Unknown keys are ignored. Returns 0 when it sourced, 1 when
# it did not (LOAD_ERR says why). A manifest that calls `exit` or fails to parse counts as not sourced.
declare -A M
LOAD_ERR=
load_manifest() {
    local dir=$1 k v seen_end=0
    M=()
    LOAD_ERR=
    if [ ! -f "$dir/tool.conf" ]; then
        LOAD_ERR="no tool.conf"
        return 1
    fi
    [ -n "$WORK" ] || WORK=$(mktemp -d "${TMPDIR:-/tmp}/swarmbox-tool.XXXXXX") || { LOAD_ERR="cannot create a temporary folder"; return 1; }
    if ! (
        cd "$dir" || exit 98
        unset "${KNOWN_KEYS[@]}"
        # shellcheck disable=SC1091  # the manifest under test
        . ./tool.conf >/dev/null 2>"$WORK/err" </dev/null || exit 97
        for k in "${KNOWN_KEYS[@]}"; do
            printf '%s\0%s\0' "$k" "${!k-}"
        done
        printf 'END\0'
    ) >"$WORK/out" 2>>"$WORK/err"; then
        LOAD_ERR="tool.conf does not source: $(head -n 1 "$WORK/err" | tr -d '\r')"
        [ "$LOAD_ERR" != "tool.conf does not source: " ] || LOAD_ERR="tool.conf does not source (it failed or called exit)"
        return 1
    fi
    while IFS= read -r -d '' k; do
        if [ "$k" = END ]; then
            seen_end=1
            break
        fi
        IFS= read -r -d '' v || break
        M[$k]=$v
    done <"$WORK/out"
    if [ "$seen_end" -ne 1 ]; then
        M=()
        LOAD_ERR="tool.conf does not source (it called exit before the end)"
        return 1
    fi
    return 0
}

# ---- validate (design 6.9) ------------------------------------------------------------------------------------------------

ERRS=()
err() { ERRS+=("$1"); }

# lint_install FILE UPDATE NAME: the static checks of 6.4. A LINT, not a guarantee: full-line comments are skipped, quoting is
# not understood, and a hostile script gets past it. Adds to ERRS.
lint_install() {
    local file=$1 update=$2 name=$3 n=0 line seg rest target verb w words
    local sys_re='^/(usr|etc|opt|var|root|bin|sbin|lib|lib64|srv|home|boot|sys|proc)(/|$)'
    local rc_re='(^|/)\.(bashrc|bash_profile|bash_login|profile|zshrc|zprofile|zshenv|zlogin)$|(^|/)\.config/fish(/|$)'
    # shellcheck disable=SC2016  # a regular expression, not an expansion
    local home_re='^(~|\$HOME|\$\{HOME\})(/|$)'
    local own_re="^(~|\\\$HOME|\\\$\\{HOME\\})/(\\.local/(bin|share/$name|state/$name)|\\.cache/$name)(/|\$)"
    local -a bad=() targets
    while IFS= read -r line || [ -n "$line" ]; do
        n=$((n + 1))
        case "$line" in
            *[![:space:]]*) ;;
            *) continue ;;
        esac
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" =~ (^|[^[:alnum:]_-])(apt-get|apt|sudo)([^[:alnum:]_-]|$) ]]; then
            err "install.sh line $n uses ${BASH_REMATCH[2]} (lint): an installer never uses apt or sudo (6.4)"
        fi
        targets=()
        # redirections: the word after > or >> (not >&N)
        rest=$line
        while [[ "$rest" =~ \>\>?[[:space:]]*([^[:space:]\;\&\|\>\<]+) ]]; do
            targets+=("${BASH_REMATCH[1]}")
            rest=${rest#*"${BASH_REMATCH[0]}"}
        done
        # commands that write: split into simple commands, take the destination words
        seg=${line//&&/;}
        seg=${seg//||/;}
        seg=${seg//|/;}
        seg=${seg//&/;}
        local IFS_SAVE=$IFS
        IFS=';'
        # shellcheck disable=SC2206  # intended word splitting on ;
        local -a segs=($seg)
        IFS=$IFS_SAVE
        for seg in "${segs[@]}"; do
            # shellcheck disable=SC2206
            words=($seg)
            [ "${#words[@]}" -gt 0 ] || continue
            verb=
            for w in "${words[@]}"; do
                case "$w" in
                    [A-Za-z_]*=*) continue ;;
                    *) verb=${w##*/}; break ;;
                esac
            done
            case "$verb" in
                mkdir|touch|chmod|chown|rm|rmdir|tee)
                    for w in "${words[@]:1}"; do
                        case "$w" in -*) ;; *) targets+=("$w") ;; esac
                    done ;;
                cp|mv|ln|install)
                    w=${words[${#words[@]}-1]}
                    case "$w" in -*) ;; *) [ "${#words[@]}" -gt 2 ] && targets+=("$w") ;; esac ;;
            esac
        done
        for target in "${targets[@]}"; do
            target=${target#[\"\']}
            target=${target%[\"\']}
            case "$target" in '&'*|"") continue ;; esac
            if [[ "$target" =~ $sys_re ]] || [[ "$target" =~ $rc_re ]]; then
                bad+=("install.sh line $n writes outside \$TOOL_PREFIX (lint): $target")
            elif [[ "$target" =~ $home_re ]]; then
                if [ "$update" = self ] && [[ "$target" =~ $own_re ]]; then
                    :
                else
                    bad+=("install.sh line $n writes outside \$TOOL_PREFIX (lint): $target")
                fi
            fi
        done
    done <"$file"
    for ((n = 0; n < ${#bad[@]}; n++)); do err "${bad[$n]}"; done
}

# check_manifest DIR LEVEL: with M loaded, appends every problem to ERRS.
check_manifest() {
    local dir=$1 base c update kind version h a
    base=$(basename "$dir")
    local schema=${M[SCHEMA]:-}
    if [ -z "$schema" ]; then
        err "SCHEMA is missing"
        return
    fi
    if [[ ! "$schema" =~ ^[0-9]+$ ]]; then
        err "SCHEMA must be a whole number, found '$schema'"
        return
    fi
    if [ "$schema" -gt "$SCHEMA_KNOWN" ]; then
        err "SCHEMA=$schema is a newer manifest format than this SwarmBox reads ($SCHEMA_KNOWN): update SwarmBox"
        return
    fi
    if [ "$schema" -lt 1 ]; then
        err "SCHEMA must be 1 or more, found '$schema'"
        return
    fi
    if [ -z "${M[NAME]:-}" ]; then
        err "NAME is missing"
    elif [[ ! "${M[NAME]}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        err "NAME '${M[NAME]}' is not a plain lowercase word (letters, digits, - and _)"
    elif [ "${M[NAME]}" != "$base" ]; then
        err "NAME '${M[NAME]}' does not match its folder '$base' (the folder is the install name)"
    fi
    kind=${M[KIND]:-}
    case "$kind" in
        agent|tool) ;;
        "") err "KIND is missing" ;;
        *) err "KIND must be agent or tool, found '$kind'" ;;
    esac
    if [ -z "${M[PROVIDES]:-}" ]; then
        err "PROVIDES is missing"
    else
        for c in ${M[PROVIDES]}; do
            [[ "$c" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || err "PROVIDES entry '$c' is not a plain command name"
        done
    fi
    version=${M[VERSION]:-}
    [ -n "$version" ] || err "VERSION is missing"
    update=${M[UPDATE]:-managed}
    case "$update" in
        managed) ;;
        self)
            [ -z "$version" ] || [ "$version" = latest ] || err "UPDATE=self needs VERSION=latest (6.7), found '$version'"
            [ -n "${M[UPDATE_CMD]:-}" ] || err "UPDATE=self needs a non-empty UPDATE_CMD (6.7)" ;;
        *) err "UPDATE must be managed or self, found '$update'" ;;
    esac
    if [ -n "$version" ]; then
        if [ "$kind" = agent ] && [ "$version" != latest ]; then
            err "KIND=agent must use VERSION=latest (D21), found '$version'"
        elif [ "$kind" = tool ] && [ "$version" = latest ]; then
            err "KIND=tool must have a pinned VERSION (D21): latest is only for agents"
        fi
    fi
    case "${M[MCP_FORMAT]:-}" in
        ""|claude|opencode) ;;
        *) err "MCP_FORMAT must be claude or opencode, found '${M[MCP_FORMAT]}'" ;;
    esac
    for a in amd64 arm64; do
        h=${M[SHA256_$a]:-}
        if [ -n "$h" ] && [[ ! "$h" =~ ^[0-9a-fA-F]{64}$ ]]; then
            err "SHA256_$a is not a 64-digit hexadecimal checksum"
        fi
    done
    [ -z "${M[SHA256_amd64]:-}" ] || [ -n "${M[SHA256_arm64]:-}" ] || err "SHA256_arm64 is missing: SHA256_amd64 is declared and both architectures are required"
    [ -z "${M[SHA256_arm64]:-}" ] || [ -n "${M[SHA256_amd64]:-}" ] || err "SHA256_amd64 is missing: SHA256_arm64 is declared and both architectures are required"
    if [ -f "$dir/install.sh" ] && [ -z "${M[SHA256_amd64]:-}" ] && [ -z "${M[SHA256_arm64]:-}" ] \
        && grep -v '^[[:space:]]*#' "$dir/install.sh" | grep -q 'TOOL_SHA256'; then
        err "install.sh verifies TOOL_SHA256 but the manifest declares no SHA256_amd64 and SHA256_arm64 (record them with dev/record-checksums.sh)"
    fi
    if [ ! -f "$dir/install.sh" ]; then
        err "install.sh is missing"
    elif [ ! -x "$dir/install.sh" ]; then
        err "install.sh is not executable"
    else
        lint_install "$dir/install.sh" "$update" "$base"
    fi
}

# validate_level LEVEL DIR: checks every <DIR>/*/ ; prints one block per manifest; sets TOTAL, FAILED. Fills the associative
# arrays OWNER_<level> (command -> tool) and TOOLS_<level> (tool -> 1) for the cross-level notes.
# shellcheck disable=SC2034  # used through the nameref in validate_level
declare -A OWNER_image OWNER_user TOOLS_image TOOLS_user
TOTAL=0
FAILED=0
NOTES=()
# shellcheck disable=SC2034  # tools is a nameref to TOOLS_<level>, read for the image level
validate_level() {
    local level=$1 root=$2 d name c
    # shellcheck disable=SC2034  # namerefs
    local -n owner=OWNER_$level tools=TOOLS_$level
    [ -d "$root" ] || return 0
    for d in "$root"/*/; do
        [ -d "$d" ] || continue
        d=${d%/}
        name=$(basename "$d")
        TOTAL=$((TOTAL + 1))
        ERRS=()
        if load_manifest "$d"; then
            check_manifest "$d"
            tools["$name"]=1
            for c in ${M[PROVIDES]:-}; do
                if [ -n "${owner[$c]:-}" ] && [ "${owner[$c]}" != "$name" ]; then
                    err "command '$c' is also provided by '${owner[$c]}' at the same level ($level)"
                else
                    owner["$c"]=$name
                fi
            done
            if [ "$level" = user ]; then
                for c in ${M[PROVIDES]:-}; do
                    [ -z "${OWNER_image[$c]:-}" ] || NOTES+=("note: user tool '$name' overrides image tool '${OWNER_image[$c]}' for the command '$c'")
                done
                [ -z "${TOOLS_image[$name]:-}" ] || NOTES+=("note: user tool '$name' overrides the image tool of the same name")
            fi
        else
            err "$LOAD_ERR"
        fi
        if [ "${#ERRS[@]}" -eq 0 ]; then
            printf 'ok    %s/%s  (%s, VERSION=%s, UPDATE=%s)\n' "$level" "$name" "${M[KIND]}" "${M[VERSION]}" "${M[UPDATE]:-managed}"
        else
            FAILED=$((FAILED + 1))
            printf 'FAIL  %s/%s\n' "$level" "$name"
            for c in "${ERRS[@]}"; do printf '      - %s\n' "$c"; done
        fi
    done
}

cmd_validate() {
    [ $# -le 1 ] || usage
    local udir
    if [ $# -eq 1 ]; then
        if [ ! -d "$1" ]; then
            echo "swarmbox-tool validate: $1 is not a folder" >&2
            exit 64
        fi
        validate_level image "$1"
    else
        validate_level image "$IMAGE_TOOLS"
        if udir=$(user_tools_dir); then
            validate_level user "$udir"
        else
            echo "swarmbox-tool validate: cannot find dirs.sh, the user level was not checked" >&2
        fi
    fi
    local i
    for ((i = 0; i < ${#NOTES[@]}; i++)); do echo "${NOTES[$i]}"; done
    echo "swarmbox-tool validate: $TOTAL manifest(s) checked, $FAILED with errors"
    [ "$FAILED" -eq 0 ]
}

# ---- link (design 6.2) ----------------------------------------------------------------------------------------------------
# link_level LEVEL ROOT SHIMS_DIR PORTS_FILE: makes the shims, the index and (PORTS_FILE not empty) tool-ports of one level.
#   shims   <SHIMS_DIR>/<command>, a symlink to $SHIM_PATH, one per PROVIDES entry
#   index   <dirname SHIMS_DIR>/index, one line "command tool", sorted by command (bytewise)
#   ports   PORTS_FILE, one line "tool<TAB>port" per PORTS entry (image level only), sorted by tool then in manifest order
# Everything is decided first and written after: a same-level duplicate command is reported on stderr and the function returns 1
# with nothing written. The write order never leaves a reader without a shim it needs: new links first (each made under a
# temporary name and renamed over, so an existing link is replaced atomically), then the index (temporary file and rename),
# then the stale links. A stale link is a symlink whose target is exactly $SHIM_PATH and whose command is no longer provided;
# anything else in the folder is left alone, and a command name taken by a file that is not such a link is reported and skipped.
SHIM_PATH=/usr/local/bin/swarmbox-shim
link_level() {
    local level=$1 root=$2 shims=$3 ports_file=$4 d name c p schema dup=0 rc=0
    local -A owner=()
    local -a lines=() plines=()
    if [ -d "$root" ]; then
        for d in "$root"/*/; do
            [ -d "$d" ] || continue
            d=${d%/}
            name=$(basename "$d")
            if ! load_manifest "$d"; then
                echo "swarmbox-tool: skipping the $level manifest '$name': $LOAD_ERR" >&2
                continue
            fi
            schema=${M[SCHEMA]:-}
            if [[ ! "$schema" =~ ^[0-9]+$ ]] || [ "$schema" -lt 1 ] || [ "$schema" -gt "$SCHEMA_KNOWN" ]; then
                echo "swarmbox-tool: skipping the $level manifest '$name': SCHEMA '$schema' is not one this SwarmBox reads (run validate)" >&2
                continue
            fi
            for c in ${M[PROVIDES]:-}; do
                if [[ ! "$c" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]; then
                    echo "swarmbox-tool: the $level manifest '$name' lists '$c' in PROVIDES, which is not a plain command name: skipped" >&2
                    continue
                fi
                if [ -n "${owner[$c]:-}" ] && [ "${owner[$c]}" != "$name" ]; then
                    echo "swarmbox-tool: command '$c' is provided by both '${owner[$c]}' and '$name' at the $level level: nothing was linked (fix one manifest)" >&2
                    dup=1
                    continue
                fi
                owner[$c]=$name
            done
            for p in ${M[PORTS]:-}; do
                if [[ "$p" =~ ^[0-9]+$ ]]; then
                    plines+=("$name"$'\t'"$p")
                else
                    echo "swarmbox-tool: the $level manifest '$name' lists '$p' in PORTS, which is not a port number: skipped" >&2
                fi
            done
        done
    fi
    [ "$dup" -eq 0 ] || return 1
    local index tmp
    index=$(dirname "$shims")/index

    if [ -n "$ports_file" ]; then
        mkdir -p "$(dirname "$ports_file")" || { echo "swarmbox-tool: cannot write $ports_file" >&2; return 1; }
        tmp="$ports_file.tmp.$$"
        # shellcheck disable=SC2015  # the || branch is the cleanup, the intent
        { [ "${#plines[@]}" -eq 0 ] || printf '%s\n' "${plines[@]}"; } >"$tmp" && mv -f "$tmp" "$ports_file" \
            || { rm -f "$tmp"; echo "swarmbox-tool: cannot write $ports_file" >&2; return 1; }
    fi
    mkdir -p "$shims" || { echo "swarmbox-tool: cannot create $shims" >&2; return 1; }
    for c in "${!owner[@]}"; do
        if [ -L "$shims/$c" ] && [ "$(readlink "$shims/$c")" = "$SHIM_PATH" ]; then
            :
        elif [ -e "$shims/$c" ] || [ -L "$shims/$c" ]; then
            echo "swarmbox-tool: $shims/$c exists and is not a SwarmBox shim: left alone, '$c' is not linked at the $level level" >&2
            unset 'owner[$c]'
        else
            tmp="$shims/.link.$$.$c"
            if ln -s "$SHIM_PATH" "$tmp" && mv -T "$tmp" "$shims/$c"; then
                :
            else
                rm -f "$tmp"
                echo "swarmbox-tool: cannot create $shims/$c" >&2
                rc=1
            fi
        fi
    done
    lines=()
    for c in "${!owner[@]}"; do lines+=("$c ${owner[$c]}"); done
    mkdir -p "$(dirname "$index")" || return 1
    tmp="$index.tmp.$$"
    # shellcheck disable=SC2015
    { [ "${#lines[@]}" -eq 0 ] || printf '%s\n' "${lines[@]}" | LC_ALL=C sort; } >"$tmp" && mv -f "$tmp" "$index" \
        || { rm -f "$tmp"; echo "swarmbox-tool: cannot write $index" >&2; return 1; }
    local f
    for f in "$shims"/*; do
        [ -L "$f" ] || continue
        c=$(basename "$f")
        [ -z "${owner[$c]:-}" ] || continue
        [ "$(readlink "$f")" = "$SHIM_PATH" ] && rm -f "$f"
    done
    return "$rc"
}

# user_shims_dir: <workspace>/.local/share/swarmbox/shims (from dirs.sh), or the test override.
user_shims_dir() {
    if [ -n "${SWARMBOX_TEST_USER_SHIMS:-}" ]; then
        printf '%s' "$SWARMBOX_TEST_USER_SHIMS"
        return 0
    fi
    local lib
    for lib in "$SB_LIB/dirs.sh" "$(dirname "$0")/dirs.sh"; do
        if [ -r "$lib" ]; then
            # shellcheck disable=SC1090  # chosen at run time
            . "$lib"
            printf '%s' "$SB_SHIMS_DIR"
            return 0
        fi
    done
    return 1
}

# ---- install, run, list, update (design 6.4, 6.5, 6.7, 6.11) ---------------------------------------------------------------
# Layout, under $SB_TOOLS_DIR/<name>/ (decision log [4a.3]):
#   managed   <version>/   the install (TOOL_PREFIX); complete when <version>/.swarmbox-env exists and every PROVIDES command is in bin/
#             current      relative symlink to <version>, moved with an atomic rename and only after a complete install
#   self      self/        SwarmBox's record only (TOOL_PREFIX for the installer); the program lives in ~/.local/bin/<command>
# "Installed" for UPDATE=self means: the record self/.swarmbox-env exists AND the command resolves to an executable that is not the
# shim. A stale record with a deleted binary, or a binary with no record, counts as not installed and is installed again.

LOCK_FILE=${SWARMBOX_TEST_LOCK:-/tmp/swarmbox/tools.lock}
LOCK_WAIT=${SWARMBOX_TEST_LOCK_WAIT:-900}
NAME_RE='^[a-z0-9][a-z0-9_-]*$'
VERSION_RE='^[A-Za-z0-9][A-Za-z0-9._+-]*$'

tools_state_dir() {
    local lib
    for lib in "$SB_LIB/dirs.sh" "$(dirname "$0")/dirs.sh"; do
        if [ -r "$lib" ]; then
            # shellcheck disable=SC1090  # chosen at run time
            . "$lib"
            printf '%s' "$SB_TOOLS_DIR"
            return 0
        fi
    done
    return 1
}

# tool_arch: amd64 or arm64 (uname -m: x86_64 and amd64 are amd64; aarch64 and arm64 are arm64), or the test override.
tool_arch() {
    local m=${SWARMBOX_TEST_ARCH:-}
    [ -n "$m" ] || m=$(uname -m)
    case "$m" in
        x86_64|amd64) printf amd64 ;;
        aarch64|arm64) printf arm64 ;;
        *) return 1 ;;
    esac
}

# find_manifest NAME: sets MDIR to the manifest folder (user level first) and loads M; returns 1 and sets FIND_ERR on failure.
MDIR=
FIND_ERR=
find_manifest() {
    local name=$1 udir lvl dir schema
    MDIR=
    for lvl in user image; do
        if [ "$lvl" = user ]; then
            udir=$(user_tools_dir) || continue
            dir=$udir/$name
        else
            dir=$IMAGE_TOOLS/$name
        fi
        [ -f "$dir/tool.conf" ] || continue
        if ! load_manifest "$dir"; then
            FIND_ERR="the $lvl manifest of '$name' is broken: $LOAD_ERR (run swarmbox-tool validate)"
            return 1
        fi
        schema=${M[SCHEMA]:-}
        if [[ ! "$schema" =~ ^[0-9]+$ ]] || [ "$schema" -lt 1 ] || [ "$schema" -gt "$SCHEMA_KNOWN" ]; then
            FIND_ERR="the $lvl manifest of '$name' has SCHEMA '$schema', which this SwarmBox does not read (update SwarmBox, or run validate)"
            return 1
        fi
        if [ -z "${M[PROVIDES]:-}" ] || [ -z "${M[VERSION]:-}" ]; then
            FIND_ERR="the $lvl manifest of '$name' lacks PROVIDES or VERSION (run swarmbox-tool validate)"
            return 1
        fi
        if [ ! -x "$dir/install.sh" ]; then
            FIND_ERR="the $lvl manifest of '$name' has no executable install.sh (run swarmbox-tool validate)"
            return 1
        fi
        MDIR=$dir
        return 0
    done
    FIND_ERR="no tool named '$name' (swarmbox-tool list shows the tools)"
    return 1
}

# home_at ROOT NAME: the HOME an UPDATE=self installer ran with for the install in ROOT: the workspace home, or for the image state
# the tool's own folder <image state>/<name>/home (the workspace home is a bind mount at run time, so it cannot hold an image install).
home_at() {
    if [ "$1" = "$IMAGE_STATE" ]; then printf '%s' "$IMAGE_STATE/$2/home"; else printf '%s' "$HOME"; fi
}

# real_command_at ROOT NAME COMMAND: prints the path of the real program of the install in ROOT, for the manifest in M. Returns 1 when
# there is none, 2 when it resolves to the shim (a loop if exec'd).
real_command_at() {
    local root=$1 name=$2 cmd=$3 path real
    if [ "${M[UPDATE]:-managed}" = self ]; then
        path=$(home_at "$root" "$name")/.local/bin/$cmd
    else
        path=$root/$name/current/bin/$cmd
    fi
    [ -f "$path" ] && [ -x "$path" ] || return 1
    real=$(realpath -e -- "$path" 2>/dev/null) || return 1
    case $(basename "$real") in swarmbox-shim | swarmbox-shim.sh) return 2 ;; esac   # .sh: the name in the repository
    [ "$real" != "$(realpath -m -- "$SHIM_PATH")" ] || return 2
    printf '%s' "$path"
}

# is_installed_at ROOT NAME [COMMAND]: with COMMAND only that command has to resolve, else every PROVIDES entry.
is_installed_at() {
    local root=$1 name=$2 only=${3:-} c rec
    if [ "${M[UPDATE]:-managed}" = self ]; then
        rec=$root/$name/self/.swarmbox-env
    else
        rec=$root/$name/current/.swarmbox-env
    fi
    [ -f "$rec" ] || return 1
    if [ -n "$only" ]; then
        real_command_at "$root" "$name" "$only" >/dev/null
        return
    fi
    for c in ${M[PROVIDES]}; do
        real_command_at "$root" "$name" "$c" >/dev/null || return 1
    done
}

# root_for NAME: the state folder whose install of NAME is used (design 6.8): in image mode the image state; otherwise the workspace
# install when it is complete, else the image install when that is complete, else the workspace (where an install goes). A broken
# workspace install therefore never shadows a good image one.
root_for() {
    if [ "$IMAGE_MODE" -eq 1 ]; then printf '%s' "$TDIR"; return 0; fi
    if is_installed_at "$TDIR" "$1" || ! is_installed_at "$IMAGE_STATE" "$1"; then printf '%s' "$TDIR"; else printf '%s' "$IMAGE_STATE"; fi
}

real_command() { real_command_at "$(root_for "$1")" "$1" "$2"; }
is_installed() { is_installed_at "$(root_for "$1")" "$1" "${2:-}"; }

# current_node_major, current_libc: the running image's side of the fingerprint (6.11); test overrides in the header.
current_node_major() {
    if [ "${SWARMBOX_TEST_NODE_MAJOR+set}" = set ]; then
        printf '%s' "$SWARMBOX_TEST_NODE_MAJOR"
        return 0
    fi
    node -v 2>/dev/null | sed -n 's/^v\([0-9]*\).*/\1/p' | head -n 1 || true
}
current_libc() {
    if [ -n "${SWARMBOX_TEST_LIBC:-}" ]; then
        printf '%s' "$SWARMBOX_TEST_LIBC"
    elif ldd --version 2>&1 | grep -qi musl; then
        printf musl
    else
        printf glibc
    fi
}

# write_fingerprint FILE ARCH VERSION: the environment record of 6.11.
write_fingerprint() {
    local node libc
    node=$(current_node_major)
    libc=$(current_libc)
    printf 'ARCH=%s\nNODE_MAJOR=%s\nLIBC=%s\nVERSION=%s\n' "$2" "$node" "$libc" "$3" >"$1"
}

# run_installer NAME PREFIX VERSION ARCH: runs install.sh in HOME with the contract variables, its stdout sent to stderr, stdin
# closed, the lock descriptor closed, a private TMPDIR. Returns the installer's status.
run_installer() {
    local name=$1 prefix=$2 version=$3 arch=$4 sha="" t="$WORK/tmp" ihome=""
    mkdir -p "$t"
    sha=${M[SHA256_$arch]:-}
    if [ "$IMAGE_MODE" -eq 1 ]; then
        ihome=$(home_at "$IMAGE_STATE" "$name")
        mkdir -p "$ihome" || return 1
    fi
    (
        cd "${ihome:-$HOME}" || exit 1
        unset TOOL_SHA256
        [ -z "$sha" ] || export TOOL_SHA256=$sha
        export TOOL_PREFIX=$prefix TOOL_VERSION=$version TOOL_ARCH=$arch TMPDIR=$t
        exec env ${ihome:+"HOME=$ihome"} "$MDIR/install.sh"
    ) </dev/null >&2 9>&-
}

# install_locked NAME VERSION FORCE ANNOUNCE: the install itself; the caller holds the lock. Returns 0 on success (also when it was
# already installed), 1 on failure with nothing left behind.
install_locked() {
    local name=$1 version=$2 force=$3 announce=$4 arch update ndir c final tmp status first_new="" probe
    update=${M[UPDATE]:-managed}
    if ! arch=$(tool_arch); then
        echo "swarmbox-tool: this machine's architecture (${SWARMBOX_TEST_ARCH:-$(uname -m)}) is not supported: only amd64 and arm64 (design 6.4)" >&2
        return 1
    fi
    if [ "$update" = self ]; then
        if [ -z "$version" ]; then
            version=${M[VERSION]}
        fi
        if [ "$force" -eq 0 ] && [ "$version" = "${M[VERSION]}" ] && is_installed "$name"; then
            echo "swarmbox-tool: $name is already installed" >&2
            return 0
        fi
    else
        [ -n "$version" ] || version=${M[VERSION]}
        if [ "$force" -eq 0 ] && [ "$(readlink "$TDIR/$name/current" 2>/dev/null)" = "$version" ] && is_installed "$name"; then
            echo "swarmbox-tool: $name is already installed ($version)" >&2
            return 0
        fi
    fi
    ndir=$TDIR/$name
    # the topmost folder this call will create (none when $ndir exists): undo_dirs removes the empty chain down from it
    probe=$ndir
    while [ ! -e "$probe" ]; do
        first_new=$probe
        probe=$(dirname "$probe")
    done
    mkdir -p "$ndir" || { echo "swarmbox-tool: cannot create $ndir" >&2; return 1; }
    # undo: remove what this call created and left empty (a failed install leaves the tree as it was)
    undo_dirs() {
        local d=$ndir
        [ -n "$first_new" ] || return 0
        while rmdir "$d" 2>/dev/null; do
            [ "$d" != "$first_new" ] || break
            d=$(dirname "$d")
        done
    }
    echo "$announce" >&2
    if [ "$update" = self ]; then
        [ "$version" = "${M[VERSION]}" ] || echo "swarmbox-tool: note: $name updates itself, so $version will move on to newer releases unless its updater is turned off (6.7)" >&2
        tmp=$ndir/.staging.$$
        rm -rf "$tmp"
        mkdir -p "$tmp"
        status=0
        run_installer "$name" "$tmp" "$version" "$arch" || status=$?
        if [ "$status" -ne 0 ]; then
            rm -rf "$tmp"
            [ "$IMAGE_MODE" -eq 0 ] || rm -rf "${ndir:?}/home"
            undo_dirs
            echo "swarmbox-tool: the install of $name failed (installer exit $status). Nothing was recorded; the next call retries." >&2
            return 1
        fi
        write_fingerprint "$tmp/.swarmbox-env" "$arch" "$version"
        for c in ${M[PROVIDES]}; do
            status=0
            real_command_at "$TDIR" "$name" "$c" >/dev/null || status=$?
            if [ "$status" -ne 0 ]; then
                rm -rf "$tmp"
                [ "$IMAGE_MODE" -eq 0 ] || rm -rf "${ndir:?}/home"
                undo_dirs
                if [ "$status" -eq 2 ]; then
                    echo "swarmbox-tool: after the install of $name, $(home_at "$TDIR" "$name")/.local/bin/$c resolves to swarmbox-shim: refusing to record it (it would call itself forever)" >&2
                else
                    echo "swarmbox-tool: the installer of $name finished but $(home_at "$TDIR" "$name")/.local/bin/$c is missing or not executable. Nothing was recorded; the next call retries." >&2
                fi
                return 1
            fi
        done
        if [ -e "$ndir/self" ]; then
            mv -T "$ndir/self" "$ndir/.old.$$" && mv -T "$tmp" "$ndir/self"
            rm -rf "$ndir/.old.$$"
        else
            mv -T "$tmp" "$ndir/self"
        fi
        echo "swarmbox-tool: $name installed" >&2
        return 0
    fi
    # managed
    final=$ndir/$version
    local existed=0
    if [ -d "$final" ] && [ "$force" -eq 0 ]; then
        existed=1
        if [ ! -f "$final/.swarmbox-env" ] || ! version_dir_complete "$final"; then
            rm -rf "$final"
            existed=0
        fi
    else
        rm -rf "$final"
    fi
    if [ "$existed" -eq 0 ]; then
        mkdir -p "$final"
        status=0
        run_installer "$name" "$final" "$version" "$arch" || status=$?
        if [ "$status" -ne 0 ]; then
            rm -rf "$final"
            undo_dirs
            echo "swarmbox-tool: the install of $name failed (installer exit $status). Nothing was installed; the next call retries." >&2
            return 1
        fi
        for c in ${M[PROVIDES]}; do
            if [ ! -f "$final/bin/$c" ] || [ ! -x "$final/bin/$c" ]; then
                rm -rf "$final"
                undo_dirs
                echo "swarmbox-tool: the installer of $name finished but bin/$c is missing or not executable. Nothing was installed; the next call retries." >&2
                return 1
            fi
        done
        write_fingerprint "$final/.swarmbox-env" "$arch" "$version"
    fi
    tmp=$ndir/.current.$$
    rm -f "$tmp"
    if ln -s "$version" "$tmp" && mv -T "$tmp" "$ndir/current"; then
        echo "swarmbox-tool: $name $version installed" >&2
        return 0
    fi
    rm -f "$tmp"
    echo "swarmbox-tool: cannot move the current link of $name" >&2
    return 1
}

# version_dir_complete DIR: every PROVIDES command of M is executable in DIR/bin.
version_dir_complete() {
    local c
    for c in ${M[PROVIDES]}; do
        [ -f "$1/bin/$c" ] && [ -x "$1/bin/$c" ] || return 1
    done
}

# take_lock: opens the lock file on descriptor 9 and waits for it. Returns 1 on failure.
take_lock() {
    mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null
    if ! exec 9>>"$LOCK_FILE"; then
        echo "swarmbox-tool: cannot open the lock file $LOCK_FILE" >&2
        return 1
    fi
    if ! flock -n 9; then
        echo "swarmbox-tool: another install is running, waiting for it..." >&2
        if ! flock -w "$LOCK_WAIT" 9; then
            echo "swarmbox-tool: gave up waiting for the install lock $LOCK_FILE after ${LOCK_WAIT}s" >&2
            exec 9>&-
            return 1
        fi
    fi
}
drop_lock() { exec 9>&-; }

# ensure_installed NAME COMMAND ANNOUNCE: the install path shared by run (COMMAND set) and install. Checks without the lock first,
# then again under it (a second shell that waited finds it done). Returns 0 installed, 1 failed.
ensure_installed() {
    local name=$1 cmd=$2 announce=$3 rc=0
    if is_installed "$name" "$cmd"; then return 0; fi
    take_lock || return 1
    if is_installed "$name" "$cmd"; then
        drop_lock
        return 0
    fi
    install_locked "$name" "" 0 "$announce" || rc=1
    drop_lock
    [ "$rc" -ne 0 ] || prepare_after_install "$name"
    return "$rc"
}

check_tool_name() {
    if [[ ! "${1:-}" =~ $NAME_RE ]]; then
        echo "swarmbox-tool: '${1:-}' is not a tool name (lowercase letters, digits, - and _)" >&2
        exit 64
    fi
}

cmd_install() {
    local name version="" force=0
    [ $# -ge 1 ] || usage
    name=$1
    shift
    check_tool_name "$name"
    while [ $# -gt 0 ]; do
        case "$1" in
            --version)
                [ $# -ge 2 ] || usage
                version=$2
                if [[ ! "$version" =~ $VERSION_RE ]]; then
                    echo "swarmbox-tool: '$version' is not a version name" >&2
                    exit 64
                fi
                shift 2 ;;
            --force) force=1; shift ;;
            --image) IMAGE_MODE=1; shift ;;
            *) usage ;;
        esac
    done
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    [ "$IMAGE_MODE" -eq 0 ] || TDIR=$IMAGE_STATE
    find_manifest "$name" || { echo "swarmbox-tool: $FIND_ERR" >&2; exit 1; }
    if [ -n "$version" ] && [ -n "${M[SHA256_amd64]:-}" ] && [ "$version" != "${M[VERSION]:-}" ]; then
        echo "swarmbox-tool: $name is pinned to ${M[VERSION]}: its checksum is recorded for that version only, so no other version can be installed" >&2
        exit 1
    fi
    take_lock || exit 69
    install_locked "$name" "$version" "$force" "Installing $name..." || { drop_lock; exit 69; }
    drop_lock
    # at build (--image) prepare.sh does not run: it renders files in the workspace home, which serve step 7 does at start (4.1)
    [ "$IMAGE_MODE" -eq 1 ] || prepare_after_install "$name"
}

cmd_run() {
    local name cmd real status c found=0 root
    [ $# -ge 2 ] || usage
    name=$1
    cmd=$2
    shift 2
    if [ $# -gt 0 ]; then
        [ "$1" = -- ] || usage
        shift
    fi
    check_tool_name "$name"
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    find_manifest "$name" || { echo "swarmbox-tool: $FIND_ERR" >&2; exit 1; }
    for c in ${M[PROVIDES]}; do [ "$c" != "$cmd" ] || found=1; done
    if [ "$found" -ne 1 ]; then
        echo "swarmbox-tool: '$name' does not provide the command '$cmd'" >&2
        exit 64
    fi
    ensure_installed "$name" "$cmd" "Installing $name (first use)..." || exit 69
    fp_gate "$name" || exit 69
    status=0
    real=$(real_command "$name" "$cmd") || status=$?
    if [ "$status" -ne 0 ]; then
        if [ "$status" -eq 2 ]; then
            echo "swarmbox-tool: '$cmd' of $name resolves to swarmbox-shim: refusing to run it (it would call itself forever)" >&2
        else
            echo "swarmbox-tool: $name is installed but '$cmd' cannot be found" >&2
        fi
        exit 69
    fi
    if [ "${M[UPDATE]:-managed}" != self ]; then
        root=$(root_for "$name")
        export PATH="$root/$name/current/bin:$PATH"
    fi
    cleanup
    WORK=
    exec 9>&-
    exec "$real" "$@"
}

cmd_update() {
    local name real status words
    [ $# -eq 1 ] || usage
    name=$1
    check_tool_name "$name"
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    find_manifest "$name" || { echo "swarmbox-tool: $FIND_ERR" >&2; exit 1; }
    if [ "${M[UPDATE]:-managed}" != self ]; then
        echo "swarmbox-tool: $name is a managed tool: its version comes from the image. After \`swarmbox update\` and \`swarmbox reset\`, run \`swarmbox tool install $name --force\` to get the new one." >&2
        exit 1
    fi
    if ! is_installed "$name"; then
        echo "swarmbox-tool: $name is not installed: nothing to update (swarmbox-tool install $name)" >&2
        exit 1
    fi
    # shellcheck disable=SC2206  # the manifest's own words, split on blanks on purpose
    words=(${M[UPDATE_CMD]})
    if [ "${#words[@]}" -eq 0 ]; then
        echo "swarmbox-tool: $name has an empty UPDATE_CMD" >&2
        exit 1
    fi
    # the first word is resolved to the real program when the tool provides it (never through the shim)
    status=0
    real=$(real_command "$name" "${words[0]}") || status=$?
    [ "$status" -eq 0 ] && words[0]=$real
    echo "swarmbox-tool: running: ${M[UPDATE_CMD]}" >&2
    "${words[@]}" >&2 </dev/null || exit $?
}

cmd_list() {
    [ $# -eq 0 ] || usage
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    local udir lvl root d name state cur seen=" " rows=()
    printf '%-16s %-6s %-8s %-8s %s\n' NAME KIND UPDATE LEVEL STATE
    for lvl in user image; do
        if [ "$lvl" = user ]; then root=$(user_tools_dir) || continue; else root=$IMAGE_TOOLS; fi
        [ -d "$root" ] || continue
        for d in "$root"/*/; do
            [ -d "$d" ] || continue
            d=${d%/}
            name=$(basename "$d")
            case "$seen" in *" $name "*) continue ;; esac   # the user level wins over the image level
            seen="$seen$name "
            if ! load_manifest "$d"; then
                state="manifest broken ($LOAD_ERR)"
                M[KIND]="?"
                M[UPDATE]="?"
            elif [ "${M[UPDATE]:-managed}" = self ]; then
                if is_installed "$name"; then
                    state="installed (self)"
                elif [ -f "$(root_for "$name")/$name/self/.swarmbox-env" ]; then
                    state="needs reinstall (the command is missing)"
                else
                    state="not installed"
                fi
            else
                cur=$(readlink "$(root_for "$name")/$name/current" 2>/dev/null || true)
                if [ -z "$cur" ]; then
                    state="not installed"
                elif is_installed "$name"; then
                    state="installed ($cur)"
                else
                    state="needs reinstall ($cur is incomplete)"
                fi
            fi
            rows+=("$(printf '%-16s %-6s %-8s %-8s %s' "$name" "${M[KIND]:-?}" "${M[UPDATE]:-managed}" "$lvl" "$state")")
        done
    done
    [ "${#rows[@]}" -eq 0 ] || printf '%s\n' "${rows[@]}" | LC_ALL=C sort
}

# ---- prepare (design 6.3, 4.1 step 7) ----------------------------------------------------------------------------------------
# prepare_tool NAME: runs <manifest dir>/prepare.sh of NAME when it has one (find_manifest has set MDIR). Run with bash (no
# executable bit needed), in $HOME, stdin closed, stdout sent to stderr (stdout belongs to the caller), under `timeout`
# (SWARMBOX_PREPARE_TIMEOUT seconds, default 60; a hang is a failure, never a stop). Exports SWARMBOX_TOOL_NAME and
# SWARMBOX_TOOL_DIR. A failure prints ONE line on stderr, "prepare-failed: <name>: <reason>", which `serve` turns into one health
# line (4.1 step 7), and returns 1. No prepare.sh: returns 0 and prints nothing.
PREPARE_TIMEOUT=${SWARMBOX_PREPARE_TIMEOUT:-60}
prepare_tool() {
    local name=$1 dir=$MDIR status=0
    [ -f "$dir/prepare.sh" ] || return 0
    (
        cd "$HOME" || exit 1
        export SWARMBOX_TOOL_NAME=$name SWARMBOX_TOOL_DIR=$dir
        exec timeout -k 2 "$PREPARE_TIMEOUT" bash "$dir/prepare.sh"
    ) </dev/null >&2 9>&- || status=$?
    [ "$status" -eq 0 ] && return 0
    if [ "$status" -eq 124 ]; then
        echo "prepare-failed: $name: prepare.sh timed out after ${PREPARE_TIMEOUT}s" >&2
    else
        echo "prepare-failed: $name: prepare.sh failed (exit $status)" >&2
    fi
    return 1
}

# declared_with NAME: true when NAME is in SWARMBOX_WITH (separated by commas or blanks).
declared_with() {
    local w
    for w in ${SWARMBOX_WITH//,/ }; do
        [ "$w" != "$1" ] || return 0
    done
    return 1
}

# prepare_after_install NAME: after a successful install; a failure is reported, never fatal (the tool is installed).
prepare_after_install() {
    find_manifest "$1" 2>/dev/null || return 0
    prepare_tool "$1" || true
}

cmd_prepare() {
    [ $# -eq 0 ] || usage
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; return 1; }
    local udir="" root d name failed=0 ldir
    udir=$(user_tools_dir) || udir=""
    local -a names
    mapfile -t names < <(
        for root in "$udir" "$IMAGE_TOOLS"; do
            [ -d "$root" ] || continue
            for d in "$root"/*/; do
                [ -f "${d}prepare.sh" ] || [ -f "${d}tool.conf" ] || continue
                d=${d%/}
                printf '%s\n' "${d##*/}"
            done
        done | LC_ALL=C sort -u
    )
    for name in "${names[@]}"; do
        if ! find_manifest "$name" 2>/dev/null; then
            # a broken manifest: only a tool that ships a prepare.sh is a failure
            ldir=$IMAGE_TOOLS/$name
            [ -n "$udir" ] && [ -f "$udir/$name/tool.conf" ] && ldir=$udir/$name
            if [ -f "$ldir/prepare.sh" ]; then
                echo "prepare-failed: $name: its manifest is broken (run swarmbox-tool validate)" >&2
                failed=1
            fi
            continue
        fi
        [ -f "$MDIR/prepare.sh" ] || continue
        if declared_with "$name" || is_installed "$name"; then
            prepare_tool "$name" || failed=1
        fi
    done
    return "$failed"
}

# ---- fingerprint, use, remove, new, doctor (slice 4b.5; design 6.11, 6.9, 6.7) -------------------------------------------------
# The fingerprint of an install is <prefix>/.swarmbox-env (ARCH, NODE_MAJOR, LIBC, VERSION). fp_check compares it with the running
# image. An empty value on either side (no Node in the image, an old record) is "unknown" and never a difference.

# load_dirs: sources dirs.sh into THIS shell (the SB_* variables); returns 1 when it cannot be found.
load_dirs() {
    local lib
    for lib in "$SB_LIB/dirs.sh" "$(dirname "$0")/dirs.sh"; do
        if [ -r "$lib" ]; then
            # shellcheck disable=SC1090  # chosen at run time
            . "$lib"
            return 0
        fi
    done
    return 1
}

fp_read() { sed -n "s/^$2=//p" "$1" | head -n 1; }

# fp_record NAME: prints the path of the fingerprint file of an installed NAME (M must hold its manifest).
fp_record() {
    local r
    r=$(root_for "$1")
    if [ "${M[UPDATE]:-managed}" = self ]; then printf '%s' "$r/$1/self/.swarmbox-env"; else printf '%s' "$r/$1/current/.swarmbox-env"; fi
}

# fp_check NAME: sets FP_ARCH (non-empty: "ARCH a -> b", the tool cannot run here) and FP_WARN (non-empty: NODE_MAJOR or LIBC
# differs, the tool may still work). Returns 1 when there is no record.
FP_ARCH=
FP_WARN=
fp_check() {
    local rec ra rn rl arch node libc
    FP_ARCH=
    FP_WARN=
    rec=$(fp_record "$1")
    [ -f "$rec" ] || return 1
    ra=$(fp_read "$rec" ARCH)
    rn=$(fp_read "$rec" NODE_MAJOR)
    rl=$(fp_read "$rec" LIBC)
    arch=$(tool_arch) || arch=
    node=$(current_node_major)
    libc=$(current_libc)
    if [ -n "$ra" ] && [ -n "$arch" ] && [ "$ra" != "$arch" ]; then FP_ARCH="ARCH $ra -> $arch"; fi
    if [ -n "$rn" ] && [ -n "$node" ] && [ "$rn" != "$node" ]; then FP_WARN="NODE_MAJOR $rn -> $node"; fi
    if [ -n "$rl" ] && [ -n "$libc" ] && [ "$rl" != "$libc" ]; then FP_WARN="${FP_WARN:+$FP_WARN, }LIBC $rl -> $libc"; fi
    return 0
}

# warned_dir: the per-entry markers, <state dir>/tool-warned (link --user clears it at every entry).
warned_dir() {
    load_dirs || return 1
    printf '%s' "$SB_STATE_DIR/tool-warned"
}

# fp_warn_once NAME: prints the NODE_MAJOR/LIBC warning of FP_WARN unless this entry already printed it for NAME.
fp_warn_once() {
    local wd marker
    wd=$(warned_dir) || wd=""
    marker=$wd/$1
    if [ -n "$wd" ] && [ -e "$marker" ]; then return 0; fi
    echo "swarmbox-tool: warning: $1 was installed in a different environment ($FP_WARN); it may still work. To rebuild it: swarmbox-tool install $1 --force (shown once per entry)" >&2
    if [ -n "$wd" ]; then
        if mkdir -p "$wd" 2>/dev/null; then : >"$marker" 2>/dev/null || true; fi
    fi
    return 0
}

# fp_gate NAME: at a shim call (run). ARCH differs: refuse (returns 1). NODE_MAJOR or LIBC differs: warn once per entry, return 0.
fp_gate() {
    fp_check "$1" || return 0
    if [ -n "$FP_ARCH" ]; then
        echo "swarmbox-tool: $1 was installed for another CPU architecture ($FP_ARCH) and cannot run here. Reinstall it: swarmbox-tool install $1 --force (or swarmbox-tool doctor --fix)" >&2
        return 1
    fi
    [ -z "$FP_WARN" ] || fp_warn_once "$1"
    return 0
}

# fp_scan_entry: at link --user (once per entry): clears the markers, then reports every installed tool whose fingerprint
# differs. Only reports; never fails the link.
fp_scan_entry() {
    local d name wd
    TDIR=$(tools_state_dir) || return 0
    wd=$(warned_dir) && rm -rf "$wd"
    [ -d "$TDIR" ] || return 0
    for d in "$TDIR"/*/; do
        [ -d "$d" ] || continue
        d=${d%/}
        name=${d##*/}
        [[ "$name" =~ $NAME_RE ]] || continue
        find_manifest "$name" 2>/dev/null || continue
        fp_check "$name" || continue
        if [ -n "$FP_ARCH" ]; then
            echo "swarmbox-tool: $name was installed for another CPU architecture ($FP_ARCH) and cannot run here, reinstall it: swarmbox-tool install $name --force (or swarmbox-tool doctor --fix)" >&2
        elif [ -n "$FP_WARN" ]; then
            fp_warn_once "$name"
        fi
    done
    return 0
}

# use NAME VERSION: moves `current` of a managed tool to an installed, complete version (atomic rename, under the lock).
cmd_use() {
    local name version tmp
    [ $# -eq 2 ] || usage
    name=$1
    version=$2
    check_tool_name "$name"
    if [[ ! "$version" =~ $VERSION_RE ]]; then
        echo "swarmbox-tool: '$version' is not a version name" >&2
        exit 64
    fi
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    find_manifest "$name" || { echo "swarmbox-tool: $FIND_ERR" >&2; exit 1; }
    if [ "${M[UPDATE]:-managed}" = self ]; then
        echo "swarmbox-tool: $name updates itself (UPDATE=self), so it has no versions to switch between (6.7)" >&2
        exit 1
    fi
    take_lock || exit 69
    if [ ! -d "$TDIR/$name/$version" ] || [ ! -f "$TDIR/$name/$version/.swarmbox-env" ] || ! version_dir_complete "$TDIR/$name/$version"; then
        drop_lock
        echo "swarmbox-tool: $name $version is not installed (swarmbox-tool install $name --version $version)" >&2
        exit 1
    fi
    if [ "$(readlink "$TDIR/$name/current" 2>/dev/null)" = "$version" ]; then
        drop_lock
        echo "swarmbox-tool: $name $version is already the active version" >&2
        exit 0
    fi
    tmp=$TDIR/$name/.current.$$
    rm -f "$tmp"
    if ln -s "$version" "$tmp" && mv -T "$tmp" "$TDIR/$name/current"; then
        drop_lock
        echo "swarmbox-tool: $name now uses $version" >&2
        exit 0
    fi
    rm -f "$tmp"
    drop_lock
    echo "swarmbox-tool: cannot move the current link of $name" >&2
    exit 1
}

# safe_rm PATH: rm -rf of one of an UPDATE=self tool's own paths, unless it is (or contains) a SwarmBox folder.
safe_rm() {
    local p r q
    p=$1
    [ -e "$p" ] || [ -L "$p" ] || return 0
    r=$(realpath -m -- "$p")
    for q in "$SB_DATA_DIR" "$SB_STATE_DIR" "$SB_CONFIG_DIR" "$TDIR" "$HOME"; do
        q=$(realpath -m -- "$q")
        case "$q/" in
            "$r"/*)
                echo "swarmbox-tool: not deleting $p: it holds SwarmBox's own folders" >&2
                return 0
                ;;
        esac
    done
    rm -rf -- "$p"
}

# remove NAME [--purge]: deletes the install of NAME in the workspace. Without --purge the manifests and shims stay, so the next
# call of the command installs it again (6.5). --purge also deletes a USER-level manifest and relinks; an image-level one is refused.
cmd_remove() {
    local name purge=0 have=0 c ushims udir
    [ $# -ge 1 ] || usage
    name=$1
    shift
    check_tool_name "$name"
    while [ $# -gt 0 ]; do
        case "$1" in
            --purge) purge=1; shift ;;
            *) usage ;;
        esac
    done
    load_dirs || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    TDIR=$SB_TOOLS_DIR
    find_manifest "$name" && have=1
    if [ "$have" -eq 0 ] && [ ! -e "$TDIR/$name" ]; then
        echo "swarmbox-tool: $FIND_ERR" >&2
        exit 1
    fi
    if [ "$purge" -eq 1 ] && [ "$have" -eq 1 ] && [ "$MDIR" = "$IMAGE_TOOLS/$name" ]; then
        echo "swarmbox-tool: the manifest of $name is part of the image and cannot be purged (remove it without --purge to delete only the install)" >&2
        exit 1
    fi
    take_lock || exit 69
    if [ "$have" -eq 1 ] && [ "${M[UPDATE]:-managed}" = self ]; then
        for c in ${M[PROVIDES]}; do
            if [ -f "$HOME/.local/bin/$c" ] || [ -L "$HOME/.local/bin/$c" ]; then rm -f -- "$HOME/.local/bin/$c"; fi
        done
        safe_rm "$HOME/.local/share/$name"
        safe_rm "$HOME/.local/state/$name"
        safe_rm "$HOME/.cache/$name"
    fi
    if [ -e "$TDIR/$name" ]; then
        rm -rf -- "${TDIR:?}/$name"
        echo "swarmbox-tool: removed the install of $name" >&2
    else
        echo "swarmbox-tool: $name is not installed: nothing to remove" >&2
    fi
    if [ "$purge" -eq 1 ] && [ "$have" -eq 1 ]; then
        rm -rf -- "${MDIR:?}"
        udir=$(user_tools_dir) && ushims=$(user_shims_dir) && link_level user "$udir" "$ushims" "" >/dev/null
        echo "swarmbox-tool: purged the user-level manifest of $name and relinked" >&2
    fi
    drop_lock
    exit 0
}

# provider_of COMMAND: prints the name of the tool that PROVIDES COMMAND at either level (first found); returns 1 when none.
provider_of() {
    local root d c udir
    udir=$(user_tools_dir) || udir=""
    for root in "$udir" "$IMAGE_TOOLS"; do
        if [ -z "$root" ] || [ ! -d "$root" ]; then continue; fi
        for d in "$root"/*/; do
            [ -f "${d}tool.conf" ] || continue
            load_manifest "${d%/}" || continue
            for c in ${M[PROVIDES]:-}; do
                if [ "$c" = "$1" ]; then
                    basename "${d%/}"
                    return 0
                fi
            done
        done
    done
    return 1
}

# new NAME [--repo | --dir DIR]: writes tool.conf and an executable install.sh that passes validate and stops with a message.
cmd_new() {
    local name base="" mode=user prov top udir
    [ $# -ge 1 ] || usage
    name=$1
    shift
    check_tool_name "$name"
    while [ $# -gt 0 ]; do
        case "$1" in
            --repo) [ "$mode" = user ] || usage; mode=repo; shift ;;
            --dir)
                if [ $# -lt 2 ] || [ "$mode" != user ]; then usage; fi
                mode=dir
                base=$2
                shift 2 ;;
            *) usage ;;
        esac
    done
    case "$mode" in
        user) base=$(user_tools_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; } ;;
        repo)
            top=$(git rev-parse --show-toplevel 2>/dev/null || true)
            if [ -z "$top" ] || [ ! -d "$top/container/tools" ]; then
                echo "swarmbox-tool: --repo needs the current folder to be inside a SwarmBox checkout (a git repository with container/tools)" >&2
                exit 1
            fi
            base=$top/container/tools ;;
    esac
    udir=$(user_tools_dir 2>/dev/null) || udir=""
    if [ -e "$base/$name" ] || [ -e "$IMAGE_TOOLS/$name" ] || { [ -n "$udir" ] && [ -e "$udir/$name" ]; }; then
        echo "swarmbox-tool: a tool named '$name' already exists (swarmbox-tool list)" >&2
        exit 1
    fi
    if prov=$(provider_of "$name"); then
        echo "swarmbox-tool: the command '$name' is already provided by '$prov': pick another name" >&2
        exit 1
    fi
    if ! mkdir -p "$base" || ! mkdir "$base/$name"; then
        echo "swarmbox-tool: cannot create $base/$name" >&2
        exit 1
    fi
    cat >"$base/$name/tool.conf" <<EOF
# Manifest of $name (design 6.3). KIND is agent (VERSION=latest) or tool (a pinned VERSION).
SCHEMA=1
NAME=$name
KIND=tool
PROVIDES="$name"
VERSION=0.0.1
EOF
    cat >"$base/$name/install.sh" <<'EOF'
#!/bin/bash
# Installer (design 6.4). It runs with TOOL_PREFIX, TOOL_VERSION and TOOL_ARCH (amd64 or arm64) set, in the home, with
# stdin closed. Write only below $TOOL_PREFIX; put each command of PROVIDES in $TOOL_PREFIX/bin; never use the system package
# manager or root; verify a download against TOOL_SHA256 when the manifest has SHA256_amd64 and SHA256_arm64.
set -euo pipefail
echo "swarmbox-tool: this installer is the skeleton written by 'swarmbox-tool new': edit $0 first" >&2
exit 1
EOF
    chmod 755 "$base/$name/install.sh"
    echo "swarmbox-tool: wrote $base/$name (tool.conf, install.sh): edit both, then run swarmbox-tool validate" >&2
    echo "$base/$name"
}

# doctor_classify NAME: with M loaded, sets DS (ok, needs reinstall, missing) and DD (the reason), and DCUR (the version that is
# active, for a managed tool).
DS=
DD=
DCUR=
doctor_classify() {
    local name=$1 rec
    DS=ok
    DD=
    DCUR=
    rec=$(fp_record "$name")
    if [ "${M[UPDATE]:-managed}" = self ]; then
        if [ ! -f "$rec" ]; then
            DS=missing
            return 0
        elif ! is_installed "$name"; then
            DS="needs reinstall"
            DD="the command is missing"
            return 0
        fi
    else
        DCUR=$(readlink "$(root_for "$name")/$name/current" 2>/dev/null || true)
        if [ -z "$DCUR" ]; then
            DS=missing
            return 0
        elif ! is_installed "$name"; then
            DS="needs reinstall"
            DD="$DCUR is incomplete"
            return 0
        fi
    fi
    fp_check "$name" || return 0
    if [ -n "$FP_ARCH" ] || [ -n "$FP_WARN" ]; then
        DS="needs reinstall"
        DD="${FP_ARCH}${FP_ARCH:+${FP_WARN:+, }}${FP_WARN}"
    fi
}

# doctor [--fix]: one line per tool: ok, needs reinstall, missing (never installed: normal, it installs on first use) or broken
# (the manifest does not load). Exit 1 when any tool needs a reinstall or is broken. --fix reinstalls those that need it, under
# one lock, with the version that was active. A NODE_MAJOR or LIBC difference is listed as "needs reinstall" here although the shim
# only warns and runs (decision log [4b.5]).
cmd_doctor() {
    local fix=0 lvl root d name seen=" " needfix=0 broken=0 failed=0 fixed=0 i
    local -a rows=() todo=() todover=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --fix) [ "$fix" -eq 0 ] || usage; fix=1; shift ;;
            *) usage ;;
        esac
    done
    TDIR=$(tools_state_dir) || { echo "swarmbox-tool: cannot find dirs.sh" >&2; exit 1; }
    for lvl in user image; do
        if [ "$lvl" = user ]; then root=$(user_tools_dir) || continue; else root=$IMAGE_TOOLS; fi
        [ -d "$root" ] || continue
        for d in "$root"/*/; do
            [ -d "$d" ] || continue
            d=${d%/}
            name=${d##*/}
            case "$seen" in *" $name "*) continue ;; esac
            seen="$seen$name "
            if ! load_manifest "$d"; then
                DS=broken
                DD=$LOAD_ERR
                DCUR=
                needfix=1
                broken=1
            else
                doctor_classify "$name"
                if [ "$DS" = "needs reinstall" ]; then
                    needfix=1
                    todo+=("$name")
                    todover+=("$DCUR")
                fi
            fi
            rows+=("$(printf '%-16s %-16s %s' "$name" "$DS" "$DD")")
        done
    done
    printf '%-16s %-16s %s\n' NAME STATE DETAIL
    [ "${#rows[@]}" -eq 0 ] || printf '%s\n' "${rows[@]}" | LC_ALL=C sort
    if [ "$fix" -eq 1 ] && [ "${#todo[@]}" -gt 0 ]; then
        take_lock || exit 1
        for i in "${!todo[@]}"; do
            name=${todo[$i]}
            if ! find_manifest "$name"; then
                echo "swarmbox-tool: cannot reinstall $name: $FIND_ERR" >&2
                failed=1
                continue
            fi
            if install_locked "$name" "${todover[$i]}" 1 "Reinstalling $name..."; then
                fixed=$((fixed + 1))
                prepare_after_install "$name"
            else
                echo "swarmbox-tool: doctor --fix: $name could not be reinstalled" >&2
                failed=1
            fi
        done
        drop_lock
        echo "swarmbox-tool: doctor --fix: reinstalled $fixed of ${#todo[@]} tool(s)" >&2
        [ "$failed" -eq 0 ] || exit 1
        exit "$broken"
    fi
    exit "$needfix"
}

usage() {
    cat >&2 <<'USAGE'
usage: swarmbox tool <command>       (inside the box: swarmbox-tool <command>)
  list                          the tools and their state
  install NAME [--force]        install a tool now (a tool also installs itself the first time you run it)
  update NAME                   update a tool that updates itself (for example claude)
  use NAME VERSION              switch to an installed version
  remove NAME [--purge]         remove an install
  doctor [--fix]                check the installs
  new NAME [--repo | --dir DIR] start a tool of your own
  validate [DIR]                check tool manifests
USAGE
    exit 64
}

[ $# -ge 1 ] || usage
cmd=$1
shift
case "$cmd" in
    validate)
        cmd_validate "$@"
        ;;
    link)
        [ $# -eq 1 ] || usage
        case "$1" in
            --system)
                link_level image "$IMAGE_TOOLS" "$IMAGE_SHIMS" "$HOST_DIR/tool-ports" || exit 1
                echo "swarmbox-tool link --system: linked the image level (shims in $IMAGE_SHIMS, tool-ports in $HOST_DIR)"
                ;;
            --user)
                if ! udir=$(user_tools_dir) || ! ushims=$(user_shims_dir); then
                    echo "swarmbox-tool link --user: cannot find dirs.sh, nothing was linked" >&2
                    exit 1
                fi
                link_level user "$udir" "$ushims" "" || exit 1
                echo "swarmbox-tool link --user: linked the user level (shims in $ushims)"
                fp_scan_entry
                ;;
            *) usage ;;
        esac
        ;;
    install) cmd_install "$@" ;;
    run) cmd_run "$@" ;;
    list) cmd_list "$@" ;;
    update) cmd_update "$@" ;;
    use) cmd_use "$@" ;;
    remove) cmd_remove "$@" ;;
    new) cmd_new "$@" ;;
    doctor) cmd_doctor "$@" ;;
    prepare) cmd_prepare "$@"; exit $? ;;
    -h|--help|help) usage ;;
    *)
        echo "swarmbox-tool: unknown command '$cmd'" >&2
        usage
        ;;
esac
