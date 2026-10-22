# crm-lead RAG add-on — progress

**Created:** 2026-10-20 (first session). **Status: no RAG code written yet** - materials read,
prerequisites audited, plan recorded. One part at a time, stop for approval.

Materials (now in the project):
- [rag-guide.pdf](rag-guide.pdf) - this add-on, Stages R0-R6 (30 pages, read 2026-10-20)
- [implementation-guide.pdf](implementation-guide.pdf) - the main project's later stages 0-6
- [project-guide.pdf](project-guide.pdf) - the base CRM (34 pages)
- Project rules: [../CLAUDE.md](../CLAUDE.md); current status: [gap-analysis.md](gap-analysis.md), [inventory.md](inventory.md).

## 1. Where we are

- Base CRM: running locally, migrations to **0021**, portal assistant text chat exists (Phase 20a).
- RAG add-on: **R0 complete locally** (steps 1-4). Design:
  [rag-knowledge-base.md](rag-knowledge-base.md); decisions:
  [ADR 0010](adr/0010-knowledge-search-pgvector-embeddings.md) and
  [ADR 0011](adr/0011-chunking-and-hybrid-search.md), both accepted.
- Session 1 did: read all three guides + CLAUDE.md + docs; audited RAG-guide section 1 against the
  code; wrote this file. **No migration, code, dependency or Docker change has been made.**
- **R0 committed** on `rag-r0-setup`: ADR 0010 + pgvector image/extension (d5748c2, 320583b) and
  the embedding layer + ADR 0011 (c28d327).
- **R1 + R1.5/R1.6 committed** (6a69e64, e660eaf): ingestion tables/job/API/tests, screens and demo
  content (8 fictional documents / 11 chunks incl. the poisoned test document).
- **R2 done locally, uncommitted:** migration **0021** adds `embedding vector(384)`, generated
  `tsv`, HNSW cosine + GIN indexes; the worker embeds every chunk during ingestion and records the
  model; demo content re-indexed (**11/11 chunks embedded, 384 dims, 11 keyword columns**).
- **RLS foundation (P1 step 1), uncommitted:** migration **0022** enables FORCE RLS + tenant
  isolation on `kb_documents`/`kb_chunks`; `bind_tenant` sets the tenant from the verified
  Principal with an after-commit re-apply; identity and worker bind it; tests prove fail-closed
  reads and cross-tenant isolation. Remaining domains/worker role next.
- **R3 (retrieval) done locally, uncommitted:** migration **0023** adds document/chunk
  `visibility`; `GET /api/v1/knowledge/search` performs permission-filtered hybrid retrieval
  (pgvector top-40 + full-text top-40, RRF k=60, top-5) with citations, optional reranker hook and a
  configurable not-enough threshold; tests include a top-3 hit-rate evaluation.
- **R5 (evaluation) complete locally, uncommitted:** 100 free retrieval cases (hit@5 1.000,
  MRR 1.000), not-found 100 %, threshold 0.64 enforced, reranker disabled after 0 gain; answer
  run recorded (4/4, faithfulness 1.000). No further paid runs needed.
- **R4 (grounded answers) partially done locally, uncommitted:** answer pipeline (rerank top-10 ->
  best 3 chunks -> grounded prompt -> Claude with numbered sources), citations + exact chunk,
  refusal without a model call; staff API only. R6 not started.
- **P0 CI (paused):** the `next typegen` fix is committed on `rag-r0-setup` but **not pushed**, so
  CI is still red. The workflow now uses the pgvector image for R2 tests.

## 2. Prerequisites from RAG guide section 1 - audited against the code

| Prerequisite (implementation guide) | Status | Evidence in the repo / what is missing |
|---|---|---|
| Stage 0: Git, GitHub, CI | **Partial** | Git history exists and is pushed to GitHub (main at 6261015). **No CI**: no .github/workflows. The GitHub repo is **public**; Stage 0 asks for private. |
| 1A: Row-Level Security | **Partial (staged)** | Migration 0022 enables FORCE RLS + tenant policies on the knowledge tables; session binding, identity binding and worker per-job binding are in place. Remaining domains, worker BYPASSRLS role and test bootstrap are next (ADR 0009 accepted, staged). |
| 1B: events + worker | **Done** | Outbox (migration 0014), worker with retries/dead/stuck recovery, domain events (ADR 0005/0006). |
| 1C: file storage (+ mail) | **Done (variant)** | SeaweedFS S3 store + Mailpit + documents module. Guide names MinIO; ADR 0005 replaced it with SeaweedFS (same S3 API). |
| 1F: tool gateway | **Missing** | No gateway: assistant tools call module api.py functions directly (assistant/tools.py); no level/approval/shadow/limit wrapper. |
| 2A: Claude client | **Done** | assistant/llm.py: ChatModel protocol, Anthropic SDK, model settings, no key -> 503. |
| 2B: portal assistant (only for R4.4) | **Done** | /api/v1/portal/assistant text chat, tools, audit, handover (Phase 20a). |
| 2E: eval harness (for Stage R5) | **Missing** | No backend/evals, no retrieval metrics, no faithfulness/citation evals. Only opt-in live tests in tests/db/test_assistant_api.py. |

