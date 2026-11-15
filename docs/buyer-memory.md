# Buyer memory (ADR 0028)

What we know about a home buyer, with every detail labelled **fact**, **assumption** or **gap**, so a
guess is never read later as something the buyer said. Design and the options considered:
[ADR 0028](adr/0028-buyer-memory.md). This page describes what is built (steps BM1: the backend, BM2: the lead page card, BM3: tests and this page).

## 1. The three labels

| Label | Meaning | What it must carry |
|---|---|---|
| **Fact** | the buyer said it or confirmed it | a **source** and a short **quote** of what they said |
| **Assumption** | we think so, nobody confirmed it | a **reason** ("sounded in a hurry on the phone"), and no source |
| **Gap** | not known yet | nothing - it is worked out: a key with no current entry |

The database itself refuses a fact without a source and quote, an assumption without a reason, an unknown
key or status (migration 0059), so no code path can store a guess as a fact.

## 2. The twelve keys

`budget`, `property_type`, `location`, `timeline` (when they want to buy), `purpose` (own use or
investment), `financing`, `household`, `decision_makers`, `must_haves`, `deal_breakers`,
`current_home`, `other_options`. A fixed list: data stays comparable, the screen can list the gaps, and
sensitive categories (religion, caste, health, politics, ID numbers) are kept out by construction.

## 3. Sources of a fact

| Source | Used by | `source_ref` |
|---|---|---|
| `buyer_confirmed` | a person (API): a rep asked and the buyer confirmed; the quote is what they said | none |
| `timeline_entry` | a person (API): a note, call or meeting of **this** lead | the entry's id (checked: must belong to this lead, else `422 memory_source_not_found`) |
| `lead_record` | the "copy from the lead form" button only | none |
| `website_chat` | the website chat only, when it saves a lead | the conversation's id |

The API accepts only the first two; the other two are set by code.

## 4. History: append-only, newest wins

Rows are never edited or deleted by the application (a trigger refuses every UPDATE and the
application role has no UPDATE or DELETE privilege). A change adds a row; the newest row of a key is the
**current** one and older rows are the **history** (newest first). **Confirming** an assumption adds a
new fact with the same key; the assumption stays in the history. Deleting remains possible only for the
table's owner - that is how an erasure of a lead would remove its memory.

## 5. API

All under `/api/v1/leads/{lead_id}/memory`. Permissions `buyer_memory:read` / `buyer_memory:write`
(sales agents, sales managers, tenant administrators); the lead's own read rules decide which leads a
person may open - any other lead is a **404**, the same answer as for one that does not exist.

| Call | What it does |
|---|---|
| `GET` | `{keys, current, history, gaps}` - the twelve keys with labels, the current entries (in key order), older entries, and the gaps |
| `POST` | records one entry: `{key, value, status, source?, source_ref?, quote?, reason?}`; `201` with the entry; `422 memory_invalid` (a rule), `422 memory_value_refused` (a card number or an instruction to an AI in the text), `422 memory_source_not_found`, `409 memory_full` (200 rows per lead) |
| `POST /{item_id}/confirm` | `{source, source_ref?, quote, value?}` - a new fact for the same key (the value may be corrected); `409 memory_not_an_assumption`, `409 memory_not_current` (a newer entry exists), `404` for an entry of another lead |
| `POST /copy-from-lead` | copies the lead form's budget, property type and area in as facts for keys that have **no** answer yet; never overwrites; `{added: n}` |

The body never carries the tenant, the lead, who recorded it, the order or the time: the server decides
them (`extra = forbid`).

## 6. Seeding from the website chat (BM6)

When the website chat saves a lead, the details the visitor gave (property type, budget, area) are
written as **facts** with source `website_chat` and the conversation's id, by the organisation's
Automation identity. Nothing is guessed: a visitor who gave only a name and a number adds nothing, and the
notes the chat wrote are **not** turned into facts.

## 7. Cleaning and audit

Every value, quote and reason goes through the website chat's input screening (a card number in any
digits and instruction-like text are refused) and then loses links, images, markup and hidden characters;
at most 300 characters. Writes are audited (`buyer_memory.added`, `.confirmed`, `.copied`,
`.recorded_from_chat`) with the **key and status only - never the value**.

## 8. Tests

`tests/test_buyer_memory_rules.py` (pure rules), `tests/db/test_buyer_memory_api.py` (the API: happy
paths, a fact without a source, newest wins, confirming, copying, role denial, record-level denial for a
colleague's lead, another organisation's lead, made-up and malformed ids, fields the server decides, the
database refusing updates, deletes and bad rows), `tests/db/test_buyer_memory_chat.py` (seeding).

## 9. The lead page card (BM2)

The **Buyer memory** card sits above Company details on `/leads/{id}` and is shown to people with
`buyer_memory:read` (the API answers 404 for a lead they may not read, and then nothing is shown).

- a one-line summary: "2 facts · 1 assumption · 9 still to ask";
- **Facts**: the detail, where it came from ("Buyer confirmed - \"quote\"", "The website chat", "The lead form") and the date;
- **Assumptions** ("We think so - not confirmed by the buyer"): the detail and "Why we think so", with a
  **Confirm** button that asks "What did the buyer say?" (and optionally a corrected detail) and adds a fact;
- **Still to ask**: the keys with no answer yet;
- for people with `buyer_memory:write`: **Add a detail** (what is it about, "The buyer told us" with what they
  said, or "We think so" with why) and **Copy from the lead form**;
- **Earlier entries (n)** behind a fold (the history), and a line: do not record religion, caste, health,
  politics or ID numbers here.

Everything anyone wrote is shown as plain text (never markup or a link). The Server Actions send only a short
list of fields: a fact is always sent as "the buyer confirmed" with its quote, and nothing else in the form
(a tenant, a lead, a source) is passed on; the API checks the key list, the permissions and every rule again.
In v1 the form offers only "the buyer told us" as a source; citing a timeline entry is possible through the
API. Messages after an action (`?done=memory-added`, `-confirmed`, `-copied`) are shown at the top of the page.

A refused save keeps what the person typed: React empties a form after its action, so every field keeps
its text in state and is remounted after each attempt with that text as its default. (A real browser
journey found this: after "Say why we think so" the topic and detail were blank again.)

## 10. Tests

Backend: see section 8. Web: `src/lib/buyer-memory.test.tsx` (helpers, the Server Actions, the card:
groups, plain-text display, read-only users, the confirm and add forms, refusals that keep the typed text).
Playwright `e2e/buyer-memory.spec.ts`:

1. An agent creates a lead, sees "0 facts · 0 assumptions · 12 still to ask", copies the lead form in as
   facts, adds an assumption (refused without a reason, saved with one), confirms it with the buyer's words
   (refused without), sees the history, and sees a fact without a quote and a card number refused. A colleague
   who may not read the lead gets "not found" and no card; a manager reads it; a support agent sees no card.
2. (needs the website chat switched on, like `public-chat.spec.ts`) a visitor's details appear as facts
   citing "The website chat", and nothing is guessed.

## 11. Not built yet

AI suggestions as assumptions through the approval queue (a later step);
copying the memory to the contact or account on conversion (the lead page stays reachable).
