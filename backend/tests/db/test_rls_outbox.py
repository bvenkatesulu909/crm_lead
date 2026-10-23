"""ADR 0009: worker claims jobs across tenants, then binds the job's tenant."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import bind_tenant
from app.core.outbox import Job, OutboxJob, enqueue, run_next_job
from app.modules.identity.models import Tenant, User
from tests.auth_helpers import TEST_ISSUER
from tests.db.conftest import session_factory_for

NOW = datetime.now(UTC)


def _world(owner_db_session: Session, clean_committed_data: None) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for key in ("alpha", "beta"):
        tenant = Tenant(slug=f"outbox-rls-{key}", name=f"Outbox {key.title()}")
        owner_db_session.add(tenant)
        owner_db_session.flush()
        user = User(
            tenant_id=tenant.id,
            idp_issuer=TEST_ISSUER,
            idp_subject=f"outbox-{key}-user",
            email=f"outbox-{key}@example.test",
            display_name=f"Outbox {key.title()} User",
            user_type="staff",
            roles=["support_agent"],
        )
        owner_db_session.add(user)
        owner_db_session.flush()
        job = enqueue(
            owner_db_session,
            tenant_id=tenant.id,
            kind="test.ping",
            payload={"tenant": key},
            run_after=NOW - timedelta(seconds=1),
        )
        ids[f"{key}_tenant"] = tenant.id
        ids[f"{key}_user"] = user.id
        ids[f"{key}_job"] = job.id
    owner_db_session.commit()
    return ids


def test_two_tenants_jobs_are_claimed_and_run_under_their_tenant(
    owner_db_session: Session,
    clean_committed_data: None,
    db_connection: Connection,
) -> None:
    ids = _world(owner_db_session, clean_committed_data)
    factory: sessionmaker[Session] = session_factory_for(db_connection)
    seen: list[uuid.UUID] = []

    def handler(session: Session, job: Job) -> None:
        seen.append(job.tenant_id)
        own_user, other_user = (
            (ids["alpha_user"], ids["beta_user"])
            if job.tenant_id == ids["alpha_tenant"]
            else (ids["beta_user"], ids["alpha_user"])
        )
        assert session.get(User, own_user) is not None
        assert session.get(User, other_user) is None

    for _ in range(2):
        assert run_next_job(factory, {"test.ping": handler}, max_attempts=3) is not None
    assert run_next_job(factory, {"test.ping": handler}, max_attempts=3) is None
    assert set(seen) == {ids["alpha_tenant"], ids["beta_tenant"]}

    for key in ("alpha", "beta"):
        with factory() as check, check.begin():
            bind_tenant(check, ids[f"{key}_tenant"])
            job = check.get(OutboxJob, ids[f"{key}_job"])
            assert job is not None
            assert job.status == "done"


def test_outbox_claim_function_is_not_public(
    owner_db_session: Session, clean_committed_data: None, db_connection: Connection
) -> None:
    _world(owner_db_session, clean_committed_data)
    factory = session_factory_for(db_connection)
    with factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT has_function_privilege('public', "
                    "'outbox_claim(timestamptz,timestamptz)', 'EXECUTE')"
                )
            )
            is False
        )
