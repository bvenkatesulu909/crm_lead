# ADR 0010 — RAG knowledge base for company documents

- **Status:** Proposed (2026-10-20; design only - no tables, code, dependency or Docker change
  yet; waiting for the owner's decisions in [docs/rag-knowledge-base.md](../rag-knowledge-base.md))
- **Date:** 2026-10-20
- **Deciders:** Project owner
- **Builds on:** ADR 0003 (accepted: local embeddings + pgvector for knowledge search); ADR 0005
  (outbox + worker); ADR 0009 (proposed RLS, not a prerequisite)

## Context

The owner wants the CRM to answer questions from **company knowledge**: policies, manuals and
production details, so the assistant can propose grounded answers instead of only reading CRM
records. ADR 0003 already decided the mechanism - an open-source embedding model runs locally and
vectors live in PostgreSQL via pgvector - but the concrete design was never written, and the
assistant phase stopped at portal text chat (20a).

Today:

- The assistant is **portal-only**; there is no staff chat.
- The documents module only stores files attached to customer accounts/quotes/opportunities;
  company manuals are not customer records.
- PostgreSQL runs postgres:16-alpine - **no vector extension**.
- The worker can run retryable background jobs; the outbox is the established pattern.

Security constraints are unchanged: tenant isolation, permissions before data leaves the server,
prompt-injection resistance, no secrets in code or logs, no client-trusted IDs.

## Decisions (proposed)

1. **A new knowledge module** owns tenant-level collections, documents and chunks:
   knowledge_collections (folder + audience staff/portal), knowledge_documents (file metadata,
   status, embedding model), knowledge_chunks (text + vector + page/heading for citations). No
   fake customer records. Uploads reuse the S3 file store and the existing upload validation,
   which moves to app/core/uploads.py so the documents and knowledge modules share one
   implementation.

2. **Local embeddings behind a protocol** (app/core/embeddings.py): embed_documents, embed_query,
   dimension, name - like the storage and mail interfaces. Candidate models are multilingual
   (bge-m3 / multilingual-e5); the final choice is made by a benchmark on the owner's real PDFs,
   recorded with the dimension. Knowledge text never leaves the machine for indexing.

3. **pgvector becomes required.** Docker image postgres:16-alpine becomes
   pgvector/pgvector:pg16 (same major version, volume kept), CREATE EXTENSION vector runs for crm
   and crm_test, and a migration creates the tables plus an HNSW cosine index. **The database is
   backed up and the restore verified before the image switch**, which the owner approves.

4. **Ingestion is asynchronous and idempotent.** One transaction saves the document and queues an
   outbox job (knowledge.ingest); the worker extracts text (pypdf/python-docx/plain), chunks
   (~700 tokens, ~100 overlap, page + heading kept), embeds and replaces that document's chunks.
   Failures retry through the existing outbox and dead-letter; status is visible (pending,
   indexed, failed, no_text). A knowledge.reindex job handles a model change.

5. **Permissions are applied before ranking.** Retrieval SQL filters by tenant, collection
   audience and per-document access (through the owning module's api.py, never a cross-module
   join) and only then orders by vector distance. Unauthorized chunks never leave the database,
   so they can never be sent to the model. Staff collections are for staff with knowledge:read /
   knowledge:manage; portal collections only for customers with portal:knowledge:read, and only
   when explicitly marked customer-visible.

6. **The assistant gets one read-only tool, search_knowledge**, with a strict argument schema and
   capped results. The answer must cite its sources; document text is data, never instructions;
   if the context is insufficient the assistant says it does not know and offers a human
   handover. The first consumer is a **new staff knowledge chat** (read-only, no CRM write tools);
   the portal assistant gets the tool later, limited to portal collections.

7. **No OCR, no connectors, no write actions in v1.** Scanned PDFs report no_text; crawling
   sites/e-mail/ERP belongs to Phase 19 Integrations. Chunk size, retrieval k, similarity floor
   and context size are settings, not constants.

8. **Evaluation is part of the feature.** 30-50 real questions with expected sources, measuring
   recall@k, citation correctness and refusal quality; prompt-injection tests embed instructions
   in a chunk and prove nothing unauthorized is returned.

## Consequences

- A new phase after the current one (or before it, if the owner chooses); steps are listed in
  [docs/rag-knowledge-base.md](../rag-knowledge-base.md) section 14, each stopping for review.
- New infrastructure: pgvector image, a local embedding dependency (size/speed depend on the
  chosen model), and indexing work in the worker (CPU-heavy on first ingestion).
- New tables and permissions; docs/api/openapi.json, docs/inventory.md, CLAUDE.md and
  implementation-plan.md must be updated as steps land.
- Portal exposure is opt-in and tested; internal policies/manuals stay internal by default.
- The embedding model becomes part of the index contract: changing it requires a reindex job,
  tracked by embedding_model on each document.

## Open questions for the owner

1. Staff first (recommended) or customers first?
2. Which local embedding model/CPU budget; are manuals scanned images (OCR needed)?
3. Approve the pgvector image change with a backup?
4. Uploads only, or also watched folders/connectors later?
5. Collection-level visibility per role, or all staff for v1?
6. Which languages (Telugu/English/Hindi) must be searchable?
7. May any internal knowledge ever be shown in the customer portal?
