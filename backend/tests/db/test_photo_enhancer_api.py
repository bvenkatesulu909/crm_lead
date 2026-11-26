# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""The photo enhancer's API (ADR 0039, PE3) through the real database and the in-memory file store.

People and records come from test_quotes_api.py: agent1 owns account A1, agent2 owns A2, tenant beta
has B1. The photo is uploaded through the documents API, the job is run by the real handler.
"""

import io
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.core.db import bind_tenant
from app.core.outbox import Job, OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.photo_enhancer import api as photo_api
from app.modules.photo_enhancer import rules
from app.modules.photo_enhancer.models import PhotoEnhancement
from tests.db.test_documents_api import files, listing, upload  # noqa: F401 - fixtures used by name
from tests.db.test_photo_enhancer import jpeg
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    Headers,
    World,
    api,
    auth,
    code_of,
    ok,
    world,
)

BASE = "/api/v1/photo-enhancer"


@pytest.fixture
def settings_override(api: TestClient):  # noqa: ANN201
    original = api.app.state.settings  # type: ignore[attr-defined]

    def change(**values: Any) -> None:
        api.app.state.settings = original.model_copy(update=values)  # type: ignore[attr-defined]

    yield change
    api.app.state.settings = original  # type: ignore[attr-defined]


def switch(api: TestClient, auth: Headers, on: bool = True, admin: str = "alpha.admin") -> None:
    url = "/api/v1/agents/photo_enhancer"
    current = api.get(url, headers=auth(admin)).json()
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    response = api.patch(url, json=body, headers=auth(admin))
    assert response.status_code == 200, response.text


@pytest.fixture
def on(api: TestClient, auth: Headers, world: World) -> None:
    switch(api, auth)


def photo(api: TestClient, auth: Headers, world: World, user: str = "alpha.agent1") -> str:
    made = upload(
        api, auth, world, user=user, name="living-room.jpg", data=jpeg(), mime="image/jpeg"
    )
    return str(ok(made, 201)["id"])


def ask(
    api: TestClient,
    auth: Headers,
    document_id: str,
    operations: dict[str, Any] | None = None,
    user: str = "alpha.agent1",
    path: str = "/enhancements",
) -> Any:
    return api.post(
        BASE + path,
        json={
            "document_id": document_id,
            "operations": {"brightness_percent": 10} if operations is None else operations,
        },
        headers=auth(user),
    )


def items(api: TestClient, auth: Headers, doc: str, user: str = "alpha.agent1") -> Any:
    return api.get(BASE + "/enhancements", params={"document_id": doc}, headers=auth(user))


def on_copy(
    api: TestClient, auth: Headers, method: str, enhancement_id: str, user: str, tail: str = ""
) -> Any:
    return api.request(method, f"{BASE}/enhancements/{enhancement_id}{tail}", headers=auth(user))


def run_job(api: TestClient, world: World, files: MemoryFileStore, enhancement_id: str) -> None:
    """The worker's handler, on the same database the API uses."""
    tenant_id = world.users["alpha.agent1"].tenant_id
    factory = api.app.state.session_factory  # type: ignore[attr-defined]
    with factory() as session:
        bind_tenant(session, tenant_id)
        [job] = [
            j
            for j in session.scalars(select(OutboxJob).where(OutboxJob.kind == photo_api.JOB_KIND))
            if j.payload["enhancement_id"] == enhancement_id
        ]
        handler = photo_api.job_handler(files, api.app.state.settings)  # type: ignore[attr-defined]
        handler(session, Job(job.id, job.tenant_id, job.kind, job.payload, 1))
        session.commit()


# --- preview -----------------------------------------------------------------------------------


def test_a_preview_is_a_small_jpeg_and_stores_nothing(api, auth, world, files, on) -> None:
    large = upload(api, auth, world, name="large.jpg", data=jpeg((1600, 1200)), mime="image/jpeg")
    doc = str(ok(large, 201)["id"])
    objects_before = len(files.objects)
    response = ask(api, auth, doc, {"brightness_percent": 20}, path="/previews")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    picture = Image.open(io.BytesIO(response.content))
    assert picture.format == "JPEG" and max(picture.size) <= rules.PREVIEW_SIDE
    assert len(files.objects) == objects_before  # nothing was stored
    assert (
        ok(
            api.get(
                BASE + "/enhancements", params={"document_id": doc}, headers=auth("alpha.agent1")
            )
        )["items"]
        == []
    )


