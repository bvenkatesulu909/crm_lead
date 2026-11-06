# ADR 0023 — Live voice mode for the staff AI Assistant (Phase 20c)

- **Status:** Proposed (2026-11-06) — nothing is built until the owner answers section 8
- **Date:** 2026-11-06
- **Deciders:** Project owner
- **Depends on:** ADR 0003 (AI assistant foundations), ADR 0014 (approval queue), ADR 0016 (agent registry,
  budgets, kill switch), ADR 0017/0018 (Sentinel, input screening, cleaning what the AI says), ADR 0021
  (one-server deployment)
- **Marked [ADR] because** it adds a streaming answer endpoint, stored conversation turns (a new tenant
  table) and possibly a new outside data processor (a speech vendor).

## 1. What the owner wants, in plain words

"Voice mode like ChatGPT": the person presses **one** button, speaks, **hears** the answer, and keeps talking
turn after turn without touching the keyboard — the way you talk to someone on the phone.

## 2. What exists today (read from the code, 2026-11-06)

| Piece | What it does | Gap for a conversation |
|---|---|---|
| `frontend/src/components/voice-recorder.tsx` | "Mic Speak question": records up to 60 s with `MediaRecorder`, sends it to `/api/voice/transcribe`; on 503 it falls back to the browser's own `SpeechRecognition` (Web Speech API). Then the form is submitted automatically. | One question per press. The person must press **Stop** (no "you stopped talking" detection). |
| `frontend/src/app/api/voice/transcribe/route.ts`, `.../voice/speak/route.ts` | Next.js route handlers: read the encrypted `crm_session` cookie on the server and call the API with the token. The browser never sees the token. | Fine — keep this pattern. |
| `backend/app/modules/voice/` (`POST /api/v1/voice/transcribe`, `POST /api/v1/voice/speak`) | Speech-to-text and text-to-speech through a `SpeechProvider`: `openai` (OpenAI-compatible audio API), `elevenlabs`, or `local` (faster-whisper + Piper on the server). Settings `voice_*` in `backend/app/core/config.py`; `voice_api_key` from the environment only. | **On staging it answers 503**: no `CRM_VOICE_API_KEY` is set and `local` is not installed. Not metered by the agent registry, no budget, no switch. |
| `frontend/src/components/speak-button.tsx` | "Speak" button on an answer: server speech, on 503 the browser's `speechSynthesis`. | Speaks only when pressed, and only the **whole** answer after it is finished. |
| `POST /api/v1/assistant/ask` (`staff_router.py`) | One question in, one complete answer out (JSON), up to tool rounds, proposals only (ADR 0014), governed by the registry (`staff_assistant`). | **No memory**: every question starts from zero, so "and what about the second one?" cannot work. **No streaming**: nothing can be spoken until the whole answer is ready. |

Two small findings, not fixed here: `voice/provider.py` says "(ADR 0012)", but ADR 0012 is the Communication
Center — voice never had its own ADR; and the consent text "Audio is processed by the speech service and not
stored" is not quite true in the browser fallback (there the **browser vendor** processes it).

## 3. Where the waiting time comes from (be honest about this first)

A spoken turn has five parts. Rough figures, to be **measured** in step VM5 (they are estimates, not test results):

| Part | Browser speech (a) | Server speech (b) | Realtime model (c) |
|---|---|---|---|
| Noticing the person has stopped talking | 0.5–1 s | 0.5–1 s (needs silence detection, VM4) | 0.3–0.6 s (built in) |
| Speech → text | 0.2–1 s | 1–2 s (upload + transcribe one clip) | — (the model hears audio) |
| **The model thinks and writes the answer** | **10–15 s today** (free OpenRouter models, whole answer) | same | 0.3–1 s to the first sound |
| Tool rounds (e.g. "look up the ticket") | each round is one more full model call | same | the model calls tools itself; still one server round each |
| Text → first sound | ~0 s (on the device) | 0.3–1 s per sentence | — |

**So the delay a person feels is mostly the model**, not the speech. With today's free models a person waits
10–15 s of silence after each sentence — that will never feel like a conversation, whichever speech engine
we pick. What actually helps, in order of effect:

1. **Stream the answer and speak the first sentence as soon as it exists.** The person then waits for the
   *first sentence* (often 2–5 s on a free model, under 1–2 s on a fast paid one), not for the whole answer.
   The rest is spoken while it is still being written.
