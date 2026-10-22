"""Owner test-bootstrap connection is privileged; runtime app role is not."""

from sqlalchemy import text


def test_owner_setup_session_is_bypassrls(owner_db_session):
    assert owner_db_session.scalar(text("select current_user")) == "crm_owner"
    assert owner_db_session.scalar(
        text("select rolbypassrls from pg_roles where rolname = current_user")
    ) is True


def test_app_runtime_session_is_restricted(db_session):
    assert db_session.scalar(text("select current_user")) == "crm_app"
    assert db_session.scalar(
        text("select rolbypassrls from pg_roles where rolname = current_user")
    ) is False
