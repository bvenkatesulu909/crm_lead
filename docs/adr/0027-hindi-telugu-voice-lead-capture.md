# ADR 0027 — Hindi and Telugu voice lead capture on the website chat

- **Status:** Accepted (2026-11-12) with the recommended answer to all five questions in section 6
- **Date:** 2026-11-12
- **Deciders:** Project owner
- **Depends on:** ADR 0013 (public website chat, `save_lead`), ADR 0017/0018 (cleaning and screening of
  untrusted text), ADR 0016 (agent registry: switch, budget), ADR 0023 (voice - browser engine first)

## 1. The problem

Many home buyers in the target markets speak Hindi or Telugu and will not type a long conversation
in English on a phone. Today the website chat (BP-01) is text only and the prompt writes English. A
visitor who can **speak** in their own language, hear the answer and leave their details should
become a lead like any other - with the language written on the lead so the advisor calls back in it.

## 2. What exists

- The public chat page `/chat` and its route handler; one tool, `save_lead`; limits, honeypot,
  cleaning of every stored field; the lead is created unassigned by the Automation identity.
- Browser speech helpers (`src/lib/speech.ts`: recognition with a `lang`, synthesis) used by the
  staff assistant; the server speech gateway (`/voice/*`) is staff-only and off by default.
- The input screening (hidden characters, instruction phrases, card numbers) is written for English
  text and Latin digits.

## 3. Decisions (proposed)

**VL1 - v1 uses the browser's own speech, nothing new on the server.** A microphone button on `/chat`
uses the browser's speech recognition with `hi-IN` or `te-IN`; replies can be read aloud with the
browser's speech synthesis. No audio reaches the CRM and no paid speech service is needed. The
privacy notice says the browser may send the audio to its own vendor (Chrome does). A browser
without speech support simply shows no microphone - typing still works. A server speech service for
Telugu (better accuracy, works in Safari) is a later, separate decision with its own cost and
privacy review.

**VL2 - Three languages, chosen by the visitor.** English, हिन्दी, తెలుగు: a switch at the top of the
chat, defaulting to the browser's language when it is one of the three. The page sends the code
(`en` | `hi` | `te`, a fixed list - never free text) with each message. The model is told to reply in
that language **in its own script**; a visitor who types Hinglish (Hindi in Latin letters) is
answered in Hindi script when `hi` is chosen.

**VL3 - The language is stored on the lead.** A new lead field `preferred_language` (`en` | `hi` |
`te`, database check) is set by `save_lead` from the chosen language - not from anything the model
or the visitor can type - and shown on the lead page and in the lead list filter, so the advisor
knows which language to call in. Names and notes are stored as the visitor said them (cleaned as
today); the model is asked to write the lead notes in English so every advisor can read them, with
the visitor's own words kept only for names and places.

**VL4 - The protections must work for Hindi and Telugu text.** Before any of this ships: Devanagari
and Telugu digits are converted to Latin digits before the card-number, phone and budget checks (a
card number written in Telugu digits must still be refused); the instruction-phrase screening gets
Hindi and Telugu phrase lists for the common "ignore previous instructions" forms and the attack
library gets matching texts; and the same exit cleaning (links, images, secret markers) applies to
every answer, whatever the language. The model still has only `save_lead`, so the worst a successful
injection can do is create one cleaned, unassigned lead - the same bound as today.

**VL5 - Evaluated like everything else.** New BP-10 public-chat cases play Hindi and Telugu
conversations with the scripted model (a lead saved with the right language, a card number in Indic
digits refused, an instruction in Hindi blocked, a Telugu answer cleaned of links); one real-model
pass with DeepSeek, with the owner's yes, to see how well it writes both languages.

## 4. What this does not do

No phone calls (that is the separate "call audio" item), no automatic translation of old leads, no
language other than the three, no server-side speech in v1, no change to who may see a lead.

## 5. Steps (Phase VL), each stops for review

| Step | Content |
|---|---|
| VL0 | This ADR (documents only) - **done 2026-11-12** |
| VL1 | Backend: `language` on the chat request, prompt per language, `preferred_language` on leads (migration, check, lead schemas, filter), Indic digit conversion, Hindi/Telugu screening phrases, attack library texts - **done 2026-11-12**: migration 0058 (`leads.preferred_language`, database check `en`/`hi`/`te`), `language` on `POST /public/chat` (fixed list, default `en`, extra values 422), one fixed prompt rule per language, the lead gets the language of the request that saved it (the model cannot set it: `save_lead` still refuses extra arguments), phone numbers in Devanagari or Telugu digits saved as 0-9, seven Hindi/Telugu instruction patterns in `app/core/screening.py` (a first version) and six cases in the attack library. The card-number check already matched Indic digits (`\d` is Unicode-aware); a test now locks that in. The lead list filter is not built yet (it needs a screen, so it moves to VL2) |
| VL2 | `/chat` screen: language switch, microphone button (browser speech), "read replies aloud", notices; route handler passes the code - **done 2026-11-12**: three buttons (English / हिन्दी / తెలుగు, the browser's own language is the starting choice), every word on the page in the chosen language (`CHAT_TEXT`), a Speak button that listens in `hi-IN` / `te-IN` / `en-IN` and puts the recognised words in the message box (nothing is sent until the visitor presses Send), a "Read replies aloud" switch that is off until ticked, a notice that the browser may send the voice to its provider, route handler and forwarder pass the code (anything else becomes English). Also the lead side: a `preferred_language` filter on `GET /leads`, a "Call in" filter on the Leads page and a "Call in" row on the lead page. The words were written by the assistant and need a read-through by a Hindi and a Telugu speaker. Error messages are still English |
| VL3 | Evaluation cases (scripted), Playwright journey (typed Hindi and Telugu; speech faked), docs, one real-model pass - **done 2026-11-12 except the real-model pass**: case fields `language` and `expect.lead_language`, twelve cases (docs/agent-evals.md 6o), Playwright `e2e/public-chat-languages.spec.ts` (a Hindi speaker with a faked speech engine, a Telugu speaker typing Telugu digits, a card number in Hindi digits); the real-model run waits for the owner's yes |

## 6. Questions for the owner (recommended answer first)

1. **Speech engine.** *Recommended:* the browser's own speech in v1 (free, no audio on our server).
   Alternative: a server speech service now (costs money, needs a provider and a privacy review).
2. **Languages.** *Recommended:* English, Hindi, Telugu. Alternative: add Tamil, Kannada or others.
3. **Preferred language on the lead.** *Recommended:* yes, a new field set from the chosen language.
   Alternative: put the language only in the lead's notes.
4. **Notes language.** *Recommended:* the model writes lead notes in English. Alternative: in the
   visitor's language.
5. **Read-aloud.** *Recommended:* off until the visitor presses "Read replies aloud". Alternative:
   on by default after the visitor used the microphone.

## 7. Consequences

- A visitor can speak Hindi or Telugu to the website chat and leave their details; the advisor sees
  the language on the lead.
- Accuracy depends on the visitor's browser: Chrome, Edge and Android are good for Hindi, Telugu is
  weaker, Safari may offer no microphone. The honest limit is written in the docs.
- The screening lists for Hindi and Telugu are a first version, not a guarantee; the bound on harm
  stays "one cleaned, unassigned lead".
