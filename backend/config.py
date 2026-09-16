from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    web_search_provider: str = "duckduckgo"
    web_search_api_key: str = ""
    default_location: str = "Purwokerto"
    default_latitude: float = -7.4242
    default_longitude: float = 109.2396
    sports_api_key: str = "123"
    sports_api_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    groq_api_key: str = ""
    microphone_device: str = ""
    vad_threshold: float = 0.55
    silence_timeout: float = 0.85
    min_record_seconds: float = 0.8
    workspace_root: Path = ROOT

def get_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "gemini").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434")),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo"),
        web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", ""),
        default_location=os.getenv("DEFAULT_LOCATION", "Purwokerto"),
        default_latitude=float(os.getenv("DEFAULT_LATITUDE", "-7.4242")),
        default_longitude=float(os.getenv("DEFAULT_LONGITUDE", "109.2396")),
        sports_api_key=os.getenv("SPORTS_API_KEY", "123"),
        sports_api_base_url=os.getenv("SPORTS_API_BASE_URL", "https://www.thesportsdb.com/api/v1/json").rstrip("/"),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv("ELEVENLABS_VOICE_ID", ""),
        elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        microphone_device=os.getenv("MICROPHONE_DEVICE", "").strip(),
        vad_threshold=float(os.getenv("VAD_THRESHOLD", "0.55")),
        silence_timeout=float(os.getenv("SILENCE_TIMEOUT", "0.85")),
        min_record_seconds=float(os.getenv("MIN_RECORD_SECONDS", "0.8")),
    )
