"""Local speech-to-text for the assistant (§5 voice, §0.4 degradation).

The browser's own recogniser is the wrong tool for this system: in Chrome it
sends the audio to Google, which breaks the one guarantee SAMAN makes about
data, and Firefox has none at all. So the assistant records raw audio in the
page and posts it here, where `faster-whisper` transcribes it on the CPU with
weights that live on disk. Nothing leaves the machine.

Optional, like the OCR reader. Without the package or the weights,
`available()` is False, `/api/health` says so, and the widget falls back to the
browser engine where one exists, or hides the microphone.

Install: ``make deps-stt`` (the package and a one-time weight download into
``data/models/whisper-base``, about 140 MB). At runtime the model is loaded
from that directory only; a missing directory is "absent", never a download.
"""

from __future__ import annotations

import io
import math
import os
import struct
import wave
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Where `make deps-stt` puts the weights. Overridable for tests and packaging.
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "whisper-base"
#: Whisper expects 16 kHz mono; the browser is asked for it but not trusted.
TARGET_RATE = 16_000
#: An utterance, not a meeting. 5 MB is about two and a half minutes at 16 kHz.
MAX_AUDIO_BYTES = 5 * 1024 * 1024
#: Below this many samples there is nothing to transcribe (0.3 s).
MIN_SAMPLES = int(0.3 * TARGET_RATE)
#: Languages the widget offers; Whisper detects if none is named.
LANGUAGES = ("en", "hi")


def model_dir() -> Path:
    return Path(os.environ.get("SAMAN_STT_MODEL_DIR", str(DEFAULT_MODEL_DIR)))


def _importable() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    """The package is installed and the weights are on disk."""
    return _importable() and (model_dir() / "model.bin").exists()


def mode() -> str:
    return "whisper" if available() else "absent"


def engine_label() -> str:
    return f"faster-whisper base, int8, {model_dir().name}" if available() else "none"


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    # int8 on CPU: the base model transcribes a five-second utterance in well
    # under a second on a laptop core, which is the only budget that matters
    # for a widget somebody is waiting on.
    return WhisperModel(str(model_dir()), device="cpu", compute_type="int8")


def decode_wav(payload: bytes) -> tuple[list[float], int]:
    """PCM WAV bytes -> mono float samples in [-1, 1] and their sample rate.

    Accepts 8/16/32-bit integer PCM and any channel count; averages channels.
    Raises ValueError for anything else, with a reason the UI can show.
    """
    if len(payload) > MAX_AUDIO_BYTES:
        raise ValueError("That recording is too long. Keep it to one question.")
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError("The audio was not a PCM WAV file.") from exc
    if width not in (1, 2, 4):
        raise ValueError(f"Unsupported sample width: {width} bytes.")
    count = len(frames) // width
    if width == 1:
        ints = struct.unpack(f"<{count}B", frames)
        samples = [(v - 128) / 128.0 for v in ints]
    elif width == 2:
        ints = struct.unpack(f"<{count}h", frames)
        samples = [v / 32768.0 for v in ints]
    else:
        ints = struct.unpack(f"<{count}i", frames)
        samples = [v / 2147483648.0 for v in ints]
    if channels > 1:
        samples = [
            sum(samples[i : i + channels]) / channels
            for i in range(0, len(samples) - channels + 1, channels)
        ]
    return samples, rate


def resample(samples: list[float], rate: int, target: int = TARGET_RATE) -> list[float]:
    """Linear resampling. Adequate for speech going into a model that was
    trained on far worse; not for anything that has to sound good."""
    if rate == target or not samples:
        return samples
    ratio = rate / target
    out_len = int(math.floor(len(samples) / ratio))
    out = []
    for i in range(out_len):
        pos = i * ratio
        lo = int(pos)
        hi = min(lo + 1, len(samples) - 1)
        frac = pos - lo
        out.append(samples[lo] * (1 - frac) + samples[hi] * frac)
    return out


def transcribe(payload: bytes, language: str | None = None) -> dict[str, Any]:
    """Transcribe one WAV utterance. Raises ValueError for bad audio, and
    RuntimeError if the engine is absent (callers check `available()` first)."""
    if not available():
        raise RuntimeError("Local speech recognition is not installed.")
    samples, rate = decode_wav(payload)
    samples = resample(samples, rate)
    if len(samples) < MIN_SAMPLES:
        return {"text": "", "language": language, "duration": len(samples) / TARGET_RATE,
                "note": "Too short to contain a word."}

    import numpy as np

    audio = np.asarray(samples, dtype=np.float32)
    lang = language if language in LANGUAGES else None
    segments, info = _model().transcribe(
        audio,
        language=lang,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    pieces = []
    logprobs = []
    for segment in segments:
        pieces.append(segment.text.strip())
        logprobs.append(segment.avg_logprob)
    text = " ".join(p for p in pieces if p).strip()
    confidence = round(math.exp(sum(logprobs) / len(logprobs)), 3) if logprobs else 0.0
    return {
        "text": text,
        "language": getattr(info, "language", lang),
        "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
        "duration": round(len(samples) / TARGET_RATE, 2),
        "confidence": confidence,
        "engine": engine_label(),
    }
