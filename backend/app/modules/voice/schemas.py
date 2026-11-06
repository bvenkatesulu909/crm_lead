"""Voice gateway contracts."""

from pydantic import BaseModel, Field


class TranscriptionRead(BaseModel):
    text: str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class VoiceStatusRead(BaseModel):
    """What the voice conversation may use here (ADR 0023)."""

    # The organisation's ``voice`` switch in the agent registry (off until an admin turns it on).
    enabled: bool
    # Whether the browser's own speech may be used (CRM_VOICE_BROWSER_ENGINE; off for real data).
    browser_engine: bool
    # Whether the CRM's speech service is configured (a key, or the local engine).
    server_engine: bool
    minutes_used: int
    minutes_budget: int
