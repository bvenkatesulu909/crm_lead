"""Public interface of the proposal decks module (ADR 0032). Other modules import only from here."""

from app.core.outbox import JobHandler
from app.core.storage import FileStore
from app.modules.proposal_decks import service
from app.modules.proposal_decks.data import DeckBrand, DeckData, DeckLine
from app.modules.proposal_decks.render import drawable_characters, render_deck

JOB = service.JOB

__all__ = [
    "JOB",
    "DeckBrand",
    "DeckData",
    "DeckLine",
    "drawable_characters",
    "job_handler",
    "render_deck",
]


def job_handler(store: FileStore) -> JobHandler:
    """Worker handler for "quote.deck": draws and stores one quote's deck (safe to run twice)."""
    return lambda session, job: service.run_job(session, store, job)
