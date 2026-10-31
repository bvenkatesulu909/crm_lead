"""Staff assistant tools: typed, permission-checked, tenant-scoped, linked.

Reading tools return records the employee may see. Proposing tools (ADR 0014) only create a
PENDING proposal in the approval queue - nothing in the CRM changes until a different person
approves it.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import DomainError, NotFoundError
from app.core.screening import clean_records
from app.modules.accounts import api as accounts_api
from app.modules.approvals import api as approvals_api
from app.modules.contacts import api as contacts_api
from app.modules.leads import api as leads_api
from app.modules.support import api as support_api
from app.modules.webcheck import api as webcheck_api

MAX_RESULT_CHARS = 4_000
Outcome = Literal["ok", "not_found", "invalid", "error"]


# At most this many proposals per question: a looping or steered model can't fill the queue.
MAX_PROPOSALS_PER_ANSWER = 3


@dataclass(frozen=True)
class ProposalRef:
    id: uuid.UUID
    description: str
    status: str
    link: str


@dataclass(frozen=True)
class StaffToolResult:
    outcome: Outcome
    content: str
    link: str | None = None
    proposal: ProposalRef | None = None

    @property
    def is_error(self) -> bool:
        return self.outcome != "ok"


def _json(data: Any) -> str:
    cleaned, _ = clean_records(data)  # record text is untrusted (ADR 0017)
    text = json.dumps(cleaned, default=str, ensure_ascii=False)
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


Reason = Field(
    min_length=1,
    max_length=500,
    description="Why you propose this, in one or two sentences, for the approving manager.",
)


class CheckRegistrationArgs(_Args):
    record_type: Literal["lead", "account"] = Field(description="What the lookup is about.")
    record_id: uuid.UUID = Field(description="The lead or account (from search results).")
    source_key: str = Field(
        min_length=1,
        max_length=60,
        description="Where to look: one of the web check sources named in the instructions.",
    )
    query: str = Field(
        min_length=1,
        max_length=200,
        description="The RERA number or the company name to look up. Nothing else.",
    )


class ProposeLeadStatusArgs(_Args):
    lead_id: uuid.UUID = Field(description="The lead UUID (from search_leads).")
    status: Literal["contacted", "qualified", "unqualified"]
    reason: str = Reason


class ProposeLeadAssignmentArgs(_Args):
    lead_id: uuid.UUID = Field(description="The lead UUID (from search_leads).")
    owner_id: uuid.UUID = Field(description="The sales person who should own the lead.")
    reason: str = Reason


class ProposeFollowUpTaskArgs(_Args):
    record_type: Literal["lead", "account", "contact"]
    record_id: uuid.UUID = Field(description="The UUID of that lead, account or contact.")
    subject: str = Field(min_length=3, max_length=200)
    due_in_days: int = Field(ge=0, le=60)
    assignee_id: uuid.UUID | None = Field(
        default=None, description="Who should do it; empty = the employee asking."
    )
    reason: str = Reason


@dataclass
class ProposalBudget:
    """Settings and bookkeeping for one question: what was proposed, and how much more may be."""

    expiry_days: int = 7
    pending_limit: int = 20
    sentinel: approvals_api.SentinelLimits | None = None
    # The application settings, for tools that need them (the web check's switches and limits).
    settings: Settings | None = None
    made: list[ProposalRef] = field(default_factory=list)


@dataclass(frozen=True)
class StaffTool:
    name: str
    description: str
    args: type[_Args]
    handler: Callable[[Session, Principal, _Args], StaffToolResult] | None = None
    # Proposing tools: (kind, target type or None = from the arguments, target id field, payload)
    proposes: Callable[[_Args], tuple[str, str, uuid.UUID, dict[str, Any]]] | None = None
    # Tools that DO something small for the person (queue a lookup) and need the context.
    acts: Callable[[Session, Principal, _Args, ProposalBudget], StaffToolResult] | None = None

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


def _status_proposal(args: _Args) -> tuple[str, str, uuid.UUID, dict[str, Any]]:
    assert isinstance(args, ProposeLeadStatusArgs)  # noqa: S101 - registry guarantees it
    return "lead.set_status", "lead", args.lead_id, {"status": args.status}


def _assignment_proposal(args: _Args) -> tuple[str, str, uuid.UUID, dict[str, Any]]:
    assert isinstance(args, ProposeLeadAssignmentArgs)  # noqa: S101 - registry guarantees it
    return "lead.assign", "lead", args.lead_id, {"owner_id": str(args.owner_id)}


def _task_proposal(args: _Args) -> tuple[str, str, uuid.UUID, dict[str, Any]]:
    assert isinstance(args, ProposeFollowUpTaskArgs)  # noqa: S101 - registry guarantees it
    payload: dict[str, Any] = {"subject": args.subject, "due_in_days": args.due_in_days}
    if args.assignee_id is not None:
        payload["assignee_id"] = str(args.assignee_id)
    return "activity.create_task", args.record_type, args.record_id, payload


def _propose(
    session: Session,
    principal: Principal,
    tool: StaffTool,
    args: _Args,
    budget: ProposalBudget | None,
) -> StaffToolResult:
    if budget is None or tool.proposes is None:
        return StaffToolResult("invalid", _json({"error": "Proposals are not available here."}))
    if len(budget.made) >= MAX_PROPOSALS_PER_ANSWER:
        return StaffToolResult(
            "invalid",
            _json({"error": f"At most {MAX_PROPOSALS_PER_ANSWER} proposals per question."}),
        )
    kind, target_type, target_id, payload = tool.proposes(args)
    try:
        # A savepoint: a refused proposal leaves nothing behind.
        with session.begin_nested():
            action = approvals_api.propose(
                session,
                principal,
                kind=kind,
                target_type=target_type,
                target_id=target_id,
                payload=payload,
                reason=getattr(args, "reason", ""),
                agent="staff_assistant",
                expires_in_days=budget.expiry_days,
                pending_limit=budget.pending_limit,
                sentinel_limits=budget.sentinel,
            )
    except approvals_api.ProposalBlockedError as exc:
        # Outside the savepoint, so the audit entry of the refusal is kept with the request.
        approvals_api.audit_blocked(session, principal, exc)
        return StaffToolResult("invalid", _json({"error": exc.detail}))
    except NotFoundError:
        return StaffToolResult("not_found", _json({"error": "Record not found."}))
    except DomainError as exc:
        return StaffToolResult("invalid", _json({"error": exc.detail}))
    ref = ProposalRef(
        id=action.id,
        description=approvals_api.describe(action),
        status=action.status,
        link=f"/approvals/{action.id}",
    )
    budget.made.append(ref)
    return StaffToolResult(
        "ok",
        _json(
            {
                "proposal_id": str(ref.id),
                "status": ref.status,
                "description": ref.description,
                "note": "Waiting for approval by a manager. Nothing has changed yet - never say "
                "it was done.",
            }
        ),
        ref.link,
        ref,
    )


def _check_registration(
    session: Session, principal: Principal, args: _Args, context: ProposalBudget
) -> StaffToolResult:
    """Queue a web check as the signed-in person (ADR 0019). Nothing is looked up yet and the
    model never sees a page: the result appears on the record and the person is told."""
    assert isinstance(args, CheckRegistrationArgs)  # noqa: S101
    if context.settings is None:
        return StaffToolResult("error", _json({"error": "The web check is not available here."}))
    try:
        asked = webcheck_api.request_check(
            session,
            principal,
            target_type=args.record_type,
            target_id=args.record_id,
            source_key=args.source_key,
            query=args.query,
            settings=context.settings,
        )
    except DomainError as exc:
        outcome: Outcome = "not_found" if exc.status_code == 404 else "invalid"
        return StaffToolResult(outcome, _json({"error": exc.detail}))
    path = "leads" if args.record_type == "lead" else "accounts"
    return StaffToolResult(
        "ok",
        _json(
            {
                "queued": True,
                "request_id": str(asked.request_id),
                "note": "The lookup runs in the background. Nothing has been found yet: the "
                "result will appear on the record and the employee will be notified. Never "
                "state a result.",
            }
        ),
        f"/{path}/{args.record_id}",
    )


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
        StaffTool(
            "check_rera",
            "Queue a lookup of a RERA number or a company on a public registry for a lead or "
            "account the employee may read. Only when the employee asks. You see no result: it "
            "appears on the record and the employee is notified.",
            CheckRegistrationArgs,
            acts=_check_registration,
        ),
        StaffTool(
            "propose_lead_status",
            "PROPOSE changing a lead's status. Creates a proposal a manager must approve; "
            "nothing changes until then. Only when the employee asks for it.",
            ProposeLeadStatusArgs,
            proposes=_status_proposal,
        ),
        StaffTool(
            "propose_lead_assignment",
            "PROPOSE giving a lead to another sales person. A manager must approve it.",
            ProposeLeadAssignmentArgs,
            proposes=_assignment_proposal,
        ),
        StaffTool(
            "propose_follow_up_task",
            "PROPOSE a follow-up task on a lead, account or contact. A manager must approve it.",
            ProposeFollowUpTaskArgs,
            proposes=_task_proposal,
        ),
    )
}


def _act(
    session: Session, principal: Principal, tool: StaffTool, args: _Args, context: ProposalBudget
) -> StaffToolResult:
    assert tool.acts is not None  # noqa: S101
    try:
        return tool.acts(session, principal, args, context)
    except Exception:  # noqa: BLE001 - tool failures are data, never 500s to the chat
        return StaffToolResult("error", _json({"error": "The tool failed."}))


def definitions() -> list[dict[str, Any]]:
    return [tool.definition() for tool in TOOLS.values()]


def execute(
    session: Session,
    principal: Principal,
    name: str,
    raw: dict[str, Any],
    budget: ProposalBudget | None = None,
) -> StaffToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        return StaffToolResult("invalid", _json({"error": "Unknown tool."}))
    try:
        args = tool.args.model_validate(raw)
    except ValidationError:
        return StaffToolResult("invalid", _json({"error": "Invalid arguments."}))
    if tool.proposes is not None:
        return _propose(session, principal, tool, args, budget)
    if tool.acts is not None:
        return _act(session, principal, tool, args, budget or ProposalBudget())
    if tool.handler is None:
        return StaffToolResult("invalid", _json({"error": "Unknown tool."}))
    try:
        return tool.handler(session, principal, args)
    except Exception:  # noqa: BLE001 - tool failures are data, never 500s to the chat
        return StaffToolResult("error", _json({"error": "The tool failed."}))
