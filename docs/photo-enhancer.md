# Property photo enhancer

Design: [ADR 0039](adr/0039-property-photo-enhancer.md). This page says what is built and how it behaves.

**Status:** PE1 (the image rules) and PE2 (the request, the worker job, storage) are built. There is no
endpoint and no screen yet (PE3, PE4), so nothing can be tried by a person today.

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

## 7. Not built yet

* PE3: API (preview, create, list, delete a copy, signed link). PE4: screens ("Enhance", sliders, "Show
  original", the "Enhanced" badge, the warning "Check for people and number plates before sharing"). PE5: decks
  and brochures using a copy with the fixed caption. PE6: gate tests and final docs.
* The retention rule for copies of closed deals (ADR question 4) and noise reduction are not built.
