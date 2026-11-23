# Property photo enhancer

Design: [ADR 0039](adr/0039-property-photo-enhancer.md). This page says what is built and how it behaves.

**Status:** PE1 (the image rules), PE2 (the request, the worker job, storage), PE3 (the API), PE4 (the
screens) and PE5 (photos in proposal decks) are built.

## 1. What it does, in plain words

A sales person picks a photo that is already attached to an account or a deal and asks for an **adjusted
copy**. The server makes the copy in the background and keeps it next to the photo. The original is never
changed. The copy is a new JPEG that is only a *truer* version of what the camera saw: brighter, straighter,
cropped, smaller, with the agency's mark in a corner. It can never add or remove anything from the scene.

## 2. The allowed adjustments (and their caps)

Code: `backend/app/modules/photo_enhancer/rules.py`. Every value has a hard cap. A value above its cap is
**refused**, not quietly reduced, so the record shows exactly what was done.

| Adjustment | Cap |
|---|---|
| Even out exposure (`auto_exposure`) | a blend of the picture with a stretched copy, plus a gentle lift of dark photos (gamma never below 0.7, aimed at a middle grey) |
| Correct a colour cast (`auto_white_balance`) | each colour moves by at most 15 % |
| Brightness | -30 % to +30 % |
| Contrast | -20 % to +20 % |
| Straighten | up to 5 degrees; the empty corners are cut away, nothing is invented |
| Crop | must keep at least 60 % of the width and of the height |
| Sharpen (`sharpen`) | one mild setting |
| Size preset | `original` (at most 4,000 px), `brochure` 2,000, `whatsapp` 1,280, `thumbnail` 400; never made bigger |
| Watermark | the organisation's logo or up to 40 characters of text, in one of four corners |

Not available, by design: replacing the sky, removing or adding objects, virtual staging, changing a room's
size, heavy filters. A request that names anything else (for example `sky_replacement` or a model) is refused.

## 3. What happens to the file

* The upload is checked from its header before any pixel is decoded: at most 20 MB, 50 megapixels and
  12,000 px a side; JPEG or PNG (the documents module does not accept WebP, so neither does the enhancer);
  no animation.
* The photo is decoded and **written again**. All metadata, including the **GPS position** and the camera's
  details, is dropped. One sentence is written into the file: "Enhanced copy of an original photo.
  Adjustments only: nothing added or removed."
* The copy is a JPEG of at most 4,000 px and 5 MB. The same input and the same adjustments give the same
  bytes.
* Decks and brochures that use a copy must print the fixed caption "Photo adjusted for brightness and
  colour" (the text is `DECK_CAPTION`; the decks use it in PE5).

## 4. Who may use it

* Off until an administrator switches **Property photo enhancer** on in *AI agents* (it calls no language
  model). A platform-wide switch, `CRM_PHOTO_ENHANCER_DISABLED`, stops it everywhere.
* Permission `photo:enhance` (sales agents, sales managers, administrators) **and** `document:write`, and the
  photo's record must be one the person may see (an agent: their own accounts and deals; a manager: all).
  Support staff and customers cannot adjust photos. Someone who may not see the photo gets "not found".
* Limits, counted before a job is queued: 5 copies per photo (a failed one does not count), 30 a person an
  hour, 500 an organisation a day (`CRM_PHOTO_ENHANCEMENTS_PER_ORIGINAL`, `..._PER_USER_HOUR`,
  `..._PER_TENANT_DAY`).

## 5. How it is stored

* The adjusted copy is a row in `documents` with purpose `property_photo_enhanced`, pointing at its original
  through `derived_from_id`. It is **not** listed as an ordinary document. It has the original's customer
  visibility. **Deleting the original deletes its copies**: the database removes the rows, and the delete
  endpoint hands back the copies' file keys with the original's.
* `photo_enhancements` has one row per request: the photo, who asked, the adjustments exactly as asked, the
  state (`queued`, `ready`, `failed`), a short failure code, the plain-words list of what was done, the size and
  the copy. Forced row-level security; the database refuses a `ready` row without a copy and a `failed` row
  without a reason.

## 6. The worker (`photo.enhance`)

* Reads the photo, refuses a photo that would need more than `CRM_PHOTO_ENHANCER_MAX_MEMORY_MB` (default 600,
  about 12 bytes a pixel, which allows every photo up to the 50-megapixel limit) and stops work after
  `CRM_PHOTO_ENHANCER_MAX_SECONDS` (default 60). A failure ends the request as `failed` with one of the codes
  `too_large`, `not_an_image`, `unreadable`, `took_too_long`, `watermark_logo_missing`, `photo_enhancer_off`,
  `processing_failed`; nothing half-made is stored.
