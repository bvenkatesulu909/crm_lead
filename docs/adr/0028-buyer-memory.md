# ADR 0028 — Buyer memory: every detail labelled a fact, an assumption or a gap

- **Status:** Accepted (2026-11-12) with the recommended answer to all seven questions in section 6
- **Date:** 2026-11-12
- **Deciders:** Project owner
- **Depends on:** ADR 0013 (website chat), ADR 0017/0018 (cleaning of untrusted text), ADR 0014
  (approvals - for the later AI step), ADR 0027 (language on the lead)
- **Used by:** the rep's brief before a site visit (next item) and, later, call summaries

## 1. The problem

A salesperson who calls a home buyer needs to know what is *known*. Today that knowledge is scattered:
a few fields on the lead (property type, budget, location), free-text notes on the timeline, and the
website conversation. Two things go wrong. People forget what was said, and - worse - **a guess gets
written down and later read as if the buyer said it** ("budget 1.5 Cr" that was really "sounded like
around 1.5"). An assistant that reads those notes repeats the guess as a fact.

Buyer memory is one small, structured place for what we know about a buyer, where **every detail says
which of three things it is** and where it came from:

- **Fact** - the buyer said it or confirmed it, and we can point to where.
- **Assumption** - we think it, nobody confirmed it; it says why we think so.
- **Gap** - we do not know it yet and a rep would want to.

## 2. What exists

- `leads` carries `property_type`, `budget_min_inr` / `budget_max_inr`, `location`, `preferred_language`.
- The timeline (`lead_activities`) holds notes, calls, e-mails and meetings as free text.
- The website chat keeps its transcript for the lead (`public_chat`), and the lead agent / Qualifier read a
  lead's fields. None of them can tell a stated detail from a guessed one.
- Modules may only use each other through `api.py`; every tenant table has forced row-level security;
  anything an AI writes must be cleaned and, if it changes the CRM, approved by a person (ADR 0014).

## 3. Decisions (proposed)

**BM1 - One new module, `buyer_memory`, one table, per lead.** `buyer_memory_items`: the lead, a **key**
from a fixed list, a **value** (short text), a **status** (`fact` | `assumption`), where it came from and
who recorded it. Rows are **never edited or deleted**: a change adds a new row and the newest row for a key
is the current one, so the history of what we believed and when stays. The tenant comes only from the
verified token; the lead is loaded through the leads module, so a person can only read or write the memory
of a lead they may read (else 404).

**BM2 - A fixed list of keys, not free-form.** Twelve keys cover what a rep asks before a site visit:
`budget`, `property_type`, `location`, `timeline` (when they want to buy), `purpose` (own use or
investment), `financing` (loan, cash, pre-approved), `household` (who will live there), `decision_makers`,
`must_haves`, `deal_breakers`, `current_home` (rent, own, selling), `other_options` (other projects they
are looking at or visited). A fixed list keeps the data comparable, lets the screen show gaps, and keeps
sensitive categories (caste, religion, health, politics) out by construction.

**BM3 - A gap is not stored, it is worked out.** A key with no current item is a gap. The screen lists the
gaps ("not known yet: timeline, financing, ...") so the rep knows what to ask. An answer turns a gap into a
fact or an assumption; nothing has to be "deleted".

**BM4 - A fact must cite a source; an assumption must give a reason.** The sources a fact may name are
fixed: `website_chat` (the conversation), `timeline_entry` (a note, call or meeting of this lead - by id),
`lead_record` (a field on the lead form), `buyer_confirmed` (a rep asked and the buyer confirmed; with
the date). Each fact also keeps a short **quote** of what the buyer said (at most 300 characters). An
assumption keeps a **reason** ("sounded like 1.5 Cr when we spoke about the Kokapet flat"). A fact with no
source is refused. **Confirming** an assumption adds a new row as a fact; the assumption stays in the
history.

**BM5 - A person writes; an AI never writes a fact.** In v1 staff who may write the lead (the same people
as for lead updates) add and confirm items. No model is involved in v1. In a later step an AI may *suggest*
items from a conversation or a call transcript, but only as **assumptions**, only through the approval
queue (ADR 0014) and the Sentinel, and never as a fact - a fact needs a person to confirm it.

**BM6 - Seeded from what we already know, honestly labelled.** When the website chat saves a lead, the
details the visitor gave (property type, budget, location) are written as **facts** with source
`website_chat`; the lead's notes from the chat are not turned into facts. For other leads, the lead form's
fields can be copied in one click as facts with source `lead_record`. Nothing is guessed on the way.

**BM7 - Cleaned like everything a visitor or a model can influence.** Every stored value, quote and reason
goes through the same cleaning as the website chat (hidden text, markup, images and links removed;
instruction-like text kept but reported); a card number is refused. Values are shown as plain text. The
screen says in one line what must not be recorded here (religion, caste, health, politics, ID numbers).

**BM8 - Audit, retention, erasure.** Writes are audited (ids and the key, not the value). Buyer memory is
deleted with its lead when the organisation anonymises or removes it, and it is covered by the same
retention rules as the lead's timeline. It is shown only on the lead page and in the future rep's brief.

## 4. What this does not do

No AI writing or guessing in v1; no free-form keys; no editing of history; no sharing between leads or
organisations; no automatic copying to the account or contact on conversion (the lead page stays
reachable, so the memory stays reachable); no sensitive categories.

## 5. Steps (Phase BM), each stops for review

| Step | Content |
|---|---|
| BM0 | This ADR (documents only) - **done 2026-11-12** |
| BM1 | Backend: migration (table, forced RLS, no UPDATE/DELETE for the app role), pure rules (keys, statuses, source and quote/reason checks, cleaning), service, `api.py`, permissions `buyer_memory:read` / `:write`, endpoints (`GET`/`POST /leads/{id}/memory`, confirm), audit, seeding from the website chat and from the lead form - **done 2026-11-12**: migration 0059 `buyer_memory_items` (forced RLS; the database refuses a fact without a source and quote, an assumption without a reason, an unknown key or status, and any UPDATE - a trigger plus no UPDATE/DELETE privilege for the application role), pure rules, service, `/api/v1/leads/{id}/memory` (read, add, confirm, copy from the lead form), permissions `buyer_memory:read` / `:write`, seeding from the website chat (facts citing the conversation; no guesses, the chat's notes are not turned into facts); see docs/buyer-memory.md |
| BM2 | Lead page card: three groups (Facts, Assumptions, Gaps), add / confirm dialogs, sources shown, history, "copy from the lead form" - **done 2026-11-12**: `buyer-memory-card.tsx` / `-views.tsx`, Server Actions that send only the fields the API accepts (a fact is always "the buyer confirmed" with its quote), plain-text display, read-only users see no forms; the form offers only "the buyer told us" as a source (citing a timeline entry stays API-only in v1) |
| BM3 | Tests (tenant isolation, role denial, record-level denial, ID tampering, a fact without a source, cleaning), Playwright journey, docs, `docs/buyer-memory.md` |

(A later step, not part of the short version: AI suggestions as assumptions through the approval queue.)

## 6. Questions for the owner (recommended answer first)

1. **Where it lives.** *Recommended:* per lead (one module, one table). Alternative: per contact or
   account, so it follows the buyer after conversion.
2. **The keys.** *Recommended:* the fixed list of twelve above. Alternative: free-form keys (more flexible,
   no gap list, a way for sensitive data to creep in).
3. **Who writes.** *Recommended:* staff who may write the lead; AI only later, only as assumptions, only
   through approval. Alternative: let a model write facts directly (not recommended).
4. **A fact must cite a source.** *Recommended:* yes, with a short quote. Alternative: a free "confirmed"
   tick without a source.
5. **History.** *Recommended:* append-only, newest row wins. Alternative: overwrite in place (loses what we
   believed earlier).
6. **Seeding.** *Recommended:* website chat details become facts automatically; the lead form can be copied
   in one click. Alternative: no seeding.
7. **Switch.** *Recommended:* no registry switch (no AI in v1); the permission decides. Alternative: an
   on/off switch per organisation like the AI agents.

## 7. Consequences

- A rep opens a lead and sees at once what the buyer really said, what we only think, and what is still to
  ask - and can tell which is which when briefing a colleague or an assistant.
- The brief before a site visit (next item) reads this instead of free-text notes, so it can say "fact" and
  "assumption" honestly.
- One more tenant table (with forced row-level security, like the others) and one more module.
- The value of the memory depends on reps filling it in; the website chat seeding and the one-click copy
  from the lead form keep the first entry cheap.
