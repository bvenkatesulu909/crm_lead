"""Communication Center, step CC1 (ADR 0012): who gets which communication permission.

No database needed: the role -> permission matrix is plain code in app/core/auth/rbac.py.
"""

import pytest

from app.core.auth.rbac import AUTOMATION_PERMISSIONS, Permission, Role, permissions_for
from app.modules.communications import rules

SEND = Permission.COMMUNICATION_SEND
READ_ALL = Permission.COMMUNICATION_READ_ALL
READ_OWN = Permission.COMMUNICATION_READ_OWN
TEMPLATES = Permission.COMMUNICATION_TEMPLATE_MANAGE
ALL_FOUR = {SEND, READ_ALL, READ_OWN, TEMPLATES}


def test_the_permission_names_follow_resource_action_scope() -> None:
    assert SEND == "communication:send"
    assert READ_ALL == "communication:read:all"
    assert READ_OWN == "communication:read:own"
    assert TEMPLATES == "communication:template:manage"


@pytest.mark.parametrize(
    "role, expected",
    [
        # Managers and admins see every message of the organisation and edit templates.
        (Role.TENANT_ADMIN, {SEND, READ_ALL, TEMPLATES}),
        (Role.SALES_MANAGER, {SEND, READ_ALL, TEMPLATES}),
        # Agents write e-mails but only list the ones they sent or logged themselves.
        (Role.SALES_AGENT, {SEND, READ_OWN}),
        (Role.SUPPORT_AGENT, {SEND, READ_OWN}),
        # The platform operator sees no tenant business data; customers use the portal only.
        (Role.SUPER_ADMIN, set()),
        (Role.CUSTOMER, set()),
    ],
)
def test_each_role_gets_exactly_its_communication_permissions(
    role: Role, expected: set[Permission]
) -> None:
    assert permissions_for(frozenset({role})) & ALL_FOUR == expected


def test_a_manager_who_is_also_an_agent_gets_the_wider_list_scope() -> None:
    granted = permissions_for(frozenset({Role.SALES_AGENT, Role.SALES_MANAGER}))
    assert {SEND, READ_ALL, READ_OWN, TEMPLATES} <= granted


@pytest.mark.parametrize(
    "value, expected",
    [
        ("ada@example.test", True),
        ("a@b", True),
        (None, False),
        ("", False),
        ("no-at-sign", False),
        ("two@@example.test", False),
        ("space in@example.test", False),
        ("x" * 315 + "@a.de", True),  # exactly the 320-character column
        ("x" * 316 + "@a.de", False),  # one longer
    ],
)
def test_only_address_shaped_values_are_used(value: str | None, expected: bool) -> None:
    assert rules.looks_like_address(value) is expected


def test_the_hourly_limit_allows_up_to_the_limit() -> None:
    assert not rules.limit_reached(199, 200)
    assert rules.limit_reached(200, 200)


@pytest.mark.parametrize(
    "error, code",
    [
        ("MailRejectedError", "recipient_refused"),
        ("MailUnavailableError", "mail_server_unavailable"),
        ("PermanentJobError: consent_withdrawn", "consent_withdrawn"),
        ("PermanentJobError: something else", "send_failed"),
        ("ValueError", "send_failed"),
    ],
)
def test_failures_become_safe_codes(error: str, code: str) -> None:
    assert rules.failure_code(error) == code


def test_automation_cannot_send_e_mails_yet() -> None:
    # Workflow rules get e-mail actions only through a later, reviewed step.
    assert AUTOMATION_PERMISSIONS & ALL_FOUR == set()
