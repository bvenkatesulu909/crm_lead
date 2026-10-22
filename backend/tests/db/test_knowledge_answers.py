# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""RAG R4 - grounded answers: exact chunk, prompt context, citations, refusal, no paid calls."""

from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.storage import MemoryFileStore
from app.modules.assistant.llm import ModelReply, UnconfiguredChatModel
from app.modules.knowledge import api as knowledge_api
from tests.db.test_quotes_api import Headers, api, auth, ok, world  # noqa: F401

ANSWER = "/api/v1/knowledge/answer"
DOCS = "/api/v1/knowledge/documents"


class SemanticEmbedder:
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


class FakeChatModel:
    available = True

    def __init__(self, answer: str = "Refunds are paid within 14 days [1].") -> None:
        self.answer = answer
        self.calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls.append((system, messages, tools))
        return ModelReply(self.answer, [], "end_turn")


EMBEDDER = SemanticEmbedder()


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


@pytest.fixture
def model(api: TestClient) -> FakeChatModel:
    fake = FakeChatModel()
    api.app.state.embedder = EMBEDDER  # type: ignore[attr-defined]
    api.app.state.reranker = None  # type: ignore[attr-defined]
    api.app.state.chat_model = fake  # type: ignore[attr-defined]
    return fake


def _json(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def upload(
    api: TestClient, auth: Headers, *, title: str, data: bytes, user: str = "alpha.admin"
) -> dict[str, Any]:
    response = api.post(
        DOCS,
        data={"title": title},
        files={"file": ("policy.txt", data, "text/plain")},
        headers=auth(user),
    )
    return _json(ok(response, 201))


def ingest(files: MemoryFileStore, db_session, document_id: str) -> None:
    from sqlalchemy import select

    from app.core.db import bind_tenant
    from app.core.outbox import OutboxJob

    job = db_session.scalars(
        select(OutboxJob).where(
            OutboxJob.kind == knowledge_api.JOB_KIND,
            OutboxJob.payload["document_id"].astext == document_id,
        )
    ).one()
    bind_tenant(db_session, job.tenant_id)
    knowledge_api.ingest_handler(files, EMBEDDER)(db_session, job)
    db_session.commit()


def ask(api: TestClient, auth: Headers, question: str, *, user: str = "alpha.agent1"):
    return api.post(ANSWER, json={"question": question}, headers=auth(user))


def test_answer_uses_the_exact_chunk_and_cites_it(api, auth, files, model, db_session):
    document = upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items are paid within 14 days.",
    )
    ingest(files, db_session, document["id"])

    response = ok(ask(api, auth, "How long do refunds take?"), 200)

    assert response["answer"].startswith("Refunds are paid")
    assert response["enough"] is True
    assert response["model_used"] is True
    assert response["grounded"] is True
    assert response["citations"] == [1]
    assert response["sources"]
    assert response["sources"][0]["document_id"] == document["id"]
    assert response["exact_chunk_id"] == response["sources"][0]["chunk_id"]
    assert len(model.calls) == 1
    system, messages, tools = model.calls[0]
    assert "ONLY from the numbered sources" in system
    assert "How long do refunds take?" in messages[0]["content"]
    assert "[1] Returns policy" in messages[0]["content"]
    assert tools == []


def test_not_enough_context_returns_refusal_without_calling_the_model(
    api, auth, files, model, db_session, monkeypatch
):
    upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds are paid. Delivery note.",
    )
    # Make the best similarity clearly below the threshold.
    monkeypatch.setattr(api.app.state.settings, "knowledge_min_similarity", 0.999)

    response = ok(ask(api, auth, "What is the refund policy?"), 200)

    assert response["enough"] is False
    assert response["model_used"] is False
    assert response["sources"] == []
    assert "couldn't find" in response["answer"]
    assert model.calls == []


def test_unconfigured_model_answers_503(api, auth, files, model, db_session):
    document = upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items are paid within 14 days.",
    )
    ingest(files, db_session, document["id"])
    api.app.state.chat_model = UnconfiguredChatModel()

    response = ask(api, auth, "How long do refunds take?")

    assert response.status_code == 503
    assert response.json()["code"] == "assistant_unavailable"


def test_customers_cannot_ask_the_knowledge_base(api, auth, model):
    response = ask(api, auth, "How long do refunds take?", user="alpha.customer")
    assert response.status_code == 403


def test_reranker_chooses_the_exact_chunk(api, auth, files, model, db_session):
    first = upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items are paid within 14 days.",
    )
    second = upload(
        api,
        auth,
        title="Refund FAQ",
        data=b"# FAQ\n\nRefund questions: refunds take two weeks.",
    )
    ingest(files, db_session, first["id"])
    ingest(files, db_session, second["id"])

    api.app.state.reranker = None
    plain = ok(ask(api, auth, "refund"), 200)

    class ReverseReranker:
        name = "reverse"

        def rerank(self, query, hits, limit):
            return list(reversed(hits))[:limit]

    api.app.state.reranker = ReverseReranker()

    response = ok(ask(api, auth, "refund"), 200)

    plain_top = [source["chunk_id"] for source in plain["sources"]]
    reversed_top = [source["chunk_id"] for source in response["sources"]]
    assert reversed_top == list(reversed(plain_top))[: len(reversed_top)]
    assert response["exact_chunk_id"] == reversed_top[0]
    assert len(response["sources"]) <= 3
    assert first["id"] != second["id"]


def test_uncited_answer_is_rejected_as_ungrounded(api, auth, files, model, db_session):
    document = upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items are paid within 14 days.",
    )
    ingest(files, db_session, document["id"])
    model.answer = "Refunds are paid within 14 days."

    response = ok(ask(api, auth, "How long do refunds take?"), 200)

    assert response["enough"] is False
    assert response["grounded"] is False
    assert response["model_used"] is True
    assert response["sources"] == []
    assert "fully supported" in response["answer"]


def test_invalid_source_number_is_rejected_as_ungrounded(api, auth, files, model, db_session):
    document = upload(
        api,
        auth,
        title="Returns policy",
        data=b"# Returns\n\nRefunds for damaged items are paid within 14 days.",
    )
    ingest(files, db_session, document["id"])
    model.answer = "Refunds are paid within 14 days [9]."

    response = ok(ask(api, auth, "How long do refunds take?"), 200)

    assert response["enough"] is False
    assert response["grounded"] is False
    assert response["citations"] == []
    assert response["sources"] == []


def test_feedback_records_and_updates_one_vote(api, auth, files, model, db_session, world):
    from sqlalchemy import select

    from app.core.db import bind_tenant
    from app.modules.knowledge.models import RagFeedback

    document = upload(
        api, auth, title="Returns policy", data=b"# Returns\n\nRefunds within 14 days."
    )
    ingest(files, db_session, document["id"])
    answer = ok(ask(api, auth, "How long do refunds take?"), 200)
    query_id = answer["query_id"]
    assert query_id
    assert (
        api.post(
            "/api/v1/knowledge/feedback",
            json={"query_id": query_id, "helpful": True},
            headers=auth("alpha.agent1"),
        ).status_code
        == 204
    )
    assert (
        api.post(
            "/api/v1/knowledge/feedback",
            json={"query_id": query_id, "helpful": False},
            headers=auth("alpha.agent1"),
        ).status_code
        == 204
    )
    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    votes = db_session.scalars(select(RagFeedback)).all()
    assert len(votes) == 1 and votes[0].helpful is False
