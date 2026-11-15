"""Public interface of the proposal decks module (ADR 0032). Other modules import only from here."""

from app.core.outbox import JobHandler
from app.core.storage import FileStore
from app.modules.proposal_decks import rules, service
from app.modules.proposal_decks.data import DeckBrand, DeckData, DeckLine
from app.modules.proposal_decks.render import drawable_characters, render_deck

JOB = service.JOB
add_summary = service.add_summary
latest_summary = service.latest_summary
summary_problem = service.summary_problem
DeckSummaryInvalidError = service.DeckSummaryInvalidError
check_summary = rules.check_summary
JOB_PPTX = service.JOB_PPTX

__all__ = [
    "JOB",
    "DeckSummaryInvalidError",
    "add_summary",
    "check_summary",
    "latest_summary",
    "summary_problem",
    "JOB_PPTX",
    "DeckBrand",
    "DeckData",
    "DeckLine",
    "drawable_characters",
    "job_handler",
    "render_deck",
]


def job_handler(store: FileStore) -> JobHandler:
    """Worker handler for "quote.deck" and "quote.deck_pptx" (the job's kind says which format):
    draws and stores one quote's deck (safe to run twice)."""
    return lambda session, job: service.run_job(session, store, job)