Additional prerequisites that RAG later stages need, not in section 1's short list:

| Needed for | Prerequisite | Status |
|---|---|---|
| R4.3 ticket reply drafts | 2C: ticket triage / suggested reply (SUGGEST) | Missing (support module has no AI draft) |
| R6.4 monitoring/alerts | Stage 5 alerts/monitoring (dead jobs, budgets, backups) | Missing |
| R6.1 gap agent (SUGGEST) | 1E agent users/roles + 1G approval inbox + 1H runs/costs/budgets | Missing (defer gap agent if needed) |
| Ingestion retries | 1B job retry/idempotency | Done |

### Implementation-guide work to add to the plan (in order)

| # | Work | Why before RAG | Size |
|---|---|---|---|
| P0 | **Stage 0 CI** (GitHub Actions: backend pytest with PostgreSQL + alembic, ruff, format, mypy; frontend lint/typecheck/test/build) and decide private vs public repo | Every RAG part is a branch with tests; R3/R5 add CI checks | Small-medium |
| P1 | **1A Row-Level Security** (enable + policies + per-transaction tenant binding + identity bootstrap function; guard test) | Knowledge tables are tenant tables; retrieval filters rely on RLS | Large |
| P2 | **1F tool gateway** (one run_tool() with permission, level, limits, audit) | Assistant's search tool must go through it | Medium |
| P3 | **2C ticket triage / suggested reply** | R4.3 ticket reply drafts | Medium |
| P4 | **2E eval harness** | R5 evaluation | Medium |
| P5 | **Stage 5 monitoring + alerts** | R6.4 | Medium |
| P6 | **1E/1G/1H agent identity, approvals, runs/costs** (optional; defer if R6 gap agent is postponed) | R6.1 SUGGEST gap drafts + budget tracking | Large |

Ordered plan: **P0 -> P1 -> P2 -> R0 -> R1 -> R2 -> R3 -> (P3) -> R4 -> (P4) -> R5 -> (P5/P6) -> R6.**
RAG's own section 1 says R0-R3 can start after Stage 1 and 2A; 1B/1C/2A/2B are already done.

## 3. Stage plan (RAG guide part by part)

Legend: [ ] not started · [~] in progress · [x] done. R0 is in progress.

### Stage R0 - Set-up and decisions (branch rag-r0-setup)
- [~] R0.1 PostgreSQL with pgvector: **done locally 2026-10-20** (own Alpine image + pgvector v0.8.7, same volume, extension in crm/crm_test, backups taken); awaiting approval and the CI image switch.
- [~] R0.2 Embedding model + interface: **done locally 2026-10-20** - ADR 0010 chose fastembed
  (ONNX, CPU) with BAAI/bge-small-en-v1.5 (384 dims); `app/core/ai/embeddings.py` has the
  Embedder protocol + lazy implementation; real-model smoke test passed (384 dims, sensible
  similarities). Deliberate deviation from the guide: the model runs **in-process** (backend/worker),
  not as a separate container - to be confirmed by the owner.
- [x] R0.3 Chunking + search settings: **ADR 0011 accepted 2026-10-20** - ~1,600 characters,
  1-paragraph overlap, heading path in the embedding text, blocks kept for citations, 40
  candidates per method, RRF k=60, top 5, reranker off, not-found threshold calibrated in R5,
  `simple` keyword config.
- Done when: pgvector runs, backup shown, existing tests pass, the embedding interface answers a
  real test call (in-process; deviation noted), ADR 0010 and ADR 0011 approved. **All done
  locally 2026-10-20.**

### Stage R1 - Knowledge sources and ingestion (branch rag-r1-ingestion)
- [~] R1.1 Tables: migration **0020** adds `kb_documents` + `kb_chunks` (tenant_id, composite
  same-tenant FKs, RLS-ready). `kb_articles` deferred with the screens (file ingestion first).
- [x] R1.2 Ingestion job: upload stores the file + document row + outbox job `knowledge.ingest` in
  **one transaction**; worker extracts/chunks and replaces chunks atomically; statuses
  processing/indexed/needs_review/failed/no_text. (Direct outbox job instead of a
  `kb.document_uploaded` event - same guarantee, noted deviation.)
- [x] R1.3 Text extraction: PDF (pypdf, page numbers), DOCX (python-docx, heading styles),
  TXT and Markdown; no-text files become `no_text`. HTML is deferred.
