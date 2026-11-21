# The voice receptionist (ADR 0038)

The website chat (ADR 0013, 0027), spoken. A visitor presses **Start** on the page, talks, and hears
an answer; the details they give become an ordinary, unassigned lead. This page describes what exists
so far. **Backend only (step VR2): there is no screen yet (VR4), and the knowledge answers and the
callback request (VR3) are not built.** Nothing is switched on anywhere.

## 1. What a spoken turn does

`POST /api/v1/public/voice/turn` - like the typed chat, only the CRM's own web server may call it
(the `X-Public-Chat-Key` header; without it the endpoint answers 404). It takes a form with the audio
of one turn (`audio`), `language` (`en`, `hi`, `te`), the conversation `token` (after the first
turn), `consent_version` and the hidden `website` field (bots fill it, people never do).

The order matters: **everything that can refuse the visitor runs before the audio is sent to the
speech service**, so a refused visitor costs nothing.

1. The organisation's switch and budget for the registry entry **`receptionist`** (off until an
   administrator switches it on; its tokens and its tool list are its own), the organisation's
   **minutes caps** (per UTC day and per month), the visitor's **consent**, the per-address call limit
   and the per-call limits. Any refusal: 503 `receptionist_unavailable` (the text is a fixed
   "resting" sentence and the page offers the typed form), 422 `voice_consent_required`, 429
   `voice_limit_reached`.
2. The audio (type and size) is checked, then the speech service **hears** it (with the language
   the visitor chose as a hint).
3. What was heard goes through the **same pipeline as a typed message**: the guardrails and cleaning
   of ADR 0013/0017/0018, the spoken-number check (section 3), the model with its one tool
   `save_lead`, the cleaned answer. The voice prompt adds fixed rules: say it is an automated
   assistant, two short sentences, read the phone number and name back and ask for a confirmation
   before saving.
4. The answer is **spoken** by the speech service. If speaking fails the text still comes back
   (`audio_base64` is null) and the call goes on.

The answer holds the token, what was heard (so the page can show it), the reply, whether the details
were saved, the audio (base64) and what is left of the call: `seconds_left`, `turns_left`,
`call_ended`. It never holds CRM data.

## 2. Consent and what is stored

The default is **no audio is stored**: the audio is sent to the speech service for one turn and
dropped. Only the text turns are saved, in the same tables as the typed chat (conversations without a
lead are deleted after 30 days).

A conversation gets `channel = web_voice` with the **time the visitor pressed Start and the version
of the notice they read** (`CRM_RECEPTIONIST_NOTICE_VERSION`, raise it when the words change). The
first spoken turn without the current version is refused; the database also refuses a voice
conversation without that record. A typed conversation that goes on by voice needs the consent first.

## 3. What it refuses

* A **card number said aloud** - 13 or more digits in a row, as digits or as number words in English,
  Hindi or Telugu - and any mention of a **one-time password or card security code**. A normal phone
  number said aloud (10 digits, or 12 with +91) passes. The refusal is a fixed spoken sentence, nothing
  is stored, and the recognition seconds still count against the organisation's day.
* Everything the typed chat already refuses: instruction phrases (also in Hindi and Telugu), card
  numbers written as digits, links and markup in answers, the filled honeypot.
* The receptionist has **one ability: `save_lead`**, as in ADR 0013. It cannot read the CRM, send
  anything, change a record or approve anything. The other two abilities of ADR 0038 (cited answers
  from the knowledge base, a callback request as a proposal) are step VR3.

## 4. Limits (all settings in `.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `CRM_RECEPTIONIST_MAX_CALL_SECONDS` | 300 | speech seconds in one call (heard + spoken, estimated) |
| `CRM_RECEPTIONIST_MAX_TURNS` | 12 | spoken turns in one call |
| `CRM_RECEPTIONIST_CALLS_PER_IP_DAY` | 3 | calls one visitor address may start per day |
| `CRM_RECEPTIONIST_MINUTES_PER_DAY` | 60 | the organisation's estimated speech minutes per UTC day |
| `CRM_RECEPTIONIST_MINUTES_PER_MONTH` | 600 | the same per calendar month |
| `CRM_RECEPTIONIST_NOTICE_VERSION` | 1 | the notice version the visitor must have read |
| `CRM_RECEPTIONIST_MAX_AUDIO_BYTES` | 2 MB | one turn's audio |

The seconds are **estimates** (no audio is decoded: the recording's size at the usual compressed rate,
and a spoken sentence at a normal pace), a budget and not a bill. The daily and monthly sums live in
`public_chat_daily_stats.voice_seconds` - anonymous counters that only grow and survive the clean-up of
old conversations. **These defaults are placeholders**: the owner sets the real numbers after the
measurement of `docs/receptionist-voice-measurement.md` shows the cost per minute.

## 5. What staff see

The lead's "Website chat" transcript (`GET /public-chat/leads/{id}/transcript`) now also says the
`channel` (`text` or `web_voice`) and the `voice_seconds`. The AI agents page lists the **Voice
receptionist** with its switch, budget and tool filter like every other agent.

## 6. Not built yet

The page and microphone (VR4), cited answers and the callback proposal (VR3), the evaluation cases
(VR5), metrics for calls and refusals, a streaming answer sentence by sentence (the reply is spoken
in one piece in v1; replies are at most two short sentences), and the phone number channel (its own
ADR).
