# Branded proposal decks

Design and decisions: [ADR 0032](adr/0032-branded-proposal-decks.md). Status: **PD1 (branding) and PD2
(the renderer) are built**; the job that stores a deck, the download links and the screens on the quote
page (PD3, PD4) are not.

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
