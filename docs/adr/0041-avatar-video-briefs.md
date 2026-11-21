# ADR 0041 — Avatar video briefs: the CRM writes the brief, a person or a tool makes the video

- **Status:** Proposed (2026-11-21, waiting for the owner's answers in section 6)
- **Date:** 2026-11-21
- **Deciders:** Project owner
- **Depends on:** ADR 0028 (buyer memory), ADR 0029 (site visit brief), ADR 0032 (branded proposal decks, PD7 deck
  writer), ADR 0014 (approval queue), ADR 0016 (agent registry, budgets, kill switch), ADR 0017 and 0018 (Sentinel,
  cleaning of untrusted text), ADR 0025 (signed links for files), ADR 0009 (row-level security), ADR 0034 and 0035
  (the pattern of a governed, approval-only agent)
- **Owner's feature list:** item 18, "Avatar video briefs".

## 1. The problem

A personalised video ("Hello Mr Rao, here are the two Kondapur flats you liked, and this is why the 3 BHK fits
your family") is more persuasive than a brochure, but it is slow to make and easy to get wrong: a rep forgets
what the buyer said, quotes the wrong price, speaks in the wrong language, or promises something the project
does not have. Video tools with talking **avatars** (a synthetic presenter) make the filming cheap, but they need
a good **script and a list of facts** - and they happily say anything they are given.

So the valuable, safe part for a CRM is the **brief**: a short document that says *what to say, to whom, in which
language and tone, for how long, using which verified facts, and what must not be said*. A human (the rep, on
camera) or an external avatar tool then turns the brief into a video.

I read the item this way: **"avatar video brief" = the written brief and script for a personalised buyer video.**
Making the video itself is a different, riskier thing (section 4) and is treated as a later option.

## 2. What exists

- **Buyer memory** (ADR 0028): twelve fixed keys; each item is a *fact* (source and quote) or an *assumption*
  (reason) or a gap; append-only. This is where "what the buyer told us" lives.
- **Site visit brief** (ADR 0029): built by code, no model, reads other modules' `api.py` as the rep; six
  sections, every line marked Fact / Assumption / Confirm / Ask / Note; print only; nothing stored.
- **Deck writer** (ADR 0032 PD7): a governed model drafts one short text from cleaned quote facts through ONE
  tool; a person approves it through the approval queue; only then does it appear in the deck.
- **Branding** (ADR 0032 PD1): colour, texts and a cleaned logo per organisation.
- **Agent registry, approval queue, Sentinel, screening**: switch, budget, kill switch; proposals approved by a
  different person; cleaning of untrusted text.
- **Documents** with signed links (ADR 0025); the **consent** fields on contacts and the website chat; Hindi and
  Telugu support in the chat (ADR 0027) and in decks (ADR 0032 PD5).
- Property and price facts: the lead's property wishes (type, budget range, location), quotes with price books,
  brochures in the knowledge base (BP-08, cited RERA answers). **There is no project catalogue table yet** - project
  facts come from quotes and brochures only.

## 3. Decisions (proposed)

**VB1 - v1 produces a written brief only. No video, no avatar, no audio, no image of a person is created by the
CRM.** The output is a printable/copyable page (like the site visit brief) plus an optional stored version. A rep
reads it and films, or pastes it into a tool the organisation already uses. This keeps likeness, voice cloning and
advertising-law risk **outside** the CRM in v1 (section 4).

**VB2 - The brief has fixed sections, and every factual line cites its source.**

1. *Purpose and audience* - the lead's first name only, the one goal of the video (introduce / follow up after a
   visit / explain a quote / revive a quiet lead).
2. *Language, tone, length* - one of English, Hindi, Telugu (as ADR 0027); tone from a fixed list (warm,
   professional, brisk); target length 30 / 60 / 90 seconds (about 75 / 150 / 225 words, so the script size is
   checkable).
3. *What we know about the buyer* - lines from buyer memory, each marked **Fact** (with its source and quote) or
   **Assumption**. Only facts are written as statements in the script; an assumption may appear only as a
   question ("You mentioned schools matter - is that still the case?").
4. *Property and price facts* - only from a quote the asker may read, a price book, or a cited brochure
   section; each line carries its source (quote number, brochure title and section). Prices are shown as stored,
   in rupees with lakh grouping; the script never invents or rounds them.
5. *The script* - a numbered list of short lines (one idea each, with a spoken-time estimate), drafted by the
   model (VB4) or written by hand.
6. *Must say / must not say* - a fixed checklist added by code: RERA registration number when the brochure has
   one, "prices subject to change", "images are indicative"; and never "guaranteed returns", "last units", an
   invented discount, a comparison against a named competitor, or a statement about the buyer's family, health,
   religion or caste.
7. *Consent and privacy notes* - what the buyer consented to (contact consent from ADR 0028 / contacts), whether
   the video may be sent on WhatsApp or e-mail, and a reminder not to put the buyer's phone number, address or
   financial details **in** the video.

**VB3 - A first version is built by code, with no model.** Sections 1-4, 6 and 7 are assembled by code as the
person asking (reading other modules' `api.py`, the lead's read rules decide, else 404). The script (section 5)
starts from a fixed skeleton: greeting with the first name, one line per cited fact (at most five), the call to
action chosen by the rep. This already helps a rep and costs nothing.

**VB4 - An optional drafted script from a governed model (`video_brief`, off by default).** Exactly like ADR
0032 PD7 and ADR 0035: a registry entry (switch, monthly token budget, tool filter, platform kill switch), ONE
tool `submit_script`, a strict answer check, cleaned inputs and outputs, limits, audit with ids only. The model
is given only the cleaned facts of VB2 as data (no phone, e-mail, address, no other lead, no audio) and must
reference each fact by its number; **code then checks** that every number, amount, date and project name in the
script is one of the supplied facts (the `numbers.py` idea of the cited-answers work), that the word count fits
the chosen length, that there is no link, and that no banned phrase of VB2-6 appears. A script that fails any of
this is refused and nothing is stored (tokens still counted).

**VB5 - A drafted script is a proposal; a different person approves it.** Through the approval queue and the
Sentinel (new kind `lead.video_script`, author `video_brief`; plan and outcome like the other kinds; checked
again at approval so a lead that changed meanwhile fails the approval). Until approved, the draft is shown only to
the asker as "AI draft - not approved"; the approved script is stored insert-only (`video_briefs`, forced RLS,
versions, a trigger that refuses UPDATE) with the facts it cited. Hand-written scripts by the rep are not
proposals (the rep is the author); they are still cleaned and checked for banned phrases. *(A manager's
approval of every script is a lot of friction; question 4.)*

**VB6 - Where it lives.** A **Video brief** card on the lead page (and later the deal page) next to the buyer
memory and site visit brief cards: *Make a brief*, *Draft a script* (when VB4 is on), a printable page under
`/print/leads/{id}/video-brief` like ADR 0029, and a copy button. The organisation's branding (name, tagline) is
used in the sign-off line; the logo is not part of the brief. The approved brief may be saved as a document on the
lead (purpose `video_brief`, ADR 0025 download links) so it can be handed to an agency.

**VB7 - Permission and limits.** New permissions `video_brief:read` and `video_brief:write` (sales agents,
managers, administrators; support none), plus the lead's read rules. Limits `CRM_VIDEO_BRIEF_PER_LEAD_HOUR` 2,
`_PER_USER_HOUR` 20, `_PER_TENANT_DAY` 200 before any model call.

**VB8 - Not in v1: generating the video.** See section 4. If the owner later wants it, it is a separate ADR step
VB9+ behind its own switch, not a change to VB1-VB7.

## 4. Generating the video through a third-party avatar API (later, optional) - evaluation

| Concern | What it means for this CRM | Recommendation |
|---|---|---|
| **Cost** | Vendors charge per minute of rendered video (cents to a few dollars) plus plan fees; a custom avatar costs more. A bulk "one video per lead" can multiply quickly. | If ever built: per-organisation monthly minute budget in the registry (like `CRM_VOICE_MONTHLY_MINUTES`), a hard stop, an estimate shown before rendering. |
| **Likeness and voice cloning** | A custom avatar or cloned voice of a real person (the rep, a director) is that person's biometric-like personal data. It needs the person's **written, revocable consent**, a limit on what the clone may say, and a way to delete it; employees leaving is a real case. Using the likeness of a **celebrity, a buyer or any third party is refused**. | Stock avatars only at first; custom avatars only with a recorded consent row and an administrator switch. |
| **Deepfake and disclosure** | A synthetic presenter that looks like a real salesperson can mislead a buyer. India's IT rules and advisories on synthetic media, and platform rules (WhatsApp, Meta), point to **labelling** AI-generated content. | Every generated video carries a visible "AI-generated presenter" label and the spoken words are exactly the approved script; no impersonation of a named employee without consent. |
| **Advertising and real-estate law** | A video is marketing. RERA requires the registration number in advertisements; the Consumer Protection Act and ASCI guidelines forbid misleading claims (guaranteed returns, "limited units", unbuilt amenities shown as real). Telemarketing and messaging rules (TRAI/DLT, consent) apply to *sending* it. | The VB2 "must say / must not say" list is the guard; a person approves every script; a lawyer should review the list before any pilot. The CRM does not send the video to a buyer in v1. |
| **Data leaving the system** | The script (a buyer's first name, preferences, prices) goes to the vendor; vendors may keep inputs/outputs or use them for training unless the contract says no. | Only the approved script text goes out; never contact details; vendor chosen by the owner with a signed data-processing agreement; named in the privacy notice; vendor API keys only in the server's environment. |
| **Quality in Hindi and Telugu** | Avatar lip-sync and pronunciation of Indian place names and rupee amounts is uneven. | A pilot with sample scripts and native-speaker review before any claim of support (as for ADR 0030's trial). |
| **Lock-in and outages** | Vendors change prices and shut down. | The brief stays vendor-neutral plain text, so the human path always works. |

Conclusion: **do not build video generation now.** The brief delivers most of the value (the right facts, the
right words, nothing banned) at a fraction of the risk, and a person or a tool the organisation already trusts
makes the video. Revisit after the owner has used briefs for a few weeks.

## 5. Steps (Phase VB), each ends with a stop for review

Each step: failing test first, deliberate breaks of each new protection, browser steps add a Playwright journey.

| Step | What | Done when |
|---|---|---|
| VB0 | This ADR, README line, status entry (documents only) | Owner answers section 6; status Accepted |
| VB1 | Pure rules and the code-built brief (VB2, VB3): sections, the cited-fact lines, banned-phrase and length checks, word counts per language; read functions in other modules' `api.py` where missing; `GET /api/v1/leads/{id}/video-brief?goal=&language=&tone=&length=` (no table, nothing written) | pure tests (Hindi/Telugu text, amounts, banned phrases); API tests: role denial, a colleague's lead = 404, made-up ids, an assumption never written as a statement, a quote the asker may not read is not used |
| VB2 | Screen and print page (VB6): card on the lead page, copy button, plain-text display, consent notes | Vitest; Playwright journey |
| VB3 | Hand-written script check (cleaning, banned phrases, length) and the stored approved-script table (migration, forced RLS, insert-only), document copy | RLS guard, migrations-in-sync, database tests |
| VB4 | Governed drafting: registry entry `video_brief` (off), `submit_script`, code-side fact check (VB4), limits, audit, scripted model for `CRM_AI_PROVIDER=fake` | database tests: switch/budget/platform switch, invented price or fact refused, over length refused, injection in a buyer-memory quote, tenant isolation |
| VB5 | Approval kind `lead.video_script` + Sentinel rules + approval card wording | tests as for ADR 0032 PD7 (never self-approval, stale lead fails) |
| VB6 | BP-10 evaluation cases (scripted), `docs/video-briefs.md`, CLAUDE.md status; optional paid real-model run reported honestly | evaluation gate in CI; deliberate breaks caught |

Nothing is switched on in staging by default and staging is not touched by these steps.

## 6. Risks

- **A banned or false claim in a script** (guaranteed returns, a wrong price). Mitigation: facts only from cited
  records, code-side number check, a banned-phrase list, human approval, RERA line.
- **An assumption presented as fact to the buyer** ("you want a 3 BHK" when the rep only guessed). Mitigation:
  assumptions can appear only as questions.
- **Buyer data in a video** (name, phone). Mitigation: first name only, a reminder, the model never sees contact
  details.
- **Prompt injection through buyer memory quotes or brochure text.** Mitigation: all inputs cleaned and passed as
  data; one tool; every output checked by code and the Sentinel.
- **Over-trust in "AI wrote it".** Mitigation: draft labels, approval by a different person, versions kept.
- **Scope creep into generating or sending video.** Mitigation: VB1 and VB8 say no; a separate ADR is needed.

## 7. Questions for the owner (recommended answer first)

1. **Is "brief only" the right reading of item 18?** *Recommended:* yes - the CRM writes the brief and script,
   a person or an external tool makes the video. Alternative: build video generation now (high cost and legal
   risk, section 4).
2. **Build the code-only brief first and the model-drafted script after?** *Recommended:* yes (VB1-VB3 need no
   model and no paid key; VB4-VB5 follow). Alternative: model-drafted scripts from the start.
3. **Languages and lengths.** *Recommended:* English, Hindi, Telugu; 30 / 60 / 90 seconds; tones warm /
   professional / brisk. Alternative: English only first.
4. **Must a different person approve every AI-drafted script?** *Recommended:* yes, through the approval queue
   (consistent with every other AI feature); hand-written scripts are not proposals. Alternative: the rep may
   use their own draft directly with the checks only (less friction, less control).
5. **Which facts may appear in a script?** *Recommended:* buyer-memory **facts**, the lead's property wishes, and
   price/brochure facts that cite a quote or brochure section; assumptions only as questions. Alternative: also
   assumptions as statements (not recommended).
6. **The "must not say" list.** *Recommended:* start with the list in VB2-6 and have a real-estate lawyer review
   it before the first video is sent to a buyer. Alternative: your own list.
7. **Do you want video generation later?** *Recommended:* not now; decide after weeks of use, and if yes only
   with stock avatars, a per-month minute budget, an "AI-generated presenter" label, and a signed data
   agreement. Alternative: never.
8. **Does the brief become a saved document on the lead?** *Recommended:* yes, approved scripts only, as a
   document with the cited facts, so it can be handed to an agency. Alternative: print/copy only, nothing
   stored.
9. **Limits and switch.** *Recommended:* off until an administrator switches it on; 2 per lead per hour, 20 per
   person per hour, 200 per organisation per day. Alternative: your numbers.

## 8. Alternatives considered

- **Generate the video now through an avatar API.** Rejected for v1: cost, likeness and deepfake consent,
  advertising-law exposure and data leaving the system (section 4), for a benefit the brief mostly delivers.
- **Let the model write the script freely, without code-side fact checks.** Rejected: a model can invent a price
  or a promise; checking every number against the supplied facts is cheap and is the same idea as the cited RERA
  answers (BP-08).
- **Reuse the site visit brief page.** Rejected: that brief is for the rep's own visit, not for words spoken to
  a buyer; the content, the banned list and the approval step differ. The pure helpers (cleaning, reading buyer
  memory) are reused.
- **Store the brief on buyer memory.** Rejected: a script is a generated document, not a fact about the buyer.
