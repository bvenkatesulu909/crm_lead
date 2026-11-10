# Documents (Phase 10)

Files that belong to a **customer account** or a **deal**: contracts, offers, requirements,
signed forms. Quote PDFs are stored automatically when a quote is sent (see
[quotes-catalog.md](quotes-catalog.md)).

## What you can do

| Who | Can |
|---|---|
| Tenant admin, sales manager | upload, download, see versions, **delete** (all versions) |
| Sales agent | upload and download - on their own customers and deals only |
| Support agent | download (all accounts) |
| Customer (portal) | download files **shared with their company** (newest version only) |

- **Upload** on the account page or the deal page (card "Documents" → *Upload*).
- **Versions:** uploading a file with the **same name** to the same record saves it as the next
  version (2, 3, …). Lists show the newest version; *Older versions* lists the rest.
- **Share with the customer:** tick *Visible to the customer in the portal* (account files
  only - deal files are always internal). The portal shows the newest version only if that
  version is shared, so uploading an internal draft hides the document again.
- **Delete** removes the document with all its versions (managers and admins). Audited.

## Rules that protect you

- **Access follows the record.** The documents module asks the accounts/deals module whether
  you may see the record. If not, you get "not found" (404), never a hint that the file exists.
- **Allowed files:** PDF, PNG, JPG, GIF, TXT, CSV, Word (.docx), Excel (.xlsx), PowerPoint
  (.pptx), OpenDocument (.odt, .ods). The type is checked by the file's **name and its first
  bytes**, never by what the browser claims - a "report.pdf" that is really a program is
  refused. HTML, SVG and programs are never allowed.
- **Size:** up to 20 MB (`CRM_FILES_MAX_BYTES`).
- **File names** are cleaned: no folders, control or reserved characters, at most 150 characters.
- **Downloads** are always sent as attachments with `X-Content-Type-Options: nosniff`, so a
  file can't run in the browser. The browser asks the Next.js server, which fetches the file
  from the API with your token - the token never reaches the browser.
- **Storage keys** are `tenant/{tenant}/{accounts|opportunitys}/{record}/{document}` and built
  only from server-side IDs; another tenant's key can't be reached (tested). A SHA-256
  checksum is saved and checked on every download.

## API (all under `/api/v1`)

| Method and path | What it does |
|---|---|
| `GET /documents?record_type=account|opportunity&record_id=…` | newest version of each document |
| `POST /documents` (multipart: `record_type`, `record_id`, `file`, `customer_visible`, `description`) | upload (201); same name = new version |
| `POST /documents/uploads` (JSON: `record_type`, `record_id`, `file_name`, `size_bytes`, `customer_visible`, `description`) | start a **direct upload** (ADR 0025): the same checks, then a 5-minute signed link for the file (201) |
| `POST /documents/uploads/{upload_id}/finish` | the file sent with that link is checked and becomes a document version (201) |
| `GET /documents/{id}/versions` | all versions, newest first |
| `GET /documents/{id}/download` | the file |
| `DELETE /documents/{id}` | delete with all versions (204) |
| `GET /portal/documents?account_id=…`, `GET /portal/documents/{id}/download` | customer portal |

Error codes: `record_not_found`, `document_not_found` (404), `file_too_large` (413),
`file_type_not_allowed` (415), `invalid_document` (422), `upload_conflict` (409),
`files_unavailable` (503, file store not configured or down); direct uploads also `upload_not_found` (404),
`upload_not_received` (409, the file has not arrived yet - send it, then finish again), `upload_expired` (410)
and `upload_limit_reached` (429).

### Direct uploads (ADR 0025)

The web app's host (Netlify) refuses requests of 6 MB or more, so the file goes from the browser straight to the
private file store:

1. **Start** - the API checks what it can before the bytes arrive (document:write, a record the person may see,
   account-only customer visibility, size <= 20 MB, a type allowed by name), counts the person's uploads this
   hour (`CRM_FILES_UPLOADS_PER_USER_HOUR`, 60), stores a pending row and hands out a five-minute signed POST
   policy for `pending/{tenant}/{upload}`. The store itself refuses another key, another type or a bigger body.
2. **Send** - the browser POSTs the fields and then the file to the store.
3. **Finish** - the row must be this person's, still pending and younger than `CRM_FILES_UPLOAD_FINISH_MINUTES`
   (60); the stored size is checked; the bytes are read back once and go through the normal upload, so the type
   check by name AND content, versions, the audit entry and events are exactly the same; the pending file is
   deleted. A refused file is deleted too. Record, name, visibility and description come from the row, never from
   the browser.

The worker deletes upload rows a day old and any pending file left behind. The multipart `POST /documents` stays
for tests and small files.

## Database

Migration `20261019_0017_document_uploads_and_versions`: `documents` gets `group_id`,
`version_no` and `description`; record types `account` and `opportunity`; purpose
`attachment`. Document rows can't be updated by the application (only added or deleted).
Migration `20261110_0054_document_uploads` (ADR 0025): `document_uploads` - pending direct uploads (who, which
record, cleaned name, type, declared size, status), forced row-level security, deleted by the worker after a day.

## Not built yet

- Documents on contacts, orders and tickets; customers uploading files in the portal.
- Virus scanning of uploads (needs a scanner such as ClamAV - an infrastructure decision).
- Full-text search in documents.
