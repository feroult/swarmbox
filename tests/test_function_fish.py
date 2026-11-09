"""The generated function in fish. The cases are in tests/function_cases.py.

Run: python3 tests/test_function_fish.py
fish runs with --no-config. Its `set -l`, `$status`, list expansion and command substitution (split on newlines) differ from
POSIX, so the template is written separately and must give the same answers as bash and zsh on every case.
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from function_cases import FunctionCases  # noqa: E402

FISH = shutil.which("fish")


@unittest.skipUnless(FISH, "fish is not installed (sudo apt-get -o APT::Sandbox::User=root install -y fish)")
class FishFunction(FunctionCases, unittest.TestCase):
    SHELL = [FISH, "--no-config"]
    NAME = "fish"
    STRICT = None


if __name__ == "__main__":
    unittest.main()
