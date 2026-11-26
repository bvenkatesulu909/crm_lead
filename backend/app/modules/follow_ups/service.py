"""The follow-up scan (ADR 0036, step FM4): finds leads whose follow-up task falls due today and
makes ONE draft e-mail for each, as a proposal in the approval queue.

Nothing here sends anything. A person (the lead's owner, or a manager) reads the draft and
approves it; only then does the normal e-mail path run, with its consent, address and hourly-limit
checks. What may be drafted at all is decided by the pure rules in
``communications/follow_up_rules.py``; this module only reads the facts those rules need from the
modules that own them, and acts on the answer.

The scan runs as the organisation's Automation identity (the same one the Qualifier uses): it may
read leads and propose, nothing else. It is safe to run again at once: a lead that already has a
waiting draft, or had one within the cooldown, is skipped.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.modules.activities import api as activities_api
from app.modules.approvals import api as approvals_api
from app.modules.communications import api as communications_api
from app.modules.communications.api import follow_up_rules as rules
from app.modules.identity import api as identity_api
from app.modules.leads import api as leads_api

logger = logging.getLogger(__name__)

# Drafts made per organisation per run. A run happens about once a minute, so this is a speed
# limit, not a daily one (the policy's daily cap is the daily one).
SCAN_BATCH = 50
# Due tasks looked at per run. The cap keeps one very busy day from loading everything.
MAX_CANDIDATES = 500
KIND = "communication.send_follow_up"
AGENT = "follow_up"
REASON_TEXT = "A follow-up task for this lead is due today."


@dataclass
class ScanResult:
    made: int = 0
    # Why candidates were passed over: reason code -> how many (codes only, never names).
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, code: str) -> None:
        self.skipped[code] = self.skipped.get(code, 0) + 1


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _draft(
    session: Session,
    automation: Principal,
    policy: rules.Policy,
    now: datetime,
    lead_id: uuid.UUID,
    facts: leads_api.FollowUpFacts,
) -> str | None:
    """Fill the template and propose it. Returns None when a draft was made, else a skip code."""
    if policy.template_id is None or facts.owner_id is None:
        return "no_template"
    tenant_id = automation.tenant_id
    if tenant_id is None:  # an Automation identity always has one
        return "refused"
    owner = identity_api.staff_principal(session, tenant_id, facts.owner_id)
    if owner is None:
        return "owner_inactive"  # the owner left; the lead needs reassigning, not an e-mail
    rendered = communications_api.render_follow_up(
        session,
        automation,
        policy.template_id,
        first_name=facts.first_name,
        full_name=facts.full_name,
        company=facts.company,
        sender_name=owner.display_name,
        sender_email=owner.email,
    )
    if rendered is None:
        return "template_unusable"
    subject, body = rendered
    try:
        # A savepoint: a refused proposal leaves nothing behind.
        with session.begin_nested():
            approvals_api.propose(
                session,
                automation,
                kind=KIND,
                target_type="lead",
                target_id=lead_id,
                payload={
                    "reason_code": rules.RULE_TASK_DUE_TODAY,
                    "subject": subject,
                    "body": body,
                    "template_id": str(policy.template_id),
                },
                reason=REASON_TEXT,
                agent=AGENT,
                expires_in_days=policy.expiry_days,
                # One Automation identity asks for the whole organisation, so the per-person
                # allowances are widened to the policy's own daily and waiting caps.
                pending_limit=policy.daily_cap * policy.expiry_days,
                sentinel_limits=approvals_api.SentinelLimits(policy.daily_cap, 3, 3),
            )
    except approvals_api.ProposalBlockedError as refusal:
        # Outside the savepoint, so the audit entry of the refusal stays.
        approvals_api.audit_blocked(session, automation, refusal)
        return "blocked"
    except (approvals_api.InvalidActionError, approvals_api.LimitReachedError):
        return "refused"
    return None


def scan(
    session: Session,
    now: datetime,
    *,
    tenant_id: uuid.UUID,
    platform_enabled: bool = True,
    batch: int = SCAN_BATCH,
) -> ScanResult:
    """One pass for one organisation. Returns what was made and why others were passed over."""
    result = ScanResult()
    policy = communications_api.follow_up_policy(session, tenant_id)
    if not platform_enabled or not policy.enabled:
        return result
    automation = identity_api.automation_principal(session, tenant_id)
    reader = automation.user_id
    if reader is None:  # an Automation identity always has one
        return result
    # The leads policy hides every lead from a session without a user: read as Automation.
    identity_api.bind_reader(session, automation)
    start, end = _day_bounds(now)
    tasks = activities_api.due_lead_tasks(session, tenant_id, start, end, MAX_CANDIDATES)
    drafts_today = approvals_api.follow_up_drafts_today(session, tenant_id, start)
    seen: set[uuid.UUID] = set()
    for task in tasks:
        if result.made >= batch:
            break
        if task.lead_id in seen:  # two due tasks on one lead make one draft, not two
            continue
        seen.add(task.lead_id)
        facts = leads_api.follow_up_facts(session, tenant_id, task.lead_id, reader_user_id=reader)
        if facts is None:
            result.skip("lead_missing")
            continue
        history = approvals_api.follow_up_history(
            session, tenant_id, task.lead_id, now - timedelta(days=rules.MONTH_DAYS)
        )
        waiting_for_owner = (
            approvals_api.follow_up_waiting_for(
                session, tenant_id, leads_api.lead_ids_of_owner(tenant_id, facts.owner_id)
            )
            if facts.owner_id is not None
            else 0
        )
        decision = rules.evaluate(
            policy,
            rules.Facts(
                now=now,
                platform_enabled=platform_enabled,
                target_type="lead",
                consent=facts.consent,
                has_address=facts.has_address,
                lead_status=facts.status,
                # They filled in the website form or chat, or wrote to us: a service follow-up.
                started_by_person=facts.source == "web"
                or communications_api.inbound_logged_since(session, tenant_id, task.lead_id, None),
                has_owner=facts.owner_id is not None,
                reply_after_trigger=communications_api.inbound_logged_since(
                    session, tenant_id, task.lead_id, task.created_at
                ),
                draft_waiting=history.waiting,
                last_draft_at=history.last_at,
                drafts_last_30_days=history.in_window,
                drafts_today=drafts_today,
                waiting_for_owner=waiting_for_owner,
            ),
        )
        if not decision.allowed:
            for code in decision.reasons:
                result.skip(code)
            continue
        problem = _draft(session, automation, policy, now, task.lead_id, facts)
        if problem is not None:
            result.skip(problem)
            continue
        result.made += 1
        drafts_today += 1
    if result.made or result.skipped:
        # Codes and counts only: never a name, an address or any text.
        logger.info(
            "follow-up scan",
            extra={"made": result.made, "skipped": dict(result.skipped)},
        )
    return result
