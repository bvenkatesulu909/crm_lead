# ADR 0038 — A live Telugu and Hindi voice receptionist (browser first, phone number later)

- **Status:** Accepted (2026-11-21, owner: recommended answers to all ten questions of section 7; limits per call 5 minutes and 12 turns; the organisation's minutes cap is set after the VR1 measurement). Documents only; VR1 not started.
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0013 (public website chat and `save_lead`), ADR 0027 (Hindi/Telugu voice lead capture,
  browser speech), ADR 0023 (live voice for the staff assistant: streaming, server speech engine, cost cap),
  ADR 0016 (agent registry: switch, budget, kill switch), ADR 0014 (approval queue), ADR 0017 and 0018
  (Sentinel, cleaning of untrusted text and of answers), ADR 0030 (call recordings: consent, retention),
  ADR 0009 (row-level security), CRM-115 / BP-08 (cited answers from brochures, the RERA gate), ADR 0019
  (the web check is the only "live" lookup)
- **Owner's feature list:** item 15, "Live Telugu and Hindi voice receptionist".

## 1. The problem

A home buyer who finds the company's website at night, or sees an advertisement, wants to **talk**, in
Telugu or Hindi, and get a few quick answers ("is the 2 BHK still available? where is the project? is it
RERA registered?"). Today there is nobody to answer, and ADR 0027 gives only a typing-or-dictating chat
with one ability: save the visitor as a lead. The goal is a **receptionist that talks**: it greets, answers
from the company's own approved material, takes the visitor's details, and offers a callback - and it
never pretends to be more than that. A receptionist who invents a price or promises a discount is worse than
no receptionist, so what it may *not* do matters as much as what it may.

## 2. What exists (and is reused)

- **Public chat (ADR 0013, 0027):** anonymous, server key, honeypot, limits per address / conversation / day,
  `save_lead` as the only tool, a lead created unassigned by the Automation identity, language en/hi/te
  stored on the lead, input screening for Hindi/Telugu, conversation transcript on the lead.
- **Browser speech (ADR 0027):** free, Chrome/Edge/Android good for Hindi, **Telugu weaker**, Safari often none.
- **Server voice gateway (ADR 0023):** staff-only, off by default; engines openai | elevenlabs | local,
  sentence-by-sentence audio, silence detection, monthly estimated-minutes cap, streaming answers.
- **Cited answers (CRM-115):** the knowledge pipeline answers only from customer-visible documents, cites
  them, refuses a RERA number or price it cannot cite, and says "this is not a live check of the RERA registry".
- **Agent registry (ADR 0016):** per-agent switch, monthly budget, kill switch, metered tokens and minutes.
- **Approval queue + Sentinel (ADR 0014/0017):** an AI never changes a record; it proposes, a different
  person approves; links, instructions and duplicates are blocked.
- **Call recordings (ADR 0030):** consent record, 90-day audio retention, cleaning, transcripts - for staff-added
  recordings of calls that already happened.

## 3. Decisions (proposed)

**VR1 - The receptionist is a *mode* of the public chat, not a new system.** Same `public_chat` module,
tables, limits, honeypot, server key, language list and lead creation. A conversation has a `channel`
(`text`, `web_voice`, later `phone`). Everything the receptionist says is produced by the same governed model
call and cleaned by the same exit screening. One code path to defend, not two.

**VR2 - Channel 1 (v1): a "Talk to us" button in the browser, no phone number.** A visitor on `/chat` (or the
company's own page, embedded) presses the button and talks; the answer is spoken back. Why first: no
telephony contract, no number, no per-minute carrier cost, no telecom rules (section 5) - and it is
exactly where the ADR 0013 visitor already is. The audio path:

| Engine | What | Trade-off |
|---|---|---|
| Browser's own speech (ADR 0027) | recognition and speaking inside the browser | free, no audio on our server; Telugu accuracy and Safari support are poor; turn-taking is clumsy |
| **Server speech (recommended for v1 voice)** | the page streams short audio chunks to the API; the API transcribes with the provider already wired for call recordings (a Whisper-class model with a language hint), the model answers, a TTS voice speaks sentence by sentence (ADR 0023 pipeline) | works in every browser, better Telugu, costs money per minute, audio goes to our speech vendor (named in the notice) |
| A realtime speech-to-speech API | one streaming model hears and speaks | lowest delay and most natural, but the model then "hears" before our guardrails read the text, so the screening of input and the cleaning of output cannot sit between hearing and speaking; **rejected for v1**, revisit under its own ADR |

The pipeline stays *listen -> transcribe -> text screening -> model -> text cleaning -> speak*, so every safety
rule of the text chat applies unchanged to a spoken call. Delay is the price (about 2-4 s per turn); a short
spoken "one moment" while thinking hides part of it.

**VR3 - Channel 2 (later, own decision): a phone number.** Options and trade-offs, so the owner can see why
it is not first:

| Option | Good | Bad |
|---|---|---|
| Browser widget only (v1) | cheapest, no rules, works today | the visitor must be on the website; many buyers prefer to dial |
| Indian cloud-telephony provider (Exotel, Knowlarity, Ozonetel, Plivo and similar; a number with a webhook and media stream) | local numbers and DLT/TRAI-compliant routing handled by them; Indian-language support staff | contract and KYC with the provider, per-minute charges, vendor-specific streaming API |
| A global CPaaS (Twilio, Vonage) | excellent documentation and SDKs | Indian number acquisition and regulation are harder; international per-minute cost |
| SIP trunk to our own media server | most control | we would run telephony; far too much for a one-person project |

If and when this is built: the provider's media stream feeds the *same* VR2 pipeline; the call is just another
`channel`. It would need its own ADR for the provider choice, the caller-ID and consent wording, DLT
registration and the exact recording rules. **Nothing in v1 depends on it.**

**VR4 - What the receptionist MAY do (three abilities, no more).**

1. **Answer questions from approved material** through one tool, `search_knowledge`, which uses the existing
   cited-answer pipeline restricted to **customer-visible** documents of the organisation. Every factual claim
   about a project, price, availability or RERA number needs a citation; if it cannot cite, it says it does not
   know and offers a callback. The fixed "not a live check of the RERA registry" line is spoken whenever a RERA
   number is mentioned. Internal documents and other organisations' documents never reach it (retrieval's own
   permission rules, tested as today).
2. **Capture a lead** with `save_lead` exactly as ADR 0013/0027: name, phone, optional budget, property type,
   location, notes in English, language set by the page, one lead per conversation, unassigned.
3. **Ask for a callback** through one tool, `request_callback` (preferred day, a time window from a fixed list,
   the language). It does **not** book anything. It creates a **proposal** in the approval queue (a new kind
   `lead.request_callback`, author `receptionist`; on approval it creates a follow-up task for the lead's
   owner, or for the sales managers if the lead is unassigned). A manager sees "Visitor asked for a callback
   tomorrow morning, in Telugu" and approves or rejects it; the visitor is told "the team will confirm", never
   "booked". A callback needs a saved lead first, so the receptionist cannot create tasks for unknown numbers.

**VR5 - What the receptionist must NEVER do.** Written into the prompt *and* enforced by code (the tools simply
do not exist), and each item has an evaluation case:

- Quote a price, discount, offer, payment plan or availability **that it cannot cite**; negotiate; "hold" a unit.
- State that a project **is or is not RERA registered** beyond what a cited brochure says; give legal, loan,
  tax or investment advice.
- Take or discuss **card numbers, bank details, OTPs, Aadhaar/PAN** - such input is refused and is not stored
  (the existing card-number screening, also on spoken digits in Hindi/Telugu words, see VR9).
- Read, search or reveal **any CRM record** (leads, accounts, quotes, other visitors' conversations), or confirm
  that a person "is already a customer".
- Send e-mail, SMS or WhatsApp, open links, fetch web pages, or start a web check.
- Approve, edit or delete anything, change a lead's status or owner, convert a lead.
- **Claim to be human.** It says at the start that it is an automated assistant, and answers "are you a robot?"
  truthfully.
- Continue after the limits or the switch say stop: it says a fixed "we are resting, please leave a number at
  ..." sentence in the visitor's language and ends the call (as the website chat already does).

**VR6 - Consent and the recording notice.** The default is **no audio is stored**: the call is transcribed in
memory per turn, only the text turns are saved (the same `public_chat_messages` as today, same 30-day deletion
without a lead). Before the microphone opens, the page shows and speaks, in the chosen language: that this is
an **automated assistant**; that **the conversation is transcribed and may be saved with the details the visitor
gives**; that audio is sent to the named speech provider for transcription; and a link to the privacy page.
The visitor presses "Start" after reading it - that press is the consent and is stored with the conversation
(a timestamp and the notice's version). No press, no microphone. If the owner later wants audio kept (for quality
review), that is a separate switch with its own notice and the 90-day retention and delete rules of ADR 0030,
not part of v1. *(This ADR is not legal advice: before going live the owner should have the notice text and the
rules for recording calls checked, in particular for the phone channel.)*

**VR7 - Governed like every other AI feature.** A new registry entry `receptionist` (a model **and** speech
agent), **off by default**, with: the switch; a monthly token budget **and a monthly speech-minutes cap**
(ADR 0016 / 0023 counters); the tool filter (so an administrator can switch off callbacks while keeping
answers); the platform kill switch `CRM_AI_DISABLED`; its own `CRM_RECEPTIONIST_*` settings. When any of them
stops it, the visitor hears the fixed resting sentence and no lead is lost silently - the page offers the
typed lead form.

**VR8 - Cost caps (speech minutes are the new expensive thing).** Per call: at most **5 minutes** and 12
turns, then a spoken goodbye that offers a callback. Per visitor address: at most 3 voice calls a day (keyed
hash, as today). Per organisation: a daily and a monthly minutes cap (default small, set by the
administrator). Silence longer than 10 s ends the call. Estimated cost is shown on the AI agents page next to
tokens, as for the other agents (CRM-111). The numbers below are *defaults to review*, and no price is claimed:
a measurement step (VR5 in section 6) gets real figures from the chosen provider before any limit is set.

**VR9 - Hindi and Telugu safety for *spoken* input.** Speech recognisers write numbers as words or digits in
either script and may transcribe an injected sentence ("ignore your instructions") like any text. So: the
transcript goes through the same input screening as typed text (ADR 0027 VL4, extended with spoken-number forms
such as "one two three four ..." in English, Hindi and Telugu words for the card-number and OTP check); a screened
refusal is spoken in a fixed sentence; the model still has only the three tools above, so the worst a successful
injection can do is: one cleaned, unassigned lead and one callback *proposal* a manager reads before anything
happens. The reply is cleaned (links, images, secret markers out) **before** it is sent to text-to-speech, so a
link or a poisoned instruction is never spoken.

**VR10 - Staff see what happened.** The conversation (text turns) appears on the lead page in the existing
"Website chat" card with a **Voice** label and its duration; a manager notification "voice conversation with a
lead" (existing event); callbacks wait in **Approvals**; the AI agents page shows minutes, calls, refusals.
Metrics `crm_receptionist_calls_total`, `..._minutes_total`, `..._refusals_total` (no tenant, no person label).

## 4. What this does not do

No phone number in v1; no outbound calling (the system never rings anyone - that raises consent and TRAI
questions of its own); no audio storage; no payment, booking or negotiation; no language beyond English, Hindi
and Telugu; no reading of CRM records; no change to who may see a lead; no voice cloning or custom celebrity
voices (a plain provider voice, named in the notice).

## 5. Telephony, consent and rules (for the later phone channel)

- A phone line means India's telecom rules (number from a licensed provider, KYC, DLT registration for any
  call or message that is promotional, "do not disturb" lists for outbound). **Inbound** calls answered by a
  receptionist are far simpler than **outbound** ones; this ADR allows only inbound.
- The opening line of a phone call must say it is an automated assistant and that the call may be recorded or
  transcribed, *before* anything is stored; staying on the line is weaker consent than pressing a button, so
  the phone ADR may require "press 1 to continue".
- Caller numbers are personal data: stored on the lead only if the visitor gives them or the owner turns caller
  ID capture on; never logged in clear in metrics.
- Emergency, abuse or an angry customer: the receptionist offers a human callback and ends; it never argues.

## 6. Steps (Phase VR), each stops for review

| Step | Content | Evidence expected |
|---|---|---|
| VR0 | This ADR (documents only) | owner answers section 7 |
| VR1 | **Measurement first**, no product: a script that sends fictional Telugu, Hindi and English sentences (reuse `docs/call-trial-samples.md` style) through the candidate speech providers and the chosen model, reporting word error rate, delay per turn and cost per minute; owner's yes before any paid call | a short table in the docs; no accuracy claim without it |
| VR2 | Backend: `channel` on conversations (migration), registry entry `receptionist` (off by default, minutes cap), settings, the **voice turn endpoint** (audio chunk in, text and sentence audio out, per-turn limits, consent record), speech pipeline reuse from ADR 0023, input screening extension (VR9) | database tests: switch/budget/minutes cap/kill switch, consent required, per-call and per-address limits, tenant isolation, a made-up conversation id, a forged server key, extra fields refused; deliberate breaks caught - **built 2026-11-21 (backend only, see `docs/receptionist.md`)**: migration 0073, registry entry `receptionist` (off by default), `POST /public/voice/turn`, consent stored with the notice version, per-call / per-address / organisation minutes limits all checked before any audio is recognised, spoken-number screening in English, Hindi and Telugu. Differences from the plan: the reply is spoken in one piece (replies are two sentences at most), not sentence by sentence; `voice_seconds` are estimates |
| VR3 | Tools: `search_knowledge` (customer-visible only, cited, RERA/price gate) and `request_callback` + approval kind `lead.request_callback` (migration widens author and kind; Sentinel rules; on approval a task for the owner or managers); the prompt per language with the NEVER list | tests: no uncited price, internal document never reached, callback needs a saved lead, a duplicate callback blocked, approval by a different person only |
| VR4 | Web: the consent screen (spoken and written), "Talk to us" button and call screen (listening / thinking / speaking states, a visible End button, typed fallback), embedding snippet for the company's site | component tests; Playwright journey with a *scripted* speech engine (Hindi and Telugu), no real microphone |
| VR5 | BP-10: a `receptionist` suite of scripted cases (every NEVER item, injected spoken instruction, Indic-digit card number, uncited price, RERA question, "are you a robot?", limits, switch off, callback proposal); `docs/receptionist.md`; CLAUDE.md status; one optional paid real-model run reported honestly | evaluation gate in CI |
| VR6 | **Owner's live check** on staging with a real microphone on Android Chrome and iPhone Safari, in Telugu and Hindi; decide the limits from the measured cost | recorded outcome, nothing assumed |
| VR7 | *Separate ADR, only if wanted:* the phone-number channel (provider, consent wording, DLT, inbound only) | its own review |

Nothing is switched on in staging by default; nothing goes online until the owner says "go live".

## 7. Questions for the owner (recommended answer first)

1. **Where to start?** *Recommended:* a "Talk to us" button in the browser (VR2); a phone number only after the
   owner has seen it work. Alternative: go straight to a phone number (needs a provider contract and a second
   ADR first).
2. **Which speech engine for the visitor?** *Recommended:* server speech (better Telugu, all browsers), with the
   browser's own speech as the free fallback if the server engine is off. Alternative: browser speech only
   (free, but Telugu and Safari are unreliable).
3. **Realtime speech-to-speech model?** *Recommended:* not in v1 (it bypasses our text screening); a separate
   ADR later if delay is the main complaint. Alternative: accept less screening for a more natural voice.
4. **What may it do?** *Recommended:* answer from cited customer-visible documents, capture a lead, and
   request a callback as a proposal a manager approves. Alternative: answers and lead capture only, no callback.
5. **Does it store audio?** *Recommended:* no; text turns only, with the 30-day clean-up for conversations
   without a lead. Alternative: keep audio 90 days for quality review (needs a second consent line and the
   ADR 0030 retention rules).
6. **Consent.** *Recommended:* the visitor presses Start after the automated-assistant and transcription notice
   in their language; the press is stored. Alternative: a spoken "say yes to continue" (harder to prove and
   to recognise in Telugu).
7. **Limits.** *Recommended:* 5 minutes and 12 turns per call, 3 calls per visitor per day, and an
   organisation minutes cap you set after the measurement step shows the real cost per minute. Alternative:
   give your numbers now.
8. **Who approves callbacks?** *Recommended:* sales managers and tenant administrators (the queue's normal
   rule), never the visitor-facing receptionist itself. Alternative: the lead's owner approves their own
   leads' callbacks.
9. **Persona and name.** *Recommended:* a plain, polite assistant that says "I am an automated assistant of
   <company>" in the visitor's language, with no human name and no invented personality. Alternative: a named
   persona (risks being mistaken for a person).
10. **Legal check.** *Recommended:* the owner has the notice text and (later) the phone recording rules checked
    by a lawyer or the client's counsel before "go live". Alternative: proceed on the standard wording and
    accept the risk.

## 8. Alternatives considered

- **A separate voice bot product (hosted receptionist SaaS).** Quick to start, but the CRM's tenant isolation,
  approval queue, Sentinel and audit would not apply, and visitor data would live elsewhere. Rejected.
- **Extend the staff voice assistant to visitors (ADR 0023).** It can see CRM data; exposing it to anonymous
  users is the opposite of the least-privilege design. Rejected - only the *speech pipeline* is reused.
- **Let the receptionist book a time directly in a calendar.** Needs calendar access and creates promises the
  team did not make; a proposal a manager approves is the safe form. Deferred.
- **Auto-dial new leads (outbound AI calls).** Different consent and DND rules, high annoyance risk. Out of scope.
- **Realtime speech-to-speech** - see VR2; rejected for v1.

## 9. Consequences

- A visitor can speak Telugu or Hindi to the website, hear cited answers about projects, leave details, and ask
  for a callback; the team sees a normal lead and an approval to act on.
- The worst case of a hostile caller is bounded as in ADR 0013: one cleaned, unassigned lead and one callback
  *proposal* that a person reads first. No CRM data is readable and no record changes by itself.
- Voice costs real money per minute; the caps, the switch and the cost line on the agents page are mandatory,
  not optional, and the limits are set only after real measurement.
- Telugu accuracy is the main honest risk: it is measured in VR1 and again by the owner in VR6, and the
  documentation states the measured limits instead of promising quality.
- The phone channel stays a separate, later decision; the design keeps `channel` open so it does not need a
  rewrite.
