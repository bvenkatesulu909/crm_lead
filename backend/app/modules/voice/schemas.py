"""Voice gateway contracts."""

from pydantic import BaseModel, Field


class TranscriptionRead(BaseModel):
    text: str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
