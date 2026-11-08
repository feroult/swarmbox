#!/bin/bash
# Spike B12 (c): what $0 holds for a script reached through a symlink, per shell.
#
# Design claims: 6.2 (swarmbox-shim finds its tool from basename "$0" when invoked through a symlink named like the
# tool); the host helper (3.7) must also know where it lives. Per-shell results are kept separate: a script run by
# its shebang (the shim case) and a file read with `.` / source (the function case) are different questions.
# Run: bash tests/spikes/spike_b12_symlink_arg0.sh   Exit 1 if the shim claim is contradicted in any shell.
set -u
fail=0
dir=$(mktemp -d /tmp/swarmbox-test-arg0-XXXXXX)
trap 'rm -rf "$dir"' EXIT
mkdir -p "$dir/bin" "$dir/shims"
ok()  { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
have() { command -v "$1" >/dev/null 2>&1; }

summary=""
for sh in dash bash zsh "busybox sh"; do
    set -- $sh
    if ! have "$1"; then printf '  skip  %s is not installed [unverified]\n' "$sh"; continue; fi
    bin=$(command -v "$1")
    label=$(printf '%s' "$sh" | tr ' ' '_')
    # shebang script (kernel passes the path as invoked)
    if [ "$sh" = "busybox sh" ]; then shebang="#!$bin sh"; else shebang="#!$bin"; fi
    printf '%s\nprintf "%%s|%%s|%%s\\n" "$0" "$(basename "$0")" "$*"\n' "$shebang" > "$dir/bin/swarmbox-shim-$label"
    chmod +x "$dir/bin/swarmbox-shim-$label"
    ln -s "$dir/bin/swarmbox-shim-$label" "$dir/shims/gcloud"
    ln -s "$dir/bin/swarmbox-shim-$label" "$dir/shims/clasp"
    g=$("$dir/shims/gcloud" a "b c")
    c=$("$dir/shims/clasp" x)
    # through PATH lookup, as a user types the command
    p=$(PATH="$dir/shims:$PATH" gcloud p1)
    rm -f "$dir/shims/gcloud" "$dir/shims/clasp"
    [ "$(printf '%s' "$g" | cut -d'|' -f2)" = gcloud ] && [ "$(printf '%s' "$c" | cut -d'|' -f2)" = clasp ] \
        && ok "$sh, run by its shebang through two symlinks: basename \$0 is the symlink's own name" \
        || bad "$sh shebang: gcloud='$g' clasp='$c'"
    [ "$(printf '%s' "$g" | cut -d'|' -f3)" = "a b c" ] && ok "$sh: arguments arrive intact" || bad "$sh: arguments '$g'"
    [ "$(printf '%s' "$p" | cut -d'|' -f2)" = gcloud ] && ok "$sh, found through PATH: basename \$0 is gcloud (\$0='$(printf '%s' "$p" | cut -d'|' -f1 | sed "s|$dir|<tmp>|")')" \
        || bad "$sh via PATH: '$p'"
    # sourced file: what does $0 hold inside a sourced file / a function defined there?
    printf 'where() { printf "%%s\\n" "$0"; }\nwhere\n' > "$dir/frag.sh"
    ln -sf "$dir/frag.sh" "$dir/frag-link.sh"
    if [ "$sh" = "busybox sh" ]; then runner="$bin sh"; else runner="$bin"; fi
    s=$($runner -c ". '$dir/frag-link.sh'" 2>&1 | head -1 | sed "s|$dir|<tmp>|")
    summary="$summary
  sourced through a symlink, $sh: \$0 inside the file's function = '$s'"
done
printf '%s\n' "$summary"
if [ "$fail" -eq 0 ]; then
    d=$(date +%F)
    echo "RESULT b12-arg0 CONFIRMED: a symlink keeps its own name in \$0 under every shell tested [verified: spike_b12_symlink_arg0.sh; $d; $(podman --version | sed 's/podman version/Podman/'), $(. /etc/os-release; echo "$PRETTY_NAME"); no image involved; reduced: run on the box, not in a throwaway container, shells are the box's own dash, bash, zsh, busybox]"
else
    echo "RESULT b12-arg0 CONTRADICTED"
fi
exit "$fail"
