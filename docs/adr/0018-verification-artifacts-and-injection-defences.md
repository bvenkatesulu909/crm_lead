# ADR 0018 — Verification artifacts, and the ForcedLeak / BodySnatcher defences (BP-29)

- **Status:** Proposed (2026-10-27) — waits for the owner's review; no code until approved
- **Date:** 2026-10-27
- **Deciders:** Project owner
- **Depends on:** ADR 0014 (approval queue), ADR 0016 (agent registry), ADR 0017 (Sentinel and
  input screening)

## 1. The problem

Two weaknesses remain after the Sentinel.

**A. The approver is asked to trust a sentence.** A proposal shows "Change the lead's status to
contacted" and a reason the model wrote. The approver does not see *what will be different* —
status `new` → `contacted`, owner Avery → Blake, a task with this subject for that person on that
day — nor, afterwards, whether what ran is what was announced. The Sentinel's findings are stored
(`agent_actions.verification`), but not the state it judged against.

**B. Two named attack families are covered only in part.**
- **ForcedLeak** (an indirect prompt injection that travels through a *web form*): an outsider
  puts instructions into a field that a CRM agent later reads, and the agent leaks data through
  something the page loads, typically an image URL. Here the outsider is the website visitor: the
  chat's `save_lead` writes model-chosen text (name, location, notes) into a lead exactly as the
  model produced it. SN3 cleans what the visitor types and what is put in prompts later, but the
  text stored in the lead is not screened at the door, and nothing stops a *model's answer* from
  carrying a link or an image.
- **BodySnatcher** (an agent that acts as whoever an e-mail address or id in its input names):
  the CRM already takes the identity only from the verified token, but nothing *proves* that no
  tool will ever accept an identity-like argument — a future tool could, and the rule would be
  broken without any test noticing.

## 2. Decisions

**V1 — The artifact is the existing `verification` column, version 2.** No new table. A stored
proposal gets, next to what the Sentinel already stores:
- `spec`: the planned changes, one entry per field: `{field, before, after}` with **ids and codes
  only** (a status code, an owner id, for a task `{subject, due_at, assignee_id}`). Names are not
  stored: they are looked up when the artifact is *read*, for a reader who may see the person
  or record (the same rule as the approval card's record name today).
- `basis`: the record's `version` (and status/owner) seen when the proposal was made. A later step
  of the Sentinel's re-check compares it with now, so "the lead changed while this waited" is a
  precise statement, not only a guess from rules.
- `outcome`, written by `approve()`: what ran (`ran_as`: approver id), the result, the fields as
  seen **after** the action, and `matches_spec: true | false`. A `false` is shown to the next reader
  and is audited (`agent_action.mismatch`) — the action ran, but not as announced.
Proposals made before this step have `verification` v1 or none; readers handle both.

**V2 — Where the "before" and "after" come from.** Each action kind in the approvals catalogue
gets a `spec(...)` function next to its `check` and `run`; it asks the owning module through its
`api.py` (`lead_snapshot` exists; task creation needs only the payload). The same function is used
after the run, so "predicted" and "seen" are produced by one piece of code and a difference is a
real difference.

**V3 — The approval card shows the plan and the result.** Above the buttons: "Would change:" with
`Status: new → contacted`, `Owner: Avery Agent → Blake Agent`, `New task: "Call the buyer", due
31 Oct, for you`. After the decision: "What happened: matched the plan" or "Differed from the
plan: …". The API read model gets `changes` (labelled, for this reader) and `outcome`. A separate
`GET …/artifact` endpoint is not needed (decision for the owner, question 1).

**V4 — ForcedLeak: clean at the door, and at the exit.**
1. **At the door.** Everything the public chat's `save_lead` writes into the CRM (name, location,
   notes) is passed through the strict `screen()` first — hidden characters, markup, images,
   links and e-mail addresses in free text are removed, floods collapsed — and the lead gets a
   timeline line "Some text from the website chat was cleaned" with the finding codes, so staff
   know. The dedicated fields (phone, e-mail) are validated as before and not touched. Other
   public entrances: there are none today besides the chat (the list is a table in the new
   `docs/injection-defences.md`, updated whenever one is added).
