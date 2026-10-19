"""Response contract of the dashboard. Money is per currency (decimal strings in JSON)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

View = Literal["executive", "manager", "representative"]


class MoneyRead(BaseModel):
    currency: str
    amount: Decimal


class PeriodRead(BaseModel):
    start: date
    end: date


class LeadFigures(BaseModel):
    created: int
    assigned: int
    unassigned: int
    new: int
    contacted: int
    qualified: int
    unqualified: int
    converted: int
    converted_in_period: int
    open_now: int
    conversion_rate: float | None  # converted / created, for leads created in the period


class CustomerFigures(BaseModel):
    total: int
    active: int
    new_in_period: int


class StageRead(BaseModel):
    stage: str
    count: int
    value: list[MoneyRead]


class PipelineFigures(BaseModel):
    open_count: int
    open_value: list[MoneyRead]
    by_stage: list[StageRead]
    closing_in_period: int
    closing_in_period_value: list[MoneyRead]
    without_amount: int


class FollowUpRead(BaseModel):
    lead_id: uuid.UUID
    name: str
    company: str | None
    status: str
    owner_name: str | None
    last_touch_at: datetime
    days_idle: int


class FollowUpFigures(BaseModel):
    total: int
    rule: str
    items: list[FollowUpRead]


class ActivityRead(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: str | None
    record_type: Literal["lead", "ticket", "order"]
    record_id: uuid.UUID
    actor_name: str | None


class RepFigures(BaseModel):
    user_id: uuid.UUID | None  # None = leads/opportunities without an owner
    name: str
    leads_created: int
    qualified: int
    converted_in_period: int
    customers: int
    open_opportunities: int
    open_value: list[MoneyRead]
    follow_ups: int


class RevenueFigures(BaseModel):
    issued_count: int
    issued_value: list[MoneyRead]
    received: list[MoneyRead]
    outstanding_count: int
    outstanding: list[MoneyRead]
    overdue_count: int
    overdue: list[MoneyRead]


class OrderFigures(BaseModel):
    confirmed_in_period: int
    confirmed_value: list[MoneyRead]
    in_progress_now: int


class SupportFigures(BaseModel):
    open_now: int
    sla_overdue_now: int
    opened_in_period: int
    complaints_in_period: int
    ratings_in_period: int
    average_rating: float | None = Field(description="Customer satisfaction 1-5 in the period.")


class DashboardRead(BaseModel):
    view: View
    available_views: list[View]
    period: PeriodRead
    owner_id: uuid.UUID | None
    leads: LeadFigures
    customers: CustomerFigures
    pipeline: PipelineFigures
    follow_ups: FollowUpFigures
    recent_activities: list[ActivityRead]
    # Sales manager and executive views:
    team: list[RepFigures] | None = None
    # Executive view only:
    revenue: RevenueFigures | None = None
    orders: OrderFigures | None = None
    support: SupportFigures | None = None
