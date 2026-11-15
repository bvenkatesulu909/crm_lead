# ruff: noqa: F811, F401 - fixtures are imported from other test files and used as parameters
"""Account research through the real API (ADR 0024, step DD4).

Real application, database, registry and permissions; only the model is the scripted fake the
module ships for local demos (one sentence per gathered fact, each citing its own record), or a
variant of it that cites things it was not given.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import bind_tenant
from app.modules.assistant.llm import ModelReply, ToolUse
from app.modules.deal_desk.llm import FakeDealDeskModel
from app.modules.deal_desk.models import AccountBrief
from app.modules.deal_desk.research_rules import TOOL
from app.modules.sales.models import Opportunity
from tests.db.conftest import bind_principal
from tests.db.test_approvals import ROLES, alpha, principal_for
from tests.db.test_quotes_api import Headers, World, api, auth, code_of, ok, world

URL = "/api/v1/account-research/briefs"


class Writer(FakeDealDeskModel):
    def __init__(self, extra: list[dict[str, Any]] | None = None, only_extra: bool = False) -> None:
        self.calls = 0
        self.extra = extra or []
        self.only_extra = only_extra

    def reply(self, **kw: Any) -> ModelReply:
        self.calls += 1
        made = super().reply(**kw)
        if not self.extra:
            return made
        sentences = [] if self.only_extra else list(made.tool_uses[0].input["sentences"])[:5]
        return ModelReply("", [ToolUse("w", TOOL, {"sentences": sentences + self.extra})])


def use(api: Any, model: Writer | None = None) -> Writer:
    chosen = model or Writer()
    api.app.state.deal_desk_model = chosen
    return chosen


def switch(api: Any, auth: Headers, on: bool = True) -> None:
    current = ok(api.get("/api/v1/agents/account_research", headers=auth("alpha.admin")))
    body: dict[str, Any] = {"enabled": on}
    if current.get("version") is not None:
        body["version"] = current["version"]
    ok(api.patch("/api/v1/agents/account_research", json=body, headers=auth("alpha.admin")))


def research(api: Any, auth: Headers, who: str, account: Any, **extra: Any) -> Any:
    return api.post(URL, json={"account_id": str(account), **extra}, headers=auth(who))


def cited(body: dict[str, Any]) -> set[str]:
    return {r["id"] for s in body["sentences"] for r in s["records"]}


def test_off_by_default_is_503_and_no_model_is_asked(api, auth, world) -> None:
    model = use(api)
    assert code_of(research(api, auth, "alpha.agent1", world.ids["A1"])) == (
        503,
        "agent_unavailable",
    )
    assert model.calls == 0


def test_a_brief_cites_only_what_the_asker_may_read(api, auth, world, db_session) -> None:
    # A deal of agent2 on agent1's account: agent1 may not read it, a manager may.
    manager = principal_for(world.users["alpha.manager"], ROLES["alpha.manager"])
    bind_principal(db_session, manager)
    hidden = Opportunity(
        tenant_id=alpha(world),
        name="Colleague's deal",
        account_id=world.ids["A1"],
        owner_id=world.users["alpha.agent2"].id,
        currency="EUR",
    )
    db_session.add(hidden)
    db_session.commit()
    switch(api, auth)

    use(api)
    mine = ok(research(api, auth, "alpha.agent1", world.ids["A1"]), 201)
    assert str(world.ids["O1"]) in cited(mine) and str(hidden.id) not in cited(mine)
    assert set(mine["gathered"]) == {"sales", "service", "conversations", "registry"}
    assert all(
        r["type"] in ("account", "opportunity", "contract")
        for s in mine["sentences"]
        for r in s["records"]
    )
    assert mine["dropped"] == 0

    theirs = ok(research(api, auth, "alpha.manager", world.ids["A1"]), 429)  # same account, hour
    assert theirs["code"] == "account_research_rate_limited"
    items = ok(
        api.get(URL, params={"account_id": str(world.ids["A1"])}, headers=auth("alpha.manager"))
    )["items"]
    assert [i["id"] for i in items] == [mine["id"]]


def test_support_may_research_an_account_it_reads(api, auth, world) -> None:
    switch(api, auth)
    use(api)
    assert ok(research(api, auth, "alpha.support", world.ids["A2"]), 201)["account_id"] == str(
        world.ids["A2"]
    )


@pytest.mark.parametrize("who", ["alpha.agent2", "beta.agent"])
def test_an_account_the_asker_may_not_read_is_404_before_any_model(api, auth, world, who) -> None:
    switch(api, auth)
    model = use(api)
    assert code_of(research(api, auth, who, world.ids["A1"]))[0] == 404
    assert (
        code_of(api.get(URL, params={"account_id": str(world.ids["A1"])}, headers=auth(who)))[0]
        == 404
    )
    assert model.calls == 0


def test_a_made_up_account_and_a_customer(api, auth, world) -> None:
    switch(api, auth)
    use(api)
    assert code_of(research(api, auth, "alpha.manager", uuid.uuid4()))[0] == 404
    assert code_of(research(api, auth, "alpha.customer", world.ids["A1"]))[0] == 403


@pytest.mark.parametrize("extra", [{"tenant_id": str(uuid.uuid4())}, {"sentences": []}])
def test_nothing_but_the_account_is_accepted(api, auth, world, extra) -> None:
    switch(api, auth)
    use(api)
    assert code_of(research(api, auth, "alpha.agent1", world.ids["A1"], **extra))[0] == 422


def test_sentences_citing_records_that_were_not_gathered_are_removed(api, auth, world) -> None:
    switch(api, auth)
    forged = [{"text": "The other account is bigger.", "record_ids": [str(world.ids["A2"])]}]
    use(api, Writer(forged))
    body = ok(research(api, auth, "alpha.agent1", world.ids["A1"]), 201)
    assert body["dropped"] == 1 and str(world.ids["A2"]) not in cited(body)
    assert "bigger" not in json.dumps(body)


def test_a_brief_with_no_sourced_sentence_stores_nothing(api, auth, world, db_session) -> None:
    switch(api, auth)
    forged = [{"text": "Invented.", "record_ids": [str(uuid.uuid4())]}]
    use(api, Writer(forged, only_extra=True))
    assert code_of(research(api, auth, "alpha.agent1", world.ids["A1"])) == (
        422,
        "account_research_invalid_answer",
    )
    bind_tenant(db_session, alpha(world))
    assert db_session.scalars(select(AccountBrief)).all() == []


def test_a_stored_brief_cannot_be_changed(api, auth, world, db_session) -> None:
    switch(api, auth)
    use(api)
    brief_id = ok(research(api, auth, "alpha.agent1", world.ids["A1"]), 201)["id"]
    bind_tenant(db_session, alpha(world))
    for statement in (
        text("UPDATE account_briefs SET dropped = 5 WHERE id = :id"),
        text("DELETE FROM account_briefs WHERE id = :id"),
    ):
        nested = db_session.begin_nested()
        with pytest.raises(DBAPIError):
            db_session.execute(statement, {"id": brief_id})
        nested.rollback()
