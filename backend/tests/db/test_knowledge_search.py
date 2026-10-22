# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""RAG R3 - hybrid retrieval through the real API, PostgreSQL and pgvector.

The embedder is a deterministic stand-in ("fake-semantic") so the test does not download a model,
but it produces meaningful vectors: "return/refund" -> dimension 0, "delivery/tracking" ->
dimension 1, "payment/invoice" -> dimension 2, anything else -> dimension 3. The API and the worker
are both given this embedder, exactly as production gives them the real one.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.auth.principal import Principal
from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.knowledge import api as knowledge_api
from app.modules.knowledge import retrieval
from app.modules.knowledge.models import KnowledgeChunk
from tests.db.test_quotes_api import Headers, api, auth, ok, world  # noqa: F401

SEARCH = "/api/v1/knowledge/search"
DOCS = "/api/v1/knowledge/documents"


class SemanticEmbedder:
    """Deterministic 384-dim vectors with a few interpretable topics."""

    model_name = "fake-semantic"
    dimensions = 384
    TOPICS = {"return": 0, "refund": 0, "delivery": 1, "tracking": 1, "payment": 2}

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * 384
        lowered = text.lower()
        matched = False
        for word, index in self.TOPICS.items():
            if word in lowered:
                vector[index] = 1.0
                matched = True
        if not matched:
            vector[3] = 1.0
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


EMBEDDER = SemanticEmbedder()


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def semantic(api: TestClient) -> SemanticEmbedder:
    api.app.state.embedder = EMBEDDER  # type: ignore[attr-defined]
    # Deterministic RRF order in these tests; the reranker has its own test.
    api.app.state.reranker = None  # type: ignore[attr-defined]
    return EMBEDDER


