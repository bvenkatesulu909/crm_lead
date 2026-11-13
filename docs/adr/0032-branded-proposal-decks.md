# ADR 0032 — Branded proposal decks from a quote

- **Status:** Accepted (2026-11-13, owner approved all six recommended answers in section 7). PD1 built 2026-11-13.
- **Date:** 2026-11-13
- **Deciders:** Project owner
- **Depends on:** ADR 0005 (files and worker jobs), ADR 0025 (signed download links), ADR 0009 (RLS),
  ADR 0017/0018 (cleaning of untrusted text)
- **Related:** the quote PDF (`quotes/pdf.py`), the portal's quote pages, the brochures (ADR/CRM-115)

## 1. The problem

A quote today is a plain A4 price sheet: number, lines, totals. A home-sales or services team sends
buyers a **proposal** - a short presentation with the company's logo and colours, who we are, what we
propose, the price and the next step. Reps build these by hand in slides, copying numbers from the CRM,
and the numbers drift from the quote.

## 2. What exists

- A quote with lines, totals, validity, a customer note and revisions; a quote PDF drawn with ReportLab
  by a worker job and stored (ADR 0005); portal customers can download it; staff download through signed
  links (ADR 0025).
- Per-organisation names only (`tenants.name`). No logo, colour or "about us" text anywhere.
- ReportLab and Pillow are pinned; there is no PowerPoint library and no bundled font. The built-in PDF
  fonts cannot show the rupee sign, which is why the quote PDF prints "INR" instead of a symbol.

## 3. Decisions (proposed)

**PD1 - A PDF deck first.** Landscape 16:9 pages drawn with ReportLab (no new dependency, opens
everywhere, cannot be edited by the buyer). A PowerPoint file (`.pptx`) is a later, separate step and
needs a new library through the security gate (BP-20); only if you want it (question 1).

**PD2 - The deck is built by code from the quote; no model writes anything in v1.** Slides: cover (logo,
title, "Prepared for", date, quote number), about us (the organisation's own text), what we propose
(the lines), investment (subtotal, discount, tax, total, valid until), terms and notes (the quote's
customer note and the organisation's standard terms), next steps and contact. Numbers come from the quote
record exactly as the quote PDF shows them, so the two can never differ.

**PD3 - Branding is stored per organisation.** One row in a new `organisation_branding` table (forced RLS):
logo, primary colour (six hex digits), "about us" text (up to 1,500 characters), standard terms (up to
1,500), a contact line and a footer line. Tenant administrators change it on a Branding page (permission
`branding:manage`); everyone in the organisation's sales roles reads it through the deck, not directly.

**PD4 - The logo is re-encoded, not trusted.** Upload through the existing signed-link path; the server
reads it back, decodes it with Pillow (PNG or JPEG only, at most 1 MB and 2,000 x 2,000 pixels, decompression
bomb limit set), and stores a clean re-encoded PNG. SVG is refused (scripts). All text is cleaned with the
shared screening (no links, no hidden characters, instruction-like text refused), drawn as plain text; the
colour is checked against `^[0-9a-f]{6}$` and the text colour is chosen for contrast.

**PD5 - A deck belongs to one quote revision.** "Create proposal deck" on a quote (people who may read the
quote and send it) queues a worker job `quote.deck`; the stored PDF is tied to the quote revision and the
branding as it was then, so it stays true for ever like the quote PDF. A new revision or a branding
change needs a new deck. Download uses a 60-second signed link; the portal customer may download the deck
of a quote that was sent to them. A deck of a draft quote is refused.

**PD6 - Fonts.** To show the rupee sign (and later Hindi and Telugu) the deck embeds **Noto Sans** (SIL Open
Font License, free to bundle, about 0.5 MB for Latin). v1 is English with the rupee sign; Hindi and Telugu
fonts are a later step (question 3).

**PD7 - Nothing leaves the CRM.** No fetch of pictures or fonts from the internet at draw time, no
templates from outside, no e-mail sending in v1 (the rep downloads it, or uses the existing quote e-mail).
Audit entries `deck.created` and `branding.updated` hold ids only.

## 3a. Corrections made while building PD1

- The logo (at most 1 MB, stored at most 500 KB) is sent as one ordinary multipart request to the API,
  not through the signed-link path (that path exists for large files, ADR 0025), and the clean PNG is kept
  in the branding row itself (`logo_png`), so it follows the organisation's row-level security and needs no
  file store. The deck renderer reads it from there.
- A colour such as `##1f3a5f` is refused (only one leading `#` is accepted); found by a test.
- The page shows which fields had a link, markup or hidden characters taken out once, after saving.

## 4. Phases

| Step | Content |
|---|---|
| PD0 | This ADR, owner's answers |
| PD1 | `branding` module: table, API, logo re-encoding, tests; Branding page for administrators - **built 2026-11-13** |
| PD2 | The deck renderer: pure, from plain data, bundled font, tests that read the PDF text |
| PD3 | Worker job, stored file, download links (staff and portal), audit |
| PD4 | Screens: "Create proposal deck" on the quote page, the portal download; Playwright journey; docs |

## 5. Risks and limits

- A logo with a huge size or a crafted image: handled by re-encoding and the pixel limit.
- A deck cannot be edited by the buyer, nor by the rep after creation: a change means a new deck.
- Property photos and project brochures are not in the deck in v1 (they live in the knowledge base with
  their own visibility rules); a later step can add chosen pictures.
- A very long quote (many lines) is split over several "what we propose" slides, 10 lines each.

## 6. What this does not change

The quote, its approval rules and the quote PDF stay as they are. The deck reads quotes only through the
quotes module's `api.py`.

## 7. Questions for the owner

1. PDF decks first, PowerPoint later only if wanted? (Recommended: yes.)
2. Branding per organisation: logo, colour, about-us text, standard terms, contact and footer lines,
   changed by tenant administrators only? (Recommended: yes.)
3. Bundle the Noto Sans font so the rupee sign prints, English only in v1? (Recommended: yes.)
4. No AI-written slides in v1; a later step may propose a summary slide through the approval queue?
   (Recommended: yes.)
5. A deck is allowed only for quotes that are not drafts, and the portal customer may download the deck of
   a quote sent to them? (Recommended: yes.)
6. Do you have a logo file and brand colour to use for the demonstration organisation? (Only you can
   supply them; a made-up fictional logo is used for tests.)