2. **A faster model for voice.** Free OpenRouter models are queued behind other users and are slow to start.
   A fast paid model (a small "flash"/"mini"-class model) typically starts answering in about 0.5–1.5 s.
   This is a cost decision for the owner (question 3).
3. **Say something at once while tools run.** A fixed sentence written by us, not the model — e.g.
   "One moment, I'm looking that up." — spoken the moment the model asks for a tool. Silence feels much
   longer than the same time with a voice.
4. **Short answers for voice.** The voice prompt asks for 1–3 spoken sentences, no tables or lists; the full
   answer (with links and proposals) still appears on screen.
5. **Fewer tool rounds** (send the open ticket's summary in the prompt instead of a tool call) — later tuning.

A realtime speech-to-speech model (c) is the only option that gets under 1 s, because one model hears and
speaks directly — but section 5 explains why it does not fit our safety rules yet.

## 4. The three options compared

Costs are **approximate list prices as I know them (mid-2026), not checked today** — re-check on the vendors'
price pages before deciding. "One minute of conversation" is assumed to be ~30 s of the person talking and
~30 s of the assistant talking (about 75 spoken words), with 2–3 model calls.

### (a) Browser-only speech — Web Speech API to listen, `speechSynthesis` to speak

- **Cost per minute:** $0 for speech. The model is the only cost (free OpenRouter today; a paid small model
  is roughly $0.002–0.005 per minute of conversation).
- **Delay felt:** speech adds almost nothing; the model decides (section 3).
- **Browsers and phones:** listening works in **Chrome** (desktop and Android) and **Safari** (Mac, iPhone,
  iPad; on iPhone every browser is Safari underneath). **Edge** has it but it is unreliable. **Firefox: no
  listening.** Speaking (`speechSynthesis`) works everywhere, but the voices differ per device and some sound
  robotic. iPhones allow sound only after a tap, so the loop must start from the one button press. Some
  browsers stop listening after a few seconds of silence — the loop must restart it.
- **Privacy:** in Chrome the **audio goes from the person's browser straight to Google**; in Safari to Apple;
  in Edge to Microsoft. The CRM never sees the audio, cannot choose the vendor, has no contract with them and
  cannot switch it off per organisation except by hiding the button. The *text* then goes to the CRM and to
  the AI model, as today. Speaking is usually done on the device (no audio leaves), but some Chrome voices
  are online.
- **Fits the rules?** Yes: the question still goes through the existing route handler → `POST /assistant/...`
  with the cookie (no token in the browser), the registry, guardrails, Sentinel and approval queue. The only
  thing outside our control is *who hears the audio*.

### (b) A speech service on the server — paid speech-to-text + text-to-speech (what `voice/` already supports)

- **Cost per minute:** with OpenAI's small audio models about $0.003/min to transcribe and about $0.015/min of
  speech produced → roughly **$0.01 per minute of conversation**, plus the model ($0–0.005). ElevenLabs or
  Deepgram are similar or higher for nicer voices. The `local` provider (faster-whisper + Piper on our own
  server) costs $0 to a vendor, but on the staging VM (e2-medium, 2 small CPUs) transcribing takes several
  seconds per sentence and slows the API for everyone — not recommended there.
- **Delay felt:** 1–2 s more than (a) for listening (a whole clip is uploaded, then transcribed) and
  0.3–1 s per spoken sentence; streaming services can bring this down later.
- **Browsers and phones:** **every** modern browser, Firefox included, because only `getUserMedia` and audio
  playback are needed. Recording format differs (Chrome `webm`, Safari `mp4`) — the API already accepts both.
- **Privacy:** audio goes **browser → our Next.js server → our API → one vendor the owner chose**, under that
  vendor's API terms (OpenAI's API terms say audio sent through the API is not used for training by default;
  the owner should read them). Nothing is stored by the CRM. With `local`, no audio leaves our server at all.
  This is the option to use **before real customers' data is spoken** ("go live").
- **Fits the rules?** Best of the three: the key stays in an environment variable on the server, the API
  can meter seconds of audio against a registry budget and refuse when the switch is off, and every spoken
  sentence is cleaned before it is turned into sound.

### (c) A realtime speech-to-speech model (e.g. OpenAI Realtime, Google Gemini Live)

