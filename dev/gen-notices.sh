#!/bin/sh
# gen-notices.sh: list the Debian packages of a root file system with their licenses (slice 7.2, design 11 last bullet).
#
# Read-only. For each installed package (dpkg-query -W) it reads /usr/share/doc/<package>/copyright, collects the
# "License:" fields of a machine-readable (DEP-5) file, and prints a tab-separated table sorted by package name:
#   package  version  licenses  source  flags
# source is https://sources.debian.org/src/<source package>/ (the Source field of the package, else its own name).
# For an old-style file the cell says "see copyright file (mentions: ...)": a hint, not a finding.
# flags: NO-COPYRIGHT-FILE (no copyright file for the package) and NO-LICENSE-FIELD (a copyright file without a
# "License:" field, an old-style file that has to be read by hand). Flagged packages are also listed on stderr.
#
# Usage: dev/gen-notices.sh [--root DIR]              DIR is the file system to read (default /); dpkg-query runs with
#                                                     --admindir DIR/var/lib/dpkg when DIR is not /
#        dev/gen-notices.sh --image swarmbox-test-X   run this script inside that image (a throwaway container named
#                                                     swarmbox-test-notices-<random>, removed by its exact name)
# The committed output is docs/debian-packages.tsv (see THIRD_PARTY_NOTICES.md for the evidence tag).
set -eu
ROOT=/
IMAGE=""
while [ $# -gt 0 ]; do
    case $1 in
        --root) [ $# -ge 2 ] || { echo "gen-notices: --root needs a value" >&2; exit 64; }; ROOT=$2; shift 2 ;;
        --image) [ $# -ge 2 ] || { echo "gen-notices: --image needs a value" >&2; exit 64; }; IMAGE=$2; shift 2 ;;
        *) echo "gen-notices: unknown option $1" >&2; exit 64 ;;
    esac
done

if [ -n "$IMAGE" ]; then
    case $IMAGE in
        swarmbox-test-?*) ;;
        *) echo "gen-notices: the image must be a swarmbox-test- image (got '$IMAGE')" >&2; exit 64 ;;
    esac
    NAME="swarmbox-test-notices-run-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
    trap 'podman rm -f "$NAME" >/dev/null 2>&1 || true' EXIT HUP INT TERM
    # the script goes in through stdin; the entrypoint is replaced so that no service starts
    podman run -i --rm --name "$NAME" --entrypoint sh "$IMAGE" -s -- --root / < "$0"
    exit $?
fi

[ -d "$ROOT" ] || { echo "gen-notices: $ROOT is not a directory" >&2; exit 66; }
DOC="${ROOT%/}/usr/share/doc"
if [ "$ROOT" = / ]; then
    set -- -W
else
    set -- --admindir "${ROOT%/}/var/lib/dpkg" -W
fi
TMP=$(mktemp -d "${TMPDIR:-/tmp}/gen-notices.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

dpkg-query "$@" -f '${binary:Package}|${Version}|${Source}|${Homepage}\n' > "$TMP/raw"

: > "$TMP/rows"
: > "$TMP/flagged"
while IFS='|' read -r pkg ver src _home; do
    [ -n "$pkg" ] || continue
    name=${pkg%%:*}
    case $src in '') s=$name ;; *) s=${src%% *} ;; esac
    file="$DOC/$name/copyright"
    flags=""
    if [ -f "$file" ]; then
        lic=$(awk '
            /^License:[ \t]*/ { v = $0; sub(/^License:[ \t]*/, "", v); gsub(/[ \t\r]+$/, "", v); if (v != "") seen[v] = 1 }
            END { n = 0; for (k in seen) { n++; a[n] = k }
                  for (i = 1; i <= n; i++) for (j = i + 1; j <= n; j++) if (a[j] < a[i]) { t = a[i]; a[i] = a[j]; a[j] = t }
                  out = ""; for (i = 1; i <= n; i++) out = out (i > 1 ? ", " : "") a[i]; print out }' "$file")
        if [ -z "$lic" ]; then
            # an old-style file: list what it points at (common-licenses files, else license words) as a hint only
            refs=$(grep -o '/usr/share/common-licenses/[A-Za-z0-9.+-]*' "$file" | sed 's|.*/||' | LC_ALL=C sort -u | paste -sd, - | sed 's/,/, /g')
            if [ -z "$refs" ]; then
                refs=$(grep -oiwE 'GPL|LGPL|GFDL|MIT|Expat|BSD|ISC|Zlib|MPL|Apache|Artistic|public domain' "$file" | LC_ALL=C sort -u | paste -sd, - | sed 's/,/, /g')
            fi
            lic="see copyright file${refs:+ (mentions: $refs)}"
            flags="NO-LICENSE-FIELD"
        fi
    else
        lic="unknown (no copyright file)"
        flags="NO-COPYRIGHT-FILE"
    fi
    printf '%s\t%s\t%s\thttps://sources.debian.org/src/%s/\t%s\n' "$name" "$ver" "$lic" "$s" "$flags" >> "$TMP/rows"
    [ -z "$flags" ] || printf '%s %s\n' "$name" "$flags" >> "$TMP/flagged"
done < "$TMP/raw"

printf 'package\tversion\tlicenses\tsource\tflags\n'
LC_ALL=C sort -u "$TMP/rows"
if [ -s "$TMP/flagged" ]; then
    echo "gen-notices: packages flagged (read their copyright files by hand):" >&2
    LC_ALL=C sort -u "$TMP/flagged" | sed 's/^/  /' >&2
fi
