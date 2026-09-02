"""Local text-to-speech for the assistant (§5 voice, §0.4 degradation).

The browser's `speechSynthesis` is a promise the browser may not keep. On a
Linux desktop Chromium reports zero voices and `speak()` fails silently with
`synthesis-failed`, which is exactly what happened on the machine this was
built on: the assistant "spoke" and nobody heard a thing. So, as with hearing,
the machine does it: `piper` synthesises on the CPU from a voice on disk, the
server returns a WAV, and the page plays it. Nothing leaves the machine.

Optional, like the recogniser. Install with ``make deps-tts`` (the package and a
one-time voice download into ``data/models/piper``). Without it the widget falls
back to the browser's engine where that actually has voices, and otherwise says
plainly that there is nothing to speak with.
"""

from __future__ import annotations

import io
import os
import re
import wave
from functools import lru_cache
from pathlib import Path

#: Where `make deps-tts` puts the voice. Overridable for tests and packaging.
DEFAULT_VOICE_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "piper"
#: A reply, not a chapter.
MAX_CHARS = 1_200
#: Identical sentences are common ("Opening Workbench."), so keep the audio.
CACHE_SIZE = 256
#: Voices in order of preference when more than one is on disk. CMU ARCTIC is a
#: multi-speaker voice under a permissive licence with an Indian-English male
#: speaker, `ksp`, which is the default here; a US voice sounds wrong reading
#: out CPSE names to a materials officer in Chennai.
PREFERRED_VOICES = ("en_US-arctic-medium", "en_US-libritts_r-medium")
DEFAULT_SPEAKER = "ksp"
#: Prosody. Piper's defaults are 0.667 / 0.8 / 1.0; a little more variance and a
#: touch slower reads as a person rather than a timetable announcement.
NOISE_SCALE = 0.72
NOISE_W = 0.9
LENGTH_SCALE = 1.04


def voice_dir() -> Path:
    return Path(os.environ.get("SAMAN_TTS_VOICE_DIR", str(DEFAULT_VOICE_DIR)))


def _voice_file() -> Path | None:
    directory = voice_dir()
    if not directory.exists():
        return None
    candidates = [p for p in sorted(directory.glob("*.onnx")) if Path(str(p) + ".json").exists()]
    for name in PREFERRED_VOICES:
        for path in candidates:
            if path.stem == name:
                return path
    return candidates[0] if candidates else None


def speaker_name() -> str:
    return os.environ.get("SAMAN_TTS_SPEAKER", DEFAULT_SPEAKER)


def _speaker_id() -> int | None:
    """The configured speaker's id in a multi-speaker voice, else None."""
    import json

    path = _voice_file()
    if path is None:
        return None
    config = json.loads(Path(str(path) + ".json").read_text())
    ids = config.get("speaker_id_map") or {}
    if not ids:
        return None
    return ids.get(speaker_name(), next(iter(ids.values())))


def _importable() -> bool:
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    return _importable() and _voice_file() is not None


def mode() -> str:
    return "piper" if available() else "absent"


def engine_label() -> str:
    voice = _voice_file()
    if not voice:
        return "none"
    speaker = speaker_name() if _speaker_id() is not None else None
    return f"piper, {voice.stem}" + (f", speaker {speaker}" if speaker else "")


@lru_cache(maxsize=1)
def _voice():
    from piper import PiperVoice

    path = _voice_file()
    assert path is not None
    return PiperVoice.load(str(path), config_path=str(path) + ".json")


def clean(text: str) -> str:
    """What is worth saying aloud: no markdown, no code fences, no URLs read
    letter by letter, section marks spoken as words."""
    text = re.sub(r"`([^`]*)`", r"\1", text or "")
    text = re.sub(r"https?://\S+", "a link", text)
    text = text.replace("§", "section ").replace("₹", "rupees ").replace("→", " to ")
    text = re.sub(r"[*_#>|]", " ", text)
    # Initialisms the voice would otherwise try to pronounce as words.
    def spell(letters: str):
        return lambda m: " ".join(letters) + ("s" if m.group(0).endswith("s") else "")

    text = re.sub(r"\bCPSEs?\b", spell("CPSE"), text)
    text = re.sub(r"\bCNMCs?\b", spell("CNMC"), text)
    text = re.sub(r"\bERP\b", "E R P", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS]


@lru_cache(maxsize=CACHE_SIZE)
def synthesize(text: str) -> bytes:
    """PCM WAV bytes for `text`. Raises RuntimeError when the engine is absent
    and ValueError when there is nothing to say."""
    if not available():
        raise RuntimeError("Local speech synthesis is not installed.")
    spoken = clean(text)
    if not spoken:
        raise ValueError("Nothing to say.")
    from piper import SynthesisConfig

    config = SynthesisConfig(
        speaker_id=_speaker_id(),
        noise_scale=NOISE_SCALE,
        noise_w_scale=NOISE_W,
        length_scale=LENGTH_SCALE,
    )
    chunks = list(_voice().synthesize(spoken, syn_config=config))
    if not chunks:
        raise ValueError("The voice produced no audio.")
    first = chunks[0]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(first.sample_channels)
        wav.setsampwidth(first.sample_width)
        wav.setframerate(first.sample_rate)
        for chunk in chunks:
            wav.writeframes(chunk.audio_int16_bytes)
    return buffer.getvalue()
