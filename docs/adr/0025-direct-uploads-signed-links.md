# ADR 0025 — Large files go straight to the file store through short-lived signed links

- **Status:** Proposed (2026-11-10) - waits for the owner's answers to the questions in section 6
- **Date:** 2026-11-10
- **Deciders:** Project owner
- **Depends on:** ADR 0005 (file store), ADR 0007 / ADR 0021 (Netlify for the web app, one server for
  the rest); the go-live checklist line "Upload/PDF sizes verified" in `docs/deployment.md`

## 1. The problem

The CRM promises **20 MB** per document (`CRM_FILES_MAX_BYTES`). Today every file travels
**browser -> web app on Netlify (a Server Action) -> API -> file store**, and back the same way on
download (`/documents/{id}/download`, `/portal/documents/{id}/download`, quote PDFs). Netlify runs
that web app as functions with a request limit: measured on `crm.crmlead.co.in` on 2026-11-09, **any
request of 6 MB or more is refused with 413** before it reaches the CRM. So:

- a document or knowledge upload above about 5 MB fails in the live set-up (it works on a PC, where
  there is no Netlify);
- a download above the same size is at risk in the other direction (Netlify also limits the size of
  what a function sends back - to be measured in step DU0).

Lowering the limit to 5 MB was the other option; the owner chose signed links (2026-11-10).

## 2. The idea in one picture

```
UPLOAD                                              DOWNLOAD
browser --1--> web app --2--> API                   browser --1--> web app --2--> API
   "I want to upload brochure.pdf, 14 MB"              "download document 42"
                       API checks permission,                     API checks permission
                       record, name, size, type                   (the same rules as today)
   <-- a signed link, valid 5 minutes, for ONE          <-- 302 to a signed link, valid 60 s,
       pending object; the bucket itself refuses           for that ONE object, "save as" name
       anything bigger than the declared size
browser --3--> file store (direct, never Netlify)   browser --3--> file store (direct)
browser --4--> web app --5--> API "finish"
   API reads the object back from the store, runs the SAME checks as today (type from name AND
   content, size, SHA-256), stores it under its real name, records the document version, audits it,
   deletes the pending object. A file that fails is deleted and nothing is recorded.
```

The browser never receives a token or a store key: a signed link opens exactly one object, for one
action, for a few minutes, and carries no account rights.

## 3. Decisions (proposed)

**U1 - Two steps around a pending object.** `POST .../uploads` (permission, the record exists and the
person may write to it, file name, declared size <= the limit, a type allowed by name) returns an
`upload_id` and a signed upload for the key `pending/<tenant>/<upload_id>`. `POST .../uploads/{id}/finish`
reads that object back **inside the server**, runs today's checks unchanged (`rules.detect(name,
first bytes)`, size, empty file, SHA-256), writes the final object under today's key scheme, records the
version exactly as `upload()` does now (same audit, same events), and deletes the pending object.
Knowledge documents do the same and then extract the text from the object they read back.

**U2 - The bucket enforces the size, not only our code.** Preferred: an S3 **POST policy** with
`content-length-range 1..declared size` and the exact key and content type - the store refuses a
larger body before storing it. If the file store in use does not honour POST policies (checked for
SeaweedFS and Google Cloud Storage in step DU0), fall back to a signed **PUT** and let `finish` delete
anything larger than declared. Either way `finish` checks the real size again.

**U3 - Pending objects never become documents by themselves.** Only `finish` creates a document, and
only from its own `pending/` key for the same person, organisation and record (stored server-side with
the `upload_id`, never taken from the browser). A `pending/` object older than one day is deleted - a
bucket lifecycle rule where the store supports it, plus a worker sweep that works everywhere.

**U4 - Downloads by signed link too.** The download routes keep their permission checks; instead of
streaming the bytes they answer **302** to a signed GET link valid **60 seconds**, with the "save as"
name set by the store (`response-content-disposition: attachment`). Quote PDFs the same way.

**U5 - The old way stays for small files and for tests.** The existing multipart endpoints remain
(the tests and other API clients use them, and they work on a PC where there is no Netlify); the web app
switches to signed links for every document and knowledge upload, so there is one path in production.

**U6 - The store must accept the browser.** The files bucket needs a CORS rule: allow `PUT`/`POST`
(and `GET` for downloads) **only** from the web app's address (`https://crm.crmlead.co.in` on
staging, `http://localhost:3000` on a PC), no credentials. The bucket stays private; there is no public
read. The web app's Content-Security-Policy gains the store's address in `connect-src`.

**U7 - Nothing secret leaves the server.** Links are made by the API with the store keys it already
has; they are never logged (only the `upload_id`); the store address and key are not shown to people;
the link's lifetime is the only "right" it carries.

## 4. What stays the same

Who may upload or download what (permissions, record-level rules, customer visibility, the portal's
grants), the allowed file types, the 20 MB limit, versions, audit entries, events, retention, the
insert-only rules of the documents table. A file that passes today passes tomorrow; one refused
today is refused tomorrow.

## 5. Steps (Phase DU), each stops for review

| Step | Content |
|---|---|
| DU0 | Measure on staging: the largest download Netlify passes; whether SeaweedFS (PC) and Google Cloud Storage (staging) honour signed POST policies and CORS. Documents only, no code |
| DU1 | `app/core/storage.py`: signed upload (POST policy or PUT) and signed download, `stat`, `copy`; tested against the in-memory store and the real SeaweedFS |
| DU2 | Documents: `POST /documents/uploads`, `.../finish`, pending table or rows, the sweep; tests for every rule (permission, record, tenant, ID tampering, a body bigger than declared, a wrong type disguised by name, finishing someone else's upload, finishing twice) |
| DU3 | Knowledge documents the same; downloads (documents, portal, quote PDFs) by 302 to a signed link |
| DU4 | Web app: the upload dialogs send the file straight to the store with progress and clear errors; CSP `connect-src`; Playwright journey with a 15 MB file |
| DU5 | Staging: CORS and lifecycle rule on the bucket (the owner runs the commands, or gives Claude the go-ahead), a real 15 MB upload and download through `crm.crmlead.co.in`; the checklist line ticked |

## 6. Questions for the owner (recommended answer first)

1. **Size enforced by the bucket (U2):** use a POST policy where the store supports it, with the PUT
   fallback checked in `finish`? *Recommended: yes.*
2. **Downloads by signed link as well (U4)**, 60 seconds, so large files can be downloaded too?
   *Recommended: yes.*
3. **Link lifetimes:** 5 minutes to start an upload, 60 seconds for a download? *Recommended: yes.*
4. **Keep the old upload endpoints (U5)** for tests and small files, with the web app always using the
   new path? *Recommended: yes.*
5. **Bucket settings on staging (U6, U3):** CORS for `https://crm.crmlead.co.in` only and a one-day
   lifecycle rule for `pending/` - Claude prepares the exact commands; you run them (or say Claude
   may, with the server's own access)? *Recommended: Claude prepares, you decide who runs them.*

## 7. Consequences

- Uploads and downloads of up to 20 MB work in the live set-up; Netlify only carries small requests.
- One more moving part: CORS on the bucket, and objects that may wait in `pending/` for up to a day.
- The file store's address becomes visible to the browser (not its keys). The bucket stays private.
- The API reads each uploaded file back once (server to store, in the same region), which costs a
  little time per upload and nothing on Netlify.
