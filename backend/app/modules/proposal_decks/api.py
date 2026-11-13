"""Public interface of the proposal decks module (ADR 0032). Other modules import only from here.

PD2 exposes the pure renderer and its data classes; PD3 adds the job and the download."""

from app.modules.proposal_decks.data import DeckBrand, DeckData, DeckLine
from app.modules.proposal_decks.render import drawable_characters, render_deck

__all__ = ["DeckBrand", "DeckData", "DeckLine", "drawable_characters", "render_deck"]
