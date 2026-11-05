# Brochures and cited RERA answers (CRM-115 / BP-08)

**Status:** design accepted 2026-11-05 with the five recommended answers (section 5). **Built: BR1-BR4 done 2026-11-05.**
**Kind:** a short design note (the master plan marks BP-08 "design", not an ADR). It builds on the
knowledge module (RAG R1-R5, docs/rag-knowledge-base.md) and the BP-10 evaluation harness. It
changes no ADR. The public website chat stays as ADR 0013 says: it can only save a lead.

## 1. The ticket, as I read it

The ticket title: *"brochure seed script + cited RERA answers with refusal gate"*. Three parts:

1. **Brochure seed script** - fictional property brochures (project, location, configurations,
   price ranges, possession date, RERA number) loaded into the knowledge base through the real
   upload and ingestion path, so the demo and the tests have property content to ask about.
2. **Cited RERA answers** - when a question or an answer is about a RERA number, the answer must
   cite the brochure (or other document) that contains **that exact number**.
3. **Refusal gate** - when the knowledge base cannot support the answer, the assistant says so
   instead of guessing. The gate exists today (section 2); this ticket makes it strict for RERA
   numbers and prices, where a wrong answer costs a buyer real money.

## 2. What already exists (no change needed)

The grounded-answer pipeline (`backend/app/modules/knowledge/answers.py`) already:

- **refuses without calling the model** when no chunk passes the similarity threshold
  ("I couldn't find enough information...");
