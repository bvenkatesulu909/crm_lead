# Call recordings (ADR 0030)

Status: **CA1 (backend) built 2026-11-13.** Cleaning, transcription and the lead-page card come in CA2 and CA3.

## What exists now
A rep adds a recording of a call to a lead the rep may read. The file goes straight to the file store
(signed link, as for documents, ADR 0025) and is checked when the upload is finished.

| Endpoint | What it does |
|---|---|
| `POST /api/v1/leads/{id}/calls/uploads` | Start: file name, size, language (hi / te / en) and the **consent** tick. Returns a 5-minute signed upload. |
| `POST /api/v1/leads/{id}/calls/{call_id}/finish` | Reads the first bytes back, checks they match the type, keeps the file, status `queued`. |
| `GET /api/v1/leads/{id}/calls`, `/{call_id}` | List / one recording (the transcript is only on the single read). |
| `GET /api/v1/leads/{id}/calls/{call_id}/listen` | A 60-second signed link; audited. |
| `DELETE /api/v1/leads/{id}/calls/{call_id}/audio` | Deletes the stored audio (the row stays). |

## Rules
- Consent is required and stored (who, when). Only an explicit `true` counts.
- Types: mp3, m4a, wav, ogg, webm, amr - by name **and** content. Limits: 100 MB, 60 minutes.
- Off by default: registry entry `call_audio` (no model). Limits: 20 uploads per person per hour, 300 per organisation per day.
- A lead the person may not read is a 404. Permissions `call:read` / `call:write` (sales roles).
- Audit holds ids and codes only; the table is forced-RLS and rows cannot be deleted.
- Settings: `CRM_CALLS_MAX_BYTES`, `_MAX_MINUTES`, `_RETENTION_DAYS` (90), `_UPLOADS_PER_USER_HOUR`, `_UPLOADS_PER_TENANT_DAY`, `_UPLOAD_FINISH_MINUTES`.

## Not yet
Audio cleaning (ffmpeg), transcripts, retention sweep, expiry of stale uploads in the worker (CA2); the card on the lead page and a measured trial (CA3).
