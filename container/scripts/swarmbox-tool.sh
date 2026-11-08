#!/bin/bash
# swarmbox-tool (design 6; installed as /usr/local/bin/swarmbox-tool). Phase 4a grows it in slices. State of this file:
#
#   validate [DIR]  REAL (slice 4a.1): reads the manifests of both levels (or only the folder DIR) and checks the rules of 6.9.
#                   Exit 0 all good, 1 a manifest failed, 64 usage.
#   link --system   writes an EMPTY box:/usr/local/share/swarmbox/host/tool-ports (shims, index and ports come in a later slice);
#                   already reads the image-level manifests and says on stderr which ones it skips
#   link --user     the same for the user level; writes nothing yet
#   prepare         nothing to do, succeeds
#   anything else   exit 70 (EX_SOFTWARE) with a message that names Phase 4a (install, run, list, update... come in later slices)
#
# Manifests (6.3) are shell-sourceable KEY=VALUE files. Loading one SOURCES it in a subshell, so it executes arbitrary shell:
# that is why only two levels are ever read, the image (read-only, built from the repository) and the user level (the user's own
# workspace), never a project folder (D18, 6.10). The `install.sh` lint of validate is a lint (design 6.4): it catches mistakes,
# it does not make an installer safe to run.
#
# Test-only variables (decision log [2.5] and [4a.1]; not in the configuration table of design 8): SWARMBOX_TEST_HOST_DIR replaces
# /usr/local/share/swarmbox/host, SWARMBOX_TEST_IMAGE_TOOLS replaces /usr/local/lib/swarmbox/tools, SWARMBOX_TEST_USER_TOOLS
# replaces the user level ($SB_CONFIG_DIR/tools), SWARMBOX_TEST_LIB is the folder with dirs.sh.

HOST_DIR=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}
IMAGE_TOOLS=${SWARMBOX_TEST_IMAGE_TOOLS:-/usr/local/lib/swarmbox/tools}
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
    for a in amd64 arm64; do
        h=${M[SHA256_$a]:-}
        if [ -n "$h" ] && [[ ! "$h" =~ ^[0-9a-fA-F]{64}$ ]]; then
            err "SHA256_$a is not a 64-digit hexadecimal checksum"
        fi
    done
    [ -z "${M[SHA256_amd64]:-}" ] || [ -n "${M[SHA256_arm64]:-}" ] || err "SHA256_arm64 is missing: SHA256_amd64 is declared and both architectures are required"
    [ -z "${M[SHA256_arm64]:-}" ] || [ -n "${M[SHA256_amd64]:-}" ] || err "SHA256_amd64 is missing: SHA256_arm64 is declared and both architectures are required"
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

# link_report LEVEL DIR: reads the manifests of one level and says on stderr which ones it skips (slice 4a.1: no shims yet).
link_report() {
    local level=$1 root=$2 d name
    [ -d "$root" ] || return 0
    for d in "$root"/*/; do
        [ -d "$d" ] || continue
        d=${d%/}
        name=$(basename "$d")
        load_manifest "$d" || echo "swarmbox-tool: skipping the $level manifest '$name': $LOAD_ERR" >&2
    done
}

usage() {
    echo "usage: swarmbox-tool validate [DIR] | link --system|--user | prepare   (the other subcommands arrive in Phase 4a)" >&2
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
                link_report image "$IMAGE_TOOLS"
                if ! mkdir -p "$HOST_DIR" || ! : > "$HOST_DIR/tool-ports"; then
                    echo "swarmbox-tool: cannot write $HOST_DIR/tool-ports" >&2
                    exit 1
                fi
                echo "swarmbox-tool link --system: stub, wrote an empty $HOST_DIR/tool-ports"
                ;;
            --user)
                if udir=$(user_tools_dir); then link_report user "$udir"; fi
                echo "swarmbox-tool link --user: stub, no tools to link yet (Phase 4a)"
                ;;
            *) usage ;;
        esac
        ;;
    prepare)
        echo "swarmbox-tool prepare: stub, no tools to prepare yet (Phase 4a)"
        ;;
    *)
        echo "swarmbox-tool: '$cmd' is not available yet: this is a placeholder, tools arrive in Phase 4a of the SwarmBox 2.0 build" >&2
        exit 70
        ;;
esac
