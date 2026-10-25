# ADR 0014 — Approval queue for AI-proposed actions (BP-05)

- **Status:** Proposed (2026-10-25)
- **Date:** 2026-10-25
- **Deciders:** Project owner
- **Covers:** blueprint BP-05 ("AI proposes, a person approves"), first object of AI Track A1 after
  BP-01. See `docs/master-plan.md`. Later blueprints build on it: BP-03 (qualification
  procedures), BP-11 (MCP write tools), BP-14 (agent registry), BP-21 (action verifier), BP-29
  (verification records).

## Context

Every AI feature in the CRM can only **read** today, or create something a person confirms on
screen at once:

- The **staff assistant** (`assistant/staff_service.py`) answers questions from records the user
  may see. It has read-only tools (`staff_tools.py`: search accounts/leads, a ticket, an
  account), and the loop currently even passes the model no tools at all.
- The **portal assistant** has one "proposing" tool, `propose_support_ticket`: the customer
  confirms the ticket on screen right away. Nothing waits, and no second person is involved.
- The **public website chat** (ADR 0013) creates a lead as the Automation identity, inside
  strict limits.
- **Workflow rules** (ADR 0006) change records automatically, but a tenant admin wrote each
  rule in advance; the rule itself is the approval.

The next AI features (BP-03 qualification, BP-11 MCP write tools, BP-02 enrichment, BP-18 deal
desk…) need the AI to **suggest changes to real records**: move a lead to "qualified", give it
to an agent, plan a follow-up. Letting a model change records directly is the main risk named
in the PDF. A model can be wrong, or be steered by text hidden in a lead's notes or an
e-mail (prompt injection). So such a change must be **proposed**, checked by a responsible
person, and only then carried out under that person's own rights.

Existing building blocks: the domain modules' `api.py` functions that already enforce their
own rules and audit (`leads_api.set_lead_status`, `activities_api.create_task`), `record_audit`,
domain events + notifications (ADR 0006), the worker's schedules, forced RLS on every tenant
table (ADR 0009) and `identity_api.bind_reader` for background reads.

## Decisions

1. **A new module `approvals`** (module 21) owns proposed actions. It never changes another
   module's tables itself: an approved action runs through the **owning module's `api.py`**,
   with that module's own rules and audit.

2. **One table `agent_actions`** (forced RLS, tenant policy):
   - what: `kind` (from a fixed catalogue), `target_type` + `target_id`, `payload` (JSON, only
     IDs, codes and short texts, validated against the kind's schema), `reason` (why the AI
     suggests it, ≤ 500 characters, shown to the approver);
   - who: `requested_by_user_id` (the signed-in person whose assistant proposed it) and
     `agent` (which AI feature, e.g. `staff_assistant`);
   - state: `status` = `pending` → `approved` | `rejected` | `expired` | `failed`;
     `decided_by_user_id`, `decided_at`, `decision_note`, `result` (short text), `expires_at`;
   - `version` for optimistic locking; rows are never deleted (history).

3. **A fixed catalogue of action kinds**, each with a Pydantic payload schema, a check that the
   requester may see the target, a one-line description for the card, and the `api.py`
   function that performs it. The first catalogue is small:
   - `lead.set_status` - contacted, qualified or disqualified (+ reason), through
     `leads_api.set_lead_status`;
   - `lead.assign` - give the lead to a sales person (`leads_api.assign_lead`, a new thin
     wrapper over the existing service, same rules as the Assign button);
   - `activity.create_task` - a follow-up task on a lead, account or contact
     (`activities_api.create_task`).

   A kind not in the catalogue is refused. New kinds are added in code with tests, never by
   the model.

4. **Proposing.** Only through the service, for a signed-in **staff** principal. At proposal
   time the payload is validated and the requester **must be able to see the target**
   (otherwise 404, as everywhere). `tenant_id` and the requester come from the verified token,
   never from the model's arguments. A requester can have at most 20 pending proposals
   (setting) so a looping model can't flood the queue. Event `agent_action.proposed` →
   notification to the approvers.