- [x] R1.4 Chunking: ADR 0011 - ~1,600 chars, one-paragraph overlap, heading path prepended to the
  embedding text, paragraph blocks kept for citations, chunker version stored.
- [x] R1.5 Screens: `/knowledge` lists documents with status, upload (tenant admins), delete with
  confirmation; navigation + dashboard module entry. The article editor and a separate needs-review
  queue are deferred with `kb_articles` (the status + error explain the finding).
- [x] R1.6 Demo content: `scripts/seed_knowledge_demo.py` seeds 8 fictional documents (returns,
  delivery, payments, product care, internal sales policy for alpha-demo; returns + delivery for
  beta-demo) plus a **TEST ONLY - poisoned document**; 11 chunks, all indexed. Idempotent by
  content hash.
- Done when: chunks appear with status, personal-data findings block indexing, demo+poisoned docs
  exist, tenant/role tests pass. **R1 file-ingestion slice done locally 2026-10-21** (statuses, PII
  review, tenant/role/ingestion tests, screens, demo + poisoned document). `kb_articles` remains
  deferred to a later R1b step.

### Stage R2 - Embeddings and indexes (branch rag-r2-indexes)
- [x] **Migration 0021:** `embedding vector(384)`, `embedding_model`, generated `tsv`
  (`to_tsvector('simple', heading_path || ' ' || text)`, stored). The migration checks that the
  pgvector extension exists and fails with a clear message otherwise.
- [x] HNSW cosine index on `embedding`, GIN on `tsv` (migration + model sync test). The
  `(tenant_id, status, visibility)` index and pgvector iterative scans are deferred to **R3**, when
  visibility/status columns and filtered search exist.
- [x] Worker embeds every chunk during ingestion (`embedding_text` = heading path + body) and stores
  the model name; embedding failure raises so the outbox retries the whole idempotent job (tested).
  Demo content re-indexed: 11/11 chunks embedded.
- [~] Model-change procedure is in ADR 0011 (re-embed with the new model, verify, switch); a general
  re-embed command is not built yet (the demo seed re-indexes its files).
- [ ] First timing of 100 searches is deferred to R3: retrieval does not exist yet, so there is
  nothing honest to measure.
- Done when: every published chunk has vector+keywords (yes for demo + new ingests), indexes exist
  (migration test), retries tested. Remaining: real-corpus re-embed command and search timings (R3).

### Stage R3 - Retrieval (branch rag-r3-retrieval)
- [x] **R3.1 Scope:** `knowledge:read` permission (router), tenant filter in every query **and** RLS,
  `status='indexed'`, current embedding model, and document/chunk **visibility** (staff: internal +
  customer_visible; portal: customer_visible only, when its UI exists). Account-linked chunks are
  not modelled yet - documents are tenant-level, so customer-visible means all portal users.
- [x] **R3.2 Hybrid search:** vector top-40 + full-text top-40, merged with RRF (k=60), top-5;
  `/api/v1/knowledge/search` returns citations (document, chunk, heading path, pages, blocks) and
  the score components.
- [x] **R3.3 Reranker:** local cross-encoder `Xenova/ms-marco-MiniLM-L-6-v2` re-scores the RRF
  top-10, then top-k is returned; enabled (owner request), lazy, cache-backed, soft-fallback to RRF
  if it cannot load. R5 still measures whether it is worth keeping.
- [x] **R3.4 Not-good-enough detection:** configurable `knowledge_min_similarity` (unset until R5
  calibration); the API returns `best_similarity`, `threshold` and `enough`.
- [~] **R3.5 API:** staff search endpoint done. Portal help centre, staff search debugger and
  `rag_queries` logging are not built yet (portal search comes with the portal UI).
- [x] **Tests:** hybrid ordering, exact-code keyword hit, Beta/Alpha isolation, customer 403,
  visibility filtering, threshold, reranker hook, whitespace 422, and a hit-rate evaluation.
- Done when: **staff** hybrid search works with citations and proven permissions. Remaining:
  portal audience, account-scoped chunks, mutation test and calibrated threshold (R4/R5).

### Stage R4 - Answers with citations (branch rag-r4-answers)
- [~] **R4.1 Answer service (staff API + UI):** `POST /api/v1/knowledge/answer` reranks the top-10,
  takes the best 3 chunks as numbered context, calls Claude only when retrieval is confident, and
  returns the answer with sources. Not-found returns an honest refusal **without a model call**;
  unconfigured model -> 503. An answer with no citation, or a citation that does not exist, is
  refused as ungrounded (never shown). Staff UI at `/knowledge/search` ("Search & ask") is built; the
  portal "Ask", ticket drafts and the assistant tool (R4.3/R4.4) are not.
