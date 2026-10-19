"""Workflow rule validation and condition logic (pure functions, no database)."""

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.modules.workflows.rules import InvalidRuleError, matches, render, validate

TASK = {"type": "create_task", "subject": "Check {record}", "due_in_days": 1, "assignee": "owner"}


def ok(
    trigger: str = "quote.approval_requested",
    days: Any = None,
    conditions: Any = None,
    actions: Any = None,
) -> tuple[Any, Any, Any]:
    return validate(trigger, days, conditions or [], [TASK] if actions is None else actions)


def refused(message: str, **kwargs: Any) -> None:
    with pytest.raises(InvalidRuleError, match=message):
        ok(**kwargs)


def test_a_valid_rule_is_normalised() -> None:
    user = uuid.uuid4()
    days, conditions, actions = ok(
        conditions=[
            {"field": "max_discount_percent", "op": "gt", "value": 20},
            {"field": "status", "op": "in", "value": ["sent", "sent", "accepted"]},
        ],
        actions=[
            {**TASK, "subject": "  Check\n  {record}  "},
            {"type": "notify", "message": "Big discount", "to": "role:sales_manager"},
            {"type": "notify", "message": "FYI", "to": f"user:{user}"},
            {"type": "update_field", "field": "account.segment", "value": "enterprise"},
        ],
    )
    assert days is None  # only schedules use days
    assert conditions == [
        {"field": "max_discount_percent", "op": "gt", "value": "20"},
        {"field": "status", "op": "in", "value": ["accepted", "sent"]},
    ]
    assert actions[0]["subject"] == "Check {record}"  # one line, no stray spaces
    assert actions[2]["to"] == f"user:{user}"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"trigger": "drop.tables"}, "Choose a trigger"),
        ({"trigger": "schedule.quote_expiring", "days": None}, "enter 0 to 365"),
        ({"trigger": "schedule.task_overdue", "days": 400}, "enter 0 to 365"),
        ({"conditions": [{"field": "password", "op": "eq", "value": "x"}]}, "Unknown field"),
        ({"conditions": [{"field": "currency", "op": "gt", "value": "EUR"}]}, "can't be used"),
        ({"conditions": [{"field": "total", "op": "eq", "value": "lots"}]}, "must be a number"),
        ({"conditions": [{"field": "total", "op": "eq", "value": "NaN"}]}, "must be a number"),
        (
            {"conditions": [{"field": "status", "op": "in", "value": ["hacked"]}]},
            "Choose one or more",
        ),
        ({"conditions": [{"field": "status", "op": "eq", "value": "x"}]}, "Choose a value"),
        ({"conditions": [{"field": "total", "op": "gt", "value": 1}] * 6}, "At most 5"),
        ({"actions": []}, "Add 1 to 5"),
        ({"actions": [TASK] * 6}, "Add 1 to 5"),
        ({"actions": [{"type": "run_sql"}]}, "Each action needs a type"),
        ({"actions": [{**TASK, "subject": ""}]}, "subject is required"),
        ({"actions": [{**TASK, "subject": "x" * 201}]}, "at most 200"),
        ({"actions": [{**TASK, "due_in_days": -1}]}, "0 to 365"),
        ({"actions": [{**TASK, "due_in_days": True}]}, "0 to 365"),
        ({"actions": [{**TASK, "assignee": "role:sales_manager"}]}, "the owner, a colleague"),
        ({"actions": [{**TASK, "assignee": "user:not-a-uuid"}]}, "the owner, a colleague"),
        ({"actions": [{"type": "notify", "message": "x", "to": "role:super_admin"}]}, "or a role"),
        (
            {"actions": [{"type": "update_field", "field": "lead.status", "value": "new"}]},
            "can't be changed",
        ),
        (
            {"actions": [{"type": "update_field", "field": "account.segment", "value": "vip"}]},
            "Choose a value",
        ),
        (
            {"actions": [{"type": "update_field", "field": "account.owner_id", "value": "x"}]},
            "can't be changed",
        ),
    ],
)
def test_invalid_rules_are_refused_with_a_reason(kwargs: dict[str, Any], message: str) -> None:
    refused(message, **kwargs)


def test_converting_a_lead_is_never_automatic() -> None:
    refused(
        "Choose a value",
        trigger="lead.assigned",
        actions=[{"type": "update_field", "field": "lead.status", "value": "converted"}],
    )
    ok(
        trigger="lead.assigned",
        actions=[{"type": "update_field", "field": "lead.status", "value": "contacted"}],
    )


def test_schedules_keep_their_days() -> None:
    assert ok(trigger="schedule.quote_expiring", days=3)[0] == 3


def test_conditions_all_have_to_match() -> None:
    values: dict[str, str | Decimal] = {
        "total": Decimal("1200.00"),
        "currency": "EUR",
        "status": "sent",
    }
    rule: list[dict[str, Any]] = [
        {"field": "total", "op": "gte", "value": "1000"},
        {"field": "currency", "op": "eq", "value": "eur"},  # text compares without case
        {"field": "status", "op": "in", "value": ["sent", "accepted"]},
    ]
    assert matches(rule, values)
    assert not matches([*rule, {"field": "total", "op": "lt", "value": "1000"}], values)
    assert not matches([{"field": "priority", "op": "eq", "value": "high"}], values)
    assert matches([], values)  # no conditions: always


def test_only_the_record_placeholder_is_filled_in() -> None:
    assert (
        render("Call about {record} today", "QT-0007: Widgets")
        == "Call about QT-0007: Widgets today"
    )
    assert render("{0} {__class__} {record!r}", "X") == "{0} {__class__} {record!r}"  # no format()
