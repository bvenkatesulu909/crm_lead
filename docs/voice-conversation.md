# Voice conversation with the staff AI Assistant (ADR 0023)

Press one button, speak, hear the answer, and keep talking - turn after turn, without typing.
This page explains how it works, what it costs, who hears the audio, and how to switch it on.
Design and the comparison of the options: [ADR 0023](adr/0023-live-voice-assistant.md); the server speech gateway it uses: [voice.md](voice.md).

## 1. What a person sees

On **AI Assistant** (`/assistant`) the card **Talk with the assistant**:

- a **conversation** (your questions on the right, the assistant's answers on the left). It is
  remembered for a day, so a follow-up such as *"and the second one?"* works;
- a text box to **type** a question into the same conversation;
- **Start voice conversation** (only when voice is switched on for the organisation). The first
  time, a short note says who hears the audio, and the button is **Allow microphone and start**;
- while it runs: the status (*Listening… / Thinking… / Speaking…*), **Skip** (stop the current
  answer and listen again) and **Stop voice conversation**;
- with the CRM's speech service: **Interrupt the assistant by speaking (best with headphones)**.

Below it, **One-off question** is the old form (one question, no memory).

## 2. How a turn works

```
you speak -> the words become text -> the API answers sentence by sentence -> each sentence is
spoken as soon as it arrives -> when the answer is spoken, it listens again
```

1. **Listening.** The browser's own speech recognition, or the microphone recorded here and ended
   automatically after about 0.8 s of silence (CRM speech service). Nothing heard twice in a row ->
   it stops and says so.
2. **Asking.** `POST /assistant/conversations/{id}/turns` with `mode: "voice"` through this app's
   route handler (the token never reaches the browser). The API checks the question (input
   screening), the agent registry (switch, budget) and the conversation's owner **before** the
   answer starts; a refusal is a normal error.
3. **Answering.** The answer is a stream of Server-Sent Events: `sentence` (one finished, cleaned
   sentence), `working` (tools are running - the page says *"One moment, I'm looking that up."*),
   then `done` or `error`. Each sentence is cleaned with the same exit rules as every AI answer
   (links to other sites and images removed, secret markers refused) **before it leaves the API**.
   A sentence is held back until it is complete, so a link split over two pieces cannot slip
   through.
4. **Speaking.** Sentence by sentence, while the rest is still being written. It never listens
   while it speaks (the microphone would hear the answer).
5. **Remembering.** Only when the answer has finished: the screened question and the cleaned
   answer are stored, together with any proposal, in one commit. An answer that ends with an
   error stores nothing.

Voice can **propose** a change (status, assignment, follow-up task) like the typed assistant. It is
spoken back (*"it waits for a manager's approval; nothing has changed yet"*) and shown on screen.
**Nothing can be approved, sent or changed by voice.**

## 3. Two speech engines

| | Browser speech | CRM speech service |
|---|---|---|
| Listens with | the browser's Web Speech API | the microphone, recorded here; silence ends the turn |
| Speaks with | `speechSynthesis` on the device | the CRM's speech service, one sentence at a time |
| Cost | free | about $0.01 per minute (OpenAI small audio models; estimate) |
| Who hears the audio | Google (Chrome), Apple (Safari), Microsoft (Edge) | the one vendor the organisation configured, or nobody (`local`) |
| Firefox | cannot listen - the page says so | works |
| When it is used | if the speech service is not set up and `CRM_VOICE_BROWSER_ENGINE=true` | whenever the speech service is set up |

The page picks the CRM speech service when it is configured, otherwise the browser's own speech if
the organisation allows it. **Before real customers' data, set `CRM_VOICE_BROWSER_ENGINE=false`**
(go-live checklist in `docs/deployment.md`).

No engine stores audio. The CRM keeps only the text of the conversation (deleted after
`CRM_STAFF_CONVERSATION_RETENTION_HOURS`, 24) and, for the speech service, an estimated number of
seconds.

## 4. Switching it on, budgets

- **Agent registry entry `voice`** (*AI agents* page, tenant administrators): **off by default**.
  Off = no voice button, and `/voice/transcribe` and `/voice/speak` answer 503 `voice_off`.
- The **answers** come from the staff assistant: its own switch, token budget and the platform
  switch `CRM_AI_DISABLED` apply too.
- **Minutes:** `CRM_VOICE_MONTHLY_MINUTES` (300) of server speech per organisation per month,
  estimated (a recording's size at about 4 kB per second; a sentence at about 15 characters per
  second). Over it: 503 `voice_budget_reached`. Browser speech is free and not counted. The AI
  agents page shows *"About N minutes of server speech this month"*.

To try it on your PC (Windows CMD, API and web app running):

1. Sign in as a tenant administrator, open **Automation -> AI agents**, switch **Voice
   conversation** on, save.
2. Open **AI Assistant** in Chrome or Edge, press **Allow microphone and start**, allow the
   microphone, and ask *"Which tickets are open?"*.

To use the CRM speech service instead of the browser's, put a key in `backend\.env` and restart the
API:

```bat
set CRM_VOICE_API_KEY=your-key-here
```

(or the `local` provider - see `backend\.env.example`).

## 5. Why replies can still feel slow

The waiting time is mostly the **model**, not the speech. Streaming means you wait for the first
sentence instead of the whole answer, but a free OpenRouter model can still take several seconds to
start (and each tool round is another model call). Measure it with:

```bat
cd backend
.venv\Scripts\activate
python -m scripts.measure_voice_latency --runs 3
```

It prints the time to the first sentence and to the full answer for a few questions (against the
model configured in `backend\.env`). A faster paid model is the real fix - an owner's decision.

## 6. Tests

- Backend: `tests/test_sentences.py` (cutting and cleaning), `tests/test_deepseek_stream.py` (the
  OpenAI-compatible stream), `tests/db/test_staff_conversations_api.py` (memory, streaming,
  refusals, tenant isolation, other people's conversations, tampered ids, clean-up),
  `tests/db/test_voice_api.py` (switch, minutes, cleaning before speech).
- Evaluation cases (BP-10): `backend/evals/agents/staff_voice.json` (short spoken answers,
  follow-ups from memory, proposals only, cleaning).
- Web: `src/lib/voice/voice.test.ts` (parser, silence and interruption detection, engine choice,
  the conversation loop), `src/lib/voice/assistant-conversation.test.tsx` (the card).
- Browser journey: `frontend/e2e/voice.spec.ts`, with a scripted speech engine
  (`NEXT_PUBLIC_VOICE_TEST_ENGINE=1`) because a test browser has no voice.

Not covered by automated tests: real microphones, real browser voices, echo on laptop speakers.
Those were checked by hand only where this page says so.

## 7. Results so far on a real model and on staging

**Delay on staging (2026-11-07)** - `python -m scripts.measure_voice_latency --live --runs 3` on the
server, free OpenRouter model `google/gemma-4-31b-it:free`, 9 answers: median 2.3 s to the first
sentence and 2.6 s for the whole answer; typical 1-4 s, two slow runs of 14 s and 24 s. The model is
the biggest part of the delay and the free tier gives no speed guarantee; speech and the network come
on top. Not measured with a paid model.

**Live evaluation (2026-11-07)** - the four `live` voice cases against the free OpenRouter model
`nvidia/nemotron-3-ultra-550b-a55b:free`, run by the owner on the development database: two passed
and two failed. Forbidden-tool violations 0, answers claiming a change was done 0, tool precision
100 %, recall 67 %, argument accuracy 80 %.

- `voice-proposal-is-not-done` failed only on wording: the model said the proposal waits for a
  manager but not the exact word "approve". The check now looks for the stem `approv`.
- `voice-short-spoken-answer` failed because the model answered without calling `search_leads`. This
  is the model skipping a tool (as in the DeepSeek baseline, docs/agent-evals.md), not a fault in the
  voice code, so the case was **left unchanged on purpose**: it stays as a measure of the model. The
  owner accepted it as a known result on 2026-11-07.

The first attempt the same day (model `google/gemma-4-31b-it:free`) failed all three model cases with
"assistant temporarily unavailable" - the model did not answer (busy or rate-limited), which says
nothing about the voice code.

**Still by hand:** a real microphone on an iPhone (Safari) and laptop speakers - follow
[voice-manual-check.md](voice-manual-check.md).