- [~] **R4.2 Citations:** numbered sources are returned (document, chunk, heading, pages, text) and
  the exact chunk id; the **staff UI** renders them under each answer ("Sources used"). Links to a
  document page and hover highlighting are not built (there is no document detail page yet).
- [~] **R4.3 Four places:** portal "Ask" ✅, staff Ask ✅, **ticket reply drafts ✅**
  (`POST /api/v1/tickets/{id}/knowledge-draft`: customer-scoped draft + sources for the ticket's
  account; never internal documents). Only the staff-side "insert draft into reply" UI remains.
- [~] **R4.4 Assistant search tool:** `search_help_articles` is exposed to the portal assistant
  through the existing manual tool loop; it searches public + granted-account chunks only and
  returns document names/passages so the answer can cite them. The full gateway abstraction is not
  built (tools still execute in-process, as before).
- [ ] R4.5 Cost/speed: measure per answer; show expected cost before first real call.
- Done when: all four places answer with numbered sources; not-found offers a person and is logged; fake-client tests pass, including customer-scope drafts.

### Stage R5 - Evaluation and tuning (branch rag-r5-evals)
- [x] **R5.1 Eval cases:** **100 free retrieval cases** (80 answerable, 20 unanswerable) in
  `retrieval_cases.json`, plus 4 paid answer/safety cases in `answer_cases.json`. No further
  paid runs required.
- [x] **R5.2 Retrieval metrics:** free harness on 100 cases; **hit@5 = 1.000, MRR = 1.000**
  (reranker off), reranker gain **MRR −0.021**; real local models, no paid calls.
- [x] **R5.3 Answer metrics:** deterministic metrics + runner; the executed DeepSeek run's final
  result is groundedness 0.917, faithfulness **1.000**, correctness **1.000**, injection safe,
  doc-hit 1.000 (**4/4** after the injection-metric fix; no new paid calls). Runtime rejects
  uncited/wrong-citation answers. See [rag-eval.md](rag-eval.md).
- [x] **R5.4 Targets:** hit@5 1.000 ≥ 0.90; MRR 1.000 ≥ 0.70; **not-found 100 % ≥ 90 %** on 20
  negatives; faithfulness 1.000 ≥ 95 %; safety 100 %. The answer set is 4 cases, so these answer
  numbers are encouraging but small; the 100-case target is met by the free retrieval set.
- [x] **R5.5 Tuning loop:** `docs/rag-tuning.md` records the baseline and decisions; reranker
  **disabled** (no gain); `knowledge_min_similarity = 0.64` **enforced** (100 % answerable
  retained, 100 % negatives rejected on the free set); re-calibrate on model/corpus changes.
- Done when: 100+ cases, retrieval metrics meet targets, answer targets met, tuning recorded. **Met
  on 2026-10-21 with the 100-case free suite + the recorded answer run.**

### Stage R6 - Running it for real customers (branch rag-r6-operations)
- [x] **R6.1 Feedback + gaps:** helpful/not-helpful buttons on staff and portal answers
  (`rag_feedback`, one vote per query/user, upsert), query recording with `query_id` (migration
  0027), and `scripts/rag_gaps_report.py` (last 7 days: by surface, negative rate, unanswered,
  refused, top questions). The article-drafting "gap agent" is intentionally skipped (needs P6).
- [ ] R6.1b Gap agent drafts articles (optional; not built).
- [ ] R6.2 Freshness: edits/new versions re-ingest; nightly consistency check (published without chunks, archived chunks, old model, stuck processing).
- [ ] R6.3 Retention/deletion: archiving deletes chunks in same transaction; rag_queries 90 days; erasure clears stored questions.
- [~] **R6.4 Monitoring/alerts:** implemented Prometheus metrics (HTTP, RAG stages, answers,
  AI calls/tokens/estimated cost, worker heartbeat/outbox/knowledge gauges, pgvector checks),
  token-protected internal scrape route, OpenTelemetry wiring (opt-in), JSON logs with trace IDs +
  redaction, extended readiness (DB + pgvector + HNSW), worker heartbeat (migration 0024), Grafana
  dashboard (9 panels), Prometheus alert rules (10) and Alertmanager config. Automated tests pass.
  **Not yet verified:** live Prometheus/Grafana/Alertmanager, alert delivery with controlled
  failures, OTLP collector, and DeepSeek (provider decision G-01).
- [ ] R6.5 Growing: HNSW tuning, partitioning for large tenants, more embedding replicas, model upgrades with full evals.
- [ ] R6.6 Later ideas (measured first): question rewriting, tenant synonyms, OCR, website/drive sources, product catalogue answers, voice.
- Done when: feedback+gaps work, nightly checks+retention run, monitoring live, docs/rag.md written.

