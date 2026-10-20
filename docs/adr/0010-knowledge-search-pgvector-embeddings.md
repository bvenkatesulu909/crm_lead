# ADR 0010 — Knowledge search: pgvector image, embedding model and index

- **Status:** Accepted (2026-10-20, approved by the project owner; records the R0 groundwork
  decisions for Phase 20b; **no code or infrastructure has been changed yet**)
- **Date:** 2026-10-20
- **Deciders:** Project owner
- **Relates to:** ADR 0003 (accepted: local embeddings + pgvector for knowledge search),
  ADR 0007 (online deployment - a new requirement on the hosted database),
  ADR 0009 (proposed: Row-Level Security; the chunk tables must be ready for it)

## Context

Phase 20b adds a knowledge base: company documents are split into searchable chunks, and the
assistant answers questions from them with citations. ADR 0003 already chose the direction -
embeddings are computed **locally** and vectors live in the existing PostgreSQL through the
**pgvector** extension - but not the concrete pieces. Before any table, dependency or container is
touched, R0 has to decide:

1. which PostgreSQL image ships pgvector (and how not to break the existing data volume),
2. how the extension is enabled without giving the API superuser rights,
3. which embedding model runs locally,
4. which index makes "nearest meaning" searches fast,
5. what future chunk tables must look like for tenants and RLS.

Constraints: Windows + Docker Desktop on one machine; the existing data volume must keep working
without a dump/restore; knowledge text must never leave the machine for indexing; one tenant must
never see another tenant's text, and internal documents must never reach customers.

## Decisions

### 1. Our own PostgreSQL image with pgvector compiled in [CHOICE]

Add `infrastructure/postgres/Dockerfile` that starts `FROM postgres:16-alpine` and compiles
**pgvector from source at a pinned version (v0.8.7, released 2026-10-01)** in a build stage. The
final image contains only the compiled extension files, not the compiler. The image tag is pinned in
`docker-compose.yml`, and the project builds it with `docker compose build postgres`.

**In plain terms:** PostgreSQL sorts text according to the C library of its base image ("collation").
The official `pgvector/pgvector:pg16` image is Debian-based (glibc); our current
`postgres:16-alpine` is Alpine (musl). Replacing the image under an existing data volume changes
the sort order, so text indexes built with the old order can become inconsistent: PostgreSQL then
requires `REINDEX`, or a full dump and restore. Compiling the extension into the existing Alpine
base keeps the same base image, collation, data volume and indexes - so no REINDEX is needed.

**Rejected alternative:** `pgvector/pgvector:pg16` - simpler to adopt, but the glibc/musl change
forces a REINDEX or dump/restore on every existing database (development, test, and the owner's
data) for a one-line benefit. It remains a fallback if the custom build proves impractical.

### 2. Enable the extension from a superuser init script, not a migration

`CREATE EXTENSION vector` requires a **database superuser**. Our normal roles are deliberately
not superusers (the `owner` role runs migrations, the `app` role runs the API). Therefore:

- a new init script `infrastructure/postgres/init/03-enable-pgvector.sh` runs on **first start of
  a new volume** (after the roles/databases script) and executes
  `CREATE EXTENSION IF NOT EXISTS vector;` in both `crm` and `crm_test`;
- **existing volumes** do not re-run init scripts; they get a documented **one-off CMD command**
  (repeated in the R0 runbook) to create the extension as the superuser;
- the Alembic migration for the knowledge tables **only verifies** that the extension exists and
  fails with a clear message if it does not. It never tries to create it, because the migration
  role is not a superuser.

*In plain terms:* installing a database-wide extension is an administrator action; giving the
migration role superuser rights for one line would weaken every migration.

### 3. Embedding model: fastembed (ONNX, CPU) with BAAI/bge-small-en-v1.5, 384 dimensions [CHOICE]

Compute embeddings **inside the backend** with `fastembed` (ONNX Runtime), model
`BAAI/bge-small-en-v1.5` producing **384 numbers** per chunk.

- `fastembed` avoids PyTorch: no multi-GB install, no GPU, fast and small enough for the owner's
  Windows machine; ONNX Runtime is CPU-only here.
