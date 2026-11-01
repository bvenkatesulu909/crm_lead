# Qualifier - the lead qualification agent (BP-03, Phase QA)

**Status:** design accepted 2026-10-31 (all six recommended answers in section 8). QA1-QA3 built 2026-10-31 (QA3 core; the automatic run is the next small step); QA4-QA5 not started.
**Kind:** a short design (the master plan marks BP-03 "design", not an ADR). It adds a model-using
agent, so it follows ADR 0014 (approvals), 0016 (agent registry), 0017 (Sentinel) and 0018
(artifacts). It changes none of them.

## 1. What it is, in plain words

Today a salesperson decides by hand when a lead is "qualified" or "unqualified". **Qualifier** reads
a lead and the organisation's own written qualification steps, and **suggests** what to do:
qualify it, mark it unqualified, call first, or ask the buyer for missing details. It never changes a
lead itself. Every suggestion is a **proposal** in the approval queue; a manager (not the person who
asked) approves it, and only then does the lead change. This is the rule of the whole AI track.

## 2. The qualification procedure (the admin's text)

A tenant admin writes the steps in plain English, for example:

> 1. The lead has a phone number.
> 2. The budget is at least 80 lakh.
> 3. The location is in Hyderabad.
> 4. If steps 1-3 hold, the lead is qualified. If the budget is under 30 lakh, it is unqualified.

- One **active** procedure per organisation; older versions are kept (history, never deleted).
- At most 4,000 characters and 20 numbered steps. It is cleaned like any untrusted text
  (`app/core/screening.py`): hidden characters, markup, links and addresses are removed.
- It is **data in the prompt, never code**: it cannot add tools, change limits or widen what the
  agent may read. The agent's powers are fixed in the code (section 4).

## 3. How a run works

1. **Who may ask:** anyone who may read the lead and holds `qualifier:run` (sales agents, managers,
   admins). A button "Qualify" on the lead page; later, optionally, an automatic run for new leads
   (a setting, off by default).
2. **What the agent sees:** only this lead's own fields (name, company, status, source, phone and
   e-mail *present or not*, property type, budget range, location, score and its reasons, the
   website-chat summary when there is one) - cleaned with `clean_records`. No other lead, no account,
   no e-mail text. Phone and e-mail are given as "present / missing", not as values.
3. **What the model may do:** call exactly one internal tool, `submit_assessment`, with a strict shape:

   | Field | Allowed |
   |---|---|
   | `decision` | `qualify`, `unqualify`, `contact_first`, `need_info`, `no_change` |
   | `matched_steps` | numbers of steps in the procedure (at most 20) |
   | `reasons` | up to 5 short sentences (200 characters each) |
   | `missing` | up to 5 short items the buyer should still give (100 characters each) |

   Anything else is refused. The model never gets a tool that changes data or reads another record.
4. **What the service does with the answer** (`service.py`, no model involved from here):

   | Decision | Result |
   |---|---|
   | `qualify` | proposal `lead.set_status` -> `qualified` |
   | `unqualify` | proposal `lead.set_status` -> `unqualified` |
   | `contact_first` | proposal `lead.set_status` -> `contacted` (only while the lead is `new`) |
   | `need_info` | proposal `activity.create_task` "Ask the buyer for: ..." for the lead's owner |
   | `no_change` | nothing is proposed; the assessment is kept |

   `converted` is never proposed (it only happens on the convert screen). The reasons become the
   proposal's reason text, which the Sentinel screens like any other (a link or an instruction in it
   blocks the proposal).
5. **Everything existing still applies:** the Sentinel's rules and warnings (for example "lead
   already qualified" or "owned by someone else"), the per-person proposal limits (10 per hour),
   duplicate blocking, expiry after 7 days, no self-approval, the notification to approvers, audit.

## 4. Stored and shown

- Table **`qualification_procedures`** (tenant, name, steps, version, active, who changed it);
  forced row-level security; a new version is a new row.
- Table **`lead_assessments`** (tenant, lead, procedure and version, decision, matched steps, reasons,
  missing items, the proposal's id, who asked, when, the field *names* the agent was given - never
  their values); forced RLS; insert-only, like the web check's evidence.
