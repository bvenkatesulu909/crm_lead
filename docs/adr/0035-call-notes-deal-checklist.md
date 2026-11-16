# ADR 0035 — Call notes and a deal checklist (BANT or MEDDIC) from a call transcript

- **Status:** Accepted (2026-11-16, owner: "Accept, build CN1"; the recommended answers of section 6 apply). CN1 built 2026-11-16.
- **Date:** 2026-11-16
- **Deciders:** Project owner
- **Depends on:** ADR 0030 (call recordings and timestamped transcripts), ADR 0028 (buyer memory),
  ADR 0014 (approval queue), ADR 0016 (agent registry, budgets, kill switch), ADR 0017 and 0018 (Sentinel
  and cleaning of untrusted text), ADR 0009 (row-level security), ADR 0034 (the pattern of a governed,
  approval-only agent)
- **Amends:** ADR 0030 decision CA7 ("no model reads a transcript in v1") - this ADR is the "later step" that
  CA7 and ADR 0028 BM5 announced, and it keeps their conditions (only suggestions, only assumptions, only
  through approval).
- **Owner's feature list:** item 12, "Call notes with deal checklist (MEDDIC/BANT)".

## 1. The problem

After a call, a rep is supposed to write notes and tick a qualification checklist. In practice the notes are
one line, and the checklist is filled from memory - so a **guess becomes a "fact"** ("budget: 1.5 Cr" when the
buyer only said "maybe around that"). We now have the recording and a timestamped transcript (ADR 0030) and a
place that keeps facts and assumptions apart (buyer memory, ADR 0028). What is missing is the step in between:
**read what was actually said and fill the checklist honestly**, so that every line says whether it was
*stated*, *assumed* or is *unknown*, and points to the exact moment on the recording.

Two frames are common in sales:

- **BANT** - Budget, Authority, Need, Timeline. Typical for a home-buying lead.
- **MEDDIC** - Metrics, Economic buyer, Decision criteria, Decision process, Identify pain, Champion. Typical
  for longer, multi-person deals (an investor buying several units, a builder-to-builder deal).

The organisation chooses one.

## 2. What exists

- `calls` module: `call_recordings` with the transcript text and **segments with start and end times**, the
  language the rep chose, status `ready`, permissions `call:read` / `call:write`. The transcript is stored as
  untrusted plain text; today no model reads it. **There is no speaker identification** (ADR 0030 section 4).
- `buyer_memory`: twelve fixed keys; each item is a fact (needs a source and a quote) or an assumption (needs
  a reason); append-only; a person confirms an assumption into a fact.
- Agent registry (`agents.governed`): switch, monthly token budget, tool filter, platform kill switch.
- Approval queue + Sentinel: any AI change is a proposal that a *different* person approves; kinds are a fixed
  catalogue (`lead.set_status`, `lead.assign`, `activity.create_task`, `quote.deck_summary`).
- `app/core/screening.py` (cleaning, instruction detection), forced RLS on every tenant table, the BP-10
  evaluation harness with scripted models, the pattern of ADR 0034 (a run is "as the person asking", returns a
  strict tool answer, stores an insert-only record, creates proposals only).

## 3. Decisions (proposed)

**CN1 - A new module `call_notes`; the output is a draft, not CRM data.** The result of a run (the notes and
the checklist) is stored in the new module's own tables and shown on the recording's card as **"AI draft from
the transcript"**. It is *not* buyer memory and does not change the lead. Anything that should reach the lead
goes through CN7.

**CN2 - Each checklist line has exactly one of three states, enforced by code and by the database.**

| State | Meaning | What the line must hold |
|---|---|---|
| `stated` | the call contains words that give this answer | a **quote** copied from the transcript and its **start time** (and end time); a short **value** that is a piece of that quote |
| `assumed` | the transcript hints at it but does not say it | a one-sentence **reason**, and the quote and time of the hint |
| `unknown` | nothing on the call answers it | nothing else (no value, no quote) |

Nothing else is allowed. A line cannot be "stated" without a quote and a time (database check), and the
absence of an answer is `unknown`, never an empty "stated".

