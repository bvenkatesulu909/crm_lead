# Branded proposal decks

Design and decisions: [ADR 0032](adr/0032-branded-proposal-decks.md). Status: **PD1 to PD4 are built** (branding, renderer, job and download links, screens).

## 1. The branding (PD1)

Tenant administrators open **Branding** in the menu and set a brand colour, a logo (PNG or JPEG, at most
1 MB; the server redraws it as a small clean PNG), an about-us text, standard terms, a contact line and a
footer line. Links and markup are taken out of the texts and text that reads like instructions to an AI is
refused. See `backend/app/modules/branding/`.

## 2. The renderer (PD2)

`proposal_decks.api.render_deck(DeckData)` returns the PDF bytes. It is pure: it reads no database and
makes no network call; the caller (PD3) builds `DeckData` from a quote and the branding.

Pages (landscape 16:9, 960 x 540 points):

1. **Cover** - the brand colour as background, the logo on a white chip (or the organisation's name), the
   title, "Prepared for" the customer and contact, the quote number and the date.
2. **About us** - only when the organisation wrote one.
3. **What we propose** - the quote lines, ten to a page ("1 of 3" ...), with a note for discounted lines.
4. **Investment** - total before discount, discount (only if there is one), subtotal, tax, total, and the
   date the proposal is valid until.
5. **Notes and terms** - the quote's customer note and the organisation's standard terms; left out when
   both are empty.
6. **Next steps** - three plain steps and the contact line.

Rules that make it safe and stable:

- Money comes from the quote record: rupees as `₹1,23,45,678.90` (lakh grouping), any other currency as
  `1,234.50 EUR`.
- Everything a person typed is drawn as plain text (`<b>` prints as typed). Text too long for its box is
  shrunk, never cut.
- The bundled font is **Noto Sans** (SIL Open Font License, text next to the files in
  `app/modules/proposal_decks/fonts/`). It has the rupee sign but not Hindi or Telugu: those characters
  print as `?` rather than empty boxes. Hindi and Telugu decks need extra fonts and are a later step.
- The PDF has no links, scripts, attachments or outside pictures; the only image is the organisation's own
  re-encoded logo. The same data always gives the same bytes.

## 3. Making, storing and downloading a deck (PD3)

| Call | Who | What |
|---|---|---|
| `POST /api/v1/quotes/{id}/deck` | people who may change the quote (an agent for their own accounts' quotes, managers, administrators) | queue a deck (202). No body: the server decides everything |
| `GET /api/v1/quotes/{id}/deck` | anyone who can read the quote | `none`, `queued`, `ready`, `failed` or `not_available` (with the reason), and the file name, size and time of the newest deck |
| `GET /api/v1/quotes/{id}/deck/link` | anyone who can read the quote | a 60-second signed link to the newest deck (ADR 0025) |
| `GET /api/v1/portal/quotes/{id}/deck` and `/deck/link` | a portal customer who can see the quote | only a finished deck; never the work in progress |

- **Which quotes:** approved, sent, accepted or declined. A draft or a quote waiting for approval answers
  409 `quote_not_ready_for_deck`; an old revision answers 409 `quote_superseded` (ask on the newest one).
- **Worker job `quote.deck`:** reads the quote through the quotes module and the branding through the
  branding module, draws the deck and stores it as a document (`purpose = quote_deck`, visible to the
  customer). Nothing in the job is a figure or a text: only the quote id and who asked.
- **Same content, one file:** the deck is deterministic, so asking again with nothing changed finds the
  same bytes and stores nothing new (a unique index per quote and content). A changed branding gives a
  new deck; the newest one is the one served. Each deck stays true for ever.
- **Limits:** one deck at a time per quote (409 `deck_pending`), `CRM_PROPOSAL_DECKS_PER_USER_HOUR`
  (default 30) per person per hour (429).
- **Audit:** `deck.requested` (by the person) and `deck.created` (by the Automation identity, with the
  document id, size and the branding version; nothing when the same deck already existed).
- **What is never in a deck:** the quote's internal note, approval details, owner or status.

## 4. Screens (PD4)

- **Staff, quote page:** a **Proposal deck** card above *Details*. For a draft or a quote waiting for approval
  it says a deck is available once the quote is approved (no button). Otherwise: *Create proposal deck*;
  while the worker is drawing, the card says so, the button is disabled and the page looks again every four
  seconds by itself; when ready it shows the file name, size and time with **Download deck** and *Make a new
  deck* (needed only after the branding changed). A failed attempt says so, and a failed refresh keeps the
  earlier deck available. People who may read but not change the quote can download but not create.
- **Customer portal, quote page:** **Download proposal deck** next to *Download PDF*, only when the supplier
  made a deck and the quote was sent to the customer.
- Downloads go through route handlers (`/quotes/<id>/deck`, `/portal/quotes/<id>/deck`) that redirect to a
  60-second signed link, so no token reaches the browser. A refusal sends the user back to the quote page.
- Only the quote id is sent when a deck is asked for.