2. **At the exit.** `sanitise_output` (what the assistants show to people) also removes
   model-written images and links to other sites (`[link removed]`), keeping links that point
   inside the CRM (`/leads/…`). A model that was steered into building an exfiltration URL cannot
   show it, and no screen renders it.
3. **The browser.** A Content-Security-Policy (`img-src 'self' data:`, `object-src 'none'`,
   `frame-ancestors 'none'`, `base-uri 'self'`) on the web app, so even a bug that renders an
   external image does not load it. First as `Content-Security-Policy-Report-Only`, then enforced
   (owner's decision, question 3): the development server needs relaxed script rules.
4. **No fetching tools.** A test proves no tool of any agent takes a URL or fetches one. (BP-15
   would introduce one deliberately, with its own ADR.)

**V5 — BodySnatcher: identity only from the token, proven by a test.** One test walks every
tool schema of the staff assistant, the portal assistant and the website chat and fails if any
argument name is identity-like — `tenant_id`, `user_id`, `requested_by*`, `actor*`, `email`,
`username`, `role(s)`, `permission(s)`, `principal`, `on_behalf*` — unless it is on a short,
reviewed **allow-list of targets** (`owner_id` of an assignment, `assignee_id` of a task: a person
to give work to, checked to be an active colleague of the same organisation by the Sentinel and the
owning module). Adding a tool with such an argument fails the build until a person reviews it.
Every tool schema also keeps `additionalProperties: false` (checked by the same test). The
service-account paths (the Automation identity of the website chat, the worker) are listed in
`docs/injection-defences.md` with the one place each gets its identity from.

**V6 — What is *not* changed.** Proposals stay human-approved (ADR 0014); the Sentinel stays
rule-based (ADR 0017); no model reads another model's output to decide. Artifacts add visibility
and checking, not new power.

## 3. What this does not do

- It cannot know a model's intent; it makes *effects* visible and checked.
- Screening at the door removes text, so a visitor who legitimately writes a link in their notes
  loses it (the chat says to describe it in words). The original is not kept.
- The artifact covers the three action kinds that exist; new kinds must provide a `spec`
  (enforced by a test over the catalogue).

## 4. Consequences

- Migration: none (JSON inside an existing column). `approvals` read schema grows (`changes`,
  `outcome`); OpenAPI is refreshed. One more owning-module call per proposal and per approval.
- The approval card gets two blocks; no other screen changes. A CSP can break a page that loads an
  outside image or script: the report-only phase exists to find out (the app loads none today).
- `docs/injection-defences.md` becomes the one page that lists every way outside text reaches a
  model and what happens to it.

## 5. Steps (each stops for review)

| Step | What | Size |
|---|---|---|
| **VA0** | This ADR and the phase plan (documents only) | S |
| **VA1** | `spec` per action kind, artifact v2 stored at `propose()`, `outcome` + `matches_spec` at `approve()`, audit of a mismatch; catalogue test; tests first | M |
| **VA2** | Door and exit: screening of what `save_lead` stores, `sanitise_output` for links and images, the identity-argument test, the no-fetch test; tests first | M |
| **VA3** | API (`changes`, `outcome`), the approval card ("Would change", "What happened"), CSP in report-only mode; frontend tests, Playwright | M |
| **VA4** | BP-10 cases (a poisoned form field, an image in an answer, a mismatch), `docs/injection-defences.md`, full runs, pull request | S |

Acceptance: every proposal made after VA1 carries a spec; an approval that changes something other
than announced is recorded as a mismatch; a visitor's hidden instruction or image link never
reaches a stored lead or a shown answer; a tool with an identity-like argument fails the build;
the approval card shows what will change; the evaluation scorecard and the full suites stay green.

## 6. Questions for the owner

1. **Read model or separate endpoint:** put `changes` and `outcome` in the normal proposal read
   (recommended), or add `GET /approvals/actions/{id}/artifact` as the master plan sketched?
2. **Old proposals:** leave proposals made before VA1 without a plan (recommended), or compute one
   on the fly when they are read?
3. **CSP:** report-only first for one release, then enforce (recommended) — or enforce at once?
4. **Output links:** remove every link to other sites from assistant answers (recommended), or
   allow a short list of trusted sites (e.g. the organisation's own website)?
5. **Cleaned text in a lead:** keep only the cleaned text and a note (recommended), or also keep
   the original in a staff-only field for investigation?
