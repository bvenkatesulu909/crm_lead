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

## 5a. Cited answers and callbacks (VR3)

The receptionist now has three abilities, and only the spoken channel has the last two (the typed website
chat keeps its single tool):

* **`search_knowledge`** (one field, `question`, 3 to 300 characters): a cited answer built only from the
  organisation's **customer-visible documents that belong to no account** (the visitor is searched as an
  anonymous customer, so internal documents, account documents and other organisations' documents are never
  reachable). It goes through the same machinery as every cited answer (citations validated, RERA numbers and
  amounts must be in a cited source, the fixed "not a live check of the RERA registry" line). When nothing is
  found the tool says so and the receptionist offers a callback. Without an embedder the tool is not offered.
* **The spoken answer is held to the same rule.** After the model's final answer, a RERA number or an
  amount that no source of this turn holds, and that the visitor did not say themselves (their own budget may
  be read back), is replaced by a fixed sentence ("I do not have that detail confirmed from our documents...
  shall I ask the team to call you back?"). This catches a price from memory even when no search was made.
* **`request_callback`** (`day`: today / tomorrow / day_after, `window`: morning / afternoon / evening): a
  **proposal** of the new kind `lead.request_callback` in the approval queue, never a booking. Only fixed
  words go into it: the language is the one the visitor chose on the page, the reason is a fixed sentence, and
  the task a manager's approval creates is built from fixed words ("Call back the website visitor tomorrow in the
  morning, in Telugu"), assigned to the lead's owner or, if there is none, to the manager who approved it.
  It needs the saved lead, allows **one per call**, the Sentinel and the usual approval rules apply (nobody
  approves their own proposal; the proposer is the website's Automation identity), and at most
  `CRM_RECEPTIONIST_CALLBACKS_WAITING` (100) may wait at once and `CRM_RECEPTIONIST_CALLBACKS_PER_HOUR` (60) be
  made per hour for the whole website. Migration 0074 allows the author `receptionist` and adds
  `public_chat_sessions.callback_requested_at`.

## 5b. The call on the page (VR4)

`/chat` shows a **Talk to us** button only when the web server has `PUBLIC_CHAT_VOICE=on` (and the browser can
record). Pressing it shows the **notice** in the chosen language (an automated assistant, not a person; the
speech is turned into text by our speech service and the conversation may be saved; no voice recording is kept;
do not say card numbers, bank details, ID numbers or one-time passwords) with **Listen to this notice**
(the browser's own voice), **Cancel** and **Start**. Nothing is recorded before Start; the press is the consent and
the page sends the notice version (`PUBLIC_CHAT_VOICE_NOTICE_VERSION`, equal to the API's
`CRM_RECEPTIONIST_NOTICE_VERSION`) with every turn.

Each turn: the microphone records until the visitor stops talking (silence detection: 1.4 s of quiet after speech,
at most 15 s, nothing said for 8 s counts as nothing), the audio goes to **our own** `POST /api/public-chat/voice`
route (404 unless the key and the switch are set; refuses audio that is empty, over 2 MB or not audio before anything
leaves the server; forwards it with the server key and the visitor's address; keeps the conversation token in the same
httpOnly cookie as the typed chat), the page shows what was heard and the reply as plain text and plays the reply,
then listens again. **End the call** is always visible. When the service is off or fails, the call button goes away
and says so; the typed chat below keeps working. Two quiet turns in a row end the call; the call's limits end it with a
sentence.

The words (notice, greeting, states, errors) exist in English, Hindi and Telugu and were written by an assistant:
**they need a read-through by a Hindi and a Telugu speaker**. Not checked yet: the page's look, a real microphone on
an Android or iPhone browser (Safari records MP4), the real speech service end to end.

## 5c. Evaluation (VR5)

32 BP-10 cases play the real voice pipeline with only the model scripted: see `docs/agent-evals.md` 6s.

## 6. Not built yet

A Playwright journey with a faked microphone, metrics for calls and refusals, a streaming answer sentence by
sentence (the reply is spoken in one piece in v1; replies are at most two short sentences), a real-model score card
for the receptionist cases, and the phone number channel (its own ADR).