- **Cost per minute:** OpenAI's realtime model roughly **$0.05–0.10 per minute** (audio out is the expensive
  part, and the whole conversation is billed again each turn); the "mini" version about a third of that;
  Gemini Live roughly $0.01–0.03. Pricing is per audio token and hard to predict.
- **Delay felt:** the best — about 0.5–1 s, and the person can interrupt naturally.
- **Browsers and phones:** all modern browsers via WebRTC or a WebSocket.
- **Privacy:** the audio **and the CRM data the tools return** go to the realtime vendor. It must be a vendor
  the owner accepts for customer data.
- **Fits the rules? Not yet, for four reasons:**
  1. **Tokens in the browser.** The usual setup gives the browser a short-lived vendor key so it can talk to
     the vendor directly. That is a token in the browser, against our rule. The alternative — our server
     relays the audio — needs a WebSocket on the API host plus a new sign-in ticket for it (the browser has
     no CRM token, and Netlify functions cannot hold a WebSocket open). That is a new auth pattern.
  2. **We cannot clean what it says before it is heard.** ADR 0018 removes links and images from AI answers
     before anyone sees them. A realtime model produces the sound itself; we only get the transcript after
     the person has already heard it.
  3. **Budgets and the kill switch** need the server in the middle to count tokens and stop a session.
  4. **Our model setup does not apply.** The registry, the evaluation harness (BP-10) and the OpenRouter
     fallbacks are all built on text models; a realtime model is a different model with different behaviour
     and would need its own evaluation cases.
  Its tool calls *could* still go through our server (the same staff tools, as the person, proposals only),
  so it is possible later — but it is its own project with its own ADR.

### Summary

| | (a) Browser | (b) Server speech | (c) Realtime |
|---|---|---|---|
| Speech cost / min | $0 | ~$0.01 ($0 with `local`) | ~$0.01–0.10 |
| Delay that speech adds | ~0.5–1 s | ~1.5–3 s | ~0.5–1 s in total |
| Firefox | no listening | yes | yes |
| Who hears the audio | Google / Apple / Microsoft, not chosen by us | the one vendor the owner chose (or nobody, `local`) | the realtime vendor, plus CRM data |
| Token stays on the server | yes | yes | needs a new relay |
| Budget + kill switch | model only | model + audio minutes | needs a new relay |
| Answer cleaned before heard | yes | yes | **no** |
| Fits today's rules | yes | yes | not without new design |

## 5. Decision (proposed)

Build **one voice mode with two interchangeable speech engines**, and fix the real cause of the delay
(no streaming, no memory) first:

1. **Streaming answers with memory come first (VM1)** — they help the typed assistant too:
   - a new endpoint `POST /api/v1/assistant/conversations/{id}/turns` that answers as a stream of
     sentences (Server-Sent Events) through a Next.js route handler (the token stays on the server);
   - the model client gains streaming (`stream: true` works on OpenRouter's OpenAI-compatible API, so on the
     existing `deepseek` provider settings); tool rounds stay as they are, only the final text streams;
   - **each sentence is cleaned with the same exit cleaning as today** (`sanitise_output` + ADR 0018 link and
     image removal) **before it leaves the API** — a sentence is held back until it is complete, so a link
     cannot slip through split across two pieces;
   - **conversation memory on the server**: a new table `assistant_conversation_turns` (`tenant_id`, `user_id`,
     conversation id, role, cleaned text, created_at; forced RLS; only the owner of the conversation can read
     it; the last 6 turns go to the model; deleted after 24 hours by the worker). The browser never sends the
     history (a person could otherwise forge an "assistant said" turn). Earlier turns are put into the prompt
     as *data*, screened like record text (ADR 0018).
2. **Voice mode screen (VM2) with the browser engine (a)** for the staging demo: one button **"Start voice
   conversation"**, then the loop *listen → send → speak sentence by sentence → listen again*, a big **Stop**
   button, the written transcript on screen, plain status words ("Listening…", "Thinking…", "Speaking…"),
   and a fixed "One moment, I'm looking that up." while tools run. If the browser cannot listen (Firefox), the
   button says so and offers the server engine if configured.
3. **Server engine (b) (VM3)** behind the same screen, switched by setting: the existing `voice/` provider,
   sentence-by-sentence speech, seconds of audio metered. **Before "go live" the server engine becomes the
   only engine** for organisations with real data (question 7).
