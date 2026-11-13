# Call recordings (ADR 0030)

Status: **CA1 (backend) and CA2 (worker) built 2026-11-13.** The lead-page card and a measured trial come in CA3.

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

## What the worker does (CA2)
Finishing an upload adds the job `call.process` (ids only) in the same transaction. The worker:

1. checks that the audio still exists, the `call_audio` switch is on and the month's minutes are not used up;
2. reads the length with `ffprobe` and refuses above `CRM_CALLS_MAX_MINUTES` (default 60) before any cleaning;
3. cleans the audio with `ffmpeg` (one mono 16 kHz channel, low rumble and hiss reduced, loudness levelled, 48 kbit/s mp3) and stores the **cleaned copy next to the original**, which is never changed;
4. sends the cleaned audio to the speech service **with the language the rep chose** (hi / te / en) and gets text with the time of each segment (a Whisper-class model, `CRM_CALLS_STT_MODEL`, default `whisper-1`);
5. stores the transcript (hidden characters removed, cut at 500,000 characters), the segments, the engine name and the length, adds the seconds to the month's usage, and the row is `ready`.

A recording that cannot be processed for a reason retrying will not fix ends `failed` with a short code: `too_long`, `unreadable`, `no_speech`, `call_audio_off`, `budget_reached`, `audio_deleted`. A set-up problem (no ffmpeg, no speech service) makes the job fail for good and the row `processing_failed`. A temporary problem (the speech service is down) is retried by the outbox; when the retries run out the row is `processing_failed`. Running the same job twice does nothing the second time.

Every day the worker also: expires uploads that were never finished (a day old) and deletes the **audio** (original and cleaned copy) `CRM_CALLS_RETENTION_DAYS` (90) after a recording finished. The row, the consent record and the transcript stay. Worker audit entries are written by the organisation's Automation identity, with ids and codes only (never the transcript).

The transcript is a machine's guess and people's words are untrusted: it is stored and shown as plain text and no model reads it in this version.

Settings added: `CRM_CALLS_STT_MODEL`, `CRM_CALLS_MONTHLY_MINUTES` (600, estimated from the audio length), `CRM_CALLS_FFMPEG_COMMAND`, `CRM_CALLS_FFPROBE_COMMAND`, `CRM_CALLS_CLEAN_TIMEOUT_SECONDS`. The Docker image now installs ffmpeg; on a PC without it the worker marks recordings `processing_failed` (install ffmpeg to try it locally).

## Not yet
The card on the lead page, the player and the transcript view (CA3); a measured trial on fictional Hindi, Hinglish and Telugu samples (CA3).
