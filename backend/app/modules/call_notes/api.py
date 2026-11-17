"""Public interface of the call notes module. Other modules import only from here."""

from app.modules.call_notes import service
from app.modules.call_notes.llm import model_for

AGENT_KEY = service.AGENT_KEY
Limits = service.Limits
NotesResult = service.NotesResult
run_notes = service.run_notes

__all__ = ["AGENT_KEY", "Limits", "NotesResult", "model_for", "run_notes"]