4. **Interrupting (VM4):** while the assistant speaks, the person can start talking and it stops speaking
   ("barge-in"); silence detection ends a turn without pressing Stop. Echo cancellation is asked for in
   `getUserMedia`.
5. **Realtime speech-to-speech (c) is not built now.** It gets its own ADR after the pilot if the owner wants
   sub-second replies and accepts a vendor for customer audio.

### Rules that do not change

- **No token in the browser** — all calls through Next.js route handlers with the `crm_session` cookie.
- **Agent registry:** the model calls stay under `staff_assistant` (its switch, token budget, tool filter,
  `CRM_AI_DISABLED`). Voice gets **its own registry entry `voice`** without a model (like `web_check`):
  switch per organisation, **off by default**, counting **minutes of audio** with a monthly minutes budget
  for the server engine. Off = the button is not shown and the API refuses with 503.
- **Sentinel and input screening:** the transcript is a question like a typed one — `inspect_input`
  (ADR 0017/0018) runs on it; proposals go through `approvals.propose()` and the Sentinel.
- **No automatic sending, no approving by voice.** Voice may lead to a *proposal* (ADR 0014); the spoken
  answer says "I have proposed it; nothing has changed until a manager approves", and the proposal is shown
  on screen. There is no voice command that approves, sends an e-mail or changes a record. A mis-heard word
  can at worst create a proposal that another person rejects.
- **Tenant isolation:** the same principal, the same tools, the conversation table under forced RLS with
  the owner filter; tests for another organisation, another person's conversation and a tampered
  conversation id (404).
- **Staff only first.** The customer portal keeps press-to-talk; a portal voice mode would be a later step.
- **No audio is stored** by the CRM in any engine; nothing about audio is logged except its length.

## 6. Steps (each stops for review, tests first)

See `implementation-plan.md`, *Phase VM*. VM1 streaming + memory · VM2 voice screen (browser engine) ·
VM3 server engine + minutes budget · VM4 interrupting + silence detection · VM5 evaluation, Playwright,
measured delays on staging, docs.

## 7. Consequences

- Good: the typed assistant also gets faster (streaming) and can answer follow-up questions (memory).
- Good: the demo can run today at no speech cost; the safer server engine is ready before real data.
- Cost: one new tenant table, one streaming endpoint, a new registry entry, and a client-side loop that
  must be tested on Chrome, Safari (iPhone) and Firefox.
- Risk: the conversation will still feel slow on free models — streaming hides some of it, a faster model is
  the real fix (question 3).
- Risk: the Web Speech API behaves differently per browser and changes without notice; the server engine
  is the fallback.

## 8. Questions for the owner (recommended answer first)

1. **Which speech engine first?** — *Recommended:* browser engine (a) for the staging demo now (free), server
   engine (b) built right after it and used once real data exists. Alternative: only (b) from the start
   (needs a voice key, ~ $0.01 per minute).
2. **Where is the conversation remembered?** — *Recommended:* on the server, last 6 turns, deleted after
   24 hours, only the person who had it can read it. Alternative: no memory (each question alone — then
   it is not really a conversation).
3. **Which model for voice?** — *Recommended:* keep the free OpenRouter models for the demo and measure the
   first-sentence delay in VM5; then decide on a fast paid model (roughly $0.002–0.005 per minute of
   conversation) before showing it to clients. Alternative: pay for a fast model now.
4. **Voice in the agent registry?** — *Recommended:* its own entry `voice`, off by default, a tenant
   administrator switches it on, monthly minutes budget for the server engine (start: 300 minutes).
5. **May a spoken request create a proposal?** — *Recommended:* yes, the same three proposals as typed
   (status, assignment, follow-up task), spoken back and shown on screen; never approving or sending by voice.
   Alternative: voice is read-only.
6. **Realtime speech-to-speech (c)?** — *Recommended:* not now; a separate ADR after the pilot if needed.
7. **Is the browser vendor (Google/Apple/Microsoft) hearing the audio acceptable?** — *Recommended:* yes for
   fictional demo data on staging only; a setting `CRM_VOICE_BROWSER_ENGINE` (on for staging, **off** in the
   go-live checklist) so organisations with real data use the server engine.
8. **Language?** — *Recommended:* English (India), `en-IN`, first; Hindi/Telugu later as a setting, after
   checking which engines support them well.
