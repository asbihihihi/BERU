import base64
import asyncio
import struct

from fastapi.testclient import TestClient
import pytest

from backend.voice.stt import GroqWhisperSTT
from backend.voice.tts import ElevenLabsTTS
from backend.voice.vad import VoiceRecorder


class FakeVAD:
    def reset_states(self):
        pass


def _pcm(samples=512):
    return struct.pack("<" + "h" * samples, *([0] * samples))


def test_vad_starts_recording_and_finishes_after_configured_silence():
    scores = iter([0.0, 0.8] + [0.0] * 40)
    recorder = VoiceRecorder(
        FakeVAD(),
        threshold=0.55,
        silence_timeout=0.085,
        min_record_seconds=0.08,
        scorer=lambda _samples: next(scores),
    )

    assert not recorder.feed(_pcm()).recording_started
    assert recorder.feed(_pcm()).recording_started
    result = None
    for _ in range(10):
        result = recorder.feed(_pcm())
        if result.audio:
            break

    assert result is not None and result.audio is not None
    assert result.audio[:4] == b"RIFF"
    assert not recorder.recording


def test_vad_does_not_finish_before_minimum_recording_time():
    recorder = VoiceRecorder(
        FakeVAD(),
        threshold=0.55,
        silence_timeout=0.032,
        min_record_seconds=0.2,
        scorer=lambda _samples: 0.9 if not recorder.recording else 0.0,
    )
    assert recorder.feed(_pcm()).recording_started
    for _ in range(5):
        assert recorder.feed(_pcm()).audio is None


def test_stt_and_tts_fail_safely_when_not_configured():
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        asyncio.run(GroqWhisperSTT("").transcribe(b"wav"))
    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(ElevenLabsTTS("", "").speak("Halo"))


def test_voice_websocket_transcript_pauses_mic_until_tts_playback_finishes(monkeypatch):
    from backend import main

    class WebVAD(FakeVAD):
        def __init__(self):
            self.calls = 0

        def __call__(self, *_args):
            self.calls += 1
            value = 0.9 if self.calls == 1 else 0.0
            return type("Score", (), {"item": lambda _self: value})()

    class FakeSTT:
        calls = 0

        async def transcribe(self, _audio):
            self.calls += 1
            return "Halo BERU"

    class FakeAgent:
        async def run(self, message, emit, *_args):
            assert message == "Halo BERU"
            await emit("message_complete", {"message": "Hai Asbii."})
            return "Hai Asbii."

    class FakeTTS:
        async def speak(self, _text):
            return b"audio"

    monkeypatch.setattr(main, "initialize_vad", lambda: WebVAD())
    monkeypatch.setattr(main, "stt", FakeSTT())
    monkeypatch.setattr(main, "agent", FakeAgent())
    monkeypatch.setattr(main, "tts", FakeTTS())

    with TestClient(main.app).websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "voice_mode", "enabled": True})
        assert ws.receive_json()["type"] == "voice_listening"
        ws.send_json({"type": "voice_start"})
        assert ws.receive_json()["type"] == "voice_ready"
        assert ws.receive_json()["type"] == "voice_listening"

        # 0.8 seconds minimum + 0.85 seconds silence at 512/16k chunks.
        chunk = base64.b64encode(_pcm()).decode("ascii")
        for _ in range(53):
            ws.send_json({"type": "voice_audio", "audio": chunk})

        events = [ws.receive_json() for _ in range(10)]
        types = [event["type"] for event in events]
        assert "transcript" in types
        assert any(event["type"] == "voice_speaking" and event["status"] for event in events)

        # Audio that arrived while STT/TTS was busy must not start a second turn.
        ws.send_json({"type": "voice_audio", "audio": chunk})
        assert main.stt.calls == 1

        ws.send_json({"type": "voice_playback_finished"})
        assert ws.receive_json() == {"type": "voice_speaking", "status": False}
        assert ws.receive_json() == {"type": "voice_listening", "status": True}


def test_voice_tts_failure_resumes_listening(monkeypatch):
    from backend import main

    class WebVAD(FakeVAD):
        def __init__(self):
            self.calls = 0

        def __call__(self, *_args):
            self.calls += 1
            value = 0.9 if self.calls == 1 else 0.0
            return type("Score", (), {"item": lambda _self: value})()

    class FakeSTT:
        async def transcribe(self, _audio):
            return "Halo BERU"

    class FakeAgent:
        async def run(self, message, emit, *_args):
            await emit("message_complete", {"message": "Hai Asbii."})
            return "Hai Asbii."

    class FailingTTS:
        async def speak(self, _text):
            raise RuntimeError("TTS offline")

    monkeypatch.setattr(main, "initialize_vad", lambda: WebVAD())
    monkeypatch.setattr(main, "stt", FakeSTT())
    monkeypatch.setattr(main, "agent", FakeAgent())
    monkeypatch.setattr(main, "tts", FailingTTS())

    with TestClient(main.app).websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "voice_mode", "enabled": True})
        ws.receive_json()
        ws.send_json({"type": "voice_start"})
        ws.receive_json()
        ws.receive_json()

        chunk = base64.b64encode(_pcm()).decode("ascii")
        for _ in range(53):
            ws.send_json({"type": "voice_audio", "audio": chunk})

        events = [ws.receive_json() for _ in range(11)]
        assert any(event["type"] == "tts_error" for event in events)
        speaking = [event for event in events if event["type"] == "voice_speaking"][-1]
        listening = [event for event in events if event["type"] == "voice_listening"][-1]
        assert speaking["status"] is False
        assert listening["status"] is True
