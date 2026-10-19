"""Who may see a document: whoever may see the record it belongs to.

The documents module doesn't decide that itself - it asks the owning module (accounts, sales)
through their api.py, so documents always follow the same tenant, role and ownership rules
as the record. Customers only ever see documents of their own accounts that staff marked
"visible to the customer".
"""

import uuid

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.accounts import api as accounts_api
from app.modules.sales import api as sales_api


def record_visible(
    session: Session, principal: Principal, record_type: str, record_id: uuid.UUID
) -> bool:
    if record_type == "account":
        return accounts_api.is_readable_account(session, principal, record_id)
    if record_type == "opportunity":
        visible, _ = sales_api.opportunity_account_id(session, principal, record_id)
        return visible
    return False  # quote PDFs are served by the quotes module, other types don't exist
