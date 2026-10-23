"""ADR 0009: identity lookup before the tenant is known + RLS on users."""

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.tokens import VerifiedToken
from app.core.db import bind_tenant
from app.modules.identity.models import Tenant, User
from app.modules.identity.service import resolve_principal
from tests.auth_helpers import TEST_ISSUER
from tests.db.conftest import session_factory_for


def _world(owner_db_session: Session, clean_committed_data: None) -> tuple[Tenant, Tenant, User]:
    alpha = Tenant(slug="identity-alpha", name="Identity Alpha")
    beta = Tenant(slug="identity-beta", name="Identity Beta")
    owner_db_session.add_all([alpha, beta])
    owner_db_session.flush()
    user = User(
        tenant_id=alpha.id,
        idp_issuer=TEST_ISSUER,
        idp_subject="identity-alpha-user",
        email="identity-alpha@example.test",
        display_name="Alpha User",
        user_type="staff",
        roles=["support_agent"],
    )
    owner_db_session.add(user)
    owner_db_session.commit()
    return alpha, beta, user


def test_login_lookup_then_normal_user_load(
    owner_db_session: Session,
    clean_committed_data: None,
    db_connection: Connection,
    token_factory,
) -> None:
    alpha, _beta, user = _world(owner_db_session, clean_committed_data)
    token: VerifiedToken = token_factory.verifier().verify(
        token_factory.mint("identity-alpha-user", ["support_agent"])
    )
    session = session_factory_for(db_connection)()
    try:
        principal = resolve_principal(session, token)
        assert isinstance(principal, Principal)
        assert principal.user_id == user.id
        assert principal.tenant_id == alpha.id
    finally:
        session.close()


def test_users_rls_cannot_read_another_tenant(
    owner_db_session: Session, clean_committed_data: None, db_connection: Connection
) -> None:
    alpha, beta, user = _world(owner_db_session, clean_committed_data)
    session = session_factory_for(db_connection)()
    try:
        bind_tenant(session, beta.id)
        assert session.get(User, user.id) is None
        assert session.scalars(select(User).where(User.id == user.id)).first() is None
    finally:
        session.close()


def test_identity_function_is_narrow_and_not_public(
    owner_db_session: Session, clean_committed_data: None, db_connection: Connection
) -> None:
    alpha, _beta, user = _world(owner_db_session, clean_committed_data)
    session = session_factory_for(db_connection)()
    try:
        rows = (
            session.execute(
                text(
                    "SELECT user_id, tenant_id, is_active "
                    "FROM identity_lookup_user(:issuer, :subject)"
                ),
                {"issuer": TEST_ISSUER, "subject": user.idp_subject or ""},
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1
        assert rows[0]["user_id"] == user.id
        assert rows[0]["tenant_id"] == alpha.id
        assert rows[0]["is_active"] is True
        no_rows = session.execute(
            text("SELECT user_id FROM identity_lookup_user(:issuer, :subject)"),
            {"issuer": TEST_ISSUER, "subject": "nobody"},
        ).all()
        assert no_rows == []
        public_execute = session.scalar(
            text(
                "SELECT has_function_privilege('public', "
                "'identity_lookup_user(text,text)', 'EXECUTE')"
            )
        )
        assert public_execute is False
    finally:
        session.close()
