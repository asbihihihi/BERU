# BERU Agent

BERU is a Windows voice assistant with a new FastAPI agent core and React command-center dashboard. The original `beru_jarvis_all.py` voice workflow is retained unchanged for compatibility: microphone → Silero VAD → Groq Whisper → Ollama → Edge TTS.

## Architecture

- `backend/agent`: orchestration, events, permissions, SQLite memory, and tool registry.
- `backend/llm`: Ollama HTTP client.
- `backend/tools`: system, workspace file, terminal, web search, screenshot, app, and Playwright browser tools.
- `backend/voice`: provider interfaces, including an ElevenLabs-ready implementation.
- `frontend`: Vite React dashboard using WebSocket events.

## Run

1. Create `.env` from `.env.example` and configure Ollama (and optionally Groq/ElevenLabs).
2. Install Python packages: `pip install -r requirements.txt`
3. For browser automation: `python -m playwright install chromium`
4. Start the API: `python -m uvicorn backend.main:app --reload`
5. In another terminal: `cd frontend; npm install; npm run dev`
6. Open the Vite URL, usually `http://localhost:5173`.

Run the legacy voice assistant with `python beru_jarvis_all.py`. Run tests with `pytest`.

## Safety

Tools are registered with LOW, MEDIUM, or HIGH permission. HIGH terminal commands produce a WebSocket `permission_required` event and only run after an explicit one-time UI approval. Filesystem actions are constrained to the BERU workspace. Browser automation only accesses public pages and does not bypass authentication, CAPTCHA, or security controls.

## Limitations

The dashboard requires a local Ollama model supporting tool calling. Browser dependencies must be installed separately. ElevenLabs is supplied as a swappable service interface, but desktop voice playback continues to use the proven Edge TTS flow until configured and connected by the caller.
