"""Imports every module's models so ``Base.metadata`` knows all tables.

Used by Alembic (alembic/env.py) to compare models with the database. Add a line here
whenever a new module gets a models.py.
"""

from app.core import audit as audit_models
from app.core import heartbeat as heartbeat_models
from app.core import outbox as outbox_models
from app.core.models import Base
from app.modules.accounts import models as accounts_models
from app.modules.activities import models as activities_models
from app.modules.approvals import models as approvals_models
from app.modules.assistant import models as assistant_models
from app.modules.catalog import models as catalog_models
from app.modules.communications import models as communications_models
from app.modules.contacts import models as contacts_models
from app.modules.contracts import models as contracts_models
from app.modules.documents import models as documents_models
from app.modules.identity import models as identity_models
from app.modules.invoices import models as invoices_models
from app.modules.knowledge import models as knowledge_models
from app.modules.leads import models as leads_models
from app.modules.notifications import models as notifications_models
from app.modules.orders import models as orders_models
from app.modules.public_chat import models as public_chat_models
from app.modules.quotes import models as quotes_models
from app.modules.sales import models as sales_models
from app.modules.support import models as support_models
from app.modules.workflows import models as workflows_models

__all__ = [
    "Base",
    "accounts_models",
    "activities_models",
    "assistant_models",
    "audit_models",
    "heartbeat_models",
    "catalog_models",
    "approvals_models",
    "communications_models",
    "contacts_models",
    "contracts_models",
    "documents_models",
    "identity_models",
    "invoices_models",
    "knowledge_models",
    "leads_models",
    "notifications_models",
    "orders_models",
    "outbox_models",
    "public_chat_models",
    "quotes_models",
    "sales_models",
    "support_models",
    "workflows_models",
]

metadata = Base.metadata
