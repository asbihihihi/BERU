import httpx
from typing import Any

class OllamaClient:
    provider = "ollama"
    def __init__(self, base_url: str, model: str): self.base_url, self.model = base_url.rstrip("/"), model
    async def chat(self, messages: list[dict[str,Any]], tools: list[dict[str,Any]] | None = None) -> dict[str,Any]:
        # Gemini's opaque thought signatures are only meaningful to Gemini and
        # may be bytes, which cannot be encoded in Ollama's JSON payload.
        ollama_messages = [{key: value for key, value in message.items() if key != "thought_signature"} for message in messages]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/api/chat", json={"model":self.model,"messages":ollama_messages,"tools":tools or [],"stream":False})
            response.raise_for_status(); return response.json().get("message", {})
