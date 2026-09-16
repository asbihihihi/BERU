"""Speech-to-text providers used by both BERU voice entry points."""

from abc import ABC, abstractmethod
import io

import httpx


GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
INDONESIAN_STT_PROMPT = (
    "Bahasa Indonesia. BERU. Perintah komputer: buka tutup jalankan cuaca "
    "waktu cmd powershell chrome edge firefox steam photoshop vscode visual "
    "studio code task manager file explorer phone link calculator youtube "
    "google github ping ipconfig python php laravel composer npm git."
)


class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str: ...


class GroqWhisperSTT(STTProvider):
    """The existing Groq Whisper configuration, exposed for the web voice loop."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def transcribe(self, audio: bytes) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY belum dikonfigurasi")
        if not audio:
            return ""

        files = {"file": ("beru_input.wav", io.BytesIO(audio), "audio/wav")}
        data = {
            "model": "whisper-large-v3",
            "language": "id",
            "prompt": INDONESIAN_STT_PROMPT,
        }
        timeout = httpx.Timeout(connect=20.0, read=30.0, write=20.0, pool=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                GROQ_TRANSCRIPTIONS_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
            )
        if not response.is_success:
            raise RuntimeError(f"Groq STT HTTP {response.status_code}")
        return str(response.json().get("text", "")).strip()
