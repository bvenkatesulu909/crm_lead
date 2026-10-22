# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Portal knowledge answers: public + granted-account chunks only; never internal/staff."""

from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import bind_tenant
from app.core.outbox import OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.assistant.llm import ModelReply
from app.modules.knowledge import api as knowledge_api
from tests.db.test_quotes_api import Headers, api, auth, ok, world  # noqa: F401

PORTAL = "/api/v1/portal/knowledge/answer"
DOCS = "/api/v1/knowledge/documents"


class SemanticEmbedder:
    model_name = "fake-portal-semantic"
    dimensions = 384
    TOPICS = {"return": 0, "internal": 1, "contract": 2, "warranty": 3}

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * 384
        lowered = text.lower()
        for word, index in self.TOPICS.items():
            if word in lowered:
                vector[index] = 1.0
        if not any(vector):
            vector[4] = 1.0
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeChatModel:
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def reply(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply:
        self.calls += 1
        return ModelReply("The public policy allows this [1].", [], "end_turn")


EMBEDDER = SemanticEmbedder()


@pytest.fixture
def files(api: TestClient) -> MemoryFileStore:
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    api.app.state.embedder = EMBEDDER  # type: ignore[attr-defined]
    api.app.state.reranker = None  # type: ignore[attr-defined]
    api.app.state.chat_model = FakeChatModel()  # type: ignore[attr-defined]
    return store


def _json(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def upload(
    api: TestClient,
    auth: Headers,
    *,
    title: str,
    text: str,
    visibility: str = "internal",
    account_id: str | None = None,
    user: str = "alpha.admin",
) -> dict[str, Any]:
    data: dict[str, str] = {"title": title, "visibility": visibility}
    if account_id:
        data["account_id"] = account_id
    response = api.post(
        DOCS,
        data=data,
        files={"file": ("doc.txt", text.encode(), "text/plain")},
        headers=auth(user),
    )
    return _json(ok(response, 201))


def ingest(files: MemoryFileStore, db_session, document_id: str) -> None:
    job = db_session.scalars(
        select(OutboxJob).where(
            OutboxJob.kind == knowledge_api.JOB_KIND,
            OutboxJob.payload["document_id"].astext == document_id,
        )
    ).one()
    bind_tenant(db_session, job.tenant_id)
    knowledge_api.ingest_handler(files, EMBEDDER)(db_session, job)
    db_session.commit()


def ask(api: TestClient, auth: Headers, question: str, *, user: str = "alpha.customer"):
    return api.post(PORTAL, json={"question": question}, headers=auth(user))


def test_portal_sees_public_customer_visible_chunk(api, auth, files, db_session):
    document = upload(
        api,
        auth,
        title="Customer returns help",
        text="Customers may return damaged items. Public return policy.",
        visibility="customer_visible",
    )
    ingest(files, db_session, document["id"])

    response = ok(ask(api, auth, "return damaged items"), 200)

    assert response["sources"]
    assert all(
        source["document_title"] == "Customer returns help" for source in response["sources"]
    )


def test_portal_never_sees_internal_documents(api, auth, files, db_session):
    internal = upload(
        api,
        auth,
        title="Internal margin notes",
        text="Internal secret margin policy. Staff only.",
    )
    ingest(files, db_session, internal["id"])

    response = ok(ask(api, auth, "internal margin policy"), 200)

    assert response["sources"] == []
    assert response["enough"] is False
    assert response["model_used"] is False


def test_portal_cannot_see_another_accounts_chunk(api, auth, files, db_session, world):
    other = upload(
        api,
        auth,
        title="Contract for account two",
        text="Contract terms that belong to account two only.",
        visibility="customer_visible",
        account_id=str(world.ids["A2"]),
    )
    ingest(files, db_session, other["id"])

    response = ok(ask(api, auth, "contract terms"), 200)

    assert response["sources"] == []
    assert response["enough"] is False


def test_portal_sees_its_own_account_chunk(api, auth, files, db_session, world):
    own = upload(
        api,
        auth,
        title="Warranty for account one",
        text="Warranty terms for this customer's account.",
        visibility="customer_visible",
        account_id=str(world.ids["A1"]),
    )
    ingest(files, db_session, own["id"])

    response = ok(ask(api, auth, "warranty terms"), 200)

    assert [source["document_title"] for source in response["sources"]] == [
        "Warranty for account one"
    ]


def test_portal_isolated_from_other_tenant(api, auth, files, db_session):
    beta = upload(
        api,
        auth,
        title="Beta portal policy",
        text="Beta customer return policy for another tenant.",
        visibility="customer_visible",
        user="beta.admin",
    )
    ingest(files, db_session, beta["id"])

    response = ok(ask(api, auth, "beta customer return"), 200)

    assert all(source["document_title"] != "Beta portal policy" for source in response["sources"])


def test_staff_tokens_are_rejected_by_the_portal_endpoint(api, auth):
    response = ask(api, auth, "return policy", user="alpha.agent1")
    assert response.status_code == 403


def test_assistant_help_tool_is_portal_scoped(api, auth, files, db_session, world):
    from app.core.auth.principal import Principal
    from app.modules.assistant import tools as assistant_tools

    document = upload(
        api,
        auth,
        title="Customer returns help",
        text="Customers may return damaged items. Public return policy.",
        visibility="customer_visible",
    )
    ingest(files, db_session, document["id"])
    principal = Principal(
        subject="test",
        issuer="test",
        user_type="customer",
        roles=frozenset(),
        permissions=frozenset(),
        tenant_id=world.users["alpha.customer"].tenant_id,
        user_id=world.users["alpha.customer"].id,
    )
    result = assistant_tools.execute(
        db_session,
        principal,
        "search_help_articles",
        {"question": "return damaged"},
        lambda _: None,
    )
    assert result.outcome == "ok"
    assert "Customer returns help" in result.content


def test_staff_can_draft_a_ticket_reply_from_customer_scope(api, auth, files, db_session, world):
    document = upload(
        api,
        auth,
        title="Warranty for account one",
        text="Warranty terms for this customer's account.",
        visibility="customer_visible",
        account_id=str(world.ids["A1"]),
    )
    ingest(files, db_session, document["id"])
    ticket = api.post(
        "/api/v1/tickets",
        json={
            "account_id": str(world.ids["A1"]),
            "subject": "Warranty question",
            "description": "What warranty terms apply?",
        },
        headers=auth("alpha.admin"),
    )
    assert ticket.status_code == 201, ticket.text
    draft = api.post(
        f"/api/v1/tickets/{ticket.json()['id']}/knowledge-draft",
        headers=auth("alpha.support"),
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["draft"]
    assert [source["document_title"] for source in body["sources"]] == ["Warranty for account one"]