* A second run of the same job does nothing. A store that is down is retried by the outbox.
* Each finished copy counts as one use in the month's usage; the audit records `photo.enhancement_requested`,
  `photo.enhanced`, `photo.failed` and `photo.copy_deleted` with ids, the list of adjustments and sizes, never
  the picture or its file name.

## 7. The API (`/api/v1/photo-enhancer`, staff only)

| Call | What it does |
|---|---|
| `POST /previews` | body `{document_id, operations}`; answers a small JPEG (at most 800 px, `no-store`) made by the same code from a reduced working copy; stores and queues nothing; at most 30 a person a minute (`CRM_PHOTO_PREVIEWS_PER_MINUTE`, counted in this process) |
| `POST /enhancements` | the same body; records the request and queues the job; 201 with the request in state `queued` |
| `GET /enhancements?document_id=` | the requests made for one photo, newest first, with the fixed `caption` the screens and decks print |
| `GET /enhancements/{id}/link` | a 60-second signed link to a finished copy (404 while waiting or failed) |
| `DELETE /enhancements/{id}` | deletes one request and its copy, never the original; 204 |

The body takes only the photo and the adjustments (unknown fields are refused with 422); the tenant, who
asked, the state and the copy are the server's. Answers: 403 without `photo:enhance` (or `document:read` for
listing and links), 404 for a photo or copy the person may not see (also another organisation's), 422 with a
stable code (`photo_operation_too_strong`, `photo_operation_unknown`, `photo_preset_unknown`,
`photo_watermark_logo_missing`, `photo_not_an_image`, `photo_too_large`), 429 `photo_limit_reached`, 503
`photo_enhancer_unavailable`.

## 8. The screens (PE4)

* **Documents card** (account and deal pages): next to a JPEG or PNG, people who may adjust photos see an
  "Adjust photo" link. Nothing is shown to anyone else.
* **`/photos/<document id>`**: sliders for brightness, contrast and straightening, tick boxes for the quick
  fixes, four trim sliders for the crop, a size menu and a watermark (none, text or our logo, with a corner).
  The sliders stop at the API's caps. A **preview** is made by the server (about every half second after the
  last change) and shown beside the sliders. The warning "Check for people and number plates before sharing
  this photo." is always shown, and so is a plain note that the copy only adjusts what the camera saw.
* **Adjusted copies** below: each shows an "Enhanced" badge once it is ready, the list of what was done, the
  size, "Download copy", "Show original" (original and copy side by side) and "Delete copy" (after a
  confirmation; the original is never touched). While a copy is being made the page looks again every
  four seconds. A failed copy says why in words.
* The browser sends only the adjustments, to this app's own route handlers (`/photos/<id>/preview`,
  `/photos/copies/<id>/download`); the token stays on the server. Pictures reach the page through the
  signed links of ADR 0025.

## 9. Photos in proposal decks (PE5)

* A sales person ticks **Use in proposal decks** on a finished copy (the Adjusted copies list, or
  `PATCH /api/v1/photo-enhancer/enhancements/{id}` with `{"in_decks": true}`). Nothing is put in a deck
  that nobody chose: a new copy starts unchosen. Only a finished copy can be chosen (409 otherwise), and the
  choice is audited (`photo.deck_choice`).
* When a deck is made (PDF or PowerPoint) the worker adds a **"The property" slide**, after "About us" and
  "Why this proposal" and before "What we propose", with the chosen copies whose original photo is on the
  quote's account or deal - at most four, newest first, in a grid, each with the fixed line
  "Photo adjusted for brightness and colour". With nothing chosen there is no such slide.
* The deck draws a copy only if its file still carries the "adjusted copy" note the enhancer wrote
  (`rules.has_label`); a copy whose file is missing, damaged or without the note is skipped, never fatal.
* A photo chosen on another customer's account or deal never reaches this quote's deck.
* Brochures: the CRM does not generate brochures (property brochures are uploaded files read by the
  knowledge base), so there is nothing to add a photo to there; the rule for any future generator is the same
  (only chosen, labelled copies, with the fixed caption).

## 10. Not built yet

* PE6: final docs and gate tests.
* The retention rule for copies of closed deals (ADR question 4) and noise reduction.
* Faces and number plates are not detected or blurred (ADR question 5): the warning is the only help.
