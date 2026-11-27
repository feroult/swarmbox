"""The sysop's own notes (docs/sysop-automations-design.md 5): <state>/sysop/notes/<name>.md, kept across goals, sessions and restarts.

A name is a short slug (letters, digits, - and _, at most 40); a note is at most MAX_TEXT characters; at most MAX_NOTES notes. The brain writes
them with the `note` tool; each goal's message lists them (index()), so the brain knows what it kept. + New does not remove them.
"""
import os
import re
import time

MAX_NOTES = 50
MAX_TEXT = 4000
PREVIEW = 200
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class NoteError(ValueError):
    pass


def folder(paths):
    return os.path.join(paths.state, "notes")


def check_name(name):
    n = str(name or "").strip().lower()
    if not _NAME.match(n):
        raise NoteError("a note name is a short slug: letters, digits, - and _ (at most 40), for example agy-quota")
    return n


def _file(paths, name):
    return os.path.join(folder(paths), check_name(name) + ".md")


def names(paths):
    try:
        return sorted(f[:-3] for f in os.listdir(folder(paths)) if f.endswith(".md") and _NAME.match(f[:-3]))
    except OSError:
        return []


def read(paths, name):
    try:
        with open(_file(paths, name), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise NoteError("no note %r (the notes are: %s)" % (name, ", ".join(names(paths)) or "none"))


def write(paths, name, text):
    text = str(text or "")
    if not text.strip():
        raise NoteError("text is required (delete removes a note)")
    if len(text) > MAX_TEXT:
        raise NoteError("a note is at most %d characters, this one has %d" % (MAX_TEXT, len(text)))
    n = check_name(name)
    if n not in names(paths) and len(names(paths)) >= MAX_NOTES:
        raise NoteError("there are already %d notes: delete one first" % MAX_NOTES)
    os.makedirs(folder(paths), mode=0o700, exist_ok=True)
    path = _file(paths, n)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n")
    os.replace(tmp, path)
    return n


def delete(paths, name):
    try:
        os.unlink(_file(paths, name))
    except FileNotFoundError:
        raise NoteError("no note %r" % name)


def index(paths, limit=1500):
    """The list the brain sees at each goal: name, age and a preview of each note (its lines joined, at most PREVIEW characters; a longer
    one says so, and `note read` gives it whole), or ""."""
    rows = []
    for n in names(paths):
        p = _file(paths, n)
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
            age = time.time() - os.path.getmtime(p)
        except OSError:
            continue
        flat = " / ".join(x.strip().lstrip("-* ").strip() for x in text.splitlines() if x.strip())
        more = len(flat) > PREVIEW
        rows.append("- %s (%s ago): %s%s" % (n, age_words(age), flat[:PREVIEW], " ... [more: note read %s]" % n if more else ""))
    text = "\n".join(rows)
    return text if len(text) <= limit else text[:limit - 20] + "\n- ... (more: note list)"


def age_words(sec):
    sec = int(max(0, sec))
    for unit, n in (("d", 86400), ("h", 3600), ("min", 60)):
        if sec >= n:
            return "%d %s" % (sec // n, unit)
    return "%d s" % sec

