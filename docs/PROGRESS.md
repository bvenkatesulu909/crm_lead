# crm-lead RAG add-on — progress

**Created:** 2026-10-20 (first session). **Status: no RAG code written yet** - materials read,
prerequisites audited, plan recorded. One part at a time, stop for approval.

Materials (now in the project):
- [rag-guide.pdf](rag-guide.pdf) - this add-on, Stages R0-R6 (30 pages, read 2026-10-20)
- [implementation-guide.pdf](implementation-guide.pdf) - the main project's later stages 0-6
- [project-guide.pdf](project-guide.pdf) - the base CRM (34 pages)
- Project rules: [../CLAUDE.md](../CLAUDE.md); current status: [gap-analysis.md](gap-analysis.md), [inventory.md](inventory.md).

## 1. Where we are

- Base CRM: running locally, migrations to **0019**, portal assistant text chat exists (Phase 20a).
- RAG add-on: **R0 complete locally** (steps 1-4). Design:
  [rag-knowledge-base.md](rag-knowledge-base.md); decisions:
  [ADR 0010](adr/0010-knowledge-search-pgvector-embeddings.md) and
  [ADR 0011](adr/0011-chunking-and-hybrid-search.md), both accepted.
- Session 1 did: read all three guides + CLAUDE.md + docs; audited RAG-guide section 1 against the
  code; wrote this file. **No migration, code, dependency or Docker change has been made.**
- **R1 in progress (ingestion built locally, uncommitted):** migration 0020 adds `kb_documents` and
  `kb_chunks` (RLS-ready); staff can upload PDF/DOCX/TXT/Markdown, the worker extracts, scans for
  personal data, chunks (ADR 0011) and replaces chunks in one transaction; status is visible. No
  screens and no embeddings yet.
- **R0 complete locally - awaiting approval to commit:** ADR 0010 (image/model/index)
  and ADR 0011 (chunking/hybrid search) accepted; custom image
  `crm-lead-postgres:16-pgvector-0.8.7` runs healthy on the same volume with `vector` 0.8.7 in
  both databases; the local embedding layer (fastembed/bge-small-en-v1.5, 384 dims) is implemented
  and smoke-tested. Steps 1-2 are committed on `rag-r0-setup`; the embedding layer and ADR 0011
  are **uncommitted**.
- **P0 CI (paused):** `.github/workflows/ci.yml` has backend and frontend jobs; backend is green on
  GitHub, the frontend `next typegen` fix is written but **uncommitted**, so CI is not green yet.

## 2. Prerequisites from RAG guide section 1 - audited against the code

| Prerequisite (implementation guide) | Status | Evidence in the repo / what is missing |
|---|---|---|
| Stage 0: Git, GitHub, CI | **Partial** | Git history exists and is pushed to GitHub (main at 6261015). **No CI**: no .github/workflows. The GitHub repo is **public**; Stage 0 asks for private. |
| 1A: Row-Level Security | **Missing** | 19 migrations, none contains ENABLE ROW LEVEL SECURITY / CREATE POLICY. Design is ADR 0009 (Proposed); not built. |
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
- [ ] Add embedding vector(384) and generated tsv (simple config) columns.
- [ ] HNSW cosine index, GIN on tsv, (tenant_id, status, visibility) index; pgvector iterative scans for filtered search.
- [ ] Embed all demo chunks through the worker with retries; embedding_model recorded per chunk.
- [ ] Model-change procedure documented (new column -> re-embed -> switch -> drop old).
- [ ] Record first timing of 100 searches in docs/rag-tuning.md.
- Done when: every published chunk has vector+keywords, indexes exist (migration test), retries tested.

### Stage R3 - Retrieval (branch rag-r3-retrieval)
- [ ] R3.1 Permission scope from existing policies: customer = public + own account chunks; staff = public + internal + allowed account chunks; tenant from RLS.
- [ ] R3.2 Hybrid search: vector + full-text, merged with Reciprocal Rank Fusion (limit 40 each, k=60).
- [ ] R3.3 Reranker: off until R5 evals show a gain (BAAI/bge-reranker-v2-m3 candidate).
- [ ] R3.4 Not-good-enough detection: best similarity vs threshold calibrated in R5.
- [ ] R3.5 Search API + portal help centre + staff search debugger; rag_queries logging.
- [ ] Tests: customer never sees internal/other-account chunks; Beta never sees Alpha; agent only own accounts; archived/other-model chunks excluded; mutation check (remove visibility -> tests fail).
- Done when: search works for both audiences, permissions proven, mutation caught, threshold set.

### Stage R4 - Answers with citations (branch rag-r4-answers)
- [ ] R4.1 Answer service: Claude search-result blocks, citations on, refusal handling, not-found path with no model call.
- [ ] R4.2 Citations -> numbered sources; only sources actually given; link to article; hover cited text.
- [ ] R4.3 Four places: portal "Ask", staff "Ask the knowledge base", ticket reply drafts (customer scope!), portal assistant (R4.4).
- [ ] R4.4 Assistant search tool search_help_articles via gateway, manual tool loop so citations survive.
- [ ] R4.5 Cost/speed: measure per answer; show expected cost before first real call.
- Done when: all four places answer with numbered sources; not-found offers a person and is logged; fake-client tests pass, including customer-scope drafts.

### Stage R5 - Evaluation and tuning (branch rag-r5-evals)
- [ ] R5.1 At least 100 eval cases: 3-5 per demo article, different wordings/languages, unanswerable, safety (other tenant, internal-for-customer, poisoned).
- [ ] R5.2 Retrieval metrics (free, CI): hit rate@5 and MRR; safety cases must be 100%.
- [ ] R5.3 Answer metrics (paid, on demand): faithfulness, citation correctness, must-say/never-say, not-found, language.
- [ ] R5.4 Targets: safety 100%; hit@5 >= 0.90; MRR >= 0.70; faithfulness >= 95%; not-found >= 90%.
- [ ] R5.5 Tuning loop: one setting at a time; record before/after in docs/rag-tuning.md; ask the student to predict first.
- Done when: 100+ cases, CI retrieval metrics meet targets, answer evals meet targets, tuning recorded.

### Stage R6 - Running it for real customers (branch rag-r6-operations)
- [ ] R6.1 Feedback buttons + weekly knowledge-gaps report; gap agent drafts articles at SUGGEST only (needs P6).
- [ ] R6.2 Freshness: edits/new versions re-ingest; nightly consistency check (published without chunks, archived chunks, old model, stuck processing).
- [ ] R6.3 Retention/deletion: archiving deletes chunks in same transaction; rag_queries 90 days; erasure clears stored questions.
- [ ] R6.4 Monitoring/alerts: zero/not-found rates, not-helpful, latency, cost per answer, ingestion failures, answers without citations (needs P5).
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
