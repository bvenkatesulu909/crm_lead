# ADR 0029 — The rep's brief before a site visit

- **Status:** Proposed (2026-11-12) - waiting for the owner's answers in section 6
- **Date:** 2026-11-12
- **Deciders:** Project owner
- **Depends on:** ADR 0028 (buyer memory - the brief reads it), ADR 0027 (language on the lead), ADR
  0024 (the deal desk: code builds cited facts, a person decides), ADR 0017/0018 (cleaning of text)

## 1. The problem

A salesperson about to show a home to a buyer has a few minutes in the car. Today they open the lead,
scroll the timeline, remember (or not) what the buyer said, and walk in without knowing what is still
unasked. With buyer memory (ADR 0028) the CRM now *knows* what is fact, assumption and gap - but it is
spread over a card, a timeline and a task list.

The **brief** is one short page, built for the minutes before the visit: who the buyer is, what we know
(and how sure we are), what to ask, where we left off, and what to be careful about.

## 2. What exists

- Buyer memory (`/leads/{id}/memory`): current facts and assumptions with their sources, and the gaps.
- The lead: name, status, owner, source, phone, e-mail, language to call in, the lead form's wishes.
- The timeline (`lead_activities`) and the activities module (tasks and follow-ups on a lead).
- The deal desk and account research (ADR 0024): code gathers cited facts through each module's
  `api.py` as the person asking; only then, if at all, a model writes sentences that cite them.

## 3. Decisions (proposed)

**SV1 - A page, built on demand, from what the CRM already holds - and nothing stored.** `GET
/api/v1/leads/{id}/brief` returns the brief; a **Site visit brief** button on the lead page opens
`/leads/{id}/brief`. Nothing is written to the database, nothing is sent anywhere, no new table. The
brief says when it was put together ("as of 14:05"), because the lead may change afterwards.

**SV2 - Built by code, no model in v1.** Every line is a fact the CRM holds, labelled **Fact**,
**Assumption**, **Gap** or **Note**, with its source. There is nothing to hallucinate and nothing a
visitor's words can steer. An AI-written "talking points" section could come later in the deal desk's
style (cited sentences, one governed model call, an agent-registry switch that is off by default) - a
separate decision.

**SV3 - Six short sections.**

1. **The visit** - an optional place ("Skyline Towers, tower B"), typed by the rep for this one view (at
   most 100 characters, cleaned, never stored), and the time.
2. **The buyer** - name, the language to call in (ADR 0027), source, status, owner, and how to reach them
   (phone and e-mail as on the lead).
3. **What we know** - the current facts (value, where it came from, what the buyer said) and then the
   assumptions, each marked "confirm on the visit" with the reason we think so.
4. **Ask on the visit** - one fixed question for every gap, in the order of the twelve keys ("When do you
   want to move in?"), and "Confirm: ..." for every assumption.
5. **Where we left off** - the last five timeline entries (kind, date, subject and the first 160
   characters of the note, cleaned, as plain text) and the open follow-ups, overdue ones first.
6. **Be careful** - plain warnings computed from the data: the lead is already converted or marked
   unqualified; no phone and no e-mail; the buyer speaks Hindi or Telugu (say so); more assumptions than
   facts; the lead form has a budget, property type or area that buyer memory does not hold yet.

**SV4 - Reads other modules only through their `api.py`, as the rep.** The lead (and its timeline)
through the leads module, tasks through activities, memory through buyer memory. A lead the rep may not
read is a **404**, like everywhere else; a sales agent therefore sees the brief of their own leads only.

**SV5 - No new permission.** The people who may read buyer memory (`buyer_memory:read`) may read the
brief; the lead's own read rules decide which leads.

**SV6 - Made for a phone and for paper.** One column, big type, a **Print** button and a print style
sheet; no PDF, no e-mail, no sharing link in v1 (a brief holds personal details; sending it somewhere is
a separate decision).

**SV7 - English words, the buyer's language shown.** The labels and questions are English in v1. The
page says which language to call in; a Hindi or Telugu brief is a later step.

## 4. What this does not do

No AI text, no new data stored, no project or brochure lookups (a later step could add "the project's
RERA number and brochure facts, cited" through the knowledge base), no scheduling of the visit, no
sharing, no change to the lead, the memory or the timeline.

## 5. Steps (Phase SV), each stops for review

| Step | Content |
|---|---|
| SV0 | This ADR (documents only) |
| SV1 | Backend: pure rules (sections, the twelve questions, the cautions, cleaning of the place and the note excerpts), service reading through the other modules' `api.py`, `GET /api/v1/leads/{id}/brief?place=`, a small read function in the leads and activities `api.py`, tests (happy path, record-level denial, other organisation, role denial, made-up id, the place cleaned, nothing stored) |
| SV2 | The page `/leads/{id}/brief` and the button on the lead page, print style, component tests, a Playwright journey |
| SV3 | `docs/site-visit-brief.md`, status notes |

## 6. Questions for the owner (recommended answer first)

1. **A model in v1?** *Recommended:* no - built by code, every line cited. Alternative: AI-written talking
   points from the start (more to evaluate, a model reads buyer text).
2. **Where it lives.** *Recommended:* a page opened from a button on the lead page. Alternative: also on
   the deal page, and a link from a scheduled meeting.
3. **The place.** *Recommended:* an optional typed place for this one view, never stored. Alternative: a
   real "visit" record (a table, a date, an outcome) - a bigger change.
4. **The six sections.** *Recommended:* as in SV3. Alternative: fewer (drop "Be careful") or more
   (project facts from the brochures).
5. **Permission.** *Recommended:* reuse `buyer_memory:read` and the lead's read rules. Alternative: a new
   `brief:read` permission.
6. **Audit.** *Recommended:* no entry for reading (like reading the lead). Alternative: audit every view.
7. **Output.** *Recommended:* the page and a print button only. Alternative: a PDF or an e-mail to the rep.

## 7. Consequences

- A rep gets the whole picture in one glance and a list of what to ask, and can tell what the buyer said
  from what the CRM only thinks.
- Cheap and safe: no model, no stored data, no new table; the brief is only as good as the memory and the
  timeline behind it.
- Once buyer memory is filled in routinely, the same brief can feed a later AI helper without changing it.
