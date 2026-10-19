# ADR 0006 — Domain events, notifications and workflow rules

- **Status:** Accepted (2026-10-19, with the field-update whitelist; steps 17a and 17b done - see docs/workflows.md)
- **Date:** 2026-10-19
- **Deciders:** Project owner

## Context

Phase 17 ("Workflow & Notifications") needs the CRM to react to things that happen - a lead is
assigned, a quote waits for approval, a customer accepts a quote, a task reaches its reminder
time - without the person who caused it waiting for the reaction.

Today:

- The outbox and worker exist (ADR 0005), but only for jobs a module queues for **itself**
  (quote PDF, quote e-mail).
- CLAUDE.md says: *"Domain events via an outbox (+ worker) are planned; until then no
  asynchronous side effects"* between modules.
- Task reminders exist only as the bell in the CRM; nobody gets an e-mail.
- `users.user_type` is `staff` or `customer`; every change is made by a person.

Constraints: modules write only their own tables; tenant isolation everywhere; nothing leaves
this computer except through Mailpit locally; rules must never loop or reach another tenant.

## Decisions

1. **Domain events through the outbox.** A module that wants others to know about something
   calls `publish(session, tenant_id, "lead.assigned", {"lead_id": …, "assignee_id": …})`
   (`app/core/events.py`) in the **same transaction** as its change. It is stored as an outbox
   job of kind `event.<name>`. The worker hands it to every **subscriber** registered for that
   name (in `app/worker.py`, from each module's `api.py`). Payloads hold IDs and small codes
   only - no personal data. A fixed **event catalogue** (documented in `docs/workflows.md`)
   starts with: `lead.assigned`, `activity.assigned`, `activity.reminder_due`,
   `quote.approval_requested`, `quote.approved`, `quote.rejected`, `quote.accepted`,
   `quote.declined`, `ticket.assigned`, `ticket.customer_replied`, `order.status_changed`.

2. **A new `notifications` module** (Phase 17a): in-app notifications per user (the existing
   bell shows them, with read/unread) and **e-mail notifications** sent by the worker. Each
   user chooses per notification type: in-app only, or in-app + e-mail. Task reminders become
   real: a **scheduler** in the worker publishes `activity.reminder_due` when a task's
   `reminder_at` is reached (once per task, tracked by the activities module).

3. **A new `workflows` module** (Phase 17b): tenant admins define rules
   *trigger → conditions → actions*:
   - **Triggers:** an event from the catalogue, or a **schedule** on a date field
     (e.g. "3 days before a quote's validity ends", "task overdue by 1 day", "account without
     activity for 30 days"), checked by the worker's scheduler.
   - **Conditions:** simple comparisons on a fixed list of fields per trigger (equals, one of,
     greater/less than) - no code, no free-form expressions.
   - **Actions:** create a task (for the record's owner or a chosen colleague), send an
     internal notification/e-mail (to the owner, a colleague, or everyone with a role), and
     update one of a short **whitelist of fields** (e.g. lead status, account segment).
     Actions call the owning module's `api.py`, so its rules and audit apply.
   - Every run is written to a **run log** (rule, record, result, error) visible to admins.

4. **Automation acts as a system identity per tenant.** Rule actions run with a principal of a
   new user type **`automation`** ("Automation" user row, one per tenant, no login, no Keycloak
   account). It has only the permissions the actions need, inside its own tenant; audit rows
   show "Automation (rule: …)". It can never act in another tenant or as platform admin.

5. **No infinite loops.** Events caused by an automation action carry a `depth`; rules don't
   fire above depth 3, a rule never fires twice for the same record and event, and each tenant
   has a limit of actions per hour (default 500). Hitting a limit is logged, not retried.

6. **Webhooks are left out for now** (they send data to outside servers, which belongs to
   Phase 19 "Integrations", with signing, an allow-list of hosts and SSRF protection). The
   plan's "webhook" action is moved there.

## Consequences

- CLAUDE.md's rule changes to: *cross-module reactions go through domain events
  (`app/core/events.py`); a module still never writes another module's tables.*
- New tables: `notifications`, `notification_preferences` (17a); `workflow_rules`,
  `workflow_runs` (17b); a flag on activities for "reminder sent"; `automation` user type
  (migration of the `users` check constraint).
- New pages: notification centre + preferences (everyone), Automation rules + run log
  (tenant admins).
- More work for the worker; the run log and limits keep it visible and bounded.
- Tests: event delivery and retries, per-tenant isolation of events and rules, loop limits,
  role denial (only admins edit rules), record-level checks (a notification about a record you
  can't see is never created), and one E2E journey per part.

## Alternatives considered

- **Call other modules directly in the same request** (no events): simple, but the request
  waits for every reaction, and one failing reaction would roll back the original change.
- **A rule engine with free-form expressions or scripts:** powerful but unsafe to give to
  tenants; a fixed list of fields and operators covers the common cases.
- **Automation acting as the rule's author:** would break when that person leaves or changes
  role, and mixes "who did it" in the audit.

## Proposed order of work (each step stops for review)

1. **17a — Events + notifications:** `app/core/events.py`, notifications module, e-mail
   notifications, task reminder e-mails, notification centre and preferences.
2. **17b — Workflow rules:** automation identity, rules editor (admins), scheduler triggers,
   actions, run log, loop limits.
