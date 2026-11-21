# ADR 0039 — Property photo enhancer (honest enhancement, original always kept)

- **Status:** Proposed (2026-11-21). Waiting for the owner's answers to section 6.
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0025 (documents, signed direct uploads, the file store), ADR 0032 (branding and the
  logo that is re-drawn as a clean PNG), ADR 0016 (agent registry, kill switch), ADR 0009 (row-level
  security), ADR 0005 (file store, worker), CRM-115 / `docs/brochures-rera.md` (property brochures),
  ADR 0033 (the pattern of a derived copy stored next to an original and deleted with it)
- **Owner's feature list:** item 16, "Property photo enhancer".

## 1. The problem

Agents photograph properties on phones: dark rooms, tilted walls, colour cast, 12-megapixel files that are
too heavy to send on WhatsApp. They want the pictures to look good before sending them to buyers or putting
them in a brochure or proposal deck. Today the CRM stores a photo as a plain document and nothing more.

There is a trap. Photo apps now offer **generative** edits: replace a grey sky with a blue one, remove an
electricity pole, add furniture, make a small room look bigger. For a property that is *misleading
advertising*. In India, RERA expects advertising to be truthful about the project, and a buyer who visits and
finds a different view can complain, demand refunds or damage the agency's name. A CRM that makes this a
one-click action is a liability for its customers. So the key decision of this ADR is **what the enhancer is
allowed to change**.

## 2. What exists

- `documents` module: files on accounts and deals with versions, type checked by name and content, 20 MB limit,
  signed direct uploads (`start` / `finish`), 60-second signed download links, audit, per-person limits.
- `app/core/storage.py`: signed upload and download links, `copy`, `stat`, `read_head`, a stored "save as"
  name, a per-call size limit.
- `branding`: the logo is uploaded, **decoded with Pillow and re-drawn as a clean PNG** (no metadata, no
  trailing data, at most 800 px, decompression bombs refused from the header). The same decode-and-redraw habit
  is the base for this feature. Pillow is pinned (13.0.0); no OpenCV or numpy dependency exists today.
- Worker with outbox jobs, retries and a dead-job state; daily sweeps (retention).
- Agent registry with switch, monthly budget and a platform kill switch; entries that use **no model** exist
  (web check, voice).
- Proposal decks (ADR 0032) and brochures (CRM-115), which will want good pictures.

## 3. Decisions (proposed)

**PE1 - Honest enhancement only, done by code, no model, in v1.** The enhancer may do only things that make
the picture a *truer, cleaner record of what the camera saw*:

| Allowed (pure code, Pillow) | Not allowed (never offered) |
|---|---|
| Auto exposure and contrast (histogram stretch, gentle shadow lift, capped) | Sky replacement |
| White balance / colour-cast correction (capped) | Removing or adding objects, people, wires, cars |
| Straightening by a small angle (up to 5 degrees; the person chooses or confirms) | Virtual staging, furniture, repainting walls |
| Crop (rectangle chosen by the person; an automatic "level horizon" crop) | Changing room size, or perspective stretching beyond a small keystone fix |
| Resize to a size preset (WhatsApp 1280 px, brochure 2000 px, thumbnail) and JPEG quality | Beautify filters that change textures (heavy HDR look, smoothing) |
| Mild sharpening and noise reduction (capped) | Anything that adds pixels that were not in the photo |
| Watermark: the organisation's logo or text in a corner at the person's choice | |

Every operation has a **hard cap** in code, so even the allowed edits cannot be pushed into a different
picture. The caps are fixed values, not settings.

**PE2 - Generative edits are out of scope, and the door is shut on purpose.** If the owner ever wants them
(question 1) it needs a new ADR that covers: a disclosed AI label baked into the picture, a ban on changing the
property itself or its surroundings, an organisation switch that is off by default, and legal review of RERA
and advertising-standards rules. Nothing in this design leaves a hook that a later step could use by accident
(no "model" parameter, no call to an outside image service).

**PE3 - The original is never changed or deleted by the enhancer.** An enhancement is a **new stored file**
(a "derived copy") linked to the original: same account or deal, purpose `property_photo_enhanced`, with a row
that records the original, the list of operations with their values, the tool version and the size. The
original stays as uploaded. Deleting the original also deletes its derived copies (same rule as the highlight
clips of ADR 0033); deleting only a derived copy is allowed.

