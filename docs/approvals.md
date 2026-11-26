# Approval queue for AI-proposed actions (BP-05, ADR 0014)

The CRM's AI may **suggest** a change to a real record; a person **approves** it; only then does
the change happen. This protects against a model that is wrong, or steered by text hidden in a
lead's notes or an e-mail.

Decisions and alternatives: [ADR 0014](adr/0014-agent-action-approvals.md). Steps AP0-AP5 in
[implementation-plan.md](../implementation-plan.md).

## The idea in one picture

```
employee ──asks──► staff assistant (a model)
                      │  may only call propose_* tools
                      ▼
              PENDING proposal  ◄── nothing in the CRM has changed yet
                      │            (notification to every approver except the asker)
   a DIFFERENT person with agent_action:approve decides
          ┌───────────┴───────────┐
       approve                  reject (a note is required)
          │                        │
   the change runs through the    nothing changes; the asker is told why
   owning module's api.py AS THE
   APPROVER (own rights, own audit)
          │
   approved   or   failed (the owning module refused: nothing changed, reason kept)

   not decided within 7 days ──► expired (the worker marks it; the asker is told)
```

## What can be proposed (fixed list)

| Kind | Does | Notes |
|---|---|---|
| `lead.set_status` | contacted, qualified or unqualified | never "converted" (that has its own screen) |
| `lead.assign` | give a lead to another sales person | only an active sales person of the organisation |
| `activity.create_task` | a follow-up task on a lead, account or contact | assignee defaults to the asker |

New kinds are added in code (`app/modules/approvals/catalogue.py`) with tests - never by a model.

## Rules (all tested)

- Only **signed-in staff** can propose; the record must be one they may see (else "not found").
- `tenant_id` and the asker come from the verified token, never from the model's arguments.
- Payloads are strict: nothing extra, texts and numbers limited.
- **No self-approval - for anyone, administrators included.** Also enforced by a database check.
- Approving needs `agent_action:approve` (sales managers, tenant admins) **and** that the approver
  can see the record; the proposal is locked while it runs, must still be waiting, unchanged
  (version) and not expired.
- A change the owning module refuses (e.g. the lead was converted meanwhile) rolls back and the
  proposal becomes **failed** with the reason.
- At most 20 proposals waiting per person (`CRM_AGENT_ACTION_PENDING_PER_USER`); the staff
  assistant makes at most 3 per question.
- Proposals are history: rows are never deleted (the database refuses DELETE).
- Audit entries: `agent_action.proposed`, `.approved`, `.rejected`, `.failed`, plus the owning
  module's own entry for the change itself (done by the approver).

## Screens

- **Approvals** (menu, module tile "AI Approvals"): tabs *Waiting* (approvers), *My proposals*,
  *History* with a status filter; one card per proposal with Details / Reject / Approve.
- `/approvals/{id}`: one proposal (notifications link here).
- "AI proposals" card on lead, account and contact pages; a count on the Automation page.
- In the staff assistant's answer: what it proposed, "Nothing has changed yet".

## API (`/api/v1/approvals`)

| Method and path | Who | What |
|---|---|---|
| `GET /actions?status=&mine=&target_id=&limit=&offset=` | approvers: the organisation's; others: their own | list, newest first |
| `GET /actions/{id}` | the asker or an approver | one proposal (else 404) |
| `POST /actions/{id}/approve` `{version, note?}` | approvers, not the asker | runs the action as the approver |
| `POST /actions/{id}/reject` `{version, note}` | approvers, not the asker | note required |

The only endpoint that creates a proposal is the one for outside AI clients (below); every other
proposal is made by an AI feature inside the CRM, through the service. Error codes: `agent_action_already_decided` (409), `agent_action_changed` (409), `agent_action_expired`
(409), `self_approval_forbidden` (403), `record_not_found` (404), `agent_action_limit_reached`
(429), `unknown_agent_action` / `invalid_agent_action` (422).

## Proposals from an outside AI client - the MCP server (ADR 0020, MCP5a)

`POST /api/v1/approvals/proposals/external` `{kind, target_type?, target_id, payload, reason}`
(strict body: nothing else is accepted). The proposal lands in the same queue, goes through the
same Sentinel checks and needs a different person's approval, with these extra locks:

| Lock | Refusal |
|---|---|
| Only a token whose **verified** `azp` is on `CRM_EXTERNAL_PROPOSAL_CLIENTS` (default `crm-mcp`) - the web app's token is refused | 403 `external_client_not_allowed` |
| The organisation's switch for the `mcp_client` agent - **off until a tenant admin turns it on**; the platform switch `CRM_AI_DISABLED` also stops it | 503 `agent_unavailable` |
| At most `CRM_MCP_PROPOSALS_PER_HOUR` (5) per person through this source | 429 `mcp_proposal_limit_reached` |
| The record must be one the person may see | 404 `record_not_found` |

