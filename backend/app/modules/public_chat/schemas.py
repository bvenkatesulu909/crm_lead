"""Request and response of the public website chat (ADR 0013).

The visitor sends a message (and, after the first answer, the conversation token). The tenant,
the visitor's address and everything about the lead are server-side; the answer never contains
CRM data - only the token, the reply text and whether the details were passed on.
"""

from typing import Annotated

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


class PublicChatReply(BaseModel):
    token: str
    reply: str
    lead_saved: bool = Field(description="True once this conversation's details were saved.")