**PE4 - A clear "enhanced" label, in three places.**
1. **On screen:** every derived copy shows an "Enhanced" badge and the list of what was done ("Brightness
   +12 %, straightened 1.5 degrees, cropped, resized to 1280 px"); the original is one click away ("Show
   original"), side by side.
2. **In the file:** a metadata text "Enhanced copy of an original photo. Adjustments only: nothing added or
   removed." is written into the JPEG; all other metadata, including GPS, is **removed** (PE6).
3. **In brochures and decks:** a derived copy gets the fixed caption "Photo adjusted for brightness and colour"
   (in the language of the deck). The renderers refuse a derived copy whose database row lacks the label.

**PE5 - How it runs.** Upload uses the existing signed direct-upload path (ADR 0025), purpose `property_photo`.
The person opens the photo and sees a **preview of the allowed adjustments with sliders** (computed on the
server from a small 800-px working copy, using the same code as the final). **Make enhanced copy** queues a
worker job `photo.enhance` that reads the original, applies the recorded operations at full size, stores the
derived copy and its record, and audits it. Another set of values makes another derived copy (at most 5 per
original; older ones can be deleted). One-click **Auto enhance** applies exposure, white balance and resize
only.

**PE6 - Privacy of the file itself.** The photo is decoded and **re-drawn**; all metadata (camera serial,
**GPS position**, owner name) is dropped. This protects the seller's address when a photo is forwarded. A "keep
location" option does not exist in v1. Faces and number plates are not detected or blurred in v1 (section 4,
question 5).

**PE7 - Image-bomb and size safety.** Same discipline as the logo, with higher limits for real photos:
- upload limit 20 MB (the documents limit) and **at most 50 megapixels and 12,000 px per side**, read from the
  header *before* decoding (Pillow `MAX_IMAGE_PIXELS` set explicitly; a decompression-bomb error is a refusal);
- only JPEG, PNG and WebP (iPhone HEIC needs a new native library: question 6); no SVG, GIF, TIFF or RAW;
- animated or multi-frame images refused; the EXIF orientation is applied, then dropped;
- the worker decodes under a **memory cap** (a job that would need more than about 300 MB refuses itself) and a
  **time cap** (60 s); a failed job ends `failed` with a code (`too_large`, `unreadable`, `not_an_image`) and
  never leaves half a file;
- the derived copy is at most 4,000 px on the longest side, JPEG, at most 5 MB.

**PE8 - Who may use it, and the registry.** A new registry entry `photo_enhancer` (no model, **off by
default**; a tenant administrator switches it on) plus a platform switch `CRM_PHOTO_ENHANCER_DISABLED`. A new
permission `photo:enhance` (sales agents, managers, administrators). The record-level rule is the document's:
whoever may read the account or deal photo sees its derived copies; whoever may change it may enhance it.
Support staff and portal customers cannot enhance; a customer sees a derived copy only if the document is
customer-visible, as with any document. Limits: 30 enhancements per person per hour and 500 per organisation
per day (settings), counted before the job is queued.

**PE9 - Cost.** No model, no paid service, no new dependency in v1 (Pillow's `ImageOps`, `ImageEnhance`,
`ImageFilter` and rotation cover the allowed list). Cost is worker CPU (about 1-3 s per 12 MP photo, to be
measured in PE1) and storage: a derived copy of about 0.5-2 MB, at most 5 per original. As a rough guide, 40
photos per property and 1,000 properties is on the order of tens of GB over time, in the organisation's own
bucket (ADR 0021); a retention rule is question 4.

**PE10 - Audit and metrics.** Audit `photo.enhanced` with ids, operation names and sizes (never the picture or
a file name); metric `crm_photo_enhancements_total{outcome}` and a duration histogram, with no tenant label.

## 4. What this does not do

- No generative edits, object removal, sky swap or virtual staging (PE2).
- No face or number-plate blurring (a privacy extra; recommended to defer, question 5).
- No video, 360-degree tours or floor plans.
- No model that scores whether a photo is "good enough".
- No change to the original and no overwriting of an existing document version.
- No gallery or syndication to property portals.
- No server-side HEIC (question 6).

