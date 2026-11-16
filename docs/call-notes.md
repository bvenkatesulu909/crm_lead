# Call notes and a deal checklist (ADR 0035)

Status: **CN1 built 2026-11-16** (the rules and the tables). Nothing calls a model yet and there is no
endpoint or screen; those are CN2-CN6. Today no model reads a transcript.

## The idea in one paragraph
After a recorded sales call has a transcript, a rep will be able to ask for notes and a BANT or MEDDIC
checklist. Each line says whether the buyer **stated** the answer (with a quote and the moment on the
recording), whether it is only **assumed** (with a reason), or **unknown**. The model's answer is never
trusted: code checks every quote against the stored transcript, word for word, and a quote it cannot find
turns the line into *unknown*. Anything that should reach the lead later goes through the approval queue
as a buyer-memory **assumption**.

## What exists now (CN1)

### The pure rules - `backend/app/modules/call_notes/rules.py`
- **Two fixed frames.** BANT: budget, authority, need, timeline. MEDDIC: metrics, economic buyer, decision
  criteria, decision process, identify pain, champion. Each field has a label, a hint for the model and, where
  it makes sense, the buyer-memory key a proposal would use (budget -> `budget`, authority and economic buyer
  -> `decision_makers`, need and decision criteria -> `must_haves`, timeline -> `timeline`, identify pain ->
  `purpose`; metrics, decision process and champion stay on the checklist only).
- **`normalise`** ignores case, punctuation and spacing and nothing else; vowel signs of Hindi and Telugu are
  kept, so a different word never matches.
- **`locate_quote`** looks for the quote in the stored segments near the time the model named (2 seconds of
  slack) and returns the **transcript's own** start and end.
- **`verify`** turns a model's claims into stored lines: a missing quote, a quote under four letters, a bad or
  over-long time window, a quote that is not in the transcript, or a stated value that is not part of its
  quote all become *unknown* with a code. A badly shaped answer (a field not in the frame, a field twice, an
  unknown line holding data, a stated line without a value) is refused whole, and so is an answer where more
  than half of the quotes fail. Numbers are never converted: "around one and a half crore" stays as said.
  What the model wrote is cleaned (links and markup out) and the kinds of finding are reported.
- Limits: value 150 characters (a note 200), quote 300, reason 300, at most 8 notes, a transcript of at most
  60,000 characters, at most 5 buyer-memory proposals per run later.

### The tables (migration 0071, forced row-level security)
- `call_notes` - one drafted note per recording and version: frame, model, tokens, how many claims were
  turned into unknown, kinds of finding. `call_note_lines` - its lines. Both are **insert-only**: a trigger
  refuses every UPDATE and an early DELETE (under 365 days) and the application role has no UPDATE or TRUNCATE.
- The database itself keeps the three states apart: *stated* needs a value, a quote and its time and no
  reason; *assumed* also needs a reason; *unknown* holds nothing but, at most, a code. A free note (field
  `note`) can only be a stated line. A checklist field appears once per note.
- `call_note_settings` - one row per organisation holding its frame (`bant` default or `meddic`), with a
  version check.

## Still to build
CN2 the run (governed model, registry entry `call_notes` off by default), CN3 the API and settings, CN4 the
proposals through the approval queue, CN5 the screens, CN6 evaluation cases.