def _json(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def upload(
    api: TestClient,
    auth: Headers,
    *,
    name: str = "policy.txt",
    data: bytes,
    title: str,
    visibility: str = "internal",
    user: str = "alpha.admin",
) -> dict[str, Any]:
    return _json(
        ok(
            api.post(
                DOCS,
                data={"title": title, "visibility": visibility},
                files={"file": (name, data, "text/plain")},
                headers=auth(user),
            ),
            201,
        )
    )


def ingest(files: MemoryFileStore, db_session, document_id: str, embedder=EMBEDDER) -> None:
    job = db_session.scalars(
        select(OutboxJob).where(
            OutboxJob.kind == knowledge_api.JOB_KIND,
            OutboxJob.payload["document_id"].astext == document_id,
        )
    ).one()
    bind_tenant(db_session, job.tenant_id)
    knowledge_api.ingest_handler(files, embedder)(db_session, job)
    db_session.commit()


def create(api, auth, files, db_session, **kwargs) -> dict[str, Any]:
    document = upload(api, auth, **kwargs)
    ingest(files, db_session, document["id"])
    return document


def search(api, auth, query: str, *, user: str = "alpha.agent1", **params) -> dict[str, Any]:
    return _json(
        ok(
            api.get(SEARCH, params={"q": query, **params}, headers=auth(user)),
            200,
        )
    )


def test_meaning_search_returns_the_right_document(api, auth, files, semantic, db_session):
    returns = create(
        api,
        auth,
        files,
        db_session,
        title="Returns policy",
        data=b"# Returns\n\nDamaged items may be returned for a refund within 14 days.",
    )
    create(
        api,
        auth,
        files,
        db_session,
        title="Delivery",
        data=b"# Delivery\n\nDelivery takes five days. Tracking is e-mailed.",
    )

    response = search(api, auth, "I want a refund for a damaged return")

    assert response["results"]
    assert response["results"][0]["document_id"] == returns["id"]
    assert response["results"][0]["similarity"] is not None
    assert response["results"][0]["chunk_id"]
    assert response["enough"] is True
    assert response["threshold"] == 0.64


def test_keyword_search_finds_an_exact_code(api, auth, files, semantic, db_session):
    sku = create(
        api,
        auth,
        files,
        db_session,
        title="Replacement parts",
        data=b"# Parts\n\nReplacement part code SKU19 is available from stock.",
    )
    create(
        api,
        auth,
        files,
        db_session,
        title="General notes",
        data=b"# Notes\n\nUnrelated internal notes about the office.",
    )

    response = search(api, auth, "SKU19")

    found = [hit for hit in response["results"] if hit["document_id"] == sku["id"]]
    assert found, response["results"]
    assert found[0]["keyword_rank"] is not None


def test_search_is_tenant_isolated_and_requires_the_permission(
    api, auth, files, semantic, db_session
):
    create(
        api,
        auth,
        files,
        db_session,
        title="Alpha returns",
        data=b"# Returns\n\nRefunds for damaged items.",
    )

    beta = search(api, auth, "refund", user="beta.admin")
    assert beta["results"] == []
    assert beta["enough"] is False

    customer = api.get(SEARCH, params={"q": "refund"}, headers=auth("alpha.customer"))
    assert customer.status_code == 403


def test_visibility_filters_before_ranking(api, auth, files, semantic, db_session):
    internal = create(
        api,
        auth,
        files,
        db_session,
        title="Internal payment rules",
        data=b"# Payments\n\nPayment terms for staff only: invoices due in 30 days.",
    )
    visible = create(
        api,
        auth,
        files,
        db_session,
        title="Customer payment help",
        data=b"# Payments\n\nPayment instructions visible to customers: invoices due in 30 days.",
        visibility="customer_visible",
    )

    response = search(api, auth, "payment invoice")
    ids = {hit["document_id"] for hit in response["results"]}
    assert {internal["id"], visible["id"]} <= ids

    rows = db_session.scalars(
        select(KnowledgeChunk).where(
            KnowledgeChunk.document_id.in_([uuid.UUID(internal["id"]), uuid.UUID(visible["id"])])
        )
    ).all()
    assert {row.visibility for row in rows} == {"internal", "customer_visible"}


def test_threshold_reports_not_enough(api, auth, files, semantic, db_session, monkeypatch):
    create(
        api,
        auth,
        files,
        db_session,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items. Delivery note: see the delivery page.",
    )
    monkeypatch.setattr(api.app.state.settings, "knowledge_min_similarity", 0.999)

    response = search(api, auth, "refund")

    assert response["threshold"] == 0.999
    assert response["enough"] is False
    assert response["results"]


def test_optional_reranker_can_reorder_results(api, auth, files, semantic, db_session, world):
    create(
        api,
        auth,
        files,
        db_session,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items.",
    )
    create(
        api,
        auth,
        files,
        db_session,
        title="Refund FAQ",
        data=b"# FAQ\n\nRefund questions answered.",
    )
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    principal = Principal(
        subject="test",
        issuer="test",
        user_type="staff",
        roles=frozenset(),
        permissions=frozenset(),
        tenant_id=world.users["alpha.admin"].tenant_id,
    )
    settings = api.app.state.settings

    class Reverse:
        name = "reverse"

        def rerank(self, query, hits, limit):
            return list(reversed(hits))[:limit]

    plain = retrieval.search(
        db_session,
        principal,
        semantic,
        query="refund",
        candidates=settings.knowledge_candidates,
        rrf_k=settings.knowledge_rrf_k,
        top_k=2,
        min_similarity=None,
    )
    reranked = retrieval.search(
        db_session,
        principal,
        semantic,
        query="refund",
        candidates=settings.knowledge_candidates,
        rrf_k=settings.knowledge_rrf_k,
        top_k=2,
        min_similarity=None,
        reranker=Reverse(),
    )
    assert [hit.chunk_id for hit in reranked.results] == list(
        reversed([hit.chunk_id for hit in plain.results])
    )


def test_whitespace_query_is_rejected(api, auth, semantic):
    response = api.get(SEARCH, params={"q": "   "}, headers=auth("alpha.agent1"))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_knowledge_query"


def test_retrieval_evaluation_hit_rate(api, auth, files, semantic, db_session):
    """Small regression evaluation: every question must find its document in the top 3."""
    cases = [
        (
            "How long do refunds take?",
            "Returns policy",
            b"# Returns\n\nRefunds are paid in 5 days.",
        ),
        ("When does delivery arrive?", "Delivery", b"# Delivery\n\nDelivery takes 3 to 5 days."),
        ("How do I pay an invoice?", "Payments", b"# Payments\n\nPay an invoice by bank transfer."),
    ]
    expected: dict[str, str] = {}
    for _question, title, data in cases:
        document = create(api, auth, files, db_session, title=title, data=data)
        expected[title] = document["id"]

    hits = 0
    for question, title, _ in cases:
        result = search(api, auth, question)
        top = [hit["document_id"] for hit in result["results"][:3]]
        hits += expected[title] in top

    assert hits == len(cases)
