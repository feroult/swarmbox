"""Shared bits of the voice tests: the library import path, the fake recognizer and a WAV maker."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

VOICE = os.path.join(ROOT, "container", "tools", "voice")
sys.path.insert(0, os.path.join(VOICE, "lib"))

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "voice")

WHISPER_FAKE = os.path.join(FIXTURES, "whisper-fake")


def wav_with(text):
    """A valid 16 kHz mono 16-bit WAV whose DATA chunk is `text` (what whisper-fake reads)."""
    import struct
    data = text.encode("utf-8")
    if len(data) % 2:
        data += b" "
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


def wav_samples(samples, rate=16000):
    """A valid 16 kHz mono 16-bit WAV with these int16 samples (real audio, unlike wav_with, whose data is text)."""
    import struct
    data = struct.pack("<%dh" % len(samples), *samples)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)
