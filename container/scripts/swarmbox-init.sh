#!/bin/sh
# swarmbox-init (design 3.1, 3.7.5, 3.8, D20; installed as /usr/local/bin/swarmbox-init, run by `swarmbox-entrypoint init`).
#
#   swarmbox-init [--shell bash|zsh|fish] [--with LIST] [--workspace DIR] [--image REF]
#
# Prints, on standard output and only there: a comment line naming the version, then the marker block
# `# >>> swarmbox X.Y.Z >>>` ... `# <<< swarmbox X.Y.Z <<<` with the function of the chosen shell and the seed values (the flags
# that were given). It writes nothing to the machine, and the same arguments always print the same text (running it twice and
# appending both leaves two identical blocks, 3.7.5).
#
# The shell is --shell, else the base name of the SHELL variable that `podman run -e SHELL` passes in (D20; B21), and anything
# that is not zsh or fish silently gives bash. An explicit unknown --shell is exit 2.
# Exit codes: 0 ok; 2 usage, unknown shell, a newline in a value; 3 the VERSION or DEFAULTS file or a template is missing or malformed (a
# corrupted image).
#
# POSIX sh on purpose (decision [3.5]): it is tested under dash and bash --posix on the development machine. The templates are
# files of the helper archive (3.7.1): container/host/templates/{bash,zsh,fish}, read from the folder of the helper
# (SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host in tests). Placeholders in them: @VERSION@ (a validated version,
# written as it is), @IMAGE@, @SEED_WITH@, @SEED_WORKSPACE@, @SEED_IMAGE@ (each already quoted for the shell).
LC_ALL=C
export LC_ALL

HOST_DIR=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}

err() { printf 'swarmbox init: %s\n' "$*" >&2; }
die() { _rc=$1; shift; err "$*"; exit "$_rc"; }

usage() {
    cat <<'USAGE'
usage: swarmbox init [--shell bash|zsh|fish] [--with LIST] [--workspace DIR] [--image REF]
  Prints the shell function (between markers) on standard output; append it to your shell startup file.
  --with LIST       tools to have ready (recorded as WITH the first time the box is used)
  --workspace DIR   the workspace folder (recorded as WORKSPACE); use an absolute path or ~/...
  --image REF       the image to use (recorded as IMAGE)
  --shell SHELL     bash, zsh or fish; without it the base name of $SHELL, and bash for anything else
USAGE
}

SHELL_NAME=
SEED_WITH=
SEED_WS=
SEED_IMAGE=
while [ $# -gt 0 ]; do
    case $1 in
        -h|--help) usage; exit 0 ;;
        --shell|--with|--workspace|--image)
            [ $# -ge 2 ] || die 2 "$1 needs a value."
            _opt=$1
            _val=$2
            shift 2
            ;;
        --shell=*|--with=*|--workspace=*|--image=*)
            _opt=${1%%=*}
            _val=${1#*=}
            shift
            ;;
        -*) die 2 "unknown option '$1'. Try: swarmbox init --help" ;;
        *) die 2 "unexpected argument '$1'. Try: swarmbox init --help" ;;
    esac
    case $_opt in
        --shell) SHELL_NAME=$_val; SHELL_GIVEN=1 ;;
        --with) SEED_WITH=$_val ;;
        --workspace) SEED_WS=$_val ;;
        --image) SEED_IMAGE=$_val ;;
    esac
    case $_val in
        *'
'*) die 2 "the value of $_opt must not contain a newline." ;;
    esac
done

# an image reference is a bare argument of `podman run` in the function: a leading '-' would be read as an option (security review SR-01)
case $SEED_IMAGE in
    -*) die 2 "the value of --image must be an image reference, not an option ('$SEED_IMAGE')." ;;
esac

# the shell: explicit (and then strict), else from SHELL (and then silent)
if [ -n "${SHELL_GIVEN:-}" ]; then
    case $SHELL_NAME in
        bash|zsh|fish) ;;
        *) die 2 "unknown shell '$SHELL_NAME'. Use --shell bash, zsh or fish." ;;
    esac
else
    case ${SHELL:-} in
        */zsh|zsh) SHELL_NAME=zsh ;;
        */fish|fish) SHELL_NAME=fish ;;
        *) SHELL_NAME=bash ;;
    esac
fi

VERSION_FILE=$HOST_DIR/VERSION
VERSION_STR=$(sed -n '1p' "$VERSION_FILE" 2> /dev/null | tr -d '\r') || VERSION_STR=
case $VERSION_STR in
    [0-9]*.[0-9]*.[0-9]*) ;;
    *) die 3 "the VERSION file of the host helper folder ($VERSION_FILE) does not hold a version (X.Y.Z): '$VERSION_STR'." ;;