**CN3 - "Stated" is verified by code, not trusted from the model.** After the model answers, the service
checks every quote against the stored segments: the quote must appear **literally** (after trimming spaces and
normalising case and punctuation only) inside the transcript between the start and end time the model gave.
A line whose quote cannot be found is **downgraded to `unknown`** with the note "the quoted words were not
found in the transcript", and a counter of such lines is kept. A model that invents a quote therefore ends up
with an empty line, not a believable one. If more than half the lines fail, the whole run is refused
(`unverified_answer`) and nothing is stored (the tokens used are still counted).

**CN4 - Numbers and names are shown as the buyer said them.** The `value` of a stated line must itself be a
substring of its quote. The service never converts, adds up or rounds ("around one and a half crore" stays
that; it is not turned into `15000000`). The checklist shows the quote beside the value so a rep can see both.
Amounts are never written into any money field.

**CN5 - Who spoke is not known in v1, and the screen says so.** The transcript has no speaker labels. The
model is asked to mark a quote as coming from the buyer only when the wording makes that clear ("my budget
is...") and to mark it `assumed` otherwise; the card shows beside every line **"Speaker not verified -
listen at 3:12"**, with a button that plays the cleaned copy at that time (the clip player already exists).
Speaker separation (two-channel recordings or diarisation) is a separate later decision (question 3).

**CN6 - The organisation picks the frame; the frame is fixed data.** `call_note_settings`: one row per
organisation holding `framework` = `bant` or `meddic` (default `bant`), with a version check. The two frames
and their field lists live in code (a fixed list, not editable text), so a typo or a clever instruction cannot
add a field. A run records the frame it used; changing the frame never rewrites old drafts. Permission
`call_notes:manage` (tenant administrators) changes it.

**CN7 - The only way to change the CRM is a proposal.** From a draft, the service may create **proposals
through the approval queue** (so the Sentinel applies and a *different* person approves, ADR 0014):

- **Buyer memory assumptions**, kind `buyer_memory.add_assumption` (new, narrow): target the lead, payload =
  one buyer-memory key, a short value, a reason that cites the call and the time. **Always an assumption**,
  never a fact (ADR 0028 BM5: a fact needs a person to confirm it with the buyer's words). Only lines that
  map to a buyer-memory key are eligible: BANT budget -> `budget`, authority -> `decision_makers`, need ->
  `must_haves`, timeline -> `timeline`; MEDDIC economic buyer -> `decision_makers`, decision criteria ->
  `must_haves`, identify pain -> `purpose`, metrics, decision process and champion stay on the checklist
  only. (The mapping is a reviewed table in code; question 4.)
- **One follow-up task** (`activity.create_task`, existing kind) for the unknown lines ("Ask about budget and
  timeline"), at most one.

At most 5 buyer-memory proposals and 1 task per run, in addition to the per-person pending limit that already
exists. **No** status change, assignment, discount, deal-stage change, e-mail or delete - none of those kinds
is offered to this agent. The model never supplies an id or an address: the lead, the recording and the times
come from the server, and the buyer-memory key from a fixed list.

**CN8 - Governed like every other AI agent.** Registry entry `call_notes` (uses a model, **off by default**):
switch, monthly token budget, tool filter, platform kill switch, tokens and estimated cost on the AI agents
page. The call is wrapped in `governed`. The model has **one tool**, `submit_notes`, whose arguments are
checked strictly (no extra fields, enumerated field names, bounded lengths, bounded number of lines, no
links). A bad answer is refused and stored nowhere.

**CN9 - The transcript is untrusted text.** It is cleaned with the shared screening before it reaches the
model (links, markup, hidden characters out), it is given to the model **as data inside a clearly marked
block**, and an instruction-like passage in it is reported (a "Safety check" note on the draft) but cannot
add a tool, a field or a proposal kind: the model can only call `submit_notes`, and everything that follows
is checked by code. What the model writes (notes, values, reasons) is cleaned again on the way out (no links
or images), and every proposal goes through the Sentinel.

**CN10 - What the model is given, and what it is not.** The model gets the cleaned transcript (with segment
times), the language, and the frame's field list. It does **not** get the lead's name, phone, e-mail, address
or the audio, and not other leads. A transcript longer than **60,000 characters** is refused
(`transcript_too_long`) in v1 - no splitting - because a 60-minute call is about 9,000 words. The transcript
text leaves the CRM to the model provider the organisation has already chosen for its agents, so the privacy
notice names that (ADR 0030 already names the speech vendor).

**CN11 - Access, limits, retention, audit.** Asking needs `call_notes:run` (sales agents, managers,
administrators) **and** the lead must be readable and `call:read` held (else 404, and the model is never
called). Limits: 3 runs per recording per day, 20 per person per hour, 100 per organisation per day
(settings, can be lowered only by an administrator). Each run creates a **new insert-only version**; the
newest is shown, older ones stay visible. Draft rows are deleted with the recording row's retention (the same
rule as the transcript) and the database refuses edits. Audit entries hold ids, the frame, counts and codes
only - never the quotes or values.

## 4. What this does not do

No live (during the call) notes; no speaker identification; no reading of audio by a model; no chunking of
very long calls; no automatic run when a transcript finishes (a person presses a button, like ADR 0034 AB7);
no writing of facts into buyer memory; no change to a lead's status, owner, budget fields or a deal; no
scoring or "win probability" (that is a later item on the owner's list); no custom checklists; no sending
anything to the buyer.

## 5. Steps (Phase CN), each ends with a stop for review

Each step is a separate, reviewed change with a failing test first and deliberate breaks of each new
protection; the browser steps add a Playwright journey.

| Step | What | Done when |
|---|---|---|
| CN0 | This ADR, the index line and the status entry (documents only) | Owner answers section 6; status Accepted |
| CN1 | Pure part, no model: the two frames, the line states, the literal quote check (CN3), the value-inside-quote rule (CN4), the buyer-memory key mapping, cleaning. Migration: `call_notes` (header: recording, lead, frame, model name, tokens, counts of downgraded lines, safety notes) and `call_note_lines` (one row per field), `call_note_settings`; forced RLS, insert-only (trigger + no UPDATE privilege), database checks for the three states | pure tests incl. quote checks on Hindi and Telugu text; RLS guard and migrations-in-sync pass |
| CN2 | Service `run_notes` (governed, registry entry `call_notes` off by default, strict `submit_notes` tool, verification, limits, audit) and a scripted model for `CRM_AI_PROVIDER=fake`; no endpoint yet | database tests: a colleague's lead = 404 and no model call, switch off, budget, platform switch, invented quote downgraded, more than half unverified refused, transcript too long, injection in the transcript, tenant isolation |
| CN3 | API: `GET/PUT /api/v1/call-notes/settings`, `POST /leads/{id}/calls/{call_id}/notes`, `GET .../notes` (newest + versions); permissions `call_notes:manage` / `:run`; OpenAPI refreshed | API tests: role denial, ID tampering (made-up recording, a recording of another lead), the client cannot send tenant, lead, frame or counts |
| CN4 | Proposals (CN7): approval kind `buyer_memory.add_assumption` (always an assumption; checked again at approval), the follow-up task, caps, Sentinel rules, `agent_actions` author `call_notes` (migration widens the allowed authors, as 0069 did); the buyer memory API gains the narrow call it needs | tests: never a fact, a lead changed in between = failed approval, no self-approval, caps, a line without a mapping is not proposable |
| CN5 | Screens: an **AI notes** block under a recording (state labels *Stated / Assumed / Unknown*, quote, time with a "listen here" button, "speaker not verified" text, the draft label, safety note, "Ask for proposals" with a plain-words preview), an administrator's **Call notes** settings (choose BANT or MEDDIC, see the field lists), the approval card says "from the call notes agent" | component tests; Playwright journey (agent runs notes on a scripted recording, sees each state, asks for proposals, a manager approves one and only then does buyer memory show it as an assumption) |
| CN6 | BP-10: a call-notes suite of scripted cases through the real service (quotes in Hindi and Telugu, an invented quote, a poisoned transcript, wrong field name, extra fields, over-long answer, forbidden kinds); `docs/call-notes.md`; CLAUDE.md status | evaluation gate in CI; deliberate breaks of the protections caught; one optional paid real-model run reported honestly |

Nothing is switched on in staging by default, and staging is not touched by any of these steps.

## 6. Questions for the owner (recommended answer first)

1. **Which frame?** *Recommended:* the organisation chooses BANT or MEDDIC in settings, default BANT (fits
   home buyers). Alternative: both frames on every call (longer, noisier).
2. **Do notes change the lead?** *Recommended:* no - the draft is shown only; anything that reaches the lead
   is a proposal a different person approves. Alternative: write the checklist straight into buyer memory
   (breaks the "a person confirms facts" rule of ADR 0028).
3. **Speaker identification.** *Recommended:* not in v1; every line shows "speaker not verified" and a play
   button so the rep checks by listening. Alternative: wait for two-channel recordings or diarisation before
   building this (more accurate "buyer said", but delays the feature and needs another ADR).
4. **What may become a proposal?** *Recommended:* buyer-memory **assumptions** for the four-to-five lines
   that map to a key (CN7), plus one follow-up task for unknowns. Alternative: only the task, nothing for
   buyer memory in v1.
5. **Does the transcript go to the AI model provider?** *Recommended:* yes, text only, without the lead's
   name or contact details, to the provider the organisation already uses for agents, named in the privacy
   notice. Alternative: a local model only (needs a bigger server and is weaker in Telugu).
6. **Long calls.** *Recommended:* refuse above 60,000 characters in v1 and say so; revisit if real calls hit
   it. Alternative: split long transcripts (more calls, more cost, needs merge rules).
7. **How is a quote judged "found"?** *Recommended:* literal match after trimming spaces and normalising case
   and punctuation; anything else is downgraded to unknown. Alternative: allow a fuzzy match for spelling
   differences in Hindi and Telugu (finds more, but could "verify" a slightly different sentence).
8. **When does it run?** *Recommended:* only when a person presses "Create call notes" (like ADR 0034).
   Alternative: automatically when a transcript is ready (cost and noise; a second decision).
9. **Limits and switch.** *Recommended:* off until an administrator switches it on, 3 runs per recording per
   day, 20 per person per hour, 100 per organisation per day. Alternative: your numbers.

## 7. Alternatives considered

- **Fill buyer memory directly from the call.** Rejected: it turns a machine's reading of a noisy transcript
  into "facts", the exact problem ADR 0028 exists to prevent.
- **A model that scores the deal in the same step.** Rejected for now: a score invites trust the quotes do not
  justify; the owner's list has "deal risk forecast" as its own item, which can read these drafts later.
- **Free-text, per-organisation checklists.** Rejected: an editable prompt is an injection surface; two fixed,
  well-known frames cover the request and keep the data comparable (ADR 0034 makes the same argument).
- **Reusing the custom-agent builder for this.** Rejected: its read sets are records, not a transcript, and
  this feature needs a code-side quote check, which a recipe cannot express.

## 7a. Amendment (2026-11-16, while building CN1)

Small corrections found while writing the rules, all of them narrowing:

1. **An assumed line also carries a short value** (what the agent thinks), because a buyer-memory
   assumption needs one. Only a *stated* line must have its value inside its quote; an assumed value is
   free text but is cleaned, labelled "assumed" and always shown next to its reason.
2. **The time of a line is the transcript's, not the model's.** The code finds the quote in the stored
   segments near the time the model named (2 seconds of slack either side) and stores the start of the
   first and the end of the last segment that hold the words. A line may point at no more than 300 seconds.
3. **A quote needs at least four letters or digits** (otherwise "yes" would "prove" anything), and the
   model may name a window of at most 120 seconds.
4. **Free call notes are lines too** (field `note`, always a stated line with a quote), at most 8 per
   draft; a note whose quote is not found is dropped and counted, not turned into unknown.
5. **One list of "kinds of finding"** (`cleaned_codes`) on each draft records what was cleaned out of what the
   model wrote and any instruction-like words the transcript contained; never the text itself.

## 8. Consequences

- A rep (or a manager reviewing a call) sees, per field, what was said, what is only hinted at and what is
  still unknown, with the exact moment to listen to - and cannot be misled by an invented quote, because code
  checks every quote against the transcript.
- New module `call_notes`, three tenant tables (forced RLS, insert-only), two permissions, one registry entry,
  one new approval kind and a new approval author; the BP-10 harness gains a suite.
- Cost and risk: a model reads a buyer's words (privacy notice and the kill switches apply); accuracy on
  noisy Hinglish and Telugu transcripts is limited by the transcript itself (the trial of ADR 0030 has still not
  been run on real audio), which is why every draft is labelled and every proposal needs a second person.
