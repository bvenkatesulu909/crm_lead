# ruff: noqa: F811 - fixtures from test_quotes_api are used as parameters
"""App-role RLS tenant isolation (enforced knowledge tables)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import bind_tenant, clear_tenant
from app.core.storage import MemoryFileStore
from app.modules.knowledge.models import KnowledgeDocument
from tests.db.test_quotes_api import Headers, api, auth, ok, world  # noqa: F401

DOCS = "/api/v1/knowledge/documents"


@pytest.fixture(autouse=True)
def files(api: TestClient, monkeypatch):
    store = MemoryFileStore()
    api.app.state.file_store = store  # type: ignore[attr-defined]
    return store


def _upload(api: TestClient, auth: Headers, user: str, name: str) -> dict[str, Any]:
    response = api.post(
        DOCS,
        data={"title": name},
        files={"file": (name + ".txt", f"# {name}\n\nPolicy text.\n".encode(), "text/plain")},
        headers=auth(user),
    )
    body: dict[str, Any] = ok(response, 201)
    return body


def test_app_role_sees_only_the_bound_tenants_documents(api, auth, db_session, world):  # noqa: F811
    alpha = _upload(api, auth, "alpha.admin", "Alpha policy")
    beta = _upload(api, auth, "beta.admin", "Beta policy")

    clear_tenant(db_session)
    assert db_session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0

    bind_tenant(db_session, world.users["alpha.admin"].tenant_id)
    alpha_ids = db_session.scalars(select(KnowledgeDocument.id)).all()
    assert alpha_ids == [__import__("uuid").UUID(alpha["id"])]

    bind_tenant(db_session, world.users["beta.admin"].tenant_id)
    beta_ids = db_session.scalars(select(KnowledgeDocument.id)).all()
    assert beta_ids == [__import__("uuid").UUID(beta["id"])]


def test_cross_tenant_api_access_is_404(api, auth):
    alpha = _upload(api, auth, "alpha.admin", "Alpha secret policy")
    response = api.get(f"{DOCS}/{alpha['id']}", headers=auth("beta.admin"))
    assert response.status_code == 404
