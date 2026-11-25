"""Answer shapes of /api/v1/deal-risk (ADR 0037, step DR3).

Nothing here comes from the client except the deal's id in the path and two list filters: the
level, the score and the factors are worked out by the server.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

Level = Literal["low", "medium", "high"]

# Said on every answer so no screen can show the score as a fact or a probability (ADR 0037 DR3).
FORECAST_NOTE = (
    "Forecast: an estimate from the reasons listed, not a promise and not a probability."
)


class DealRiskFactorRead(BaseModel):
    code: str
    sentence: str
    points: int
    source: str


class DealRiskSnapshotRead(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    level: Level
    score: int
    rules_version: int
    source: Literal["nightly", "on_demand"]
    computed_at: datetime
    factors: list[DealRiskFactorRead]
    # Signals that could not be read, as codes: unknown, never counted as good news.
    unknown: list[str]
    note: str = FORECAST_NOTE


class DealRiskDealRead(BaseModel):
    id: uuid.UUID
    name: str
    account_id: uuid.UUID
    stage: str
    amount: Decimal | None
    currency: str


class DealRiskRead(DealRiskSnapshotRead):
    deal: DealRiskDealRead | None


class DealRiskList(BaseModel):
    items: list[DealRiskRead]
    total: int
    limit: int
    offset: int
    note: str = FORECAST_NOTE


class DealRiskSnapshotList(BaseModel):
    items: list[DealRiskSnapshotRead]
