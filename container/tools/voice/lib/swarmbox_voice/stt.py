"""Speech to text: Whisper (whisper.cpp), through ONE function.

transcribe(wav_path, language, model, vocabulary, ...) -> text   raises SttError

This is the only place that knows about the recognizer, so replacing Whisper later is a change of this module. The audio is a
16 kHz mono 16-bit WAV (check_wav): the browser makes it, so no decoder (ffmpeg) is needed in the box.

whisper-cli is told the language explicitly: its own default is English, so "auto" is passed as `-l auto` (detection).
`--prompt` is passed only when a vocabulary is set. Only multilingual models are used, never the `.en` ones.
Paths: <tool prefix>/libexec/whisper-cli and <tool prefix>/models/ggml-<model>.bin. Tests replace the binary with
SWARMBOX_TEST_WHISPER (a fake that prints a transcript) and the models folder with SWARMBOX_TEST_MODELS.
"""
import os
import re
import struct
import subprocess

MAX_WAV_BYTES = 8 * 1024 * 1024          # about four minutes of 16 kHz mono
SAMPLE_RATE = 16000
NOISE = re.compile(r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SILENCE)\]|\((?:silence|music|noise)\)", re.I)


class SttError(RuntimeError):
    def __init__(self, code, message):
        RuntimeError.__init__(self, message)
        self.code = code
        self.message = message


def prefix():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def models_dir():
    return os.environ.get("SWARMBOX_TEST_MODELS") or os.path.join(prefix(), "models")


def whisper_bin():
    return os.environ.get("SWARMBOX_TEST_WHISPER") or os.path.join(prefix(), "libexec", "whisper-cli")


def model_path(model, folder=None):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", model or "") or model.endswith(".en"):
        raise SttError("bad_model", "the model must be a multilingual model name (never *.en)")
    return os.path.join(folder or models_dir(), "ggml-%s.bin" % model)


def check_wav(data):
    """Raise SttError unless data is a PCM WAV, 16 kHz, mono, 16-bit, with some audio in it."""
    if len(data) > MAX_WAV_BYTES:
        raise SttError("too_large", "the audio is larger than %d bytes" % MAX_WAV_BYTES)
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SttError("bad_audio", "the audio must be a WAV file")
    pos, fmt, size = 12, None, 0
    while pos + 8 <= len(data):
        cid, clen = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt " and clen >= 16:
            fmt = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            size = min(clen, len(data) - pos - 8)
            break
        pos += 8 + clen + (clen & 1)
    if fmt is None:
        raise SttError("bad_audio", "the WAV file has no fmt chunk")
    if fmt[0] != 1 or fmt[1] != 1 or fmt[2] != SAMPLE_RATE or fmt[5] != 16:
        raise SttError("bad_audio", "the WAV must be 16 kHz, mono, 16-bit PCM")
    if size <= 0:
        raise SttError("bad_audio", "the WAV file has no audio")


def clean(text):
    return " ".join(NOISE.sub(" ", text).split())


def transcribe(wav_path, language, model, vocabulary="", binary=None, models=None, timeout=180):
    exe = binary or whisper_bin()
    mpath = model_path(model, models)
    if not os.access(exe, os.X_OK):
        raise SttError("no_whisper", "whisper-cli is not installed (run `swarmbox tool install voice`)")
    if not os.path.isfile(mpath):
        raise SttError("no_model", "the model %s is missing (run `swarmbox-voice model fetch %s`)" % (model, model))
    cmd = [exe, "-m", mpath, "-f", wav_path, "-l", language or "auto", "-nt", "-np"]
    if vocabulary:
        cmd += ["--prompt", vocabulary]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    env.update({k: v for k, v in os.environ.items() if k.startswith("SWARMBOX_TEST_")})
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SttError("timeout", "the recognizer took longer than %gs" % timeout) from None
    except OSError as e:
        raise SttError("no_whisper", "cannot start whisper-cli: %s" % e) from None
    if p.returncode != 0:
        raise SttError("failed", "whisper-cli exited with %d: %s" % (p.returncode, p.stderr.decode("utf-8", "replace").strip()[-200:]))
    text = clean(p.stdout.decode("utf-8", "replace"))
    if not text:
        raise SttError("no_speech", "no speech was recognized")
    return text[:2000]
