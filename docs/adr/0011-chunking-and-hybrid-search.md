# ADR 0011 — Chunking and hybrid search: starting settings

- **Status:** Accepted (2026-10-20; owner instructed completion of R0.3; the numeric settings are
  starting points that Stage R5 tunes against the evaluation set)
- **Date:** 2026-10-20
- **Deciders:** Project owner
- **Relates to:** ADR 0010 (pgvector image, embedding model, HNSW index), ADR 0009 (proposed RLS)

## Context

ADR 0010 chose the storage and the embedding model. Before R1/R2 can build ingestion and search,
two things must be written down so the code is deterministic and reviewable:

1. **How a document becomes chunks** (size, overlap, what metadata is kept, how citations stay
   precise).
2. **How a question finds the right chunks** (meaning search, word search, how the two are merged,
   what happens when nothing is good enough).

These are decisions, not tuning: R5 may change the numbers, but the shape (hybrid search, RRF,
heading paths, blocks for citations) should not change casually. Without a written starting point,
every implementation choice becomes an undocumented guess.

## Decisions

### 1. Chunk shape: structure-aware, about 1,600 characters, one-paragraph overlap

- **Target size:** ~**1,600 characters** (roughly 400 tokens). Big enough to answer a question,
  small enough that a citation points to a short passage.
- **Overlap:** carry **one paragraph** into the next chunk, so a sentence split across a boundary
  is still found by both chunks.
- **Structure:** respect the document's headings where the extractor provides them (Markdown,
  DOCX paragraph styles, PDF text heuristics). Each chunk records its **heading path** (for example
  `Returns policy > Damaged items`).
- **Heading path in the embedding text:** the heading path is prepended before embedding
  (`heading_path + newline + paragraphs`). This measurably improves retrieval because the same
  words in different sections get different meanings ("returns" in the shipping section vs the
  policy section).
- **Paragraph blocks stay separate.** A chunk stores `blocks` (JSONB list of paragraphs) and the
  concatenated `text`. Citations point at blocks, so the UI can show exactly the cited sentences
  rather than a whole chunk.
- **Large paragraphs** are split at sentence boundaries near the target size; **tiny trailing
  fragments** (under ~200 characters) are merged into the previous chunk when they belong to the
  same heading.
- Each chunk records `position`, `heading_path`, `page_from`, `page_to`, `token_count`.

### 2. Chunking is deterministic and versioned

The chunker version/configuration is stored on every chunk (`chunking_version`). Re-running
ingestion for the same document version replaces its chunks **in one transaction**, so search never
sees half an update. Changing the chunker later means re-ingesting documents, exactly like changing
the embedding model means re-embedding.

### 3. Metadata is copied onto every chunk

Each chunk carries `tenant_id`, `visibility` (public/internal/account), `account_id`, `status`,
`document_version` and `embedding_model`. Search therefore needs **no joins** to apply the
permission filter, and the filter can run before ranking - which is the rule that prevents leaks and
empty filtered results.

### 4. Two search columns

- **Meaning search:** `embedding vector(384)` with an **HNSW cosine** index (ADR 0010). The
  question is embedded by the same model version; chunks embedded by another model are ignored.
- **Word search:** a stored generated column
  `tsv = to_tsvector('simple', heading_path || ' ' || text)` with a **GIN** index.
  The `simple` configuration does no language-specific stemming. It works identically for
  English now and for Telugu/Hindi later, and still matches exact codes, invoice numbers and
  product names, which meaning search can miss.

### 5. Hybrid retrieval with Reciprocal Rank Fusion (RRF)

Run both searches over the **same permission-filtered** chunk set:

- meaning search: top **40** chunks by cosine distance;
- word search: top **40** chunks by PostgreSQL rank, using `websearch_to_tsquery('simple', query)`;
- merge with **RRF**: each chunk scores `SUM(1 / (60 + rank))` across the lists it appears in;
- return the best **5** chunks to the answer step.

Why both: a customer writes "send back" while the policy says "return" - the meaning search finds
it; a colleague asks about product code `SKU-19` - the word search finds it. RRF rewards chunks
that rank well in **both** lists without needing a calibrated score comparison.

Because the permission filter removes most rows for a customer, the vector index may not return
enough candidates; the search transaction enables pgvector's iterative scan
(`SET LOCAL hnsw.iterative_scan = relaxed_order`, available in pgvector 0.8.7) so filtered
searches still get 40 candidates.

### 6. No reranker at the start

A cross-encoder reranker (for example BAAI/bge-reranker-v2-m3) can improve the final top 5, but it
adds latency and a second model. It stays **off** until the R5 evaluation set shows a measured gain.

### 7. "Not good enough" is a threshold, calibrated by measurement

RRF produces a ranking but not a confidence. The decision "we have no answer" uses the **best
cosine similarity** `1 - distance` of the meaning search, compared with a threshold that R5
calibrates on the evaluation set. Below the threshold, Claude is **not called**: the system says it
could not find the answer, offers a human, and logs a knowledge gap. The starting threshold is
deliberately unset (no fake precision) and is recorded after calibration.

### 8. Embeddings unavailable means no silent fallback

If the local embedding model cannot run, search and answers return 503
`embeddings_unavailable`. A silent keyword-only answer would look identical to a normal one while
missing paraphrases and possibly policy nuances. Availability is preferable to an unannounced
quality drop; the error is visible and retryable.

### 9. All starting settings live in one place

| Setting | Starting value |
|---|---|
| Chunk target characters | 1,600 |
| Paragraph overlap | 1 |
| Heading path in embedding text | on |
| Candidates per search method | 40 |
| RRF constant | 60 |
| Results sent to the answer step | 5 |
| Reranker | off |
| Not-found similarity threshold | unset until R5 calibration |
| Keyword configuration | `simple` (no stemming) |

They belong in one settings module (with environment overrides from Appendix D of the RAG guide),
never scattered as magic numbers in the code. Changing one is a tuning change recorded in
`docs/rag-tuning.md`, not a new ADR.

### 10. Out of scope

No tables, migrations, ingestion code or UI are decided here (R1/R2). OCR, multilingual keyword
configuration, reranking and question rewriting are later, measured changes.

## Consequences

- The answer step receives about 5 chunks × ~400 tokens ≈ 2,000 tokens of context plus
  instructions, keeping cost and latency predictable.
- Chunking quality becomes a tunable with numbers (R5), not an opinion.
- Changing the chunker or the embedding model requires re-ingestion/re-embedding; both are recorded
  per chunk so a mixed index is detectable.
- `simple` keyword search will not match "returned" to "return" by stemming; the meaning search
  covers word forms, and R5 can measure whether a language-specific configuration is worth it.
- Filtering before ranking remains the security rule; iterative scans keep that practical.

## Alternatives considered

| Alternative | Why not (now) |
|---|---|
| One chunk per document | Too coarse for citations; poor precision |
| Fixed windows ignoring headings | Loses section context; worse retrieval and citations |
| Meaning search only | Misses exact codes, numbers and names |
| Keyword search only | Misses paraphrases ("send back" vs "return") |
| Reranker immediately | Extra latency/cost before any measured gain |
| Language-specific stemming now | Premature while the first content is English |
| Score-threshold on RRF | RRF scores are rank-based, not comparable across queries |

## Approval

Accepted on 2026-10-20 at the owner's instruction to complete R0.3. The numbers are starting points;
R5 changes them only through the measurement loop.
