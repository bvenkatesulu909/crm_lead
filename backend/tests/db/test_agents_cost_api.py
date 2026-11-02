# ruff: noqa: F811 - pytest fixtures imported from other test files are used as parameters
"""The estimated monthly cost on the agents API (CRM-111, step LM2).

Computed when read, from the month's stored tokens and the two prices of the server's settings:
nothing new is stored, the client sends no price and no cost, another organisation's usage never
counts, and without a price the field is ``null``.
"""

import re
from datetime import UTC, datetime
from typing import Any

from app.modules.agents import api as agents_api
from app.modules.agents.service import Limits
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world  # noqa: F401

URL = "/api/v1/agents"
LIMITS = Limits(platform_disabled=False, default_monthly_tokens=10_000_000)
MONEY = re.compile(r"^\d+\.\d{4}$")


def price(api: Any, input_price: float, output_price: float) -> None:
    """Set the two prices the way the environment would (read per request from the settings)."""
    settings = api.app.state.settings
    api.app.state.settings = settings.model_copy(
        update={
            "ai_input_price_per_million": input_price,
            "ai_output_price_per_million": output_price,
        }
    )


def use(db_session: Any, world: World, who: str, key: str, tokens_in: int, tokens_out: int) -> None:
    user = world.users[who]
    bind_principal(db_session, principal_for(user, ROLES[who]))
    agents_api.record_usage(
        db_session,
        user.tenant_id,
        key,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        limits=LIMITS,
        now=datetime.now(UTC),
    )
    db_session.flush()


def by_key(api: Any, auth: Headers, who: str = "alpha.admin") -> dict[str, Any]:
    return {a["key"]: a for a in ok(api.get(URL, headers=auth(who)))["items"]}


def test_without_a_price_there_is_no_cost_to_show(api, auth, world, db_session) -> None:
    use(db_session, world, "alpha.admin", "staff_assistant", 1_000_000, 1_000_000)
    assert all(a["estimated_cost_usd"] is None for a in by_key(api, auth).values())


def test_with_prices_the_cost_follows_the_months_tokens(api, auth, world, db_session) -> None:
    price(api, 3.0, 15.0)
    use(db_session, world, "alpha.admin", "staff_assistant", 2_000_000, 1_000_000)
    staff = by_key(api, auth)["staff_assistant"]
    assert staff["estimated_cost_usd"] == "21.0000"
    assert MONEY.match(staff["estimated_cost_usd"])  # text, so no float rounding in JSON


def test_an_agent_without_usage_costs_zero_and_one_without_a_model_has_none(
    api, auth, world
) -> None:
    price(api, 3.0, 15.0)
    agents = by_key(api, auth)
    assert agents["qualifier"]["estimated_cost_usd"] == "0.0000"
    assert agents["web_check"]["uses_model"] is False
    assert agents["web_check"]["estimated_cost_usd"] is None


def test_each_agent_has_its_own_cost(api, auth, world, db_session) -> None:
    price(api, 1.0, 2.0)
    use(db_session, world, "alpha.admin", "qualifier", 1_000_000, 0)
    use(db_session, world, "alpha.admin", "public_chat", 0, 1_000_000)
    agents = by_key(api, auth)
    assert agents["qualifier"]["estimated_cost_usd"] == "1.0000"
    assert agents["public_chat"]["estimated_cost_usd"] == "2.0000"
    assert agents["staff_assistant"]["estimated_cost_usd"] == "0.0000"


def test_another_organisations_usage_never_counts(api, auth, world, db_session) -> None:
    price(api, 3.0, 15.0)
    use(db_session, world, "beta.admin", "staff_assistant", 5_000_000, 5_000_000)
    assert by_key(api, auth)["staff_assistant"]["estimated_cost_usd"] == "0.0000"
    assert by_key(api, auth, "beta.admin")["staff_assistant"]["estimated_cost_usd"] == "90.0000"


def test_the_single_agent_read_has_the_cost_too(api, auth, world, db_session) -> None:
    price(api, 3.0, 15.0)
    use(db_session, world, "alpha.admin", "staff_assistant", 1_000_000, 0)
    one = ok(api.get(f"{URL}/staff_assistant", headers=auth("alpha.manager")))
    assert one["estimated_cost_usd"] == "3.0000"


def test_a_change_cannot_carry_a_cost_or_a_price(api, auth, world) -> None:
    for body in ({"estimated_cost_usd": "0.0000"}, {"enabled": True, "price_per_million": 1}):
        reply = api.patch(f"{URL}/staff_assistant", json=body, headers=auth("alpha.admin"))
        assert reply.status_code == 422, body


def test_who_may_not_read_agents_still_may_not_see_the_cost(api, auth, world) -> None:
    price(api, 3.0, 15.0)
    for who in ("alpha.agent1", "alpha.support", "alpha.customer"):
        assert code_of(api.get(URL, headers=auth(who)))[0] == 403
