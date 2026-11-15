"""Speech to text: Whisper (whisper.cpp), through ONE function.

transcribe(wav_path, language, model, vocabulary, ...) -> text   raises SttError

This is the only place that knows about the recognizer, so replacing Whisper later is a change of this module. The audio is a
16 kHz mono 16-bit WAV (check_wav): the browser makes it, so no decoder (ffmpeg) is needed in the box.

whisper-cli is told the language explicitly: its own default is English, so "auto" is passed as `-l auto` (detection).
`--prompt` is passed only when a vocabulary is set. Only multilingual models are used, never the `.en` ones.
Paths: <tool prefix>/libexec/whisper-cli and <tool prefix>/models/ggml-<model>.bin. Tests replace the binary with
SWARMBOX_TEST_WHISPER (a fake that prints a transcript) and the models folder with SWARMBOX_TEST_MODELS.
"""
import array
import math
import os
import re
import struct
import subprocess
import sys

MAX_WAV_BYTES = 8 * 1024 * 1024          # about four minutes of 16 kHz mono
SAMPLE_RATE = 16000
# what Whisper writes for a sound that is not speech, in the language it was asked for: [BLANK_AUDIO], [MUSIC], (water running), [Som de fio], [MUSICA DE FUNDO]. A short
# bracketed or parenthesized note is never what the person said; speech comes out of Whisper without brackets.
NOISE = re.compile(r"\[[^\[\]]{1,60}\]|\([^()]{1,60}\)")
MIN_RMS = 120        # of 32768: a recording whose loudest 100 ms is quieter than this has no speech in it (speech is some 500 to 3000; noise-suppressed silence is under 30)
WINDOW = 1600        # 100 ms at 16 kHz
STEP = 800


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


def _parse(data):
    """(fmt, start, size) of a WAV: the fmt chunk fields, and where the samples are in `data` and how many bytes (the declared size, cut at the end of the data)"""
    if len(data) > MAX_WAV_BYTES:
        raise SttError("too_large", "the audio is larger than %d bytes" % MAX_WAV_BYTES)
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SttError("bad_audio", "the audio must be a WAV file")
    pos, fmt, start, size = 12, None, 0, 0
    while pos + 8 <= len(data):
        cid, clen = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt " and clen >= 16:
            fmt = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
        elif cid == b"data":
            start, size = pos + 8, min(clen, len(data) - pos - 8)
            break
        pos += 8 + clen + (clen & 1)
    return fmt, start, size


def check_wav(data):
    """Raise SttError unless data is a PCM WAV, 16 kHz, mono, 16-bit, with some audio in it."""
    fmt, _, size = _parse(data)
    if fmt is None:
        raise SttError("bad_audio", "the WAV file has no fmt chunk")
    if fmt[0] != 1 or fmt[1] != 1 or fmt[2] != SAMPLE_RATE or fmt[5] != 16:
        raise SttError("bad_audio", "the WAV must be 16 kHz, mono, 16-bit PCM")
    if size <= 0:
        raise SttError("bad_audio", "the WAV file has no audio")


def loudest(data):
    """The RMS (of 32768) of the loudest 100 ms of a checked WAV, or of the whole clip when it is shorter than that."""
    _, start, size = _parse(data)
    n = size // 2
    if n <= 0:
        return 0.0
    # Constant memory: the energy of each STEP block (an array of n / STEP numbers, not of n samples), a window is the sum of its blocks.
    # A clip shorter than a window is one window. (A window is a whole number of blocks: WINDOW is 2 * STEP.)
    def energy(lo, hi):
        part = array.array("h")
        part.frombytes(data[start + lo * 2:start + hi * 2])
        if sys.byteorder == "big":
            part.byteswap()
        return sum(x * x for x in part)
    win = min(WINDOW, n)
    if win < WINDOW:
        best = energy(0, n)
    else:
        blocks = [energy(i, i + STEP) for i in range(0, n - STEP + 1, STEP)]
        per = WINDOW // STEP
        best = max(sum(blocks[k:k + per]) for k in range(0, (n - WINDOW) // STEP + 1))
    return math.sqrt(best / win)


def check_speech(data):
    """Raise no_speech when the recording has no sound in it. Whisper does not say 'nothing': given silence or a little noise it writes a word of its own
    ('you', a bracketed note such as [MUSICA DE FUNDO], 'Thank you.'), and that would become a goal on the bus. The page and the microphone are not trusted to send
    only speech (a button pressed and released, a muted or noise-suppressed microphone), so the quiet recording is stopped here, before the recognizer."""
    if loudest(data) < MIN_RMS:
        raise SttError("no_speech", "the recording has no sound in it")


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