def test_a_preview_follows_the_same_rules_as_a_request(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    assert code_of(ask(api, auth, doc, {"brightness_percent": 99}, path="/previews")) == (
        422,
        "photo_operation_too_strong",
    )
    assert code_of(ask(api, auth, doc, {"sky_replacement": True}, path="/previews")) == (
        422,
        "photo_operation_unknown",
    )
    assert ask(api, auth, doc, user="alpha.agent2", path="/previews").status_code == 404
    assert ask(api, auth, doc, user="alpha.support", path="/previews").status_code == 403
    assert ask(api, auth, str(uuid.uuid4()), path="/previews").status_code == 404


def test_previews_are_limited_per_person(api, auth, world, files, on, settings_override) -> None:
    doc = photo(api, auth, world)
    settings_override(photo_previews_per_minute=1)
    assert ask(api, auth, doc, path="/previews").status_code == 200
    assert code_of(ask(api, auth, doc, path="/previews")) == (429, "photo_limit_reached")


def test_a_photo_too_big_for_the_memory_cap_gets_no_preview(
    api, auth, world, files, on, settings_override
) -> None:
    big = io.BytesIO()
    Image.new("L", (3000, 3000)).save(big, format="PNG")  # about 108 MB at 12 bytes a pixel
    made = upload(api, auth, world, name="big.png", data=big.getvalue(), mime="image/png")
    settings_override(photo_enhancer_max_memory_mb=50)
    assert code_of(ask(api, auth, ok(made, 201)["id"], path="/previews")) == (
        422,
        "photo_too_large",
    )


# --- asking for a copy ---------------------------------------------------------------------------


def test_asking_queues_a_copy_and_tells_the_state(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    row = ok(ask(api, auth, doc, {"brightness_percent": 12, "preset": "whatsapp"}), 201)
    assert row["status"] == "queued" and row["original_document_id"] == doc
    assert row["operations"]["brightness_percent"] == 12 and row["applied"] is None
    assert row["failure_code"] is None and row["width"] is None
    assert "tenant_id" not in row and "requested_by_user_id" not in row


def test_the_client_cannot_choose_the_server_controlled_fields(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    for extra in (
        {"status": "ready"},
        {"tenant_id": str(uuid.uuid4())},
        {"derived_document_id": doc},
    ):
        response = api.post(
            BASE + "/enhancements",
            json={"document_id": doc, "operations": {}, **extra},
            headers=auth("alpha.agent1"),
        )
        assert response.status_code == 422


def test_what_is_refused_is_refused_with_a_stable_code(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    assert code_of(ask(api, auth, doc, {"straighten_degrees": 9})) == (
        422,
        "photo_operation_too_strong",
    )
    assert code_of(ask(api, auth, doc, {"watermark": {"kind": "logo"}})) == (
        422,
        "photo_watermark_logo_missing",
    )
    pdf = ok(upload(api, auth, world, name="plan.pdf"), 201)["id"]
    assert code_of(ask(api, auth, pdf)) == (422, "photo_not_an_image")


def test_it_is_unavailable_until_switched_on_and_by_the_platform_switch(
    api, auth, world, files, settings_override
) -> None:
    doc = photo(api, auth, world)
    assert code_of(ask(api, auth, doc)) == (503, "photo_enhancer_unavailable")
    switch(api, auth)
    assert ask(api, auth, doc).status_code == 201
    settings_override(photo_enhancer_disabled=True)
    assert code_of(ask(api, auth, doc)) == (503, "photo_enhancer_unavailable")


def test_roles_and_isolation(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    assert ask(api, auth, doc, user="alpha.manager").status_code == 201
    assert ask(api, auth, doc, user="alpha.support").status_code == 403
    assert ask(api, auth, doc, user="alpha.customer").status_code == 403
    assert ask(api, auth, doc, user="alpha.agent2").status_code == 404  # record-level denial
    switch(api, auth, admin="beta.admin")  # beta has it on too, so only the photo is in question
    assert ask(api, auth, doc, user="beta.agent").status_code == 404  # another organisation
    assert api.post(BASE + "/enhancements", json={"document_id": doc}).status_code == 401


def test_the_limits_answer_429(api, auth, world, files, on, settings_override) -> None:
    doc = photo(api, auth, world)
    settings_override(photo_enhancements_per_original=1)
    assert ask(api, auth, doc).status_code == 201
    assert code_of(ask(api, auth, doc)) == (429, "photo_limit_reached")


# --- listing, link, delete ------------------------------------------------------------------


def test_the_whole_journey_ask_work_list_download_delete(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    asked = ok(ask(api, auth, doc, {"brightness_percent": 15}), 201)
    run_job(api, world, files, asked["id"])

    page = ok(items(api, auth, doc))
    assert page["caption"] == "Photo adjusted for brightness and colour"
    [item] = page["items"]
    assert item["status"] == "ready" and item["applied"][0] == "Brightness +15 %"
    assert item["width"] == 400 and item["size_bytes"] > 0

    link = ok(on_copy(api, auth, "GET", asked["id"], "alpha.agent1", "/link"))
    assert link["file_name"] == "living-room-enhanced.jpg" and link["url"]

    # the adjusted copy never shows up among the ordinary documents; the original is untouched
    assert [d["id"] for d in ok(listing(api, auth, world))["items"]] == [doc]

    assert on_copy(api, auth, "DELETE", asked["id"], "alpha.agent1").status_code == 204
    assert (
        ok(
            api.get(
                BASE + "/enhancements", params={"document_id": doc}, headers=auth("alpha.agent1")
            )
        )["items"]
        == []
    )
    assert (
        api.get(f"/api/v1/documents/{doc}/download", headers=auth("alpha.agent1")).status_code
        == 200
    )
    assert len(files.objects) == 1  # only the original is left in the store


def test_other_people_cannot_list_link_or_delete(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    asked = ok(ask(api, auth, doc), 201)
    run_job(api, world, files, asked["id"])
    switch(api, auth, admin="beta.admin")
    for user in ("alpha.agent2", "beta.agent"):
        assert (
            api.get(
                BASE + "/enhancements", params={"document_id": doc}, headers=auth(user)
            ).status_code
            == 404
        )
        assert on_copy(api, auth, "GET", asked["id"], user, "/link").status_code == 404
        assert on_copy(api, auth, "DELETE", asked["id"], user).status_code == 404
    assert on_copy(api, auth, "DELETE", asked["id"], "alpha.support").status_code == 403
    assert (
        api.get(
            f"{BASE}/enhancements/{uuid.uuid4()}/link", headers=auth("alpha.agent1")
        ).status_code
        == 404
    )


def test_a_waiting_copy_has_no_link(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    asked = ok(ask(api, auth, doc), 201)
    assert on_copy(api, auth, "GET", asked["id"], "alpha.agent1", "/link").status_code == 404


def test_the_request_is_kept_as_asked_even_when_the_job_fails(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    asked = ok(ask(api, auth, doc, {"brightness_percent": 5}), 201)
    files.objects.clear()  # the original's file vanished from the store
    run_job(api, world, files, asked["id"])
    [item] = ok(items(api, auth, doc))["items"]
    assert (item["status"], item["failure_code"]) == ("failed", "unreadable")
    assert item["operations"]["brightness_percent"] == 5 and item["applied"] is None


def test_the_enhancements_rows_belong_to_the_organisation(api, auth, world, files, on) -> None:
    doc = photo(api, auth, world)
    ok(ask(api, auth, doc), 201)
    factory = api.app.state.session_factory
    with factory() as session:
        bind_tenant(session, world.users["beta.agent"].tenant_id)
        assert session.scalars(select(PhotoEnhancement)).all() == []
