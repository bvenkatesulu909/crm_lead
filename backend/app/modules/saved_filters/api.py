"""Public interface of the saved filters module. Other modules import only this.

The batch research of ADR 0042 reads a saved filter's parameters through ``filter_params``; the
person's own read rules still decide which accounts the filter finds.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.saved_filters import service
from app.modules.saved_filters.service import SavedFilterNotFoundError

__all__ = ["SavedFilterNotFoundError", "filter_params"]


def filter_params(session: Session, principal: Principal, filter_id: uuid.UUID) -> dict[str, str]:
    """The parameters of a filter the person may use (their own or a shared one), else 404."""
    return dict(service.get_filter(session, principal, filter_id).params)
