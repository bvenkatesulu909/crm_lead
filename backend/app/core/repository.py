"""The tenant-scoped repository base class.

Every module repository receives a Session and the authenticated Principal. This class puts the
tenant boundary in ONE place: every query built here is restricted to the caller's tenant, and
every inserted row is attached to it. The tenant always comes from the Principal - which is built
from the verified token and the CRM user record - never from a request parameter or header.

The class is deliberately small and plain SQLAlchemy. A module repository may subclass it and add
its own query methods, or a function-based repository may create one per call. Record-level
business rules (own/all/team/customer grants) stay in the module's policies.py; this layer only
guarantees that no query can escape its tenant.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.errors import ForbiddenError, NotFoundError


class TenantScopedRepository:
    """Tenant-safe query primitives for one request.

    The session is the request's Session (one transaction, committed by the router) and the
    principal is the caller established by the server.
    """

    def __init__(self, session: Session, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    @property
    def tenant_id(self) -> uuid.UUID:
        """The caller's tenant, or 403 for platform users (they belong to no tenant)."""
        if self.principal.tenant_id is None:
            raise ForbiddenError("This action requires a user inside a tenant.")
        return self.principal.tenant_id

    # "Any" below is intentional: this layer is generic over module models, and app.core may not
    # import business modules (enforced by import-linter).
    def scoped_select(self, model: type[Any]) -> Select[Any]:
        """A SELECT of the model restricted to the caller's tenant."""
        return select(model).where(model.tenant_id == self.tenant_id)

    def scope(self, statement: Select[Any], model: type[Any]) -> Select[Any]:
        """Add the caller's tenant to an existing SELECT of the model."""
        return statement.where(model.tenant_id == self.tenant_id)

    def get_or_none(
        self,
        model: type[Any],
        record_id: uuid.UUID,
        *conditions: ColumnElement[bool],
    ) -> Any | None:
        """The tenant's row with this id that also matches the module's policy, or None.

        None means "does not exist OR not allowed" - callers turn it into 404, so an
        unauthorized id looks exactly like an unknown one.
        """
        statement = self.scoped_select(model).where(model.id == record_id, *conditions)
        return self.session.scalars(statement).one_or_none()

    def get_or_404(
        self,
        model: type[Any],
        record_id: uuid.UUID,
        *conditions: ColumnElement[bool],
    ) -> Any:
        """Like get_or_none, but raises the standard 404 instead of returning None."""
        record = self.get_or_none(model, record_id, *conditions)
        if record is None:
            raise NotFoundError(f"{model.__name__} not found.")
        return record

    def add(self, entity: Any) -> Any:
        """Add a new row in the caller's tenant; refuse a row that names another tenant."""
        current = getattr(entity, "tenant_id", None)
        if current is None:
            entity.tenant_id = self.tenant_id
        elif current != self.tenant_id:
            raise ForbiddenError("A record can only be created in the caller's tenant.")
        self.session.add(entity)
        return entity
