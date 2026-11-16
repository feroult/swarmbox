"""The multilingual Whisper models the addon can fetch, pinned: Hugging Face revision, size and SHA-256 of each file.

Only multilingual files (ggml-<name>.bin) are listed: the `.en` ones know only English and are never offered. fetch() downloads to
a temporary file in the models folder, verifies the SHA-256 and only then renames it, so a half or wrong download is never used.
The same table is mirrored in install.sh (which fetches the default model at install); a test keeps the two equal.
"""
import hashlib
import os
import urllib.request

REVISION = "5359861c739e955e79d9a303bcbc70fb988958b1"
URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/%s/ggml-%s.bin"
MODELS = {   # name: (bytes, sha256)
    "tiny": (77691713, "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21"),
    "base": (147951465, "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"),
    "small": (487601967, "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"),
    "medium": (1533763059, "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"),
    "large-v3": (3095033483, "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"),
    "large-v3-turbo": (1624555275, "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"),
}


class ModelError(RuntimeError):
    pass


def installed(folder):
    return sorted(n for n in MODELS if os.path.isfile(os.path.join(folder, "ggml-%s.bin" % n)))


def fetch(name, folder, opener=urllib.request.urlopen, progress=None):
    """Download model `name` into folder (verified). Returns the path. Raises ModelError."""
    if name not in MODELS:
        raise ModelError("unknown model %r; known: %s (multilingual only, never *.en)" % (name, ", ".join(MODELS)))
    size, want = MODELS[name]
    final = os.path.join(folder, "ggml-%s.bin" % name)
    os.makedirs(folder, exist_ok=True)
    tmp = final + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with opener(URL % (REVISION, name), timeout=60) as src, open(tmp, "wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done > size:
                    raise ModelError("the download of %s is larger than expected" % name)
                if progress:
                    progress(done, size)
        if h.hexdigest() != want:
            raise ModelError("checksum mismatch for %s: expected %s, got %s. Nothing was installed." % (name, want, h.hexdigest()))
        os.replace(tmp, final)
    except OSError as e:
        raise ModelError("cannot download %s: %s" % (name, e)) from None
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return final
