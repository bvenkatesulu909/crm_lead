# ruff: noqa: F811 - pytest fixtures imported from test_quotes_api are used as parameters
"""Per-organisation approval limit for quote discounts (ADR 0005 follow-up, step E2c)."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from tests.db.test_quotes_api import (  # noqa: F401 - fixtures used by name
    QUOTES,
    Headers,
    World,
    api,
    auth,
    code_of,
    new_quote,
    ok,
    step,
    world,
)

SETTINGS = f"{QUOTES}/settings"


def settings(api, auth, user: str = "alpha.agent1") -> Any:
    return ok(api.get(SETTINGS, headers=auth(user)))


def change(api, auth, limit: Any, version: int, user: str = "alpha.admin") -> Any:
    return api.put(
        SETTINGS,
        json={"version": version, "approval_limit_percent": limit},
        headers=auth(user),
    )


def submitted(api, auth, world, discount: str, **kw: Any) -> Any:
    product = kw.pop("product", "P1")
    quote = new_quote(
        api,
        auth,
        world,
        lines=[
            {"product_id": str(world.ids[product]), "quantity": "1", "discount_percent": discount}
        ],
        **kw,
    )
    return ok(step(api, auth, kw.get("user", "alpha.agent1"), quote, "submit"))


def test_organisations_start_with_ten_percent(api, auth, world) -> None:
    assert settings(api, auth) == {
        "approval_limit_percent": "10.00",
        "version": 0,
        "updated_at": None,
    }
    assert submitted(api, auth, world, "10")["status"] == "approved"
    assert submitted(api, auth, world, "10.01")["status"] == "pending_approval"


def test_an_admin_raises_the_limit(api, auth, world, db_session: Session) -> None:
    result = ok(change(api, auth, "20", 0))
    assert (result["approval_limit_percent"], result["version"]) == ("20.00", 1)
    assert settings(api, auth)["approval_limit_percent"] == "20.00"  # everyone reads it
    assert submitted(api, auth, world, "15")["status"] == "approved"
    assert submitted(api, auth, world, "20.5")["status"] == "pending_approval"

    [audit] = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "quote.settings_changed")
    ).all()
    assert audit.changes == {"approval_limit_percent": {"old": "10.00", "new": "20.00"}}
    assert audit.actor_user_id == world.users["alpha.admin"].id


def test_zero_means_every_discount_needs_approval(api, auth, world) -> None:
    ok(change(api, auth, "0", 0))
    assert submitted(api, auth, world, "0")["status"] == "approved"
    assert submitted(api, auth, world, "0.5")["status"] == "pending_approval"


def test_quotes_already_waiting_keep_waiting(api, auth, world) -> None:
    waiting = submitted(api, auth, world, "15")
    ok(change(api, auth, "50", 0))
    read = ok(api.get(f"{QUOTES}/{waiting['id']}", headers=auth("alpha.agent1")))
    assert read["status"] == "pending_approval"  # decided when it was submitted


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("alpha.manager", 403),  # approves quotes, but doesn't set the rules
        ("alpha.agent1", 403),
        ("alpha.support", 403),
        ("alpha.customer", 403),
    ],
)
def test_only_admins_change_the_limit(api, auth, world, user, expected) -> None:
    assert change(api, auth, "50", 0, user=user).status_code == expected
    assert settings(api, auth)["approval_limit_percent"] == "10.00"


@pytest.mark.parametrize("user", ["alpha.support", "alpha.customer"])
def test_people_without_quotes_cannot_read_the_settings(api, auth, world, user) -> None:
    assert api.get(SETTINGS, headers=auth(user)).status_code == 403


def test_each_organisation_has_its_own_limit(api, auth, world) -> None:
    ok(change(api, auth, "30", 0))
    beta = settings(api, auth, "beta.agent")
    assert (beta["approval_limit_percent"], beta["version"]) == ("10.00", 0)
    beta_quote = submitted(
        api, auth, world, "15", user="beta.agent", account="B1", book="BBOOK", product="PB"
    )
    assert beta_quote["status"] == "pending_approval"


@pytest.mark.parametrize(
    "body",
    [
        {"version": 0, "approval_limit_percent": "100.01"},
        {"version": 0, "approval_limit_percent": "-1"},
        {"version": 0, "approval_limit_percent": "10.555"},
        {"version": 0, "approval_limit_percent": "ten"},
        {"approval_limit_percent": "20"},  # version is required
        {"version": 0, "approval_limit_percent": "20", "tenant_id": "x"},  # no extra fields
    ],
)
def test_invalid_values_are_refused(api, auth, world, body) -> None:
    assert api.put(SETTINGS, json=body, headers=auth("alpha.admin")).status_code == 422
    assert settings(api, auth)["version"] == 0


def test_two_admins_cannot_overwrite_each_other(api, auth, world) -> None:
    ok(change(api, auth, "20", 0))
    assert code_of(change(api, auth, "5", 0)) == (409, "version_conflict")
    assert ok(change(api, auth, "5", 1))["approval_limit_percent"] == "5.00"
    assert settings(api, auth)["approval_limit_percent"] == "5.00"


def test_the_limit_is_stored_exactly(api, auth, world) -> None:
    assert ok(change(api, auth, 12.5, 0))["approval_limit_percent"] == "12.50"
    assert Decimal(settings(api, auth)["approval_limit_percent"]) == Decimal("12.5")
