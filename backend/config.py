from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    web_search_provider: str = "duckduckgo"
    web_search_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    workspace_root: Path = ROOT

def get_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo"),
        web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", ""),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
        elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
    )
