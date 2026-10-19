# ADR 0005 — S3 file storage (SeaweedFS), an outbox + worker, and e-mailed quote PDFs

- **Status:** Accepted (2026-10-19; steps C1, E2a, E2b and E2c done - see docs/background-jobs.md, docs/quotes-catalog.md)
- **Date:** 2026-10-19
- **Deciders:** Project owner

## Context

Phase E1 delivered quotes, but two things were left out because the building blocks don't
exist yet:

1. **Stored quote PDFs.** Today `/print/quotes/<id>` renders a page and the user saves it as a
   PDF with the browser. Nothing is kept, so we can't prove later *exactly* what the customer
   received.
2. **E-mailing a quote from the CRM.** Today "Mark as sent" only records that someone sent it
   by other means.

`architecture.md` already plans the pieces (§11 background work, §12 documents) and marks the
stack choices as decisions. This ADR makes them concrete. It is the first part of gap-analysis
Phase C; teams and row-level security (RLS) are **not** part of it.

Constraints:

- Everything runs locally; e-mails must never reach real inboxes (Mailpit catches them).
- An HTTP request must not fail or hang because the mail server or the file store is slow;
  and a quote must never be marked "sent" while its e-mail silently got lost.
- Modules write only their own tables (import-linter contracts).
- No secrets in code; Windows + Docker Desktop.

## Decisions

1. **An S3-compatible file store: SeaweedFS** (changed from MinIO on 2026-10-19, see
   "Amendment" below). A pinned `chrislusf/seaweedfs` container is added to
   `infrastructure/docker-compose.yml` with a named volume, one private bucket `crm-files`, and
   an access key + secret from `infrastructure/.env` (placeholders in `.env.example`); anonymous
   access is not allowed. Object keys always start with the tenant:
   `tenant/{tenant_id}/{module}/{record_id}/{file_id}`. The backend uses a generic S3 client,
   wrapped in `app/core/storage.py`, so the rest of the code never sees the store directly
   (a test double replaces it in tests) and another S3 store (MinIO, AWS S3) is a settings
   change.

2. **A small `documents` module** (plan Phase 10, metadata only for now): table `documents`
   with `tenant_id`, linked record (type + id), file name, content type, size, SHA-256
   checksum, `created_by`, `created_at`, and a `customer_visible` flag. The bytes live in the S3 store.
   Downloads go **through the API** after the usual checks (permission + record-level policy of
   the linked record; portal users only for `customer_visible` documents of their own
   accounts). Other modules create documents only through `documents/api.py`. Upload screens
   and versioning come later with the rest of Phase 10.

3. **Outbox + worker.** A table `outbox_jobs` (tenant, kind, JSON payload with IDs only — never
   personal data or secrets, status `pending/running/done/failed/dead`, attempts, next try time,
   last error). A service adds a job **in the same transaction** as its change, so either both
   happen or neither. A worker process, `python -m app.worker` (same codebase, its own CMD
   window), takes jobs with `SELECT … FOR UPDATE SKIP LOCKED`, runs the job's handler, and
   retries with growing delays (1 min, 5 min, 30 min, 2 h, 6 h); after 5 failures the job is
   `dead` and shown to admins. Handlers must be safe to run twice. No Redis/RabbitMQ.

4. **Server-side PDFs with ReportLab.** Pure Python, no system libraries (WeasyPrint needs GTK
   on Windows; a headless browser is heavy). The PDF is built from the **same data** as the
   print page: lines, totals, validity, customer note — never internal notes or approval
   details. A PDF is stored when a quote is **sent** (that version is what the customer got); a
   revision gets its own PDF. Staff and the customer download it from the quote page.

5. **E-mail through SMTP**, Python's built-in `smtplib`, wrapped in `app/core/mail.py`.
   Locally it points at Mailpit (`SMTP_HOST=localhost`, `SMTP_PORT=1025`); settings in `.env`.
   The quote page gets **"Send by e-mail"** next to "Mark as sent":
   - it needs a contact with an e-mail address on the quote (the staff user sees the address
     before confirming; the address is not taken from the request body);
   - the quote moves to **sent** at once and a job `quote.email` is queued; the worker builds
     and stores the PDF, sends the e-mail with the PDF attached, and records "e-mailed to …" in
     the quote history; on a permanent failure the history says so, and staff can retry;
   - a quote e-mail is a transactional message, so it does **not** depend on the contact's
     marketing consent (`email_consent`).

6. **The approval limit becomes a setting per organisation** (`quote_approval_limit_percent`,
   default 10, 0–100, changed only by tenant admins, audited). This is small and independent of
   the rest; it is listed here only so the whole quote follow-up is in one place.

## Amendment (2026-10-19): SeaweedFS instead of MinIO

While starting step C1 it turned out that MinIO no longer publishes community container
images: `minio/minio` and `quay.io/minio/minio` (including `latest`) can't be downloaded. The
owner chose **SeaweedFS** (Apache 2.0, one container, S3 API) over a local folder or Garage.
Because the code only speaks S3 through `app/core/storage.py`, nothing else in this ADR
changes. architecture.md is updated accordingly.

## Consequences

- One more container (SeaweedFS) and one more process to start (the worker). The
  commands table in CLAUDE.md gets "Run worker".
- New dependencies: an S3 client and `reportlab` (both pinned). Mail uses the standard library.
- New migrations: `documents`, `outbox_jobs`, the approval-limit setting.
- The outbox is the foundation for later work that is waiting for it: e-mail reminders for
  tasks, notifications, workflows and the Communication Center.
- Tests: storage and SMTP are replaced by in-memory doubles in unit/API tests; one E2E journey
  checks the real path (send by e-mail → message with PDF in Mailpit → PDF download in staff
  and portal; a different customer gets 404).
- Backups (Phase H) must include the file-store volume as well as PostgreSQL.

## Alternatives considered

- **Store PDFs in PostgreSQL (`bytea`).** Simplest, but the architecture already chose MinIO
  for files, and the database would grow quickly once uploads arrive.
- **Generate and e-mail inside the request.** No worker needed, but a slow or down mail server
  would make the "Send" button hang or fail after the quote changed state.
- **Celery/RQ with Redis.** More moving parts than this project needs now; the job table can be
  swapped later behind the same interface (architecture.md §11).
- **Headless-browser PDF (Playwright).** Would reuse the print page exactly, but needs a
  Chromium download on the server side and is slow to start.

## Proposed order of work (each step stops for review)

1. **C1 — infrastructure:** SeaweedFS container, `app/core/storage.py`, `app/core/mail.py`,
   `outbox_jobs` + worker with retries, tests.
2. **E2a — documents + quote PDFs:** `documents` module (metadata + authorised download), PDF
   stored on send, download buttons for staff and portal.
3. **E2b — e-mail quotes:** "Send by e-mail", worker job, history entries, Mailpit E2E.
4. **E2c — approval limit setting** (can also go first; it is independent).
