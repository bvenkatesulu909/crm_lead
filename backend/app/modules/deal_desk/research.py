"""Account research: a one-page brief about one account (ADR 0024, step DD4).

    permission ─► limits ─► account readable? (else 404, no model) ─► registry
    ─► four gatherers (sales, service, conversations, registry) ─► writer (governed model)
    ─► sentences without a gathered source removed ─► brief stored (insert-only) ─► audit

It reads only, through the other modules' api.py and AS THE PERSON ASKING. It proposes nothing,
does not browse the internet and starts no web check (it shows the checks already on file).

The gatherers are independent of each other, but they read through ONE database session, which
must not be shared between threads; database reads take milliseconds, so they run one after the
other. The slow part - the model - is a single call. (The deal desk's three reviewers, which are
model calls, do run in parallel threads.)
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog, record_audit
from app.core.auth.principal import Principal
from app.core.auth.rbac import Permission
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError, NotFoundError
from app.modules.accounts import api as accounts_api
from app.modules.agents import api as agents_api
from app.modules.assistant.api import ChatModel
from app.modules.contracts import api as contracts_api
from app.modules.deal_desk import research_rules as rules
from app.modules.deal_desk.models import AccountBrief
from app.modules.orders import api as orders_api
from app.modules.relationships import api as relationships_api
from app.modules.sales import api as sales_api
from app.modules.support import api as support_api
from app.modules.webcheck import api as webcheck_api

AGENT = "account_research"
AUDIT_ACTION = "account_research.written"
ASK = "Write the brief and call the tool exactly once."
RETENTION = timedelta(days=365)  # the database enforces the same figure (migration 0053)
LIST_LIMIT = 20


class AccountNotFoundError(NotFoundError):
    code = "account_not_found"

    def __init__(self) -> None:
        super().__init__("Account not found.")


class ResearchRateLimitedError(DomainError):
    status_code = 429
    code = "account_research_rate_limited"


class ResearchInvalidError(DomainError):
    status_code = 422
    code = "account_research_invalid_answer"


@dataclass(frozen=True)
class Limits:
    per_account_hour: int
    per_tenant_day: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "Limits":
        return cls(
            settings.account_research_per_account_hour, settings.account_research_per_tenant_day
        )

    @classmethod
    def default(cls) -> "Limits":
        fields = Settings.model_fields
        return cls(
            int(fields["account_research_per_account_hour"].default),
            int(fields["account_research_per_tenant_day"].default),
        )


def _asker(principal: Principal) -> tuple[uuid.UUID, uuid.UUID]:
    if (
        principal.tenant_id is None
        or principal.user_id is None
        or principal.user_type != "staff"
        or not principal.has_permission(Permission.ACCOUNT_RESEARCH_RUN)
    ):
        raise ForbiddenError("You may not do this.")
    return principal.tenant_id, principal.user_id


def count_runs(
    session: Session, tenant_id: uuid.UUID, since: datetime, account_id: uuid.UUID | None = None
) -> int:
    query = select(func.count()).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.action == AUDIT_ACTION,
        AuditLog.occurred_at >= since,
    )
    if account_id is not None:
        query = query.where(AuditLog.entity_id == account_id)
    return int(session.scalar(query) or 0)


def gather(
    session: Session, principal: Principal, account_id: uuid.UUID, now: datetime
) -> list[rules.GatheredFact]:
    """The four gatherers, each reading through its module's api.py as the person asking. The
    account must already be known to be readable."""
    tenant_id = principal.tenant_id
    assert tenant_id is not None  # noqa: S101 - checked by _asker
    found = relationships_api.account_health(session, principal, account_id)
    health = rules.HealthRow(
        score=found.score,
        label=found.label,
        factors=tuple(factor.label for factor in found.factors),
        last_interaction_at=found.last_interaction_at,
        days_inactive=found.days_inactive,
        lifetime=tuple((m.currency, m.amount) for m in found.lifetime_value),
    )
    deals = [
        rules.DealRow(d.id, d.name, d.stage, d.amount, d.currency)
        for d in sales_api.account_deals(session, principal, account_id)
    ]
    last_order = orders_api.last_order_by_account(session, tenant_id, [account_id]).get(account_id)
    signals = support_api.ticket_signals_by_account(session, tenant_id, [account_id]).get(
        account_id, support_api.TicketSignals()
    )
    tickets = rules.TicketRow(
        signals.open,
        signals.sla_overdue,
        signals.open_complaints,
        signals.average_rating,
        signals.ratings,
    )
    renewal_found = contracts_api.next_renewal(session, principal, account_id)
    renewal = rules.RenewalRow(*renewal_found) if renewal_found else None
    evidence = webcheck_api.evidence_summary(session, principal, "account", account_id)
    return [
        *rules.sales_facts(account_id, deals, health, last_order),
        *rules.service_facts(account_id, tickets, renewal, now.date()),
        *rules.conversation_facts(account_id, health),
        *rules.registry_facts(account_id, evidence),
    ]


def run_research(
    session: Session,
    principal: Principal,
    model: ChatModel,
    account_id: uuid.UUID,
    *,
    limits: Limits | None = None,
    ai_limits: agents_api.Limits | None = None,
    now: datetime | None = None,
) -> AccountBrief:
    tenant_id, user_id = _asker(principal)
    when = now or datetime.now(UTC)
    gate = ai_limits or agents_api.Limits.default()
    caps = limits or Limits.default()
    if (
        count_runs(session, tenant_id, when - timedelta(hours=1), account_id)
        >= caps.per_account_hour
    ):
        raise ResearchRateLimitedError("This account was researched a moment ago. Try again later.")
    if count_runs(session, tenant_id, when - timedelta(days=1)) >= caps.per_tenant_day:
        raise ResearchRateLimitedError(
            "Your organisation reached its daily limit for account research."
        )
    if not accounts_api.is_readable_account(session, principal, account_id):
        raise AccountNotFoundError()
    if not model.available:
        model.reply(system="", messages=[], tools=[])  # raises "not configured"
    governed = agents_api.governed(model, session, tenant_id, AGENT, gate)
    governed.precheck()  # switched off or over budget: refused before any gathering

    gathered = gather(session, principal, account_id, when)
    reply = governed.reply(
        system=rules.prompt(gathered),
        messages=[{"role": "user", "content": ASK}],
        tools=[rules.tool()],
    )
    try:
        brief = rules.parse(reply.tool_uses, gathered)
    except rules.BriefRefusedError as refusal:
        raise ResearchInvalidError(str(refusal)) from None
    if not brief.sentences:
        raise ResearchInvalidError("No sentence of the brief named a source it was given.")
    counts = {name: sum(1 for g in gathered if g.gatherer == name) for name in rules.GATHERERS}
    usage = reply.usage or {}
    stored = AccountBrief(
        tenant_id=tenant_id,
        account_id=account_id,
        requested_by_user_id=user_id,
        sentences=[s.as_json() for s in brief.sentences],
        dropped=brief.dropped,
        gathered=counts,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
    )
    session.add(stored)
    session.flush()
    record_audit(
        session,
        principal,
        action=AUDIT_ACTION,
        entity_type="account",
        entity_id=account_id,
        changes={
            "brief_id": str(stored.id),
            "sentences": len(brief.sentences),
            "dropped": brief.dropped,
        },
    )
    session.flush()  # the limits count the audit rows
    return stored


def list_briefs(
    session: Session, principal: Principal, account_id: uuid.UUID
) -> list[AccountBrief]:
    """The briefs of an account, newest first, for someone who may read the account."""
    if principal.tenant_id is None or principal.user_type != "staff":
        raise AccountNotFoundError()
    if not accounts_api.is_readable_account(session, principal, account_id):
        raise AccountNotFoundError()
    return list(
        session.scalars(
            select(AccountBrief)
            .where(
                AccountBrief.tenant_id == principal.tenant_id,
                AccountBrief.account_id == account_id,
            )
            .order_by(AccountBrief.seq.desc())
            .limit(LIST_LIMIT)
        )
    )


def delete_expired(session: Session, now: datetime, *, tenant_id: uuid.UUID) -> int:
    result = session.execute(
        delete(AccountBrief).where(
            AccountBrief.tenant_id == tenant_id, AccountBrief.created_at < now - RETENTION
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
