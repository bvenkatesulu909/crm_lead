# Communication Center (one-to-one e-mail, ADR 0012)

**Status: CC0–CC6 built (2026-10-24/25)** on branch `feat/communications`, draft PR #13.
Design and decisions: [ADR 0012](adr/0012-communication-center.md). Module code:
`backend/app/modules/communications/`, screens under `frontend/src/app/(app)/communications/`.

## What it is for

Staff write e-mails to a **lead** or a **contact** from inside the CRM, optionally starting from a
**template**, and every record shows its **conversation history**. Received e-mails are logged by
hand (pasted in) until Phase 19 (Integrations) connects a mailbox.

Not in this module: receiving replies automatically (Phase 19), bulk/marketing e-mail (Phase 16,
which will reuse these templates), HTML e-mails, attachments, CC/BCC.

## Words

- **Message:** one e-mail with exactly one lead or one contact. `outbound` (sent by us) or
  `inbound_logged` (received, typed in by staff).
- **Status:** `queued` → `sent`, or `failed` (with a safe `error_code`); logged e-mails are `logged`.
- **Related record:** an e-mail to a contact may be filed under that contact's account or one of
  its deals; it then also appears in that record's history.
- **Template:** a subject and text with placeholders from a fixed list.

## How sending works

```
Send dialog ──► Server Action ──► POST /api/v1/communications/emails
                                   checks (below) → message "queued" + outbox job
                                   + timeline entry + audit "email.queued"   (one commit)
worker (python -m app.worker) ──► SMTP (Mailpit locally), Reply-To = the sender
   ├─ sent                       → status "sent", sent_at
   ├─ mail server down           → retried later (stays "queued")
   └─ refused / retries used up / consent withdrawn meanwhile
                                 → "failed" + error_code + event communication.email_failed
                                   → in-app notification "E-mail not delivered: …" for the sender
```

Checks on sending, in order (each with a stable error `code`):

| Check | Answer |
|---|---|
| Permission `communication:send` | 403 |
| The lead/contact is visible to the sender (its own module's rules) | 404 `recipient_not_found` |
| The account/deal is visible and is the contact's own | 404 `related_not_found` / 422 `related_record_mismatch` |
| The template exists and is active | 404 `template_not_found` |
| The record has a usable address (taken from the record, never from the client) | 409 `recipient_has_no_email` |
| The contact hasn't withdrawn e-mail consent | 409 `consent_withdrawn` |
| At most 200 e-mails per person per hour (`CRM_COMMUNICATION_EMAILS_PER_HOUR`) | 429 `send_limit_reached` |

Logging a received e-mail (`POST /emails/received`) checks the same record rules and the address,
but not consent or the limit (nothing is sent).

## Templates

Six placeholders, filled by plain text replacement in one pass (no template engine, no
expressions; a value is never expanded again; line breaks never reach a subject):

| Placeholder | Value |
|---|---|
| `{{recipient.first_name}}` | First name of the lead or contact |
| `{{recipient.full_name}}` | First and last name |
| `{{recipient.company}}` | The lead's company, or the contact's account |
| `{{sender.name}}` | The user writing the e-mail |
| `{{sender.email}}` | Their e-mail address |
| `{{organisation.name}}` | The tenant's name |

Unknown or unbalanced placeholders are refused when a template is saved (422
`unknown_placeholder`). An empty value is left out and reported by the preview (`missing`). The
text finally sent is what the sender saw and edited; the `template_id` is kept for reference.

## Who may do what

| Role | Send / log | Communication Center list | Templates |
|---|---|---|---|
| Tenant admin, Sales manager | ✔ | every e-mail (`communication:read:all`) | manage (`communication:template:manage`) |
| Sales agent, Support agent | ✔ | only their own (`communication:read:own`) | use active ones |
| Customer, platform admin | — | — | — |

A record's **history** (`GET /history?…_id=`) is shown to anyone with a communication permission
who may read that record; an account's history includes its contacts and deals.

## Data (migrations 0038, 0039)

- `email_templates`: name (unique per tenant), subject, body (≤ 20,000), `is_active`, version.
- `email_messages`: direction, status, `lead_id` **or** `contact_id`, optional `account_id`
  **or** `opportunity_id` (never for a lead), address, subject, body (≤ 50,000), template,
  sender, `sent_at`, `error_code`, `seq` (reliable newest-first order).
- Both: forced RLS + tenant policy; tenant-scoped foreign keys; the database refuses impossible
  rows. The application may not DELETE or TRUNCATE messages.
- Personal data: bodies and addresses stay in these rows; never in logs, outbox payloads, events
  (IDs only) or audit entries (record IDs only). The timeline entry holds only the subject.

## The API (`/api/v1/communications`)

| Method and path | Who |
|---|---|
| `POST /emails` | send |
| `POST /emails/received` | log a received e-mail |
| `GET /emails` (q, status, direction, sent_by_user_id, limit, offset) | read:all / read:own |
| `GET /emails/{id}` | read:all, or the sender |
| `GET /history?lead_id=|contact_id=|account_id=|opportunity_id=` | anyone who may read the record |
| `GET /templates` (`include_inactive` for managers) · `GET /templates/{id}` | senders, managers |
| `POST /templates` · `PATCH /templates/{id}` (version check) | managers, tenant admins |
| `POST /templates/{id}/preview` (lead, contact or sample values) | senders, managers |
| `GET /placeholders` | senders, managers |

## The screens

- **E-mails card** on lead, contact, account and deal pages: history (newest first, status,
  failure reason, full text) with **Send e-mail** and **Log a received e-mail**. A person
  without an address or with withdrawn consent gets a short explanation instead of the button.
- **Send / log dialog:** "To" is the page's lead/contact, or a list of the account's contacts
  (people who can't be written to are shown but disabled). A template fills in subject and text
  through the API preview; everything stays editable and is kept if the server reports an error.
- **Communication Center** `/communications` (menu entry "E-mail"): search, status and direction
  filters, paging.
- **Templates** `/communications/templates` (managers): list, new, edit, deactivate/reactivate,
  with the placeholder list beside the form.

## Tests

- Backend: `test_communication_rules.py`, `db/test_communications_schema.py`,
  `db/test_communications_send.py`, `db/test_communications_templates.py`,
  `db/test_communications_history.py` (happy path, validation, tenant isolation, role and
  record-level denial, ID tampering, consent, limit, retries, failure notification).
- Frontend: `src/lib/communications.test.tsx` (helpers, permissions, menu, tile, dialog).
- End to end: `e2e/communications.spec.ts` - template → send → real Mailpit e-mail (Reply-To the
  sender) → log the reply → Communication Center; who may not see what.

## Running it locally

Run the API and the worker (`python -m app.worker`, own CMD window) as usual; e-mails go to
Mailpit at http://localhost:8025. After pulling this branch, run `alembic upgrade head` once.
