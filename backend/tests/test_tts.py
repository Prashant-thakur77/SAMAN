"""Local text-to-speech: the text is cleaned before it is spoken, the endpoint
says 503 rather than pretending when the engine is absent, and with a voice on
disk the WAV that comes back actually contains sound."""

import io
import struct
import wave

import pytest

from app import tts


class TestCleaning:
    def test_markup_and_links_are_not_read_aloud(self):
        spoken = tts.clean("Open `/workbench` — see https://example.com/x **now** §0.9b ₹19.3 Cr")
        assert "`" not in spoken and "**" not in spoken and "https://" not in spoken
        assert "section 0.9b" in spoken and "rupees" in spoken

    def test_length_is_bounded(self):
        assert len(tts.clean("word " * 2000)) <= tts.MAX_CHARS


class TestAbsentEngine:
    def test_absent_without_a_voice(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SAMAN_TTS_VOICE_DIR", str(tmp_path / "nowhere"))
        assert not tts.available()
        assert tts.mode() == "absent"
        tts.synthesize.cache_clear()
        with pytest.raises(RuntimeError):
            tts.synthesize("hello")

    def test_endpoint_says_503(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("SAMAN_TTS_VOICE_DIR", str(tmp_path / "nowhere"))
        response = client.post("/api/assistant/speak", json={"text": "hello"})
        assert response.status_code == 503
        assert "make deps-tts" in response.json()["detail"]
        voice = client.get("/api/assistant/voice").json()
        assert voice["tts"]["available"] is False

    def test_health_reports_the_mode(self, client):
        body = client.get("/api/health").json()
        assert body["capabilities"]["tts"]["mode"] in ("piper", "absent")


@pytest.mark.skipif(not tts.available(), reason="local voice not installed")
class TestWithVoice:
    def test_the_wav_contains_sound(self):
        tts.synthesize.cache_clear()
        audio = tts.synthesize("Opening the workbench.")
        with wave.open(io.BytesIO(audio), "rb") as wav:
            assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
            frames = wav.readframes(wav.getnframes())
            assert wav.getnframes() / wav.getframerate() > 0.8
        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        assert max(abs(s) for s in samples) > 3000, "a silent file is not speech"

    def test_endpoint_round_trip(self, client):
        response = client.post("/api/assistant/speak", json={"text": "Opening Workbench."})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/wav")
        assert response.content[:4] == b"RIFF"

    def test_nothing_to_say_is_a_400(self, client):
        response = client.post("/api/assistant/speak", json={"text": "```"})
        assert response.status_code == 400
