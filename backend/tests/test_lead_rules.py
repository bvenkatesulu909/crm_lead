"""Unit tests for lead rules that need no database: transitions, validation, permissions."""

import itertools
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.auth.rbac import Permission, Role, permissions_for
from app.core.search import escape_like
from app.modules.leads.schemas import (
    ActivityCreate,
    ConvertAccount,
    ConvertOpportunity,
    LeadCreate,
    LeadDisqualify,
    LeadStatusChange,
    LeadUpdate,
)
from app.modules.leads.transitions import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    check_transition,
)

STATUSES = ["new", "contacted", "qualified", "unqualified", "converted"]
ALLOWED = {
    ("new", "contacted"),
    ("new", "qualified"),
    ("new", "unqualified"),
    ("contacted", "qualified"),
    ("contacted", "unqualified"),
    ("qualified", "contacted"),
    ("qualified", "unqualified"),
    ("unqualified", "contacted"),
}

# --- Status transitions -----------------------------------------------------------------


@pytest.mark.parametrize(("current", "target"), sorted(ALLOWED))
def test_allowed_transitions_pass(current: str, target: str) -> None:
    check_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        pair
        for pair in itertools.product(STATUSES, STATUSES)
        if pair not in ALLOWED and pair[1] != "converted"
    ],
)
def test_every_other_transition_is_rejected(current: str, target: str) -> None:
    with pytest.raises(InvalidTransitionError):
        check_transition(current, target)


@pytest.mark.parametrize("current", STATUSES)
def test_converted_is_only_reachable_through_conversion(current: str) -> None:
    with pytest.raises(InvalidTransitionError, match="convert endpoint"):
        check_transition(current, "converted")


def test_only_qualified_leads_can_be_converted() -> None:
    check_transition("qualified", "converted", via_conversion=True)
    for status in ("new", "contacted", "unqualified", "converted"):
        with pytest.raises(InvalidTransitionError):
            check_transition(status, "converted", via_conversion=True)


def test_converted_is_final() -> None:
    assert ALLOWED_TRANSITIONS["converted"] == frozenset()


def test_invalid_transition_maps_to_409_with_code() -> None:
    assert InvalidTransitionError.status_code == 409
    assert InvalidTransitionError.code == "invalid_status_transition"


# --- Input validation -------------------------------------------------------------------


def test_create_trims_text_and_normalises_email_domain() -> None:
    lead = LeadCreate(last_name="  Example  ", email="Jamie@Example.TEST")

    assert lead.last_name == "Example"
    assert lead.email == "Jamie@example.test"


@pytest.mark.parametrize(
    "payload",
    [
        {"last_name": ""},
        {"last_name": "   "},
        {"last_name": "x" * 101},
        {"last_name": "A", "email": "not-an-email"},
        {"last_name": "A", "email": "two@@example.test"},
        {"last_name": "A", "phone": "call me maybe"},
        {"last_name": "A", "source": "carrier-pigeon"},
        {"last_name": "A", "tenant_id": str(uuid.uuid4())},
        {"last_name": "A", "status": "converted"},
        {"last_name": "A", "id": str(uuid.uuid4())},
        {"first_name": "No last name"},
    ],
)
def test_invalid_create_payloads_are_rejected(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        LeadCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1},  # nothing to change
        {"version": 1, "last_name": None},  # last name cannot be removed
        {"version": 0, "last_name": "B"},  # versions start at 1
        {"version": 1, "status": "qualified"},  # status has its own endpoint
        {"version": 1, "owner_id": str(uuid.uuid4())},  # owner has its own endpoint
        {"version": 1, "converted_account_id": str(uuid.uuid4())},
        {"last_name": "B"},  # version is required
    ],
)
def test_invalid_update_payloads_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LeadUpdate.model_validate(payload)


def test_update_reports_only_sent_fields_and_allows_clearing_optional_ones() -> None:
    update = LeadUpdate.model_validate({"version": 3, "phone": None, "job_title": "CTO"})

    assert update.changes() == {"phone": None, "job_title": "CTO"}


def test_status_endpoint_cannot_target_converted_or_new() -> None:
    for status in ("converted", "new", "bogus"):
        with pytest.raises(ValidationError):
            LeadStatusChange.model_validate({"status": status})


def test_disqualify_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        LeadDisqualify.model_validate({})
    with pytest.raises(ValidationError):
        LeadDisqualify.model_validate({"reason": "   "})


def test_convert_account_is_either_existing_or_new() -> None:
    with pytest.raises(ValidationError):
        ConvertAccount(existing_account_id=uuid.uuid4(), name="Both")


@pytest.mark.parametrize(
    "payload",
    [
        {"currency": "eur"},
        {"currency": "EURO"},
        {"currency": "EUR", "amount": "-1"},
        {"currency": "EUR", "amount": "1.001"},
        {"amount": "10"},
    ],
)
def test_invalid_opportunity_payloads_are_rejected(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ConvertOpportunity.model_validate(payload)


def test_opportunity_amount_is_exact_decimal() -> None:
    opportunity = ConvertOpportunity.model_validate({"currency": "EUR", "amount": "1234.50"})

    assert opportunity.amount == Decimal("1234.50")


def test_activity_time_must_have_time_zone() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        ActivityCreate.model_validate(
            {"kind": "call", "subject": "Intro", "occurred_at": "2026-10-18T09:00:00"}
        )


def test_users_cannot_record_system_activity_kinds() -> None:
    with pytest.raises(ValidationError):
        ActivityCreate.model_validate({"kind": "converted", "subject": "fake"})


# --- Search escaping --------------------------------------------------------------------


def test_like_wildcards_in_search_are_escaped() -> None:
    assert escape_like("100%_off\\") == "100\\%\\_off\\\\"


# --- Permission matrix for leads --------------------------------------------------------

LEAD_PERMISSIONS = {p for p in Permission if p.value.startswith("lead:")}


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (
            Role.TENANT_ADMIN,
            LEAD_PERMISSIONS - {Permission.LEAD_READ_OWN, Permission.LEAD_WRITE_OWN},
        ),
        (
            Role.SALES_MANAGER,
            LEAD_PERMISSIONS - {Permission.LEAD_READ_OWN, Permission.LEAD_WRITE_OWN},
        ),
        (
            Role.SALES_AGENT,
            {Permission.LEAD_READ_OWN, Permission.LEAD_WRITE_OWN, Permission.LEAD_CONVERT},
        ),
        (Role.SUPPORT_AGENT, set()),
        (Role.CUSTOMER, set()),
        (Role.SUPER_ADMIN, set()),
    ],
)
def test_lead_permissions_per_role(role: Role, expected: set[Permission]) -> None:
    assert permissions_for(frozenset({role})) & LEAD_PERMISSIONS == expected
