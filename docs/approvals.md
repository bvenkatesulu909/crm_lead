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

No endpoint creates proposals: only AI features inside the CRM do, through the service. Error
codes: `agent_action_already_decided` (409), `agent_action_changed` (409), `agent_action_expired`
(409), `self_approval_forbidden` (403), `record_not_found` (404), `agent_action_limit_reached`
(429), `unknown_agent_action` / `invalid_agent_action` (422).

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
