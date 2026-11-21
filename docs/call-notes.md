# Call notes and a deal checklist (ADR 0035)

Status: **CN1 (rules, tables) built 2026-11-16, CN2 (the governed run) built 2026-11-17.** There is no
endpoint or screen yet (CN3-CN6). Nothing calls the run from the web app, so no model reads a transcript
in practice until CN3.

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

## The run (CN2) - `call_notes/service.py`, `answer.py`, `llm.py`
`run_notes(session, principal, model, lead_id, call_id, ...)` does, in this order:

1. **Who:** a staff member with `call_notes:run` **and** `call:read` (sales agents, managers, administrators;
   support and customers are refused). New permissions: `call_notes:run`, `call_notes:manage` (administrators,
   used from CN3).
2. **Which transcript:** `calls_api.transcript_of` - only of a lead the person may read (else 404, so a
   colleague's lead or another organisation's looks the same as a made-up id); a recording without a finished
   transcript is a 409. The model is not called for any of these.
3. **Size:** a transcript over 60,000 characters or with nothing readable is refused before the model.
4. **Limits** (settings `CRM_CALL_NOTES_PER_RECORDING_DAY` 3, `_PER_USER_HOUR` 20, `_PER_TENANT_DAY` 100):
   counted from stored drafts; over the limit is a 429 and the model is not called.
5. **The gate:** a new registry agent `call_notes` (**off by default**, one tool `submit_notes`): switch,
   monthly token budget, tool filter and the AI platform switch all apply (ADR 0016). Tokens are counted
   even when the answer is refused.
6. **What the model sees:** the transcript cleaned like any untrusted text (links, markup and hidden
   characters out; instruction-like words are reported and the prompt says so), each line as
   `[start_ms-end_ms] text` inside marked data, the language and the checklist fields. Never the lead's
   name, contact details or ids, never the audio.
7. **The answer:** exactly one `submit_notes` call, read strictly (`answer.parse_answer`: nothing extra,
   only the fields of the chosen frame, whole-number times), then every quote is checked against the
   transcript the model saw (`rules.verify`, CN1). A badly shaped answer, or one where more than half of the
   quotes fail, is a 422 `call_notes_bad_answer` / `call_notes_unverified_answer` and nothing is stored.
8. **The draft:** one insert-only `call_notes` row (next version for the recording) with its lines, and an
   audit entry `call_notes.created` with ids, counts and kinds of finding - never a quote, value or reason.
   **Nothing else in the CRM changes**: no lead, no buyer memory, no proposal (CN4 adds those).

`CRM_AI_PROVIDER=fake` uses a scripted model (`llm.FakeCallNotesModel`) that quotes the first transcript line
for the first checklist field, so a demo shows a real, verifiable quote.

## Still to build
CN3 the API (settings and `POST/GET /leads/{id}/calls/{call_id}/notes`), CN4 the proposals through the
approval queue, CN5 the screens, CN6 evaluation cases.
