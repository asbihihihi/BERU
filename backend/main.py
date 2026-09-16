import base64
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings, ROOT
from .agent.core import AgentCore
from .agent.memory import Memory
from .agent.permissions import PermissionManager
from .agent.tool_registry import ToolRegistry
from .llm.ollama_client import OllamaClient
from .tools import register_builtin_tools
from .voice.tts import ElevenLabsTTS


settings = get_settings()

registry = ToolRegistry()
register_builtin_tools(registry)

agent = AgentCore(
    OllamaClient(
        settings.ollama_base_url,
        settings.ollama_model,
    ),
    registry,
    PermissionManager(),
)

memory = Memory(ROOT / "beru_memory.db")

tts = ElevenLabsTTS(
    settings.elevenlabs_api_key,
    settings.elevenlabs_voice_id,
    settings.elevenlabs_model_id,
)


app = FastAPI(title="BERU Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "online",
        "model": settings.ollama_model,
        "tts": "elevenlabs",
        "voice_id": settings.elevenlabs_voice_id,
    }


@app.get("/tools")
async def tools():
    return registry.list()


@app.get("/memory")
async def get_memory():
    return memory.list()


@app.delete("/memory/{key}")
async def delete_memory(key: str):
    if not memory.delete(key):
        raise HTTPException(404, "Memory not found")

    return {"deleted": key}


@app.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()

    try:
        while True:
            incoming = await ws.receive_json()

            message = str(
                incoming.get("message", "")
            ).strip()

            if not message:
                continue

            async def emit(kind, data):
                # Kirim event normal ke frontend
                await ws.send_json({
                    "type": kind,
                    **data,
                })

            # Jalankan agent
            answer = await agent.run(
                message,
                emit,
                bool(incoming.get("approved", False)),
            )

            # Jika BERU menghasilkan jawaban, ubah menjadi suara
            if answer and answer.strip():
                try:
                    await emit(
                        "tts_started",
                        {"status": "generating"},
                    )

                    audio = await tts.speak(answer)

                    # Kirim audio sebagai base64 melalui WebSocket
                    audio_base64 = base64.b64encode(audio).decode("ascii")

                    await emit(
                        "tts_audio",
                        {
                            "audio": audio_base64,
                            "mime_type": "audio/mpeg",
                        },
                    )

                    await emit(
                        "tts_finished",
                        {"status": "completed"},
                    )

                except Exception as exc:
                    await emit(
                        "tts_error",
                        {
                            "message": str(exc),
                        },
                    )

    except WebSocketDisconnect:
        pass