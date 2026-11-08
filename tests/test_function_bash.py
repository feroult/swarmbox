"""Slice 3.5: the generated function in bash (design 3.6, 13.3 layer 4). The cases are in tests/function_cases.py.

Run: python3 tests/test_function_bash.py

bash 3.2 (macOS /bin/bash) cannot be run on this machine. What stands in for it, and only that: the cases run a second time under
`bash --posix`, and a lint test rejects every bash 4+ construct in the template (associative arrays, ${var,,}, ${var^^}, mapfile,
readarray, &>>, |&, [[ -v ]], coproc, `local -n`, `declare -g`, ${var@Q}, `;&`, `printf -v` with an array element). A construct that
this list does not know about, or a bash 3.2 behavior that differs for another reason (for example `set -u` with an empty array),
is not caught: macOS bash 3.2 stays [unverified] until a macOS runner exists (Phase 6).
"""
import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from function_cases import ROOT, FunctionCases  # noqa: E402

BASH = shutil.which("bash")
TEMPLATE = os.path.join(ROOT, "container", "host", "templates", "bash")

BASH4 = [
    (r"\bdeclare\s+-[a-zA-Z]*A", "associative array (declare -A)"),
    (r"\btypeset\s+-[a-zA-Z]*A", "associative array (typeset -A)"),
    (r"\blocal\s+-[a-zA-Z]*A", "associative array (local -A)"),
    (r"\blocal\s+-[a-zA-Z]*n", "name reference (local -n)"),
    (r"\bdeclare\s+-[a-zA-Z]*[ng]", "declare -n or -g"),
    (r"\$\{[A-Za-z_0-9@*!#]+,,?[^}]*\}", "lower-casing ${var,,}"),
    (r"\$\{[A-Za-z_0-9@*!#]+\^\^?[^}]*\}", "upper-casing ${var^^}"),
    (r"\$\{[A-Za-z_0-9@*!#]+@[QEPAa]\}", "parameter transformation ${var@Q}"),
    (r"\bmapfile\b", "mapfile"),
    (r"\breadarray\b", "readarray"),
    (r"&>>", "&>>"),
    (r"\|&", "|&"),
    (r"\[\[\s+-v\b", "[[ -v ]]"),
    (r"\[\s+-v\s", "[ -v ]"),
    (r"\bcoproc\b", "coproc"),
    (r";&|;;&", "case fall-through ;& or ;;&"),
    (r"\bshopt\s+-s\s+(globstar|lastpipe|autocd|dirspell|checkjobs)", "bash 4 shopt option"),
    (r"\bset\s+-o\s+pipefail", "pipefail (a bash 3 feature on paper, but never rely on it here)"),
    (r"\bread\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[iNnt]\s+[0-9.]+[^|;&]*\bread\b", "read with a fractional timeout"),
    (r"\$\{![A-Za-z_]+\[@\]\}", "array indices ${!a[@]}"),
    (r"\bwait\s+-n\b", "wait -n"),
    (r"\bprintf\s+-v\s+[A-Za-z_]+\[", "printf -v into an array element"),
    (r"\+=\(", "array append +=(...)"),
    (r"\bcompgen\b", "compgen"),
]


def code_lines(text):
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.split(" #")[0] if not line.lstrip().startswith("#") else ""
        if stripped.strip():
            yield n, stripped


class BashFunction(FunctionCases, unittest.TestCase):
    SHELL = [BASH, "--noprofile", "--norc"]
    NAME = "bash"
    STRICT = "-u"


class BashPosixFunction(FunctionCases, unittest.TestCase):
    """The same table under `bash --posix` (the closest stand-in here for macOS's /bin/sh, which is bash 3.2 in POSIX mode)."""
    SHELL = [BASH, "--posix", "--noprofile", "--norc"]
    NAME = "bash"
    STRICT = "-u"


class Bash32Lint(unittest.TestCase):
    def test_the_template_has_no_bash_4_construct(self):
        with open(TEMPLATE) as f:
            text = f.read()
        for n, line in code_lines(text):
            for rx, what in BASH4:
                self.assertIsNone(re.search(rx, line), "template line %d uses %s: %s" % (n, what, line))

    def test_the_lint_itself_catches_each_construct(self):
        samples = ["declare -A m", "local -A m", 'echo "${x,,}"', 'echo "${x^^}"', "mapfile -t a < f", "readarray a", "cmd &>> f",
                   "a |& b", "[[ -v x ]]", "coproc c", "x=${y@Q}", "case $x in a) ;& b) ;; esac", "shopt -s globstar",
                   "local -n r=x", "a+=(x)"]
        for s in samples:
            self.assertTrue(any(re.search(rx, s) for rx, _ in BASH4), "the lint misses: %s" % s)

    def test_the_lint_accepts_what_the_template_needs(self):
        for s in ['a=("${a[@]}" x)', 'echo "${1-}"', 'x=${y:-z}', '[ -t 1 ]', 'local a b c', 'case $x in a) ;; esac', 'printf "%s\\n" x']:
            self.assertFalse(any(re.search(rx, s) for rx, _ in BASH4), "the lint rejects: %s" % s)

    def test_the_template_passes_bash_n_and_has_no_function_keyword_or_bashisms_beyond_arrays_and_local(self):
        with open(TEMPLATE) as f:
            text = "\n".join(line for _, line in code_lines(f.read()))
        self.assertNotRegex(text, r"(?m)^\s*function\s")
        self.assertNotIn("[[", text)
        self.assertNotIn("<(", text)
        self.assertNotIn("<<<", text)


if __name__ == "__main__":
    unittest.main()
