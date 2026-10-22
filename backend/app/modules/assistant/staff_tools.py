"""Staff assistant tools: typed, permission-checked, tenant-scoped, linked."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.accounts import api as accounts_api
from app.modules.contacts import api as contacts_api
from app.modules.leads import api as leads_api
from app.modules.support import api as support_api

MAX_RESULT_CHARS = 4_000
Outcome = Literal["ok", "not_found", "invalid", "error"]


@dataclass(frozen=True)
class StaffToolResult:
    outcome: Outcome
    content: str
    link: str | None = None

    @property
    def is_error(self) -> bool:
        return self.outcome != "ok"


def _json(data: Any) -> str:
    text = json.dumps(data, default=str, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = json.dumps({"truncated": True, "note": "Ask about one record."})
    return text


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TicketArgs(_Args):
    ticket_id: uuid.UUID = Field(description="The ticket UUID from the support page.")


class AccountArgs(_Args):
    account_id: uuid.UUID = Field(description="The account UUID.")


class SearchAccountsArgs(_Args):
    q: str = Field(min_length=1, max_length=100, description="Company name to search.")


class AccountContactsArgs(_Args):
    account_id: uuid.UUID = Field(description="The account UUID.")


class SearchLeadsArgs(_Args):
    q: str = Field(
        default="",
        max_length=100,
        description="Name/company/email fragment; empty = first visible leads.",
    )
    limit: int = Field(default=10, ge=1, le=50)


@dataclass(frozen=True)
class StaffTool:
    name: str
    description: str
    args: type[_Args]
    handler: Callable[[Session, Principal, _Args], StaffToolResult]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args.model_json_schema(),
        }


def _search_accounts(session: Session, principal: Principal, args: _Args) -> StaffToolResult:
    assert isinstance(args, SearchAccountsArgs)  # noqa: S101
    accounts = accounts_api.search_accounts(session, principal, q=args.q)
    for account in accounts:
        account["link"] = f"/accounts/{account['id']}"
    return StaffToolResult("ok", _json(accounts))


def _account_contacts(session: Session, principal: Principal, args: _Args) -> StaffToolResult:
    assert isinstance(args, AccountContactsArgs)  # noqa: S101
    if not accounts_api.is_readable_account(session, principal, args.account_id):
        return StaffToolResult("not_found", _json({"error": "Account not found."}))
    contacts = contacts_api.list_account_contacts(session, principal, args.account_id)
    return StaffToolResult("ok", _json(contacts), f"/accounts/{args.account_id}")


def _search_leads(session: Session, principal: Principal, args: _Args) -> StaffToolResult:
    assert isinstance(args, SearchLeadsArgs)  # noqa: S101
    leads = leads_api.search_leads(session, principal, q=args.q, limit=args.limit)
    return StaffToolResult("ok", _json(leads))


def _get_ticket(session: Session, principal: Principal, args: _Args) -> StaffToolResult:
    assert isinstance(args, TicketArgs)  # noqa: S101 - registry guarantees it
    facts = support_api.ticket_facts(session, principal, args.ticket_id)
    if facts is None:
        return StaffToolResult("not_found", _json({"error": "Ticket not found."}))
    return StaffToolResult(
        "ok",
        _json(
            {
                "label": facts.label,
                "record_type": facts.record_type,
                "values": facts.values,
                "account_id": str(facts.account_id) if facts.account_id else None,
            }
        ),
        facts.link,
    )


def _get_account(session: Session, principal: Principal, args: _Args) -> StaffToolResult:
    assert isinstance(args, AccountArgs)  # noqa: S101 - registry guarantees it
    if not accounts_api.is_readable_account(session, principal, args.account_id):
        return StaffToolResult("not_found", _json({"error": "Account not found."}))
    tenant_id = principal.tenant_id
    name = accounts_api.account_name(session, tenant_id, args.account_id) if tenant_id else None
    if name is None:
        return StaffToolResult("not_found", _json({"error": "Account not found."}))
    return StaffToolResult("ok", _json({"name": name}), f"/accounts/{args.account_id}")


TOOLS: dict[str, StaffTool] = {
    tool.name: tool
    for tool in (
        StaffTool(
            "get_ticket",
            "Read a support ticket the employee may see: status, priority, category and link.",
            TicketArgs,
            _get_ticket,
        ),
        StaffTool(
            "search_leads",
            "Search visible leads by name/company/email; returns names, companies, emails, "
            "status and links.",
            SearchLeadsArgs,
            _search_leads,
        ),
        StaffTool(
            "search_accounts",
            "Search accounts the employee may read by company name.",
            SearchAccountsArgs,
            _search_accounts,
        ),
        StaffTool(
            "list_account_contacts",
            "List contacts of an account the employee may read.",
            AccountContactsArgs,
            _account_contacts,
        ),
        StaffTool(
            "get_account",
            "Read an account the employee may see: name and link only.",
            AccountArgs,
            _get_account,
        ),
    )
}


def definitions() -> list[dict[str, Any]]:
    return [tool.definition() for tool in TOOLS.values()]


def execute(
    session: Session, principal: Principal, name: str, raw: dict[str, Any]
) -> StaffToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        return StaffToolResult("invalid", _json({"error": "Unknown tool."}))
    try:
        args = tool.args.model_validate(raw)
    except ValidationError:
        return StaffToolResult("invalid", _json({"error": "Invalid arguments."}))
    try:
        return tool.handler(session, principal, args)
    except Exception:  # noqa: BLE001 - tool failures are data, never 500s to the chat
        return StaffToolResult("error", _json({"error": "The tool failed."}))
