"""Record-level authorization for knowledge documents (RAG R1).

Staff only; every row of the caller's tenant. A later RAG step may add per-collection access, but
the tenant filter here is the boundary that must never be skipped.
"""

from sqlalchemy import ColumnElement, false

from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.modules.knowledge.models import KnowledgeDocument


def readable_documents(principal: Principal) -> ColumnElement[bool]:
    if principal.tenant_id is None or principal.user_type != "staff":
        return false()
    if not principal.has_permission(Permission.KNOWLEDGE_READ):
        return false()
    return KnowledgeDocument.tenant_id == principal.tenant_id
