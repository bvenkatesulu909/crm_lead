"""Unit tests for the tenant-scoped repository base (no database needed).

The class only builds SQLAlchemy statements and delegates to the Session, so a small fake Session
is enough. Real database behaviour (tenant isolation end to end) stays covered by tests/db/.
"""

import uuid
from typing import Any, cast

import pytest
from sqlalchemy import String, Uuid, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.auth.principal import Principal, UserType
from app.core.errors import ForbiddenError, NotFoundError
from app.core.repository import TenantScopedRepository

TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000a")
OTHER_TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000b")


class _WidgetBase(DeclarativeBase):
    """Private metadata for test-only models.

    Deliberately NOT the app's Base: tests/db/test_migrations.py autogenerates against
    Base.metadata, so a throwaway table there would look like a missing migration.
    """


class Widget(_WidgetBase):
    """A throwaway model: the base class is generic over real module models."""

    __tablename__ = "test_repository_widgets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(50))


def staff(tenant_id: uuid.UUID | None = TENANT) -> Principal:
    user_type: UserType = "staff" if tenant_id is not None else "platform"
    return Principal(
        subject="subject",
        issuer="issuer",
        user_type=user_type,
        roles=frozenset(),
        permissions=frozenset(),
        tenant_id=tenant_id,
    )


class _FakeScalars:
    def __init__(self, value: Any) -> None:
        self.value = value

    def one_or_none(self) -> Any:
        return self.value


class _FakeSession:
    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.statement: Any = None
        self.added: list[Any] = []

    def scalars(self, statement: Any) -> _FakeScalars:
        self.statement = statement
        return _FakeScalars(self.value)

    def add(self, entity: Any) -> None:
        self.added.append(entity)


def repository(
    tenant_id: uuid.UUID | None = TENANT, value: Any = None
) -> tuple[TenantScopedRepository, _FakeSession]:
    fake = _FakeSession(value)
    return TenantScopedRepository(cast(Session, fake), staff(tenant_id)), fake


def test_scoped_select_adds_the_tenant_condition() -> None:
    scoped, _ = repository()
    compiled = scoped.scoped_select(Widget).compile()
    assert "test_repository_widgets.tenant_id" in str(compiled)
    assert TENANT in compiled.params.values()


def test_scope_adds_the_tenant_condition_to_an_existing_statement() -> None:
    scoped, _ = repository()
    compiled = scoped.scope(select(Widget), Widget).compile()
    assert "test_repository_widgets.tenant_id" in str(compiled)


def test_platform_user_cannot_query_tenant_data() -> None:
    scoped, _ = repository(tenant_id=None)
    with pytest.raises(ForbiddenError):
        scoped.scoped_select(Widget)


def test_get_or_none_combines_tenant_id_and_policy() -> None:
    widget = Widget()
    scoped, fake = repository(value=widget)
    assert scoped.get_or_none(Widget, uuid.uuid4(), Widget.name == "Acme") is widget
    compiled = fake.statement.compile()
    assert TENANT in compiled.params.values()
    assert "name" in str(compiled)


def test_get_or_404_raises_the_standard_error() -> None:
    scoped, _ = repository(value=None)
    with pytest.raises(NotFoundError):
        scoped.get_or_404(Widget, uuid.uuid4())


def test_add_attaches_the_callers_tenant() -> None:
    scoped, fake = repository()
    widget = Widget()
    scoped.add(widget)
    assert widget.tenant_id == TENANT
    assert fake.added == [widget]


def test_add_refuses_a_row_for_another_tenant() -> None:
    scoped, fake = repository()
    widget = Widget(tenant_id=OTHER_TENANT)
    with pytest.raises(ForbiddenError):
        scoped.add(widget)
    assert fake.added == []
