# BOBCards Voice Assistant

A real-time phone voice assistant for BOBCards / BOBCards built with FastAPI, Twilio Media Streams, Sarvam AI, Gemini, SQLite, and a live browser dashboard.

This project handles both inbound and outbound calls, streams live call audio over WebSocket, detects customer speech with server-side VAD, transcribes audio with Sarvam STT, generates guided banking replies with a hybrid rules + Gemini flow, converts replies back to speech with Sarvam TTS, and pushes the audio back into the same live call.

## What This Project Does

- Accepts Twilio voice webhooks for live calls.
- Starts outbound calls from the dashboard or API.
- Opens a bidirectional Twilio Media Stream for each active call.
- Streams the assistant greeting and every follow-up reply back into the call.
- Detects speech boundaries from incoming mu-law audio.
- Supports barge-in, so the assistant can stop playback when the customer starts speaking.
- Transcribes customer utterances with Sarvam STT.
- Runs a banking-focused conversation flow:
  - consent check
  - language selection
  - identity confirmation
  - issue capture
  - issue resolution
  - closing
- Uses a hybrid response engine:
  - deterministic issue guidance for common support cases
  - Gemini for flexible conversational replies when needed
- Tracks noisy-call conditions and falls back to shorter or safer prompts when STT quality drops.
- Stores call records, transcripts, and opt-out numbers in SQLite.
- Exposes a realtime monitoring dashboard for live conversation state, transcripts, business state, TTS/Gemini decisions, and call summary.
- Exposes a separate latency dashboard for Twilio, STT, Gemini, and TTS timing events.
- Includes WebRTC session APIs and browser-side scaffolding for a future media bridge.

## Tech Stack

- Backend: FastAPI, Uvicorn
- Telephony: Twilio Voice, Twilio Media Streams, Twilio Python SDK
- Speech-to-Text: Sarvam AI STT (`saaras:v3`), with streaming-first and REST fallback support
- Text-to-Speech: Sarvam AI TTS (`bulbul:v3`), with streaming-first and REST fallback support
- LLM: Google Gemini (`GEMINI_MODEL` configurable, example `.env` uses `gemini-2.5-flash`)
- Database: SQLite + SQLAlchemy async + `aiosqlite`
- HTTP client: `httpx`
- Frontend dashboard: static HTML, CSS, vanilla JavaScript
- Realtime browser updates: WebSocket
- Audio handling: server-side mu-law/WAV transcoding with Python audio utilities, plus `ffmpeg` in Docker image
- Deployment: Docker, Docker Compose

## High-Level Flow

1. Twilio hits `POST /api/twilio/voice` for an inbound or outbound call.
2. The app returns TwiML with `<Connect><Stream>` to `WS /api/twilio/media-stream`.
3. Twilio streams live call audio to the backend over WebSocket.
4. The backend buffers inbound mu-law frames and uses VAD to finalize utterances.
5. Finalized audio is converted to WAV and sent to Sarvam STT.
6. `ConversationService` decides the next reply using business-state logic, issue guidance, and Gemini when needed.
7. Reply text is synthesized with Sarvam TTS.
8. TTS audio is converted to Twilio-compatible audio and streamed back into the same live call.
9. Call state, transcripts, latency events, and summaries are pushed to the browser dashboard in realtime.

## Key Features

### Call handling

- Inbound call webhook support
- Outbound call initiation via `POST /api/twilio/outbound-call`
- Personalized greeting with customer name and preferred language
- Opt-out checks before continuing an automated call

### Conversation engine

- Banking-safe prompt flow
- English and Hindi support, with Hinglish-aware handling in the logic
- Rule-based issue detection for cases like:
  - Aadhaar upload
  - PAN upload
  - photo/document upload
  - OTP issues
  - login issues
  - EMI issues
  - refund, invoice, statement, address, card block, and application status queries
- Gemini fallback for broader or low-confidence conversations

### Realtime monitoring

- Live transcript feed for customer and assistant
- Realtime call phase and business-state updates
- Audio quality, fallback, interruption, Gemini, and TTS status panels
- Recent calls view
- Call summary view
- Latency monitor at `/dashboard/latency.html`

### WebRTC scaffolding