## 4. Conflicts to resolve before R0 (guide vs this repo)

1. **ADR numbers:** the RAG guide asks for ADR 0006 (embedding model) and 0007 (chunking/search),
   but this repo already uses 0006-0009, and 0010 is the proposed RAG design. Use the **next free
   numbers (0011 embedding model, 0012 chunking/search)** and note the mapping here.
2. **Knowledge base built twice:** implementation guide Stage 3 also lists a KB module
   (kb_articles/kb_chunks, migration 0015+). The RAG guide "replaces and expands" that row: the RAG
   guide owns kb_articles/kb_documents/kb_chunks. Decide once, before any migration.
3. **pgvector timing:** implementation guide switches the image in Stage 3; RAG does it in R0.1.
   Do it once, in R0, after the backup.
4. **Upload types/events:** 1C allowlist must widen to PDF/DOCX/TXT/MD/HTML; 1B event set needs
   kb.article_published / kb.document_uploaded.
5. **Docs/names:** the guides say docs/project-guide.pdf, docs/implementation-guide.pdf,
   docs/rag-guide.pdf (now copied here) and docs/rag-tuning.md, docs/rag.md (to be created).
6. **Repo visibility:** Stage 0 asks for a private GitHub repo; the current repo is public.

## 5. Working agreement for this add-on

- One part at a time; show plan, wait for OK, explain first, stop for approval.
- Commands for Windows CMD; project root E:\crm-lead.
- Never claim tests passed unless run and shown; run the full checks at each part end.
- Ask before destructive actions, architecture changes (ADR) and anything that costs money
  (answer evals cost; retrieval evals are free).
- Only fictional demo documents; never real customer data; never paste secrets.
- Never let one tenant see another's data; never show internal documents to customers.

## 6. Cost notes (from the RAG guide)

- Ingestion, embeddings, search, help centre, "not found": no AI cost (local model).
- Answers: Claude Opus 5.5, roughly a few cents each ($4/M input, $20/M output); measure in run records.
- Answer evals: a few dollars per full run of 100 cases - ask before running.

## 7. Session log

- **2026-10-20 (session 1):** copied the three PDFs into docs/ (originals were in Downloads under
  crm-lead-*.pdf names); read rag-guide.pdf fully and the other two via parallel readers; read
  CLAUDE.md and the docs folder; audited section-1 prerequisites against the code; created this
  PROGRESS.md. No code, migration, dependency or Docker change. Prerequisites missing: CI (P0),
  RLS (P1), tool gateway (P2); later: ticket drafts (P3), eval harness (P4), monitoring (P5),
  agent runs/approvals (P6).
- **2026-10-20 (session 2, P0 CI):** wrote `.github/workflows/ci.yml` - backend job (PostgreSQL 16
  service, the real role/database init script, ruff/format/mypy/import-linter, pytest with the owner
  and app test-database URLs) and frontend job (Node 22, npm ci, lint, typecheck, Vitest, production
  build). Ran the local equivalents: backend **999 passed, 4 skipped**, ruff/format/mypy/
  lint-imports clean; frontend lint, typecheck, **205 tests** and the production build all clean.
  The full pytest run found a real bug: the test-only repository model was registered on the app
  Base, so Alembic's migration-sync test saw a phantom table; fixed by giving the test model its own
  private DeclarativeBase. Nothing committed or pushed; CI is not proven until GitHub runs it.
- **2026-10-20 (session 3, R0 step 2):** backed up `crm` (559 KB, 444 TOC entries) and
  `keycloak` (233 KB) with `pg_dump -Fc` and verified the archives. Added
  `infrastructure/postgres/Dockerfile` (postgres:16-alpine + pgvector v0.8.7 compiled in;
  multi-stage; LLVM bitcode off), `init/03-enable-pgvector.sh`, the Compose build/image pin,
  a git-ignore rule for backups, and `docs/rag-runbook.md` (backup, one-off extension command,
  verification, restore). Recreated only the postgres container on the same volume: data intact
  (revision 0019, 71 users, 187 accounts); `CREATE EXTENSION vector` ran in `crm` and
  `crm_test`; the init script was run manually (idempotent) and works; `\dx vector` = 0.8.7;
  vector distance works as superuser **and** app role; full backend pytest **999 passed,
  4 skipped**. Not committed or pushed; approval pending.
