"""Request and response of the public website chat (ADR 0013).

The visitor sends a message (and, after the first answer, the conversation token). The tenant,
the visitor's address and everything about the lead are server-side; the answer never contains
CRM data - only the token, the reply text and whether the details were passed on.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.public_chat.rules import TOKEN_PATTERN


class PublicChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, StringConstraints(pattern=TOKEN_PATTERN.pattern)] | None = Field(
        default=None, description="The conversation token from the previous answer, if any."
    )
    # The guardrails refuse anything over 2,000 characters; this only stops huge payloads.
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    # A hidden form field people never fill in; bots that fill it are refused.
    website: Annotated[str, StringConstraints(max_length=500)] = ""
    # The language switch on the page (ADR 0027): a fixed list, never free text. It chooses the
    # language of the answer and is written on the lead.
    language: Literal["en", "hi", "te"] = "en"


class PublicChatReply(BaseModel):
    token: str
    reply: str
    lead_saved: bool = Field(description="True once this conversation's details were saved.")


class TranscriptMessage(BaseModel):
    """One message of a website conversation, as staff see it on the lead page."""

    model_config = ConfigDict(from_attributes=True)

    role: Literal["visitor", "assistant"]
    content: str
    created_at: datetime


class PublicChatTranscript(BaseModel):
    """The website conversation that created a lead (empty if the lead came another way)."""

    started_at: datetime | None
    channel: Literal["text", "web_voice"] = "text"
    voice_seconds: int = 0
    messages: list[TranscriptMessage]


class PublicVoiceReply(BaseModel):
    """What comes back after one spoken turn (ADR 0038)."""

    token: str
    heard: str = Field(description="What the speech service heard the visitor say.")
    reply: str
    lead_saved: bool
    # The reply as speech (base64), or none when speech could not be made: the page then shows
    # the text only and the conversation goes on.
    audio_base64: str | None = None
    audio_type: str | None = None
    seconds_left: int = Field(description="Speech seconds left in this call.")
    turns_left: int
    call_ended: bool = Field(description="True when this call's limits are used up.")
