# Video briefs (ADR 0041)

The CRM writes the **brief** for a personalised video to a buyer; a person or a tool the organisation trusts
makes the video. Nothing in the CRM creates a video, an avatar or audio.

## What VB1 does (built 2026-11-21)

`GET /api/v1/leads/{lead_id}/video-brief?goal=&language=&tone=&length=` builds a brief on demand. Nothing is
stored and nothing is written (a test counts the rows).

| Choice | Values | Default |
|---|---|---|
| `goal` | introduce, follow_up, after_visit, explain_quote, revive | follow_up |
| `language` | en, hi, te | the lead's preferred language, else en |
| `tone` | warm, professional, brisk | warm |
| `length` | 30, 60, 90 (seconds; about 75 / 150 / 225 words) | 60 |
| `quote_id` | an approved, sent or accepted quote of the account this lead became (optional) | none |

The answer holds: the buyer's **first name only**, the facts it knows (each marked **fact**, **assumption** or
**lead form**, with its source and quote), a **script** (greeting, intro for the goal, up to five fact lines,
one question per assumption, a closing for the goal), the fixed **must say** and **must not say** lists, the
**consent notes**, and **cautions**.

## The rules that keep it honest

- A buyer-memory **fact** may be spoken as a statement. An **assumption** is only ever a question ("Is ... still
  right for ...?"). What the lead form says is shown but never spoken.
- A value with a phone number, e-mail address, card number or instruction is left out and reported.
- Links, markup and hidden characters in stored values are cleaned before they reach the script.
- The phone number, e-mail address and last name never appear in the answer.
- A script longer than the chosen length gets the caution `script_too_long`.
- Banned kinds of statement (guaranteed returns, false urgency, religion, health, a named competitor) are
  detected by `rules.banned_phrases_in`; the built script is checked with it.

## Price facts from a quote (VB1b, built 2026-11-21)

With `quote_id` the script gets up to three price lines (product description and the line total) and a total
with the quote's validity date. Every line cites the quote number, and the amounts are shown exactly as stored:
rupees with the rupee sign and lakh grouping (`₹1,20,00,000`), another currency with its code. Rules:

- The quote must be readable by the person **and** belong to the account the lead became (`converted_account_id`).
  Any other quote, a made-up id, or a lead that was never converted gives **404** `quote_not_found`.
- Only an **approved, sent or accepted** quote may be used; a draft, pending, declined or replaced quote gives
  **422** `video_brief_quote_not_ready`.
- Only the figures are read (`quotes_api.price_facts`): never the internal or customer notes.
- A product description with a link is cleaned; one with a phone number is left out and reported.

## The screen (VB2, built 2026-11-22)

A **Video brief** button on the lead page (next to *Site visit brief*, for people with `video_brief:read`) opens
`/print/leads/{id}/video-brief`: one column made for a phone and for paper, with a **Print / Save as PDF** button.
A form on the page chooses the goal, language (the buyer's own by default), tone, length and, when the lead
became an account, one of its approved, sent or accepted quotes. The choices live in the address; the page
checks them against the same fixed lists and falls back to the defaults, and the API checks them again.

The page shows the script line by line (with how long each takes and which fact it came from), what the brief
is built from (each line marked **Fact**, **Assumption**, **Lead form** or **Quote**, and what happens to it:
lead-form details are shown but never said, assumptions are only asked as questions), the **Say this** and
**Never say this** lists, **Consent and privacy** and **Be careful**. A script longer than its length is marked in
red. A refused quote never blocks the brief: the page says why and builds it without prices. Everything is
shown as plain text. The CRM still makes no video.

Tests: `src/lib/video-brief.test.tsx` (22 Vitest tests: choices, paths, the view, the page) and
`e2e/video-brief.spec.ts` (one Playwright journey: nothing confirmed -> lead form shown but not said; copy the
lead form into buyer memory -> three facts in the script; Hindi, 30 seconds and another goal; an altered
address falls back to the defaults; a colleague gets "not found", a manager can open it, support cannot).

## Saved hand-written scripts (VB3, built 2026-11-22)

A rep may write the script themselves and keep it. `POST /api/v1/leads/{id}/video-scripts` saves the lines as
the **next version** of the lead's script (`GET` lists them, newest first). Permission `video_brief:write`
(sales agents, managers, administrators) and the lead's own read rules; a lead the person may not read is a 404.

- The body holds only `language`, `tone`, `goal`, `length_seconds` (30 / 60 / 90) and up to 12 `lines` of at
  most 300 characters; anything else (tenant, version, source, author) is refused. The server sets those.
- Each line is cleaned (links, markup, hidden characters out) and **refused** with a stable code - never
  repeating the text - when it looks like a card number or an instruction (`script_unsafe_text`), holds a
  phone number or e-mail address (`script_contact_detail`), holds a banned kind of statement
  (`script_banned_phrase`), or when the whole script has no words (`script_empty`), is longer than its length
  (`script_too_long`), or a line is too long (`script_line_too_long` / `script_too_many_lines`).
- At most `CRM_VIDEO_SCRIPTS_PER_USER_HOUR` (30) saves per person per hour (429 `video_script_rate_limited`).
- Table `video_scripts` (migration 0077): forced row-level security, database checks for every fixed list, and
  **insert-only** - a trigger refuses every UPDATE and a DELETE of a row younger than 365 days, and the
  application role has no UPDATE or TRUNCATE. `source` is `hand_written` now; an approved AI draft (VB5) will be
  `ai_draft`.
- Saving is audited (`video_script.saved`) with ids, the version, the word count, the language and the source -
  never the words.

### The screen for it (VB3b, built 2026-11-22)

On the video brief page, people with `video_brief:write` get **Write your own script**: a box that starts from the
script the CRM suggests, a live count against the chosen length (red when over), and **Save script**. The goal,
language, tone, length and quote travel as hidden fields - the ones the brief above was built for - so they cannot
be edited there. The Server Action checks the lead id, the fixed lists and the script first, and sends only the
five fields the API accepts (language, tone, goal, length, lines). A refusal is explained in plain words (phone
number, card number or instruction, never-say list, too long) and the typed text stays. After a save the page
says "saved as version N" (only a plain number is ever shown) and lists the **saved scripts**, newest first, as
plain text; people who may only read still see that list. Failing to load the list never stops the brief.

Tests: `src/lib/video-scripts.test.tsx` (22 Vitest tests) and `e2e/video-script.spec.ts` (one Playwright journey).

Not built yet: copying a saved script to a document on the lead.

## The drafted script (VB4, built 2026-11-22)

`POST /api/v1/leads/{id}/video-brief/draft` asks a governed model to write the spoken script. Body: `goal`,
`language`, `tone`, `length_seconds` and an optional `quote_id` - **only the choices**; the facts are read by the
server as the person asking (the same brief as above). Permission `video_brief:write` and the lead's read rules
(a lead the person may not read is a 404 and the model is never called).

- **A governed agent, off by default.** Registry entry `video_brief` ("Video script drafter"): an administrator
  switches it on; the monthly token budget, the tool filter and the AI platform switch apply (503
  `agent_unavailable` / `agent_budget_reached`). Limits `CRM_VIDEO_BRIEF_PER_LEAD_HOUR` (3) and
  `CRM_VIDEO_BRIEF_PER_TENANT_DAY` (100) -> 429 `video_draft_rate_limited`.
- **What the model sees:** the buyer's first name, the choices, the confirmed facts, a quote's prices exactly as
  stored, and - in a separate list - the assumptions it may only ask about. Never the phone, e-mail, last name,
  an unconfirmed lead-form detail, or another lead. Everything is cleaned and passed as data; text that looks
  like an instruction is flagged to the model.
- **One tool, `submit_script`:** exactly `lines` and `reason`, nothing else.
- **What code checks afterwards** (refusing with a 422 `video_draft_*` code that never repeats the text, and
  keeping the tokens the call used): the shape of the answer; every check of a hand-written script (cleaning,
  card numbers and instructions, contact details, banned statements, the length); **every number, amount and date
  must be one of the supplied facts** (`video_draft_unsupported_number`); an assumption may only be asked, never
  said as a statement (`video_draft_assumption_stated`).
- **The answer is a draft:** `status: "draft"`, shown to the person who asked. **Nothing is saved and nothing is
  approved** - the approval queue is the next step (VB5). The audit entry `video_brief.drafted` holds ids, the
  word count and the language only.
- `CRM_AI_PROVIDER=fake` uses a scripted model that builds a plain English script from the facts.

Limits of the checks, honestly: amounts spoken in words ("one and a half crore") and names of projects or people
are not verified by code; the banned-statement list, the human approval of VB5 and the native-speaker read-through
of Hindi and Telugu remain the guards for those.

Tests: `tests/test_video_brief_draft.py` (22 pure tests) and `tests/db/test_video_brief_draft_api.py` (28
database tests: switch, platform switch, budget, limits, roles, colleague and other organisation, made-up ids,
only the documented fields, each kind of refused answer).

## Sending a drafted script for approval (VB5, built 2026-11-23)

`POST /api/v1/leads/{id}/video-brief/propose` puts a drafted script into the approval queue. Body: the choices
(`goal`, `language`, `tone`, `length_seconds`, optional `quote_id`) and the `lines`. Permission
`video_brief:write`, the lead's read rules and the right to propose (`agent_action:propose`).

- **The drafter must be switched on.** This is its output, so a person cannot queue a script while it is off (503
  `agent_unavailable`). No model is called here, so no tokens are counted.
- **Every check runs again, on the server.** The facts are read again as the person asking and every code-side check
  of the drafter is re-run on the lines (a made-up number, an assumption said as a fact, a banned statement, a
  contact detail, the length -> 422 `video_draft_*`). Lines a person edited, or a client that invents some, get no
  further than a model's would. The lines stored in the proposal are the cleaned ones.
- **A new approval kind `lead.video_script`** (target: the lead; author `video_brief`, migration 0078). Its payload is
  exactly `language`, `tone`, `goal`, `length_seconds` and `lines` (at most 12 lines of at most 300 characters);
  anything else is refused. The approval card shows the planned change as the script's lines and says "the video
  script drafter" asked.
- **The Sentinel screens lists.** It used to read only text fields; a list of strings is now screened line by line
  (links blocked, hidden text blocked, a phone number warned about, the same as any other text).
- **A different person approves.** Nobody approves their own proposal; sales agents cannot approve. Only on approval
  is the script saved as the next version of the lead's script with `source: ai_draft`, the **approver** as the
  person recorded and `proposal_id` pointing at the proposal (migration 0078; a database check keeps `ai_draft` and
  `proposal_id` together). The approval re-checks the lines; the plan and the outcome are compared like for every
  other kind.

Not built yet: the screen (a "Draft with AI" button and "Send for approval" on the video brief page - VB5b), the
evaluation cases (VB6).

## Who may ask

Permission `video_brief:read` (sales agents, managers, administrators) **and** the lead's own read rules: a lead
the person may not read is a 404, exactly like a lead that does not exist. Support staff and customers get 403.

## Tests

`tests/test_video_brief_rules.py` (30 pure tests) and `tests/db/test_video_brief_api.py` (15 tests: roles,
colleague, other organisation, made-up ids, no data leaked, nothing written); price facts:
`tests/test_video_brief_prices.py` (12 pure) and `tests/db/test_video_brief_prices.py` (8 database tests).

## Not yet built

Brochure facts with RERA citations, the screen for drafting and sending for approval (VB5b), the governed model draft (VB4), the approval kind (VB5), evaluation cases (VB6). The Hindi and
Telugu words need a native-speaker read-through.
