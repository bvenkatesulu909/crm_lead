"""Public interface of the deal desk module (ADR 0024). Other modules import only from here."""

from app.modules.deal_desk.facts import DealNotFoundError, build_sheets
from app.modules.deal_desk.llm import model_for
from app.modules.deal_desk.research import (
    AccountNotFoundError,
    BriefOverview,
    Limits,
    ResearchInvalidError,
    ResearchNoSourceError,
    ResearchRateLimitedError,
    latest_overviews,
    list_briefs,
    overviews_of,
    recent_average_tokens,
    researched_today,
    run_research,
)
from app.modules.deal_desk.research import delete_expired as delete_expired_briefs
from app.modules.deal_desk.rules import REVIEWERS, DealSheets, Fact, FactSheet, Reviewer
from app.modules.deal_desk.service import delete_expired, list_reviews, run_review

__all__ = [
    "model_for",
    "REVIEWERS",
    "AccountNotFoundError",
    "BriefOverview",
    "Limits",
    "ResearchInvalidError",
    "ResearchNoSourceError",
    "ResearchRateLimitedError",
    "DealNotFoundError",
    "DealSheets",
    "Fact",
    "FactSheet",
    "Reviewer",
    "build_sheets",
    "delete_expired",
    "delete_expired_briefs",
    "latest_overviews",
    "list_briefs",
    "overviews_of",
    "recent_average_tokens",
    "researched_today",
    "run_research",
    "list_reviews",
    "run_review",
]