The organisation and the person come from the token, never from the body. The row stores the
agent `mcp_client` and the verified client in `via_client` (a database check keeps the two
together); the audit entry `agent_action.proposed` and the proposal read carry it. Each proposal
counts as one call on the AI agents page (there are no tokens of ours to count). The MCP server's
three `propose_*` tools are in the MCP server (MCP5b, `docs/mcp-tools.md`). On screen (MCP5c) the approval card says "Asked by <name> through an outside AI client (MCP) - application "crm-mcp"" (the verified application, shown as plain text), and the AI agents page has a card "AI clients (MCP)" that counts proposals (no tokens) and starts switched off.

## Events and notifications

`agent_action.proposed` (`action_id`, `actor_id`) → everyone who may approve, except the asker.
`agent_action.decided` (`action_id`, optional `actor_id`) → the asker: approved, rejected, could
not be carried out, or expired. See `docs/workflows.md`.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `CRM_AGENT_ACTION_EXPIRY_DAYS` | 7 | days until a waiting proposal expires |
| `CRM_AGENT_ACTION_PENDING_PER_USER` | 20 | proposals one person may have waiting |
| `CRM_AI_PROVIDER` | `anthropic` | `anthropic`, `deepseek` or `fake` (see below) |

## Trying it without any paid key

`CRM_AI_PROVIDER=fake` selects a scripted assistant (`assistant/fake_llm.py`). It understands one
sentence and proposes through the same tool path a real model uses:

```
mark lead <lead id> as contacted because the buyer answered my call
```