esac
case $VERSION_STR in
    *[!0-9A-Za-z.+-]*) die 3 "the VERSION file ($VERSION_FILE) holds characters that are not allowed in a version: '$VERSION_STR'." ;;
esac

# The default image repository comes from the DEFAULTS file of the helper folder (D40), read as the helper does: parsed, not sourced.
DEFAULTS_FILE=$HOST_DIR/DEFAULTS
[ -r "$DEFAULTS_FILE" ] || die 3 "the host helper folder has no DEFAULTS file ($DEFAULTS_FILE); this image is corrupted."
REGISTRY_REPO=
while IFS= read -r _l || [ -n "$_l" ]; do
    case $_l in
        SWARMBOX_DEFAULT_IMAGE_REPO=*)
            REGISTRY_REPO=${_l#*=}
            case $REGISTRY_REPO in
                \'*\') REGISTRY_REPO=${REGISTRY_REPO#\'}; REGISTRY_REPO=${REGISTRY_REPO%\'} ;;
            esac
            ;;
    esac
done < "$DEFAULTS_FILE"
case $REGISTRY_REPO in
    ''|*[[:space:]\'\"]*) die 3 "the DEFAULTS file ($DEFAULTS_FILE) has no usable SWARMBOX_DEFAULT_IMAGE_REPO: '$REGISTRY_REPO'." ;;
esac
TEMPLATE=$HOST_DIR/templates/$SHELL_NAME
[ -r "$TEMPLATE" ] || die 3 "the template for $SHELL_NAME ($TEMPLATE) is missing from this image."

# quote VALUE for the shell: single quotes; a quote inside is '\'' in bash and zsh, and \' in fish (where a backslash is also
# special inside single quotes)
quote() {
    if [ "$SHELL_NAME" = fish ]; then
        printf "'%s'" "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g")"
    else
        printf "'%s'" "$(printf '%s' "$1" | sed -e "s/'/'\\\\''/g")"
    fi
}

IMAGE_REF=$SEED_IMAGE
[ -n "$IMAGE_REF" ] || IMAGE_REF=$REGISTRY_REPO:$VERSION_STR
X_VERSION=$VERSION_STR
X_IMAGE=$(quote "$IMAGE_REF")
X_SEED_WITH=$(quote "$SEED_WITH")
X_SEED_WORKSPACE=$(quote "$SEED_WS")
X_SEED_IMAGE=$(quote "$SEED_IMAGE")
export X_VERSION X_IMAGE X_SEED_WITH X_SEED_WORKSPACE X_SEED_IMAGE

# Replace the placeholders from left to right in one pass, so a value that looks like a placeholder is never expanded again.
# awk reads the values from its environment: no value is ever parsed as a pattern, an escape or a program.
BLOCK=$(awk '
BEGIN {
    n = split("@VERSION@ @IMAGE@ @SEED_WITH@ @SEED_WORKSPACE@ @SEED_IMAGE@", keys, " ")
    val["@VERSION@"] = ENVIRON["X_VERSION"]
    val["@IMAGE@"] = ENVIRON["X_IMAGE"]
    val["@SEED_WITH@"] = ENVIRON["X_SEED_WITH"]
    val["@SEED_WORKSPACE@"] = ENVIRON["X_SEED_WORKSPACE"]
    val["@SEED_IMAGE@"] = ENVIRON["X_SEED_IMAGE"]
}
{
    s = $0
    out = ""
    while (1) {
        best = 0
        for (k = 1; k <= n; k++) {
            i = index(s, keys[k])
            if (i > 0 && (best == 0 || i < best)) { best = i; bk = keys[k] }
        }
        if (best == 0) break
        out = out substr(s, 1, best - 1) val[bk]
        s = substr(s, best + length(bk))
    }
    print out s
}' "$TEMPLATE") || die 3 "could not read the template $TEMPLATE."
[ -n "$BLOCK" ] || die 3 "the template $TEMPLATE is empty."

# shellcheck disable=SC2016  # the backquotes are text of the comment line, not a command substitution
printf '# swarmbox %s: the shell function printed by `swarmbox init` (append it to your shell startup file)\n' "$VERSION_STR"
printf '%s\n' "$BLOCK"
if [ -t 1 ]; then
    printf 'swarmbox init: append this to your shell startup file, then open a new shell.\n' >&2
fi
exit 0
