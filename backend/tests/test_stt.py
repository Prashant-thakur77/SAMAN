"""Local speech-to-text: the audio path is exercised without a model, the model
path only where the weights are present, and the endpoint says 503 rather than
pretending when the engine is absent."""

import io
import math
import struct
import wave

import pytest

from app import stt


def _wav(samples: list[float], rate: int = 16_000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            frames = struct.pack(f"<{len(samples) * channels}h", *[
                int(max(-1, min(1, s)) * 32767) for s in samples for _ in range(channels)
            ])
        else:
            frames = struct.pack(f"<{len(samples) * channels}B", *[
                int((max(-1, min(1, s)) + 1) * 127.5) for s in samples for _ in range(channels)
            ])
        w.writeframes(frames)
    return buf.getvalue()


def _tone(seconds: float, rate: int, hz: float = 440.0) -> list[float]:
    return [0.5 * math.sin(2 * math.pi * hz * i / rate) for i in range(int(seconds * rate))]


class TestAudioPath:
    def test_decodes_16_bit_mono(self):
        samples, rate = stt.decode_wav(_wav(_tone(0.5, 16_000)))
        assert rate == 16_000
        assert len(samples) == 8_000
        assert max(samples) == pytest.approx(0.5, abs=0.01)

    def test_averages_stereo_to_mono(self):
        samples, _ = stt.decode_wav(_wav(_tone(0.1, 16_000), channels=2))
        assert len(samples) == 1_600

    def test_decodes_8_bit(self):
        samples, _ = stt.decode_wav(_wav(_tone(0.1, 8_000), rate=8_000, width=1))
        assert len(samples) == 800

    def test_resamples_to_16k(self):
        samples, rate = stt.decode_wav(_wav(_tone(1.0, 48_000), rate=48_000))
        out = stt.resample(samples, rate)
        assert len(out) == pytest.approx(16_000, abs=2)

    def test_refuses_non_wav(self):
        with pytest.raises(ValueError, match="PCM WAV"):
            stt.decode_wav(b"RIFF this is not audio")

    def test_refuses_oversize(self):
        with pytest.raises(ValueError, match="too long"):
            stt.decode_wav(b"\0" * (stt.MAX_AUDIO_BYTES + 1))


class TestAbsentEngine:
    def test_absent_without_weights(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAMAN_STT_MODEL_DIR", str(tmp_path / "nowhere"))
        assert not stt.available()
        assert stt.mode() == "absent"
        with pytest.raises(RuntimeError):
            stt.transcribe(_wav(_tone(0.5, 16_000)))

    def test_endpoint_says_503_not_nonsense(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("SAMAN_STT_MODEL_DIR", str(tmp_path / "nowhere"))
        response = client.post(
            "/api/assistant/transcribe",
            files={"audio": ("q.wav", _wav(_tone(0.5, 16_000)), "audio/wav")},
        )
        assert response.status_code == 503
        assert "make deps-stt" in response.json()["detail"]
        voice = client.get("/api/assistant/voice").json()
        assert voice["available"] is False

    def test_health_reports_the_mode(self, client):
        body = client.get("/api/health").json()
        assert body["capabilities"]["stt"]["mode"] in ("whisper", "absent")


@pytest.mark.skipif(not stt.available(), reason="local speech weights not installed")
class TestWithWeights:
    def test_silence_transcribes_to_nothing(self):
        result = stt.transcribe(_wav([0.0] * 16_000))
        assert result["text"] == ""

    def test_too_short_is_said_not_guessed(self):
        result = stt.transcribe(_wav(_tone(0.1, 16_000)))
        assert result["text"] == ""
        assert "short" in result["note"].lower()

    def test_endpoint_round_trip(self, client):
        response = client.post(
            "/api/assistant/transcribe",
            files={"audio": ("q.wav", _wav([0.0] * 16_000), "audio/wav")},
            data={"language": "en"},
        )
        assert response.status_code == 200
        assert "engine" in response.json()
