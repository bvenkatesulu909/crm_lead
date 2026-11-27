# ruff: noqa: F811 - the pytest fixture "world" is imported and then used as a parameter
"""The photo enhancer's request, worker and storage through the real database (ADR 0039, PE2).

People and records come from test_quotes_api.py: agent1 owns account A1 (and deal O1), agent2 owns
A2, tenant beta has B1. Files go to an in-memory store. Only the file store is replaced.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PIL import Image
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.core.db import bind_tenant
from app.core.errors import ForbiddenError
from app.core.outbox import Job, OutboxJob
from app.core.storage import MemoryFileStore
from app.modules.agents import api as agents_api
from app.modules.branding import api as branding_api
from app.modules.documents import api as documents_api
from app.modules.documents import service as documents_service
from app.modules.documents.models import Document
from app.modules.photo_enhancer import api as photo_api
from app.modules.photo_enhancer import rules, service
from app.modules.photo_enhancer.models import PhotoEnhancement
from app.worker import WorkerServices, dead_job_handlers, job_handlers
from tests.auth_helpers import TEST_ISSUER
from tests.conftest import UNREACHABLE_DATABASE_URL
from tests.db.conftest import bind_principal, forget_request_user
from tests.db.test_approvals import ROLES, alpha, principal_for
from tests.db.test_quotes_api import World, world  # noqa: F401 - fixture used by name


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=UNREACHABLE_DATABASE_URL,
        oidc_issuer=TEST_ISSUER,
        **overrides,
    )


def jpeg(size: tuple[int, int] = (400, 300), colour: tuple[int, int, int] = (50, 50, 50)) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "SecretPhoneMaker"
    exif[0x8825] = {1: "N", 2: (17.0, 22.0, 30.0), 3: "E", 4: (78.0, 29.0, 10.0)}
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def png(size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("L", size).save(out, format="PNG")
    return out.getvalue()


class Setup:
    def __init__(self, session: Session, world: World) -> None:
        self.session, self.world = session, world
        self.store = MemoryFileStore()
        self.config = settings()
        self.tenant_id = alpha(world)

    def principal(self, name: str):
        principal = principal_for(self.world.users[name], ROLES[name])
        bind_principal(self.session, principal)
        return principal

    def switch(self, on: bool = True) -> None:
        current = agents_api.effective(
            self.session,
            self.tenant_id,
            service.AGENT_KEY,
            agents_api.Limits.default(),
            datetime.now(UTC),
        )
        agents_api.update_settings(
            self.session,
            self.principal("alpha.admin"),
            service.AGENT_KEY,
            limits=agents_api.Limits.default(),
            now=datetime.now(UTC),
            version=current.version,
            enabled=on,
        )
        self.session.flush()

    def photo(
        self,
        *,
        user: str = "alpha.agent1",
        record: str = "A1",
        name: str = "living-room.jpg",
        data: bytes | None = None,
        customer_visible: bool = False,
    ) -> uuid.UUID:
        """An uploaded document (as the person), the way the documents module stores it."""
        body = jpeg() if data is None else data
        made = documents_service.upload(
            self.session,
            self.principal(user),
            self.store,
            record_type="account",
            record_id=self.world.ids[record],
            file_name=name,
            data=body,
            max_bytes=20 * 1024 * 1024,
            customer_visible=customer_visible,
            description=None,
        )
        return made.id

    def ask(
        self,
        photo_id: uuid.UUID,
        operations: dict[str, Any] | None = None,
        *,
        user: str = "alpha.agent1",
        config: Settings | None = None,
        now: datetime | None = None,
    ) -> PhotoEnhancement:
        row = service.request_enhancement(
            self.session,
            self.principal(user),
            photo_id,
            {"brightness_percent": 10} if operations is None else operations,
            config or self.config,
            now=now,
        )
        self.session.flush()
        return row

    def job_for(self, enhancement_id: uuid.UUID, *, attempt: int = 1) -> Job:
        bind_tenant(self.session, self.tenant_id)
        found = self.session.scalars(
            select(OutboxJob).where(OutboxJob.kind == photo_api.JOB_KIND)
        ).all()
        [job] = [j for j in found if j.payload["enhancement_id"] == str(enhancement_id)]
        return Job(job.id, job.tenant_id, job.kind, job.payload, attempt)

    def run(self, row: PhotoEnhancement, config: Settings | None = None) -> PhotoEnhancement:
        forget_request_user(self.session)
        bind_tenant(self.session, self.tenant_id)
        photo_api.job_handler(self.store, config or self.config)(self.session, self.job_for(row.id))
        self.session.flush()
        return self.reload(row.id)

    def reload(self, enhancement_id: uuid.UUID) -> PhotoEnhancement:
        bind_tenant(self.session, self.tenant_id)
        return self.session.scalars(
            select(PhotoEnhancement)
            .where(PhotoEnhancement.id == enhancement_id)
            .execution_options(populate_existing=True)
        ).one()

    def derived_documents(self) -> list[Document]:
        bind_tenant(self.session, self.tenant_id)
        return list(
            self.session.scalars(
                select(Document).where(Document.purpose == "property_photo_enhanced")
            ).all()
        )

    def audit_actions(self) -> list[str]:
        bind_tenant(self.session, self.tenant_id)
        return [a.action for a in self.session.scalars(select(AuditLog)).all()]


@pytest.fixture
def setup(db_session: Session, world: World) -> Setup:
    ready = Setup(db_session, world)
    ready.switch(True)
    return ready


# --- the happy path ---------------------------------------------------------------------------


def test_a_request_is_recorded_and_queues_one_job_with_ids_only(setup: Setup) -> None:
    photo_id = setup.photo()
    row = setup.ask(photo_id, {"brightness_percent": 12, "straighten_degrees": 1.5})
    assert (row.status, row.original_document_id, row.tool_version) == ("queued", photo_id, "pe1")
    assert row.operations["brightness_percent"] == 12  # exactly what was asked for
    assert row.derived_document_id is None
    [job] = setup.session.scalars(select(OutboxJob).where(OutboxJob.kind == photo_api.JOB_KIND))
    assert job.payload == {"enhancement_id": str(row.id)}
    assert "photo.enhancement_requested" in setup.audit_actions()


def test_the_worker_makes_a_clean_labelled_copy_and_leaves_the_original_alone(setup: Setup) -> None:
    original = jpeg()
    photo_id = setup.photo(data=original)
    row = setup.run(setup.ask(photo_id, {"brightness_percent": 20, "preset": "whatsapp"}))
    assert row.status == "ready" and row.failure_code is None
    assert row.derived_document_id is not None and row.applied is not None
    assert "Brightness +20 %" in row.applied
    assert (row.width, row.height) == (400, 300)  # never made bigger
    bind_tenant(setup.session, setup.tenant_id)
    # the original document and its bytes are untouched
    _, kept = documents_api.read_document(setup.session, setup.store, setup.tenant_id, photo_id)
    assert kept == original
    [copy] = setup.derived_documents()
    assert copy.id == row.derived_document_id
    assert (copy.purpose, copy.derived_from_id, copy.content_type) == (
        "property_photo_enhanced",
        photo_id,
        "image/jpeg",
    )
    assert copy.file_name == "living-room-enhanced.jpg"
    data = setup.store.get(copy.storage_key)
    assert b"SecretPhoneMaker" not in data  # the camera's details and GPS position are gone
    assert Image.open(io.BytesIO(data)).getexif().get(0x010E) == rules.FILE_LABEL
    assert row.size_bytes == len(data) == copy.size_bytes
    assert "photo.enhanced" in setup.audit_actions()


def test_the_audit_names_the_steps_and_never_the_picture_or_its_name(setup: Setup) -> None:
    photo_id = setup.photo(name="secret-villa-front.jpg")
    setup.run(setup.ask(photo_id))
    bind_tenant(setup.session, setup.tenant_id)
    entries = [a for a in setup.session.scalars(select(AuditLog)) if a.action.startswith("photo.")]
    assert {a.action for a in entries} >= {"photo.enhancement_requested", "photo.enhanced"}
    for entry in entries:
        assert "secret-villa" not in str(entry.changes)
        assert "SecretPhoneMaker" not in str(entry.changes)


def test_an_adjusted_copy_is_not_listed_as_an_ordinary_document(setup: Setup) -> None:
    photo_id = setup.photo()
    setup.run(setup.ask(photo_id))
    listed = documents_service.list_documents(
        setup.session, setup.principal("alpha.agent1"), "account", setup.world.ids["A1"]
    )
    assert [d.id for d in listed] == [photo_id]


def test_the_copy_follows_the_originals_customer_visibility(setup: Setup) -> None:
    visible = setup.run(setup.ask(setup.photo(name="a.jpg", customer_visible=True)))
    hidden = setup.run(setup.ask(setup.photo(name="b.jpg", customer_visible=False)))
    by_id = {d.id: d for d in setup.derived_documents()}
    assert by_id[cast(uuid.UUID, visible.derived_document_id)].customer_visible is True
    assert by_id[cast(uuid.UUID, hidden.derived_document_id)].customer_visible is False


def test_running_the_job_twice_makes_one_copy(setup: Setup) -> None:
    row = setup.run(setup.ask(setup.photo()))
    setup.run(row)
    assert len(setup.derived_documents()) == 1


def test_each_use_is_counted_in_the_months_usage(setup: Setup) -> None:
    setup.run(setup.ask(setup.photo()))
    state = agents_api.effective(
        setup.session,
        setup.tenant_id,
        service.AGENT_KEY,
        agents_api.Limits.default(),
        datetime.now(UTC),
    )
    assert state.used_tokens == 1


def test_a_logo_watermark_uses_the_organisations_logo(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    logo = io.BytesIO()
    Image.new("RGBA", (200, 200), (255, 255, 255, 255)).save(logo, format="PNG")
    asked: list[bytes | None] = []

    def fake_branding(session: Session, tenant_id: uuid.UUID) -> Any:
        asked.append(logo.getvalue())
        return branding_api.DeckBranding("1f3a5f", "", "", "", "", logo.getvalue(), 1)

    monkeypatch.setattr(
        "app.modules.photo_enhancer.service.branding_api.branding_for_deck", fake_branding
    )
    row = setup.run(setup.ask(setup.photo(), {"watermark": {"kind": "logo", "corner": "top_left"}}))
    assert row.status == "ready" and asked


# --- who may ask, and for which photo ---------------------------------------------------------


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_people_without_the_permission_are_refused(setup: Setup, user: str) -> None:
    photo_id = setup.photo()
    with pytest.raises(ForbiddenError):
        setup.ask(photo_id, user=user)
    assert setup.session.scalars(select(PhotoEnhancement)).first() is None


def test_a_manager_may_adjust_a_photo_on_an_agents_account(setup: Setup) -> None:
    photo_id = setup.photo(user="alpha.agent1")
    assert setup.ask(photo_id, user="alpha.manager").status == "queued"


def test_an_agent_cannot_adjust_a_photo_on_a_colleagues_account(setup: Setup) -> None:
    photo_id = setup.photo(user="alpha.agent1")
    with pytest.raises(service.PhotoNotFoundError):
        setup.ask(photo_id, user="alpha.agent2")


def test_another_organisation_cannot_see_the_photo(setup: Setup) -> None:
    photo_id = setup.photo()
    beta_admin = setup.principal(
        "beta.admin"
    )  # beta switches the feature on, so only the photo is in question
    beta_tenant = cast(uuid.UUID, beta_admin.tenant_id)
    limits = agents_api.Limits.default()
    current = agents_api.effective(
        setup.session, beta_tenant, service.AGENT_KEY, limits, datetime.now(UTC)
    )
    agents_api.update_settings(
        setup.session,
        beta_admin,
        service.AGENT_KEY,
        limits=limits,
        now=datetime.now(UTC),
        version=current.version,
        enabled=True,
    )
    setup.session.flush()
    with pytest.raises(service.PhotoNotFoundError):
        setup.ask(photo_id, user="beta.agent")


def test_a_made_up_id_is_not_found(setup: Setup) -> None:
    with pytest.raises(service.PhotoNotFoundError):
        setup.ask(uuid.uuid4())


def test_an_adjusted_copy_cannot_be_adjusted_again_by_its_id(setup: Setup) -> None:
    row = setup.run(setup.ask(setup.photo()))
    with pytest.raises(service.PhotoNotFoundError):
        setup.ask(cast(uuid.UUID, row.derived_document_id))


def test_a_file_that_is_not_a_photo_is_refused(setup: Setup) -> None:
    pdf = setup.photo(name="plan.pdf", data=b"%PDF-1.7 fictional")
    with pytest.raises(service.NotAPhotoError):
        setup.ask(pdf)


# --- the switches -----------------------------------------------------------------------------


def test_it_is_off_until_an_administrator_switches_it_on(db_session: Session, world: World) -> None:
    fresh = Setup(db_session, world)  # not switched on
    photo_id = fresh.photo()
    with pytest.raises(service.PhotoEnhancerUnavailableError):
        fresh.ask(photo_id)


def test_the_platform_switch_stops_requests(setup: Setup) -> None:
    photo_id = setup.photo()
    with pytest.raises(service.PhotoEnhancerUnavailableError):
        setup.ask(photo_id, config=settings(photo_enhancer_disabled=True))


def test_a_request_waiting_when_the_organisation_switches_it_off_fails_cleanly(
    setup: Setup,
) -> None:
    row = setup.ask(setup.photo())
    setup.switch(False)
    done = setup.run(row)
    assert (done.status, done.failure_code) == ("failed", "photo_enhancer_off")
    assert setup.derived_documents() == []


# --- what may be asked for --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operations", "code"),
    [
        ({"brightness_percent": 31}, "photo_operation_too_strong"),
        ({"straighten_degrees": 5.1}, "photo_operation_too_strong"),
        ({"crop": [0, 0, 0.5, 1]}, "photo_operation_too_strong"),
        ({"sky_replacement": True}, "photo_operation_unknown"),
        ({"remove_objects": ["wire"]}, "photo_operation_unknown"),
        ({"preset": "huge"}, "photo_preset_unknown"),
        ({"watermark": {"kind": "logo"}}, "photo_watermark_logo_missing"),
    ],
)
def test_a_request_above_a_cap_or_off_the_list_is_refused_and_nothing_is_queued(
    setup: Setup, operations: dict[str, Any], code: str
) -> None:
    photo_id = setup.photo()
    with pytest.raises(service.PhotoRequestError) as caught:
        setup.ask(photo_id, operations)
    assert caught.value.code == code
    assert (
        setup.session.scalars(select(OutboxJob).where(OutboxJob.kind == "photo.enhance")).first()
        is None
    )


# --- limits -----------------------------------------------------------------------------------


def test_a_photo_can_have_only_so_many_copies_and_a_failed_one_does_not_count(
    setup: Setup,
) -> None:
    config = settings(photo_enhancements_per_original=2)
    photo_id = setup.photo()
    first = setup.ask(photo_id, config=config)
    setup.ask(photo_id, config=config)
    with pytest.raises(service.PhotoLimitReachedError):
        setup.ask(photo_id, config=config)
    first.status, first.failure_code = "failed", "unreadable"
    setup.session.flush()
    assert setup.ask(photo_id, config=config).status == "queued"


def test_a_person_has_an_hourly_limit_and_the_organisation_a_daily_one(setup: Setup) -> None:
    photo_id = setup.photo()
    hourly = settings(photo_enhancements_per_user_hour=1, photo_enhancements_per_original=50)
    setup.ask(photo_id, config=hourly)
    with pytest.raises(service.PhotoLimitReachedError):
        setup.ask(photo_id, config=hourly)
    # another person is not held back by that person's hour...
    assert setup.ask(photo_id, user="alpha.manager", config=hourly).status == "queued"
    # ...but the organisation's day counts everybody
    daily = settings(photo_enhancements_per_tenant_day=2, photo_enhancements_per_original=50)
    with pytest.raises(service.PhotoLimitReachedError):
        setup.ask(photo_id, user="alpha.admin", config=daily)


def test_requests_older_than_the_window_do_not_count(setup: Setup) -> None:
    photo_id = setup.photo()
    config = settings(photo_enhancements_per_user_hour=1, photo_enhancements_per_original=50)
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    setup.ask(photo_id, config=config, now=long_ago)
    assert setup.ask(photo_id, config=config).status == "queued"


# --- what the worker refuses ------------------------------------------------------------------


def test_a_pixel_bomb_is_refused_by_the_worker_and_nothing_is_stored(setup: Setup) -> None:
    bomb = setup.photo(name="bomb.png", data=png((9000, 9000)))  # 81 megapixels in a tiny file
    row = setup.run(setup.ask(bomb))
    assert (row.status, row.failure_code) == ("failed", "too_large")
    assert row.derived_document_id is None and setup.derived_documents() == []


def test_a_photo_that_needs_too_much_memory_is_refused(setup: Setup) -> None:
    big = setup.photo(name="big.png", data=png((3000, 3000)))  # about 108 MB at 12 bytes a pixel
    row = setup.run(setup.ask(big), settings(photo_enhancer_max_memory_mb=50))
    assert (row.status, row.failure_code) == ("failed", "too_large")


def test_a_photo_that_takes_too_long_is_refused_without_a_half_made_copy(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([0.0] + [10_000.0] * 50)
    clock = SimpleNamespace(monotonic=lambda: next(ticks))
    monkeypatch.setattr("app.modules.photo_enhancer.rules.time", clock)
    monkeypatch.setattr("app.modules.photo_enhancer.service.time", clock)
    row = setup.run(setup.ask(setup.photo()))
    assert (row.status, row.failure_code) == ("failed", "took_too_long")
    assert setup.derived_documents() == []
    assert len(setup.store.objects) == 1  # only the original


def test_a_missing_original_file_fails_the_request(setup: Setup) -> None:
    photo_id = setup.photo()
    row = setup.ask(photo_id)
    setup.store.objects.clear()
    done = setup.run(row)
    assert (done.status, done.failure_code) == ("failed", "unreadable")


def test_a_failed_request_says_so_in_the_audit(setup: Setup) -> None:
    setup.run(setup.ask(setup.photo(name="bomb.png", data=png((9000, 9000)))))
    assert "photo.failed" in setup.audit_actions()


def test_when_the_retries_run_out_the_request_is_marked_failed(setup: Setup) -> None:
    row = setup.ask(setup.photo())
    job = setup.job_for(row.id, attempt=5)
    forget_request_user(setup.session)
    bind_tenant(setup.session, setup.tenant_id)
    photo_api.dead_job_handler()(setup.session, job, "boom")
    done = setup.reload(row.id)
    assert (done.status, done.failure_code) == ("failed", "processing_failed")


def test_the_worker_knows_the_job_and_its_dead_job_hook(db_connection: Connection) -> None:
    services = WorkerServices(settings(), MemoryFileStore(), cast(Any, None))
    assert photo_api.JOB_KIND in job_handlers(services)
    assert photo_api.JOB_KIND in dead_job_handlers()


# --- listing, links and deleting --------------------------------------------------------------


def test_requests_are_listed_for_whoever_may_read_the_photo(setup: Setup) -> None:
    photo_id = setup.photo()
    setup.run(setup.ask(photo_id))
    setup.ask(photo_id, {"contrast_percent": 5})
    listed = service.list_copies(setup.session, setup.principal("alpha.manager"), photo_id)
    assert [r.status for r in listed] == ["queued", "ready"]  # newest first
    with pytest.raises(service.PhotoNotFoundError):
        service.list_copies(setup.session, setup.principal("alpha.agent2"), photo_id)
    with pytest.raises(service.PhotoNotFoundError):
        service.list_copies(setup.session, setup.principal("beta.agent"), photo_id)


def test_a_finished_copy_has_a_signed_link_and_an_unfinished_one_does_not(setup: Setup) -> None:
    photo_id = setup.photo()
    ready = setup.run(setup.ask(photo_id))
    waiting = setup.ask(photo_id, {"contrast_percent": 5})
    link = service.copy_link(setup.session, setup.principal("alpha.agent1"), setup.store, ready.id)
    assert link.file_name == "living-room-enhanced.jpg"
    with pytest.raises(service.CopyNotFoundError):
        service.copy_link(setup.session, setup.principal("alpha.agent1"), setup.store, waiting.id)
    with pytest.raises(service.CopyNotFoundError):
        service.copy_link(setup.session, setup.principal("alpha.agent2"), setup.store, ready.id)
    with pytest.raises(service.CopyNotFoundError):
        service.copy_link(setup.session, setup.principal("beta.agent"), setup.store, ready.id)
    with pytest.raises(service.CopyNotFoundError):
        service.copy_link(setup.session, setup.principal("alpha.agent1"), setup.store, uuid.uuid4())


def test_deleting_a_copy_keeps_the_original(setup: Setup) -> None:
    photo_id = setup.photo()
    row = setup.run(setup.ask(photo_id))
    copy = setup.derived_documents()[0]
    key = service.delete_copy(setup.session, setup.principal("alpha.agent1"), row.id)
    assert key == copy.storage_key
    service.remove_file(setup.store, key)
    bind_tenant(setup.session, setup.tenant_id)
    assert setup.derived_documents() == []
    assert setup.session.scalars(select(PhotoEnhancement)).first() is None
    documents_api.read_document(setup.session, setup.store, setup.tenant_id, photo_id)
    assert copy.storage_key not in setup.store.objects
    assert "photo.copy_deleted" in setup.audit_actions()


def test_deleting_a_waiting_request_needs_no_file(setup: Setup) -> None:
    row = setup.ask(setup.photo())
    assert service.delete_copy(setup.session, setup.principal("alpha.agent1"), row.id) is None
    assert setup.session.scalars(select(PhotoEnhancement)).first() is None


def test_nobody_else_may_delete_a_copy(setup: Setup) -> None:
    row = setup.run(setup.ask(setup.photo()))
    with pytest.raises(service.CopyNotFoundError):
        service.delete_copy(setup.session, setup.principal("alpha.agent2"), row.id)
    with pytest.raises(service.CopyNotFoundError):
        service.delete_copy(setup.session, setup.principal("beta.agent"), row.id)
    with pytest.raises(ForbiddenError):
        service.delete_copy(setup.session, setup.principal("alpha.support"), row.id)


def test_deleting_the_original_deletes_its_copies_and_hands_back_their_files(
    setup: Setup,
) -> None:
    photo_id = setup.photo()
    row = setup.run(setup.ask(photo_id))
    copy = setup.derived_documents()[0]
    keys = documents_service.delete_document(
        setup.session, setup.principal("alpha.agent1"), photo_id
    )
    setup.session.flush()
    assert copy.storage_key in keys and len(keys) == 2
    bind_tenant(setup.session, setup.tenant_id)
    assert setup.derived_documents() == []
    assert (
        setup.session.scalars(select(PhotoEnhancement).where(PhotoEnhancement.id == row.id)).first()
        is None
    )


# --- tenant isolation of the table ------------------------------------------------------------


def test_another_organisation_cannot_read_the_table(setup: Setup) -> None:
    setup.ask(setup.photo())
    setup.principal("beta.agent")
    assert setup.session.scalars(select(PhotoEnhancement)).all() == []


# --- what the database itself refuses ---------------------------------------------------------


def _owner_insert(setup: Setup, sql: str, **values: Any) -> None:
    bind_tenant(setup.session, setup.tenant_id)
    with setup.session.begin_nested():
        setup.session.execute(text(sql), {"t": setup.tenant_id, **values})


def test_the_database_refuses_a_ready_row_without_a_copy(setup: Setup) -> None:
    photo_id = setup.photo()
    user_id = setup.world.users["alpha.agent1"].id
    with pytest.raises(IntegrityError):
        _owner_insert(
            setup,
            "insert into photo_enhancements (tenant_id, original_document_id, requested_by_user_id,"
            " status, operations, tool_version, width, height, size_bytes, applied)"
            " values (:t, :o, :u, 'ready', '{}'::jsonb, 'pe1', 1, 1, 1, '[]'::jsonb)",
            o=photo_id,
            u=user_id,
        )


def test_the_database_refuses_a_failed_row_without_a_reason(setup: Setup) -> None:
    photo_id = setup.photo()
    user_id = setup.world.users["alpha.agent1"].id
    with pytest.raises(IntegrityError):
        _owner_insert(
            setup,
            "insert into photo_enhancements (tenant_id, original_document_id, requested_by_user_id,"
            " status, operations, tool_version) values (:t, :o, :u, 'failed', '{}'::jsonb, 'pe1')",
            o=photo_id,
            u=user_id,
        )


def test_the_database_keeps_derived_purpose_and_original_together(setup: Setup) -> None:
    photo_id = setup.photo()
    base = (
        "insert into documents (tenant_id, record_type, record_id, purpose, file_name,"
        " content_type, size_bytes, sha256, storage_key, group_id, derived_from_id)"
        " values (:t, 'account', :r, :p, 'x.jpg', 'image/jpeg', 1, repeat('a', 64), :k,"
        " gen_random_uuid(), :d)"
    )
    record = setup.world.ids["A1"]
    with pytest.raises(IntegrityError):  # a copy without its original
        _owner_insert(setup, base, r=record, p="property_photo_enhanced", k="k1", d=None)
    with pytest.raises(IntegrityError):  # an ordinary document that claims an original
        _owner_insert(setup, base, r=record, p="attachment", k="k2", d=photo_id)