## 5. Steps (Phase PE), each ends with a stop for review

| Step | What | Done when |
|---|---|---|
| PE0 | This ADR accepted | The owner's answers |
| PE1 | Pure image rules: the allowed operations with hard caps, header checks, presets, re-draw without metadata, the label text; no database | Tests on generated images (dark picture gets brighter, tilted one straightened within the cap, metadata-heavy JPEG leaves clean, pixel bomb and animated image refused, an operation above its cap refused, same input gives same bytes); deliberate breaks caught |
| PE2 | Migration (`photo_enhancements`: original, derived document, operations, tool version; forced RLS), the `photo.enhance` job, registry entry, limits, audit | Database tests: happy path, tenant isolation, role denial, record-level denial, ID tampering, limits, switch off, memory and time cap, a failed job stores nothing, deleting the original removes the copies |
| PE3 | API: preview, create, list, delete a copy; signed links for the derived copy | API tests; OpenAPI refreshed |
| PE4 | Screens: Enhance on a photo, sliders with preview, "Show original" side by side, "Enhanced" badge and operation list | Vitest; Playwright journey (upload, enhance, original kept, label shown, a colleague without rights refused) |
| PE5 | Decks and brochures use a derived copy with the fixed caption and refuse an unlabelled one | Deck and brochure tests |
| PE6 | `docs/photo-enhancer.md`; gate tests that the allowed list and caps cannot be exceeded | Docs and tests |

## 6. Questions for the owner (recommended answer first)

1. **Generative changes (sky swap, object removal, staging)?** Recommended: **No, not in v1 and not offered at
   all.** Misleading buyers about a property is a legal and reputational risk for your customers. Later, only
   through a new ADR with an AI label and legal review.
2. **Keep the original and label every enhanced copy?** Recommended: **Yes** - original always kept, a visible
   "Enhanced" badge with what was done, a note in the file, and a fixed caption in decks and brochures.
3. **Watermark?** Recommended: **Yes, optional**: the organisation's logo or name in a corner chosen per photo;
   never covering part of the property.
4. **How long to keep enhanced copies?** Recommended: **While the deal or account is open; offer deleting copies
   (not originals) 12 months after a deal closes.**
5. **Blur faces and number plates?** Recommended: **Defer.** It needs a detection model; v1 shows the warning
   "Check for people and number plates before sharing".
6. **iPhone HEIC photos?** Recommended: **Not on the server in v1**; the screen tells the user to share as JPEG.
7. **Who may use it?** Recommended: **Sales agents, managers, administrators; off by default until an
   administrator switches it on.** Support staff and customers cannot enhance.
8. **Size limits?** Recommended: **20 MB, 50 megapixels, 12,000 px per side, JPEG/PNG/WebP only; results at most
   4,000 px and 5 MB.**

## 7. Alternatives considered

| Option | Why not (now) |
|---|---|
| Generative AI photo editing (sky, objects, staging) | Can mislead buyers, may breach RERA and advertising rules, adds model cost. A separate ADR if ever wanted. |
| An outside photo-editing service | Sends sellers' photos and locations to a third party, adds cost and a dependency; the allowed edits need none of it. |
| Editing in the browser and uploading the result | The browser would then be trusted with the final file; the original and label rules could not be enforced. |
| Overwrite the original | Loses the proof of what was photographed. |
| OpenCV / numpy for better auto-exposure | A large dependency for small gain; Pillow is enough for v1. |
| Label only on screen | A forwarded file would lose it; the file note and the deck caption cost almost nothing. |

## 8. Consequences

- Agents get tidy, smaller, consistently branded photos without a design tool, and the CRM never becomes the
  place where a property is made to look like something it is not.
- Storage grows with derived copies; question 4 controls it.
- A new worker job reads user-uploaded images, so the limits of PE7 are security controls and are tested like
  the logo's.
- Dropping GPS and metadata is a privacy gain for sellers.
- "No generative edits" is a product position the owner may revisit; the cost of revisiting is explicit (a new
  ADR, legal review, an AI label).