1. In `backend\.env` set `CRM_AI_PROVIDER=fake`, restart the API.
2. Sign in as an agent, open **AI Assistant**, ask the sentence above (the lead id is in the
   lead's address). The answer shows the waiting proposal.
3. Sign in as a manager, open **Approvals** and approve or reject it.

The fake provider is **refused when `CRM_ENVIRONMENT=production`**. Set the provider back to your
real one (`anthropic` / `deepseek`) afterwards. A real model has not been tried yet (no API credit
so far); until then the assistant is tested with scripted models only.

## The plan and the outcome - the verification artifact (BP-29, ADR 0018)

Every proposal made since step VA1 stores, in `agent_actions.verification` (version 2), next to what
the Sentinel found:

- **`spec.changes`** - the PLAN: for each field it will change, `{field, before, after}`. Ids and
  codes only, never names (names are looked up when someone reads it, for a reader who may see them).
  A status change plans `status: new -> contacted`; an assignment `owner_id: <old> -> <new>`
  (`null` before for an unassigned lead); a task `task: null -> {subject, due_in_days, assignee_id}`
  (nobody named = the asker).
- **`spec.basis`** - the record as it was when the proposal was made (its version, status, owner;
  empty for an account or contact). Judged against the same facts the Sentinel used.
- **`outcome`** - written when the proposal is **approved** (and when approving fails): who it ran
  as, what was seen afterwards (`seen`), `matches_spec` (`true`, `false`, or `null` when it did not
  run or the proposal has no plan) and `differs` (the fields). A rejected proposal has no outcome.

Each action kind in `catalogue.py` provides `spec` (the plan) and `observe` (what is true after it
ran, in the same shape); the same two functions are used before and after, so a difference is a real
one. `run` now returns `Ran(text, created_id)` so a created task can be looked at. An approval that
ran but did not do what was announced stays "approved" and is recorded: audit
`agent_action.mismatch` (kind, record id, field names - no text). A plan that cannot be prepared
refuses the proposal (`artifact_error`, fail closed). Proposals from before this step have a version
1 artifact or none: they are approved as before, with an outcome that does not judge.

Not yet (VA3): `changes` and `outcome` in the proposal read of the API, and the "Would change" /
"What happened" blocks on the approval card.

## Tests

- Backend: `tests/db/test_approvals.py` (module rules), `tests/db/test_approvals_api.py`
  (API, events, notifications, expiry, limit), `tests/db/test_assistant_proposals.py` (assistant
  tools), `tests/test_staff_fake_model.py`.
- Web: `src/lib/approvals.test.tsx`, `src/lib/assistant-proposals.test.tsx`.
- End to end: `e2e/approvals.spec.ts` (needs `E2E_FAKE_ASSISTANT=1` in `frontend\.env.local` and
  `CRM_AI_PROVIDER=fake` in `backend\.env`; skipped otherwise).

## Not built yet

- More action kinds (these come with BP-03 qualification procedures, BP-11 MCP write tools).
- A rule-based check before a proposal is stored (BP-21), before/after records (BP-29), agent
  switches and budgets (BP-14).
- A live check with a real model.

## What the approver sees: the plan and what happened (ADR 0018, VA3)

`GET /approvals/actions` and `/actions/{id}` now carry `changes` (the plan: field, before, after - ids and codes only) and `outcome` (`ran`, `matches_plan`, `differs`, `seen`; null until approved). The same read rules as the rest of the proposal apply. The approval card shows **Would change** and **What happened** blocks; a result that did not match the plan is shown in red with the field names. Proposals made before plans existed show neither block.

The web app also sends `Content-Security-Policy-Report-Only` (outside images and plug-ins blocked, framing refused). It only reports in the browser console for now; enforcing it is a later decision.

## Follow-up e-mail drafts (ADR 0036, step FM2, 2026-11-21)

Kind `communication.send_follow_up` (author `follow_up`, migration `0078`), for a lead or a contact:

- **Payload (strict):** `reason_code` (only `task_due_today` in v1), `subject` (1-200), `body` (1-20,000, not blank), optional `template_id`. The text is FINAL: a template is filled in when the draft is made, so the approver reads exactly what will be sent. The plan shows it as the change `email`.
- **Checked when proposed:** the person can be found, has a usable address, has NOT withdrawn e-mail consent, and the template (if any) is active. Sentinel: links, e-mail addresses, markup and instruction-like text are blocked (a phone number only warns); a lead that is `converted` or `unqualified` is blocked (`lead_closed`); a duplicate waiting draft is blocked.
- **Approving** calls `communications_api.send_follow_up` AS THE APPROVER, which is the normal `send_email` path: readable recipient, address, consent and the hourly limit are judged again, the message is queued, and the worker re-checks consent just before sending (ADR 0036 FM1). Any refusal makes the proposal `failed` and nothing is queued. The sender and Reply-To are the approver. The outcome compares the stored message with the plan.
- **Who may decide:** people with `agent_action:approve` (managers, administrators) as for every kind, AND the **owner of the lead or contact** for this kind only (`OWNER_DECIDES` in `service.py`). The owner can read, list, approve and reject drafts for the records they own; nobody can decide on a proposal they asked for, and an owner has no right over other kinds. Others get 403 whether or not the proposal exists.
- **Not built yet (FM3-FM5):** who creates the drafts (the scan, its rules, its limits and the Automation identity), notifying the owner, editing the text before approving, and the full text on the approval card. Note for FM4: the Sentinel counts at most 10 proposals per hour per asker, which a scan run as one Automation identity would hit; FM4 must give it its own allowance.

## Follow-up rules and settings (ADR 0036, step FM3, 2026-11-21)

Two parts, neither of which creates a draft yet (that is the scan, step FM4):

- **Rules** (`backend/app/modules/communications/follow_up_rules.py`, pure): the fixed menu has ONE rule in v1, `task_due_today` (a task on a lead falls due today in UTC and is not done; an overdue task is not chased). `evaluate(policy, facts)` lists every reason a draft may not be made: `platform_off`, `switched_off`, `unknown_rule`, `no_template`, `bad_policy`, `consent_withdrawn`, `consent_unknown`, `no_address`, `no_owner`, `lead_closed`, `reply_received`, `draft_waiting`, `cooldown`, `monthly_cap`, `daily_cap`, `owner_pending_cap`. Consent: a "no" always stops; "unknown" allows only a conversation the person started; "granted" allows. Numbers outside their bounds make the whole policy bad and nothing else is judged (found by a test: a text where a number belonged crashed the comparison).
- **Settings** (table `follow_up_policies`, migration `0079`): one row per change, newest wins, never updated, deleted only after 365 days, forced row-level security, composite foreign keys keep the template and the author inside the organisation. Defaults (off): 3 per person per 30 days (never above 8), 100 drafts per organisation per day (never above 100), 20 waiting per owner, expiry 7 days, cooldown 7 days. Switching on needs a template (a database check). The database repeats every bound. Read and write through `communications/repository.py` (`current_follow_up_policy`, `add_follow_up_policy`, `follow_up_policy_history`); the service with permission and audit comes with the API (FM5).

## The follow-up scan (ADR 0036, step FM4, 2026-11-21)

New module `follow_ups` (no tables; imports only other modules api.py). About once a minute the worker asks it, for every active organisation, to make the follow-up drafts that are due:

1. **Off unless on:** nothing happens unless the organisation switched it on in its settings (FM3) AND the platform switch `CRM_FOLLOW_UPS_DISABLED` is not true. A bug in the scan is logged by type only and never stops the other organisations or the workflow rules.
2. **Who is due:** open `task` activities linked to a lead whose due time falls on today (UTC), oldest first, at most 500 looked at, at most 50 drafts per run. Notes, calls and meetings do not count; an overdue task is not chased. Two due tasks on one lead make one draft. (The ADR says "a follow-up task": tasks have no separate type, so every open task on a lead counts.)
3. **May a draft be made:** the pure rules of FM3 run over facts read through each owning module api.py: the lead (status, owner, consent, address, source), earlier drafts (waiting, newest, count in 30 days, today, waiting per owner), and received e-mails logged for the lead (`started_by_person` = the lead came from the website or has ever written to us; `reply_received` = they wrote after the task was set).
4. **Making it:** the organisation template is filled in for the lead (a template with a placeholder that has no value, or an inactive one, makes no draft); the sender lines are the lead owner, who will normally approve. The draft is proposed as the Automation identity, author `follow_up`, expiry from the policy, through the same approval queue and Sentinel. Because one identity asks for the whole organisation, the Sentinel hourly allowance and the waiting limit are widened to the policy daily cap (not removed). A refused draft leaves nothing behind and a blocked one is audited (`agent_action.blocked`, codes only).
5. **Telling people:** the existing `agent_action.proposed` notification now also reaches the owner of the lead for this kind (ADR 0036 planned a separate `follow_up.proposed` event; the existing one does the job). The log line holds counts and reason codes only.
6. **Safe to repeat:** a waiting draft, or any draft within the cooldown, blocks another for that lead.


## Settings, the full text and edit-before-approve (ADR 0036, step FM5, 2026-11-22)

**Settings (administrators).** `GET` / `PUT /api/v1/communications/follow-up-settings`, permission `follow_up:manage` (tenant administrators only; managers and agents get 403). `PUT` replaces the whole settings (switch, template, the five numbers); `version` is the `seq` of the settings the screen saw (0 when none were ever saved) and a stale one is a 409 `version_conflict`. Numbers outside their bounds, a template that is not an active one of the organisation, and switching on without a template are 422 `follow_up_settings_invalid`. Each save is a new insert-only row and an audit entry `follow_up.settings_changed` with the old and new values of what changed. The client cannot send a tenant, the rule or anything else (unknown fields are 422). Screen: **Automation > Follow-ups** (`/automation/follow-ups`).

**The full text.** The approval card (list and detail page) shows a follow-up draft as "The e-mail that will be sent": subject and text as plain text, a reminder that consent and the hourly limit are checked again at sending. The lead page list names the subject of a waiting draft.

**Edit before approving.** `POST /approvals/actions/{id}/approve` accepts an optional `edit` with `subject` and/or `body`, for a follow-up draft only (any other kind: 422 `agent_action_edit_not_allowed`). The new text must fit the payload shape, pass the kind's own check and the Sentinel's word rules (links, instruction-like text and hidden characters are refused with 422 `agent_action_edit_refused`; a refusal changes nothing and the draft keeps waiting). A field equal to what is stored is not an edit. An accepted edit rebuilds the plan, replaces the warnings about phone numbers, marks the proposal `edited`, and writes the audit entry `agent_action.edited` with the field NAMES only, never the text. The edited text is what the e-mail path sends.

**Fix found on the way (FM2):** the service already let the owner of a lead decide on a draft for it, but the approve and reject endpoints still demanded the approver permission, so an owner got 403 through the real API. They now accept anyone who may propose; the service still refuses everybody who is neither an approver nor the record's owner (403), and the owner of a draft they asked for still cannot approve it.

**Playwright journey:** `frontend/e2e/follow-ups.spec.ts` (rule on with a refused out-of-range number, a due task makes ONE draft for the lead that agreed to e-mails and none for the one that opted out, a second scan makes no second draft, the owner sees the full text, a colleague gets "not found", a link in the reworded text is refused, the reworded e-mail arrives in Mailpit with Reply-To the owner, no second draft inside the cooldown, an opted-out lead gets none, settings put back). It type-checks, lints and is listed by Playwright but **has not been run**: the ports it needs (3000, 8000) were in use by the owner's servers. Run it with the web app, API and Mailpit up and the worker NOT running as a standing process.

**Looked at (2026-11-22):** the approval card with a draft, the Follow-ups settings form with an error, and the lead page list, rendered with the real stylesheet (components rendered to static HTML and photographed at 900 px and 390 px wide). They read well and wrap cleanly on a phone. The Approve dialog (it only opens in a running app) and the pages inside the real app shell were not looked at.