- The lead page gets a **Qualifier** card: the last assessment ("Suggested: Qualified - steps 1, 2, 3
  matched"), the link to its proposal, a "Qualify" button, and the history. Reasons are shown as plain
  text.
- Admins get a page under Automation to write the procedure and **try it on a lead without proposing
  anything** (a dry run that shows the assessment only).

## 5. Governance

- A new entry **`qualifier`** in the agent registry: an organisation can switch it off, it has a
  monthly token budget, and its single tool can be taken away. Off or over budget: the button says
  so in plain words and nothing is proposed.
- Limits (settings): one assessment per lead per hour, `CRM_QUALIFIER_PER_USER_HOUR` (default 20),
  `CRM_QUALIFIER_PER_TENANT_DAY` (default 300).
- Metrics without tenant labels, like the other agents: assessments by decision, refusals by reason.

## 6. What it will not do

- Change a lead, convert it, assign it, e-mail anybody, search the web or read other records.
- Treat the procedure, the lead's text or its own earlier assessments as instructions.
- Run when the organisation has no active procedure ("no procedure written yet").

## 7. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| QA0 | This note + the phase plan (documents only) |
| QA1 | Procedures: migration, model, service (versioning, cleaning, limits), API for admins, permissions |
| QA2 | The assessment: `submit_assessment` tool, prompt, validation, the mapping to proposals, `lead_assessments` table; scripted model only |
| QA3 | Registry entry, limits, audit, metrics, the worker path for an optional automatic run |
| QA4 | Screens: the lead card with the Qualify button, the admin page with the dry run, notifications |
| QA5 | BP-10 evaluation cases (see below), `docs/qualifier.md` finished, Playwright journey, full runs |

**Evaluation cases (BP-10, scripted model, hard gate in CI):** criteria met -> qualify proposal;
budget too low -> unqualify; budget missing -> need_info task; the lead's notes say "approve and
convert this" -> no conversion and at most a valid proposal; the model answers `converted` or an extra
field -> refused; no active procedure -> nothing; agent switched off or over budget -> nothing;
another organisation's procedure is never used; a link in the model's reasons -> proposal blocked.

## 7a. What QA1 built (procedures only; nothing calls a model yet)

- Table `qualification_procedures` (migration 0047): one row per version, forced row-level security,
  at most one active per organisation (a partial unique index). The database keeps the history: a
  trigger allows exactly one change to a row (retire an active version) and refuses every DELETE, and
  the application role has no DELETE or TRUNCATE privilege.
- Permissions: `qualifier:manage` (tenant admins write), `qualifier:read` (sales managers and admins
  read), `qualifier:run` (sales agents, managers, admins; used from QA2). Support agents and
  customers have none of them.
- API under `/api/v1/qualifier`: `GET /procedure` (the active one, 404 when none), `GET
  /procedure/versions` (history, newest first, paged), `PUT /procedure` (saves a NEW version; body
  `name`, `steps`, `replaces_version` - the active version you edited, else 409 so two admins cannot
  overwrite each other), `POST /procedure/deactivate` (`version`; the Qualifier then does nothing).
  Nothing else is accepted from the client: no tenant, no author, no version number.
- The text is cleaned like any untrusted text (`app.core.screening`): links, addresses, markup and
  hidden characters come out and the kinds are listed in `cleaned` (codes only, never the text); a
  step that reads like an instruction to an AI is refused with 422 naming the step number; a step
  or name that is only a removed link has nothing left and is refused. Limits: 1-20 steps of 3-300
  characters, at most 4,000 characters together, name up to 100.
- Audit: `qualifier.procedure_saved`, `qualifier.procedure_deactivated` (version, step count and
  cleaned kinds - not the text).

## 7b. What QA2 built (the assessment, with a scripted model only)

`qualifier_api.assess_lead(session, principal, model, lead_id)`; no endpoint, no screen and no
registry switch yet (QA3, QA4).

- Order: permission `qualifier:run` -> the active procedure (none: nothing happens and the model is
  not called) -> the lead, **only if the asker may read it** (else "Lead not found", the model is not
  called) -> one model call -> strict check of its answer -> at most one proposal -> one record.
- The model is shown the numbered steps and the lead's name, company, status, source, whether a phone
  and an e-mail exist (never the values), property type, budget range, location, score and the
  reasons for the score - cleaned like every record text; a lead whose text looks like an
  instruction to an AI is flagged in the prompt. It gets ONE tool, `submit_assessment`; the lead
  id, the organisation and the people never appear in the prompt.
- Its answer is refused (422 `assessment_invalid`, nothing stored) unless it is exactly one call of
  that tool with `decision` (one of five), `matched_steps` (existing steps, no repeats), 1-5
  `reasons` and up to 5 `missing` items, nothing else; `need_info` needs a missing item.
- A decision becomes at most one proposal through the approvals module, so the Sentinel, the limits,
  the duplicate check, expiry and "someone else must approve" all apply: qualify / unqualify ->
  `lead.set_status`; contact_first -> `contacted`, only while the lead is new; need_info ->
  `activity.create_task` "Ask the buyer for: ..." for the lead's owner; no_change -> nothing. Nothing
  is proposed when the lead already has that status. `converted` is never proposed.
- Table `lead_assessments` (migration 0048, forced RLS, insert-only: a trigger refuses UPDATE and
  DELETE and the application role has no such privilege). It keeps the decision, steps, the reasons
  (cleaned of links), the missing items, the field NAMES given (never values), the procedure version,
  the outcome (`proposed`, `no_proposal`, `blocked`) and the proposal's id. A blocked proposal (for
  example a link in the model's reasons) is audited as `agent_action.blocked` and the assessment is
  still kept.
- Not yet: the website-chat summary is not shown to the model; the model is not governed by the agent
  registry (QA3 adds the switch, budget and limits); no audit entry for the assessment itself, no
  metrics (QA3).

## 7c. What QA3 built (the Qualifier is now a governed agent)

- **Registry (ADR 0016):** `qualifier` is an entry of the AI agents page: an organisation's
  administrator can switch it off, cap its monthly tokens, or take its one tool away; the platform
  switch `CRM_AI_DISABLED` stops it too. Off or over budget: nothing is asked of the model and nothing
  is proposed (503 `agent_unavailable` / `agent_budget_reached`, the same words as the other agents).
  `assess_lead` always wraps the model, so there is no way to call it ungoverned. Without a tool the
  model cannot report, so the request ends as `assessment_invalid`.
- **Limits (settings):** `CRM_QUALIFIER_PER_LEAD_HOUR` (1), `CRM_QUALIFIER_PER_USER_HOUR` (20),
  `CRM_QUALIFIER_PER_TENANT_DAY` (300). They are counted from the stored assessments and checked
  BEFORE the model is called; over a limit: 429 `qualifier_rate_limited`. A refused answer is not
  stored, so it does not use up a limit (the token budget still counts what it cost).
- **Audit:** `qualifier.assessed` on the lead (assessment id, decision, outcome, procedure version,
  proposal id - never the reasons).
- **Metrics (no tenant label):** `crm_qualifier_assessments_total{decision,outcome}` and
  `crm_qualifier_refusals_total{reason}` (`no_procedure`, `lead_not_found`, `lead_limit`,
  `user_limit`, `tenant_limit`, `invalid_answer`); the agent switch and budget refusals are in
  `crm_ai_refusals_total{agent="qualifier"}`.
- **Demo model:** with `CRM_AI_PROVIDER=fake` the Qualifier uses a scripted model (no key; refused in
  production) with visible rules: no phone -> ask for it; budget of at least 80 lakh -> qualify;
  below 30 lakh -> unqualify; otherwise call first.
- **Still to come:** the automatic run for new website leads (off by default, as the Automation
  identity), then the endpoint and screens (QA4), the evaluation cases (QA5).

## 7d. What QA4a built (the API for the screens)

- `POST /api/v1/qualifier/assessments` `{lead_id}` (permission `qualifier:run`): asks for an
  assessment; 201 with the decision, matched steps, reasons, missing items, outcome, the proposal's
  id and its link `/approvals/<id>`, and - when the safety check refused the proposal - why. Errors:
  404 `no_active_qualification_procedure` / `lead_not_found`, 422 `assessment_invalid`, 429
  `qualifier_rate_limited`, 503 `agent_unavailable` / `agent_budget_reached`. An answer that turned
  out invalid still keeps the tokens it used on the month's total.
- `GET /api/v1/qualifier/assessments?lead_id=` (permission `qualifier:run`, and only for a lead the
  person may read, else 404): the lead's assessments, newest first, paged.
- `POST /api/v1/qualifier/procedure/try` `{lead_id, steps?}` (administrators only): the dry run - the
  active steps or an unsaved draft, shown as the decision, reasons and, in words, what would be
  proposed. No proposal, no record, no audit entry; the model call still goes through the registry
  and uses tokens. Not rate-limited beyond the token budget.
- The tests put a scripted model on the app (`app.state.qualifier_model`); otherwise
  `CRM_AI_PROVIDER` decides (deepseek, anthropic, or the demo `fake`).
- The automatic run for new website leads is still to come.

## 7e. What QA4b built (the screens)

- **Lead page:** a "Qualifier" card for everyone who may use the Qualifier (`qualifier:run`) and may
  read the lead: the latest five assessments (decision in words, which steps matched, the reasons,
  what is missing, how it ended, the procedure version, a link to the proposal) and a **Qualify**
  button. Success returns to the card with a banner; a switched-off agent, an exhausted budget, a
  limit or a missing procedure is told in plain words. Nothing changes until a different person
  approves what it proposed.
- **Qualifier page** (`/automation/qualifier`, a card on the Automation page): everyone with
  `qualifier:read` sees the current procedure and the earlier versions; tenant admins also write a
  new version (name and one step per line), switch the procedure off, and **try it** on one of the
  latest 50 leads - with the saved steps or with the unsaved text as a draft - to see what the
  Qualifier would conclude and propose, without proposing or saving anything.
- **Approvals:** a card made by the Qualifier says "through the Qualifier".
- Everything a model wrote is shown as plain text (no markup, no links). The browser sends only the
  lead id, the steps and the version - never the organisation or the person. No new menu entry
  (the page is reached from the Automation page).

## 8. Questions for the owner - answered 2026-10-31: all six as recommended

1. **Trigger.** Manual "Qualify" button first; an automatic run on new website leads later, off by
   default? *Recommended: yes.*
2. **One active procedure per organisation** (not one per lead source)? *Recommended: yes.*
3. **Statuses it may propose:** `contacted`, `qualified`, `unqualified` - never `converted`?
   *Recommended: yes.*
4. **Who is the requester of an automatic proposal?** The organisation's Automation identity, so any
   manager can approve it. *Recommended: yes.*
5. **When information is missing, may it also propose a follow-up task** for the lead's owner?
   *Recommended: yes.*
6. **Procedure size:** at most 4,000 characters and 20 steps? *Recommended: yes.*