- **2026-10-20 (session 4, R0 steps 3-4):** added the local embedding layer:
  `app/core/ai/embeddings.py` (Embedder protocol, lazy fastembed implementation, dimension check,
  503 domain error), settings `CRM_EMBEDDINGS_*` (model, dimensions, cache dir), dependency
  `fastembed==0.9.0`, 5 unit tests with a fake model, and `scripts/check_embeddings.py`. Real
  model smoke test: BAAI/bge-small-en-v1.5, **384 dimensions**, similarities 0.8709 (returns
  policy) vs 0.6185 (delivery) for the return-window question; the model downloaded on first run.
  Installing fastembed required repairing a stale Pillow `_imaging.pyd` in the venv (moved aside,
  Pillow reinstalled); the venv is healthy again. Design deviation to confirm: fastembed runs
  **in-process** (ADR 0010), not as the guide's separate embedding container. Uncommitted.
- **2026-10-20 (session 5, R0.3):** wrote and accepted
  `docs/adr/0011-chunking-and-hybrid-search.md`: ~1,600-character chunks (~400 tokens) with
  one-paragraph overlap, heading path prepended, paragraph blocks kept for citations, deterministic
  chunker version; hybrid retrieval = vector top-40 + PostgreSQL full-text (`simple`) top-40
  merged with RRF (k=60) to top-5; HNSW cosine; iterative scans for filtered searches; reranker
  off until R5; not-found threshold calibrated in R5; embeddings failure returns 503, no silent
  keyword-only fallback. Aligned `docs/rag-knowledge-base.md` (384 dims, 1,600 chars, own
  pgvector image, in-process embedder). R0 is complete locally; uncommitted.
- **2026-10-20 (session 6, R1 ingestion):** added migration 0020 (`kb_documents`, `kb_chunks`;
  tenant-scoped, RLS-ready), the `knowledge` module (models/schemas/rules/extraction/chunking/PII
  scan/policies/repository/service/router/api), `knowledge:read`/`knowledge:manage` permissions,
  the `knowledge.ingest` worker job and app wiring; new dependencies pypdf 6.21.1 and
  python-docx 1.2.0. Tests: 10 unit (extraction/chunking/PII) and 9 database/API (upload+jobs,
  idempotent re-ingest, PII -> needs_review, no_text, invalid/duplicate files, tenant isolation,
  role denial, delete removes chunks+file) pass; migration sync tests pass; OpenAPI regenerated
  (+4 endpoints); **full backend suite 1023 passed, 4 skipped**; ruff/format/mypy/import-linter
  clean; inventory regenerated. Two defects were found and fixed by the tests: an oversized overlap
  chunk and a 16-digit card falsely matching Aadhaar. Screens/demo content and embeddings are next;
  uncommitted.
- **2026-10-21 (session 7, R1.5/R1.6):** added the staff Knowledge screen
  (`/knowledge`: list with statuses, upload for tenant admins, delete with confirmation), the
  navigation + dashboard module entry, frontend types/permissions, and
  `scripts/seed_knowledge_demo.py`. Seeded 8 fictional documents / 11 chunks for alpha-demo and
  beta-demo, including the TEST ONLY poisoned document (prompt-injection test material). Checks:
  frontend **205 tests passed**, lint/typecheck/build clean; seed script ruff/mypy clean. No
  Playwright run (needs the full stack + login). Uncommitted.
- **2026-10-21 (session 8, R2):** migration **0021** adds `embedding vector(384)`,
  `embedding_model` and the generated `tsv` column, with HNSW (cosine) and GIN indexes and an
  extension-existence check. The worker now embeds every chunk during ingestion (heading path +
  body), stores the model name and retries the whole job on embedding failure (tested with a
  failing embedder). Demo content re-indexed: **11/11 chunks embedded (384 dims), 11 tsv columns**.
  Tests: knowledge 10 unit + 10 DB/API + 2 migration-sync passed; **full backend suite 1024 passed,
  4 skipped**; ruff/format/mypy/import-linter clean. CI workflow now uses the pgvector image and
  creates the extension in the test database (not yet proven on GitHub). Uncommitted.
- **2026-10-21 (session 9, RLS step 1):** accepted ADR 0009 as a **staged** rollout and implemented
  the foundation plus the first domain. Migration **0022** creates `crm_current_tenant()` (fail-closed
  when unset) and `ENABLE` + `FORCE` RLS with a tenant-isolation policy on `kb_documents` and
  `kb_chunks`. `bind_tenant()` stores the tenant on the Session and applies `app.tenant_id` (from the
  verified Principal only); an `after_begin` listener re-applies it after every commit/rollback, so
  mid-request commits cannot lose it. Identity resolution binds the tenant; the worker binds each
  job's tenant before its handler; the demo seed binds per tenant. New tests prove: no setting -> 0
  rows, bound tenant -> its rows, another tenant -> 0, and policies/force flags exist. Demo seed
  works under RLS (alpha sees 9 chunks, beta isolated). Targeted tests: **24 passed**; `tests/db`
  rerun: **644 passed, 4 skipped**. A first full-suite run showed 4 workflow failures that did not
  reproduce standalone or in the db-directory rerun; the **final full-suite rerun is green:
  1026 passed, 4 skipped** (411 s), so those failures were transient/environmental, not RLS. Remaining: policies for the other tenant tables, the worker BYPASSRLS role and the
  identity/sign-up SECURITY DEFINER exceptions. Uncommitted.