- `bge-small-en-v1.5` is a well-known small English model: good quality for its size and fast on
  a CPU. The first run downloads the model; the library and model revision are pinned.
- Every chunk stores the model name/revision that produced its vector, and a search only compares
  chunks embedded by the **current** model.
- **Changing the model later means re-embedding every chunk** (background job, out of R0 scope).
- Limitation to record now: this is an **English** model. Telugu/Hindi/multilingual manuals would
  need a multilingual model and a full re-embed; that decision must be made before indexing real
  content.

*In plain terms:* an embedding turns text into a list of numbers; 384 numbers are compact enough to
store many chunks and compare quickly.

**Rejected alternatives:** PyTorch + sentence-transformers (large install), cloud embedding APIs
(text leaves the machine and costs per chunk; contradicts ADR 0003), bge-m3 (better multilingual but
slower/bigger on CPU; a later upgrade, not the starting point).

### 4. Index: HNSW with cosine distance

Future chunk tables get `embedding vector(384)` and an **HNSW** index using
`vector_cosine_ops`. HNSW is an approximate nearest-neighbour index: it finds the closest meanings
quickly instead of comparing the question with every chunk. Cosine distance is the standard choice
for normalised text embeddings.

*In plain terms:* HNSW is like a library index that gets you close to the right shelf quickly; the
final comparisons happen only among nearby candidates. Index parameters stay at defaults until the
R5 evaluation set measures them; they are never tuned by guesswork.

### 5. Future chunk tables are tenant tables

The R1 tables (`kb_articles`, `kb_documents`, `kb_chunks`) will:

- carry `tenant_id` with composite same-tenant foreign keys (no cross-tenant links),
- be accessed through the tenant-scoped repository (the base class exists),
- be designed so the RLS policies of ADR 0009 can be enabled without redesign,
- never be searched with a query that fetches broadly and filters afterwards: tenant and
  visibility filters are part of the SQL **before** ranking.

### 6. Consequence for ADR 0007 (online deployment)

The hosted PostgreSQL selected for step D2 must **support pgvector** (the extension is available),
or the database must run this same custom image on a container host. Managed providers must be
checked before any purchase. If the chosen database cannot install pgvector, the deployment plan
needs a different database. This does not change the hosting layout - only a requirement on the
database provider.

### 7. Out of scope for R0

R0 does **not** create knowledge tables, does not build upload or indexing, does not change
retrieval in the assistant, and adds no UI. Those belong to R1-R4. R0 delivers: these decisions, the
pgvector image and extension groundwork (later steps), and the embedding-service interface (later
steps).

## Consequences

- The development PostgreSQL image becomes ours to build and pin; building it needs network access
  once to fetch the pgvector source.
- **Back up the database before switching the image** (the next R0 step); the backup is the safety
  net, but keeping the same base image/collation is what avoids the REINDEX in the first place.
- Existing volumes need the documented one-off superuser command; new volumes get the extension
  automatically.
- CI currently uses `postgres:16`; once R0 lands, CI must use the same pgvector-enabled image so
  tests can create and query `vector` columns.
- `fastembed` adds a Python dependency and downloads a model on first use; both must be pinned and
  cached, and tests must not need the real model (a fake embedder covers them).
- Changing the embedding model is a **data migration** (re-embed all chunks), not a configuration
  change.
- The knowledge feature cannot ship until the extension check passes in every environment:
  development, test, and production.

## Alternatives considered (summary)

| Alternative | Why not (now) |
|---|---|
| `pgvector/pgvector:pg16` image | Debian/glibc base changes text collation -> REINDEX or dump/restore on existing volumes |
| `CREATE EXTENSION` in an Alembic migration | Needs superuser; our migration role deliberately is not one |
| Cloud embedding API | Knowledge text would leave the machine and cost per chunk; ADR 0003 chose local |
| Larger local model (bge-m3 / PyTorch) | Bigger/slower on CPU; can be a later upgrade with a full re-embed |
| Brute-force search without an index | Fine for a toy, too slow for real customer knowledge |

## Approval

This ADR is **Accepted** (2026-10-20). R0 step 2 (custom image, backup, extension) starts only
after a separate go-ahead and a verified database backup. No code, dependency, Docker file,
migration or running service was changed by this step.
