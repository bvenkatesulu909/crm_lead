# Call notes and a deal checklist (ADR 0035)

Status: **CN1 (rules, tables) built 2026-11-16; CN2 (the governed run), CN3 (the API) and CN4 (proposals)
built 2026-11-17.** There is no screen yet (CN5-CN6). The feature stays off until an administrator switches the `call_notes`
agent on (AI agents page or `PATCH /api/v1/agents/call_notes`).

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

## The API (CN3)
| Endpoint | Who | What |
|---|---|---|
| `GET /api/v1/call-notes/settings` | sales agents, managers, administrators | The chosen frame (`bant` until an administrator chooses), its `version` (0 before the first choice) and the fields of both frames with labels and hints. |
| `PUT /api/v1/call-notes/settings` | administrators | Body: `framework` (`bant` or `meddic`) and `version` (what the screen last saw; 0 or absent for the first choice). Nothing else is accepted. A stale version is a 409. Saving the frame already chosen changes nothing. Audit `call_notes.framework_changed` (from, to). |
| `POST /api/v1/leads/{lead}/calls/{call}/notes` | people with `call_notes:run` | **No body**: the lead and call are in the address, the frame is the organisation's. 201 with the draft. Errors: 403 (no permission), 404 (lead or call not found or not readable), 409 (no transcript yet), 422 (`call_notes_bad_answer`, `_unverified_answer`, `_transcript_too_long`, `_no_transcript`), 429 (`call_notes_rate_limited`), 503 (agent off, over budget, platform switch). A refused answer still keeps the tokens it used. |
| `GET /api/v1/leads/{lead}/calls/{call}/notes` | same | `{newest, versions}`: the newest draft (or null) and every version, newest first. |
| `GET /api/v1/leads/{lead}/calls/{call}/notes/{n}` | same | One version. |

A line in a draft has: `field`, a `label`, `state` (`stated`, `assumed`, `unknown`), `value`, `quote`,
`start_ms` / `end_ms` (the transcript's own time), `reason` (assumed only) and `note_code` (why a claim became
unknown). The response carries no tokens, tenant, prompt or raw model answer.

## Proposals (CN4)
A draft changes nothing. A person can turn chosen lines into **proposals** in the approval queue; a
DIFFERENT person approves each one (no self-approval, as for every AI suggestion) and the Sentinel checks
each first.

| Endpoint | What |
|---|---|
| `GET /api/v1/leads/{lead}/calls/{call}/notes/{n}/proposals/preview?positions=..&follow_up_task=..` | What would be suggested, in plain words. Stores nothing. |
| `POST /api/v1/leads/{lead}/calls/{call}/notes/{n}/proposals` | Body: `positions` (line numbers; none = every line that can be suggested) and `follow_up_task` (default true). Nothing else is accepted - the key, value, lead and call come from the stored draft. Returns one result per proposal: `proposed`, `blocked` (by the safety check), `refused` (for example the buyer already confirmed it) or `skipped` (too many waiting). |

- **Buyer memory, assumptions only.** New approval kind `buyer_memory.add_assumption` (author
  `call_notes`, migration 0072): payload `key` (one of the twelve), `value`, `note` (the call and the moment),
  `call_id`, `at_ms`. It has no status field, so it can only ever record an **assumption**, even for a
  *stated* line - the speaker is not verified (ADR 0035 CN5) and a fact needs a person to confirm it with the
  buyer's words. Which lines can be suggested is a reviewed table: budget, authority, need and timeline for
  BANT; economic buyer, decision criteria and identify pain for MEDDIC. Metrics, decision process and champion
  stay on the checklist. At most 5 per request.
- **Never over a confirmed fact.** A newer buyer-memory row replaces the older one, so the kind refuses a key
  whose current entry is a fact - when the suggestion is made, and again when it is approved (then the
  approval ends `failed` and nothing changes). The same assumption twice is refused as pointless.
- **One follow-up task** (`activity.create_task`) for the unknown lines ("Ask the buyer about need and
  timeline", due in 2 days, for the person who asked), built from fixed labels.
- The approver records the assumption; the approval card shows "Note in the buyer memory, as an assumption
  (not a fact)", the plan and the outcome like every other kind.
- Asking twice does not fill the queue: the Sentinel blocks an identical waiting proposal. The audit entry
  `call_notes.proposed` has ids and counts only. No model is called.

## Still to build
CN5 the screens, CN6 evaluation cases.
