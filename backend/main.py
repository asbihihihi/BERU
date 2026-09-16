import base64
import json
import asyncio
import logging
from time import perf_counter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings, ROOT
from .agent.core import AgentCore
from .agent.memory import Memory
from .agent.permissions import PermissionManager
from .agent.tool_registry import ToolRegistry
from .llm.ollama_client import OllamaClient
from .llm.gemini_client import GeminiClient
from .llm.provider import FallbackLLM
from .tools import register_builtin_tools
from .voice.tts import ElevenLabsTTS
from .voice.stt import GroqWhisperSTT
from .voice.vad import VoiceRecorder, initialize_vad


settings = get_settings()
LOG = logging.getLogger("beru.api")

registry = ToolRegistry()
register_builtin_tools(registry)

ollama = OllamaClient(settings.ollama_base_url, settings.ollama_model)
if settings.llm_provider == "gemini":
    llm = FallbackLLM(GeminiClient(settings.gemini_api_key, settings.gemini_model), ollama)
elif settings.llm_provider == "ollama":
    llm = ollama
else:
    raise RuntimeError("LLM_PROVIDER harus bernilai 'gemini' atau 'ollama'.")

agent = AgentCore(
    llm,
    registry,
    PermissionManager(),
)

memory = Memory(ROOT / "beru_memory.db")

tts = ElevenLabsTTS(
    settings.elevenlabs_api_key,
    settings.elevenlabs_voice_id,
    settings.elevenlabs_model_id,
)
stt = GroqWhisperSTT(settings.groq_api_key)


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
        "provider": settings.llm_provider,
        "model": llm.model,
        "tts": "elevenlabs",
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
    # Context is intentionally scoped to this WebSocket connection and bounded
    # in AgentCore, so it is neither leaked between users nor sent indefinitely.
    conversation: list[dict] = []
    send_lock = asyncio.Lock()
    tts_tasks: set[asyncio.Task] = set()
    voice_mode = False
    voice_busy = False
    voice_recorder: VoiceRecorder | None = None

    try:
        while True:
            incoming = await ws.receive_json()

            async def emit(kind, data):
                # A lock keeps concurrent agent/TTS events ordered and avoids
                # competing WebSocket writes.
                async with send_lock:
                    await ws.send_json({"type": kind, **data})

            event_type = incoming.get("type", "chat")
            if event_type == "voice_mode":
                voice_mode = bool(incoming.get("enabled", False))
                if not voice_mode:
                    voice_busy = False
                    voice_recorder = None
                    await emit("voice_listening", {"status": False})
                    await emit("voice_recording", {"status": False})
                else:
                    await emit("voice_listening", {"status": True})
                continue

            if event_type == "voice_start":
                if not voice_mode:
                    continue
                try:
                    # Model loading is deferred until voice mode is actually used.
                    vad = await asyncio.to_thread(initialize_vad)
                    voice_recorder = VoiceRecorder(
                        vad,
                        settings.vad_threshold,
                        settings.silence_timeout,
                        settings.min_record_seconds,
                    )
                    await emit("voice_ready", {})
                    await emit("voice_listening", {"status": True})
                except Exception:
                    LOG.exception("VAD tidak dapat dimuat")
                    await emit("voice_error", {"message": "Pendeteksi suara tidak tersedia."})
                continue

            if event_type == "voice_playback_finished":
                if voice_mode:
                    voice_busy = False
                    await emit("voice_speaking", {"status": False})
                    await emit("voice_listening", {"status": True})
                continue

            if event_type == "voice_audio":
                if not voice_mode or voice_recorder is None or voice_busy:
                    continue
                try:
                    pcm = base64.b64decode(str(incoming.get("audio", "")), validate=True)
                    result = await asyncio.to_thread(voice_recorder.feed, pcm)
                except (ValueError, TypeError):
                    await emit("voice_error", {"message": "Data microphone tidak valid."})
                    continue
                except Exception:
                    LOG.exception("VAD gagal memproses audio")
                    await emit("voice_error", {"message": "Pendeteksi suara gagal."})
                    continue

                if result.recording_started:
                    await emit("voice_listening", {"status": False})
                    await emit("voice_recording", {"status": True})
                if not result.audio:
                    continue

                voice_busy = True
                await emit("voice_recording", {"status": False})
                await emit("thinking", {"status": "Mentranskripsi..."})
                try:
                    message = await stt.transcribe(result.audio)
                except Exception:
                    LOG.exception("STT gagal")
                    voice_busy = False
                    await emit("stt_error", {"message": "Maaf, saya tidak menangkap ucapanmu."})
                    if voice_mode:
                        await emit("voice_listening", {"status": True})
                    continue
                if not message:
                    voice_busy = False
                    await emit("stt_error", {"message": "Maaf, saya tidak menangkap ucapanmu."})
                    if voice_mode:
                        await emit("voice_listening", {"status": True})
                    continue
                await emit("transcript", {"text": message})
                incoming = {"message": message, "voice": True}

            message = str(
                incoming.get("message", "")
            ).strip()

            if not message:
                continue
            LOG.info("[BERU] Request received")

            async def generate_tts(text: str, is_voice: bool):
                nonlocal voice_busy
                tts_started = perf_counter()
                try:
                    if is_voice:
                        # The browser stops capture before receiving audio.
                        await emit("voice_speaking", {"status": True})
                    await emit("tts_started", {"status": "generating"})
                    audio = await tts.speak(text)
                    await emit("tts_audio", {"audio": base64.b64encode(audio).decode("ascii"), "mime_type": "audio/mpeg"})
                    await emit("tts_finished", {"status": "completed"})
                    LOG.info("[BERU] TTS: %.2fs", perf_counter() - tts_started)
                except Exception as exc:
                    LOG.warning("TTS failed (%s).", type(exc).__name__)
                    try:
                        await emit("tts_error", {"message": "TTS sedang tidak tersedia."})
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    if is_voice and voice_mode:
                        voice_busy = False
                        await emit("voice_speaking", {"status": False})
                        await emit("voice_listening", {"status": True})

            # Jalankan agent
            answer = await agent.run(
                message,
                emit,
                bool(incoming.get("approved", False)),
                conversation,
            )

            # Jika BERU menghasilkan jawaban, ubah menjadi suara
            if answer and answer.strip():
                # Text is already delivered; audio must not hold the chat loop.
                task = asyncio.create_task(generate_tts(answer, bool(incoming.get("voice", False))))
                tts_tasks.add(task)
                task.add_done_callback(tts_tasks.discard)

    except WebSocketDisconnect:
        for task in tts_tasks:
            task.cancel()
