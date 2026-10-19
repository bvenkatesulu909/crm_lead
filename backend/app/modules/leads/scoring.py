"""Lead scoring: a transparent 0-100 score with the factors behind it.

The same rules exist twice:
- ``score_sql()`` - a SQL expression, so lists can be SORTED and FILTERED by score in the
  database (and only over leads the user may see);
- ``explain()`` - Python, to show the user which factors gave which points.
Tests check that both give the same number for the same lead.

Weights are simple and documented (docs/customer-relationships.md); organisations will be able
to tune them in the administration phase.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Integer, and_, case, cast, func, literal, select

from app.modules.leads.models import USER_ACTIVITY_KINDS, Lead, LeadActivity

SOURCE_POINTS = {
    "referral": 20,
    "partner": 15,
    "event": 10,
    "web": 10,
    "advertisement": 5,
    "cold_call": 0,
    "other": 0,
}
STATUS_POINTS = {"new": 0, "contacted": 5, "qualified": 20, "converted": 20}
SENIOR_WORDS = (
    "chief", "ceo", "cfo", "cto", "coo", "cio", "director", "head", "vp", "vice president",
    "owner", "founder", "partner", "president",
)  # fmt: skip
RECENT_DAYS = 14
STALE_DAYS = 30
POINTS_PER_ACTIVITY = 3
MAX_ACTIVITY_POINTS = 12
HOT_FROM = 70
WARM_FROM = 40
_SENIOR_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in SENIOR_WORDS) + r")\b")
_SENIOR_SQL = r"\m(" + "|".join(SENIOR_WORDS) + r")\M"


def priority_of(score: int) -> str:
    return "hot" if score >= HOT_FROM else "warm" if score >= WARM_FROM else "cold"


@dataclass(frozen=True)
class Factor:
    label: str
    points: int


def explain(
    lead: Lead, activity_count: int, last_activity_at: datetime | None, now: datetime
) -> tuple[int, str, list[Factor]]:
    if lead.status == "unqualified":
        return 0, "cold", [Factor("Disqualified", 0)]
    factors: list[Factor] = []
    if lead.email:
        factors.append(Factor("Has an e-mail address", 15))
    if lead.phone:
        factors.append(Factor("Has a phone number", 10))
    if lead.company_name:
        factors.append(Factor("Company known", 10))
    if lead.job_title:
        senior = bool(_SENIOR_RE.search(lead.job_title.lower()))
        factors.append(
            Factor("Senior decision-maker" if senior else "Job title known", 15 if senior else 5)
        )
    source_points = SOURCE_POINTS.get(lead.source or "", 0)
    if source_points:
        factors.append(Factor(f"Source: {lead.source}", source_points))
    status_points = STATUS_POINTS.get(lead.status, 0)
    if status_points:
        factors.append(Factor(f"Status: {lead.status}", status_points))
    if last_activity_at is not None:
        if last_activity_at >= now - timedelta(days=RECENT_DAYS):
            factors.append(Factor(f"Engaged in the last {RECENT_DAYS} days", 15))
        elif last_activity_at < now - timedelta(days=STALE_DAYS):
            factors.append(Factor(f"No engagement for over {STALE_DAYS} days", -10))
    if activity_count:
        factors.append(
            Factor(
                f"{activity_count} call(s), e-mail(s), meeting(s) or note(s)",
                min(activity_count * POINTS_PER_ACTIVITY, MAX_ACTIVITY_POINTS),
            )
        )  # fmt: skip
    score = max(0, min(100, sum(f.points for f in factors)))
    return score, priority_of(score), factors


def _activities() -> tuple[ColumnElement[int], ColumnElement[datetime]]:
    mine = and_(
        LeadActivity.tenant_id == Lead.tenant_id,
        LeadActivity.lead_id == Lead.id,
        LeadActivity.kind.in_(USER_ACTIVITY_KINDS),
    )
    count = select(func.count()).where(mine).correlate(Lead).scalar_subquery()
    last = select(func.max(LeadActivity.occurred_at)).where(mine).correlate(Lead).scalar_subquery()
    return count, last


def score_sql() -> ColumnElement[int]:
    """The score as a SQL expression on ``Lead`` (same rules as ``explain``)."""
    count, last = _activities()
    now = func.now()

    def points(condition: ColumnElement[bool], value: int) -> ColumnElement[int]:
        return case((condition, value), else_=0)

    source = case(*((Lead.source == s, p) for s, p in SOURCE_POINTS.items() if p), else_=literal(0))
    status = case(*((Lead.status == s, p) for s, p in STATUS_POINTS.items() if p), else_=literal(0))
    senior = func.lower(Lead.job_title).op("~")(_SENIOR_SQL)
    title = case((Lead.job_title.is_(None), 0), (senior, 15), else_=5)
    engagement = case(
        (last.is_(None), 0),
        (last >= now - timedelta(days=RECENT_DAYS), 15),
        (last < now - timedelta(days=STALE_DAYS), -10),
        else_=0,
    )
    activity_points = func.least(count * POINTS_PER_ACTIVITY, MAX_ACTIVITY_POINTS)
    total = (
        points(Lead.email.is_not(None), 15)
        + points(Lead.phone.is_not(None), 10)
        + points(Lead.company_name.is_not(None), 10)
        + title
        + source
        + status
        + engagement
        + activity_points
    )
    clamped = func.greatest(0, func.least(100, total))
    return cast(case((Lead.status == "unqualified", 0), else_=clamped), Integer)


def priority_condition(priority: str) -> ColumnElement[bool]:
    score = score_sql()
    if priority == "hot":
        return score >= HOT_FROM
    if priority == "warm":
        return and_(score >= WARM_FROM, score < HOT_FROM)
    return score < WARM_FROM
