# ADR 0012 — Communication Center: one-to-one e-mail, templates and conversation history

- **Status:** Accepted (2026-10-24) — the owner accepted the four main decisions (1–4 below)
  and told us to start the work as planned
- **Date:** 2026-10-24
- **Deciders:** Project owner

## Context

Staff write to customers all the time, but the CRM can't help with it yet. Today:

- The CRM sends e-mail only for **its own reasons**: quote e-mails (ADR 0005), invitations
  (ADR 0004) and notifications (ADR 0006). A salesperson can't write a free e-mail to a lead or
  contact from the CRM.
- The only record of an e-mail written outside the CRM is a hand-made activity of kind
  `email` (on a lead's timeline or in the activities module), holding a note, not the message.
- The building blocks exist: `app/core/mail.py` (SMTP; Mailpit locally), the outbox + worker
  with retries (ADR 0005), domain events (ADR 0006), and `contacts.email_consent`.
- The module grid already shows "Communication Center — E-mail composer, templates and
  conversation history" as *planned*, but [architecture.md](../../architecture.md) has no module
  for it. Marketing (Phase 16) also plans "email templates".

Constraints: tenant isolation with forced RLS; record-level rules decide who may write to whom;
e-mail is sent only from the worker, never inside an HTTP request; locally nothing leaves the
computer except through Mailpit; no personal data in logs or event payloads.

## Decisions

1. **A new module `communications`** (module 18). It owns **e-mail templates** and the
   **message history** (sent e-mails and e-mails logged by hand). Other modules use it only
   through `communications/api.py`; it reaches leads, contacts, accounts and deals only
   through their `api.py`.

2. **Outgoing e-mail only, for now.** Receiving customer replies automatically needs a real
   mailbox connection (IMAP or a provider webhook), with stored credentials. That belongs to
   Phase 19 "Integrations". Until then staff can **log a received e-mail by hand** (pasted
   subject and text), so a record's conversation history is still complete.

3. **Templates live in `communications`; Marketing reuses them.** Phase 16 will not build a
   second template system. It will call `communications/api.py` to render a template, and add
   its own rules for bulk sending (segments, unsubscribe links).

4. **Consent:** a one-to-one sales or support e-mail is **allowed** when a contact's marketing
   consent is `unknown` or `granted`, and **blocked** when it is `withdrawn` (the composer says
   why; the API returns a business error with a stable code). Leads have no consent field; a
   lead has contacted us, so writing back is allowed. Marketing's bulk sending (Phase 16) will
   require `granted`.

### How it works (details for the steps below)

5. **Who the e-mail goes to.** The recipient is always **one lead or one contact**, chosen by
   ID. The server loads it through that module's `api.py` and record policy (missing or not
   allowed → 404) and takes the **address from the record**. The client never sends an e-mail
   address, so the CRM can't be used to write to arbitrary people. An e-mail to a contact may
   also be linked to **one account or deal** the sender may read (for that record's history).
   No CC/BCC and no attachments in the first version.

6. **Sending goes through the outbox.** `POST /api/v1/communications/emails` checks
   everything, stores the message as `queued`, and queues a `communication.email` job in the
   same transaction; the router commits once. The worker sends it: `sent`, or `failed` after
   the retries (mail server down → retry; address refused → no retry). From is the CRM's
   `mail_from`; **Reply-To is the sender's own address**, so the customer's answer reaches a
   person. A timeline entry of kind `email` is added through the lead's or the activities
   module's `api.py`, and `record_audit()` records the send.

7. **Plain text only, no code in templates.** E-mails are plain text, like the quote e-mails,
   so no HTML from users reaches anyone's mail program. Templates have a subject and a body
   with **placeholders from a fixed list** (for example `{{recipient.first_name}}`,
   `{{account.name}}`, `{{sender.name}}`). They are filled by simple text replacement — no
   template engine, no expressions. An unknown placeholder is refused when the template is
   saved. The text the sender finally sends (after editing) is what is stored.

8. **Permissions** (in `app/core/auth/rbac.py`):
   - `communication:send` — write and log e-mails (sales and support roles, managers, admins);
     the sender must also be allowed to read the recipient record.
   - `communication:read:all` (managers, tenant admins) / `communication:read:own` (others):
     the Communication Center list shows all messages of the tenant, or only the ones the user
     sent or logged. Filtered in SQL.
   - A **record's history** (on a lead, contact, account or deal page) shows every message for
     that record to anyone allowed to read the record.
   - `communication:template:manage` (managers, tenant admins) — create and edit templates;
     everyone with `communication:send` may use them.
   Portal users get none of these.

9. **Tables** (one migration, both with `tenant_id`, ENABLE + FORCE RLS and the tenant policy):
   - `email_templates`: name, subject, body, active, created/updated by and at.
   - `email_messages`: direction (`outbound` / `inbound_logged`), status (`queued`, `sent`,
     `failed`, `logged`), recipient type + ID (lead or contact), optional related account or
     deal, address, subject, body, template used, sender, timestamps. Rows are never deleted
     through the API; after sending only the status fields change.

10. **Limits and events.** Each user may send at most 200 e-mails per hour (a guard against
    mistakes, not a marketing tool). When a send finally fails, the module publishes
    `communication.email_failed` (IDs only), and the notifications module tells the sender
    in the CRM.

## Consequences

- architecture.md gets module 18 `communications`; Marketing's row no longer owns templates.
- New tables `email_templates` and `email_messages`; new permissions; a new worker job kind
  and a new event in the catalogue (docs/workflows.md).
- New screens: a "Send e-mail" dialog on lead, contact, account and deal pages; a Templates
  page; a Communication Center page (sent and logged messages, with filters). The module tile
  becomes "Available".
- E-mail bodies are personal data: they stay in the tenant's rows (RLS), are never logged and
  never put into event payloads.
- Replies don't arrive by themselves until Phase 19; users must be told that "log a received
  e-mail" is the way for now.
- Tests: happy path, validation, tenant isolation, role denial, record-level denial, ID
  tampering (someone else's lead or contact → 404), withdrawn consent → refused, mail server
  down → retried, the hourly limit, and one Playwright journey that finds the e-mail in Mailpit.

## Alternatives considered

- **Templates in Marketing, e-mail sending in each module:** two template systems, and every
  module would build its own composer and history.
- **Let the user type any address:** convenient, but turns the CRM into an open mail relay
  and bypasses record-level rules and consent.
- **HTML e-mails and a template engine (e.g. Jinja2):** nicer mails, but user-written HTML
  and expressions open injection risks; plain text with fixed placeholders covers one-to-one
  e-mail. HTML can be a later ADR.
- **Build inbound e-mail now:** needs mailbox credentials, polling or webhooks, and matching
  replies to records — the Integrations phase is the right place.

## Proposed order of work (each step stops for review)

| Step | What |
|---|---|
| CC0 | This ADR + the phase in implementation-plan.md (documents only) |
| CC1 | Tables, migration 0038 with forced RLS, permissions |
| CC2 | Sending: API, outbox job, worker, timeline entry, audit, consent and limit checks |
| CC3 | Templates: create, edit, preview, placeholder check |
| CC4 | Conversation history per record + log a received e-mail |
| CC5 | Screens: composer dialog, Templates page, Communication Center page, module tile |
| CC6 | Playwright journey with Mailpit, docs/communications.md, CLAUDE.md, full test run |
