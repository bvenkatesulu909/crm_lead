# Files, e-mail and background jobs (Phase C1, ADR 0005)

Three building blocks that the next steps (stored quote PDFs, e-mailing quotes, later task
reminders, notifications and workflows) are built on. Nothing visible in the CRM changes yet.

## What runs where

| Piece | What it is | Where |
|---|---|---|
| File store | **SeaweedFS**, an open-source store with the same "S3" API as Amazon S3 and MinIO. Keeps files (PDFs, later uploads) outside the database | Docker container `files`, `127.0.0.1:8333` |
| Mail catcher | **Mailpit** catches every e-mail; nothing reaches real inboxes | inbox http://localhost:8025, SMTP `127.0.0.1:2525` |
| Worker | A second Python process that runs background jobs | `python -m app.worker` (own CMD window) |

Why SeaweedFS and not MinIO? The plan said MinIO, but MinIO no longer publishes its container
images, so they can't be downloaded. SeaweedFS speaks the same S3 language, and the CRM only
talks to it through `app/core/storage.py`, so switching store later is a configuration change.

## Starting everything (Windows CMD)

```
cd infrastructure
docker compose up -d
```

Then, besides the API (`uvicorn …`) and the web app (`npm run dev`), open one more CMD window:

```
cd backend
.venv\Scripts\activate
python -m app.worker
```

`Ctrl+C` stops the worker after the job it is working on. `python -m app.worker --once` runs
every job that is due now and exits (handy for checking).

## Settings

`infrastructure\.env` holds the file store's access key and secret (`FILES_S3_ACCESS_KEY`,
`FILES_S3_SECRET_KEY`); `backend\.env` holds the same values as `CRM_FILES_S3_ACCESS_KEY` /
`CRM_FILES_S3_SECRET_KEY`, plus `CRM_SMTP_HOST` / `CRM_SMTP_PORT`. The `.env.example` files list
every setting with placeholders. Without file-store keys the API still starts; only features
that store files answer **503** ("file storage is not configured").

The file store refuses every request without the key (tested: anonymous → 403).

## How a background job works (the "outbox")

1. A service saves its change **and** a row in `outbox_jobs` in the same database transaction:
   either both are saved or neither. So a quote can never be "sent" without its e-mail job.
2. The worker looks for due jobs every 2 seconds. It locks one row with
   `SELECT … FOR UPDATE SKIP LOCKED`, so two workers never take the same job.
3. It runs the job's handler. Success: the handler's database changes and "done" are saved
   together.
4. Failure: everything the handler did is undone, and the job is tried again after 1 min, then
   5 min, 30 min, 2 h, 6 h. After 5 attempts - or at once for errors that can't get better
   (e.g. the mail server refuses the address) - the job becomes **dead**.
5. A job left "running" for 15 minutes (its worker crashed) is picked up again. Handlers are
   written so that running twice does no harm.

Rules for job data: the payload contains **IDs only** (no names, e-mail addresses, tokens). The
stored error is the error type only (plus our own safe messages), because error texts can
contain personal data.

## Code map

| File | Purpose |
|---|---|
| `backend/app/core/storage.py` | `FileStore` interface; `S3FileStore` (real), `MemoryFileStore` (tests), `UnconfiguredFileStore` (503). Keys: `tenant/{tenant_id}/{area}/{record_id}/{file_id}` |
| `backend/app/core/mail.py` | `Mailer` interface; `SmtpMailer` (real), `MemoryMailer` (tests); header-injection safe; temporary vs permanent failures |
| `backend/app/core/outbox.py` | `outbox_jobs` table, `enqueue()`, `run_next_job()`, retries |
| `backend/app/worker.py` | The worker program and the list of job handlers |
| `backend/alembic/versions/20261019_0014_outbox_jobs.py` | Migration 0014 |

## Tests

- `tests/test_files_and_mail.py` - keys, 503 without configuration, connection failures,
  e-mail building, header injection, SMTP error mapping (no real servers).
- `tests/db/test_outbox.py` - job only with a committed change, done + handler work together,
  rollback and retry with delay, dead after too many tries or permanent errors, unknown kinds,
  crashed workers, two workers at the same time.
- A live smoke test (2026-10-19) stored/read/deleted a file in SeaweedFS, sent an e-mail with a
  PDF attachment that arrived in Mailpit, and started the worker.

## Not built yet

- Job kinds so far: `quote.pdf` (stores the PDF of a sent quote, E2a) and `quote.email`
  (e-mails a quote with its PDF, E2b). When a job dies, a "dead-job handler" can note it in the
  record's history in the same transaction (used by `quote.email`).
- A screen for admins to see dead jobs, and clean-up of old finished jobs.
- Backups of the file-store volume (Phase H).
