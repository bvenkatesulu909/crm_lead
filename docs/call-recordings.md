# Call recordings (ADR 0030)

Status: **CA1 (backend), CA2 (worker) and CA3 (screen) built 2026-11-13.** The measured trial on real recordings is still to do (see "The trial").

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

## The screen (CA3)
Leads with `call:read` (sales agents, managers, administrators) get a **Call recordings** card on the lead page; the API still decides who may see which lead (a lead one may not read gives no card, and the page is "not found").

- **Add a call recording** (needs `call:write`): choose the file, the language of the call and tick that **the buyer agreed to the call being recorded**. The tick is never pre-filled and the form refuses without it; a refused attempt keeps what was chosen. The file goes from the browser straight to the file store (ADR 0025), so Netlify's 6 MB limit does not apply; the web app only ever sees the name and size.
- Each recording shows its file name, language, length, size, date and a status in words: *Being cleaned and transcribed* (the card looks again every 8 seconds), *Transcript ready*, or *Could not be processed* with the reason and what to do. A file that was refused (not really audio) stays on the card as a failed item.
- **Listen** asks for a fresh 60-second link and plays the **cleaned** copy. **Show transcript** reads the text on request: plain text, the time each stretch started, and a reminder that it is automatic and can contain mistakes. A transcript is never shown as markup and never linked.
- **Delete audio** asks first; the transcript and the record of the consent stay.
- The report-only content security policy lists the file store under `media-src` as well, for the player.

A bug the browser journey found and the unit tests now guard: a dialog whose item stays on the page after its action worked (the delete confirmation, the add form) stayed open as a modal and blocked the page. `ActionDialog` has an optional `closeWhen` value that closes it when the page shows the result; the call recordings use it. Other cards that redirect to a page that keeps the same item mounted may have the same problem; they were not changed.

## Trying it without ffmpeg or a speech service
`CRM_CALLS_ENGINE=fake` (API and worker; refused in production) skips ffmpeg and the vendor: the audio is passed through and every recording gets a fixed fictional transcript in the language chosen (Hindi, Telugu or English). The Playwright journey `frontend/e2e/call-recordings.spec.ts` uses it (`E2E_CALLS_FAKE=1`, no standing worker, file store running).

## The trial (still to do)
`python -m scripts.measure_call_transcription <folder> --engine real --also-original` (with `CRM_RUN_LIVE_EVALS=1`, ffmpeg installed and the speech service in `backend\.env`) transcribes a folder of made-up sample calls (`visit1.hi.mp3` + `visit1.hi.txt` with the words really said, and likewise `.te` and `.en`) and prints the word and character error rates per sample and language, for the cleaned and, with `--also-original`, the uncleaned audio, and the seconds it took. **It has not been run on real audio**: it needs sample recordings of fictional Hindi, Hinglish and Telugu conversations, ffmpeg on the machine and a paid speech call. The scripted mode (`--engine scripted`) only shows that the table works. Until the trial is run, no accuracy figure for Hindi, Hinglish or Telugu is claimed anywhere.

## Not yet
Live calling (ADR 0030 CA1 is uploads only); any AI reading of the transcript (CA7: transcripts are untrusted and no model sees them in this version); the measured trial above.
