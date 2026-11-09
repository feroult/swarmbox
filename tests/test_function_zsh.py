"""The generated function in zsh. The cases are in tests/function_cases.py.

Run: python3 tests/test_function_zsh.py
zsh runs with -f (no startup files). zsh splits no unquoted expansion, numbers arrays from 1 and treats an unmatched glob as an
error, so the template is its own file and these cases keep it honest.
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from function_cases import FunctionCases  # noqa: E402

ZSH = shutil.which("zsh")


@unittest.skipUnless(ZSH, "zsh is not installed (sudo apt-get -o APT::Sandbox::User=root install -y zsh)")
class ZshFunction(FunctionCases, unittest.TestCase):
    SHELL = [ZSH, "-f"]
    NAME = "zsh"
    STRICT = "-u"


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshSh(unittest.TestCase):
    def test_nomatch_and_ksh_arrays_do_not_break_the_function(self):
        # a user's options must not matter: KSH_ARRAYS shifts array indexes, NO_UNSET errors on unset names, and an unmatched
        # glob is an error in zsh by default; the function uses none of them
        import subprocess
        from function_cases import FunctionCases as F
        import tempfile
        base = tempfile.mkdtemp(prefix="swarmbox-test-zsh-")
        self.addCleanup(shutil.rmtree, base, True)

        class C(F, unittest.TestCase):
            SHELL = [ZSH, "-f"]
            NAME = "zsh"

            def runTest(self):
                pass
        c = C()
        c.setUp()
        self.addCleanup(c.doCleanups)
        c.fake_helper()
        script = 'setopt KSH_ARRAYS NO_UNSET SH_WORD_SPLIT; . "$1"; shift; swarmbox "$@"; exit $?'
        r = subprocess.run([ZSH, "-f", "-c", script, "zsh", c.fn, "ls", "*.nomatch", "a b"], env=c.env(), cwd=c.cwd,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(c.podman_calls(), [c.exec_call("attach", "ls", "*.nomatch", "a b")])


if __name__ == "__main__":
    unittest.main()
