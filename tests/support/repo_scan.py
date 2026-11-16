"""One walk of the repository for the guards that look at every file (no old names, no default name as a literal).

    import repo_scan
    for rel in repo_scan.repo_files(): ...        # the files that belong to the repository: tracked, or new and not ignored
    text = repo_scan.read(rel)                    # its text, or None for a binary or unreadable file; each file is read once per process

The list comes from `git ls-files` (so __pycache__, logs and other ignored files are not in it); without git (a copy of the tree) every file of
the folder is listed except the folders that start with a dot (but .github) and __pycache__.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

BINARY = (".pyc", ".png", ".gif", ".jpg", ".ico", ".woff", ".woff2", ".gz", ".tar")
_files = None
_texts = {}


def repo_files(root=ROOT):
    """Sorted relative paths of the files of the repository (computed once for ROOT)."""
    global _files
    if root == ROOT and _files is not None:
        return _files
    out = None
    try:
        r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout:
            out = sorted(set(p for p in r.stdout.decode("utf-8", "surrogateescape").split("\0") if p))
    except (OSError, subprocess.SubprocessError):
        pass
    if out is None:
        out = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            dirnames[:] = [d for d in dirnames if (not d.startswith(".") or d == ".github") and d != "__pycache__"]
            out.extend((rel_dir + "/" + f).lstrip("/") for f in filenames)
        out.sort()
    if root == ROOT:
        _files = out
    return out


def read(rel, root=ROOT):
    """The text of a file of the repository, or None when it is binary, a link, a folder or cannot be read."""
    key = (root, rel)
    if key not in _texts:
        full = os.path.join(root, rel)
        text = None
        if not rel.endswith(BINARY) and os.path.isfile(full) and not os.path.islink(full):
            try:
                with open(full, encoding="utf-8") as f:
                    text = f.read()
            except (UnicodeDecodeError, OSError):
                text = None
        _texts[key] = text
    return _texts[key]


def texts(root=ROOT):
    """{relative path: text} of every text file of the repository."""
    return {rel: t for rel in repo_files(root) for t in [read(rel, root)] if t is not None}
