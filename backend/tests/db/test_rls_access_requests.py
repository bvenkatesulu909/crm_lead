"""ADR 0009: signup before a principal exists + RLS on access_requests."""

from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.auth.tokens import VerifiedToken
from app.core.db import bind_tenant
from app.modules.identity import onboarding
from app.modules.identity.models import AccessRequest, Tenant
from tests.auth_helpers import TEST_ISSUER
from tests.db.conftest import session_factory_for

CODE = "ABCD-EFGH-JKMN"


def _world(owner_db_session: Session, clean_committed_data: None) -> tuple[Tenant, Tenant]:
    alpha = Tenant(slug="signup-alpha", name="Signup Alpha", signup_code=CODE)
    beta = Tenant(slug="signup-beta", name="Signup Beta", signup_code="NPQR-STUV-WXYZ")
    owner_db_session.add_all([alpha, beta])
    owner_db_session.commit()
    return alpha, beta


def _token(token_factory: Any, subject: str = "signup-new") -> VerifiedToken:
    return cast(
        VerifiedToken,
        token_factory.verifier().verify(
            token_factory.mint(
                subject,
                [],
                email="signup@example.test",
                email_verified=True,
                name="Signup Person",
            ),
        ),
    )


def test_signup_works_without_a_tenant_setting(
    owner_db_session: Session,
    clean_committed_data: None,
    db_connection,
    token_factory,
) -> None:
    alpha, _beta = _world(owner_db_session, clean_committed_data)
    session = session_factory_for(db_connection)()
    try:
        state = onboarding.onboarding_status(session, _token(token_factory))
        assert state.state == "none"
        result = onboarding.submit_access_request(session, _token(token_factory), CODE)
        assert result.state == "pending"
        assert result.organisation_name == "Signup Alpha"
        bind_tenant(session, alpha.id)
        request = session.scalars(
            select(AccessRequest).where(AccessRequest.idp_subject == "signup-new")
        ).one()
        assert request.tenant_id == alpha.id
    finally:
        session.close()


def test_anonymous_connection_cannot_read_access_requests(
    owner_db_session: Session, clean_committed_data: None, db_connection
) -> None:
    alpha, _beta = _world(owner_db_session, clean_committed_data)
    owner_db_session.add(
        AccessRequest(
            tenant_id=alpha.id,
            idp_issuer=TEST_ISSUER,
            idp_subject="signup-existing",
            email="existing@example.test",
            display_name="Existing",
        )
    )
    owner_db_session.commit()
    session = session_factory_for(db_connection)()
    try:
        assert session.scalars(select(AccessRequest)).all() == []
        with __import__("pytest").raises(DBAPIError):
            session.execute(
                text(
                    "INSERT INTO access_requests "
                    "(tenant_id, idp_issuer, idp_subject, email, display_name) "
                    "VALUES (:t, :i, :s, :e, :n)"
                ),
                {
                    "t": alpha.id,
                    "i": TEST_ISSUER,
                    "s": "direct-insert",
                    "e": "direct@example.test",
                    "n": "Direct",
                },
            )
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_access_requests_follow_tenant_isolation(
    owner_db_session: Session, clean_committed_data: None, db_connection
) -> None:
    alpha, beta = _world(owner_db_session, clean_committed_data)
    for tenant, subject in ((alpha, "request-alpha"), (beta, "request-beta")):
        owner_db_session.add(
            AccessRequest(
                tenant_id=tenant.id,
                idp_issuer=TEST_ISSUER,
                idp_subject=subject,
                email=f"{subject}@example.test",
                display_name=subject,
            )
        )
    owner_db_session.commit()
    session = session_factory_for(db_connection)()
    try:
        bind_tenant(session, alpha.id)
        assert {r.idp_subject for r in session.scalars(select(AccessRequest))} == {"request-alpha"}
        bind_tenant(session, beta.id)
        assert {r.idp_subject for r in session.scalars(select(AccessRequest))} == {"request-beta"}
    finally:
        session.close()


def test_signup_functions_are_narrow_and_not_public(
    owner_db_session: Session, clean_committed_data: None, db_connection
) -> None:
    alpha, _beta = _world(owner_db_session, clean_committed_data)
    session = session_factory_for(db_connection)()
    try:
        rows = (
            session.execute(
                text("SELECT status, tenant_id FROM access_request_latest(:i, :s)"),
                {"i": TEST_ISSUER, "s": "nobody"},
            )
            .mappings()
            .all()
        )
        assert rows == []
        submitted = session.execute(
            text("SELECT request_id, tenant_id FROM access_request_submit(:i, :s, :e, :n, :c)"),
            {
                "i": TEST_ISSUER,
                "s": "function-signup",
                "e": "function@example.test",
                "n": "Function Signup",
                "c": "WRONG-CODE-XXXX",
            },
        ).all()
        assert submitted == []
        public_latest = session.scalar(
            text(
                "SELECT has_function_privilege('public', "
                "'access_request_latest(text,text)', 'EXECUTE')"
            )
        )
        public_submit = session.scalar(
            text(
                "SELECT has_function_privilege('public', "
                "'access_request_submit(text,text,text,text,text)', 'EXECUTE')"
            )
        )
        assert public_latest is False
        assert public_submit is False
        assert alpha.id is not None
    finally:
        session.close()
