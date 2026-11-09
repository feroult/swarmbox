#!/bin/sh
# name-check.sh: the reduced name availability check of D25 (slice 7.6). NOT legal advice.
# Usage: sh dev/name-check.sh [name [github-owner]]      (defaults: swarmbox, feroult)
# It asks four public, unauthenticated endpoints with curl (GitHub repository search, the owner's repository, npm, PyPI) and
# prints one line each: "TAKEN|FREE|UNKNOWN <source> <text>". It exits 0 always: it informs, the owner decides.
# It writes nothing to disk. Unauthenticated GitHub search is rate limited (about 10 requests a minute): UNKNOWN then.
# A trademark search (USPTO, EUIPO, WIPO Global Brand Database) is NOT done by this script; see docs/release-checklist.md.
NAME=${1:-swarmbox}
OWNER=${2:-feroult}
UA="swarmbox-name-check"

# get URL: prints "<status>" on the last line of the output; UNKNOWN is the empty status
get() { curl -s -m 20 -A "$UA" -H 'Accept: application/json' -w '%{http_code}' "$1" 2>/dev/null; }
status_of() { printf '%s' "$1" | tail -c 3; }

out=$(get "https://api.github.com/search/repositories?q=$NAME+in:name&per_page=1")
rc=$?
st=$(status_of "$out")
if [ "$rc" != 0 ] || [ "$st" != 200 ]; then
    echo "UNKNOWN github-search no answer (curl exit $rc, status '${st:-none}')"
else
    n=$(printf '%s' "$out" | sed -n 's/.*"total_count": *\([0-9][0-9]*\).*/\1/p' | head -n 1)
    if [ "${n:-0}" -gt 0 ]; then echo "TAKEN github-search $n public repositories have '$NAME' in their name"
    else echo "FREE github-search no public repository has '$NAME' in its name"; fi
fi

out=$(get "https://api.github.com/repos/$OWNER/$NAME")
rc=$?
st=$(status_of "$out")
if [ "$rc" != 0 ]; then echo "UNKNOWN github-repo no answer (curl exit $rc)"
elif [ "$st" = 200 ]; then echo "TAKEN github-repo $OWNER/$NAME exists (the owner's own repository is expected)"
elif [ "$st" = 404 ]; then echo "FREE github-repo $OWNER/$NAME does not exist"
else echo "UNKNOWN github-repo status $st"; fi

for pair in "npm https://registry.npmjs.org/$NAME" "pypi https://pypi.org/pypi/$NAME/json"; do
    src=${pair%% *}; url=${pair#* }
    out=$(get "$url")
    rc=$?
    st=$(status_of "$out")
    if [ "$rc" != 0 ]; then echo "UNKNOWN $src no answer (curl exit $rc)"
    elif [ "$st" = 200 ]; then echo "TAKEN $src a package named '$NAME' exists ($url)"
    elif [ "$st" = 404 ]; then echo "FREE $src no package named '$NAME'"
    else echo "UNKNOWN $src status $st"; fi
done

echo "This is a name lookup on three public indexes, not a trademark search and not legal advice."
exit 0
