# BERU Agent

BERU is a Windows voice assistant with a new FastAPI agent core and React command-center dashboard. The original `beru_jarvis_all.py` voice workflow is retained unchanged for compatibility: microphone → Silero VAD → Groq Whisper → Ollama → Edge TTS.

## Architecture

- `backend/agent`: orchestration, events, permissions, SQLite memory, and tool registry.
- `backend/llm`: Gemini async client, Ollama HTTP client, dan fallback provider.
- `backend/tools`: system, workspace file, terminal, web search, screenshot, app, and Playwright browser tools.
- `backend/tools/live_info.py`: data realtime untuk cuaca, sepak bola, berita, dan waktu Asia/Jakarta.
- `backend/voice`: provider interfaces, including an ElevenLabs-ready implementation.
- `frontend`: Vite React dashboard using WebSocket events.

## Run

1. Create `.env` from `.env.example`. Set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, and optionally `GEMINI_MODEL=gemini-2.5-flash`. Ollama remains configured as the automatic fallback. Set `LLM_PROVIDER=ollama` to use only the local model.
2. Install Python packages: `pip install -r requirements.txt`
3. For browser automation: `python -m playwright install chromium`
4. Start the API: `python -m uvicorn backend.main:app --reload`
5. In another terminal: `cd frontend; npm install; npm run dev`
6. Open the Vite URL, usually `http://localhost:5173`.

## Live information

- Cuaca memakai Open-Meteo forecast dan geocoding tanpa API key.
- Jadwal/hasil sepak bola memakai TheSportsDB. `SPORTS_API_KEY=123` adalah public key dengan batas cakupan/rate limit; gunakan key TheSportsDB sendiri untuk cakupan lebih luas.
- Berita memakai Google News RSS; `get_latest_news` membatasi hasil menjadi maksimal lima artikel.
- Waktu memakai zona `Asia/Jakarta`.

Run the legacy voice assistant with `python beru_jarvis_all.py`. Run tests with `pytest`.

## Voice mode in the dashboard

Start the API and dashboard as above, then open the dashboard over `http://localhost:5173` and choose **VOICE MODE: ON**. The browser asks for microphone permission once. BERU streams microphone PCM to the existing Silero VAD settings (`VAD_THRESHOLD`, `SILENCE_TIMEOUT`, and `MIN_RECORD_SECONDS`), transcribes the completed in-memory WAV with the existing Groq Whisper configuration, and sends that transcript into the same AgentCore chat session as typed messages.

The browser stops every microphone track before ElevenLabs playback and only opens it again after the audio `ended` event. No microphone audio is written to the workspace. `GROQ_API_KEY` is required for dashboard STT; ElevenLabs failures leave the text answer visible and resume voice listening.

## Safety

Tools are registered with LOW, MEDIUM, or HIGH permission. HIGH terminal commands produce a WebSocket `permission_required` event and only run after an explicit one-time UI approval. Filesystem actions are constrained to the BERU workspace. Browser automation only accesses public pages and does not bypass authentication, CAPTCHA, or security controls.

## Limitations

The dashboard supports Gemini function calling and Ollama tool calling. Browser dependencies must be installed separately. ElevenLabs is supplied as a swappable service interface, but desktop voice playback continues to use the proven Edge TTS flow until configured and connected by the caller.
