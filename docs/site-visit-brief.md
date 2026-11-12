# The rep's brief before a site visit (ADR 0029)

One short page for the minutes before showing a home to a buyer: who the buyer is, what we know and how
sure we are, what to ask, where we left off, and what to be careful about. It is built **by code** from what
the CRM already holds - no AI, nothing stored, nothing sent. Design and the options considered:
[ADR 0029](adr/0029-site-visit-brief.md). This page describes what is built (step SV1: the backend).

## 1. What it returns

`GET /api/v1/leads/{lead_id}/brief?place=` (optional `place`). Permission `buyer_memory:read` (sales
agents, managers, tenant administrators) **and** the lead's own read rules: a lead the person may not read,
another organisation's lead or a made-up id is a **404**; roles without lead access get **403**.

| Field | What it holds |
|---|---|
| `as_of` | when the brief was put together (the lead may change afterwards) |
| `place` | the place typed for this one view, cleaned (at most 100 characters), or null |
| `buyer` | name, status, source, owner (display name), phone, e-mail, `language` (`en` / `hi` / `te` or null) and `language_label` |
| `facts` | the current buyer memory facts: value, source, the buyer's quote, when recorded |
| `assumptions` | the current assumptions: value, reason, when recorded |
| `ask` | what to ask: first `confirm` ("Confirm: Timeline - Within six months") for every assumption, then one fixed `gap` question for every detail nobody has answered yet, in the order of the twelve keys |
| `recent` | the last five things people logged on the lead (notes, calls, e-mails, meetings - not system events): kind, time, subject and the first 160 characters as plain text (links, images, markup and hidden characters removed) |
| `tasks` | the open tasks and follow-ups on the lead that the person may read - overdue first, then by date, undated last |
| `cautions` | plain warnings worked out from the data (below) |

## 2. The cautions

In this order, each with a stable `code` and a sentence:

| Code | When |
|---|---|
| `lead_converted` | the lead is already converted to a customer |
| `lead_unqualified` | the lead was marked unqualified |
| `no_contact_details` | no phone number and no e-mail address |
| `speaks_other_language` | the buyer prefers Hindi or Telugu (ADR 0027) - "speak (and call) in ..." |
| `more_guesses_than_facts` | more assumptions than facts |
| `form_not_in_memory` | the lead form has a budget, property type or area that buyer memory holds no entry for - use "Copy from the lead form" |
| `overdue_follow_ups` | open follow-ups on the lead are overdue (with the number) |

## 3. The twelve questions

One plain English question per buyer memory key, for example budget: "What budget are you comfortable
with?", timeline: "When would you like to move in or to buy?", financing: "How are you planning to pay - a
loan, savings, or both?". They are fixed text in `app/modules/site_brief/rules.py`; a test fails if a key
of buyer memory has no question.

## 4. The place

The rep may type where the visit is ("Skyline Towers, tower B") for this one view. It goes through the
same screening as a visitor's message: a card number in any digits and text that reads like an instruction
to an AI are refused (`422 brief_place_invalid`), links, images, markup and hidden characters are removed,
and it may be at most 100 characters. It is **never stored**.

## 5. Nothing is written

Building the brief changes nothing: no row, no audit entry, no notification. A test builds it three times
and checks that buyer memory, the timeline and the audit log have the same number of rows afterwards.

## 6. How it reads other modules

Only through their `api.py`, as the person asking: the leads module (`brief_facts`, `recent_timeline`),
activities (`open_tasks_of_lead`, which applies the activity read policy: an agent reads the activities linked to a lead they own, whoever made them), buyer memory (`current_memory`,
`KEYS`, `budget_text`, `property_type_text`) and identity (`people_by_id` for the owner's name).

## 7. Tests

`tests/test_site_brief_rules.py` (the questions, the place, excerpts, the ordering of tasks, every
caution) and `tests/db/test_site_brief_api.py` (the whole brief through the real API and database, the
place cleaned and refused, nothing written, role denial, a colleague's lead, another organisation, made-up
and malformed ids).

## 8. Not built yet

The page and the button on the lead page, the print style and a Playwright journey (step SV2); a Hindi or
Telugu version of the words; project facts from the brochures (RERA number, price list) and AI-written
talking points (later, separate decisions); a PDF, an e-mail or a sharing link (not in v1).
