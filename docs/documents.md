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
| `GET /documents/{id}/versions` | all versions, newest first |
| `GET /documents/{id}/download` | the file |
| `DELETE /documents/{id}` | delete with all versions (204) |
| `GET /portal/documents?account_id=…`, `GET /portal/documents/{id}/download` | customer portal |

Error codes: `record_not_found`, `document_not_found` (404), `file_too_large` (413),
`file_type_not_allowed` (415), `invalid_document` (422), `upload_conflict` (409),
`files_unavailable` (503, file store not configured or down).

## Database

Migration `20261019_0017_document_uploads_and_versions`: `documents` gets `group_id`,
`version_no` and `description`; record types `account` and `opportunity`; purpose
`attachment`. Document rows can't be updated by the application (only added or deleted).

## Not built yet

- Documents on contacts, orders and tickets; customers uploading files in the portal.
- Virus scanning of uploads (needs a scanner such as ClamAV - an infrastructure decision).
- Full-text search in documents.
