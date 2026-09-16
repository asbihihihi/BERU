import asyncio
import httpx
from backend.config import get_settings


async def main():
    s = get_settings()

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{s.elevenlabs_voice_id}"

    headers = {
        "xi-api-key": s.elevenlabs_api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "text": "Halo Asbii, saya BERU. Sistem suara ElevenLabs berhasil terhubung.",
        "model_id": s.elevenlabs_model_id,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

        print("STATUS:", response.status_code)
        if not response.is_success:
            print("RESPONSE:", response.text)

        if response.is_success:
            with open("test_elevenlabs.mp3", "wb") as f:
                f.write(response.content)

            print("AUDIO:", len(response.content), "bytes")


if __name__ == "__main__":
    asyncio.run(main())