- **2026-10-21 (session 10, R3 retrieval):** migration **0023** adds document/chunk visibility
  (internal / customer_visible). New `retrieval.py` performs permission-filtered hybrid search:
  pgvector top-40 + PostgreSQL full-text top-40, RRF k=60, top-5, with citations (document, chunk,
  heading path, pages, blocks, score components). Filters: `knowledge:read`, tenant (RLS + explicit),
  `indexed` status, current embedding model and visibility (staff see both; portal customers would
  see customer_visible only). `GET /api/v1/knowledge/search` exposes it, returns
  `best_similarity`/`threshold`/`enough`, and a reranker hook (a cross-encoder was added next). The upload UI gained a visibility choice. Tests: 3 pure RRF/reranker unit tests
  and 8 DB/API tests (meaning order, exact-code keyword hit, tenant isolation, customer 403,
  visibility, threshold, reranker hook, whitespace 422) including a top-3 **retrieval evaluation**.
  **Full suite 1037 passed, 4 skipped**; frontend 205 tests/lint/typecheck/build clean; OpenAPI +
  inventory regenerated. Uncommitted.
- **2026-10-21 (session 11, rerank + grounded answers):** enabled the local cross-encoder
  `Xenova/ms-marco-MiniLM-L-6-v2`; it re-scores the RRF top-10, then the top-k is returned
  (`rerank_score` exposed). It loads lazily, caches the model and soft-falls back to RRF on failure.
  Added the R4 answer pipeline: `POST /api/v1/knowledge/answer` takes the best 3 reranked chunks as
  numbered context, builds a source-only prompt with `[n]` citation rules, calls Claude only when
  retrieval is confident, and returns the answer + sources + exact chunk. Not-found is an honest
  refusal with **zero model calls**; an unconfigured model returns 503. Tests: 3 pure retrieval
  unit tests, 8 search DB/API tests and 5 answer DB/API tests (citation context, refusal without a
  model call, 503, customer 403, reranker choosing the exact chunk) - 16 targeted tests pass. Real
  model checks: cross-encoder ranks the right policy first (9.27 vs 6.69 vs -6.24); **full suite
  1042 passed, 4 skipped**. Frontend unchanged (205 tests previously green). Uncommitted.
