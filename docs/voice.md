# Server-side voice gateway (STT/TTS)

## Why

Browser speech (Web Speech API) is convenient but Chrome/Edge-centric and depends on the
vendor. Production voice uses a server-side provider abstraction.

## Provider abstraction

`app/modules/voice/provider.py`:

- `SpeechProvider` protocol: `transcribe(...) -> str`, `synthesize(...) -> SynthesizedSpeech`
- `OpenAISpeechProvider`: OpenAI-compatible
  - `POST {base}/audio/transcriptions` (Whisper-style)
  - `POST {base}/audio/speech` (TTS, mp3)
- `build_speech_provider(settings)`: **None when no key**, so voice is cleanly unavailable.

Add another vendor by implementing the protocol; routers do not change.

## Endpoints

Both require a valid Keycloak bearer token for a staff or customer principal.

| Endpoint | Body | Response |
|---|---|---|
| `POST /api/v1/voice/transcribe` | multipart `file` (audio/webm, wav, mpeg, mp4, ogg) | `{ "text": "..." }` |
| `POST /api/v1/voice/speak` | `{ "text": "..." }` (≤2000 chars) | `audio/mpeg` |

Controls:

- upload limit `CRM_VOICE_MAX_UPLOAD_BYTES` (default 10 MiB);
- unsupported/empty/oversized audio → **503 `voice_unavailable`**;
- TTS text is passed through the assistant **output guardrail** before synthesis;
- `Cache-Control: no-store` on audio;
- audio is processed in memory and not stored.

## Configuration

```dotenv
CRM_VOICE_ENABLED=true
CRM_VOICE_API_KEY=...
CRM_VOICE_BASE_URL=https://api.openai.com/v1
CRM_VOICE_STT_MODEL=gpt-4o-mini-transcribe
CRM_VOICE_TTS_MODEL=gpt-4o-mini-tts
CRM_VOICE_TTS_VOICE=alloy
```

Without `CRM_VOICE_API_KEY`, both endpoints return 503 and the portal keeps its browser
speech controls.

## Tests

`backend/tests/test_voice_provider.py` — transcription request/response, TTS bytes, vendor
failure mapping, provider absent without key. Uses `httpx.MockTransport`; no paid calls.

## Current UI integration

The portal assistant and ticket reply dictation currently use **browser speech**. Wiring the
UI to these server endpoints (MediaRecorder upload + audio playback) is the remaining step;
until then the server gateway is available to API clients and voice-enabled frontends but is
not the default UI path.

## ElevenLabs adapter

Set:
`dotenv
CRM_VOICE_PROVIDER=elevenlabs
CRM_VOICE_API_KEY=... # xi-api-key
CRM_VOICE_BASE_URL=https://api.elevenlabs.io/v1
CRM_VOICE_STT_MODEL=scribe_v1
CRM_VOICE_TTS_MODEL=eleven_multilingual_v2
CRM_VOICE_TTS_VOICE=<voice_id>
``nSTT calls /v1/speech-to-text; TTS calls /v1/text-to-speech/{voice_id}.

