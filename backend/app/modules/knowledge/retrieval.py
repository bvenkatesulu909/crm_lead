"""Hybrid knowledge retrieval (RAG R3, ADR 0011).

One query, two independent candidate lists over the SAME permission-filtered rows:
- meaning search: pgvector cosine distance over chunk embeddings (HNSW index);
- word search: PostgreSQL full-text (websearch_to_tsquery + ts_rank_cd, GIN index).
The lists are merged with Reciprocal Rank Fusion (RRF, k=60) and cut to top-k.

Security comes first: the tenant is bound on the session (RLS, ADR 0009) AND every query filters
on tenant, document status and visibility, so an authorization bug cannot leak another tenant's
text. Only indexed chunks with an embedding from the CURRENT model are candidates.

The reranker is optional and off by default (ADR 0011: turn it on in R5 only with a measured gain).
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core.ai.embeddings import Embedder
from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import DomainError
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


class InvalidKnowledgeQueryError(DomainError):
    status_code = 422
    code = "invalid_knowledge_query"


class Reranker(Protocol):
    """Optional second-stage scorer. Implementations must not be trusted to filter permissions."""

    name: str

    def rerank(self, query: str, hits: Sequence["SearchHit"], limit: int) -> list["SearchHit"]: ...


class CrossEncoderReranker:
    """Local cross-encoder: scores each (query, chunk) pair and reorders the candidates.

    Loaded lazily on the first search; if the model cannot load or score (offline, missing
    download), the reranker logs and falls back to the RRF order - search must stay available.
    """

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self.name, cache_dir=self._cache_dir)
        return self._model

    def rerank(self, query: str, hits: Sequence["SearchHit"], limit: int) -> list["SearchHit"]:
        if not hits:
            return []
        try:
            scores = list(self._get_model().rerank(query, [hit.text for hit in hits]))
        except Exception as exc:  # noqa: BLE001 - optional feature; never break search
            logger.warning(
                "reranker unavailable, keeping RRF order", extra={"error": type(exc).__name__}
            )
            return list(hits[:limit])
        ranked = sorted(
            zip(hits, scores, strict=False), key=lambda pair: float(pair[1]), reverse=True
        )
        return [replace(hit, rerank_score=float(score)) for hit, score in ranked[:limit]]


def build_reranker(settings: Settings) -> Reranker | None:
    if not settings.knowledge_reranker_enabled:
        return None
    return CrossEncoderReranker(settings.knowledge_reranker_model, settings.embeddings_cache_dir)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    file_name: str
    heading_path: str
    page_from: int | None
    page_to: int | None
    text: str
    blocks: list[str]
    visibility: str
    similarity: float | None
    keyword_rank: int | None
    score: float
    # Set by the cross-encoder reranker when it runs (higher = more relevant).
    rerank_score: float | None = None


@dataclass(frozen=True)
class SearchOutcome:
    query: str
    results: list[SearchHit]
    best_similarity: float | None
    threshold: float | None
    enough: bool


def rrf_fuse(
    vector_ids: Sequence[uuid.UUID],
    keyword_ids: Sequence[uuid.UUID],
    *,
    k: int = 60,
) -> dict[uuid.UUID, float]:
    """Reciprocal Rank Fusion: 1/(k+rank) per list, summed; pure and easy to test."""
    scores: dict[uuid.UUID, float] = {}
    for ids in (vector_ids, keyword_ids):
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _allowed_visibilities(principal: Principal) -> tuple[str, ...]:
    # Staff see internal reference material and customer-visible material. Portal users (later)
    # must never see internal documents.
    if principal.user_type == "customer":
        return ("customer_visible",)
    return ("internal", "customer_visible")


def _conditions(
    principal: Principal, account_ids: Sequence[uuid.UUID] | None = None
) -> list[ColumnElement[bool]]:
    if principal.tenant_id is None:
        return []
    allowed = _allowed_visibilities(principal)
    conditions: list[ColumnElement[bool]] = [
        KnowledgeDocument.tenant_id == principal.tenant_id,
        KnowledgeDocument.status == "indexed",
        KnowledgeDocument.is_archived.is_(False),
        KnowledgeDocument.visibility.in_(allowed),
        KnowledgeChunk.visibility.in_(allowed),
    ]
    if principal.user_type == "customer":
        # Public customer-visible chunks (no account) OR chunks of accounts this portal user was
        # granted. Never internal documents and never another account's documents.
        conditions.append(
            or_(
                KnowledgeDocument.account_id.is_(None),
                KnowledgeDocument.account_id.in_(list(account_ids or [])),
            )
        )
    return conditions


def _vector_candidates(
    session: Session,
    principal: Principal,
    embedder: Embedder,
    query_vector: list[float],
    *,
    candidates: int,
    account_ids: Sequence[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    statement = (
        select(KnowledgeChunk.id, (1 - distance).label("similarity"))
        .join(
            KnowledgeDocument,
            (KnowledgeDocument.tenant_id == KnowledgeChunk.tenant_id)
            & (KnowledgeDocument.id == KnowledgeChunk.document_id),
        )
        .where(
            *_conditions(principal, account_ids),
            KnowledgeChunk.embedding.is_not(None),
            KnowledgeChunk.embedding_model == embedder.model_name,
        )
        .order_by(distance, KnowledgeChunk.id)
        .limit(candidates)
    )
    return [(row[0], float(row[1])) for row in session.execute(statement).all()]


def _keyword_candidates(
    session: Session,
    principal: Principal,
    query: str,
    *,
    candidates: int,
    account_ids: Sequence[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    tsquery = func.websearch_to_tsquery("simple", query)
    statement = (
        select(KnowledgeChunk.id)
        .join(
            KnowledgeDocument,
            (KnowledgeDocument.tenant_id == KnowledgeChunk.tenant_id)
            & (KnowledgeDocument.id == KnowledgeChunk.document_id),
        )
        .where(
            *_conditions(principal, account_ids),
            KnowledgeChunk.tsv.op("@@")(tsquery),
        )
        .order_by(func.ts_rank_cd(KnowledgeChunk.tsv, tsquery).desc(), KnowledgeChunk.id)
        .limit(candidates)
    )
    return [row[0] for row in session.execute(statement).all()]


def search(
    session: Session,
    principal: Principal,
    embedder: Embedder,
    *,
    query: str,
    candidates: int,
    rrf_k: int,
    top_k: int,
    min_similarity: float | None,
    reranker: Reranker | None = None,
    rerank_candidates: int = 10,
    account_ids: Sequence[uuid.UUID] | None = None,
) -> SearchOutcome:
    """Permission-filtered hybrid search. RLS adds the tenant check again at the database."""
    cleaned = " ".join(query.split())
    if not cleaned:
        raise InvalidKnowledgeQueryError("Type what you are looking for.")
    if principal.tenant_id is None:
        return SearchOutcome(cleaned, [], None, min_similarity, False)

    query_vector = embedder.embed_query(cleaned)
    vector_rows = _vector_candidates(
        session,
        principal,
        embedder,
        query_vector,
        candidates=candidates,
        account_ids=account_ids,
    )
    keyword_ids = _keyword_candidates(
        session, principal, cleaned, candidates=candidates, account_ids=account_ids
    )
    fused = rrf_fuse([chunk_id for chunk_id, _ in vector_rows], keyword_ids, k=rrf_k)
    if not fused:
        return SearchOutcome(cleaned, [], None, min_similarity, False)

    similarity_by_id = dict(vector_rows)
    keyword_rank_by_id = {chunk_id: rank for rank, chunk_id in enumerate(keyword_ids, start=1)}
    rows = session.execute(
        select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeChunk.text,
            KnowledgeChunk.blocks,
            KnowledgeChunk.heading_path,
            KnowledgeChunk.page_from,
            KnowledgeChunk.page_to,
            KnowledgeChunk.visibility,
            KnowledgeDocument.title,
            KnowledgeDocument.file_name,
        )
        .join(
            KnowledgeDocument,
            (KnowledgeDocument.tenant_id == KnowledgeChunk.tenant_id)
            & (KnowledgeDocument.id == KnowledgeChunk.document_id),
        )
        .where(*_conditions(principal, account_ids), KnowledgeChunk.id.in_(list(fused)))
    ).all()
    row_by_id = {row[0]: row for row in rows}

    hits = [
        SearchHit(
            chunk_id=row[0],
            document_id=row[1],
            text=row[2],
            blocks=row[3],
            heading_path=row[4],
            page_from=row[5],
            page_to=row[6],
            visibility=row[7],
            document_title=row[8],
            file_name=row[9],
            similarity=similarity_by_id.get(row[0]),
            keyword_rank=keyword_rank_by_id.get(row[0]),
            score=fused[row[0]],
        )
        for chunk_id, row in row_by_id.items()
    ]
    hits.sort(key=lambda hit: (-hit.score, str(hit.chunk_id)))

    best_similarity = max(similarity_by_id.values(), default=None)
    # The reranker only sees the RRF top 10; the final top-k is chosen from its ordering.
    pool = hits[:rerank_candidates]
    ranked = reranker.rerank(cleaned, pool, top_k) if reranker is not None else pool[:top_k]
    enough = bool(ranked) and (
        min_similarity is None
        or (best_similarity is not None and best_similarity >= min_similarity)
    )
    return SearchOutcome(cleaned, ranked, best_similarity, min_similarity, enough)
