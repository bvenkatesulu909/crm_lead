"""Pure rules for automatic follow-up drafts (ADR 0036, step FM3). No database, no clock of its own.

Two questions, both answered by code and never by a model:

1. *Is a follow-up due?*  The fixed menu of rules (``RULES``). In v1 there is one:
   ``task_due_today`` - a follow-up task on a lead became due today and is not done.
2. *May a draft be made now?*  ``evaluate`` runs every stop condition against facts the scan reads
   from the database (step FM4) and returns every reason that says no. Nothing here sends
   anything: a draft is only a proposal in the approval queue (step FM2).

The organisation's settings (``Policy``) can only be tightened inside the bounds below; the
database repeats the bounds as checks, so a bug here cannot store a wider one.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

RULE_TASK_DUE_TODAY = "task_due_today"


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    description: str


# The fixed menu. A new rule is an amendment to ADR 0036 and a code change, never a setting.
RULES: dict[str, Rule] = {
    RULE_TASK_DUE_TODAY: Rule(
        RULE_TASK_DUE_TODAY,
        "A follow-up task is due today",
        "A task on a lead that is due today and not done yet.",
    )
}

# (lowest, highest) allowed value of each number in the policy.
BOUNDS: dict[str, tuple[int, int]] = {
    "monthly_cap": (1, 8),  # follow-ups per person in 30 days; an administrator can never exceed 8
    "daily_cap": (1, 100),  # drafts per organisation per day (ADR 0036 answer 10: 100)
    "pending_cap": (1, 20),  # drafts waiting for one owner
    "expiry_days": (1, 30),  # a waiting draft expires after this many days
    "cooldown_days": (1, 60),  # no second draft of the same rule for the same person within this
}
MONTH_DAYS = 30

CLOSED_LEAD_STATUSES = frozenset({"converted", "unqualified"})


@dataclass(frozen=True)
class Policy:
    """An organisation's settings. Off until an administrator switches it on."""

    enabled: bool = False
    monthly_cap: int = 3
    daily_cap: int = 100
    pending_cap: int = 20
    expiry_days: int = 7
    cooldown_days: int = 7
    # The e-mail template the rule fills in (None: the rule cannot make drafts yet).
    template_id: uuid.UUID | None = None

    def problems(self) -> list[str]:
        """Which numbers are outside their bounds (names only, never values)."""
        found = []
        for name, (low, high) in BOUNDS.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                found.append(name)
        return found


@dataclass(frozen=True)
class Facts:
    """What the scan read about one candidate. Counts are for the organisation's own rows."""

    now: datetime
    platform_enabled: bool = True  # not switched off by CRM_FOLLOW_UPS_DISABLED
    target_type: str = "lead"
    consent: str = "unknown"  # unknown / granted / withdrawn
    has_address: bool = True
    lead_status: str | None = None  # None for a contact
    # The person started the conversation (filled in the form, wrote to us, asked for a quote).
    started_by_person: bool = False
    has_owner: bool = True
    reply_after_trigger: bool = False  # a received e-mail was logged after the task was set
    draft_waiting: bool = False  # an undecided draft for this person already exists
    last_draft_at: datetime | None = None  # newest draft of THIS rule for this person
    drafts_last_30_days: int = 0  # this person, all rules
    drafts_today: int = 0  # the organisation, all people
    waiting_for_owner: int = 0  # undecided drafts for this owner


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reasons: list[str]


def is_task_due_today(due_at: datetime, done: bool, now: datetime) -> bool:
    """The task is not done and falls due on today's date (UTC in v1; an organisation time zone
    is a later step). An overdue task is not chased by this rule: it was due on another day."""
    return not done and due_at.date() == now.date()


# The reason codes, in the order they are reported.
REASONS = (
    "platform_off",
    "switched_off",
    "unknown_rule",
    "no_template",
    "bad_policy",
    "consent_withdrawn",
    "consent_unknown",
    "no_address",
    "no_owner",
    "lead_closed",
    "reply_received",
    "draft_waiting",
    "cooldown",
    "monthly_cap",
    "daily_cap",
    "owner_pending_cap",
)


def evaluate(policy: Policy, facts: Facts, rule_key: str = RULE_TASK_DUE_TODAY) -> Decision:
    """May a draft be made now? ``allowed`` only when no reason says no; every reason is listed."""
    reasons: list[str] = []
    if not facts.platform_enabled:
        reasons.append("platform_off")
    if not policy.enabled:
        reasons.append("switched_off")
    if rule_key not in RULES:
        reasons.append("unknown_rule")
    if policy.template_id is None:
        reasons.append("no_template")
    if policy.problems():
        # Numbers outside their bounds decide nothing else: stop here rather than compare them.
        reasons.append("bad_policy")
        return Decision(False, reasons)
    # Consent: a "no" always stops; "unknown" only allows a service follow-up about a
    # conversation the person started themselves (ADR 0036 answer 2).
    if facts.consent == "withdrawn":
        reasons.append("consent_withdrawn")
    elif facts.consent != "granted" and not facts.started_by_person:
        reasons.append("consent_unknown")
    if not facts.has_address:
        reasons.append("no_address")
    if not facts.has_owner:
        reasons.append("no_owner")
    if facts.lead_status in CLOSED_LEAD_STATUSES:
        reasons.append("lead_closed")
    if facts.reply_after_trigger:
        reasons.append("reply_received")
    if facts.draft_waiting:
        reasons.append("draft_waiting")
    if facts.last_draft_at is not None and (
        facts.now - facts.last_draft_at < timedelta(days=policy.cooldown_days)
    ):
        reasons.append("cooldown")
    if facts.drafts_last_30_days >= policy.monthly_cap:
        reasons.append("monthly_cap")
    if facts.drafts_today >= policy.daily_cap:
        reasons.append("daily_cap")
    if facts.waiting_for_owner >= policy.pending_cap:
        reasons.append("owner_pending_cap")
    return Decision(not reasons, reasons)
