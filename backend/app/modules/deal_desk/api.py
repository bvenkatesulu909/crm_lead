"""Public interface of the deal desk module (ADR 0024). Other modules import only from here."""

from app.modules.deal_desk.facts import DealNotFoundError, build_sheets
from app.modules.deal_desk.research import delete_expired as delete_expired_briefs
from app.modules.deal_desk.research import list_briefs, run_research
from app.modules.deal_desk.rules import REVIEWERS, DealSheets, Fact, FactSheet, Reviewer
from app.modules.deal_desk.service import delete_expired, list_reviews, run_review

__all__ = [
    "REVIEWERS",
    "DealNotFoundError",
    "DealSheets",
    "Fact",
    "FactSheet",
    "Reviewer",
    "build_sheets",
    "delete_expired",
    "delete_expired_briefs",
    "list_briefs",
    "run_research",
    "list_reviews",
    "run_review",
]
