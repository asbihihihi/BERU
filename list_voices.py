import asyncio
import httpx
from backend.config import get_settings


async def main():
    s = get_settings()

    headers = {
        "xi-api-key": s.elevenlabs_api_key,
    }

    params = {
        "page_size": 100,
        "include_total_count": True,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            "https://api.elevenlabs.io/v2/voices",
            headers=headers,
            params=params,
        )

        print("STATUS:", response.status_code)

        if not response.is_success:
            print(response.text)
            return

        data = response.json()

        print("TOTAL:", data.get("total_count"))
        print("=" * 80)

        for voice in data.get("voices", []):
            labels = voice.get("labels") or {}

            print(
                f"NAME       : {voice.get('name')}\n"
                f"VOICE ID   : {voice.get('voice_id')}\n"
                f"TYPE       : {voice.get('voice_type', '-')}\n"
                f"CATEGORY   : {voice.get('category', '-')}\n"
                f"GENDER     : {labels.get('gender', '-')}\n"
                f"AGE        : {labels.get('age', '-')}\n"
                f"ACCENT     : {labels.get('accent', '-')}\n"
                f"LANGUAGE   : {labels.get('language', '-')}\n"
                f"DESCRIPTION: {voice.get('description', '-')}\n"
                f"AVAILABLE  : {voice.get('available_for_tiers', '-')}\n"
            )

            print("-" * 80)


if __name__ == "__main__":
    asyncio.run(main())