- **refuses an answer without a valid citation**: every answer needs at least one `[n]` and every
  `[n]` must point at a source that was really given ("I couldn't produce an answer that is fully
  supported...");
- treats document text as data (a poisoned document is in the demo seed and the evaluation cases);
- respects who may see what: internal documents for staff only, `customer_visible` ones for portal
  customers of the right account, never another organisation's.

**What is missing:** a citation proves the answer used *a* source, not that *the number in the
answer* is in that source. A model can cite brochure [1] and still write a RERA number or a price
that is not in it. That is the hole this ticket closes.

## 3. The design

### 3a. The seed script (`backend/scripts/seed_brochures_demo.py`)

- About five fictional brochures for `alpha-demo` and one for `beta-demo` (to prove isolation),
  written as Markdown like the existing `seed_knowledge_demo.py`, stored through
  `knowledge.service` (file store, chunking, embeddings) - not written into tables directly.
- **Fictional RERA numbers that cannot be real:** every number starts with `DEMO-`
  (for example `DEMO-P02400000001`), so a demo answer can never be mistaken for a real registry
  entry. They still fit the web check's RERA pattern, so the demo web check (BP-15) can look them up.
- The set covers the cases the gate must handle: two customer-visible brochures, one internal-only
  (a price sheet for staff), one brochure replaced by a newer version with a changed price (the old
  price must never be quoted), and one project without a RERA number.
- Idempotent (a brochure whose content already exists is skipped), like the existing seed script.
  Command for the owner (Windows CMD, in `backend` with the venv active):
  `python -m scripts.seed_brochures_demo`.

### 3b. The stricter gate (in `knowledge`, pure rules in `rules.py`)

Three checks, added after the existing citation check:

| Check | When | What happens |
|---|---|---|
| **Asked number not on file** | The question contains a RERA-shaped number and no retrieved chunk contains it | Refused **before** any model call: "I couldn't find RERA number X in the documents I can see." |
| **Every RERA number is quoted from a cited source** | The answer contains a RERA-shaped number | Each one must appear, character for character (ignoring case and dashes; a number typed with spaces inside reads as separate words and is not recognised as one number), in a source the answer **cites**. Otherwise the whole answer is refused. |
| **Every price is quoted from a cited source** | The answer contains a rupee amount (₹, Rs, lakh, crore) | Each amount, normalised to whole rupees ("1.2 Cr", "120 lakh" and "₹1,20,00,000" are the same; a small backend reader like the one the lead form already has in `frontend/src/lib/format.ts`), must appear in a cited source. Otherwise refused. |

- A refusal never shows the model's text (it might contain the invented number).
- Every answer that mentions a RERA number gets one fixed line: *"This is what the brochure says;
  it is not a live check of the RERA registry."* For a live check, staff use the web check
  (BP-15) on the lead or account page. The assistant never claims a current registry status.
- Each refusal is counted in the existing `crm_rag_answers_total` metric with new outcome values
  (`rera_not_found`, `rera_not_cited`, `price_not_cited`); no personal data, no tenant label.
- Applies to the **staff** answers (`/knowledge/answer`) and the **portal** answers
  (`/portal/knowledge/answer`). Nothing new for the public chat.

### 3c. Retrieval of exact numbers

Hybrid search already includes full-text search, which should find a chunk by its RERA number. A
test proves it with the seeded brochures. If PostgreSQL's text search splits a number like
`DEMO-P02400000001` so it is not found, BR2 adds a small exact-number lookup (a normalised
`LIKE` through the repository, still filtered by tenant, visibility and account) - only then.

## 4. Steps (each stops for review, tests first)

| Step | Content |
|---|---|
| BR0 | This note (documents only) |
| BR1 (done 2026-11-05) | The seed script + tests (idempotent, both organisations, visibility as written, the replaced version archived, numbers all `DEMO-`) |
| BR2 (done 2026-11-05) | The three gate checks, the fixed "not a live check" line, refusal codes and metrics; tests first (pure rules + the real pipeline against the test database, incl. tenant isolation, a customer asking about an internal price, ID tampering is not applicable: no IDs in a question) |
| BR3 (done 2026-11-05) | BP-10 cases in `evals/rag/ci_cases.json`: a number on file is cited; an unknown number is refused with no model call; an invented number, a wrong price and an old price are refused; a customer never sees the internal price; another organisation's brochure never appears; deliberate breaks of each check must fail a case |
| BR4 (done 2026-11-05) | Screens: the answer's sources already link to the document - add the "not a live check" line and plain words for the new refusals; docs (`docs/rag-knowledge-base.md`, this note); a Playwright check on the existing knowledge journey |

No database migration is planned (no new tables or columns).

### What BR1 found

- `python -m scripts.seed_brochures_demo` on the development data added 6 brochures to
  `alpha-demo` (Skyline Towers as version 2, version 1 archived) and 1 to `beta-demo`; run again,
  it added nothing.
- **Exact numbers are not found reliably by meaning alone.** With the real embedding model and the
  normal threshold, "What is the RERA number of Lakeview Residences?" found the Lakeview brochure,
  but "DEMO-P02400000003 price" ranked the *internal price sheet* first, not the Skyline brochure
  that carries that number. (In the tests, with the stand-in embedder, full-text search found the
  number.) So BR2 adds the exact-number lookup of section 3c rather than leaving it optional.

### What BR2 built and found (2026-11-05)

- `app/modules/knowledge/numbers.py` (pure): what a RERA number looks like (a letter, at least six
  digits, registry separators; never an id, a date, a phone number or a price), whole-number
  matching (`...0001` is not `...00012`), rupee amounts in whole rupees, and `unsupported()`.
- `retrieval.chunks_with_number` and `retrieval.document_chunks`: the literal lookups, under the
  same permission conditions as the search (tenant, indexed, not archived, visibility, the
  customer's accounts). The number is a bound parameter; LIKE's wildcards are escaped.
- **A brochure's number and its prices are in different sections.** The first version gave the
  model only the section with the number, so it never saw the prices. Now, when a question names
  a number, the model also gets the other sections of that brochure (at most 3 sources in all).
- The answer pipeline refuses (`reason`) with `rera_not_found` before any model call, or with
  `rera_not_cited` / `price_not_cited` after it (the model's text is never shown); an answer that
  names a RERA number ends with the fixed "not a live check" line. The person's own amounts in the
  question may be repeated back to them.
- `crm_rag_answers_total` counts the three new outcomes.
- **Bug fixed on the way:** the staff answer endpoint saved every question twice in the question
  log (`rag_queries`); a failing test came first.
- On the development data, with the real embedding model, the lookup finds the Skyline brochure
  for `DEMO-P02400000003` (with its price section), the Lakeview brochure for
  `demo-p0240-0000001`, and nothing for an unknown number.

## 5. Questions for the owner (recommended answer first)

1. **Is the reading in section 1 right?** *Recommended:* yes. If the ticket text says more (for
   example matching leads to properties, `GET /leads/{id}/property-matches` in the old roadmap),
   paste it; that would be a separate step after BR4.
2. **How does the gate know a question is "about RERA"?** *Recommended:* by a RERA-shaped number in
   the question or the answer - no new document type, no migration. *Alternative:* a "brochure"
   document type (a migration and an upload-form change), which would also let us filter by type.
3. **Check prices too, or RERA numbers only?** *Recommended:* prices too - a wrong price is the most
   likely costly mistake.
4. **Where does it apply?** *Recommended:* staff and portal answers; the public chat stays without
   answers (ADR 0013); property answers there would need their own ADR.
5. **Fictional numbers with a `DEMO-` prefix?** *Recommended:* yes, so nothing in the demo can look
   like a real registration.

### What BR4 built (2026-11-05)

- The answer API (`/knowledge/answer`, `/portal/knowledge/answer`) returns `refusal_reason`: a
  code, `null` when answered (`not_found`, `ungrounded`, `rera_not_found`, `rera_not_cited`,
  `price_not_cited`).
- The answer box (staff "Knowledge" page and portal "Help & policies") words each reason: an
  unknown number says "check the number" and that a live registry check is a separate step (Web
  check on the lead or account page); a refused number or price says the answer was not shown and to
  open the brochure itself. Before, every refusal said "nothing was close enough".
- The fixed "not a live check of the RERA registry" line is shown as its own note under the
  answer. A backend test checks that the web app's copy of the sentence matches the backend's.
- Browser journey `frontend/e2e/knowledge-rera.spec.ts`: staff and a portal customer ask about an
  unknown number and see the plain refusal, with no sources and no model call.

## 6. How to try it on this PC

Windows CMD, in `backend` with the virtual environment active:

```bat
python -m scripts.seed_brochures_demo
```

Then sign in to the web app as a sales agent, open **Knowledge** and ask, for example, "What does
DEMO-P02400000003 cost?" (answered from the Skyline Towers brochure, with the fixed line) or "Is
DEMO-P02499999999 registered?" (refused before any model call). A real answer needs the AI
provider configured; the refusal does not.