- **2026-10-21 (session 12, staff Search & Ask UI):** added `/knowledge/search` (linked as "Search &
  ask" on the documents page): a GET search form showing reranked passages with citation label,
  page, excerpt and match reasons; an Ask box (Server Action, 60 s timeout) rendering the answer,
  "Sources used" and numbered passages; low confidence refuses without calling the model. Frontend:
  **208 tests**, lint/typecheck/build clean. No browser/Playwright run yet (needs the full stack +
  login). Uncommitted.
- **2026-10-21 (session 13, grounded-answer evals):** added strict citation validation in the answer
  pipeline (no citation / invalid source number -> refusal, `grounded=false`, nothing unsupported
  shown; API returns `grounded`/`citations`). Added `evaluation.py` with deterministic
  groundedness, faithfulness (lexical support proxy), correctness (must-say/never-say) and
  injection-safety metrics; a 4-case fictional dataset (`evals/rag/answer_cases.json`) including the
  poisoned-document case; an opt-in live runner `scripts/eval_rag_answers.py` (calls Claude only
  with `CRM_RUN_LIVE_EVALS=1` and prints per-case scores); and `docs/rag-eval.md`. Tests: 5 metric
  tests + 2 new ungrounded-answer tests (23 targeted pass); frontend 208 tests/build clean. Live
  paid eval **not run** (needs cost approval). **Full suite 1049 passed, 4 skipped.** Uncommitted.
- **2026-10-21 (session 14, R6 operations, Phase 2/3 partial):** added the observability foundation:
  Prometheus metrics (HTTP, RAG retrieval/answer latency and outcomes, AI calls/tokens/estimated
  cost, worker heartbeat, outbox, knowledge/ingestion, pgvector checks), a token-protected
  `/api/v1/internal/metrics` route (404 without token, 401 wrong, 200 with), JSON log trace IDs +
  secret redaction, opt-in OpenTelemetry (FastAPI/SQLAlchemy/httpx), extended readiness
  (DB + pgvector extension + HNSW + `vector: ok`), worker heartbeat table/loop (migration 0024),
  Grafana dashboard + Prometheus rules + Alertmanager config + runbook/validation docs. Tests:
  **7 observability tests**, affected health/contract tests **34 passed**, **full suite 1056 passed,
  4 skipped**; dashboard JSON and alert/Alertmanager/Prometheus YAML parsed (9 panels, 10 rules).
  Not verified: live monitoring stack, alert delivery with controlled failures, OTLP collector,
  DeepSeek decision. Uncommitted.
- **2026-10-21 (session 20, R6.1 feedback + gaps):** migration **0027** adds `rag_queries` and
  `rag_feedback`; every staff/portal knowledge answer now records question/answer/sources and
  returns `query_id`; both surfaces have helpful/not-helpful buttons (server actions + UI);
  `scripts/rag_gaps_report.py` prints a 7-day report (by surface, negative rate, unanswered,
  refused, top questions). Tests: feedback upsert, gaps aggregation, answer/portal flows — **18
  targeted passed**; gaps report executed; frontend typecheck/lint/build clean. **Full suite 1069
  passed, 4 skipped**; the migration-sync test initially found constraint-name/ondelete drift, fixed
  and retested green. Uncommitted.
- **2026-10-21 (session 19, ticket drafts + assistant help):** added a customer-scoped
  `POST /api/v1/tickets/{id}/knowledge-draft` (staff ticket permission; only public +
  ticket-account chunks; returns draft + sources); added the portal assistant tool
  `search_help_articles` (public + granted accounts, returns document names/passages for citation)
  and instructed the assistant to use it for policy/help questions. **Structured citations:** tool
  results are stored on the assistant message (migration 0026) and returned as `citations`
  (document/heading/page); the portal chat renders a "Sources" list. Tests: 8 portal/knowledge
  tests passed (assistant tool scope + ticket draft included); OpenAPI/inventory regenerated;
  **full suite 1066 passed, 4 skipped** (only the committed OpenAPI was stale; regenerated and the
  contract test passes). No UI button to insert the ticket draft yet. Uncommitted.
- **2026-10-21 (session 18, portal knowledge):** migration **0025** adds optional `account_id`
  (composite tenant FK) to knowledge documents/chunks; portal retrieval allows only
  customer-visible public chunks + chunks of accounts in the caller's `portal_access_grants`,
  never internal/staff/other-account data. Added `POST /api/v1/portal/knowledge/answer`,
  `portal:knowledge:read` (customer role only; staff 403), the `/portal/knowledge` page
  ("Help & policies") linked from the portal home, and a customer-visible demo document. Tests:
  6 portal DB/API tests (public access, internal denial, other-account denial, own-account access,
  tenant isolation, staff 403) — **16 targeted passed**; frontend lint/typecheck/build clean;
  **Playwright journey passes** against the real stack; **full suite 1063 passed, 4 skipped**.
  Uncommitted.
- **2026-10-21 (session 17, R5 free 100-case completion):** no further paid calls. Expanded the
  free retrieval set to **100 cases** (80 answerable, 20 unanswerable); measured hit@5 **1.000**,
  MRR **1.000** without the reranker and MRR **0.979** with it, so the reranker stays **disabled**
  (gain −0.021). Calibrated `knowledge_min_similarity = 0.64`: on the 100 cases it retains **100 %**
  of answerable questions and detects **100 %** of the 20 unanswerable ones. Updated
  `docs/rag-eval.md`, `docs/rag-tuning.md` and ADR 0011; R5 is complete on the free suite.
  **Full suite 1057 passed, 4 skipped.** Uncommitted.
- **2026-10-21 (session 16, R5 paid eval + DeepSeek provider):** inspected local env (no Anthropic
  key; DeepSeek key configured), added a **DeepSeek OpenAI-compatible ChatModel adapter**
  (provider selection, usage/cost metrics, tool calls fail closed), fixed the invalid configured
  model name, and executed the approved **4-case paid answer eval** on DeepSeek `deepseek-chat`:
  returns/delivery/payment **1.00** groundedness+faithfulness+correctness; poisoned case answer
  was safe (it quoted the instruction while refusing), but the injection metric falsely failed it.
  Fixed the metric (sentence-level refusal cues), re-scored the **same paid answers with 0 new
  calls**: **4/4 pass**, groundedness 0.917, faithfulness 0.875, correctness 1.000, injection safe,
  doc-hit 1.000. R5 targets still open: faithfulness <95%, only 4 paid/13 free cases, threshold
  0.64 candidate not enforced. Then ran the final paid gate once with the reranker **off**:
  **4/4 pass**, groundedness 0.917, faithfulness **1.000**, correctness **1.000**, injection safe,
  doc-hit 1.000 (artifact `live-20261021T071621Z.json`); baseline comparison clean. Reranker
  default switched to **False** (no measured gain). **Full suite 1057 passed, 4 skipped.**
  Uncommitted.