5. **Approving and rejecting.**
   - New permission `agent_action:approve` for **sales managers and tenant admins**;
     `agent_action:read` for every staff role that uses the assistant (own proposals only),
     approvers see all of the tenant's.
   - **No self-approval, for anyone:** the requester can never approve their own proposal,
     admins included (stricter than quote approval, because the text came from a model).
   - Approve runs in **one transaction**: lock the row (`SELECT … FOR UPDATE`), check it is
     still `pending`, not expired and the version matches, **re-validate** the payload, then
     run the action **as the approver** - the approver's permissions and record rules decide
     (e.g. an approver who can't see the lead gets 404 and nothing happens). Audit:
     `agent_action.approved` with the action id, kind, requester and agent, plus the owning
     module's own audit entry for the change itself.
   - If the action fails (lead already converted, assignee left…) the change is rolled back
     to a savepoint, the proposal becomes `failed` with the reason, and the approver sees it.
   - Reject needs a short note. Event `agent_action.decided` → notification to the requester.
   - Approving or rejecting twice → 409 `agent_action_already_decided`.

6. **Expiry.** Pending proposals expire after **7 days** (setting
   `CRM_AGENT_ACTION_EXPIRY_DAYS`); the worker marks them `expired` in its schedule. An expired
   proposal can't be approved.

7. **The staff assistant gets proposing tools**, one per catalogue kind (`propose_lead_status`,
   `propose_lead_assignment`, `propose_follow_up_task`). They only create a pending proposal and
   answer "Proposal waiting for approval" with a link. The model never runs an action. The
   tools are tested with a scripted fake model (no paid key), like the public chat.

8. **Screens.** An **Approvals** page (menu entry for approvers) with pending cards (what, on
   which record, why, who asked, when it expires) and Approve / Reject; history with filters;
   "My proposals" for requesters; a summary card on the Automation page and a link from the
   record. Notifications link to the card. All loading via `apiFetch`, changes via Server
   Actions, as everywhere.

## Consequences

- Migration **0042**: `agent_actions` with forced RLS (`test_rls_tenant_tables.py` will demand
  it); new permissions in `rbac.py`; new events in `EVENT_NAMES`; new notification types.
- `leads/api.py` gains `assign_lead`; no other module changes its rules.
- Approved actions appear twice in the audit trail on purpose: the approval and the change.
- Later steps hook in here: BP-21 adds a rule-based check before a proposal is stored, BP-29
  stores before/after records, BP-14 checks the agent's switch and budget before it proposes,
  BP-11's MCP write tools create proposals instead of writing.
- Tests for every rule: proposal validation, unknown kind, target not visible (404), tenant
  isolation, role denial, **self-approval refused**, approver without access to the record,
  double decision, expiry, failure rollback, the pending limit, notifications, and the
  assistant tools with a fake model.

## Alternatives considered

- **Let the assistant change records directly, with an undo button:** fast, but the change
  happens before anyone looks, and a steered model could do damage that "undo" can't repair
  (e-mails sent, people notified).
- **Confirm on screen by the same person** (like the portal ticket): fine for low-risk
  self-service, but the point of BP-05 is a **second person**. A requester confirming their own
  AI suggestion adds little protection against prompt injection.
- **Reuse workflow rules as the queue:** rules are written in advance by admins; proposals are
  one-off and come from a model. Mixing them would blur who approved what.
- **Store a generic "API call" (method + URL + body):** flexible, but an approver couldn't
  understand it, and every endpoint would become reachable by the model. A fixed catalogue of
  understandable actions is safer.

## Proposed order of work (each step stops for review)

| Step | What |
|---|---|
| AP0 | This ADR + the phase plan (documents only) |
| AP1 | `approvals` module: migration 0042 (forced RLS), permissions, catalogue (3 kinds), propose / approve / reject service with locking, no self-approval, failure rollback, audit; `leads_api.assign_lead`; tests first |
| AP2 | API endpoints, events `agent_action.proposed` / `agent_action.decided` → notifications, worker expiry, pending limit; tests first |
| AP3 | Staff assistant: tools passed to the model, the three proposing tools, fake-model tests |
| AP4 | Web: Approvals page (pending, history, my proposals), record links, Automation card, assistant answer shows the waiting proposal; Vitest |
| AP5 | Playwright journey (agent's assistant proposes → manager approves → lead changes; self-approval refused), `docs/approvals.md`, full run, PR |
