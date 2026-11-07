"""Voice is governed like an agent (ADR 0023, steps VM2-VM3).

The registry entry ``voice`` (ADR 0016) has a switch per organisation - OFF until an administrator
switches it on - and counts SECONDS of server speech in the usage row's two counters (heard /
spoken), so the AI agents page can show minutes. The monthly allowance is
``CRM_VOICE_MONTHLY_MINUTES`` per organisation. Browser speech costs us nothing and is not counted;
the switch still decides whether the voice conversation is offered at all.

The seconds are ESTIMATES (no audio is decoded): a recording's size at the usual compressed rate,
and a spoken sentence's length at a normal speaking pace. They are a budget, not a bill.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.config import Settings
from app.core.errors import DomainError, ForbiddenError
from app.modules.agents import api as agents_api

AGENT_KEY = "voice"
# Compressed speech from a browser (Opus/AAC) is about 32 kbit/s = 4 kB per second.
BYTES_PER_SECOND = 4000
# A normal speaking pace is about 15 characters per second.
CHARS_PER_SECOND = 15
MAX_SECONDS_PER_CLIP = 600


class VoiceOffError(DomainError):
    status_code = 503
    code = "voice_off"

    def __init__(self) -> None:
        super().__init__("Voice is switched off for your organisation.")


class VoiceBudgetReachedError(DomainError):
    status_code = 503
    code = "voice_budget_reached"

    def __init__(self) -> None:
        super().__init__("Voice has used this month's minutes. An administrator can help.")


@dataclass(frozen=True)
class VoiceState:
    enabled: bool
    seconds_used: int
    seconds_budget: int


def seconds_heard(size_bytes: int) -> int:
    return max(1, min(MAX_SECONDS_PER_CLIP, math.ceil(size_bytes / BYTES_PER_SECOND)))


def seconds_spoken(text: str) -> int:
    return max(1, min(MAX_SECONDS_PER_CLIP, math.ceil(len(text) / CHARS_PER_SECOND)))


def _tenant(principal: Principal) -> uuid.UUID:
    if principal.user_type not in ("staff", "customer") or principal.tenant_id is None:
        raise ForbiddenError("Voice is for staff and customers.")
    return principal.tenant_id


def state(session: Session, principal: Principal, settings: Settings) -> VoiceState:
    """The organisation's voice switch and this month's seconds (no refusal)."""
    current = agents_api.effective(
        session,
        _tenant(principal),
        AGENT_KEY,
        agents_api.Limits.default(),
        datetime.now(UTC),
    )
    return VoiceState(
        enabled=current.enabled,
        seconds_used=current.input_tokens + current.output_tokens,
        seconds_budget=settings.voice_monthly_minutes * 60,
    )


def check(session: Session, principal: Principal, settings: Settings) -> None:
    """Refuse server speech when voice is off or this month's minutes are used up."""
    try:
        agents_api.check_can_call(
            session, _tenant(principal), AGENT_KEY, agents_api.Limits.default(), datetime.now(UTC)
        )
    except agents_api.AgentUnavailableError:
        raise VoiceOffError() from None
    current = state(session, principal, settings)
    if current.seconds_used >= current.seconds_budget:
        raise VoiceBudgetReachedError()


def record(session: Session, principal: Principal, *, heard: int = 0, spoken: int = 0) -> None:
    """Add estimated seconds to the month (not committed): heard in one counter, spoken in the
    other."""
    agents_api.record_usage(
        session,
        _tenant(principal),
        AGENT_KEY,
        input_tokens=heard,
        output_tokens=spoken,
        limits=agents_api.Limits.default(),
        now=datetime.now(UTC),
    )
