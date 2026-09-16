from abc import ABC, abstractmethod

import httpx


class TTSProvider(ABC):
    @abstractmethod
    async def speak(self, text: str) -> bytes:
        ...


class ElevenLabsTTS(TTSProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    async def speak(self, text: str) -> bytes:
        if not self.api_key or not self.voice_id:
            raise RuntimeError(
                "ElevenLabs is not configured"
            )

        url = (
            "https://api.elevenlabs.io/v1/"
            f"text-to-speech/{self.voice_id}"
        )

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "text": text,
            "model_id": self.model_id,
        }

        timeout = httpx.Timeout(
            connect=20.0,
            read=120.0,
            write=20.0,
            pool=20.0,
        )

        async with httpx.AsyncClient(
            timeout=timeout
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

            if not response.is_success:
                try:
                    detail = response.json()
                except Exception:
                    detail = response.text

                raise RuntimeError(
                    f"ElevenLabs HTTP {response.status_code}: "
                    f"{detail}"
                )

            return response.content