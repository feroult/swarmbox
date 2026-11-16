"""Shared set-up of the tests that need the real image (skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works).

SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image (and does not remove it); otherwise the image is built with
dev/dev-build.sh and removed at the end. A test module imports setUpModule and tearDownModule from here and reads TAG.
"""
import os
import random
import shutil
import string
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=120, **kw):
    return subprocess.run(["podman"] + list(args), capture_output=True, timeout=timeout, **kw)


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)
