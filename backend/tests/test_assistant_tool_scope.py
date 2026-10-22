"""Customer assistant tool-scope and internal-data tests."""

import pytest
from pydantic import ValidationError

from app.core.errors import ForbiddenError
from app.modules.assistant import tools
from app.modules.assistant.tools import QuoteArgs
from app.modules.catalog import api as catalog_api
from app.modules.contacts import api as contacts_api
from app.modules.quotes import api as quotes_api
from app.modules.quotes.schemas import PortalQuoteRead


class Customer:
    user_type = "customer"
    permissions: frozenset[str] = frozenset()
    tenant_id = None

    def has_permission(self, permission: str) -> bool:
        return False


def test_internal_lead_report_user_tools_are_absent():
    names = set(tools.TOOLS)
    forbidden = ("lead", "report", "admin", "user", "workflow", "document")
    for name in names:
        assert not any(word in name.lower() for word in forbidden), name


def test_quote_tools_reject_unexpected_arguments():
    with pytest.raises(ValidationError):
        QuoteArgs.model_validate(
            {"quote_id": "00000000-0000-0000-0000-000000000000", "tenant_id": "x"}
        )


def test_non_customers_cannot_call_customer_quote_product_or_contact_apis():
    principal = Customer()
    with pytest.raises(ForbiddenError):
        quotes_api.customer_quotes(object(), principal)  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        quotes_api.customer_quote(object(), principal, __import__("uuid").uuid4())  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        catalog_api.customer_products(object(), principal)  # type: ignore[arg-type]
    with pytest.raises(ForbiddenError):
        contacts_api.customer_contacts(object(), principal)  # type: ignore[arg-type]


def test_portal_quote_does_not_expose_internal_fields():
    fields = set(PortalQuoteRead.model_fields)
    assert "internal_note" not in fields
    assert "owner_id" not in fields
    assert "needs_approval" not in fields
    assert "created_by_user_id" not in fields
    assert "approved_by_user_id" not in fields
