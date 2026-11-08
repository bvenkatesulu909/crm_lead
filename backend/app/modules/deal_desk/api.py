"""Public interface of the deal desk module (ADR 0024). Other modules import only from here."""

from app.modules.deal_desk.facts import DealNotFoundError, build_sheets
from app.modules.deal_desk.rules import REVIEWERS, DealSheets, Fact, FactSheet, Reviewer

__all__ = [
    "REVIEWERS",
    "DealNotFoundError",
    "DealSheets",
    "Fact",
    "FactSheet",
    "Reviewer",
    "build_sheets",
]
