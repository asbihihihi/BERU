import httpx
from typing import Any

class OllamaClient:
    def __init__(self, base_url: str, model: str): self.base_url, self.model = base_url.rstrip("/"), model
    async def chat(self, messages: list[dict[str,Any]], tools: list[dict[str,Any]] | None = None) -> dict[str,Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/api/chat", json={"model":self.model,"messages":messages,"tools":tools or [],"stream":False})
            response.raise_for_status(); return response.json().get("message", {})