- Session creation and signaling endpoints
- Browser `RTCPeerConnection` scaffolding
- ICE candidate storage
- Prepared for future browser-to-backend media bridging

## Project Structure

```text
app/
  main.py
  api/routes/
    health.py
    twilio.py
    webrtc.py
    websocket.py
  core/
    config.py
    prompts.py
    conversation_prompts.py
    issue_guidance.py
    logging.py
  db/
    database.py
    models.py
    schemas.py
  services/
    audio_quality_service.py
    conversation_service.py
    gemini_service.py
    issue_resolution_service.py
    realtime_service.py
    sarvam_stt_service.py
    sarvam_tts_service.py
    twilio_media_stream_service.py
    twilio_service.py
    vad_service.py
    webrtc_service.py
  utils/
    helpers.py
dashboard/
data/
Dockerfile
docker-compose.yml
requirements.txt
.env.example
README.md
```

## Prerequisites

- Python 3.12+ for local development
- A Twilio account and voice-enabled phone number
- A public HTTPS URL reachable by Twilio
- A Sarvam API key
- A Gemini API key

## Environment Setup

Copy the example file:

```bash
cp .env.example .env
```

Main variables:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=

SARVAM_API_KEY=
SARVAM_STT_MODEL=saaras:v3
SARVAM_STT_USE_STREAMING=true
SARVAM_TTS_MODEL=bulbul:v3
SARVAM_TTS_VOICE=shubh

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

DATABASE_URL=sqlite:///./data/voice_agent.db
PUBLIC_URL=https://your-public-url.example
WEBRTC_ICE_SERVERS=stun:stun.l.google.com:19302
```

Notes:

- `PUBLIC_URL` is required for Twilio webhooks and Media Streams.
- The app also supports tuning for STT confidence, VAD thresholds, noisy-call fallback, and TTS cache size through `.env`.

## Run With Docker

```bash
docker compose up --build
```

App URLs:

- App: `http://localhost:8000`
- Health: `http://localhost:8000/health`
- Main dashboard: `http://localhost:8000/dashboard/`
- Latency dashboard: `http://localhost:8000/dashboard/latency.html`

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Twilio Setup

Configure your Twilio number with:

- Voice webhook: `POST {PUBLIC_URL}/api/twilio/voice`
- Status callback: `POST {PUBLIC_URL}/api/twilio/status`

The primary live-call path uses Twilio Media Streams over WebSocket through:

- `WS {PUBLIC_URL}/api/twilio/media-stream`

If you are testing locally, expose port `8000` with `ngrok`, `cloudflared`, or another HTTPS tunnel and set that URL as `PUBLIC_URL`.

## Main Endpoints

### Health and dashboard

- `GET /health`
- `GET /dashboard/`

### Twilio

- `POST /api/twilio/voice`
- `POST /api/twilio/status`
- `POST /api/twilio/outbound-call`
- `WS /api/twilio/media-stream`

### Realtime monitoring

- `WS /api/ws/realtime`

### Calls and WebRTC sessions

- `GET /api/webrtc/calls/recent`
- `GET /api/webrtc/calls/{call_sid}/conversation`
- `POST /api/webrtc/sessions`
- `GET /api/webrtc/sessions`
- `GET /api/webrtc/sessions/{session_id}`
- `POST /api/webrtc/sessions/{session_id}/offer`
- `POST /api/webrtc/sessions/{session_id}/answer`
- `POST /api/webrtc/sessions/{session_id}/ice`
- `POST /api/webrtc/sessions/{session_id}/close`

## Current Limitations

- WebRTC signaling is scaffolded, but there is no full browser audio media bridge yet.
- Twilio request signature validation is not implemented yet.
- Conversation memory is SQLite-backed and local to the app instance.
- The system is tuned for guided BOBCards support flows, not open-ended banking operations.
- Some provider integrations use fallback behavior when streaming APIs fail or return low-confidence output.

## Dashboard Overview

The browser dashboard is designed for demo and operator visibility:

- Place outbound calls with name, number, and language
- Watch live transcript updates
- Inspect business state and reply planning
- Track Gemini and TTS behavior
- See audio quality and interruption events
- Review recent calls and summaries
- Open the latency monitor for timing diagnostics
