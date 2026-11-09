#!/bin/sh
# swarmbox-install (installed as /usr/local/bin/swarmbox-install, run by `swarmbox-entrypoint install`).
#
#   podman run --rm IMAGE install [--with TOOLS] [--image REF] | sh
#
# Prints, on standard output and only there, a small POSIX sh installer that carries the `swarmbox` script of this image (a quoted
# here-doc). Run by sh, the installer writes the script to ${SWARMBOX_BIN_DIR:-$HOME/.local/bin}/swarmbox (mode 755, through a
# temporary file and a rename, so a running or half-written copy is never seen), then runs `swarmbox setup`, which checks Podman,
# puts the support files in place, records the image reference and the tools in the SwarmBox config file, and prints the PATH
# advice, a warning for an old shell function, and what to run next. It writes no shell startup file. The same arguments always
# print the same text, and running the installer again changes nothing that is already right.
#
# The image reference recorded is --image, else the one Podman recorded for this container in /run/.containerenv (the name given to
# `podman run`, so a local build is found under its own name), else the default repository of the image at its own version.
# Exit codes: 0 ok; 2 usage or a value that is not allowed; 3 the script or DEFAULTS/VERSION of this image is missing or malformed.
#
# POSIX sh on purpose: it is tested under dash and bash --posix. SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host and
# SWARMBOX_TEST_CONTAINERENV replaces /run/.containerenv in tests.
LC_ALL=C
export LC_ALL

HOST_DIR=${SWARMBOX_TEST_HOST_DIR:-/usr/local/share/swarmbox/host}
CONTAINERENV=${SWARMBOX_TEST_CONTAINERENV:-/run/.containerenv}
END=SWARMBOX_SCRIPT_END

err() { printf 'swarmbox install: %s\n' "$*" >&2; }
die() { _rc=$1; shift; err "$*"; exit "$_rc"; }

usage() {
    cat <<'USAGE'
usage: podman run --rm IMAGE install [--with TOOLS] [--image REF] | sh
  Prints an installer for the `swarmbox` command; sh runs it. Nothing is written until sh does.
  --with TOOLS   tools to have ready (recorded as WITH in the config, for example claude,gcloud)
  --image REF    the image to record (default: the name this image was started under)
USAGE
}

WITH=
IMAGE=
while [ $# -gt 0 ]; do
    case $1 in
        -h|--help) usage; exit 0 ;;
        --with|--image)
            [ $# -ge 2 ] || die 2 "$1 needs a value."
            _opt=$1
            _val=$2
            shift 2
            ;;
        --with=*|--image=*)
            _opt=${1%%=*}
            _val=${1#*=}
            shift
            ;;
        -*) die 2 "unknown option '$1'. Try: swarmbox install --help" ;;
        *) die 2 "unexpected argument '$1'. Try: swarmbox install --help" ;;
    esac
    case $_val in
        *'
'*) die 2 "the value of $_opt must not contain a newline." ;;
    esac
    case $_opt in
        --with) WITH=$_val ;;
        --image) IMAGE=$_val ;;
    esac
done

SCRIPT=$HOST_DIR/swarmbox-host
[ -r "$SCRIPT" ] || die 3 "this image has no script ($SCRIPT)."
# the here-doc must not end early, and the script must be complete
if grep -qx "$END" "$SCRIPT"; then die 3 "the script of this image holds the line $END."; fi
grep -q '^SCRIPT_VERSION=' "$SCRIPT" || die 3 "the script of this image has no SCRIPT_VERSION."

# the image: --image, else what Podman recorded for this container, else the default repository at this image's version
if [ -z "$IMAGE" ] && [ -r "$CONTAINERENV" ]; then
    IMAGE=$(sed -n 's/^image="\(.*\)"$/\1/p' "$CONTAINERENV" | head -n 1)
fi
if [ -z "$IMAGE" ]; then
    VERSION=$(sed -n '1p' "$HOST_DIR/VERSION" 2> /dev/null | tr -d '\r')
    REPO=$(sed -n "s/^SWARMBOX_DEFAULT_IMAGE_REPO=['\"]*\\([^'\"]*\\)['\"]*\$/\\1/p" "$HOST_DIR/DEFAULTS" 2> /dev/null | head -n 1)
    case $VERSION in [0-9]*.[0-9]*.[0-9]*) ;; *) die 3 "the VERSION file of this image does not hold a version: '$VERSION'." ;; esac
    [ -n "$REPO" ] || die 3 "the DEFAULTS file of this image has no SWARMBOX_DEFAULT_IMAGE_REPO."
    case $REPO in
        *'<'*|*'>'*) die 2 "Podman did not tell this container the image it was started from, and the default repository ($REPO) is a placeholder until the image is published. Add --image REF, for a local build use the name you gave to podman build, with localhost/ in front" ;;
    esac
    IMAGE=$REPO:$VERSION
    err "note: Podman did not tell this container the image it was started from, so the default $IMAGE is recorded; add --image REF to record another."
fi
# an image reference is a bare argument of `podman run` in the script: a leading '-' would be read as an option
case $IMAGE in
    -*) die 2 "the image must be an image reference, not an option ('$IMAGE')." ;;
esac

# quote VALUE for sh: single quotes, a quote inside is '\''
quote() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

cat <<EOF
#!/bin/sh
# SwarmBox installer, made by \`swarmbox install\`. Writes the swarmbox command, then runs \`swarmbox setup\`. No startup file is edited.
set -eu
BIN=\${SWARMBOX_BIN_DIR:-\${HOME:?HOME is not set}/.local/bin}
IMAGE=$(quote "$IMAGE")
WITH=$(quote "$WITH")
mkdir -p "\$BIN"
tmp=\$(mktemp "\$BIN/.swarmbox.XXXXXX")
trap 'rm -f "\$tmp"' EXIT
cat > "\$tmp" <<'$END'
EOF
cat "$SCRIPT"
cat <<EOF
$END
chmod 755 "\$tmp"
mv -f "\$tmp" "\$BIN/swarmbox"
trap - EXIT
exec "\$BIN/swarmbox" setup --image "\$IMAGE" \${WITH:+--with "\$WITH"} < /dev/null
EOF
